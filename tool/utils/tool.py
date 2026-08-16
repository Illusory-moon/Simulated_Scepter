import os

import numpy as np
import win32gui

from tool.utils.game_window import canonical_game_title


def get_hwnd_and_text():
    hwnd = win32gui.GetForegroundWindow()
    Text = canonical_game_title(hwnd) or win32gui.GetWindowText(hwnd)
    return hwnd,Text


def get_center(img, i, j):
    """
    计算图像中指定位置(i,j)附近区域的加权中心坐标
    """
    rx, ry, rt = 0, 0, 0
    for x in range(-7, 7):
        for y in range(-7, 7):
            if (
                    0 <= i + x < img.shape[0]
                    and 0 <= j + y < img.shape[1]
            ):
                s = np.sum(img[i + x, j + y])
                if 30 < s < 255 * 3 - 30:
                    rt += 1
                    rx += x
                    ry += y
    return (i + rx / rt, j + ry / rt)


def find_latest_modified_file(folder_path):
    """返回目录中最新写入的大地图切片与目标标注文件。

    录图过程中裁剪范围会不断扩张，每次扩张都会新写一份 target_*.jpg，
    角色跨过不同地面特征时 map_*.jpg 的编号也会变化，因此目录里可能
    残留多份文件。os.listdir 的顺序不可依赖，这里按修改时间挑选最新
    的一份，保证切片图像与其目标标注的裁剪范围一致。
    """
    latest_map = None
    latest_target = None
    try:
        names = os.listdir(folder_path)
    except FileNotFoundError:
        return None, -1, -1, -1, -1, -1, None
    for name in names:
        path = os.path.join(folder_path, name)
        if not os.path.isfile(path):
            continue
        if name.startswith("map_"):
            if latest_map is None or os.path.getmtime(path) > os.path.getmtime(latest_map):
                latest_map = path
        elif name.startswith("target_"):
            if latest_target is None or os.path.getmtime(path) > os.path.getmtime(latest_target):
                latest_target = path

    x, y, map_num, upx, upy = -1, -1, -1, -1, -1
    file = latest_map
    if latest_map is not None:
        name = os.path.splitext(os.path.basename(latest_map))[0]
        try:
            map_num = name.split("_")[1]
            coords = name.split("(")[1].split(")")[0]
            x, y = map(float, coords.split(","))  # 将坐标转换为浮点数
        except (IndexError, ValueError):
            file = None
    target_path = latest_target
    if latest_target is not None:
        name = os.path.splitext(os.path.basename(latest_target))[0]
        try:
            upx = float(name.split("_")[1])
            upy = float(name.split("_")[2])
        except (IndexError, ValueError):
            target_path = None

    return file, x, y, map_num, upx, upy, target_path

