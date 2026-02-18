import cv2
import numpy as np

from utils.utils.minimap_util import image_size, subtract_blur, group_points, inrange, remove_border


def predict_enemy(h, v,radius_enemy,mask_interact,circle_enemy):
    min_radius, max_radius = radius_enemy
    width, height = image_size(v)

    # 获取白色圆形 `y`
    y = subtract_blur(h, 3, negative=False)
    cv2.inRange(h, 168, 255, dst=h)
    cv2.bitwise_and(y, h, dst=y)
    # 获取红色光晕 `v`
    cv2.inRange(v, 168, 255, dst=v)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cv2.dilate(v, kernel, dst=v)
    # 去除噪声，只保留红色圆形
    cv2.bitwise_and(y, v, dst=y)
    # cv2.imshow('predict_enemy', y)
    # 去除游戏UI
    cv2.bitwise_and(y, mask_interact, dst=y)
    # 去除边缘上的点，否则 draw_circle() 会溢出
    remove_border(y, max_radius)

    # 获取所有像素
    points = inrange(y, lower=18)
    if points.shape[0] > 1000:
        print(f'AimDetector.predict_enemy() 绘制点过多: {points.shape}')
    # 绘制圆形
    draw = np.zeros((height, width), dtype=np.uint8)
    draw_circle(draw, circle_enemy, points)
    draw_enemy = cv2.multiply(draw, 4)
    draw_enemy = subtract_blur(draw_enemy, 3)

    # 寻找峰值
    points = inrange(draw_enemy, lower=36)

    points=group_points(points,10)
    if points.shape[0] > 3:
        print(f'AimDetector.predict_enemy() 峰值过多: {points.shape}')
    points_enemy = points
    # print(points)
    return draw_enemy,points_enemy


def predict_item(v,radius_item,mask_interact,circle_item):
    min_radius, max_radius = radius_item
    width, height = image_size(v)

    # 获取白色圆形 `y`
    y = subtract_blur(v, 9)
    white = cv2.inRange(v, 112, 144)
    cv2.bitwise_and(y, white, dst=y)
    # 获取青色光晕 `v`
    cv2.inRange(v, 0, 84, dst=v)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cv2.dilate(v, kernel, dst=v)

    # 去除噪声，只保留青色圆形
    cv2.bitwise_and(y, v, dst=y)
    # 去除游戏UI
    cv2.bitwise_and(y, mask_interact, dst=y)
    # 去除边缘上的点，否则 draw_circle() 会溢出
    remove_border(y, max_radius)

    # 获取所有像素
    points = inrange(y, lower=18)
    # print(points.shape)
    if points.shape[0] > 1000:
        print(f'AimDetector.predict_item() 绘制点过多: {points.shape}')
    # 绘制圆形
    draw = np.zeros((height, width), dtype=np.uint8)
    draw_circle(draw, circle_item, points)
    draw = subtract_blur(draw, 5)
    draw_item = cv2.multiply(draw, 4)

    # 寻找峰值
    points = inrange(draw, lower=10)
    points=group_points(points,10)
    if points.shape[0] > 3:
        print(f'AimDetector.predict_item() 峰值过多: {points.shape}')
    points_item = points
    # print(points)
    return draw_item,points_item
def aimed_enemy(points_enemy) -> tuple[int, int] | None:
    if points_enemy is None:
        return None

    count = len(points_enemy)
    if count >= 2:
        print(f'发现多个瞄准的敌人: {points_enemy}')
    try:
        point = points_enemy[0]
        return tuple(point)
    except IndexError:
        return None
def aimed_item(points_item) -> tuple[int, int] | None:
    if points_item is None:
        return None
    try:
        _ = points_item[1]
        print(f'发现多个瞄准的物品，使用第一个点 {points_item}')
    except IndexError:
        pass
    try:
        point = points_item[0]
        return tuple(point)
    except IndexError:
        return None

def predict(image, enemy=True, item=True, show_log=True, debug=False):
    """
    在图像上预测 `瞄准`，耗时约 10.0~10.5ms。

    参数:
        image:
        enemy: True 表示预测敌人
        item: True 表示预测物品
        show_log:
        debug: True 表示显示 AimDetector 图像
    """

    draw_item = None
    draw_enemy = None
    points_item = None
    points_enemy = None




    # 1.5~2.0ms
    yuv = cv2.cvtColor(image, cv2.COLOR_RGB2YUV)
    v = yuv[:, :, 2]
    h = yuv[:, :, 0]
    # 4.0~4.5ms
    if enemy:
        draw_enemy,points_enemy =predict_enemy(h.copy(), v.copy(), radius_enemy,mask_interact,circle_enemy)
    # 3.0~3.5ms
    if item:
        draw_item,points_item =predict_item(v.copy(), radius_item,mask_interact,circle_item)

    if show_log:
        kv = {}
        kv['enemy'] = aimed_enemy(points_enemy)
        kv['item'] = aimed_item(points_item)
        if kv:
            print(f'Aimed: {kv}')
    if debug:
        show_aim(draw_enemy,draw_item)
def show_aim(draw_enemy,draw_item):
    if draw_enemy is None:
        if draw_item is None:
            return
        else:
            r = g = b = draw_item
    else:
        if draw_item is None:
            r = g = b = draw_enemy
        else:
            r = draw_enemy
            g = b = draw_item

    image = cv2.merge([b, g, r])

    cv2.imshow('AimDetector', image)
    cv2.waitKey(0)