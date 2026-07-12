"""
倒计时最大化优化器 — 蒙特卡洛控制 + 精确动态规划 (Hybrid)

用于差分宇宙三张地图的倒计时最大化决策。
地图为固定小规模 DAG，每步移动后触发随机效果（1/6 等概率），
玩家可使用作弊（自选效果）或重投改变效果。

两种求解器：
  - MonteCarloOptimizer: ε-greedy MC 控制，不枚举状态、不预知未来
  - ExactCountdownDP: 精确 DP（用于小资源范围或精确分析）

默认流程 (run_full_analysis):
  Pass 1: MC 估计每张图的 W[(c,r)] 表（单图独立，零预知未来）
  Pass 2: MC 策略评估 + 联合资源分配（W 表反向归纳）

集成方式：
    from test.test_countdown_optimizer import optimize_map
    result = optimize_map(nodes, edges, start_idx, infectable_indices, cheat=1, reroll=2)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import hashlib
import heapq
import json
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from importing import load_img
from test_infectable_path import (match_multiple_targets, detect_infectable_nodes,
                                  build_rightward_graph, compute_start_point_from_crop,
                                  max_weight_path, display_matches)
from tool.utils.countdown_joint import (build_future_table)
load_img()
# ---- 计时工具 ----
_times = {}

def _timed(fn):
    """计时装饰器。独立函数写 `_times`，方法写 `self.timer`。"""
    name = fn.__name__
    def wrapper(*a, **kw):
        t0 = time.time()
        r = fn(*a, **kw)
        t = getattr(a[0], 'timer', None) if a else None
        if t is None:
            t = _times
        t[name] = t.get(name, 0) + time.time() - t0
        return r
    return wrapper

def _fmt(times, keys=None):
    if not times:
        return ''
    ks = keys if keys is not None else sorted(times)
    return '\n'.join(f'    {k:<25s} {times[k]:7.2f}s' for k in ks if k in times)
# ---- 效果定义 ----
EFFECT_SPREAD = 1       # 浇灌：每个传染节点感染一个随机邻居
EFFECT_BONUS = 2        # 为善：每个传染节点 +1 倒计时
EFFECT_ADJACENT = 3     # 对症：感染目标位置（下一步）的所有邻居
EFFECT_SELECT = 4       # 慈怀：手动选择一个节点感染
EFFECT_RANDOM_INFECT = 5  # 归心：随机感染一个未传染节点
EFFECT_NOTHING = 6      # 可憎：无事发生
ALL_EFFECTS = [EFFECT_SPREAD, EFFECT_BONUS, EFFECT_ADJACENT, EFFECT_SELECT, EFFECT_RANDOM_INFECT, EFFECT_NOTHING]
EFFECT_NAMES = {1: '浇灌', 2: '为善', 3: '对症', 4: '慈怀', 5: '归心', 6: '可憎'}
# 节点类型优先级：奖励 > 事件 > 冒险(探险) > 其它
_NODE_PRIORITY = {'reward': 0, 'reward2': 0, 'event': 1, 'adventure': 2}
def _node_priority(node_map: dict, node_idx: int) -> int:
    return _NODE_PRIORITY.get(node_map.get(node_idx, {}).get('name', ''), 3)
@dataclass(frozen=True)
class CountdownState:
    """不可变状态。

    effect_state 三态:
      "unlocked" — 未锁定（随机观察效果，可 cheat/reroll）
      "locked"   — 已锁定（效果已知，玩家可 keep/cheat/reroll，效果 CD 正常计算）
      "settled"  — 已结算（效果已在上张图生效，跳过效果阶段，不额外施加 CD/感染）

    observed_effect: 1~6 观察到的效果值，仅 effect_state != "unlocked" 时有效。
    """
    node_idx: int
    infected: int          # 位掩码
    countdown: int
    cheat_rem: int
    reroll_rem: int
    observed_effect: int = None   # 1~6，unlocked 时为 None
    effect_state: str = "unlocked"  # "unlocked" | "locked" | "settled"
class MapSimulator:
    """地图模拟器：管理节点/边/传染/列销毁等核心逻辑。"""
    def __init__(self, nodes: list, edges: dict, start_idx: int, infectable_indices: set):
        self.nodes = nodes
        self.edges = edges
        self.start_idx = start_idx
        self.node_map = {n['idx']: n for n in nodes}
        self._x = {n['idx']: n['cx'] for n in nodes}
        self._init_infectable = frozenset(infectable_indices)
        # 预计算每个节点的邻居（successors + predecessors）
        self._neighbors: dict[int, list] = {}
        for n in nodes:
            nb = set(edges.get(n['idx'], []))
            for src, dsts in edges.items():
                if n['idx'] in dsts:
                    nb.add(src)
            self._neighbors[n['idx']] = list(nb)
        # 预计算列索引（cx 聚簇，同列容差 30px）
        sorted_by_x = sorted(self.nodes, key=lambda n: n['cx'])
        self._col: dict[int, int] = {}
        col_idx = 0
        prev_cx = None
        for n in sorted_by_x:
            if prev_cx is not None and n['cx'] - prev_cx > 30:
                col_idx += 1
            self._col[n['idx']] = col_idx
            prev_cx = n['cx']
        # 预计算销毁掩码（基于列索引，同列及左侧全销毁，包含自身列）
        self._destroy_masks: dict[int, int] = {}
        for n in nodes:
            mask = 0
            ncol = self._col[n['idx']]
            for idx in range(len(nodes)):
                if self._col[idx] <= ncol:
                    mask |= (1 << idx)
            self._destroy_masks[n['idx']] = mask
        # 拓扑排序 (rightmost first)
        self._topo_order = self._topological_sort()
        self._ae_cache: dict[tuple, list] = {}  # apply_effect 结果缓存
    def _topological_sort(self) -> list:
        """返回节点索引的拓扑排序（右侧优先），用于反向 DP。"""
        indeg = {n['idx']: 0 for n in self.nodes}
        for src, dsts in self.edges.items():
            for dst in dsts:
                indeg[dst] = indeg.get(dst, 0) + 1
        # Kahn's algorithm, prefer larger x
        # 使用负 x 坐标作为优先级，使右侧节点先出队
        heap = [( -self._x.get(i, 0), i) for i, d in indeg.items() if d == 0]
        heapq.heapify(heap)
        order = []
        while heap:
            _, node = heapq.heappop(heap)
            order.append(node)
            for dst in self.edges.get(node, []):
                indeg[dst] -= 1
                if indeg[dst] == 0:
                    heapq.heappush(heap, (-self._x.get(dst, 0), dst))
        return order
    def initial_state(self, cheat: int, reroll: int, countdown: int = 0,
                      observed_effect: int = None,
                      effect_state: str = "unlocked") -> CountdownState:
        return CountdownState(node_idx=self.start_idx,
                              infected=sum(1 << i for i in self._init_infectable),
                              countdown=countdown, cheat_rem=cheat, reroll_rem=reroll,
                              observed_effect=observed_effect,
                              effect_state=effect_state)
    def is_terminal(self, state: CountdownState) -> bool:
        return state.node_idx not in self.edges or len(self.edges[state.node_idx]) == 0
    def _active_infected(self, infected_mask: int, destroyed_mask: int) -> int:
        return (infected_mask & ~destroyed_mask).bit_count()
    def _get_uninfected(self, infected_mask: int, destroyed_mask: int) -> list:
        return [n['idx'] for n in self.nodes
                if not ((destroyed_mask >> n['idx']) & 1)
                and not ((infected_mask >> n['idx']) & 1)]
    def apply_effect(self, infected_mask: int, effect: int, current_idx: int,
                     destroyed_mask: int, max_outcomes: int = None) -> list:
        """应用效果，返回所有可能的 (mask, cd_delta) 列表。

        max_outcomes: 最大采样数（None=全部）。用于 BFS 状态枚举时限制 SELECT/RANDOM_INFECT/SPREAD 的爆炸。
        """
        _ae_key = (infected_mask, effect, current_idx, destroyed_mask, max_outcomes)
        if _ae_key in self._ae_cache:
            return self._ae_cache[_ae_key]
        _result = [(infected_mask, 0)]
        if effect == EFFECT_BONUS:
            _result = [(infected_mask, self._active_infected(infected_mask, destroyed_mask))]
        elif effect == EFFECT_SPREAD:
            spread_sources, _ = self._build_spread_sources(infected_mask, destroyed_mask)
            if not spread_sources:
                _result = [(infected_mask, 0)]
            elif (full_results := self._cartesian_spread(infected_mask, spread_sources)) and max_outcomes is not None and len(full_results) > max_outcomes:
                rng = random.Random(infected_mask + current_idx * 10007)
                _result = [(m, 0) for m in rng.sample(full_results, min(max_outcomes, len(full_results)))]
            else:
                _result = [(m, 0) for m in full_results]
        elif effect == EFFECT_ADJACENT:
            new_mask = infected_mask
            for nb in self._neighbors.get(current_idx, []):
                if not ((destroyed_mask >> nb) & 1):
                    new_mask |= (1 << nb)
            _result = [(new_mask, 0)]
        elif effect == EFFECT_SELECT:
            if not (candidates := self._get_uninfected(infected_mask, destroyed_mask)):
                _result = [(infected_mask, 0)]
            else:
                if max_outcomes is not None and len(candidates) > max_outcomes:
                    rng = random.Random(infected_mask + current_idx * 10007)
                    candidates = rng.sample(candidates, max_outcomes)
                _result = [(infected_mask | (1 << c), 0) for c in candidates]
        elif effect == EFFECT_RANDOM_INFECT:
            if not (candidates := self._get_uninfected(infected_mask, destroyed_mask)):
                _result = [(infected_mask, 0)]
            else:
                if max_outcomes is not None and len(candidates) > max_outcomes:
                    rng = random.Random(infected_mask + current_idx * 10007 + 1)
                    candidates = rng.sample(candidates, max_outcomes)
                _result = [(infected_mask | (1 << c), 0) for c in candidates]
        self._ae_cache[_ae_key] = _result
        return _result
    def _cartesian_spread(self, base_mask: int, sources: list[list[int]]) -> list[int]:
        """递归计算浇灌的笛卡尔积。"""
        results = [base_mask]
        for choices in sources:
            results = [mask | (1 << choice) for mask in results for choice in choices]
        return results
    def _build_spread_sources(self, infected_mask: int, destroyed_mask: int) -> tuple:
        """返回 (spread_sources, est_product)。spread_sources 为每个已感染未销毁节点的未感染邻居列表。"""
        sources = []
        product = 1
        for idx in range(len(self.nodes)):
            if not ((infected_mask >> idx) & 1) or ((destroyed_mask >> idx) & 1):
                continue
            nb_uninf = [nb for nb in self._neighbors.get(idx, [])
                       if not ((infected_mask >> nb) & 1)
                       and not ((destroyed_mask >> nb) & 1)]
            if nb_uninf:
                sources.append(nb_uninf)
                product *= len(nb_uninf)
        return sources, product
    def move_delta(self, node_idx: int, infected_mask: int) -> int:
        """移动到此节点的倒计时变化（传染+1，否则-3）。"""
        return 1 if ((infected_mask >> node_idx) & 1) else -3
class MonteCarloOptimizer:
    """蒙特卡洛控制：通过大量随机 rollout 同时学习最优路径与效果决策。

    核心思想：不做状态枚举、不预知未来。每个步骤随机探索两个决策维度：
      1. 路径选择 — 走哪个后继节点（多分支 DAG）
      2. 效果决策 — keep / cheat(指定效果) / reroll

    Ex-post 建模：先观察随机效果 e，再基于 (状态+e) 选择 (路径+动作)。
    Q[(node, mask, c, r, observed_effect)] → (next_node, effect_decision) → [final_cd]
    """
    def __init__(self, sim: 'MapSimulator'):
        self.sim = sim
        # Q_effect[(state_key, observed_effect)][effect_decision] → [final_cd]
        #   effect_decision: 'keep' | 'reroll' | ('cheat', k)
        self.Q_effect: dict[tuple, dict[tuple, list[float]]] = defaultdict(
            lambda: defaultdict(list))
        # Q_path[(state_key, locked_effect)][next_node] → [final_cd]
        # locked_effect 始终是解析后的正整数值 (1~6)，不代表状态
        self.Q_path: dict[tuple, dict[int, list[float]]] = defaultdict(
            lambda: defaultdict(list))
        self._future_table: dict = None
        self._initial_observed_effect: int = None  # 首步观察到的效果 (1~6)，None 表示未观察
        self._initial_effect_state: str = "unlocked"  # "unlocked" | "locked" | "settled"
        self._ge_cache: dict = None  # eval 期贪心决策缓存: (sk, observed) → eff
        self.timer = {}
        self._train_times = {}
    # ------------------------------------------------------------------
    # 键函数
    # ------------------------------------------------------------------
    @staticmethod
    def _state_key(state: CountdownState) -> tuple:
        return (state.node_idx, state.infected, state.cheat_rem, state.reroll_rem)
    @staticmethod
    def _effect_action_key(effect_decision) -> tuple:
        """效果决策键：'keep' | 'reroll' | ('cheat', k)。"""
        return (('cheat', effect_decision[1]) if isinstance(effect_decision, tuple) and effect_decision[0] == 'cheat'
                else ('reroll',) if effect_decision == 'reroll'
                else ('keep',))
    def _marginal_cheat(self, sk: tuple, c: int = None, r: int = None) -> float:
        """消耗 1 cheat 的边际成本（DP W 表优先，回退 future_table）。"""
        if c is None:
            c = sk[2]
        if r is None:
            r = sk[3]
        if c <= 0:
            return 0.02
        node, mask = sk[0], sk[1]
        if hasattr(self, '_dp_w') and self._dp_w is not None:
            dp_c = self._dp_w.get((node, mask, c, r))
            dp_c1 = self._dp_w.get((node, mask, c - 1, r))
            if dp_c is not None and dp_c1 is not None:
                return max(dp_c - dp_c1, 0.02)
        if self._future_table:
            ft_c = self._future_table.get((c, r), 0.0)
            ft_c1 = self._future_table.get((c - 1, r), 0.0)
            return max(ft_c - ft_c1, 0.02)
        return 0.02
    def _marginal_reroll(self, sk: tuple, c: int = None, r: int = None) -> float:
        """消耗 1 reroll 的边际成本（DP W 表优先，回退 future_table）。"""
        if c is None:
            c = sk[2]
        if r is None:
            r = sk[3]
        if r <= 0:
            return 0.02
        node, mask = sk[0], sk[1]
        if hasattr(self, '_dp_w') and self._dp_w is not None:
            dp_r = self._dp_w.get((node, mask, c, r))
            dp_r1 = self._dp_w.get((node, mask, c, r - 1))
            if dp_r is not None and dp_r1 is not None:
                return max(dp_r - dp_r1, 0.02)
        if self._future_table:
            ft_r = self._future_table.get((c, r), 0.0)
            ft_r1 = self._future_table.get((c, r - 1), 0.0)
            return max(ft_r - ft_r1, 0.02)
        return 0.02
    # ------------------------------------------------------------------
    # 动作空间
    # ------------------------------------------------------------------
    def _get_effect_actions(self, state: CountdownState) -> list:
        """效果决策选项：keep / cheat(k) / reroll。"""
        actions = ['keep']
        if state.cheat_rem > 0:
            actions.extend(('cheat', e) for e in ALL_EFFECTS)
        if state.reroll_rem > 0:
            actions.append('reroll')
        return actions
    # ------------------------------------------------------------------
    # 状态转移
    # ------------------------------------------------------------------
    @_timed
    def _apply_and_move(self, state: CountdownState,
                        effect: int, next_node: int,
                        cost_c: int, cost_r: int,
                        rng: random.Random,
                        skip_effect_apply: bool = False) -> 'CountdownState':
        """应用已锁定效果，移动，列销毁。不再处理效果决策逻辑。"""
        if skip_effect_apply:
            new_mask, cd_delta = state.infected, 0
        else:
            node = state.node_idx
            eff_results = self.sim.apply_effect(
                state.infected, effect,
                next_node if effect == EFFECT_ADJACENT else node,
                (self.sim._destroy_masks[next_node]
                 if effect == EFFECT_ADJACENT else self.sim._destroy_masks[node]))
            if len(eff_results) == 1:
                new_mask, cd_delta = eff_results[0]
            elif effect == EFFECT_SELECT:
                new_mask, cd_delta = self._pick_best_select(
                    eff_results, state, next_node, cost_c, cost_r, rng)
            else:
                new_mask, cd_delta = eff_results[rng.randint(0, len(eff_results) - 1)]
        return CountdownState(
            node_idx=next_node,
            infected=new_mask & ~self.sim._destroy_masks[next_node],
            countdown=state.countdown + cd_delta + self.sim.move_delta(next_node, new_mask),
            cheat_rem=state.cheat_rem - cost_c,
            reroll_rem=state.reroll_rem - cost_r,
        )
    def _pick_best_select(self, candidates, state, next_node,
                          cost_c, cost_r, rng):
        """SELECT 效果：玩家选择最优感染目标。DP 优先，否则优先感染目的地。"""
        c_after = state.cheat_rem - cost_c
        r_after = state.reroll_rem - cost_r
        dest_destroyed = self.sim._destroy_masks[next_node]
        if hasattr(self, '_dp_w') and self._dp_w is not None:
            best_val = float('-inf')
            best = candidates[0]
            for new_mask, cd_delta in candidates:
                final_mask = new_mask & ~dest_destroyed
                md = self.sim.move_delta(next_node, new_mask)
                future = self._dp_w.get((next_node, final_mask, c_after, r_after))
                if future is not None:
                    val = cd_delta + md + future
                    if val > best_val:
                        best_val = val
                        best = (new_mask, cd_delta)
            return best
        # 无 DP：优先感染目的地（move_delta 从 -3 变 +1）
        for new_mask, cd_delta in candidates:
            if (new_mask >> next_node) & 1:
                return (new_mask, cd_delta)
        return candidates[rng.randint(0, len(candidates) - 1)]
    def _apply_and_move_best(self, dp: 'ExactCountdownDP', state: CountdownState,
                              effect: int, next_node: int, cost_c: int,
                              skip_effect_apply: bool = False) -> 'CountdownState':
        """与 _apply_and_move 相同，但当效果有多个结果时选 DP-W 最优者。
        用于热启动 rollout，确保随机效果按最优方向发生。
        """
        if skip_effect_apply:
            new_mask, cd_delta = state.infected, 0
        else:
            eff_results = self.sim.apply_effect(
                state.infected, effect,
                next_node if effect == EFFECT_ADJACENT else state.node_idx,
                (self.sim._destroy_masks[next_node]
                 if effect == EFFECT_ADJACENT else self.sim._destroy_masks[state.node_idx]))
            if len(eff_results) == 1:
                new_mask, cd_delta = eff_results[0]
            else:
                c_dp = min(state.cheat_rem - cost_c, dp._dp_max_c)
                r_dp = min(state.reroll_rem, dp._dp_max_r)
                destroyed_nn = self.sim._destroy_masks[next_node]
                new_mask, cd_delta = max(eff_results, key=lambda p: (
                    p[1] + self.sim.move_delta(next_node, p[0])
                    + dp.W.get((next_node, p[0] & ~destroyed_nn, c_dp, r_dp), float('-inf'))))
        return CountdownState(
            node_idx=next_node,
            infected=new_mask & ~self.sim._destroy_masks[next_node],
            countdown=state.countdown + cd_delta + self.sim.move_delta(next_node, new_mask),
            cheat_rem=state.cheat_rem - cost_c,
            reroll_rem=state.reroll_rem,
        )
    # ------------------------------------------------------------------
    # 训练
    # ------------------------------------------------------------------
    def train(self, cheat: int = 5, reroll: int = 10,
              n_rollouts: int = 20000, epsilon: float = 0.3,
              future_table: dict = None) -> dict:
        """ε-greedy MC 控制，含多段 reroll 内层循环。

        每步：
          观察效果 e → [reroll 循环: keep/cheat/reroll]
          → 锁定效果 → 选路径 → 应用效果+移动+列销毁。
        """
        self._future_table = future_table
        self._ge_cache = None  # 训练期 Q 表在变，禁用贪心决策缓存
        rng = random.Random(42)
        self.timer = {}
        for ep in range(n_rollouts):
            state = self.sim.initial_state(cheat, reroll, 0,
                                           observed_effect=self._initial_observed_effect,
                                           effect_state=self._initial_effect_state)
            eff_trace: list[tuple] = []   # [(sk, observed, eff_ak)]
            path_trace: list[tuple] = []  # [(sk, locked_effect, nn)]
            ε = epsilon  # 提前定义，供路径阶段使用
            while not self.sim.is_terminal(state):
                if not (next_nodes := self.sim.edges.get(state.node_idx, [])):
                    break
                # 首步可能已结算（效果在上张图已施加）
                if state.effect_state == "settled":
                    locked_effect = state.observed_effect
                    cost_c = 0
                    skip_effect = True
                else:
                    skip_effect = False
                    observed = state.observed_effect if state.effect_state == "locked" else rng.randint(1, 6)
                    # ---- 效果阶段 (reroll 循环) ----
                    while True:
                        sk = self._state_key(state)
                        eff_actions = self._get_effect_actions(state)
                        eff = (self._random_effect_action(eff_actions, rng)
                               if ε and rng.random() < ε
                               else self._greedy_effect(sk, observed, eff_actions, rng))
                        eff_ak = self._effect_action_key(eff)
                        if eff == 'reroll':
                            eff_trace.append((sk, observed, eff_ak))
                            state = CountdownState(
                                node_idx=state.node_idx, infected=state.infected,
                                countdown=state.countdown,
                                cheat_rem=state.cheat_rem,
                                reroll_rem=state.reroll_rem - 1)
                            observed = rng.randint(1, 6)
                            continue  # 回到效果阶段
                        # keep 或 cheat：锁定效果
                        locked_effect, cost_c = (observed, 0) if eff == 'keep' else (eff[1], 1)
                        eff_trace.append((sk, observed, eff_ak))
                        break
                # ---- 路径阶段 ----
                sk_locked = self._state_key(state)
                nn = (next_nodes[rng.randint(0, len(next_nodes) - 1)]
                      if ε and rng.random() < ε
                      else self._greedy_path(sk_locked, locked_effect, next_nodes, rng))
                path_trace.append((sk_locked, locked_effect, nn))
                # 转移
                state = self._apply_and_move(state, locked_effect, nn, cost_c, 0, rng,
                                              skip_effect_apply=skip_effect)
            # Episode 结束：回补
            t0_bp = time.time()
            final_cd = state.countdown + (future_table.get((state.cheat_rem, state.reroll_rem), 0.0) if future_table else 0)
            for sk, obs, eff_ak in eff_trace:
                vals = self.Q_effect[(sk, obs)][eff_ak]
                vals.append(final_cd)
                if len(vals) > 200:
                    vals.pop(0)
            for sk, locked_e, nn in path_trace:
                vals = self.Q_path[(sk, locked_e)][nn]
                vals.append(final_cd)
                if len(vals) > 200:
                    vals.pop(0)
            self.timer['backprop'] = self.timer.get('backprop', 0) + time.time() - t0_bp
            # 自适应清空 _reroll_value 缓存：前期频繁（Q 变化快），后期稀疏
            _rv_clear_interval = 500 if ep < 3000 else 2000
            if hasattr(self, '_rv_cache') and ep % _rv_clear_interval == _rv_clear_interval - 1:
                self._rv_cache.clear()
        self._train_times = dict(self.timer)
        total_q = sum(len(acts) for acts in self.Q_effect.values())
        total_q += sum(len(acts) for acts in self.Q_path.values())
        return {
            'q_entries': total_q,
            'states_visited': len(self.Q_effect) + len(self.Q_path),
        }
    def warm_start_from_dp(self, dp: 'ExactCountdownDP', cheat: int, reroll: int,
                           n_rollouts: int = 2000, epsilon: float = 0.1):
        """使用 DP 策略 rollout 填充 Q 表，打破冷启动死循环。

        DP 知晓全局最优策略。用其引导 rollout 可确保 Q_path 对长路径节点
        （如 adventure#1）获得合理高估值，避免 MC 从零探索时永远选短路径。
        """
        rng = random.Random(12345)
        self._future_table = None
        # 存储 DP 的 W 表，供 _reroll_value 精确查询
        self._dp_w = dp.W
        self._dp_max_c = dp._dp_max_c
        self._dp_max_r = dp._dp_max_r
        self._dpev_cache = {}  # (node, mask, effect, c, r) → float|None
        self._rv_cache = {}    # (node, mask, c, r) → float, 每500ep清空
        def _eval_effect_path(node, mask, effect, nn, c_dp, r_dp, destroyed):
            destroyed_nn = self.sim._destroy_masks[nn]
            eff_node = nn if effect == EFFECT_ADJACENT else node
            eff_destroyed = destroyed_nn if effect == EFFECT_ADJACENT else destroyed
            results = self.sim.apply_effect(mask, effect, eff_node, eff_destroyed)
            best = float('-inf')
            for new_mask, cd_delta in results:
                final_mask = new_mask & ~destroyed_nn
                md = self.sim.move_delta(nn, new_mask)
                future = dp.W.get((nn, final_mask, c_dp, r_dp), float('-inf'))
                val = cd_delta + md + future
                if val > best:
                    best = val
            return best
        for ep in range(n_rollouts):
            state = self.sim.initial_state(cheat, reroll, 0,
                                           observed_effect=self._initial_observed_effect,
                                           effect_state=self._initial_effect_state)
            eff_trace: list[tuple] = []
            path_trace: list[tuple] = []
            while not self.sim.is_terminal(state):
                if not (next_nodes := self.sim.edges.get(state.node_idx, [])):
                    break
                # 首步可能已结算
                if state.effect_state == "settled":
                    locked_effect = state.observed_effect
                    cost_c = 0
                    skip_effect = True
                else:
                    skip_effect = False
                    observed = state.observed_effect if state.effect_state == "locked" else rng.randint(1, 6)
                    # ---- 效果阶段 (DP-guided ε-greedy) ----
                    while True:
                        sk = self._state_key(state)
                        eff_actions = self._get_effect_actions(state)
                        if rng.random() < epsilon:
                            eff = self._random_effect_action(eff_actions, rng)
                        else:
                            _node, _mask, _c, _r = state.node_idx, state.infected, state.cheat_rem, state.reroll_rem
                            _c_dp = min(_c, dp._dp_max_c)
                            _r_dp = min(_r, dp._dp_max_r)
                            _nn_list = self.sim.edges.get(_node, [])
                            _destroyed = self.sim._destroy_masks[_node]
                            _best_val = float('-inf')
                            _best_eff = 'keep'
                            for _nn in _nn_list:
                                _val = _eval_effect_path(_node, _mask, observed, _nn, _c_dp, _r_dp, _destroyed)
                                if _val > _best_val:
                                    _best_val = _val
                                    _best_eff = 'keep'
                            if _c > 0:
                                _c_dp_cheat = min(_c - 1, dp._dp_max_c)
                                for k in ALL_EFFECTS:
                                    for _nn in _nn_list:
                                        _val = _eval_effect_path(_node, _mask, k, _nn, _c_dp_cheat, _r_dp, _destroyed)
                                        if _val > _best_val:
                                            _best_val = _val
                                            _best_eff = ('cheat', k)
                            if _r > 0:
                                _rv = dp.W.get((_node, _mask, _c_dp, min(_r - 1, dp._dp_max_r)))
                                if _rv is not None and _rv > _best_val:
                                    _best_val = _rv
                                    _best_eff = 'reroll'
                            eff = self._fallback_effect(state, observed, rng) if _best_val == float('-inf') else _best_eff
                        eff_ak = self._effect_action_key(eff)
                        if eff == 'reroll':
                            eff_trace.append((sk, observed, eff_ak))
                            state = CountdownState(
                                node_idx=state.node_idx, infected=state.infected,
                                countdown=state.countdown,
                                cheat_rem=state.cheat_rem,
                                reroll_rem=state.reroll_rem - 1)
                            observed = rng.randint(1, 6)
                            continue
                        locked_effect, cost_c = (observed, 0) if eff == 'keep' else (eff[1], 1)
                        eff_trace.append((sk, observed, eff_ak))
                        break
                # ---- 路径阶段 (DP-guided ε-greedy) ----
                sk_locked = self._state_key(state)
                if rng.random() < epsilon:
                    nn = next_nodes[rng.randint(0, len(next_nodes) - 1)]
                else:
                    _node, _mask, _c, _r = state.node_idx, state.infected, state.cheat_rem, state.reroll_rem
                    _c_dp = min(_c, dp._dp_max_c)
                    _r_dp = min(_r, dp._dp_max_r)
                    _destroyed = self.sim._destroy_masks[_node]
                    _best_val = float('-inf')
                    _best_nn = next_nodes[0]
                    for _nn in next_nodes:
                        _val = _eval_effect_path(_node, _mask, locked_effect, _nn, _c_dp, _r_dp, _destroyed)
                        if _val > _best_val:
                            _best_val = _val
                            _best_nn = _nn
                    nn = self._fallback_path(state, locked_effect, next_nodes, rng) if _best_val == float('-inf') else _best_nn
                path_trace.append((sk_locked, locked_effect, nn))
                # 转移：选 DP 最优结果（非随机），确保热启动 rollout 达到 DP 预测值
                state = self._apply_and_move_best(dp, state, locked_effect, nn, cost_c,
                                                   skip_effect_apply=skip_effect)
            # 回补
            final_cd = state.countdown
            for sk, obs, eff_ak in eff_trace:
                vals = self.Q_effect[(sk, obs)][eff_ak]
                vals.append(final_cd)
                if len(vals) > 200:
                    vals.pop(0)
            for sk, locked_e, nn in path_trace:
                vals = self.Q_path[(sk, locked_e)][nn]
                vals.append(final_cd)
                if len(vals) > 200:
                    vals.pop(0)
    @staticmethod
    def _random_effect_action(eff_actions: list, rng: random.Random):
        """探索时等权重随机选效果决策。"""
        dec_types = list(set(
            'keep' if a == 'keep' else
            'cheat' if isinstance(a, tuple) and a[0] == 'cheat' else
            'reroll' for a in eff_actions))
        dec = dec_types[rng.randint(0, len(dec_types) - 1)]
        if dec == 'keep':
            return 'keep'
        elif dec == 'cheat':
            cheat_opts = [a for a in eff_actions if isinstance(a, tuple) and a[0] == 'cheat']
            return cheat_opts[rng.randint(0, len(cheat_opts) - 1)]
        else:
            return 'reroll'
    # ------------------------------------------------------------------
    # 贪心选择
    # ------------------------------------------------------------------
    @_timed
    def _greedy_effect(self, sk: tuple, observed: int,
                       actions: list, rng: random.Random,
                       min_samples: int = 5) -> str:
        """选最优效果决策。reroll 值由 _reroll_value 自底向上计算。

        cheat 到与 observed 相同效果时，不从独立 Q 样本估算（结果与 keep
        完全相同，独立采样引入的统计噪声会导致"花钱买相同效果"的荒谬结论），
        而是直接从 keep 值扣除 cheat 边际成本。
        """
        if self._ge_cache is not None:
            cached = self._ge_cache.get((sk, observed))
            if cached is not None:
                return cached
        infected_mask = sk[1]
        infected_count = bin(infected_mask).count('1')
        def _effect_heuristic(eff) -> float:
            e = observed if eff == 'keep' else eff[1] if isinstance(eff, tuple) and eff[0] == 'cheat' else None
            return 0.0 if e is None else float(infected_count) if e == EFFECT_BONUS else 1.5 if e == EFFECT_ADJACENT else 2.0 if e == EFFECT_SELECT else 0.5 if e in (EFFECT_SPREAD, EFFECT_RANDOM_INFECT) else 0.0
        c, r = sk[2], sk[3]
        marginal_cheat = self._marginal_cheat(sk)
        marginal_reroll = self._marginal_reroll(sk)
        def _compute_eff_score(eff) -> float:
            """计算非 reroll 动作的评分。"""
            eff_ak = self._effect_action_key(eff)
            vals = self.Q_effect[(sk, observed)].get(eff_ak, [])
            n = len(vals)
            avg = sum(vals) / n if vals else 0.0
            if n >= min_samples:
                score = avg
            elif n > 0:
                h = _effect_heuristic(eff)
                score = max(avg, h) - (min_samples - n) / max(min_samples, 1) * 2.0
            else:
                score = _effect_heuristic(eff)
            if isinstance(eff, tuple) and eff[0] == 'cheat':
                score -= marginal_cheat
            return score
        # keep_score: DP 优先（与 cheat 同一尺度），回退 Q_effect
        keep_score = (v if (v := self._dp_effect_value(sk[0], sk[1], observed, c, r)) is not None
                      else _compute_eff_score('keep'))
        best_score, best = (keep_score, 'keep') if keep_score > float('-inf') else (float('-inf'), 'keep')
        # cheat(k) — 直接用 ALL_EFFECTS 迭代，免去 isinstance 开销
        if c > 0:
            for target in ALL_EFFECTS:
                if target == observed:
                    score = keep_score - marginal_cheat if keep_score > float('-inf') else float('-inf')
                else:
                    if (dp_val := self._dp_cheat_value(sk[0], sk[1], target, c, r)) is not None:
                        score = dp_val
                    else:
                        t_keep = self.Q_effect.get((sk, target), {}).get(('keep',), [])
                        score = (sum(t_keep) / len(t_keep) - marginal_cheat if len(t_keep) >= min_samples
                                 else max(sum(t_keep) / len(t_keep), _effect_heuristic(('cheat', target))) - marginal_cheat if t_keep
                                 else _effect_heuristic(('cheat', target)) - marginal_cheat)
                if score > best_score + 1e-9:
                    best_score = score
                    best = ('cheat', target)
        # reroll — 独立处理，避免在循环中用字符串比较
        if r > 0:
            raw_rv = self._reroll_value(sk, min_samples)
            score = raw_rv - marginal_reroll
            if score <= 0.0:
                score = 1.0 if best_score <= 0 else best_score - 0.5
            if score > best_score + 1e-9:
                best_score = score
                best = 'reroll'
        if self._ge_cache is not None:
            self._ge_cache[(sk, observed)] = best
        return best
    @_timed
    def _reroll_value(self, sk: tuple, min_samples: int = 5) -> float:
        """reroll 期望值 — 自底向上从 Q_effect (MC) 递推，不含 cheat。

        从 r'=1 到 r 自底向上递推:
          reroll_val[r'] = avg over 6 effects of max(keep_val_at_r', reroll_val[r'-1])
        每层 r' 使用该层资源水平 (c, r') 下的 Q 值，确保递推与封顶在同一尺度。
        """
        if sk[3] <= 0:
            return float('-inf')
        node, mask, c, r = sk[0], sk[1], sk[2], sk[3]
        rv_key = (node, mask, c, r)
        if hasattr(self, '_rv_cache') and rv_key in self._rv_cache:
            return self._rv_cache[rv_key]
        # 1) 收集各 effect 的 keep 均值（必须满足 min_samples）
        keep_vals: dict[int, float] = {}
        sufficient_count = 0
        for e in ALL_EFFECTS:
            qe = self.Q_effect.get(((node, mask, c, r), e))
            kv = qe.get(('keep',), []) if qe else []
            if len(kv) >= min_samples:
                keep_vals[e] = sum(kv) / len(kv)
                sufficient_count += 1
        # 至少需要 3 个效果有充足数据，否则 reroll 估值不可靠
        if sufficient_count < 3:
            return 0.0
        # 2) 缺失效果用已有均值填补（而非 0.0）
        if sufficient_count < 6:
            existing_avg = sum(keep_vals.values()) / sufficient_count
            for e in ALL_EFFECTS:
                if e not in keep_vals:
                    keep_vals[e] = existing_avg
        # 3) 缓存各 rp 级别的 keep 值（懒加载），缺失时回退到原始 r 级别
        _keep_cache: dict[int, dict[int, float]] = {r: keep_vals}
        def _get_keep_at(rp: int) -> dict[int, float]:
            if rp not in _keep_cache:
                vals: dict[int, float] = {}
                for e in ALL_EFFECTS:
                    qe = self.Q_effect.get(((node, mask, c, rp), e))
                    kv = qe.get(('keep',), []) if qe else []
                    if len(kv) >= min_samples:
                        vals[e] = sum(kv) / len(kv)
                if len(vals) >= 3:
                    if len(vals) < 6:
                        avg = sum(vals.values()) / len(vals)
                        for e in ALL_EFFECTS:
                            if e not in vals:
                                vals[e] = avg
                    _keep_cache[rp] = vals
                else:
                    _keep_cache[rp] = keep_vals  # 数据不足时回退
            return _keep_cache[rp]
        # 4) r'=1..r 自底向上递推，每层使用该层自身的 keep 值和封顶
        reroll_vals: dict[int, float] = {}
        for rp in range(1, r + 1):
            keep = _get_keep_at(rp)
            max_keep_at_rp = max(keep.values())
            total = 0.0
            for e_new in ALL_EFFECTS:
                k_val = keep.get(e_new)
                if k_val is None:
                    k_val = sum(keep.values()) / len(keep)
                best = k_val
                if rp > 1 and rp - 1 in reroll_vals:
                    if reroll_vals[rp - 1] > best:
                        best = reroll_vals[rp - 1]
                total += best
            reroll_vals[rp] = min(total / 6.0, max_keep_at_rp)
        result = reroll_vals.get(r, 0.0)
        if hasattr(self, '_rv_cache'):
            self._rv_cache[rv_key] = result
        return result
    @_timed
    def _dp_effect_value(self, node: int, mask: int, effect: int,
                          c: int, r: int) -> float:
        """用 DP W 表精确计算「选定效果 + 最优移动」的期望未来 CD 增量。"""
        cache_key = (node, mask, effect, c, r)
        if hasattr(self, '_dpev_cache') and cache_key in self._dpev_cache:
            return self._dpev_cache[cache_key]
        if not hasattr(self, '_dp_w') or self._dp_w is None:
            result = None
        else:
            if not (next_nodes := self.sim.edges.get(node, [])):
                result = None
            else:
                destroyed = self.sim._destroy_masks.get(node, 0)
                if effect == EFFECT_ADJACENT:
                    best = max((self.sim.move_delta(nn, nm) + future
                               for nn in next_nodes
                               for dd in [self.sim._destroy_masks[nn]]
                               for nm in [(mask & ~dd) | sum((1 << nb for nb in self.sim._neighbors.get(nn, []) if not ((dd >> nb) & 1)), 0)]
                               for future in [self._dp_w.get((nn, nm, c, r))]
                               if future is not None), default=float('-inf'))
                    result = best if best > float('-inf') else None
                elif effect in (EFFECT_BONUS, EFFECT_NOTHING):
                    new_mask, cd_delta = self.sim.apply_effect(mask, effect, node, destroyed)[0]
                    best = max((cd_delta + self.sim.move_delta(nn, new_mask) + future
                               for nn in next_nodes
                               for dd in [self.sim._destroy_masks[nn]]
                               for future in [self._dp_w.get((nn, new_mask & ~dd, c, r))]
                               if future is not None), default=float('-inf'))
                    result = best if best > float('-inf') else None
                else:
                    eff_results = self.sim.apply_effect(mask, effect, node, destroyed,
                                                         max_outcomes=300)
                    if effect == EFFECT_SELECT or len(eff_results) == 1:
                        best = max((cd_delta + self.sim.move_delta(nn, new_mask) + future
                                   for new_mask, cd_delta in eff_results
                                   for nn in next_nodes
                                   for dd in [self.sim._destroy_masks[nn]]
                                   for future in [self._dp_w.get((nn, new_mask & ~dd, c, r))]
                                   if future is not None), default=float('-inf'))
                        result = best if best > float('-inf') else None
                    else:
                        vals = [max((cd_delta + self.sim.move_delta(nn, new_mask) + future
                                    for nn in next_nodes
                                    for dd in [self.sim._destroy_masks[nn]]
                                    for future in [self._dp_w.get((nn, new_mask & ~dd, c, r))]
                                    if future is not None), default=None)
                               for new_mask, cd_delta in eff_results]
                        vals = [v for v in vals if v is not None]
                        result = sum(vals) / len(vals) if vals else None
        if hasattr(self, '_dpev_cache'):
            self._dpev_cache[cache_key] = result
        return result
    def _dp_cheat_value(self, node: int, mask: int, target_effect: int,
                         c: int, r: int) -> float:
        """cheat→target_effect 的价值：同 _dp_effect_value 但资源减 1 cheat。"""
        return None if c <= 0 else self._dp_effect_value(node, mask, target_effect, c - 1, r)
    @_timed
    def _greedy_path(self, sk: tuple, locked_effect: int,
                     next_nodes: list, rng: random.Random,
                     min_samples: int = 5) -> int:
        """选最优路径（效果已锁定）。

        无 Q 数据时用启发式：已感染 +1、未感染 -3。否则少量幸运样本会使
        烂节点（-3）打败好节点（+1），策略永远学不到正确路径。
        """
        infected_mask = sk[1]
        best_score = float('-inf')
        best = next_nodes[0]
        for nn in next_nodes:
            vals = self.Q_path[(sk, locked_effect)].get(nn, [])
            n, avg = len(vals), (sum(vals) / len(vals) if vals else 0.0)
            score = (avg if n >= min_samples
                     else max(avg, 1.0 if (infected_mask >> nn) & 1 else 0.0)
                          - (min_samples - n) / max(min_samples, 1) * 2.0 if n > 0
                     else 1.0 if (infected_mask >> nn) & 1 else 0.0)
            if score > best_score + 1e-9:
                best_score, best = score, nn
            elif abs(score - best_score) <= 1e-9:
                nn_inf = (infected_mask >> nn) & 1
                best_inf = (infected_mask >> best) & 1
                if nn_inf > best_inf or (nn_inf == best_inf and _node_priority(self.sim.node_map, nn) < _node_priority(self.sim.node_map, best)):
                    best = nn
        return best
    def _greedy_rollout(self, state: CountdownState, rng: random.Random) -> float:
        """从 state 出发，用贪心策略走完全程，返回最终 CD。"""
        while not self.sim.is_terminal(state):
            if not (next_nodes := self.sim.edges.get(state.node_idx, [])):
                break
            if state.effect_state == "settled":
                locked, cost_c, skip_eff = state.observed_effect, 0, True
            else:
                skip_eff = False
                observed = state.observed_effect if state.effect_state == "locked" else rng.randint(1, 6)
                while True:
                    sk = self._state_key(state)
                    eff = self._greedy_effect(sk, observed, self._get_effect_actions(state), rng)
                    if eff == 'reroll':
                        state = CountdownState(node_idx=state.node_idx, infected=state.infected,
                                               countdown=state.countdown, cheat_rem=state.cheat_rem,
                                               reroll_rem=state.reroll_rem - 1)
                        observed = rng.randint(1, 6)
                        continue
                    locked, cost_c = (observed, 0) if eff == 'keep' else (eff[1], 1)
                    break
            sk_locked = self._state_key(state)
            nn = self._greedy_path(sk_locked, locked, next_nodes, rng)
            state = self._apply_and_move(state, locked, nn, cost_c, 0, rng,
                                          skip_effect_apply=skip_eff)
        return float(state.countdown)
    # ------------------------------------------------------------------
    # 策略查询
    # ------------------------------------------------------------------
    def get_action(self, state: CountdownState):
        """返回 (effect_decision, next_node) 或 None。从 state.effect_state 推导分析模式。"""
        if not (next_nodes := self.sim.edges.get(state.node_idx, [])):
            return None
        sk = self._state_key(state)
        # 已结算：只选路
        if state.effect_state == "settled":
            locked = state.observed_effect
            nn = self._greedy_path(sk, locked, next_nodes, random.Random(0))
            return (None, nn)
        # 已锁定：用锁定的效果作为 observed，允许 keep/cheat/reroll
        if state.effect_state == "locked":
            if state.observed_effect == EFFECT_SELECT:
                destroyed = self.sim._destroy_masks[state.node_idx]
                next_set = set(next_nodes)
                candidates = [idx for idx in range(len(self.sim.nodes))
                              if not ((state.infected >> idx) & 1)
                              and not ((destroyed >> idx) & 1)
                              and idx not in next_set]
                if not candidates:
                    target, nn = None, self._greedy_path(self._state_key(state), EFFECT_SELECT, next_nodes, random.Random(0))
                else:
                    best_val = float('-inf')
                    best_target = candidates[0]
                    best_nn = next_nodes[0]
                    for target in candidates:
                        new_infected = state.infected | (1 << target)
                        for _nn in next_nodes:
                            move_d = self.sim.move_delta(_nn, new_infected)
                            final_infected = new_infected & ~self.sim._destroy_masks[_nn]
                            ns = CountdownState(
                                node_idx=_nn, infected=final_infected,
                                countdown=state.countdown + move_d,
                                cheat_rem=state.cheat_rem, reroll_rem=state.reroll_rem)
                            total = 0.0
                            _rng = random.Random(42 + target * 100 + _nn)
                            for _ in range(50):
                                total += self._greedy_rollout(ns, _rng)
                            avg = total / 50.0
                            if self._future_table:
                                avg += self._future_table.get(
                                    (state.cheat_rem, state.reroll_rem), 0.0)
                            if avg > best_val + 1e-9:
                                best_val = avg
                                best_target = target
                                best_nn = _nn
                    target, nn = best_target, best_nn
                return (target, nn)
            obs = state.observed_effect
            eff = self._greedy_effect(sk, obs, self._get_effect_actions(state), random.Random(0))
            locked = (obs if eff == 'keep'
                      else eff[1] if isinstance(eff, tuple)
                      else self._best_effect_after_reroll(sk, random.Random(0)))
            return (eff, self._greedy_path(sk, locked, next_nodes, random.Random(0)))
        # 未锁定 → 遍历 6 种效果，取 ex-ante 最优
        marginal_cheat = self._marginal_cheat(sk)
        best_eff, best_nn = None, None
        best_avg = float('-inf')
        for obs in ALL_EFFECTS:
            eff = self._greedy_effect(sk, obs, self._get_effect_actions(state),
                                      random.Random(0))
            if eff == 'reroll':
                # reroll：用 reroll 后期望效果 + 最优路径
                locked = self._best_effect_after_reroll(sk, random.Random(0))
                if locked is None:
                    continue
                nn = self._greedy_path(sk, locked, next_nodes, random.Random(0))
                avg = self._reroll_value(sk)
            elif isinstance(eff, tuple) and eff[0] == 'cheat':
                locked = eff[1]
                nn = self._greedy_path(sk, locked, next_nodes, random.Random(0))
                vals = self.Q_path[(sk, locked)].get(nn, [])
                avg = (sum(vals) / len(vals) if vals else 0.0) - marginal_cheat
            else:  # keep
                locked = obs
                nn = self._greedy_path(sk, locked, next_nodes, random.Random(0))
                vals = self.Q_path[(sk, locked)].get(nn, [])
                avg = sum(vals) / len(vals) if vals else 0.0
            if avg > best_avg:
                best_avg = avg
                best_eff, best_nn = eff, nn
        return None if best_eff is None else (best_eff, best_nn)
    def _best_effect_after_reroll(self, sk, rng):
        """reroll 后最有价值的锁定效果（含 keep 和 cheat）。"""
        sk_r1 = (sk[0], sk[1], sk[2], sk[3] - 1)
        marginal_cheat = self._marginal_cheat(sk, c=sk[2], r=sk[3] - 1)
        best_eff, best_val = EFFECT_BONUS, float('-inf')
        for e in ALL_EFFECTS:
            e_best_val, e_best_eff = float('-inf'), e
            kv = self.Q_effect[(sk_r1, e)].get(('keep',), [])
            if kv and (avg := sum(kv) / len(kv)) > e_best_val:
                e_best_val, e_best_eff = avg, e
            if sk[2] > 0:
                for k in ALL_EFFECTS:
                    cv = self.Q_effect[(sk_r1, e)].get(('cheat', k), [])
                    if cv and (avg := sum(cv) / len(cv) - marginal_cheat) > e_best_val:
                        e_best_val, e_best_eff = avg, k
            if e_best_val > best_val:
                best_val, best_eff = e_best_val, e_best_eff
        return best_eff
    # ------------------------------------------------------------------
    # 决策对比分析（两阶段）
    # ------------------------------------------------------------------
    def analyze_decision(self, state: CountdownState,
                          node_names: dict = None,
                          top_k: int = 6) -> str:
        """两阶段决策分析：先效果决策，再路径选择。

        分析模式从 state.effect_state 推导：
          "unlocked" → ex-ante（遍历6效果）, "locked" → 已锁定, "settled" → 已结算
        """
        if not (next_nodes := self.sim.edges.get(state.node_idx, [])):
            return '  （终态，无可选动作）'
        def _fmt(eff) -> str:
            return 'keep' if eff == 'keep' else 'reroll' if eff == 'reroll' else f'cheat->{EFFECT_NAMES.get(eff[1], eff[1])}' if isinstance(eff, tuple) and eff[0] == 'cheat' else str(eff)
        if node_names is None:
            node_names = {}
        sk = self._state_key(state)
        eff_actions = self._get_effect_actions(state)
        ft_current = self._future_table.get(
                (state.cheat_rem, state.reroll_rem), 0.0) if self._future_table else 0.0
        lines = []
        lines.append(f'\n  {"="*70}')
        lines.append(f'  决策对比分析 — node={state.node_idx} '
                     f' cheat={state.cheat_rem} reroll={state.reroll_rem}')
        if self._future_table:
            lines.append(f'  [注] 显示值 = Q值 - 后续残值({ft_current:+.2f}) = 图内CD')
        # 效果已结算：跳过阶段1，直接显示路径选择
        if state.effect_state == "settled":
            locked = state.observed_effect
            e_name = EFFECT_NAMES.get(locked, str(locked))
            lines.append(f'  效果已锁定(已结算): {e_name}（跳过效果决策）')
            lines.append(f'  {"="*70}')
            cd0 = state.countdown  # 初始 CD，用于计算增量
            # 慈怀（EFFECT_SELECT）未应用时：需枚举感染目标 + 路径组合
            if locked == EFFECT_SELECT and state.effect_state != "settled":
                destroyed = self.sim._destroy_masks[state.node_idx]
                next_set = set(next_nodes)
                target_candidates = [idx for idx in range(len(self.sim.nodes))
                                    if not ((state.infected >> idx) & 1)
                                    and not ((destroyed >> idx) & 1)
                                    and idx not in next_set]
                lines.append(f'\n  --- 慈怀目标选择 + 路径 (效果已锁定 {e_name}) ---')
                tgt_sep = ('  ' + '─' * 4 + '─┼' + '─' * 19 + '─┼' + '─' * 19 + '─┼'
                           + '─' * 9 + '─┼' + '─' * 8)
                combos = []
                n_roll = 100
                for target in target_candidates:
                    new_infected = state.infected | (1 << target)
                    for nn in next_nodes:
                        move_d = self.sim.move_delta(nn, new_infected)
                        final_infected = new_infected & ~self.sim._destroy_masks[nn]
                        ns = CountdownState(
                            node_idx=nn, infected=final_infected,
                            countdown=state.countdown + move_d,
                            cheat_rem=state.cheat_rem, reroll_rem=state.reroll_rem)
                        total = 0.0
                        srng = random.Random(42 + target * 100 + nn)
                        for _ in range(n_roll):
                            total += self._greedy_rollout(ns, srng)
                        avg = total / n_roll
                        if self._future_table:
                            avg += self._future_table.get(
                                (state.cheat_rem, state.reroll_rem), 0.0)
                        combos.append((avg, target, nn))
                if combos:
                    combos.sort(key=lambda x: -x[0])
                    best_val = combos[0][0]
                    lines.append(tgt_sep)
                    for rank, (avg, target, nn) in enumerate(combos[:top_k]):
                        t_name = node_names.get(target, '')
                        t_label = f'{t_name}#{target}' if t_name else f'node_{target}'
                        n_name = node_names.get(nn, '')
                        nn_label = f'{n_name}#{nn}' if n_name else f'node_{nn}'
                        delta = f'{- (best_val - avg):+.2f}' if rank > 0 else '基准'
                        mark = ' ★' if rank == 0 else ''
                        display_val = avg - ft_current - cd0
                        lines.append(
                            f'  {rank+1:>3d} │ {t_label:>18s} │ {nn_label:>18s} │ '
                            f'{display_val:>+8.2f} │ {delta:>8s}{mark}')
                lines.append(f'\n  {"="*70}')
                lines.append(f'  已锁定效果: {e_name}')
                if combos:
                    _, best_t, best_n = combos[0]
                    t_name = node_names.get(best_t, '')
                    t_label = f'{t_name}#{best_t}' if t_name else f'node_{best_t}'
                    n_name = node_names.get(best_n, '')
                    nn_label = f'{n_name}#{best_n}' if n_name else f'node_{best_n}'
                    pw = combos[0][0] - ft_current - cd0
                    lines.append(f'  -> 推荐: 感染 {t_label}, 走 {nn_label}  图内期望ΔCD={pw:+.2f}')
                lines.append(f'  {"="*70}')
                return '\n'.join(lines)
            # 非慈怀：普通路径选择表
            lines.append(f'\n  --- 路径选择 (效果已锁定 {e_name}) ---')
            path_sep = ('  ' + '─' * 9 + '─┼' + '─' * 4 + '─┼' + '─' * 19 + '─┼'
                        + '─' * 9 + '─┼' + '─' * 7 + '─┼' + '─' * 8)
            candidates = [(sum(vs) / len(vs), len(vs), nn)
                          for nn in next_nodes
                          if (vs := self.Q_path[(sk, locked)].get(nn, []))]
            if candidates:
                candidates.sort(key=lambda x: -x[0])
                best_val = candidates[0][0]
                lines.append(path_sep)
                for rank, (avg, cnt, nn) in enumerate(candidates[:top_k]):
                    name = node_names.get(nn, '')
                    nn_label = f'{name}#{nn}' if name else f'node_{nn}'
                    delta = f'{- (best_val - avg):+.2f}' if rank > 0 else '基准'
                    mark = ' ★' if rank == 0 else ''
                    e_label = e_name if rank == 0 else ''
                    display_val = avg - ft_current - cd0
                    lines.append(
                        f'  {e_label:>8s} │ {rank+1:>3d} │ {nn_label:>18s} │ '
                        f'{display_val:>+8.2f} │ {cnt:>6d} │ {delta:>8s}{mark}')
            lines.append(f'\n  {"="*70}')
            lines.append(f'  已锁定效果: {e_name}')
            if candidates:
                _, _, best_nn = candidates[0]
                name = node_names.get(best_nn, '')
                nn_label = f'{name}#{best_nn}' if name else f'node_{best_nn}'
                pw = candidates[0][0] - ft_current - cd0
                lines.append(f'  -> 推荐路径: {nn_label}  图内期望ΔCD={pw:+.2f}')
            lines.append(f'  {"="*70}')
            return '\n'.join(lines)
        # 已观察到的效果（未锁定时用户已知效果值，分析应聚焦该效果而非遍历6种求平均）
        obs_input = state.observed_effect  # 可能为 None（尚未观察）
        lines.append(f'  {"="*70}')
        cd0 = state.countdown  # 初始 CD，后续计算增量用
        # ===== 阶段1: 效果决策 =====
        if obs_input is not None:
            e_name = EFFECT_NAMES.get(obs_input, str(obs_input))
            lines.append(f'\n  --- 阶段1: 效果决策 (已观察: {e_name}，选 keep/cheat/reroll) ---')
        else:
            lines.append('\n  --- 阶段1: 效果决策 (未观察，遍历6种效果取最优) ---')
        eff_sep = ('  ' + '─' * 9 + '─┼' + '─' * 4 + '─┼' + '─' * 17 + '─┼'
                   + '─' * 9 + '─┼' + '─' * 7 + '─┼' + '─' * 8)
        marginal_cheat = self._marginal_cheat(sk)
        marginal_reroll = self._marginal_reroll(sk)

        def _analyze_effect_candidates(_obs):
            """对单一效果 _obs，枚举 keep/cheat→k/reroll 候选值。"""
            candidates = []
            keep_val = None
            for eff in eff_actions:
                eff_ak = self._effect_action_key(eff)
                if eff == 'reroll':
                    rv = self._reroll_value(sk) - marginal_reroll
                    candidates.append((rv, 0, eff))
                elif isinstance(eff, tuple) and eff[0] == 'cheat' and eff[1] == _obs:
                    continue  # cheat→obs 从 keep 推导，稍后加入
                elif isinstance(eff, tuple) and eff[0] == 'cheat':
                    target = eff[1]
                    t_vals = self.Q_effect.get((sk, target), {})
                    if (t_keep := t_vals.get(('keep',), [])):
                        avg = sum(t_keep) / len(t_keep) - marginal_cheat
                        candidates.append((avg, len(t_keep), eff))
                else:  # keep
                    if (vals := self.Q_effect[(sk, _obs)].get(eff_ak, [])):
                        avg = sum(vals) / len(vals)
                        candidates.append((avg, len(vals), eff))
                        if eff == 'keep':
                            keep_val = avg
            if keep_val is not None:
                keep_cnt = next((c_[1] for c_ in candidates if c_[2] == 'keep'), 0)
                candidates.append((keep_val - marginal_cheat, keep_cnt, ('cheat', _obs)))
            return candidates

        if obs_input is not None:
            # 已观察效果：仅展示该效果下的决策候选
            candidates = _analyze_effect_candidates(obs_input)
            if candidates:
                candidates.sort(key=lambda x: -x[0])
                best_val = candidates[0][0]
                lines.append(eff_sep)
                for rank, (avg, cnt, eff) in enumerate(candidates[:top_k]):
                    eff_str = _fmt(eff)
                    delta = f'{- (best_val - avg):+.2f}' if rank > 0 else '基准'
                    mark = ' ★' if rank == 0 else ''
                    eff_label = e_name if rank == 0 else ''
                    display_val = avg - ft_current - cd0
                    lines.append(
                        f'  {eff_label:>8s} │ {rank+1:>3d} │ {eff_str:>16s} │ '
                        f'{display_val:>+8.2f} │ {cnt:>6d} │ {delta:>8s}{mark}')
            # 推荐效果决策
            eff = self._greedy_effect(sk, obs_input, eff_actions, random.Random(0))
            if eff == 'reroll':
                obs_best = (self._reroll_value(sk), 0, eff)
            else:
                eff_ak = self._effect_action_key(eff)
                vals = self.Q_effect[(sk, obs_input)].get(eff_ak, [])
                avg = sum(vals) / len(vals) if vals else 0.0
                obs_best = (avg, len(vals), eff)
        else:
            # 未观察效果：显示每种效果下的最优决策，再显示 ex-ante 平均
            for obs in ALL_EFFECTS:
                candidates = _analyze_effect_candidates(obs)
                if not candidates:
                    continue
                candidates.sort(key=lambda x: -x[0])
                best_val = candidates[0][0]
                lines.append(eff_sep)
                for rank, (avg, cnt, eff) in enumerate(candidates[:top_k]):
                    eff_str = _fmt(eff)
                    delta = f'{- (best_val - avg):+.2f}' if rank > 0 else '基准'
                    mark = ' ★' if rank == 0 else ''
                    eff_label = EFFECT_NAMES.get(obs, str(obs)) if rank == 0 else ''
                    display_val = avg - ft_current - cd0
                    lines.append(
                        f'  {eff_label:>8s} │ {rank+1:>3d} │ {eff_str:>16s} │ '
                        f'{display_val:>+8.2f} │ {cnt:>6d} │ {delta:>8s}{mark}')
            # ex-ante 平均
            lines.append(eff_sep)
            lines.append(f'  {"ex-ante":>8s} │ (遍历6效果取平均，top-5)')
            exante_eff = []
            for eff in eff_actions:
                if eff == 'reroll':
                    exante_eff.append((self._reroll_value(sk), 0, eff))
                else:
                    total_avg = 0.0
                    total_n = 0
                    eff_ak = self._effect_action_key(eff)
                    for obs in ALL_EFFECTS:
                        if (vals := self.Q_effect[(sk, obs)].get(eff_ak, [])):
                            total_avg += sum(vals) / len(vals)
                            total_n += 1
                    if total_n > 0:
                        exante_eff.append((total_avg / total_n, total_n, eff))
            exante_eff.sort(key=lambda x: -x[0])
            for rank, (avg, cnt, eff) in enumerate(exante_eff[:5]):
                eff_str = _fmt(eff)
                delta = f'{- (exante_eff[0][0] - avg):+.2f}' if rank > 0 else '基准'
                mark = ' ★' if rank == 0 else ''
                display_val = avg - ft_current - cd0
                lines.append(
                    f'  {"":>8s} │ {rank+1:>3d} │ {eff_str:>16s} │ '
                    f'{display_val:>+8.2f} │ {cnt:>4d} │ {delta:>8s}{mark}')
            obs_best = exante_eff[0] if exante_eff else None
        # ===== 阶段2: 路径选择（按锁定效果分组） =====
        current_name = node_names.get(state.node_idx, '')
        current_label = f'{current_name}#{state.node_idx}' if current_name else f'node_{state.node_idx}'
        lines.append(f'\n  --- 阶段2: 路径选择 @{current_label} (效果锁定后选目标节点) ---')
        path_sep = ('  ' + '─' * 9 + '─┼' + '─' * 4 + '─┼' + '─' * 19 + '─┼'
                    + '─' * 9 + '─┼' + '─' * 7 + '─┼' + '─' * 8)
        for locked_e in ALL_EFFECTS:
            candidates = [(sum(vs) / len(vs), len(vs), nn)
                          for nn in next_nodes
                          if (vs := self.Q_path[(sk, locked_e)].get(nn, []))]
            if not candidates:
                continue
            candidates.sort(key=lambda x: -x[0])
            best_val = candidates[0][0]
            lines.append(path_sep)
            for rank, (avg, cnt, nn) in enumerate(candidates[:top_k]):
                name = node_names.get(nn, '')
                nn_label = f'{name}#{nn}' if name else f'node_{nn}'
                delta = f'{- (best_val - avg):+.2f}' if rank > 0 else '基准'
                mark = ' ★' if rank == 0 else ''
                e_label = EFFECT_NAMES.get(locked_e, str(locked_e)) if rank == 0 else ''
                display_val = avg - ft_current - cd0
                lines.append(
                    f'  {e_label:>8s} │ {rank+1:>3d} │ {nn_label:>18s} │ '
                    f'{display_val:>+8.2f} │ {cnt:>6d} │ {delta:>8s}{mark}')
        # 综合推荐
        lines.append(f'\n  {"="*70}')
        if obs_best:
            best_val, _, best_eff = obs_best
            eff_str = _fmt(best_eff)
            best_within = best_val - ft_current - cd0
            if obs_input is not None:
                e_name = EFFECT_NAMES.get(obs_input, str(obs_input))
                lines.append(f'  已观察效果: {e_name}')
            if best_eff == 'reroll':
                lines.append(f'  -> 推荐效果决策: {eff_str}')
                lines.append(f'     reroll期望 = {best_within:+.2f}')
            elif best_eff == 'keep':
                lines.append(f'  -> 推荐效果决策: {eff_str}')
                lines.append(f'     锁定效果 {EFFECT_NAMES.get(obs_input or EFFECT_BONUS, "?")} 后的最优路径:')
                locked_for_path = obs_input if obs_input is not None else EFFECT_BONUS
                path_candidates = [(sum(vs) / len(vs), len(vs), nn)
                                   for nn in next_nodes
                                   if (vs := self.Q_path[(sk, locked_for_path)].get(nn, []))]
                if path_candidates:
                    path_candidates.sort(key=lambda x: -x[0])
                    _, _, best_nn = path_candidates[0]
                    name = node_names.get(best_nn, '')
                    nn_label = f'{name}#{best_nn}' if name else f'node_{best_nn}'
                    pw = path_candidates[0][0] - ft_current
                    lines.append(f'     ->{nn_label}  图内CD={pw:+.2f}')
            else:
                locked = best_eff[1] if isinstance(best_eff, tuple) else (obs_input or EFFECT_BONUS)
                lines.append(f'  -> 推荐效果决策: {eff_str}')
                path_candidates = [(sum(vs) / len(vs), len(vs), nn)
                                   for nn in next_nodes
                                   if (vs := self.Q_path[(sk, locked)].get(nn, []))]
                if path_candidates:
                    path_candidates.sort(key=lambda x: -x[0])
                    _, _, best_nn = path_candidates[0]
                    name = node_names.get(best_nn, '')
                    nn_label = f'{name}#{best_nn}' if name else f'node_{best_nn}'
                    pw = path_candidates[0][0] - ft_current
                    lines.append(f'     ->{nn_label}  图内期望CD={pw:+.2f}')
        lines.append(f'  {"="*70}')
        return '\n'.join(lines)
    # ------------------------------------------------------------------
    # 评估
    # ------------------------------------------------------------------
    def evaluate(self, cheat: int = 5, reroll: int = 10,
                 n_rollouts: int = 2000, seed: int = 123,
                 future_table: dict = None,
                 node_names: dict = None) -> dict:
        """纯贪心评估，含多段 reroll。追踪最佳 rollout 的完整路径。"""
        if self._ge_cache is None:
            self._ge_cache = {}  # Q 表冻结，启用贪心决策缓存
        rng = random.Random(seed)
        values_raw = []      # 实际模拟终值（整数）
        values_augmented = []  # 加 future_table 后的期望值（用于 mean/std）
        best_raw = float('-inf')
        best_trace = []      # 最佳 rollout 的步骤列表
        for _ in range(n_rollouts):
            state = self.sim.initial_state(cheat, reroll, 0,
                                           observed_effect=self._initial_observed_effect,
                                           effect_state=self._initial_effect_state)
            trace = []
            while not self.sim.is_terminal(state):
                if not (next_nodes := self.sim.edges.get(state.node_idx, [])):
                    break
                # 首步可能已结算
                if state.effect_state == "settled":
                    locked_effect, cost_c, skip_effect, observed_first, eff, reroll_count = state.observed_effect, 0, True, None, None, 0
                else:
                    skip_effect, reroll_count = False, 0
                    observed_first = observed = state.observed_effect if state.effect_state == "locked" else rng.randint(1, 6)
                    while True:
                        sk = self._state_key(state)
                        eff = self._greedy_effect(sk, observed, self._get_effect_actions(state), rng)
                        if eff == 'reroll':
                            reroll_count += 1
                            state = CountdownState(node_idx=state.node_idx, infected=state.infected,
                                                   countdown=state.countdown, cheat_rem=state.cheat_rem,
                                                   reroll_rem=state.reroll_rem - 1)
                            observed = rng.randint(1, 6)
                            continue
                        locked_effect, cost_c = (observed, 0) if eff == 'keep' else (eff[1], 1)
                        break
                # 路径阶段
                sk_locked = self._state_key(state)
                nn = (self._dp_path_fallback(state, locked_effect, next_nodes, rng)
                      if not self.Q_path.get((sk_locked, locked_effect))
                      else self._greedy_path(sk_locked, locked_effect, next_nodes, rng))
                cd_before = state.countdown
                node_before = state.node_idx
                infected_before = state.infected
                node_name_before = (node_names or {}).get(node_before,
                                    self.sim.node_map.get(node_before, {}).get('name', ''))
                state = self._apply_and_move(state, locked_effect, nn, cost_c, 0, rng,
                                              skip_effect_apply=skip_effect)
                trace.append({
                    'step': len(trace) + 1,
                    'node_idx': node_before,
                    'node_name': node_name_before,
                    'observed_first': observed_first,
                    'reroll_count': reroll_count,
                    'decision': eff,
                    'locked_effect': locked_effect,
                    'next_node': nn,
                    'cd_before': cd_before,
                    'cd_delta': state.countdown - cd_before,
                    'cd_after': state.countdown,
                    'cheat_rem': state.cheat_rem,
                    'reroll_rem': state.reroll_rem,
                    'infected_added': state.infected & ~infected_before,
                })
            raw_cd = state.countdown
            values_raw.append(raw_cd)
            values_augmented.append(raw_cd + (future_table.get((state.cheat_rem, state.reroll_rem), 0.0) if future_table else 0))
            if raw_cd > best_raw:
                best_raw = raw_cd
                best_trace = trace
        n = len(values_augmented)
        mean = sum(values_augmented) / n
        var = sum((v - mean) ** 2 for v in values_augmented) / (n - 1) if n > 1 else 0
        sv_raw = sorted(values_raw)
        return {
            'mean': mean, 'std': var ** 0.5,
            'p50': sv_raw[n // 2], 'p80': sv_raw[int(n * 0.8)],
            'max': sv_raw[-1], 'min': sv_raw[0],
            'n_rollouts': n,
            'best_raw': best_raw,
            'best_trace': best_trace,
        }
    @staticmethod
    def _format_best_trace(trace: list, node_names: dict = None) -> str:
        """格式化最佳路径的详细步骤。节点用编号（不重名）而非类型名（会重复）。"""
        if not trace:
            return '  (无)'
        lines = []
        for t in trace:
            locked_name = EFFECT_NAMES.get(t['locked_effect'], str(t['locked_effect']))
            first_name = EFFECT_NAMES.get(t.get('observed_first'), '?')
            dec = t['decision']
            if dec is None:
                dec_str = f'已锁定({locked_name})'
            elif dec == 'keep':
                dec_str = 'keep'
            elif dec == 'reroll':
                dec_str = 'reroll'
            elif isinstance(dec, tuple) and dec[0] == 'cheat':
                dec_str = f'cheat→{EFFECT_NAMES.get(dec[1], dec[1])}'
            else:
                dec_str = str(dec)
            rr = t.get('reroll_count', 0)
            if t.get('observed_first') is None:
                obs_str = f'已锁定({locked_name})'
            elif rr > 0:
                obs_str = f'{first_name}→reroll×{rr}→{locked_name}'
            else:
                obs_str = f'{first_name}'
            from_node = f'#{t["node_idx"]}'
            to_node = f'#{t["next_node"]}'
            line = (f'  Step{t["step"]:>2d}: @{from_node}  '
                    f'观察:{obs_str}  决策:{dec_str}  '
                    f'→{to_node}  '
                    f'CD {t["cd_before"]:+d}→{t["cd_after"]:+d} '
                    f'(Δ{t["cd_delta"]:+d})  '
                    f'c:{t["cheat_rem"]} r:{t["reroll_rem"]}')
            nn = node_names or {}
            def _fmt(idx):
                name = nn.get(idx, '')
                return f'{name}#{idx}' if name else f'#{idx}'
            if (infected_all := t.get('infected_all', 0)):
                line += f'  已感染: [{", ".join(_fmt(idx) for idx in range(64) if (infected_all >> idx) & 1)}]'
            if (added := t.get('infected_added', 0)):
                line += f'  +新增: {", ".join(_fmt(idx) for idx in range(64) if (added >> idx) & 1)}'
            if (destroyed := t.get('destroyed', 0)):
                line += f'  已销毁: [{", ".join(_fmt(idx) for idx in range(64) if (destroyed >> idx) & 1)}]'
            lines.append(line)
        return '\n'.join(lines)
    @staticmethod
    def _fallback_effect(state: CountdownState, observed: int,
                         rng: random.Random):
        """未探索状态的保守效果策略。

        关键：cheat→SELECT (慈怀感染下一节点) 与 cheat→BONUS (为善) 各有优势，
        必须都探索，否则策略永远学不到"感染路径节点"这条路线。
        """
        c, r = state.cheat_rem, state.reroll_rem
        if observed == EFFECT_BONUS:
            return 'keep'
        if r > 1:
            return 'reroll'
        if c > 0:
            return ('cheat', EFFECT_SELECT) if rng.random() < 0.5 else ('cheat', EFFECT_BONUS)
        return 'reroll' if r > 0 else 'keep'
    def _fallback_path(self, state: CountdownState, locked_effect: int,
                       next_nodes: list, rng: random.Random) -> int:
        """未探索状态的路径选择：优先已感染节点（移动 +1 vs -3）。"""
        if (infected := [nn for nn in next_nodes if (state.infected >> nn) & 1]):
            infected.sort(key=lambda nn: _node_priority(self.sim.node_map, nn))
            best_prio = _node_priority(self.sim.node_map, infected[0])
            top = [nn for nn in infected if _node_priority(self.sim.node_map, nn) == best_prio]
            return rng.choice(top)
        return rng.choice(next_nodes)
    def _dp_path_fallback(self, state: CountdownState, locked_effect: int,
                          next_nodes: list, rng: random.Random) -> int:
        """DP W 表引导的路径选择 —— Q_path 无数据时的 fallback。
        对每个后继节点评估「锁定效果 + 移动 + 列销毁」后的 DP 期望值。
        """
        if not hasattr(self, '_dp_w') or self._dp_w is None:
            return self._fallback_path(state, locked_effect, next_nodes, rng)
        node, mask, c, r = state.node_idx, state.infected, state.cheat_rem, state.reroll_rem
        destroyed = self.sim._destroy_masks[node]
        best_val = float('-inf')
        best_nn = next_nodes[0]
        for nn in next_nodes:
            destroyed_nn = self.sim._destroy_masks[nn]
            results = self.sim.apply_effect(mask, locked_effect,
                nn if locked_effect == EFFECT_ADJACENT else node,
                destroyed_nn if locked_effect == EFFECT_ADJACENT else destroyed)
            nn_best = max((cd_delta + self.sim.move_delta(nn, new_mask) + future
                          for new_mask, cd_delta in results
                          for future in [self._dp_w.get((nn, new_mask & ~destroyed_nn, c, r))]
                          if future is not None), default=float('-inf'))
            if nn_best > best_val:
                best_val, best_nn = nn_best, nn
        return self._fallback_path(state, locked_effect, next_nodes, rng) if best_val == float('-inf') else best_nn
    def estimate_w_table(self, max_cheat: int, max_reroll: int,
                         n_train: int = 15000, n_eval: int = 300,
                         sample_cheats: list = None,
                         sample_rerolls: list = None,
                         future_table: dict = None,
                         max_useful: int = None) -> dict:
        """对单张图用 MC 估计 W[(c, r)] 表（零预知未来）。

        训练一次（最大资源，自然覆盖各资源水平），在各采样点评估，双线性插值到全网格。

        future_table: {(c, r): value} — 后续地图的资源价值。
        max_useful: 单图最大有用资源数（≤步数），超出部分边际收益为 0。
        """
        # cheat 至多 1 次/步，封顶于步数；reroll 可单节点反复使用，无步数封顶
        if max_useful is not None:
            max_cheat = min(max_cheat, max_useful)
        if sample_cheats is None:
            # 密集低值 + 稀疏高值（W 在 c≈5 饱和）
            pts = [0, 1, 2, 3, 4, 5]
            if max_cheat > 5:
                pts.extend([8, 12, max_cheat])
            sample_cheats = pts
        if sample_rerolls is None:
            pts = [0, 1, 2, 3, 5]
            if max_reroll > 5:
                pts.extend([10, 20, 50, max_reroll])
            sample_rerolls = pts
        sample_cheats = sorted(set(c for c in sample_cheats if c <= max_cheat))
        sample_rerolls = sorted(set(r for r in sample_rerolls if r <= max_reroll))
        # 训练一次（最大资源，rollout 自然耗尽资源覆盖所有水平）
        print(f'      训练MC策略 (ε=0.3, {n_train} rollouts)...',
              end=' ', flush=True)
        _t0 = time.time()
        self.train(cheat=max_cheat, reroll=max_reroll, n_rollouts=n_train, epsilon=0.3,
                   future_table=future_table)
        print(f'{time.time() - _t0:.1f}s  '
              f'({len(self.Q_effect) + len(self.Q_path)} states)', flush=True)
        # 在各采样点评估（复用同一 Q 表，策略在低资源时自动回退到保守策略）
        w_samples = {}
        for c in sample_cheats:
            for r in sample_rerolls:
                result = self.evaluate(cheat=c, reroll=r, n_rollouts=n_eval,
                                       seed=c * 1000 + r + 42,
                                       future_table=future_table)
                w_samples[(c, r)] = result['mean']
        # 双线性插值扩展到完整网格
        w_table = {}
        for c in range(max_cheat + 1):
            for r in range(max_reroll + 1):
                if (c, r) in w_samples:
                    w_table[(c, r)] = w_samples[(c, r)]
                    continue
                # 找包围的采样点
                c_lo = max(sc for sc in sample_cheats if sc <= c)
                c_hi = min(sc for sc in sample_cheats if sc >= c)
                r_lo = max(sr for sr in sample_rerolls if sr <= r)
                r_hi = min(sr for sr in sample_rerolls if sr >= r)
                if c_lo == c_hi and r_lo == r_hi:
                    w_table[(c, r)] = w_samples[(c_lo, r_lo)]
                elif c_lo == c_hi:
                    tr = (r - r_lo) / (r_hi - r_lo) if r_hi != r_lo else 0
                    w_table[(c, r)] = w_samples[(c_lo, r_lo)] + tr * (w_samples[(c_lo, r_hi)] - w_samples[(c_lo, r_lo)])
                elif r_lo == r_hi:
                    tc = (c - c_lo) / (c_hi - c_lo) if c_hi != c_lo else 0
                    w_table[(c, r)] = w_samples[(c_lo, r_lo)] + tc * (w_samples[(c_hi, r_lo)] - w_samples[(c_lo, r_lo)])
                else:
                    tc, tr = (c - c_lo) / (c_hi - c_lo), (r - r_lo) / (r_hi - r_lo)
                    w_table[(c, r)] = (w_samples[(c_lo, r_lo)] * (1 - tc) * (1 - tr) +
                                       w_samples[(c_hi, r_lo)] * tc * (1 - tr) +
                                       w_samples[(c_lo, r_hi)] * (1 - tc) * tr +
                                       w_samples[(c_hi, r_hi)] * tc * tr)
        return w_table
class ExactCountdownDP:
    """精确动态规划求解倒计时最大化问题。

    利用 cd 线性可加性：V(node, mask, cd, c, r) = cd + W(node, mask, c, r)
    W 仅依赖 (node, mask, c, r)，可通过反向 DP 精确求解。
    """
    def __init__(self, sim: MapSimulator):
        self.sim = sim
        self.W: dict[tuple, float] = {}  # (node, mask, c, r) -> future expected cd change
        self.V: dict[tuple, float] = {}  # (node, mask, c, r, e_obs) -> value after observing e
        self.policy: dict[tuple, tuple] = {}  # -> (effect_action, next_node)
        self.W_best: dict[tuple, float] = {}  # best-case (max over random outcomes)
    def _better_node(self, val: float, nn: int, best_val: float, best_nn) -> bool:
        """值更高则优；等值时按节点类型倾向：奖励>事件>冒险>其它。"""
        return val > best_val + 1e-9 or (best_nn is not None and abs(val - best_val) <= 1e-9 and _node_priority(self.sim.node_map, nn) < _node_priority(self.sim.node_map, best_nn))
    def solve(self, max_cheat: int = 2, max_reroll: int = 3,
              future_table: dict = None):
        """对所有可达状态运行反向 DP（ex-post 优化，多段 reroll）。

        DP 内部自动截断资源上限到每图最多可用步数（每步至多消耗 1 资源），
        超出部分通过边界值外推（边际收益为零），避免状态空间爆炸。

        多段 reroll：reroll 后回到决策起点，可反复 reroll 直到 keep/cheat 或用尽次数。
        按 r 分层递推：先算 r=0（无 reroll），再算 r=1..max_r，
        每层 reroll 值 = W[(node, mask, c, r-1)]（上一层已算好的期望值）。

        future_table: {(c, r): value} — 留 c 个 cheat、r 个 reroll 给未来地图的期望 cd 增量。
        """
        if future_table is None:
            future_table = {}
        reachable = self._enumerate_reachable_states(max_cheat, max_reroll)
        masks_by_node = defaultdict(set)
        for node, mask in reachable:
            masks_by_node[node].add(mask)
        # 自动截断：DP 只在适度资源网格上精确求解
        solve_c = min(max_cheat, 5)
        solve_r = min(max_reroll, 30)
        self._dp_max_c = solve_c
        self._dp_max_r = solve_r
        # 终端节点：一次性填好所有 (c, r)，供各层查询
        for node in masks_by_node:
            if node not in self.sim.edges or not self.sim.edges[node]:
                for mask in masks_by_node[node]:
                    for c in range(max_cheat + 1):
                        for r in range(max_reroll + 1):
                            ft_val = future_table.get((c, r), 0.0)
                            self.W[(node, mask, c, r)] = ft_val
                            self.policy[(node, mask, c, r)] = ('terminal', -1)
                            for e_obs in ALL_EFFECTS:
                                self.V[(node, mask, c, r, e_obs)] = ft_val
        # _value_after_effect 缓存：相同 (node, mask, effect, c, r) 被多次调用
        _vae_cache: dict[tuple, tuple] = {}
        def _cached_value_after_effect(n, m, eff, cc, rr, nn, dd):
            _key = (n, m, eff, cc, rr)
            if _key in _vae_cache:
                return _vae_cache[_key]
            _result = self._value_after_effect(n, m, eff, cc, rr, nn, dd)
            _vae_cache[_key] = _result
            return _result
        # 按 r 分层递推：多段 reroll 依赖 W[(node, mask, c, r-1)]
        for r in range(solve_r + 1):
            for node in reversed(self.sim._topo_order):
                if not (masks := masks_by_node.get(node, set())):
                    continue
                if node not in self.sim.edges or not self.sim.edges[node]:
                    continue  # 已在上方填好
                next_nodes = self.sim.edges.get(node, [])
                destroyed = self.sim._destroy_masks[node]
                for mask in masks:
                    for c in range(solve_c + 1):
                        expected_val = 0.0
                        best_overall_val = float('-inf')
                        best_overall_for_action = None
                        for e_obs in ALL_EFFECTS:
                            # keep: 接受当前效果，选最优路径
                            best_e, action_e = _cached_value_after_effect(
                                node, mask, e_obs, c, r, next_nodes, destroyed)
                            best_action_for_e = ('keep', action_e[1] if action_e else -1)
                            # cheat(k): 自选效果 k，选最优路径
                            if c > 0:
                                for k in ALL_EFFECTS:
                                    val_k, action_k = _cached_value_after_effect(
                                        node, mask, k, c - 1, r, next_nodes, destroyed)
                                    if val_k > best_e + 1e-9:
                                        best_e = val_k
                                        best_action_for_e = (('cheat', k),
                                                             action_k[1] if action_k else -1)
                            # reroll (多段): 期望值 = W[(node, mask, c, r-1)]
                            if r > 0:
                                reroll_val = self.W.get((node, mask, c, r - 1), float('-inf'))
                                if reroll_val > best_e + 1e-9:
                                    best_e = reroll_val
                                    best_action_for_e = ('reroll', -1)
                            self.V[(node, mask, c, r, e_obs)] = best_e
                            expected_val += best_e / 6.0
                            if best_e > best_overall_val:
                                best_overall_val = best_e
                                best_overall_for_action = best_action_for_e
                        self.W[(node, mask, c, r)] = expected_val
                        self.policy[(node, mask, c, r)] = best_overall_for_action
        # 外推：将 W 扩展到完整的 (max_cheat, max_reroll) 范围
        if max_cheat > solve_c or max_reroll > solve_r:
            for node in masks_by_node:
                if node not in self.sim.edges or not self.sim.edges[node]:
                    continue
                for mask in masks_by_node[node]:
                    for c in range(max_cheat + 1):
                        for r in range(max_reroll + 1):
                            if (node, mask, c, r) in self.W:
                                continue
                            src_c = min(c, solve_c)
                            src_r = min(r, solve_r)
                            self.W[(node, mask, c, r)] = self.W.get(
                                (node, mask, src_c, src_r), 0.0)
                            self.policy[(node, mask, c, r)] = self.policy.get(
                                (node, mask, src_c, src_r), ('terminal', -1))
        # 最优极限 DP：所有随机因素按最有利方向发生
        _vaeb_cache: dict[tuple, tuple] = {}
        def _cached_value_after_effect_best(n, m, eff, cc, rr, nn, dd):
            _key = (n, m, eff, cc, rr)
            if _key in _vaeb_cache:
                return _vaeb_cache[_key]
            _result = self._value_after_effect_best(n, m, eff, cc, rr, nn, dd)
            _vaeb_cache[_key] = _result
            return _result
        for node in masks_by_node:
            if node not in self.sim.edges or not self.sim.edges[node]:
                for mask in masks_by_node[node]:
                    for c in range(max_cheat + 1):
                        for r in range(max_reroll + 1):
                            self.W_best[(node, mask, c, r)] = 0.0
        for r in range(solve_r + 1):
            for node in reversed(self.sim._topo_order):
                if not (masks := masks_by_node.get(node, set())):
                    continue
                if node not in self.sim.edges or not self.sim.edges[node]:
                    continue
                next_nodes = self.sim.edges.get(node, [])
                destroyed = self.sim._destroy_masks[node]
                for mask in masks:
                    for c in range(solve_c + 1):
                        best_val = float('-inf')
                        for e in ALL_EFFECTS:
                            best_e, _ = _cached_value_after_effect_best(
                                node, mask, e, c, r, next_nodes, destroyed)
                            if c > 0:
                                for k in ALL_EFFECTS:
                                    val_k, _ = _cached_value_after_effect_best(
                                        node, mask, k, c - 1, r, next_nodes, destroyed)
                                    if val_k > best_e + 1e-9:
                                        best_e = val_k
                            if r > 0:
                                reroll_val = self.W_best.get(
                                    (node, mask, c, r - 1), float('-inf'))
                                if reroll_val > best_e + 1e-9:
                                    best_e = reroll_val
                            if best_e > best_val:
                                best_val = best_e
                        self.W_best[(node, mask, c, r)] = best_val
        if max_cheat > solve_c or max_reroll > solve_r:
            for node in masks_by_node:
                for mask in masks_by_node[node]:
                    for c in range(max_cheat + 1):
                        for r in range(max_reroll + 1):
                            if (node, mask, c, r) in self.W_best:
                                continue
                            src_c = min(c, solve_c)
                            src_r = min(r, solve_r)
                            self.W_best[(node, mask, c, r)] = self.W_best.get(
                                (node, mask, src_c, src_r), 0.0)
    def _value_after_effect_best(self, node, mask, effect, c, r, next_nodes, destroyed):
        """最优极限：效果→行走→销毁（含目标自身）。max over outcomes, max over next_node。"""
        c = min(c, getattr(self, '_dp_max_c', c))
        r = min(r, getattr(self, '_dp_max_r', r))
        best_val = float('-inf')
        best_action = None
        if effect == EFFECT_BONUS:
            cd_delta = self.sim._active_infected(mask, destroyed)
            for nn in next_nodes:
                fm = mask & ~self.sim._destroy_masks[nn]
                md = self.sim.move_delta(nn, mask)
                future = self.W_best.get((nn, fm, c, r), float('-inf'))
                val = cd_delta + md + future
                if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                    best_val = val
                    best_action = (effect, nn)
            return best_val, best_action
        if effect == EFFECT_ADJACENT:
            for nn in next_nodes:
                dd = self.sim._destroy_masks[nn]
                surviving = mask & ~dd
                nm = surviving
                for nb in self.sim._neighbors.get(nn, []):
                    if not ((dd >> nb) & 1):
                        nm |= (1 << nb)
                md = self.sim.move_delta(nn, mask)
                future = self.W_best.get((nn, nm, c, r), float('-inf'))
                val = md + future
                if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                    best_val = val
                    best_action = (effect, nn)
            return best_val, best_action
        if effect == EFFECT_NOTHING:
            for nn in next_nodes:
                fm = mask & ~self.sim._destroy_masks[nn]
                md = self.sim.move_delta(nn, mask)
                future = self.W_best.get((nn, fm, c, r), float('-inf'))
                val = md + future
                if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                    best_val = val
                    best_action = (effect, nn)
            return best_val, best_action
        if effect == EFFECT_SELECT:
            for nn in next_nodes:
                dd = self.sim._destroy_masks[nn]
                # SELECT 在当前位置生效，使用当前位置的 destroyed 过滤可选目标
                if not (candidates := self.sim._get_uninfected(mask, destroyed)):
                    md = self.sim.move_delta(nn, mask)
                    future = self.W_best.get((nn, mask & ~dd, c, r), float('-inf'))
                    val = md + future
                    if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                        best_val = val
                        best_action = (effect, nn, None)
                else:
                    for choice in candidates:
                        nm_effect = mask | (1 << choice)
                        nm_future = nm_effect & ~dd
                        md = self.sim.move_delta(nn, nm_effect)
                        future = self.W_best.get((nn, nm_future, c, r), float('-inf'))
                        val = md + future
                        if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                            best_val = val
                            best_action = (effect, nn, choice)
            return best_val, best_action
        if effect == EFFECT_RANDOM_INFECT:
            for nn in next_nodes:
                dd = self.sim._destroy_masks[nn]
                # RANDOM_INFECT 在当前位置生效，使用当前位置的 destroyed 过滤可选目标
                candidates = self.sim._get_uninfected(mask, destroyed)
                for choice in (candidates if candidates else [None]):
                    nm_effect = mask | (1 << choice) if choice is not None else mask
                    nm_future = nm_effect & ~dd
                    md = self.sim.move_delta(nn, nm_effect)
                    future = self.W_best.get((nn, nm_future, c, r), float('-inf'))
                    val = md + future
                    if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                        best_val = val
                        best_action = (effect, nn, choice)
            return best_val, best_action
        if effect == EFFECT_SPREAD:
            for nn in next_nodes:
                dd = self.sim._destroy_masks[nn]
                surviving = mask & ~destroyed
                spread_sources, est_product = self.sim._build_spread_sources(surviving, destroyed)
                if not spread_sources:
                    masks_effect = [surviving]
                elif est_product <= 600:
                    masks_effect = self.sim._cartesian_spread(surviving, spread_sources)
                else:
                    nm = surviving
                    used = set()
                    for choices in spread_sources:
                        picked = next((c for c in choices if c not in used), None)
                        if picked is None:
                            picked = choices[0]
                        used.add(picked)
                        nm |= (1 << picked)
                    masks_effect = [nm]
                for nm_effect in masks_effect:
                    nm_future = nm_effect & ~dd
                    md = self.sim.move_delta(nn, nm_effect)
                    future = self.W_best.get((nn, nm_future, c, r), float('-inf'))
                    val = md + future
                    if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                        best_val = val
                        best_action = (effect, nn, nm_effect)
            return best_val, best_action
        return best_val, best_action
    def trace_best_path(self, start_node: int, start_mask: int,
                        initial_cd: int, cheat: int, reroll: int,
                        observed_effect: int = None,
                        effect_state: str = "unlocked",
                        node_names: dict = None) -> list:
        """从起始状态前向追踪 DP 最优极限路径（所有随机按最有利方向发生）。

        observed_effect: 1~6 观察到的效果 (unlocked 时为 None)。
        effect_state: "unlocked" | "locked" | "settled"。
        """
        trace = []
        node = start_node
        mask = start_mask
        cd = initial_cd
        c = cheat
        r = reroll
        destroyed_cum = 0  # 已销毁节点累计掩码
        first_step = True
        while True:
            if node not in self.sim.edges or not self.sim.edges[node]:
                break
            if not (next_nodes := self.sim.edges.get(node, [])):
                break
            destroyed = self.sim._destroy_masks[node]
            best_val = float('-inf')
            best_decision = None     # 'keep' | ('cheat', k) | 'reroll' | None=已锁定
            best_effect = None
            best_next_node = None
            best_choice = None       # SELECT/RANDOM_INFECT 的目标节点
            best_spread_mask = None  # SPREAD 的最佳感染掩码
            cost_c = 0
            if first_step and effect_state == "settled":
                # Case A: 首步效果已结算 → 跳过效果枚举，直接选最优路径
                val, action = self._value_after_effect_best(
                    node, mask, EFFECT_NOTHING, c, r, next_nodes, destroyed)
                best_val = val
                best_decision = None
                best_effect = observed_effect
                cost_c = 0
                if action:
                    best_next_node = action[1]
            else:
                # keep 时考虑的效果列表：首步已锁定时只考虑锁定效果
                keep_effects = [observed_effect] if (first_step and effect_state == "locked") else ALL_EFFECTS
                # ---- keep: 观察到的效果恰好是最佳的 ----
                for e_obs in keep_effects:
                    val, action = self._value_after_effect_best(
                        node, mask, e_obs, c, r, next_nodes, destroyed)
                    if val > best_val + 1e-9:
                        best_val = val
                        best_decision = 'keep'
                        best_effect = e_obs
                        cost_c = 0
                        if action:
                            best_next_node = action[1]
                            if e_obs == EFFECT_SELECT or e_obs == EFFECT_RANDOM_INFECT:
                                best_choice = action[2] if len(action) > 2 else None
                            elif e_obs == EFFECT_SPREAD:
                                best_spread_mask = action[2] if len(action) > 2 else None
                # ---- cheat: 消耗 1c 自选效果 ----
                if c > 0:
                    for k in ALL_EFFECTS:
                        val, action = self._value_after_effect_best(
                            node, mask, k, c - 1, r, next_nodes, destroyed)
                        if val > best_val + 1e-9:
                            best_val = val
                            best_decision = ('cheat', k)
                            best_effect = k
                            cost_c = 1
                            if action:
                                best_next_node = action[1]
                                if k == EFFECT_SELECT or k == EFFECT_RANDOM_INFECT:
                                    best_choice = action[2] if len(action) > 2 else None
                                elif k == EFFECT_SPREAD:
                                    best_spread_mask = action[2] if len(action) > 2 else None
                # ---- reroll: 消耗 1r，重新随机 ----
                if r > 0:
                    reroll_val = self.W_best.get((node, mask, c, r - 1), float('-inf'))
                    if reroll_val > best_val + 1e-9:
                        best_decision = 'reroll'
                        r -= 1
                        continue  # 重 roll，不前进节点
            if best_next_node is None:
                break
            # ---- 确定性地应用最佳效果和移动 ----
            cd_before = cd
            dd_nn = self.sim._destroy_masks[best_next_node]
            if first_step and effect_state == "settled":
                effect_cd = 0
                nm_post_effect = mask
            elif best_effect == EFFECT_BONUS:
                effect_cd = self.sim._active_infected(mask, destroyed)
                nm_post_effect = mask
            elif best_effect == EFFECT_ADJACENT:
                effect_cd = 0
                # ADJACENT 在目的位置生效，感染目的地的邻居（不预销毁目的地，move_delta 需要看到感染状态）
                nm_post_effect = mask
                for nb in self.sim._neighbors.get(best_next_node, []):
                    if not ((dd_nn >> nb) & 1):
                        nm_post_effect |= (1 << nb)
            elif best_effect == EFFECT_SELECT:
                effect_cd = 0
                # SELECT 在当前位置生效：存活 = 掩码过滤当前位置销毁
                nm_post_effect = mask & ~destroyed
                if best_choice is not None:
                    nm_post_effect |= (1 << best_choice)
            elif best_effect == EFFECT_RANDOM_INFECT:
                effect_cd = 0
                nm_post_effect = mask & ~destroyed
                if best_choice is not None:
                    nm_post_effect |= (1 << best_choice)
            elif best_effect == EFFECT_SPREAD:
                effect_cd = 0
                nm_post_effect = best_spread_mask if best_spread_mask is not None else mask & ~destroyed
            else:  # EFFECT_NOTHING
                effect_cd = 0
                nm_post_effect = mask
            move_delta = self.sim.move_delta(best_next_node, nm_post_effect)
            cd = cd + effect_cd + move_delta
            new_mask = nm_post_effect & ~dd_nn  # 目的列销毁
            infected_added = new_mask & ~mask
            destroyed_cum |= dd_nn  # 目标列节点全部销毁
            step_no = len(trace) + 1
            trace.append({
                'step': step_no,
                'node_idx': node,
                'node_name': (node_names or {}).get(node,
                    self.sim.node_map.get(node, {}).get('name', '')),
                'observed_first': (
                    None if (first_step and effect_state == "settled") else
                    observed_effect if (first_step and effect_state == "locked") else
                    best_effect
                ),
                'reroll_count': 0,
                'decision': best_decision,
                'locked_effect': best_effect,
                'next_node': best_next_node,
                'cd_before': cd_before,
                'cd_delta': effect_cd + move_delta,
                'cd_after': cd,
                'cheat_rem': c - cost_c,
                'reroll_rem': r,
                'infected_added': infected_added,
                'infected_all': new_mask,        # 当前累计已感染节点
                'destroyed': destroyed_cum,       # 当前累计已销毁节点
            })
            node = best_next_node
            mask = new_mask
            c -= cost_c
            first_step = False
            # r already decremented if reroll was chosen
            if len(trace) > 100:  # 安全保护
                break
        return trace
    def _value_after_effect(self, node: int, mask: int, effect: int, c: int, r: int,
                            next_nodes: list, destroyed: int) -> tuple:
        """应用效果后最优移动。效果先计算，再行走，最后销毁目标列（含目标自身）。"""
        # 截断资源到 DP 求解范围：超出上限的资源边际收益为零
        c = min(c, getattr(self, '_dp_max_c', c))
        r = min(r, getattr(self, '_dp_max_r', r))
        best_val = float('-inf')
        best_action = None
        if effect == EFFECT_BONUS:
            cd_delta = self.sim._active_infected(mask, destroyed)
            for nn in next_nodes:
                fm = mask & ~self.sim._destroy_masks[nn]
                md = self.sim.move_delta(nn, mask)
                future = self.W.get((nn, fm, c, r), 0.0)
                val = cd_delta + md + future
                if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                    best_val = val
                    best_action = (effect, nn)
            return best_val, best_action
        if effect == EFFECT_ADJACENT:
            for nn in next_nodes:
                dd = self.sim._destroy_masks[nn]
                surviving = mask & ~dd
                nm = surviving
                for nb in self.sim._neighbors.get(nn, []):
                    if not ((dd >> nb) & 1):
                        nm |= (1 << nb)
                md = self.sim.move_delta(nn, mask)
                future = self.W.get((nn, nm, c, r), 0.0)
                val = md + future
                if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                    best_val = val
                    best_action = (effect, nn)
            return best_val, best_action
        if effect == EFFECT_NOTHING:
            for nn in next_nodes:
                fm = mask & ~self.sim._destroy_masks[nn]
                md = self.sim.move_delta(nn, mask)
                future = self.W.get((nn, fm, c, r), 0.0)
                val = md + future
                if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                    best_val = val
                    best_action = (effect, nn)
            return best_val, best_action
        if effect == EFFECT_SELECT:
            for nn in next_nodes:
                dd = self.sim._destroy_masks[nn]
                # SELECT 在当前位置生效，使用当前位置的 destroyed 过滤可选目标
                if not (candidates := self.sim._get_uninfected(mask, destroyed)):
                    md = self.sim.move_delta(nn, mask)
                    future = self.W.get((nn, mask & ~dd, c, r), 0.0)
                    val = md + future
                    if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                        best_val = val
                        best_action = (effect, nn, None)
                else:
                    for choice in candidates:
                        nm_effect = mask | (1 << choice)
                        nm_future = nm_effect & ~dd
                        md = self.sim.move_delta(nn, nm_effect)
                        future = self.W.get((nn, nm_future, c, r), 0.0)
                        val = md + future
                        if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                            best_val = val
                            best_action = (effect, nn, choice)
            return best_val, best_action
        if effect == EFFECT_RANDOM_INFECT:
            for nn in next_nodes:
                dd = self.sim._destroy_masks[nn]
                # RANDOM_INFECT 在当前位置生效，使用当前位置的 destroyed 过滤可选目标
                if not (candidates := self.sim._get_uninfected(mask, destroyed)):
                    md = self.sim.move_delta(nn, mask)
                    future = self.W.get((nn, mask & ~dd, c, r), 0.0)
                    val = md + future
                    if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                        best_val = val
                        best_action = (effect, nn)
                else:
                    n_cand = len(candidates)
                    val = 0.0
                    for choice in candidates:
                        nm_effect = mask | (1 << choice)
                        nm_future = nm_effect & ~dd
                        md = self.sim.move_delta(nn, nm_effect)
                        future = self.W.get((nn, nm_future, c, r), 0.0)
                        val += (md + future) / n_cand
                    if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                        best_val = val
                        best_action = (effect, nn)
            return best_val, best_action
        if effect == EFFECT_SPREAD:
            for nn in next_nodes:
                dd = self.sim._destroy_masks[nn]
                # SPREAD 在当前位置生效，使用当前位置的 destroyed 过滤（不是目的地）
                surviving = mask & ~destroyed
                spread_sources, est_product = self.sim._build_spread_sources(surviving, destroyed)
                if not spread_sources:
                    md = self.sim.move_delta(nn, surviving)
                    val = md + self.W.get((nn, surviving & ~dd, c, r), 0.0)
                    if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                        best_val, best_action = val, (effect, nn)
                elif est_product <= 600:
                    all_masks_effect = self.sim._cartesian_spread(surviving, spread_sources)
                    val = sum((self.sim.move_delta(nn, nm) + self.W.get((nn, nm & ~dd, c, r), 0.0))
                              / len(all_masks_effect) for nm in all_masks_effect)
                    if self._better_node(val, nn, best_val, best_action[1] if best_action else None):
                        best_val, best_action = val, (effect, nn)
                else:
                    rng = random.Random(mask + nn * 10007 + c * 100003)
                    n_samples = 400
                    total = 0.0
                    for _ in range(n_samples):
                        nm_effect = surviving
                        for choices in spread_sources:
                            nm_effect |= (1 << rng.choice(choices))
                        total += self.sim.move_delta(nn, nm_effect) + self.W.get((nn, nm_effect & ~dd, c, r), 0.0)
                    if self._better_node(total / n_samples, nn, best_val, best_action[1] if best_action else None):
                        best_val, best_action = total / n_samples, (effect, nn)
            return best_val, best_action
        return best_val, best_action
    def _enumerate_reachable_states(self, max_cheat: int, max_reroll: int,
                                      max_total_states: int = 1500) -> set:
        """BFS 枚举所有可达的 (node, mask) 组合。大图自动限制防爆。"""
        reachable = set()
        masks_per_node = defaultdict(set)
        init_mask = self.sim.initial_state(0, 0).infected
        q = deque()
        q.append((self.sim.start_idx, init_mask))
        reachable.add((self.sim.start_idx, init_mask))
        masks_per_node[self.sim.start_idx].add(init_mask)
        is_large = len(self.sim.nodes) > 18
        per_node_limit = 8 if is_large else 25
        sample_limit = 4 if is_large else 8
        while q:
            node, mask = q.popleft()
            if node not in self.sim.edges or not self.sim.edges[node]:
                continue
            destroyed = self.sim._destroy_masks[node]
            for next_node in self.sim.edges[node]:
                if len(masks_per_node[next_node]) >= per_node_limit:
                    continue
                dest_destroyed = self.sim._destroy_masks[next_node]
                for effect in ALL_EFFECTS:
                    eff_node, eff_destroyed = (node, destroyed) if effect == EFFECT_BONUS else (next_node, dest_destroyed)
                    outcomes = self.sim.apply_effect(
                        mask, effect, eff_node, eff_destroyed, max_outcomes=sample_limit)
                    for new_mask, cd_delta in outcomes:
                        final_mask = new_mask & ~dest_destroyed
                        state_key = (next_node, final_mask)
                        if state_key not in reachable:
                            reachable.add(state_key)
                            masks_per_node[next_node].add(final_mask)
                            if len(reachable) >= max_total_states:
                                return reachable
                            q.append(state_key)
        return reachable
    def evaluate_initial(self, cheat: int, reroll: int, initial_countdown: int = 0) -> dict:
        """评估初始状态的期望倒计时。"""
        init_state = self.sim.initial_state(cheat, reroll, initial_countdown)
        key = (init_state.node_idx, init_state.infected, cheat, reroll)
        future = self.W.get(key, 0.0)
        total = initial_countdown + future
        action = self.policy.get(key)
        return {
            'expected_countdown': total,
            'future_value': future,
            'initial_countdown': initial_countdown,
            'best_first_action': action,
            'num_states': len(self.W),
            'num_reachable_masks': len(set(k[:2] for k in self.W)),
        }
    def _run_one_trial(self, trial_seed: int, cheat: int, reroll: int,
                        initial_countdown: int) -> int:
        """执行单次模拟试验，含多段 reroll 内层循环，返回最终倒计时。"""
        rng = random.Random(trial_seed)
        init_state = self.sim.initial_state(cheat, reroll, initial_countdown)
        state = init_state
        while not self.sim.is_terminal(state):
            node = state.node_idx
            mask = state.infected
            c = state.cheat_rem
            r = state.reroll_rem
            destroyed = self.sim._destroy_masks[node]
            if not (next_nodes := self.sim.edges.get(node, [])):
                break
            observed = rng.randint(1, 6)
            # ---- 效果阶段 (多段 reroll 循环) ----
            while True:
                val_keep, action_keep = self._value_after_effect(
                    node, mask, observed, c, r, next_nodes, destroyed)
                best_val = val_keep
                best_decision = ('keep', observed, action_keep)
                if c > 0:
                    for k in ALL_EFFECTS:
                        val_k, action_k = self._value_after_effect(
                            node, mask, k, c - 1, r, next_nodes, destroyed)
                        if val_k > best_val + 1e-9:
                            best_val = val_k
                            best_decision = ('cheat', k, action_k)
                # 多段 reroll: 期望值 = W[(node, mask, c, r-1)]
                if r > 0:
                    reroll_val = self.W.get((node, mask, c, r - 1), float('-inf'))
                    if reroll_val > best_val + 1e-9:
                        r -= 1
                        observed = rng.randint(1, 6)
                        continue
                break  # keep 或 cheat → 锁定效果
            action_type, effect, action_info = best_decision
            next_node = action_info[1] if action_info else next_nodes[0]
            choice = action_info[2] if action_info and len(action_info) > 2 else None
            dest_destroyed = self.sim._destroy_masks[next_node]
            actual_cd_delta = 0
            if effect == EFFECT_BONUS:
                actual_cd_delta = self.sim._active_infected(mask, destroyed)
                final_mask = mask & ~dest_destroyed
            elif effect == EFFECT_ADJACENT:
                final_mask = (mask & ~dest_destroyed) | sum(
                    (1 << nb for nb in self.sim._neighbors.get(next_node, [])
                     if not ((dest_destroyed >> nb) & 1)), 0)
            elif effect == EFFECT_SELECT:
                final_mask = (mask & ~dest_destroyed) | ((1 << choice) if choice is not None else 0)
            elif effect == EFFECT_RANDOM_INFECT:
                surviving = mask & ~dest_destroyed
                candidates = self.sim._get_uninfected(surviving, dest_destroyed)
                final_mask = surviving | (1 << rng.choice(candidates)) if candidates else surviving
            elif effect == EFFECT_SPREAD:
                nm = surviving = mask & ~dest_destroyed
                for idx in range(len(self.sim.nodes)):
                    if ((surviving >> idx) & 1):
                        nb_uninf = [nb for nb in self.sim._neighbors.get(idx, [])
                                   if not ((surviving >> nb) & 1) and not ((dest_destroyed >> nb) & 1)]
                        if nb_uninf:
                            nm |= (1 << rng.choice(nb_uninf))
                final_mask = nm
            else:
                final_mask = mask & ~dest_destroyed
            state = CountdownState(node_idx=next_node, infected=final_mask,
                                   countdown=state.countdown + actual_cd_delta + self.sim.move_delta(next_node, mask),
                                   cheat_rem=c - 1 if action_type == 'cheat' else c,
                                   reroll_rem=r)
        return state.countdown
    def simulate_with_policy(self, cheat: int, reroll: int, initial_countdown: int = 0,
                             n_trials: int = 2000, seed: int = 42) -> dict:
        """多进程蒙特卡洛模拟，使用最优 ex-post 策略。"""
        seeds = [seed + i * 10007 for i in range(n_trials)]
        n_workers = min(cpu_count(), n_trials, 8)
        task_args = [(s, cheat, reroll, initial_countdown) for s in seeds]
        try:
            with Pool(processes=n_workers, initializer=_init_worker, initargs=(self,)) as pool:
                values = pool.map(_run_trial_worker, task_args)
        except Exception as e:
            print(f'  [WARN] 多进程失败 ({e})，回退到单进程模拟')
            values = [self._run_one_trial(s, cheat, reroll, initial_countdown) for s in seeds]
        mean = sum(values) / n_trials
        var = sum((v - mean) ** 2 for v in values) / (n_trials - 1) if n_trials > 1 else 0
        sorted_vals = sorted(values)
        return {
            'expected_countdown': mean,
            'std': var ** 0.5,
            'p80': sorted_vals[int(n_trials * 0.8)],
            'p50': sorted_vals[n_trials // 2],
            'max': max(values),
            'min': min(values),
        }
# ---- 多进程并行模拟工作函数 ----
_dp_instance = None
def _init_worker(dp):
    """进程池初始化：每个 worker 进程载入 DP 实例（只读）。"""
    global _dp_instance
    _dp_instance = dp
def _run_trial_worker(args):
    """进程池工作函数：执行单次模拟试验。"""
    return _dp_instance._run_one_trial(*args)
# ---- W 表持久化 ----
def _map_hash(nodes: list, edges: dict, start_idx: int, infectable: set) -> str:
    """生成地图的唯一标识（用于缓存键）。"""
    data = {
        'nodes': [(n['idx'], n['cx'], n['cy'], n.get('name', '')) for n in nodes],
        'edges': {str(k): sorted(v) for k, v in sorted(edges.items())},
        'start_idx': start_idx,
        'infectable': sorted(infectable),
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
def _cache_dir():
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cache')
    os.makedirs(d, exist_ok=True)
    return d
def save_w_table(nodes, edges, start_idx, infectable, w_table, label=''):
    """保存 W 表到缓存文件。"""
    h = _map_hash(nodes, edges, start_idx, infectable)
    path = os.path.join(_cache_dir(), f'w_{h}.json')
    label_path = os.path.join(_cache_dir(), f'w_{h}_label.txt')
    serializable = {f'{c},{r}': round(v, 4) for (c, r), v in w_table.items()}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(serializable, f, ensure_ascii=False)
    with open(label_path, 'w', encoding='utf-8') as f:
        f.write(label)
    print(f'  W表已保存: {path} ({label})', flush=True)
    return h
def load_w_table(nodes, edges, start_idx, infectable):
    """从缓存加载 W 表，不存在或条目过少（不完整）则返回 None。"""
    h = _map_hash(nodes, edges, start_idx, infectable)
    path = os.path.join(_cache_dir(), f'w_{h}.json')
    label_path = os.path.join(_cache_dir(), f'w_{h}_label.txt')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if len(raw) < 20:
            return None, ''
        w_table = {}
        for k, v in raw.items():
            c_str, r_str = k.split(',')
            w_table[(int(c_str), int(r_str))] = v
        label = ''
        if os.path.exists(label_path):
            with open(label_path, 'r', encoding='utf-8') as f:
                label = f.read().strip()
        return w_table, label
    return None, ''
# 各平面典型地图（用于估算跨平面资源保留价值）
_TYPICAL_MAP_FILES = {
    1: '20260616_114926.png',
    2: '20260616_115208.png',
    3: '20260616_115639.png',
}
def _get_w_table_for_image(image_path: str, max_cheat: int, max_reroll: int,
                            n_train: int = 15000, n_eval: int = 300,
                            use_cache: bool = True, verbose: bool = False,
                            match_mode: int = 1) -> dict:
    """处理一张地图图像并返回其 W 表 {(c,r): cd_gain}（优先读缓存）。

    这是一个内部辅助函数，供 analyze_single_map 自动构建 future_table 使用。
    """
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f'无法读取图像: {image_path}')
    matches = match_multiple_targets(img, mode=match_mode)
    detect_infectable_nodes(img, matches)
    if (boss_head_x := [m['location'][0] for m in matches if m['name'] in ('boss', 'head')]):
        matches = [m for m in matches if m['location'][0] <= max(boss_head_x)]
    leftmost_x = min((m['location'][0] + m['size'][0] / 2 for m in matches), default=0) if matches else 0
    start = None
    for mode, th in [(2, 0.9), (3, 0.9), (2, 0.4), (3, 0.4)]:
        candidate = compute_start_point_from_crop(img, mode=mode, th=th)
        if candidate is None:
            continue
        if candidate[0] > leftmost_x + 50:
            continue
        start = candidate
        break
    if start is None:
        leftmost = min(matches, key=lambda m: m['location'][0])
        start = (leftmost['location'][0] + leftmost['size'][0] / 2,
                leftmost['location'][1] + leftmost['size'][1] / 2)
    nodes, edges, start_idx = build_rightward_graph(matches, start=start)
    _, _, _ = max_weight_path(nodes, edges, start_idx)
    infectable = {i for i, m in enumerate(matches) if m.get('infectable', False)}
    # 每步至多消耗 1 资源，以 DAG 最长路径步数封顶
    # 使用 DAG 最长路径 DP（按步数，非权重），避免 max_weight_path 因
    # start 与最近节点 gap 过大返回空路径时 fallback 到 len(nodes) 的错误
    def _dag_longest_steps(nodes, edges, start_idx):
        node_map = {n['idx']: n for n in nodes}
        ordered = sorted(node_map, key=lambda i: node_map[i]['cx'])
        dp = {i: float('-inf') for i in ordered}
        dp[start_idx] = 1
        for idx in ordered:
            if dp[idx] != float('-inf'):
                for c in edges.get(idx, []):
                    dp[c] = max(dp[c], dp[idx] + 1)
        return (max(vals) - 1) if (vals := [v for v in dp.values() if v != float('-inf')]) else 0
    longest = _dag_longest_steps(nodes, edges, start_idx)
    if longest <= 0:
        # start 检测可能偏离实际节点（gap 过大导致无边），回退到最左端匹配节点
        leftmost = min(range(len(nodes)), key=lambda i: nodes[i]['cx'])
        longest = _dag_longest_steps(nodes, edges, leftmost)
    max_steps = longest
    useful = min(max_steps, max_cheat, max_reroll)
    # 优先读缓存
    if use_cache:
        w_table, cached_label = load_w_table(nodes, edges, start_idx, infectable)
        if w_table is not None:
            if verbose:
                print(f'  [future_table] W表缓存命中 ({cached_label}), '
                      f'{len(w_table)} entries', flush=True)
            return w_table
    if verbose:
        print(f'  [future_table] 估算典型地图 W 表 ({len(nodes)}节点, '
              f'{max_steps}步)...', flush=True)
    _t0 = time.time()
    sim = MapSimulator(nodes, edges, start_idx, infectable)
    mc = MonteCarloOptimizer(sim)
    w_table = mc.estimate_w_table(max_cheat, max_reroll,
                                   n_train=n_train, n_eval=n_eval,
                                   max_useful=useful)
    if verbose:
        print(f'  [future_table] W表完成 ({time.time()-_t0:.1f}s)', flush=True)
    save_w_table(nodes, edges, start_idx, infectable, w_table,
                  os.path.basename(image_path))
    return w_table
# ---- 单图分析封装 ----
def analyze_single_map(image_path: str = None, *,
                        nodes: list = None, edges: dict = None,
                        start_idx: int = None, infectable: set = None,
                        cheat: int = 0, reroll: int = 0,
                        initial_countdown: int = 0,
                        observed_effect: int = None,
                        effect_state: str = "unlocked",
                        plane: int = None,
                        future_table: dict = None,
                        target_cd: float = None,
                        n_train: int = 15000, n_eval: int = 300,
                        n_sim_trials: int = 2000,
                        use_cache: bool = True,
                        label: str = '',
                        verbose: bool = True,
                        match_mode: int = 1) -> dict:
    """单张地图完整分析 — 从图像或预构建图出发，训练 MC 策略并评估。

    两种用法:
      1. image_path → 自动检测节点/边/传染/起点
      2. nodes + edges + start_idx + infectable → 跳过图像处理

    Returns:
        dict 含 w_table, analysis, recommended_action, decision_analysis, 等
    """
    _times.clear()
    _t0_total = time.time()

    # ---- 计时闭包（全部 @_timed，置顶定义） ----

    @_timed
    def _img_read_and_match():
        _img = cv2.imread(image_path)
        if _img is None:
            raise FileNotFoundError(f'无法读取图像: {image_path}')
        return _img, match_multiple_targets(_img, mode=match_mode)

    @_timed
    def _img_detect_infectable():
        detect_infectable_nodes(img, matches)

    @_timed
    def _img_detect_start():
        ms = matches
        if (boss_head_x := [m['location'][0] for m in ms if m['name'] in ('boss', 'head')]):
            ms = [m for m in ms if m['location'][0] <= max(boss_head_x)]
        _lx = min((m['location'][0] + m['size'][0] / 2 for m in ms), default=0) if ms else 0
        _st = None
        if plane is not None:
            sp_mode = 3 if plane == 3 else 2
            for th in (0.9, 0.4):
                c = compute_start_point_from_crop(img, mode=sp_mode, th=th)
                if c is None or c[0] > _lx + 50:
                    continue
                _st = c
                break
            if _st is None:
                fallback_mode = 2 if sp_mode == 3 else 3
                for th in (0.9, 0.4):
                    c = compute_start_point_from_crop(img, mode=fallback_mode, th=th)
                    if c is None or c[0] > _lx + 50:
                        continue
                    _st = c
                    break
        else:
            for mode, th in [(2, 0.9), (3, 0.9), (2, 0.4), (3, 0.4)]:
                c = compute_start_point_from_crop(img, mode=mode, th=th)
                if c is None or c[0] > _lx + 50:
                    continue
                _st = c
                break
        if _st is None:
            lm = min(ms, key=lambda m: m['location'][0])
            _st = (lm['location'][0] + lm['size'][0] / 2,
                   lm['location'][1] + lm['size'][1] / 2)
        return ms, _st, _lx

    @_timed
    def _img_build_graph():
        nds, eds, sidx = build_rightward_graph(matches, start=start)
        _st = start
        if not eds.get(sidx) and plane is not None:
            fallback_mode = 2 if plane == 3 else 3
            for th in (0.9, 0.4):
                c = compute_start_point_from_crop(img, mode=fallback_mode, th=th)
                if c is None or c[0] > leftmost_x + 50:
                    continue
                fb_n, fb_e, fb_s = build_rightward_graph(matches, start=c)
                if fb_e.get(fb_s):
                    nds, eds, sidx = fb_n, fb_e, fb_s
                    _st = c
                    break
        return nds, eds, sidx, _st

    @_timed
    def _img_max_weight_path():
        _, _, _ = max_weight_path(nodes, edges, start_idx)

    @_timed
    def _img_visualize():
        save_fname = f'{image_path[:-4]}_annotated.png'
        display_matches(img, matches, save_path=save_fname, show=False,
                       start_idx=start_idx, start_coord=start)

    @_timed
    def _sim_init():
        return MapSimulator(nodes, edges, start_idx, infectable)

    @_timed
    def _w_cache_load():
        return load_w_table(nodes, edges, start_idx, infectable)

    @_timed
    def _w_mc_init():
        return MonteCarloOptimizer(sim)

    @_timed
    def _w_estimate_table():
        return mc_w.estimate_w_table(cheat if cheat > 0 else 25,
                                      reroll if reroll > 0 else 150,
                                      n_train=n_train, n_eval=n_eval)

    @_timed
    def _w_cache_save():
        save_w_table(nodes, edges, start_idx, infectable, w_table, label)

    @_timed
    def _build_future_table():
        nonlocal future_table
        example_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'example')
        subs = []
        for p in range(plane + 1, 4):
            fpath = os.path.join(example_dir, _TYPICAL_MAP_FILES.get(p, ''))
            if not fpath or not os.path.exists(fpath):
                continue
            if verbose:
                print(f'[analyze_single_map] 加载位面{p}典型地图W表: '
                      f'{os.path.basename(fpath)}', flush=True)
            wt = _get_w_table_for_image(fpath, max_cheat=use_c, max_reroll=use_r,
                                         n_train=n_train, use_cache=use_cache,
                                         verbose=verbose)
            subs.append(wt)
        if subs:
            future_table = build_future_table(subs, max_cheat=use_c, max_reroll=use_r)
            if verbose:
                print(f'[analyze_single_map] future_table已构建 '
                      f'({len(subs)}个后续位面, {len(future_table)} entries)', flush=True)

    @_timed
    def _dp_mc_init():
        return MonteCarloOptimizer(sim)

    @_timed
    def _dp_solve():
        dp = ExactCountdownDP(sim)
        dp.solve(max_cheat=use_c, max_reroll=use_r, future_table=future_table)
        return dp

    @_timed
    def _dp_warm_rollout():
        mc.warm_start_from_dp(dp_warm, cheat=use_c, reroll=use_r,
                               n_rollouts=max(1000, n_train // 5), epsilon=0.25)

    @_timed
    def _dp_warm_start():
        nonlocal mc, dp_warm
        mc = _dp_mc_init()
        mc._initial_observed_effect = observed_effect
        mc._initial_effect_state = effect_state
        dp_warm = _dp_solve()
        _dp_warm_rollout()

    @_timed
    def _mc_train():
        mc.train(cheat=use_c, reroll=use_r, n_rollouts=n_train, epsilon=0.15,
                 future_table=future_table)

    @_timed
    def _eval_resource():
        return mc.evaluate(cheat=cheat, reroll=reroll,
                          n_rollouts=n_sim_trials, seed=42,
                          future_table=future_table,
                          node_names=node_name_map)

    @_timed
    def _eval_zero_resource():
        return mc.evaluate(cheat=0, reroll=0,
                          n_rollouts=n_sim_trials // 2, seed=99,
                          future_table=future_table,
                          node_names=node_name_map)

    @_timed
    def _analyze_decision():
        _dt = mc.analyze_decision(init_state, node_names=node_name_map)
        rec = mc.get_action(init_state)
        if rec is None:
            _rs = 'keep (未探索)'
        else:
            eff, nn = rec
            _name = node_name_map.get(nn, '')
            _nnl = f'{_name}#{nn}' if _name else str(nn)
            if eff is None:
                ev = init_state.observed_effect or 0
                _rs = f'→{_nnl} (效果已锁定: {EFFECT_NAMES.get(ev, str(ev))})'
            elif eff == 'keep':
                _rs = f'→{_nnl} + keep'
            elif eff == 'reroll':
                _rs = f'→{_nnl} + reroll'
            elif isinstance(eff, tuple) and eff[0] == 'cheat':
                _rs = f'→{_nnl} + cheat→{EFFECT_NAMES.get(eff[1], eff[1])}'
            elif isinstance(eff, int):
                tn = node_name_map.get(eff, '')
                tl = f'{tn}#{eff}' if tn else str(eff)
                _rs = f'→{_nnl} (慈怀感染: {tl})'
            else:
                _rs = f'→{_nnl} + {eff}'
        return _dt, _rs

    @_timed
    def _sim_win_rate():
        wc = 0
        wrng = random.Random(42)
        for _ in range(n_sim_trials):
            st = sim.initial_state(cheat, reroll, initial_countdown,
                                    observed_effect=observed_effect,
                                    effect_state=effect_state)
            while not sim.is_terminal(st):
                if not (nn_list := mc.sim.edges.get(st.node_idx, [])):
                    break
                if st.effect_state == "settled":
                    locked = st.observed_effect
                    cost_c = 0
                    skip_eff = True
                else:
                    skip_eff = False
                    obs = st.observed_effect if st.effect_state == "locked" else wrng.randint(1, 6)
                    sk = mc._state_key(st)
                    while True:
                        eff_acts = mc._get_effect_actions(st)
                        eff = mc._greedy_effect(sk, obs, eff_acts, wrng)
                        if eff == 'reroll':
                            st = CountdownState(node_idx=st.node_idx, infected=st.infected,
                                                 countdown=st.countdown,
                                                 cheat_rem=st.cheat_rem,
                                                 reroll_rem=st.reroll_rem - 1)
                            obs = wrng.randint(1, 6)
                            sk = mc._state_key(st)
                            continue
                        locked, cost_c = (obs, 0) if eff == 'keep' else (eff[1], 1)
                        break
                sk_locked = mc._state_key(st)
                nn = (mc._dp_path_fallback(st, locked, nn_list, wrng)
                      if not mc.Q_path.get((sk_locked, locked))
                      else mc._greedy_path(sk_locked, locked, nn_list, wrng))
                st = mc._apply_and_move(st, locked, nn, cost_c, 0, wrng,
                                         skip_effect_apply=skip_eff)
            if st.countdown >= target_cd:
                wc += 1
        return wc / n_sim_trials

    @_timed
    def _dp_max_path():
        im = sim.initial_state(0, 0, observed_effect=observed_effect,
                                effect_state=effect_state).infected
        nns = sim.edges.get(start_idx, [])
        dstr = dp_warm.sim._destroy_masks.get(start_idx, 0)
        if effect_state == "settled":
            v, _ = dp_warm._value_after_effect_best(
                start_idx, im, EFFECT_NOTHING, cheat, reroll, nns, dstr)
            mv = v if v > float('-inf') else None
        elif effect_state == "locked":
            bv = float('-inf')
            vk, _ = dp_warm._value_after_effect_best(
                start_idx, im, observed_effect, cheat, reroll, nns, dstr)
            if vk > bv:
                bv = vk
            if cheat > 0:
                for k in ALL_EFFECTS:
                    vc, _ = dp_warm._value_after_effect_best(
                        start_idx, im, k, cheat - 1, reroll, nns, dstr)
                    if vc > bv:
                        bv = vc
            if reroll > 0:
                vr = dp_warm.W_best.get((start_idx, im, cheat, reroll - 1), float('-inf'))
                if vr > bv:
                    bv = vr
            mv = bv if bv > float('-inf') else None
        else:
            mv = dp_warm.W_best.get((start_idx, im, cheat, reroll), None)
        if mv is not None:
            print(f'\n  --- DP极限最大路径 (max={initial_countdown + mv:.0f} cd) ---')
            bp = dp_warm.trace_best_path(start_idx, im, initial_countdown, cheat, reroll,
                                          observed_effect=observed_effect,
                                          effect_state=effect_state,
                                          node_names=node_name_map)
            print(MonteCarloOptimizer._format_best_trace(bp, node_name_map))
        else:
            print('\n  --- DP极限最大路径: 无数据 ---')

    # ============================================================
    # 执行区
    # ============================================================

    if image_path is not None:
        img, matches = _img_read_and_match()
        _img_detect_infectable()
        matches, start, leftmost_x = _img_detect_start()
        nodes, edges, start_idx, start = _img_build_graph()
        _img_max_weight_path()
        infectable = {i for i, m in enumerate(matches) if m.get('infectable', False)}
        if not label:
            label = os.path.basename(image_path)
        _img_visualize()
    elif nodes is not None and edges is not None and start_idx is not None and infectable is not None:
        if not label:
            label = f'{len(nodes)}节点图'
    else:
        raise ValueError('必须提供 image_path 或 (nodes, edges, start_idx, infectable)')

    sim = _sim_init()

    w_table = None
    if use_cache:
        w_table, cached_label = _w_cache_load()
        if w_table is not None and verbose:
            print(f'[analyze_single_map] W表缓存命中 ({cached_label}), '
                  f'{len(w_table)} entries', flush=True)
    if w_table is None:
        if verbose:
            print('[analyze_single_map] 训练MC W表...', flush=True)
        _t0 = time.time()
        mc_w = _w_mc_init()
        w_table = _w_estimate_table()
        if verbose:
            print(f'[analyze_single_map] W表完成 ({time.time()-_t0:.1f}s)', flush=True)
        if use_cache:
            _w_cache_save()

    use_c = max(cheat, 5)
    use_r = max(reroll, 10)
    if plane is not None and future_table is None and 1 <= plane <= 3:
        _build_future_table()

    _t0 = time.time()
    mc = None
    dp_warm = None
    _dp_warm_start()
    if verbose:
        print(f'[analyze_single_map] DP热启动完成 ({time.time()-_t0:.1f}s)', flush=True)

    if verbose:
        print(f'[analyze_single_map] 训练MC策略 (cheat={use_c}, reroll={use_r})...', flush=True)
    _t0 = time.time()
    _mc_train()
    if verbose:
        print(f'[analyze_single_map] 策略训练完成 ({time.time()-_t0:.1f}s)', flush=True)
        print('  [train内部耗时]')
        print(_fmt(mc._train_times, ['_greedy_effect', '_greedy_path', '_apply_and_move',
                                      '_dp_effect_value', '_reroll_value', 'backprop']))

    node_name_map = {n['idx']: n.get('name', str(n['idx'])) for n in nodes}
    eval_result = _eval_resource()
    eval_zero = _eval_zero_resource()

    init_state = sim.initial_state(use_c, use_r, initial_countdown,
                                    observed_effect=observed_effect,
                                    effect_state=effect_state)
    decision_text, recommended_str = _analyze_decision()

    win_rate = None
    if target_cd is not None:
        win_rate = _sim_win_rate()

    if verbose:
        print(f'\n{"="*60}')
        print(f'单图分析: {label}')
        print(f'{"="*60}')
        print(f'  节点数: {len(nodes)}  传染节点: {len(infectable)}')
        print(f'  资源配置: cheat={cheat}  reroll={reroll}  init_cd={initial_countdown}')
        print(f'  Q表状态数: {len(mc.Q_effect)} + {len(mc.Q_path)}')
        print(f'  期望最终CD: {eval_result["mean"]:.2f} ± {eval_result["std"]:.2f}  '
              f'(n={eval_result["n_rollouts"]})')
        print(f'  P50={eval_result["p50"]:.0f}  P80={eval_result["p80"]:.0f}  '
              f'max={eval_result["max"]:.0f}  min={eval_result["min"]:.0f}')
        print(f'  零资源基线: {eval_zero["mean"]:.2f}  '
              f'(资源增益: {eval_result["mean"] - eval_zero["mean"]:+.2f})')
        if win_rate is not None:
            print(f'  目标 {target_cd}: 胜率 {win_rate*100:.4f}%  '
                  f'({"可达" if win_rate > 0 else "不可达"})')
        print(f'  推荐首步: {recommended_str}')
        _dp_max_path()
        print(f'\n{decision_text}')

    total_elapsed = time.time() - _t0_total
    if verbose:
        print(f'\n{"="*60}')
        print(f'[Timing] analyze_single_map 各阶段耗时 ({label}):')
        print(f'{"="*60}')
        print(_fmt(_times))
        if total_elapsed > 0:
            print(f'  {"TOTAL":<35s} {total_elapsed:8.3f}s')
    return {
        'label': label,
        'nodes': nodes, 'edges': edges, 'start_idx': start_idx, 'infectable': infectable,
        'sim': sim, 'mc': mc,
        'w_table': w_table,
        'eval': eval_result,
        'eval_zero': eval_zero,
        'resource_gain': eval_result['mean'] - eval_zero['mean'],
        'recommended_action': recommended_str,
        'decision_analysis': decision_text,
        'win_rate': win_rate,
        'target_cd': target_cd,
        'num_q_states': len(mc.Q_effect) + len(mc.Q_path),
        'future_table': future_table,
    }
