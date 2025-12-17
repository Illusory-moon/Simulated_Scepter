import os

import numpy as np
import win32gui


def get_hwnd_and_text():
    hwnd = win32gui.GetForegroundWindow()
    Text = win32gui.GetWindowText(hwnd)
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
    files = [
        os.path.join(folder_path, file)
        for file in os.listdir(folder_path)
        if file.split("/")[-1][0] == "m"
    ]
    nx, ny = 4096, 4096
    file = ""
    for i in files:
        try:
            x, y = i.split("_")[-3:-1]
            x, y = int(x), int(y)
            if x < nx or y < ny:
                nx, ny = x, y
                file = i
        except:
            pass
    return file

