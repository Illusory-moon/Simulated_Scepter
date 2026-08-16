"""手动录图工具：人在房间内手动走路，脚本自动记录地图并标注交互点。

> 本文件由 AI 辅助实现（DeepSeek），并经单元测试与真机验证后提交。

解决场景：某张问题地图很难刷到、或自动探路一直找不到交互点。
用户只需要站进房间后运行本脚本，然后像平时一样手动走动：
- 脚本自动保存 init.jpg（房间识别快照）；
- 自动跟踪你的位置并画成蓝色路径（你绕开桌子的走法就是最佳路线）；
- 每次画面出现 F 提示，脚本都会把该位置标成黄绿交互点（支持一张图
  多个交互点：如 事件点 + 觐见装置 的双 F 流程）；
- 事件对话等界面打开时自动暂停记录（通过 big_world 图标判断），
  不会把界面画面当轨迹录进去；
- 走完全部流程后，在命令行窗口按回车结束：只要有交互点就自动转正。

用法（房间类型：event / rest / trade）：
    uv run python tool/scripts/manual_record_map.py event

注意：
- 需要 1920x1080 的本地或云游戏窗口，简体中文，无遮挡；
- 运行期间不要打开任何覆盖小地图/交互提示区域的界面；
- 走到 F 位置后请自己按 F 继续流程（脚本只记录，不代按）。
"""

import msvcrt
import os
import random
import sys
import time
from collections import deque

import cv2 as cv
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from route import PATHS  # noqa: E402
from tool.screenshot import Screen  # noqa: E402
from tool.utils.game_window import (  # noqa: E402
    find_game_window,
    get_client_screen_rect,
)
from tool.utils.image_tool import (  # noqa: E402
    find_image_by_name,
    load_all_images_from_directory,
)
from tool.utils.minimap_util import (  # noqa: E402
    MINIMAP_RADIUS,
    POSITION_SEARCH_SCALE,
    get_minimap,
    re_get_position,
)
from tool.utils.mminimap import PositionPredict  # noqa: E402

# F 提示检测参数（与 UniverseUtils.check("f", 0.4443, 0.4417, mask="mask_f1") 一致）
F_X = 0.4443
F_Y = 0.4417
F_THRESHOLD = 0.96
# big_world 图标：位于界面左上角，仅在"可自由行动"时可见，用于暂停录制
WORLD_X = 0.0245
WORLD_Y = 0.5185
WORLD_THRESHOLD = 0.98
CROP_PAD = 60
SCREEN_W = 1920
SCREEN_H = 1080

# 轨迹采样、F 去重与录制时长
TRACE_STEP = 8.0
F_DEDUPE_DISTANCE = 8.0
F_DEDUPE_SECONDS = 5.0
MAX_SECONDS = 600

MAP_ROOTS = {
    "event": os.path.join(PATHS["image"], "event_nmaps"),
    "rest": os.path.join(PATHS["image"], "rest_nmaps"),
    "trade": os.path.join(PATHS["image"], "trade_nmaps"),
}


