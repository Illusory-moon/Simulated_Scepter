import cv2
import numpy as np
from scipy import signal
from utils.utils.minimap_util import MINIMAP_RADIUS, get_minimap, rgb2yuv, RotationRemapData, peak_confidence, convolve, \
    DIRECTION_RADIUS, DIRECTION_ARROW_COLOR, area_pad, color_similarity_2d, get_bbox, area_limit, image_size, \
    DIRECTION_ROTATION_SCALE, crop, DIRECTION_SEARCH_SCALE, subtract_blur, POSITION_SEARCH_SCALE, cubic_find_maximum, \
    ArrowRotateMap, ArrowRotateMapAll, ImageNotSupported


def update_rotation(or_image=None, minimap=None):
    """
    获取角色方向，耗时约0.66ms。

    将设置以下属性：
    - direction_similarity
    - direction
    """
    d = MINIMAP_RADIUS * 2
    scale = 1
    if minimap is None:
        minimap = get_minimap(or_image, radius=MINIMAP_RADIUS)
    image = rgb2yuv(minimap)[:, :, 1].copy()
    cv2.subtract(src1=184, src2=image, dst=image)
    cv2.GaussianBlur(image, (3, 3), 0, dst=image)
    remap = cv2.remap(image, *RotationRemapData(), cv2.INTER_LINEAR)[d * 1 // 10:d * 6 // 10].astype(np.float32)

    remap = cv2.resize(remap, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    gradx = cv2.Scharr(remap, cv2.CV_32F, 1, 0)
    para = {
        'height': 35,
        'wlen': d * scale,
    }
    l = np.bincount(signal.find_peaks(gradx.ravel(), **para)[0] % (d * scale), minlength=d * scale)
    r = np.bincount(signal.find_peaks(-gradx.ravel(), **para)[0] % (d * scale), minlength=d * scale)
    l, r = np.maximum(l - r, 0), np.maximum(r - l, 0)

    conv0 = []
    kernel = 2 * scale
    r_expanded = np.concatenate([r, r, r])
    r_length = len(r)
    def roll_r(shift):
        return r_expanded[r_length - shift:r_length * 2 - shift]

    def convolve_r(ker, shift):
        return sum(roll_r(shift + i) * (ker - abs(i)) // ker for i in range(-ker + 1, ker))

    for offset in range(-kernel + 1, kernel):
        result = l * convolve_r(ker=3 * kernel, shift=-d * scale // 4 + offset)
        conv0 += [result]

    conv0 = np.maximum(conv0, 1)
    maximum = np.max(conv0, axis=0)
    rotation_confidence = round(peak_confidence(maximum), 3)
    if rotation_confidence > 0.3:
        # 匹配良好
        result = maximum
    else:
        # 再次卷积以减少噪声
        average = np.mean(conv0, axis=0)
        minimum = np.min(conv0, axis=0)
        result = convolve(maximum * average * minimum, 2 * scale)
        rotation_confidence = round(peak_confidence(maximum), 3)

    # 将匹配点转换为角度
    degree = np.argmax(result) / (d * scale) * 360 + 135
    degree = int(degree % 360)

    return degree


def update_direction(or_image=None, minimap=None):
    """
    获取角色方向，耗时约0.64ms。

    将设置以下属性：
    - direction_similarity
    - direction
    """
    if minimap is None:
        minimap = get_minimap(or_image, DIRECTION_RADIUS)

    image = color_similarity_2d(minimap, color=DIRECTION_ARROW_COLOR)

    try:
        area = area_pad(get_bbox(image, threshold=128), pad=-1)
        area = area_limit(area, (0, 0, *image_size(image)))
    except IndexError:
        print('小地图上没有方向箭头')
        return None

    image = crop(image, area=area, copy=False)
    scale = DIRECTION_ROTATION_SCALE * DIRECTION_SEARCH_SCALE
    mapping = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

    result = cv2.matchTemplate(ArrowRotateMap, mapping, cv2.TM_CCOEFF_NORMED)
    result = subtract_blur(result, 5)
    _, sim, _, loca = cv2.minMaxLoc(result)
    loca = np.array(loca) / DIRECTION_SEARCH_SCALE // (DIRECTION_RADIUS * 2)

    degree = int((loca[0] + loca[1] * 8) * 5)

    def to_map(x):
        return int((x * DIRECTION_RADIUS * 2 + DIRECTION_RADIUS) * POSITION_SEARCH_SCALE)

    row = int(degree // 8) + 45
    row = (row - 2, row + 3)
    row = (to_map(row[0]) - 5, to_map(row[1]) + 5)
    precise_map = ArrowRotateMapAll[row[0]:row[1], :].copy()

    result = cv2.matchTemplate(precise_map, mapping, cv2.TM_CCOEFF_NORMED)
    result = subtract_blur(result, 5)

    _, _, _, precise_loc = cv2.minMaxLoc(result)


    def to_map(x):
        return int((x * DIRECTION_RADIUS * 2) * POSITION_SEARCH_SCALE)

    def get_precise_sim(d):
        y, x = divmod(d, 8)
        im = result[to_map(y):to_map(y + 1), to_map(x):to_map(x + 1)]
        _, sim, _, _ = cv2.minMaxLoc(im)
        return sim

    precise = np.array([[get_precise_sim(_) for _ in range(24)]])
    precise_sim, precise_loca = cubic_find_maximum(precise, precision=0.1)
    precise_loca = degree // 8 * 8 - 16 + precise_loca[0]

    direction_similarity = round(precise_sim, 3)
    direction = round(precise_loca % 360, 1)
    print('direction:', direction, 'confidence:', direction_similarity)
    return direction


def show_minimap(image, rotation, direction=0):
    print('视角:', rotation, '角色朝向:', direction)
    position = np.array((93, 93)).astype(int)

    def vector(degree):
        degree = np.deg2rad(degree - 90)
        point = np.array(position) + np.array((np.cos(degree), np.sin(degree))) * 30
        return point.astype(int)

    image = cv2.circle(image, position, radius=2, color=(0, 0, 255), thickness=-1)
    image = cv2.line(image, position, vector(direction), color=(0, 255, 0), thickness=1)  # 绿线
    image = cv2.line(image, position, vector(rotation), color=(255, 0, 0), thickness=1)  # 蓝线
    cv2.imshow('MinimapTracking', image)
    cv2.waitKey(0)


def update_minimap_data(image=None,rotation=None,direction=None, rotation_minimap=None, direction_minimap=None):
    if rotation_minimap is None:
        rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS)
    if direction_minimap is None:
        direction_minimap = get_minimap(image, radius=DIRECTION_RADIUS)
    try:
        direction = update_direction(minimap=direction_minimap)
    except ImageNotSupported:
        return rotation, direction
    rotation = update_rotation(minimap=rotation_minimap)

    return rotation, direction


if __name__ == "__main__":
    pth = "../temp/20251019_154916.png"
    image = cv2.imread(pth)
    rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS)
    rotation, direct = update_minimap_data(image)
    show_minimap(rotation_minimap, rotation, direct)