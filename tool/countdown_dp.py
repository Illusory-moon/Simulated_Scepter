"""倒计时地图的最佳情形 DP 旁路分析器。

该模块只计算"所有环境随机结果均取最有利值"时的理论最大最终 CD，供 GUI
展示上限、路径和感染点；它不读取、修改或热启动纯 MC 控制器。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from heapq import heapify, heappop, heappush
from itertools import combinations
from typing import Callable, Mapping, Optional

from tool.countdown_evaluator import (
    ALL_EFFECTS, CountdownMap, CountdownState, DecisionContext,
    EFFECT_ADJACENT, EFFECT_BONUS, EFFECT_NOTHING, EFFECT_RANDOM_INFECT,
    EFFECT_SELECT, EFFECT_SPREAD, PHASE_EFFECT, PHASE_PATH, PHASE_TARGET,
    PHASE_TERMINAL,
)


@dataclass(frozen=True, slots=True)
class DPBestStep:
    node_idx: int
    effect_action: object
    effect: int
    next_node: int
    countdown_delta: int
    effect_countdown_delta: int
    move_countdown_delta: int
    infected_added: tuple[int, ...]
    countdown_before: int
    countdown_after: int
    infected_before: int
    infected_after: int
    cheat_before: int
    cheat_after: int
    reroll_before: int
    reroll_after: int


@dataclass(frozen=True, slots=True)
class DPBestResult:
    max_countdown: int
    path: tuple[int, ...]
    infection_nodes: tuple[int, ...]
    steps: tuple[DPBestStep, ...]
    states_evaluated: int


@dataclass(frozen=True, slots=True)
class _Plan:
    state: CountdownState
    parent: Optional["_Plan"] = None
    effect_action: object = None
    effect: int = 0
    effect_delta: int = 0
    added_mask: int = 0
    cheat_used: int = 0
    reroll_used: int = 0
    path_bonus: float = 0.0


class ExactCountdownDP:
    """从当前确定上下文求最有利随机结果下的理论最大 CD。"""

    def __init__(self, countdown_map: CountdownMap, max_states: int = 250_000,
                 max_spread_outcomes: int = 50_000,
                 cancelled: Optional[Callable[[], bool]] = None,
                 path_bonuses: Optional[Mapping[str, float]] = None):
        self.map = countdown_map
        self.max_states = max(1, int(max_states))
        self.max_spread_outcomes = max(1, int(max_spread_outcomes))
        self.cancelled = cancelled
        self.path_bonuses = dict(path_bonuses or {})
        self.states_evaluated = 0
        indegree = {node: 0 for node in self.map.node_map}
        for targets in self.map.edges.values():
            for target in targets:
                indegree[target] += 1
        ready = [(self.map.columns[node], node) for node, degree in indegree.items()
                 if not degree]
        heapify(ready)
        order = []
        while ready:
            _, node = heappop(ready)
            order.append(node)
            for target in self.map.edges[node]:
                indegree[target] -= 1
                if not indegree[target]:
                    heappush(ready, (self.map.columns[target], target))
        if len(order) != len(indegree):
            raise ValueError("地图包含环，倒计时 DP 仅支持 DAG")
        self._topological_order = tuple(order)

    def _checkpoint(self) -> None:
        if self.cancelled and self.cancelled():
            raise InterruptedError("DP 计算已取消")

    @staticmethod
    def _plan_key(plan: _Plan) -> tuple:
        return (-(plan.state.countdown + plan.path_bonus),
                plan.cheat_used + plan.reroll_used,
                plan.cheat_used, plan.reroll_used)

    def _spread_path_outcomes(self, state: CountdownState):
        """按路径逐组生成仍可区分的浇灌结果，并保留合法感染见证。"""
        origin_future = self.map.future_masks[state.node_idx]
        sources = state.infected & origin_future
        raw_groups = {}
        while sources:
            self._checkpoint()
            source_bit = sources & -sources
            source = source_bit.bit_length() - 1
            candidates = (self.map.neighbor_masks[source]
                          & origin_future & ~state.infected)
            if candidates:
                raw_groups[candidates] = raw_groups.get(candidates, 0) + 1
            sources ^= source_bit

        for next_node in self.map.path_options(state):
            relevant = self.map.future_masks[next_node] | 1 << next_node
            groups, irrelevant_witness = {}, 0
            for candidates, source_count in raw_groups.items():
                projected = candidates & relevant
                if projected:
                    groups[projected] = groups.get(projected, 0) + source_count
                else:
                    irrelevant_witness |= candidates & -candidates
            outcomes = {state.infected & relevant: irrelevant_witness}
            for candidates, source_count in groups.items():
                bits, rest = [], candidates
                while rest:
                    bit = rest & -rest
                    bits.append(bit)
                    rest ^= bit
                combined, largest, checked = {}, -1, 0
                for selected in combinations(bits, min(source_count, len(bits))):
                    choice = sum(selected)
                    for mask, witness in outcomes.items():
                        new_mask, new_witness = mask | choice, witness | choice
                        checked += 1
                        if (checked & 1023) == 0:
                            self._checkpoint()
                        size = new_mask.bit_count()
                        if size < largest:
                            continue
                        if size > largest:
                            combined.clear()
                            largest = size
                        previous = combined.get(new_mask)
                        if previous is None or new_witness < previous:
                            combined[new_mask] = new_witness
                outcomes = combined
                if len(outcomes) > self.max_spread_outcomes:
                    raise RuntimeError(
                        f"浇灌非支配组合超过安全上限 {self.max_spread_outcomes:,}")
            yield next_node, outcomes

    def _offer(self, pending: Optional[dict], plan: _Plan, action: object,
               effect: int, effect_delta: int, next_node: int,
               infected: int, countdown: int, added_mask: int) -> Optional[_Plan]:
        path_bonus = plan.path_bonus + self.path_bonuses.get(
            str(self.map.node_map[next_node].get("name", "")), 0.0)
        if pending is not None:
            plans = pending.get(next_node)
            if plans is None:
                plans = pending[next_node] = {}
            same = plans.get(infected)
            if same and (same.state.countdown + same.path_bonus > countdown + path_bonus or (
                    same.state.countdown + same.path_bonus == countdown + path_bonus
                    and (same.cheat_used + same.reroll_used,
                         same.cheat_used, same.reroll_used) <= (
                         plan.cheat_used + plan.reroll_used,
                         plan.cheat_used, plan.reroll_used))):
                return None
        child = _Plan(
            CountdownState(next_node, infected, countdown, 0, 0),
            plan, action, effect, effect_delta, added_mask,
            plan.cheat_used, plan.reroll_used, path_bonus)
        if pending is not None:
            plans[infected] = child
        return child

    def _expand(self, plan: _Plan, effect: int, action: object,
                outcomes=None, pending: Optional[dict] = None):
        origin = plan.state
        if outcomes is None and effect == EFFECT_SPREAD:
            for next_node, spread_outcomes in self._spread_path_outcomes(origin):
                surviving = self.map.future_masks[next_node]
                for projected, witness in spread_outcomes.items():
                    countdown = origin.countdown + (
                        1 if projected & 1 << next_node else -3)
                    child = self._offer(
                        pending, plan, action, effect, 0, next_node,
                        projected & surviving, countdown, witness)
                    if child is not None:
                        yield child
            return
        if outcomes is None and effect in (EFFECT_SELECT, EFFECT_RANDOM_INFECT):
            available = self.map.future_masks[origin.node_idx] & ~origin.infected
            for next_node in self.map.path_options(origin):
                next_bit, surviving = 1 << next_node, self.map.future_masks[next_node]
                base = origin.infected & surviving
                future_targets = available & surviving
                targets = []
                while future_targets:
                    bit = future_targets & -future_targets
                    targets.append((base | bit, origin.countdown + (
                        1 if origin.infected & next_bit else -3), bit))
                    future_targets ^= bit
                if available & next_bit:
                    targets.append((base, origin.countdown + 1, next_bit))
                elif not targets:
                    destroyed = available & ~(surviving | next_bit)
                    targets.append((base, origin.countdown + (
                        1 if origin.infected & next_bit else -3),
                                    destroyed & -destroyed))
                for infected, countdown, selected in targets:
                    child = self._offer(
                        pending, plan, action, effect, 0, next_node,
                        infected, countdown, selected)
                    if child is not None:
                        yield child
            return
        if outcomes is None:
            effect_delta = (self.map.active_infected_count(origin)
                            if effect == EFFECT_BONUS else 0)
            for next_node in self.map.path_options(origin):
                adjacent = (self.map.neighbor_masks[next_node]
                            & ~self.map.destroy_masks[origin.node_idx]
                            & ~origin.infected
                            if effect == EFFECT_ADJACENT else 0)
                mask = origin.infected | adjacent
                countdown = origin.countdown + effect_delta + (
                    1 if mask & 1 << next_node else -3)
                child = self._offer(
                    pending, plan, action, effect, effect_delta, next_node,
                    mask & self.map.future_masks[next_node], countdown, adjacent)
                if child is not None:
                    yield child
            return
        for mask, effect_delta, selected in outcomes:
            post = CountdownState(
                origin.node_idx, mask, origin.countdown + effect_delta, 0, 0)
            selected_mask = sum(1 << idx for idx in selected)
            for next_node in self.map.path_options(post):
                self._checkpoint()
                adjacent_added = (self.map.neighbor_masks[next_node]
                                  & ~self.map.destroy_masks[origin.node_idx]
                                  & ~origin.infected
                                  if effect == EFFECT_ADJACENT else 0)
                moved = self.map.move(post, next_node, effect)
                child = self._offer(
                    pending, plan, action, effect, effect_delta, next_node,
                    moved.infected, moved.countdown,
                    moved.infected & ~origin.infected | adjacent_added | selected_mask)
                if child is not None:
                    yield child

    def _first_plans(self, context: DecisionContext, state: CountdownState):
        if context.phase == PHASE_EFFECT:
            observed = context.observed_effect
            if observed not in ALL_EFFECTS:
                raise ValueError("效果阶段缺少实际观察效果")
            choices = {observed: ("keep", 0, 0)}
            if context.state.cheat_rem:
                choices.update(
                    (effect, (("cheat", effect), 1, 0))
                    for effect in ALL_EFFECTS if effect != observed)
            if context.state.reroll_rem:
                for effect in ALL_EFFECTS:
                    candidate = ("reroll", 0, 1)
                    if effect not in choices or candidate[1:] < choices[effect][1:]:
                        choices[effect] = candidate
            for effect, (action, cheat, reroll) in choices.items():
                for plan in self._expand(_Plan(state), effect, action):
                    yield replace(plan, cheat_used=cheat, reroll_used=reroll)
        elif context.phase == PHASE_TARGET:
            yield from self._expand(_Plan(state), EFFECT_SELECT, "选择感染点")
        elif context.phase == PHASE_PATH:
            effect = context.locked_effect or EFFECT_NOTHING
            yield from self._expand(
                _Plan(state), effect, "已结算", ((state.infected, 0, ()),))
        else:
            raise ValueError(f"未知决策阶段: {context.phase}")

    def _pareto_frontier(self, plans: dict) -> dict:
        """按 CD 降序批量构造稀疏感染集合反链，避免逐状态反复全表扫描。"""
        ordered = sorted(
            plans.values(),
            key=lambda plan: (
                -(plan.state.countdown + plan.path_bonus),
                -plan.state.infected.bit_count(),
                *self._plan_key(plan)[1:], plan.state.infected))
        frontier, postings = {}, {}
        for index, plan in enumerate(ordered):
            if (index & 1023) == 0:
                self._checkpoint()
            mask, bits, rest = plan.state.infected, [], plan.state.infected
            while rest:
                bit = rest & -rest
                bits.append(bit)
                rest ^= bit
            arrays = [postings.get(bit) for bit in bits]
            dominated = bool(frontier) if not bits else not any(
                array is None for array in arrays)
            if dominated and bits:
                dominated = False
                for block in range(min(map(len, arrays))):
                    matches = arrays[0][block]
                    for array in arrays[1:]:
                        matches &= array[block]
                        if not matches:
                            break
                    if matches:
                        dominated = True
                        break
            if dominated:
                continue
            frontier[mask] = plan
            slot, flag = len(frontier) - 1, 1 << ((len(frontier) - 1) & 2047)
            block = slot >> 11
            for bit in bits:
                blocks = postings.setdefault(bit, [])
                if len(blocks) <= block:
                    blocks.extend([0] * (block + 1 - len(blocks)))
                blocks[block] |= flag
        self.states_evaluated += len(frontier)
        if self.states_evaluated > self.max_states:
            raise RuntimeError(f"DP 非支配状态超过安全上限 {self.max_states:,}")
        return frontier

    def solve(self, context: DecisionContext) -> DPBestResult:
        """返回当前上下文在最有利随机结果下的最大 CD 与一条实现轨迹。"""
        source = context.state
        if context.phase == PHASE_TERMINAL:
            return DPBestResult(source.countdown, (source.node_idx,), (), (), 0)
        state = CountdownState(source.node_idx, source.infected, 0, 0, 0)
        pending = {}
        for plan in self._first_plans(context, state):
            plans = pending.setdefault(plan.state.node_idx, {})
            same = plans.get(plan.state.infected)
            if same is None or self._plan_key(plan) < self._plan_key(same):
                plans[plan.state.infected] = plan

        terminals = []
        for node in self._topological_order:
            self._checkpoint()
            candidates = pending.pop(node, None)
            if not candidates:
                continue
            frontier = self._pareto_frontier(candidates)
            if not self.map.edges[node]:
                terminals.extend(frontier.values())
                continue
            for plan in frontier.values():
                # 最有利结果下"归心"等价于"慈怀"，"可憎"又被慈怀弱支配。
                for effect in (EFFECT_SPREAD, EFFECT_BONUS,
                               EFFECT_ADJACENT, EFFECT_SELECT):
                    for _ in self._expand(plan, effect, "keep", pending=pending):
                        pass
        if not terminals:
            raise RuntimeError("DP 未找到可到达的终点")
        best = min(terminals, key=self._plan_key)
        compact_steps, cursor = [], best
        while cursor.parent is not None:
            compact_steps.append(cursor)
            cursor = cursor.parent
        compact_steps.reverse()
        raw_steps = []
        for plan in compact_steps:
            origin, moved = plan.parent.state, plan.state
            raw_steps.append(DPBestStep(
                origin.node_idx, plan.effect_action, plan.effect, moved.node_idx,
                moved.countdown - origin.countdown,
                plan.effect_delta,
                moved.countdown - origin.countdown - plan.effect_delta,
                tuple(idx for idx in self.map.node_map
                      if (plan.added_mask >> idx) & 1),
                origin.countdown, moved.countdown,
                origin.infected, moved.infected, 0, 0, 0, 0))
        cheat, reroll, steps = source.cheat_rem, source.reroll_rem, []
        for step in raw_steps:
            cheat_before, reroll_before = cheat, reroll
            if isinstance(step.effect_action, tuple) and step.effect_action[0] == "cheat":
                cheat -= 1
            elif step.effect_action == "reroll":
                reroll -= 1
            steps.append(replace(
                step,
                countdown_before=source.countdown + step.countdown_before,
                countdown_after=source.countdown + step.countdown_after,
                cheat_before=cheat_before, cheat_after=cheat,
                reroll_before=reroll_before, reroll_after=reroll))
        steps = tuple(steps)
        seen = set()
        infection_nodes = tuple(
            node for step in steps for node in step.infected_added
            if node not in seen and not seen.add(node))
        return DPBestResult(
            source.countdown + best.state.countdown,
            (source.node_idx,) + tuple(step.next_node for step in steps),
            infection_nodes, steps, self.states_evaluated)


__all__ = ["DPBestResult", "DPBestStep", "ExactCountdownDP"]
