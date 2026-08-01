import os
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from importing import load_img
from route import PATHS
from tool.utils.image_tool import find_image_in_folder


def match_multiple_targets(processed_image, mode=1, threshold=0.5):
    """对一组模板在单张灰度图上做多目标匹配，并使用 cv2.dnn.NMSBoxes 进行非极大值抑制。

    返回列表：{'name','location','size','similarity'}。
    """
    if processed_image is None:
        return []

    # 预处理图像
    processed_image = cv2.GaussianBlur(processed_image, (5, 5), 0)
    processed_image = cv2.Canny(processed_image, 100, 200)

    if mode == 1:
        kind_list = ['event', 'wait', 'trade', 'adventure', 'reward', 'battle', 'elite', 'bugevent', 'bugbattle',
                     'head', 'boss']
    else:
        kind_list = ['event', 'wait', 'trade', 'trade2', 'adventure', 'reward', 'reward2', 'battle', 'elite', 'bugevent',
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
        cur_threshold = 0.8 if name == 'blank' else threshold
        ys, xs = np.where(res >= cur_threshold)
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
        indices = indices.flatten()
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
        weight_map (dict): 各类型 (name) 对应的非负权重
        start: 可选的起点索引或 (x,y) 坐标；若为 None 则选最左侧节点作为起点
        max_gap: 最大允许的水平空隙（像素）；若 None 使用节点最小宽度的默认值
        max_overlap: 最大允许的水平重叠（像素）；若 None 使用节点最小宽度的默认值
        max_dy: 最大允许的垂直偏移（像素）；若 None 使用节点最小高度的默认值
    Returns:
        nodes: 节点字典列表，包含键：idx,name,cx,cy,w,h,weight,orig
        edges: 字典 idx -> 子节点 idx 列表
        start_idx: 选定的起点索引
    """
    # 事件遇战15/41，奖励遇战三只小猪1/6，无视极低概率阮梅与不可重复的超验之境，事件虫群6/9可进战
    weight_map = {
        'event': 0.36, 'wait': 0, 'trade': 0, 'trade2': 0, 'adventure': 0,
        'reward': 0.16, 'reward2': 0.16, 'battle': 1.2, 'elite': 1, 'bugevent': 0.66,
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
            if new_weight > old_weight or (new_weight == old_weight and new_len > old_len):
                dp[c] = (new_weight, new_len)
                prev[c] = idx
    max_cx = max(node_map[i]['cx'] for i in ordered)
    candidates = [i for i in ordered if node_map[i]['cx'] >= max_cx - x_tol]
    end_idx = None
    best = (NEG, 0)
    for i in candidates:
        curr = dp.get(i, (NEG, 0))
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


def compute_start_point_from_crop(image, mode=2, th=0.9):
    """通过裁剪图像并将裁剪区域与完整图像进行模板匹配来计算起点。

    Args:
        image: 原始图像（BGR 或灰度）
        mode: 2=普通位面(小裁剪区缩小), 3=第三位面(大裁剪区放大)
        th: 匹配阈值

    Returns:
        匹配位置的中心坐标 (cx, cy)，失败则返回 None
    """
    if image is None:
        return None
    if mode == 2:
        crop_coords = [55, 63, 92, 104]
    else:
        crop_coords = [1003, 929, 1035, 965]
    x1, y1, x2, y2 = crop_coords
    tpl = image[y1:y2, x1:x2].copy()
    tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    if mode == 2:
        new_w = int(tpl_gray.shape[1] / 1.05)
        new_h = int(tpl_gray.shape[0] / 1.05)
    else:
        new_w = int(tpl_gray.shape[1] * 1.15)
        new_h = int(tpl_gray.shape[0] * 1.15)
    tpl_gray = cv2.resize(tpl_gray, (new_w, new_h))
    search_gray = cv2.cvtColor(image.copy(), cv2.COLOR_BGR2GRAY)

    # 先尝试不带 mask 的匹配（mask 可能遮挡起点区域）
    res = cv2.matchTemplate(search_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < th:
        # 降级：带 head_mask 再试一次
        head_mask = find_image_in_folder(f'gray_image/', 'head_mask')
        if head_mask is not None:
            try:
                masked_search = cv2.bitwise_and(search_gray, search_gray, mask=head_mask)
                res = cv2.matchTemplate(masked_search, tpl_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
            except Exception:
                pass
    mx, my = max_loc
    cx = mx + tpl_gray.shape[1] / 2.0
    cy = my + tpl_gray.shape[0] / 2.0
    print(f'(匹配得分={max_val:.3f})')
    if max_val > th:
        return float(cx), float(cy)
    else:
        return None


# ---- 角标检测配置 ----
CORNER_MARKER_DEFS = [
    {'name': 'pig1', 'threshold': 0.7},
    {'name': 'pig2', 'threshold': 0.7},
    {'name': 'pig3', 'threshold': 0.7},
    {'name': 'pig4', 'threshold': 0.7},
    {'name': 'reinforce1', 'threshold': 0.9},
    {'name': 'reinforce2', 'threshold': 0.9},
    {'name': 'alienation1', 'threshold': 0.9},
    {'name': 'alienation2', 'threshold': 0.9},
]


def detect_corner_markers(color_image, matches, marker_defs=None, max_dist=80.0):
    """在彩色原图上检测角标，并关联到最近的地图节点。

    使用彩色模板匹配（非灰度/Canny），因为角标具有颜色区分度。

    Args:
        color_image: 原始彩色截图 (BGR)
        matches: match_multiple_targets 返回的匹配列表
        marker_defs: 角标定义列表，默认使用 CORNER_MARKER_DEFS
        max_dist: 角标中心与节点中心的最大距离（像素），超出则忽略关联

    Returns:
        corner_results: 检测到的角标列表 [{'name':..., 'location':(x,y), 'size':(w,h),
                         'similarity':..., 'node_idx':...}, ...]
        同时就地修改 matches 中对应的节点，添加 'corner_marker' 属性（完整 dict）。
    """
    if marker_defs is None:
        marker_defs = CORNER_MARKER_DEFS

    if color_image is None or not matches:
        for m in matches:
            m.pop('corner_marker', None)
        return []

    all_boxes = []
    all_scores = []
    all_names = []

    for mdef in marker_defs:
        tpl = find_image_in_folder('', mdef['name'])
        if tpl is None:
            print(f'[角标检测] 无法从缓存加载模板: {mdef["name"]}')
            continue
        th, tw = tpl.shape[:2]
        res = cv2.matchTemplate(color_image, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= mdef['threshold'])
        for x, y in zip(xs, ys):
            score = float(res[y, x])
            all_boxes.append([int(x), int(y), tw, th])
            all_scores.append(score)
            all_names.append(mdef['name'])

    if not all_boxes:
        for m in matches:
            m.pop('corner_marker', None)
        return []

    boxes_np = np.array(all_boxes, dtype=np.float32)
    scores_np = np.array(all_scores, dtype=np.float32)
    indices = cv2.dnn.NMSBoxes(
        bboxes=boxes_np.tolist(),
        scores=scores_np.tolist(),
        score_threshold=0.5,
        nms_threshold=0.3
    )
    if isinstance(indices, tuple) and len(indices) == 0:
        for m in matches:
            m.pop('corner_marker', None)
        return []
    if isinstance(indices, (list, tuple)):
        if len(indices) > 0 and isinstance(indices[0], (list, tuple)):
            indices = indices[0]
    elif hasattr(indices, 'flatten'):
        indices = indices.flatten()

    kept = []
    for idx in indices:
        idx = int(idx)
        kept.append({
            'name': all_names[idx],
            'location': (all_boxes[idx][0], all_boxes[idx][1]),
            'size': (all_boxes[idx][2], all_boxes[idx][3]),
            'similarity': round(all_scores[idx], 3),
        })
    kept.sort(key=lambda r: r['similarity'], reverse=True)

    for c in kept:
        cx = c['location'][0] + c['size'][0] / 2.0
        cy = c['location'][1] + c['size'][1] / 2.0
        best_idx = None
        best_dist = float('inf')
        for i, m in enumerate(matches):
            mx = m['location'][0] + m['size'][0] / 2.0
            my = m['location'][1] + m['size'][1] / 2.0
            dist = ((cx - mx) ** 2 + (cy - my) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_idx = i
        c['node_idx'] = best_idx
        c['node_dist'] = round(best_dist, 1)

    for m in matches:
        m.pop('corner_marker', None)

    node_assigned = {}
    for c in kept:
        ni = c['node_idx']
        if ni is None or c['node_dist'] > max_dist:
            continue
        if ni not in node_assigned or c['similarity'] > node_assigned[ni]['similarity']:
            node_assigned[ni] = c

    corner_results = []
    for ni, c in node_assigned.items():
        matches[ni]['corner_marker'] = c
        corner_results.append(c)

    return corner_results


def detect_infectable_nodes(color_image, matches, pad=20, cyan_ratio_threshold=0.20,
                            b_min=120, g_min=90):
    """检测青绿色节点并标记为可传染节点。

    在彩色原图上分析每个匹配节点周围区域的青绿色像素比例，
    满足条件的节点标记为"可传染节点"（添加 infectable 属性）。

    Args:
        color_image: 原始彩色截图 (BGR)
        matches: match_multiple_targets 返回的匹配列表
        pad: 节点区域外扩像素数（用于捕获节点周围的青绿色光晕）
        cyan_ratio_threshold: 青绿色像素比例阈值
        b_min: B 通道最低均值（青绿节点的蓝色通道显著偏高）
        g_min: G 通道最低均值（青绿节点的绿色通道也需偏高）

    Returns:
        infectable_nodes: 标记为可传染的节点索引列表
        同时就地修改 matches 中对应节点，添加 'infectable': True 属性。
    """
    if color_image is None or not matches:
        for m in matches:
            m['infectable'] = False
        return []

    infectable_nodes = []

    for i, m in enumerate(matches):
        x, y = m.get('location', (0, 0))
        w, h = m.get('size', (0, 0))
        x1 = max(0, int(x) - pad)
        y1 = max(0, int(y) - pad)
        x2 = min(color_image.shape[1], int(x) + w + pad)
        y2 = min(color_image.shape[0], int(y) + h + pad)
        roi = color_image[y1:y2, x1:x2]
        if roi.size == 0:
            m['infectable'] = False
            continue

        b, g, r = cv2.split(roi.astype(np.float32))

        # 青绿色像素：B 和 G 显著高于 R，且有一定最低亮度
        cyan_mask = (b > r * 1.2) & (g > r * 1.1) & (b > 80) & (g > 60)
        cyan_ratio = cyan_mask.sum() / cyan_mask.size

        b_mean, g_mean = float(b.mean()), float(g.mean())

        is_infectable = (b_mean > b_min and g_mean > g_min and cyan_ratio > cyan_ratio_threshold) \
                        or (g_mean > 130 and b_mean > 100)
        m['infectable'] = is_infectable
        if is_infectable:
            infectable_nodes.append(i)

    return infectable_nodes


def display_matches(image, matches, path=None, highlight_idx=None, save_path=None, wait_ms=0,
                    font_size_override=None, alt_path=None, show=True, start_idx=None,
                    start_coord=None):
    """简化可视化：绘制检测框、中心点（带索引）、路径、角标和可传染标记。

    Args:
        image: 原始图像
        matches: 匹配结果列表
        path: max_weight_path 返回的节点列表（baseline 路径）
        highlight_idx: 要标记为替换建议的匹配索引（此脚本中用于标记传染节点列表）
        save_path: 保存路径
        wait_ms: 等待时间（毫秒），0 表示无限等待
        font_size_override: 字体大小覆盖值
        alt_path: 备选路径，用不同颜色绘制
    """
    if image is None:
        print('没有图像可显示')
        return
    vis = image.copy()
    font_path = PATHS["font"] + '/手书体.ttf'
    font_size = int(font_size_override) if font_size_override is not None else max(8, min(vis.shape[1] // 140, 13))
    EN_TO_CN = {'event': '事件', 'wait': '休息区', 'trade': '交易', 'trade2': '交易', 'adventure': '探险',
                'reward': '奖励', 'reward2': '奖励', 'battle': '战斗', 'elite': '精英', 'bugevent': '虫事件',
                'bugbattle': '虫战斗', 'head': '首领'}
    texts_to_draw = []
    for i, m in enumerate(matches):
        name = m.get('name', 'obj')
        x, y = m.get('location', (0, 0))
        w, h = m.get('size', (0, 0))

        # 可传染节点用青绿色框，普通节点用绿色框
        if m.get('infectable', False):
            color = (255, 200, 0)  # BGR 青绿偏金色醒目框
            thickness = 4
        else:
            color = (0, 180, 0)
            thickness = 2

        cv2.rectangle(vis, (int(x), int(y)), (int(x + w), int(y + h)), color, thickness)
        cx, cy = int(round(x + w / 2.0)), int(round(y + h / 2.0))
        cv2.circle(vis, (cx, cy), 4, (0, 255, 0), -1)

        label = f"{i}"
        if m.get('infectable', False):
            label += '[染]'

        cm = m.get('corner_marker', None)
        if cm:
            if isinstance(cm, dict):
                cmx, cmy = cm['location']
                cmw, cmh = cm['size']
                cv2.rectangle(vis, (int(cmx), int(cmy)), (int(cmx + cmw), int(cmy + cmh)), (0, 200, 255), 2)

        texts_to_draw.append((label, (int(x), int(y) - 6)))

    # 起点标记：模板匹配检测到的物理起点位置 + 对应节点编号
    if start_coord is not None:
        scx, scy = int(round(start_coord[0])), int(round(start_coord[1]))
        # 红色大菱形标记起点物理位置
        r = 12
        diamond_pts = np.array([
            [scx, scy - r], [scx + r, scy], [scx, scy + r], [scx - r, scy]
        ], dtype=np.int32)
        cv2.fillPoly(vis, [diamond_pts], (0, 0, 255))
        cv2.polylines(vis, [diamond_pts], isClosed=True, color=(0, 0, 200), thickness=2)
        # 标注: "起点→#{start_idx}"（如果 start_idx 存在）
        if start_idx is not None:
            lbl = f'起点->#{start_idx}'
        else:
            lbl = '起点'
        texts_to_draw.append((lbl, (scx + 16, scy - 6)))

    elif start_idx is not None and 0 <= start_idx < len(matches):
        # 无独立起点坐标时（回退最左节点），标记该节点为起点
        sm = matches[start_idx]
        sx, sy = sm.get('location', (0, 0))
        sw, sh = sm.get('size', (0, 0))
        # 金色虚线框
        cv2.rectangle(vis, (int(sx), int(sy)), (int(sx + sw), int(sy + sh)), (0, 215, 255), 3)
        start_label = f'{start_idx}[起点-回退]'
        texts_to_draw.append((start_label, (int(sx), int(sy) - 22)))

    if alt_path and len(alt_path) >= 2:
        pts = []
        for p in alt_path:
            if isinstance(p, dict) and 'cx' in p and 'cy' in p:
                pts.append((int(round(p['cx'])), int(round(p['cy']))))
        if len(pts) >= 2:
            pts_array = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(vis, [pts_array], isClosed=False, color=(255, 0, 0), thickness=4, lineType=cv2.LINE_AA)
            for i, (cx, cy) in enumerate(pts):
                cv2.circle(vis, (cx, cy), 8, (255, 0, 0), -1)

    if path and len(path) >= 2:
        pts = []
        for p in path:
            if isinstance(p, dict) and 'cx' in p and 'cy' in p:
                pts.append((int(round(p['cx'])), int(round(p['cy']))))
        if len(pts) >= 2:
            cv2.polylines(vis, [np.array(pts, dtype=np.int32)], isClosed=False, color=(0, 0, 255), thickness=2)
            for (cx, cy) in pts:
                cv2.circle(vis, (cx, cy), 6, (0, 0, 255), -1)

    if texts_to_draw:
        vis_rgb = cv2.cvtColor(vis, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(vis_rgb)
        try:
            fnt = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
        except Exception:
            fnt = ImageFont.load_default()
        d = ImageDraw.Draw(pil_img)
        for t, (tx, ty) in texts_to_draw:
            try:
                bbox = d.textbbox((tx, ty), t, font=fnt)
                d.rectangle((bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2), fill=(255, 255, 255))
                d.text((tx, ty), t, font=fnt, fill=(0, 0, 0))
            except Exception:
                try:
                    d.text((tx, ty), t, font=fnt, fill=(0, 0, 0))
                except Exception:
                    d.text((tx, ty), t, fill=(0, 0, 0))
        vis = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    if save_path:
        cv2.imwrite(save_path, vis)
        print(f'  地图可视化已保存: {save_path}')
    if show:
        try:
            cv2.imshow('Matches', vis)
            cv2.waitKey(wait_ms)
            cv2.destroyAllWindows()
        except cv2.error:
            pass  # headless environment, no GUI available


if __name__ == '__main__':
    load_img()
    # 指定测试图像（可修改为其他图片路径进行单模块测试）
    test_image = cv2.imread('3d6c236d67ccad3788860331c2363bdf.png')
    mode = 2

    # --- match_multiple_targets ---
    matches = match_multiple_targets(test_image, mode)
    print(f"当前模式{mode}, 找到 {len(matches)} 个匹配")
    if len(matches) == 0:
        print("未匹配到任何地图图标，可能是误识别")
        matches = match_multiple_targets(test_image, mode)
        print(f"重新匹配，当前模式{mode}, 找到 {len(matches)} 个匹配")
        if len(matches) == 0:
            raise RuntimeError("NoMatchError: 无法匹配到任何地图图标")

    # --- compute start point ---
    if mode == 2:
        start = compute_start_point_from_crop(test_image)
        if start is None:
            start = compute_start_point_from_crop(test_image, th=0.6)
    elif mode == 3:
        start = compute_start_point_from_crop(test_image, mode=mode)
        if start is None:
            start = compute_start_point_from_crop(test_image, mode, th=0.6)
    else:
        start = None
    print(f"当前起点坐标{start}")

    # --- detect corner markers ---
    corner_results = detect_corner_markers(test_image, matches)
    if corner_results:
        print(f'\n检测到 {len(corner_results)} 个角标:')
        for cr in corner_results:
            print(f"  {cr['name']} at {cr['location']} sim={cr['similarity']:.3f} -> 节点{cr['node_idx']} (dist={cr['node_dist']})")
    else:
        print('\n未检测到角标')

    # --- detect infectable nodes (青绿色 → 可传染) ---
    infectable_indices = detect_infectable_nodes(test_image, matches)
    if infectable_indices:
        print(f'\n检测到 {len(infectable_indices)} 个可传染节点:')
        for idx in infectable_indices:
            m = matches[idx]
            print(f"  节点{idx}: {m['name']} at {m['location']}")
    else:
        print('\n未检测到可传染节点')

    # --- print matches ---
    for i, m in enumerate(matches):
        cm = m.get('corner_marker', None)
        cm_str = f' [角标:{cm["name"]}]' if cm else ''
        inf_str = ' [可传染]' if m.get('infectable', False) else ''
        print(f"  {i}: {m['name']} at {m['location']}, 相似度: {m.get('similarity')}{cm_str}{inf_str}")

    # --- filter by boss/head ---
    boss_head_x = [m['location'][0] for m in matches if m['name'] in ('boss', 'head')]
    if boss_head_x:
        rightmost = max(boss_head_x)
        matches = [m for m in matches if m['location'][0] <= rightmost]
        print(f"过滤boss/head右侧节点后，剩余 {len(matches)} 个匹配")
        for i, m in enumerate(matches):
            print(f"  {i}: {m['name']} at {m['location']}, 相似度: {m.get('similarity')}")
    else:
        raise RuntimeError("NoBossError: 未找到boss/head节点")

    # --- build graph ---
    if mode == 3:
        nodes, edges, start_idx = build_rightward_graph(
            matches, start=start,
            max_gap=110, max_overlap=50, max_dy=130
        )
    else:
        nodes, edges, start_idx = build_rightward_graph(matches, start=start)

    print('\n构建图后的节点 (索引，类型，相似度，中心 x, 中心 y, 可传染):')
    for n in nodes:
        inf_tag = ' [可传染]' if n.get('orig') and n['orig'].get('infectable') else ''
        print(f"  {n['idx']}: {n['name']} sim={n.get('similarity', 0):.3f} center=({n['cx']:.1f},{n['cy']:.1f}){inf_tag}")

    # --- max weight path ---
    path, expectation_weight, end_idx = max_weight_path(nodes, edges, start_idx)
    if not path:
        print("未找到有效路径，可能是起点位于最右端或图构建失败")
        raise RuntimeError("NoMatchError: 未找到有效路径")

    if path:
        weight_ranges = {
            'event': (0, 1), 'wait': (0, 0), 'trade': (0, 0), 'trade2': (0, 0), 'adventure': (0, 0),
            'reward': (0, 1), 'reward2': (0, 1), 'battle': (1, 3), 'elite': (1, 1), 'bugevent': (0, 1),
            'bugbattle': (1, 1), 'head': (1, 1), 'boss': (1, 1), 'blank': (0, 0)
        }
        print(f'\n路径理论期望值：{expectation_weight:.3f}')
        print(f'路径理论最小值：{sum(weight_ranges.get(n["name"], (0, 0))[0] for n in path)}')
        print(f'路径理论最大值：{sum(weight_ranges.get(n["name"], (0, 0))[1] for n in path)}')

    print(f'\n路径结果：path={len(path) if path else 0}, total_weight={expectation_weight}, end_idx={end_idx}')
    print('\n找到的路径 (索引 -> 名称，权重):')
    for n in path:
        inf_tag = ' [可传染]' if n.get('orig') and n['orig'].get('infectable') else ''
        print(f"  {n['idx']} -> {n['name']} (w={n['weight']}){inf_tag}")

    # --- 统计路径上的可传染节点 ---
    path_infectable = [n for n in path if n.get('orig') and n['orig'].get('infectable')]
    all_infectable = [n for n in nodes if n.get('orig') and n['orig'].get('infectable')]
    if all_infectable:
        print(f'\n可传染节点总计: {len(all_infectable)} 个')
        for n in all_infectable:
            on_path = ' [在路径上]' if n in path else ''
            print(f"  节点{n['idx']}: {n['name']} at ({n['cx']:.0f},{n['cy']:.0f}){on_path}")
        if path_infectable:
            print(f'其中 {len(path_infectable)} 个在当前最优路径上')
        else:
            print('当前最优路径上无可传染节点')

    # --- display ---
    try:
        display_matches(test_image, matches, path=path,
                       save_path='matches_preview.png', wait_ms=0,
                       font_size_override=14, alt_path=None)
    except Exception as e:
        print('显示匹配结果时出错:', e)
