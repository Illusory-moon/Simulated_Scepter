import cv2
import numpy as np
from scipy import signal
from PIL import Image

from route import PATHS
MINIMAP_RADIUS = 93
MINIMAP_CENTER = (45 + MINIMAP_RADIUS, 56 + MINIMAP_RADIUS)#(138,149)
DIRECTION_RADIUS = 17
DIRECTION_ARROW_COLOR = (255, 199, 2)
DIRECTION_ROTATION_SCALE = 1.0
DIRECTION_SEARCH_SCALE = 0.5
POSITION_SEARCH_SCALE = 0.5

def load_image(file, area=None):
    """
    Load an image like pillow and drop alpha channel.

    Args:
        file (str):
        area (tuple):

    Returns:
        np.ndarray:
    """
    # always remember to close Image object
    with Image.open(file) as f:
        if area is not None:
            f = f.crop(area)

        image = np.array(f)

    channel = image_channel(image)
    if channel == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)

    return image

class ImageNotSupported(Exception):
    """
    Raised if we can't perform image calculation on this image
    """
    pass
def cubic_find_maximum(image, precision=0.05):
    """
    使用CUBIC调整算法拟合曲面，找到最大值和位置。

    Args:
        image (np.ndarray):
        precision (int, float):

    Returns:
        float: 曲面上的最大值
        np.ndarray[float, float]: 最大值的位置
    """
    image = cv2.resize(image, None, fx=1 / precision, fy=1 / precision, interpolation=cv2.INTER_CUBIC)
    _, sim, _, loca = cv2.minMaxLoc(image)
    loca = np.array(loca, dtype=float) * precision
    return sim, loca
def subtract_blur(image, radius=3, negative=False):
    """
    If you care performance more than quality:
    - radius=3, use medianBlur
    - radius=5,7,9,11, use GaussianBlur
    - radius>11, use stackBlur (requires opencv >= 4.7.0)

    Args:
        image:
        radius:
        negative:

    Returns:
        np.ndarray:
    """
    if radius <= 3:
        blur = cv2.medianBlur(image, radius)
    elif radius <= 11:
        blur = cv2.GaussianBlur(image, (radius, radius), 0)
    else:
        blur = cv2.stackBlur(image, (radius, radius), 0)

    if negative:
        cv2.subtract(blur, image, dst=blur)
    else:
        cv2.subtract(image, blur, dst=blur)
    return blur
def image_size(image):
    """
    Args:
        image (np.ndarray):

    Returns:
        int, int: width, height
    """
    shape = image.shape
    return shape[1], shape[0]
def limit_in(x, lower, upper):
    """
    Limit x within range (lower, upper)

    Args:
        x:
        lower:
        upper:

    Returns:
        int, float:
    """
    return max(min(x, upper), lower)
def area_limit(area1, area2):
    """
    Limit an area in another area.

    Args:
        area1: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
        area2: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).

    Returns:
        tuple: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
    """
    x_lower, y_lower, x_upper, y_upper = area2
    return (
        limit_in(area1[0], x_lower, x_upper),
        limit_in(area1[1], y_lower, y_upper),
        limit_in(area1[2], x_lower, x_upper),
        limit_in(area1[3], y_lower, y_upper),
    )
def image_channel(image):
    """
    Args:
        image (np.ndarray):

    Returns:
        int: 0 for grayscale, 3 for RGB.
    """
    return image.shape[2] if len(image.shape) == 3 else 0
