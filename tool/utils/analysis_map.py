from datetime import datetime

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from route import PATHS
from tool.log import CUS_LOGGER
from tool.utils.image_tool import find_image_in_folder


def match_multiple_targets(processed_image, mode=1, threshold=0.5):
    """对一组模板在单张灰度图上做多目标匹配，并使用 cv2.dnn.NMSBoxes 进行非极大值抑制。

    返回列表：{'name','location','size','similarity'}。
    """
    if processed_image is None:
        return []
    
    # 预处理图像
    processed_image = cv2.GaussianBlur(processed_image.copy(), (5, 5), 0)
    processed_image = cv2.Canny(processed_image, 100, 200)
    
    if mode == 1:
        kind_list = ['event', 'wait', 'trade', 'adventure', 'reward', 'battle', 'elite', 'bugevent', 'bugbattle',
                     'head', 'boss']
    else:
        kind_list = ['event', 'wait', 'trade', 'trade2', 'adventure', 'reward', 'reward2','battle', 'elite', 'bugevent',
                     'bugbattle', 'head', 'boss', 'blank']
    if mode == 3:
        mode = 2
    all_boxes = []      # [x, y, w, h]
    all_scores = []     # 置信度分数
    all_names = []      # 对应的模板名称
    
    for name in kind_list:
        tpl = find_image_in_folder(f'gray_image/node{mode}/', name)
        if tpl is None:
            continue
        th, tw = tpl.shape[:2]
        res = cv2.matchTemplate(processed_image, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        if xs.size == 0:
            continue
        
        # 收集该模板的所有候选框
        for x, y in zip(xs, ys):
            score = float(res[y, x])
            all_boxes.append([int(x), int(y), tw, th])
            all_scores.append(score)
            all_names.append(name)
    
    if not all_boxes:
        return []
    
    # 转换为 numpy 数组
    boxes_np = np.array(all_boxes, dtype=np.float32)  # shape: (N, 4)
    scores_np = np.array(all_scores, dtype=np.float32)  # shape: (N,)
    
    # 使用 cv2.dnn.NMSBoxes 进行非极大值抑制
    # 参数说明：
    # - boxes: 检测框列表 [x, y, w, h]
    # - scores: 置信度分数
    # - score_threshold: 最低分数阈值（已经过滤过，这里设低一点）
    # - nms_threshold: NMS IoU 阈值，控制去重强度（0.3-0.5 较合适）
    nms_threshold = 0.3
    indices = cv2.dnn.NMSBoxes(
        bboxes=boxes_np.tolist(),
        scores=scores_np.tolist(),
        score_threshold=threshold,
        nms_threshold=nms_threshold
    )
    if isinstance(indices, tuple) and len(indices) == 0:
        return []
    if isinstance(indices, (list, tuple)):
        if len(indices) > 0 and isinstance(indices[0], (list, tuple)):
            indices = indices[0]
    elif hasattr(indices, 'flatten'):
        indices = indices.flatten()  # numpy 数组
    results = []
    for idx in indices:
        idx = int(idx)
        x, y, w, h = all_boxes[idx]
        results.append({
            'name': all_names[idx],
            'location': (x, y),
            'size': (w, h),
            'similarity': round(all_scores[idx], 3)
        })
    
    # 按相似度降序排序
    results.sort(key=lambda r: r['similarity'], reverse=True)
    
    return results


def build_rightward_graph(matches, start=None, max_gap=90.0, max_overlap=40.0, max_dy=120.0):
    """构建一个只能向右走（右 / 右上 / 右下）的有向图并返回节点与边。

    Args:
        matches (list): match_multiple_targets 的输出列表，元素包含 'name','location','size','similarity'
        start: 可选的起点索引或 (x,y) 坐标；若为 None 则选最左侧节点作为起点
        max_gap: 最大允许的水平空隙（像素）
        max_overlap: 最大允许的水平重叠（像素）
        max_dy: 最大允许的垂直偏移（像素）
    Returns:
        nodes: 节点字典列表，包含键：idx,name,cx,cy,w,h,weight,orig
        edges: 字典 idx -> 子节点 idx 列表
        start_idx: 选定的起点索引
    """
    # 事件遇战15/41，奖励遇战三只小猪1/6，无视极低概率阮梅与不可重复的超验之境，事件虫群6/9可进战
    weight_map = {
        'event': 0.36, 'wait': 0, 'trade': 0, 'trade2': 0, 'adventure': 0,
        'reward': 0.16,'reward2': 0.16, 'battle': 1.2, 'elite': 1, 'bugevent': 0.66,
        'bugbattle': 1, 'head': 1, 'boss': 1, 'blank': 0
    }
    if not matches:
        return [], {}, None
    nodes = []
    for i, m in enumerate(matches):
        x, y = m.get('location', (0, 0))
        w, h = m.get('size', (0, 0))
        cx = float(x) + float(w) / 2.0
        cy = float(y) + float(h) / 2.0
        nodes.append({'idx': i, 'name': m.get('name'), 'cx': cx, 'cy': cy, 'w': w, 'h': h,
                      'weight': float(weight_map.get(m.get('name'), 0)), 'similarity': float(m.get('similarity', 0)),
                      'orig': m})

    if start is not None:
        sx, sy = start[0], start[1]
        nodes.append({'idx': len(nodes), 'name': 'start', 'cx': float(sx), 'cy': float(sy), 'w': 50, 'h': 50,
                      'weight': 0.0, 'similarity': 0.0, 'orig': None})

    # 构建只向右的边（基本要求：b.cx > a.cx），并按邻近约束过滤。
    edges = {n['idx']: [] for n in nodes}
    for a in nodes:
        a_left = a['cx'] - a['w'] / 2.0
        a_right = a['cx'] + a['w'] / 2.0
        for b in nodes:
            if b['cx'] <= a['cx']:
                continue
            b_left = b['cx'] - b['w'] / 2.0
            gap = b_left - a_right  # 正值表示两框之间的空隙，负值表示重叠
            dy = abs(b['cy'] - a['cy'])
            if dy > max_dy:
                continue
            if gap > max_gap or gap < -max_overlap:
                continue
            edges[a['idx']].append(b['idx'])

    # 选择起点：如果 start 有效则使用；否则取最左侧的
    if start is not None:
        start_idx = len(nodes) - 1
    else:
        leftmost = min(nodes, key=lambda n: (n['cx'], n['cy']))
        start_idx = leftmost['idx']

    return nodes, edges, start_idx


def max_weight_path(nodes, edges, start_idx, x_tol=1e-6):
    """在有向无环图上（边只指向右边）求从 start 到最右端点的最大权重路径。
    如果有多条权重相同的路径，优先选择更长的路径（经过更多节点）。

    Args:
        nodes: build_rightward_graph 返回的节点列表
        edges: 邻接表字典 idx -> 子节点 idx 列表
        start_idx: 起点索引
        x_tol: 选取"最右端点"时允许的 x 近似容差

    Returns:
        path_nodes: 节点字典列表，从起点到终点
        total_weight: 总权重（浮点数）
        end_idx: 选定的终点索引
    """
    if not nodes or start_idx is None:
        return [], 0.0, None
    node_map = {n['idx']: n for n in nodes}
    ordered = sorted(node_map.keys(), key=lambda i: node_map[i]['cx'])
    NEG = float('-inf')
    # dp 存储 (权重，路径长度) 元组
    dp = {i: (NEG, 0) for i in ordered}
    prev = {i: None for i in ordered}
    dp[start_idx] = (node_map[start_idx]['weight'], 1)
    start_pos = ordered.index(start_idx)
    for idx in ordered[start_pos:]:
        curr_weight, curr_len = dp[idx]
        if curr_weight == NEG:
            continue
        for c in edges.get(idx, []):
            new_weight = curr_weight + node_map[c]['weight']
            new_len = curr_len + 1
            old_weight, old_len = dp[c]
            # 优先比较权重，权重相同时比较路径长度（选更长的）
            if new_weight > old_weight or (new_weight == old_weight and new_len > old_len):
                dp[c] = (new_weight, new_len)
                prev[c] = idx
    max_cx = max(node_map[i]['cx'] for i in ordered)
    candidates = [i for i in ordered if node_map[i]['cx'] >= max_cx - x_tol]
    end_idx = None
    best = (NEG, 0)
    for i in candidates:
        curr = dp.get(i, (NEG, 0))
        # 优先比较权重，权重相同时比较路径长度（选更长的）
        if curr[0] > best[0] or (curr[0] == best[0] and curr[1] > best[1]):
            best = curr
            end_idx = i

    if end_idx is None or best[0] == NEG:
        return [], 0.0, None
    path = []
    cur = end_idx
    while cur is not None:
        path.append(node_map[cur])
        cur = prev.get(cur)
    path.reverse()
    return path, float(best[0]), end_idx


def compute_all_max_steps(nodes, edges, start_idx):
    """一次性计算从起点到所有节点的最长路径步数（经过的边数）。

    Args:
        nodes: build_rightward_graph 返回的节点列表
        edges: 邻接表字典 idx -> 子节点 idx 列表
        start_idx: 起点索引

    Returns:
        steps_dict: 字典 {节点 idx: 最长步数}，无法到达的节点值为 -1
    """
    node_map = {n['idx']: n for n in nodes}
    ordered = sorted(node_map.keys(), key=lambda i: node_map[i]['cx'])
    NEG = float('-inf')
    dp = {i: NEG for i in ordered}
    dp[start_idx] = 0
    start_pos = ordered.index(start_idx)
    for idx in ordered[start_pos:]:
        if dp[idx] == NEG:
            continue
        for c in edges.get(idx, []):
            dp[c] = max(dp[c], dp[idx] + 1)
    return {i: (int(dp[i]) if dp[i] != NEG else -1) for i in ordered}
def evaluate_best_single_replacement(nodes, edges, start_idx, t=0.2):
    """尝试将每个节点的权重替换为目标类型权重并返回最佳改进的路径。

    Args:
        nodes: build_rightward_graph 返回的节点列表
        edges: 邻接表字典
        start_idx: 起点索引
        t: 期权折扣参数 (0-1)，默认 0.2

    Returns:
        best_path: 最佳路径节点列表（替换后的新路径）
        best_weight: 最佳路径权重
        best_end_idx: 最佳路径终点索引
        best_replace_idx: 被替换的最佳节点索引（无替换则为 None）
        delta: 原始权重增量（未折现）
        discounted_delta: 期权调整后的增量 (1-t)^k * delta
    """
    baseline_path, baseline_weight, baseline_end_idx = max_weight_path(nodes, edges, start_idx)
    target_weight = 1.2
    steps = compute_all_max_steps(nodes, edges, start_idx)
    best_path = baseline_path
    best_weight = baseline_weight
    best_end_idx = baseline_end_idx
    best_replace_idx = None
    best_delta = 0.0
    best_discounted_delta = 0.0
    start_center = None
    if start_idx is not None:
        for sn in nodes:
            if sn['idx'] == start_idx:
                start_center = (float(sn['cx']), float(sn['cy']))
                break

    best_dist = float('inf')
    for n in nodes:
        idx = n['idx']
        if idx == start_idx:
            continue
        if n['name'] in ['head', 'boss']:
            continue

        orig_w = float(n.get('weight', 0.0))
        if orig_w >= target_weight:
            continue
        nodes_mod = [dict(nn) for nn in nodes]
        for nm in nodes_mod:
            if nm['idx'] == idx:
                nm['weight'] = target_weight
                break

        new_path, new_weight, new_end_idx = max_weight_path(nodes_mod, edges, start_idx)
        delta = new_weight - baseline_weight
        k = steps.get(idx, -1)
        if k < 0:
            discounted_delta = 0  # 无法到达的点位，没有任何增量
        else:
            # 计算期权调整后的 delta: (1-t)^k * delta
            discounted_delta = ((1 - t) ** k) * delta

        choose = False
        if discounted_delta > best_discounted_delta:
            choose = True
        elif discounted_delta == best_discounted_delta and discounted_delta > 0 and start_center is not None:
            cur_dist = ((float(n['cx']) - start_center[0]) ** 2 + (float(n['cy']) - start_center[1]) ** 2) ** 0.5
            if cur_dist < best_dist:
                choose = True
        if choose:
            best_delta = float(delta)
            best_discounted_delta = float(discounted_delta)
            best_path = new_path
            best_weight = float(new_weight)
            best_end_idx = new_end_idx
            best_replace_idx = idx
            if start_center is not None:
                best_dist = ((float(n['cx']) - start_center[0]) ** 2 + (float(n['cy']) - start_center[1]) ** 2) ** 0.5

    return best_path, best_weight, best_end_idx, best_replace_idx, float(best_delta), float(best_discounted_delta)


def compute_start_point_from_crop(image, crop_coords=(55, 63, 92, 104),th=0.6):
    """通过裁剪图像并将裁剪区域与完整图像进行模板匹配来计算起点。

    Args:
        image: 原始图像（BGR 或灰度）
        crop_coords: 裁剪坐标 (left, top, right, bottom)，单位像素

    Returns:
        匹配位置的中心坐标 (cx, cy)，失败则返回 None

    Notes:
        - 为避免裁剪区域与自身匹配，在运行模板匹配前会先掩码原图像中的裁剪区域。
    """
    if image is None:
        return None
    x1, y1, x2, y2 = crop_coords
    tpl = image[y1:y2, x1:x2].copy()
    tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    search_gray = cv2.cvtColor(image.copy(), cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(
        cv2.bitwise_and(search_gray, search_gray, mask=find_image_in_folder(f'gray_image/', 'head_mask')), tpl_gray,
        cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    mx, my = max_loc
    cx = mx + tpl.shape[1] / 2.0
    cy = my + tpl.shape[0] / 2.0
    CUS_LOGGER.debug(f'角色匹配得分={max_val:.3f}')
    if max_val > th:
        return float(cx), float(cy)
    else:
        return None


def display_matches(image, matches, path=None, highlight_idx=None, save_path=None, font_size_override=None,
                    alt_path=None):
    """简化可视化：绘制检测框、中心点（带索引）、路径和可选的高亮标记。

    Args:
        image: 原始图像
        matches: 匹配结果列表
        path: max_weight_path 返回的节点列表（baseline 路径）
        highlight_idx: 要标记为替换建议的匹配索引
        save_path: 保存路径
        wait_ms: 等待时间（毫秒），0 表示无限等待
        font_size_override: 字体大小覆盖值
        alt_path: 备选路径（如替换后的新路径），用不同颜色绘制
    """
    if image is None:
        print('没有图像可显示')
        return
    vis = image.copy()
    font_path = PATHS["font"] + '/手书体.ttf'
    font_size = int(font_size_override) if font_size_override is not None else max(10, min(vis.shape[1] // 60, 18))
    EN_TO_CN = {'event': '事件', 'wait': '休息区', 'trade': '交易', 'trade2': '交易', 'adventure': '探险',
                'reward': '奖励', 'reward2': '奖励','battle': '战斗', 'elite': '精英', 'bugevent': '虫事件', 'bugbattle': '虫战斗',
                'head': '首领'}
    texts_to_draw = []
    for i, m in enumerate(matches):
        name = m.get('name', 'obj');
        x, y = m.get('location', (0, 0));
        w, h = m.get('size', (0, 0));
        color = (0, 180, 0)
        cv2.rectangle(vis, (int(x), int(y)), (int(x + w), int(y + h)), color, 2)
        cx, cy = int(round(x + w / 2.0)), int(round(y + h / 2.0));
        cv2.circle(vis, (cx, cy), 4, (0, 255, 0), -1)
        label = f"{i}:{EN_TO_CN.get(name, name)}:{m.get('similarity', 0)}"
        texts_to_draw.append((label, (int(x), int(y) - 6)))
    if alt_path and len(alt_path) >= 2:
        pts = []
        for p in alt_path:
            if isinstance(p, dict) and 'cx' in p and 'cy' in p: pts.append((int(round(p['cx'])), int(round(p['cy']))))
        if len(pts) >= 2:
            pts_array = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(vis, [pts_array], isClosed=False, color=(255, 0, 0), thickness=4, lineType=cv2.LINE_AA)
            for i, (cx, cy) in enumerate(pts):
                cv2.circle(vis, (cx, cy), 8, (255, 0, 0), -1)
    if path and len(path) >= 2:
        pts = []
        for p in path:
            if isinstance(p, dict) and 'cx' in p and 'cy' in p: pts.append((int(round(p['cx'])), int(round(p['cy']))))
        if len(pts) >= 2:
            cv2.polylines(vis, [np.array(pts, dtype=np.int32)], isClosed=False, color=(0, 0, 255), thickness=2)
            for (cx, cy) in pts:
                cv2.circle(vis, (cx, cy), 6, (0, 0, 255), -1)
    if highlight_idx is not None and 0 <= int(highlight_idx) < len(matches):
        m = matches[int(highlight_idx)];
        lx, ly = m.get('location', (0, 0));
        w, h = m.get('size', (0, 0))
        hc, hr = int(round(lx + w / 2.0)), int(round(ly + h / 2.0));
        cv2.circle(vis, (hc, hr), 10, (0, 255, 255), 3)
        rlbl = 'REPLACE';
        (tw, th), baseline = cv2.getTextSize(rlbl, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        rtx, rty = hc + 12, hr + 6;
        cv2.rectangle(vis, (rtx - 2, rty - th - 2), (rtx + tw + 2, rty + baseline + 2), (255, 255, 255), -1);
        cv2.putText(vis, rlbl, (rtx, rty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    if texts_to_draw:
        vis_rgb = cv2.cvtColor(vis, cv2.COLOR_BGR2RGB);
        pil_img = Image.fromarray(vis_rgb)
        try:
            fnt = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
        except Exception:
            fnt = ImageFont.load_default()
        d = ImageDraw.Draw(pil_img)
        for t, (tx, ty) in texts_to_draw:
            try:
                bbox = d.textbbox((tx, ty), t, font=fnt);
                d.rectangle((bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2), fill=(255, 255, 255));
                d.text((tx, ty), t, font=fnt, fill=(0, 0, 0))
            except Exception:
                try:
                    d.text((tx, ty), t, font=fnt, fill=(0, 0, 0))
                except Exception:
                    d.text((tx, ty), t, fill=(0, 0, 0))
        vis = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    # cv2.imshow('Matches', vis);
    # cv2.waitKey(wait_ms);
    # cv2.destroyAllWindows()
    if save_path:
        cv2.imwrite(PATHS["root"]+"/temp/"+datetime.now().strftime("%Y%m%d_%H%M%S")+".png", vis)


        #使用作弊100%能替换节点，重投在1与2位面1/5概率能替换节点，第三位面1/3概率能替换节点，还可以什么都不做
        #每走一步自动投一次，可能会随机到能替换节点，该概率与重投相同，此时不需要考虑作弊重投，因为已经获得想要的了，不消耗次数
        #总共有三个位面地图，这些位面地图首尾相连，但是某个位面的修改替换节点只对该位面地图生效
        #当前作弊次数与重投次数要作为参数传入
        #需要根据当前地图节点与作弊次数和重投次数给出决策，决定当前节点替换哪个节点的实际算法已经给出，这个算法基于贪心，并不是最佳算法，
        #当前最佳不代表全局最佳，可能出现替换节点靠后的状况，如果在走到该节点前再次成功随机投出替换节点但是没有可替换的会亏
        #注意我给出的算法只是计算出了进行一次替换最值得替换的一个点位，随着多步执行，完全是有可能替换多个路径节点的
        #根据马尔可夫决策过程相关理论为我建立数学模型
        # 机制
        # 玩家沿着路径一步一步向前走（每经过一个节点 / 一段路就是一个决策步）。
        # 每走一步都会发生以下事件：
        # 先进行一次免费投（概率在上方指出）：
        # 成功：获得一次替换机会，此时必须立即决定要替换当前地图上的哪个节点。
        # 失败：不获得替换机会。
        # 在失败时，玩家当前节点可以额外做出一次决策：
        # 是否立即使用作弊（100 % 获得一次替换机会）
        # 是否立即使用重投（以概率p（在上方指出）获得一次替换机会）
        # 或者什么都不做
        #每次决策替换只能替换一个
        # 替换机会不可保留：一旦获得，必须当场使用（选择替换哪个节点），不能留到下一步。
        # 一个节点最多只会被替换一次（不必特别考虑，因为算法计算battle1.2权重更换battle1.2权重没有任何收益）。