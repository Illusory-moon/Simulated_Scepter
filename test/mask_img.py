from copy import deepcopy

import cv2 as cv
import numpy as np
xx=1920
yy=1080
def get_local(x, y, size,screen, large=True):
    sx, sy = size[0] + 60 * large, size[1] + 60 * large
    bx, by = xx - int(x * xx), yy - int(y * yy)
    print(f"范围y{max(0, by - sx // 2)}到{min(yy, by + sx // 2)},x{max(0, bx - sy // 2)}到{ min(xx, bx + sy // 2)}")
    return screen[
           max(0, by - sx // 2): min(yy, by + sx // 2),#y
           max(0, bx - sy // 2): min(xx, bx + sy // 2),#x
           :,
           ]
def get_end_point(sc):
    local_screen = get_local(0.4979, 0.6296, (715, 1399),sc)
    black = np.array([0, 0, 0])
    white = np.array([255, 255, 255])
    bw_map = np.zeros(local_screen.shape[:2], dtype=np.uint8)
    b_map = deepcopy(bw_map)
    b_map[np.sum((local_screen - black) ** 2, axis=-1) <= 1600] = 255
    w_map = deepcopy(bw_map)
    w_map[np.sum((local_screen - white) ** 2, axis=-1) <= 1600] = 255
    kernel = np.zeros((7, 7), np.uint8)  # 设置kenenel大小
    kernel += 1
    b_map = cv.dilate(b_map, kernel, iterations=1)  # 膨胀还原图形
    bw_map[(b_map > 200) & (w_map > 200)] = 255
    cv.imwrite("area5.jpg",bw_map)

if __name__ == '__main__':
    test_image = cv.imread('20260314_221423.png')
    get_end_point(test_image)