def get_bbox(image, threshold=0):
    """
    获取图像中内容的边界框
    这是pillow中getbbox()函数的opencv实现

    参数:
        image (np.ndarray): 输入图像
        threshold (int):
            颜色值 > threshold 的像素将被视为内容
            颜色值 <= threshold 的像素将被视为背景

    返回:
        tuple[int, int, int, int]: 边界框坐标 (左, 上, 右, 下)

    异常:
        ImageNotSupported: 如果无法获取边界框则抛出此异常
    """
    channel = image_channel(image)
    # convert to grayscale
    if channel == 3:
        # RGB
        mask = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        cv2.threshold(mask, threshold, 255, cv2.THRESH_BINARY, dst=mask)
    elif channel == 0:
        # grayscale
        _, mask = cv2.threshold(image, threshold, 255, cv2.THRESH_BINARY)
    elif channel == 4:
        # RGBA
        mask = cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        cv2.threshold(mask, threshold, 255, cv2.THRESH_BINARY, dst=mask)
    else:
        raise ImageNotSupported(f'shape={image.shape}')

    # find bbox
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_y, min_x = mask.shape
    max_x = 0
    max_y = 0
    # all black
    if not contours:
        raise ImageNotSupported(f'Cannot get bbox from a pure black image')
    for contour in contours:
        # x, y, w, h
        x1, y1, x2, y2 = cv2.boundingRect(contour)
        x2 += x1
        y2 += y1
        if x1 < min_x:
            min_x = x1
        if y1 < min_y:
            min_y = y1
        if x2 > max_x:
            max_x = x2
        if y2 > max_y:
            max_y = y2
    if min_x < max_x and min_y < max_y:
        return min_x, min_y, max_x, max_y
    else:
        # This shouldn't happen
        raise ImageNotSupported(f'Empty bbox {(min_x, min_y, max_x, max_y)}')
def area_pad(area, pad=10):
    """
    Inner offset an area.

    Args:
        area: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
        pad (int):

    Returns:
        tuple: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
    """
    upper_left_x, upper_left_y, bottom_right_x, bottom_right_y = area
    return upper_left_x + pad, upper_left_y + pad, bottom_right_x - pad, bottom_right_y - pad
def color_similarity_2d(image, color):
    """
    Args:
        image: 2D array.
        color: (r, g, b)

    Returns:
        np.ndarray: uint8
    """
    # r, g, b = cv2.split(cv2.subtract(image, (*color, 0)))
    # positive = cv2.max(cv2.max(r, g), b)
    # r, g, b = cv2.split(cv2.subtract((*color, 0), image))
    # negative = cv2.max(cv2.max(r, g), b)
    # return cv2.subtract(255, cv2.add(positive, negative))
    diff = cv2.subtract(image, (*color, 0))
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    positive = r
    cv2.subtract((*color, 0), image, dst=diff)
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    negative = r
    cv2.add(positive, negative, dst=positive)
    cv2.subtract(255, positive, dst=positive)
    return positive
def RotationRemapData():
    d = MINIMAP_RADIUS * 2
    mx = np.zeros((d, d), dtype=np.float32)
    my = np.zeros((d, d), dtype=np.float32)
    for i in range(d):
        for j in range(d):
            mx[i, j] = d / 2 + i / 2 * np.cos(2 * np.pi * j / d)
            my[i, j] = d / 2 + i / 2 * np.sin(2 * np.pi * j / d)
    return mx, my
def copy_image(src):
    """
    Equivalent to image.copy() but a little bit faster

    Time cost to copy a 1280*720*3 image:
        image.copy()      0.743ms
        copy_image(image) 0.639ms
    """
    dst = np.empty_like(src)
    cv2.copyTo(src, None, dst)
    return dst
def crop(image, area, copy=True):
    """
    Crop image like pillow, when using opencv / numpy.
    Provides a black background if cropping outside of image.

    Args:
        image (np.ndarray):
        area:
        copy (bool):

    Returns:
        np.ndarray:
    """
    # map(round, area)
    x1, y1, x2, y2 = area
    x1 = round(x1)
    y1 = round(y1)
    x2 = round(x2)
    y2 = round(y2)
    # h, w = image.shape[:2]
    shape = image.shape
    h = shape[0]
    w = shape[1]
    # top, bottom, left, right
    # border = np.maximum((0 - y1, y2 - h, 0 - x1, x2 - w), 0)
    overflow = False
    if y1 >= 0:
        top = 0
        if y1 >= h:
            overflow = True
    else:
        top = -y1
    if y2 > h:
        bottom = y2 - h
    else:
        bottom = 0
        if y2 <= 0:
            overflow = True
    if x1 >= 0:
        left = 0
        if x1 >= w:
            overflow = True
    else:
        left = -x1
    if x2 > w:
        right = x2 - w
    else:
        right = 0
        if x2 <= 0:
            overflow = True
    # If overflowed, return empty image
    if overflow:
        if len(shape) == 2:
            size = (y2 - y1, x2 - x1)
        else:
            size = (y2 - y1, x2 - x1, shape[2])
        return np.zeros(size, dtype=image.dtype)
    # x1, y1, x2, y2 = np.maximum((x1, y1, x2, y2), 0)
    if x1 < 0:
        x1 = 0
    if y1 < 0:
        y1 = 0
    if x2 < 0:
        x2 = 0
    if y2 < 0:
        y2 = 0
    # crop image
    image = image[y1:y2, x1:x2]
    # if border
    if top or bottom or left or right:
        if len(shape) == 2:
            value = 0
        else:
            value = tuple(0 for _ in range(image.shape[2]))
        return cv2.copyMakeBorder(image, top, bottom, left, right, borderType=cv2.BORDER_CONSTANT, value=value)
    elif copy:
        return copy_image(image)
    else:
        return image