def check_icon(screen, name, x, y, threshold, mask_name=None):
    """检测画面指定位置是否出现目标图标。返回 (是否出现, 相似度)。"""
    target = find_image_by_name(name)
    if target is None:
        return False, -1.0
    if mask_name is not None:
        mask_img = find_image_by_name(mask_name)
        if mask_img is None:
            return False, -1.0
        height, width = mask_img.shape[0], mask_img.shape[1]
    else:
        height, width = target.shape[0], target.shape[1]
    sx, sy = height + CROP_PAD, width + CROP_PAD
    bx = SCREEN_W - int(x * SCREEN_W)
    by = SCREEN_H - int(y * SCREEN_H)
    local = screen[
        max(0, by - sx // 2): min(SCREEN_H, by + sx // 2),
        max(0, bx - sy // 2): min(SCREEN_W, bx + sy // 2),
        :,
    ]
    result = cv.matchTemplate(local, target, cv.TM_CCORR_NORMED)
    _, max_val, _, _ = cv.minMaxLoc(result)
    return max_val > threshold, max_val


def new_map_dir(map_root):
    while True:
        name = "my_" + str(random.randint(0, 99999))
        path = os.path.join(map_root, name)
        try:
            os.makedirs(path)
            return name, path + os.sep
        except FileExistsError:
            continue


def update_cut(cut_pos, position, big):
    """复制 cut_map 的扩张逻辑：以当前位置为圆心 93px 半径逐步扩张。"""
    radius = 93
    x_limit, y_limit = big.shape[1], big.shape[0]
    pos = re_get_position(position, need_int=False)
    if cut_pos is None:
        return [
            max(0, pos[0] - radius * POSITION_SEARCH_SCALE),
            min(x_limit, pos[0] + radius * POSITION_SEARCH_SCALE),
            max(0, pos[1] - radius * POSITION_SEARCH_SCALE),
            min(y_limit, pos[1] + radius * POSITION_SEARCH_SCALE),
        ]
    left, right, top, bottom = cut_pos
    return [
        max(0, min(left, pos[0] - radius * POSITION_SEARCH_SCALE)),
        min(x_limit, max(right, pos[0] + radius * POSITION_SEARCH_SCALE)),
        max(0, min(top, pos[1] - radius * POSITION_SEARCH_SCALE)),
        min(y_limit, max(bottom, pos[1] + radius * POSITION_SEARCH_SCALE)),
    ]


def write_map(map_file, big, cut_pos, start_pos, trace, interactions, map_number):
    """把轨迹画成蓝色、交互点画成黄绿色，写入 map_/target_ 文件。"""
    left, right, top, bottom = (
        int(cut_pos[0]), int(cut_pos[1]), int(cut_pos[2]), int(cut_pos[3])
    )
    if right <= left or bottom <= top:
        return
    color = cv.cvtColor(big, cv.COLOR_GRAY2BGR)
    start_x, start_y = re_get_position(start_pos)
    if left <= start_x < right and top <= start_y < bottom:
        cv.circle(color, (int(start_x), int(start_y)), 2, (0, 255, 0), -1)
    for point in trace:
        x, y = re_get_position(point)
        if left <= x < right and top <= y < bottom:
            cv.circle(color, (int(x), int(y)), 2, (255, 0, 0), -1)
    for point in interactions:
        x, y = re_get_position(point)
        if left <= x < right and top <= y < bottom:
            cv.circle(color, (int(x), int(y)), 2, (29, 230, 181), -1)
    for name in os.listdir(map_file):
        if name.startswith("map_") or name.startswith("target_"):
            os.remove(os.path.join(map_file, name))
    cv.imwrite(
        map_file + f"map_{map_number}_({start_pos[0]},{start_pos[1]}).jpg",
        big[top:bottom, left:right],
    )
    cv.imwrite(map_file + f"target_{left}_{top}.jpg", color[top:bottom, left:right])


def promote_dir(map_file):
    old_dir = map_file.rstrip("/\\")
    old_name = os.path.basename(old_dir)
    root = os.path.dirname(old_dir)
    while True:
        new_name = str(random.randint(100000, 999999))
        new_dir = os.path.join(root, new_name)
        if not os.path.exists(new_dir):
            break
    os.rename(old_dir, new_dir)
    print(f"[manual_record] 地图目录已由 {old_name} 转正为 {new_name}")
    return new_name


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in MAP_ROOTS:
        print("用法: uv run python tool/scripts/manual_record_map.py event|rest|trade")
        return 1
    map_root = MAP_ROOTS[sys.argv[1]]
    load_all_images_from_directory(PATHS["image"])

    window = find_game_window(prefer_foreground=True)
    if window is None:
        print("[manual_record] 未找到游戏窗口（崩坏：星穹铁道，1920x1080，需置于前台）")
        return 1
    left, top, _, _ = get_client_screen_rect(window.hwnd)
    screen_cap = Screen()
    print(f"[manual_record] 已定位游戏窗口 ({left},{top})，开始录制，去走一圈吧")

    predictor = PositionPredict()
    cut_pos = None
    trace = []
    interactions = []
    start_pos = None
    map_name = None
    map_file = None

    def capture():
        return screen_cap.grab(left, top)

    screen = capture()
    best = predictor.match_multiple_maps(screen)
    position = best.get("position")
    if position is None:
        print("[manual_record] 定位失败：小地图不可见或不在可识别地图范围内")
        return 1
    start_pos = tuple(np.round(position, 1))
    print(f"[manual_record] 起点: {start_pos}（匹配地图 {best.get('map_name')}）")
    map_name, map_file = new_map_dir(map_root)
    initial_map = get_minimap(screen, radius=MINIMAP_RADIUS, copy=True)
    cv.imwrite(map_file + "init.jpg", initial_map)
    print(f"[manual_record] 已创建目录 {map_name}")

    start_time = time.time()
    last_pos = None
    recent = deque(maxlen=3)
    last_f_pos = None
    last_f_time = 0.0
    print("[manual_record] 走完全部流程后，回到本窗口按回车结束录制")
    while True:
        screen = capture()
        in_world, _ = check_icon(
            screen, "big_world", WORLD_X, WORLD_Y, WORLD_THRESHOLD
        )
        elapsed = int(time.time() - start_time)
        if not in_world:
            print(
                f"[manual_record] (界面中，暂停记录) 交互点{len(interactions)}个 "
                f"轨迹{len(trace)}点 用时{elapsed}s",
                end="\r",
            )
        else:
            position, sim = predictor.update_position(screen)
            recent.append(np.round(position, 1))
            # 该房间对地面特征的匹配度可能很低，定位在多个估计间跳动；
            # 取近 3 帧中值，抑制轨迹与交互点的位置噪声。
            smoothed = tuple(np.median(np.array(recent), axis=0))
            position = smoothed
            if last_pos is None or np.linalg.norm(
                np.array(position) - np.array(last_pos)
            ) >= TRACE_STEP:
                trace.append(position)
                last_pos = position
            big = predictor.assets_floor_feat
            if big is not None:
                cut_pos = update_cut(cut_pos, position, big)
                write_map(
                    map_file, big, cut_pos, start_pos, trace, interactions,
                    predictor.map_num,
                )
            found_f, f_sim = check_icon(
                screen, "f", F_X, F_Y, F_THRESHOLD, mask_name="mask_f1"
            )
            if found_f and (
                last_f_pos is None
                or np.linalg.norm(np.array(position) - np.array(last_f_pos))
                >= F_DEDUPE_DISTANCE
                or time.time() - last_f_time > F_DEDUPE_SECONDS
            ):
                interactions.append(position)
                last_f_pos = position
                last_f_time = time.time()
                print(
                    f"\n[manual_record] 第{len(interactions)}次检测到F，"
                    f"交互点已标注: {position}"
                )
            print(
                f"[manual_record] 位置{position} F相似度{f_sim:.2f} "
                f"交互点{len(interactions)}个 轨迹{len(trace)}点 用时{elapsed}s",
                end="\r",
            )
        if msvcrt.kbhit() and msvcrt.getch() in (b"\r", b"\n"):
            print()
            break
        if elapsed > MAX_SECONDS:
            print()
            break
        time.sleep(0.3)

    big = predictor.assets_floor_feat
    if big is not None and cut_pos is not None:
        write_map(
            map_file, big, cut_pos, start_pos, trace, interactions,
            predictor.map_num,
        )
    if interactions:
        promote_dir(map_file)
        print(
            f"[manual_record] 完成！共标注 {len(interactions)} 个交互点，"
            "下次脚本进入该房间将自动按此地图寻路。"
        )
        return 0
    print(
        f"[manual_record] 未检测到任何F，地图（仅路径）已保存至 {map_name}，"
        "可下次续录或人工补交互点"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
