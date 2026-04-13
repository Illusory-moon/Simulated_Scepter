from copy import deepcopy

import numpy as np
import cv2 as cv

from utils.utils.minimap_util import get_minimap, MINIMAP_RADIUS


def get_bw_map(local_screen=None):
    """
        进一步得到小地图的黑白格式
        re_screen：是否重新截图
        大小是186*186
    """
    black = np.array([0, 0, 0])
    white = np.array([210, 210, 210])
    gray = np.array([55, 55, 55])
    # local_screen=screen[46:222,43:219]#[43,46,219,222]源范围  正确范围#[45,56,231,242]
    # local_screen=screen[56:242,45:231]#[43,46,219,222]源范围  正确范围#[45,56,231,242] 偏移[2,10,12,20]
    local_screen = get_minimap(local_screen, radius=MINIMAP_RADIUS, copy=True, rotation=True, center_radius=93)

    # local_screen[np.sum(np.abs(local_screen - blue), axis=-1) <= 50] = 0
    hsv = cv.cvtColor(local_screen, cv.COLOR_BGR2HSV)  # 转HSV
    lower = np.array([80, 60, 60])  # 90 改成120只剩箭头，但是角色移动过的印记会消失
    upper = np.array([110, 255, 255])

    mask = cv.inRange(hsv, lower, upper)  # 创建掩膜
    loc_tp = cv.bitwise_and(local_screen, local_screen, mask=mask)
    local_screen = local_screen - loc_tp
    bw_map = np.zeros(local_screen.shape[:2], dtype=np.uint8)
    # 灰块、白线：小地图中的可移动区域、可移动区域的边缘
    # b_map：当前像素点是否是灰块。只允许灰块附近（2像素）的像素被识别为白线
    grey_map = deepcopy(bw_map)
    grey_map[
        np.sum((local_screen - gray) ** 2, axis=-1) <= 4800
        ] = 255
    kernel = np.zeros((5, 5), np.uint8)  # 设置kenenel大小
    kernel += 1
    grey_map = cv.dilate(grey_map, kernel, iterations=1)
    bw_map[
        (np.sum((local_screen - white) ** 2, axis=-1) <= 9000)
        & (grey_map > 200)
        ] = 255
    # 排除半径90以外的像素点
    for i in range(bw_map.shape[0]):
        for j in range(bw_map.shape[1]):
            if ((i - 93) ** 2 + (j - 93) ** 2) > 90 ** 2:
                bw_map[i, j] = 0
    return bw_map