def area_offset(area, offset):
    """
    Move an area.

    Args:
        area: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
        offset: (x, y).

    Returns:
        tuple: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y).
    """
    upper_left_x, upper_left_y, bottom_right_x, bottom_right_y = area
    x, y = offset
    return upper_left_x + x, upper_left_y + y, bottom_right_x + x, bottom_right_y + y


def rotate_minimap(minimap, angle):
    """
    以(93,93)为中心旋转小地图

    Args:
        minimap: 小地图图像数组
        angle: 旋转角度（度），正数为顺时针

    Returns:
        旋转后的小地图图像
    """
    height, width = minimap.shape[:2]
    center = (MINIMAP_RADIUS, MINIMAP_RADIUS)
    # 计算旋转矩阵
    rotation_matrix = cv2.getRotationMatrix2D(center, -angle, 1.0)  # 负号是因为OpenCV中正角度是逆时针
    rotated_minimap = cv2.warpAffine(minimap, rotation_matrix, (width, height),
                                     flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                     borderValue=(0, 0, 0))  # 使用黑色填充边界

    return rotated_minimap
def get_minimap(image, radius,copy=False,rotation=False):
    """
    Crop the minimap area on image.
    """
    area = area_offset((-radius, -radius, radius, radius), offset=MINIMAP_CENTER)
    image = crop(image, area, copy=copy)
    if rotation:
        from utils.utils.mminimap import update_rotation
        # 获取输入图片的视角角度
        input_rotation = update_rotation(minimap=image)
        # 读取0度视角纹理图
        zero_degree_texture_path = "resource/imgs/only_rotated.png"
        zero_texture = cv2.imread(zero_degree_texture_path)
        # 根据输入图片的视角旋转0度视角纹理图
        rotated_texture = rotate_minimap(zero_texture, input_rotation)
        # 将输入图片的小地图与旋转后的视角纹理相减
        image = cv2.subtract(image, rotated_texture)
    return image
def convolve(arr, kernel=3):
    """
    Args:
        arr (np.ndarray): 形状 (N,)
        kernel (int):

    Returns:
        np.ndarray:
    """
    return sum(np.roll(arr, i) * (kernel - abs(i)) // kernel for i in range(-kernel + 1, kernel))
def peak_confidence(arr, **kwargs):
    """
    评估最高峰值的显著性

    Args:
        arr (np.ndarray): 形状 (N,)
        **kwargs: signal.find_peaks的额外参数

    Returns:
        float: 0-1
    """
    para = {
        'height': 0,
        'prominence': 10,
    }
    para.update(kwargs)
    length = len(arr)
    peaks, properties = signal.find_peaks(np.concatenate((arr, arr, arr)), **para)
    peaks = [h for p, h in zip(peaks, properties['peak_heights']) if length <= p < length * 2]
    peaks = sorted(peaks, reverse=True)

    count = len(peaks)
    if count > 1:
        highest, second = peaks[0], peaks[1]
    elif count == 1:
        highest, second = 1, 0
    else:
        highest, second = 1, 0
    confidence = (highest - second) / highest
    return confidence
def rgb2yuv(image):
    """
    Convert RGB to YUV color space.

    Args:
        image (np.ndarray): Shape (height, width, channel)

    Returns:
        np.ndarray: Shape (height, width)
    """
    image = cv2.cvtColor(image, cv2.COLOR_RGB2YUV)
    return image

path=PATHS["image"]+"/ArrowRotateMap.png"
ArrowRotateMap=load_image(path)
path=PATHS["image"]+"/ArrowRotateMapAll.png"
ArrowRotateMapAll=load_image(path)