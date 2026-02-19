from dataclasses import dataclass
from typing import Any

from utils.utils.minimap_util import get_minimap, image_size, crop, area_offset, cubic_find_maximum, subtract_blur
import numpy as np
import cv2
POSITION_RADIUS = 90
POSITION_SEARCH_SCALE = 0.5
POSITION_MOVE_PATCH = (0.5, 0.5)
POSITION_FEATURE_PAD = 155
POSITION_SEARCH_RADIUS = 1.666
dict_circle_mask = {}
position: tuple[float, float] = (656.8, 60.5)
assets_floor_feat=cv2.imread("map_5f.png", cv2.IMREAD_GRAYSCALE)
assets_floor_outside_mask=cv2.imread("map_5a.png", cv2.IMREAD_GRAYSCALE)
@dataclass
class PositionPredictState:
    size: Any = None
    scale: Any = None

    search_area: Any = None
    search_image: Any = None
    result_mask: Any = None
    result: Any = None

    sim: Any = None
    loca: Any = None
    local_sim: Any = None
    local_loca: Any = None
    precise_sim: Any = None
    precise_loca: Any = None

    global_loca: Any = None
def create_circular_mask(h, w, center=None, radius=None):
    # https://stackoverflow.com/questions/44865023/how-can-i-create-a-circular-mask-for-a-numpy-array
    if center is None:  # 使用图像的中心
        center = (int(w / 2), int(h / 2))
    if radius is None:  # 使用中心点到图像边缘的最短距离
        radius = min(center[0], center[1], w - center[0], h - center[1])

    y, x = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((x - center[0]) ** 2 + (y - center[1]) ** 2)

    mask = dist_from_center <= radius
    return mask
def get_circle_mask(image):
    """
    Create a circle mask with the shape of given image,
    Masks will be cached once created.
    """
    w, h = image_size(image)
    try:
        return dict_circle_mask[(w, h)]
    except KeyError:
        mask = create_circular_mask(w=w, h=h)
        mask = (mask * 255).astype(np.uint8)
        dict_circle_mask[(w, h)] = mask
        return mask
def map_image_preprocess(image):
    """
    在ResourceGenerate和_predict_position()中使用的共享预处理方法

    Args:
        image (np.ndarray): RGB格式的屏幕截图

    Returns:
        np.ndarray:
    """
    # image = rgb2luma(image)
    image = cv2.GaussianBlur(image, (5, 5), 0)
    image = cv2.Canny(image, 15, 50)
    return image

def image_center_crop(image, size):
    """
    居中裁剪给定图像。

    Args:
        image (np.ndarray):
        size: 输出图像形状，(width, height)

    Returns:
        np.ndarray:
    """
    diff = image_size(image) - np.array(size)
    left, top = int(diff[0] / 2), int(diff[1] / 2)
    right, bottom = diff[0] - left, diff[1] - top
    image = image[top:-bottom, left:-right]
    return image
def _predict_precise_position(state):
    """
    Args:
        result (PositionPredictState): 结果状态

    Returns:
        PositionPredictState
    """
    size = state.size
    scale = state.scale
    search_area = state.search_area
    result = state.result
    loca = state.loca
    local_loca = state.local_loca

    precise = crop(result, area=area_offset((-4, -4, 4, 4), offset=loca), copy=False)
    precise_sim, precise_loca = cubic_find_maximum(precise, precision=0.05)
    precise_loca -= 5

    state.precise_sim = precise_sim
    state.precise_loca = precise_loca

    # 在search_image上的位置
    lookup_loca = precise_loca + local_loca + size * scale / 2
    # 在GIMAP上的位置
    global_loca = (lookup_loca + search_area[:2]) / POSITION_SEARCH_SCALE
    # 不知道为什么，但result_of_0.5_lookup_scale + 0.5 ~= result_of_1.0_lookup_scale
    global_loca += POSITION_MOVE_PATCH
    # 移动到地图的原点
    global_loca -= POSITION_FEATURE_PAD

    state.global_loca = global_loca

    return state


def _predict_position(image, scale=1.0):
    """
    Args:
        image: 图像
        scale: 缩放比例

    Returns:
        PositionPredictState:
    """
    scale *= POSITION_SEARCH_SCALE
    local = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    size = np.array(image_size(image))
    if sum(position) > 0:
        search_position = np.array(position, dtype=np.int64)
        search_position += POSITION_FEATURE_PAD
        search_size = np.array(image_size(local)) * POSITION_SEARCH_RADIUS
        search_half = (search_size // 2).astype(np.int64)
        search_area = area_offset((0, 0, *(search_half * 2)), offset=-search_half)
        search_area = area_offset(search_area, offset=np.multiply(search_position, POSITION_SEARCH_SCALE))
        search_area = np.array(search_area).astype(np.int64)
        search_image = crop(assets_floor_feat, search_area, copy=False)
        result_mask = crop(assets_floor_outside_mask, search_area, copy=False)
    else:
        search_area = (0, 0, *image_size(local))
        search_image = assets_floor_feat
        result_mask = assets_floor_outside_mask

    # if round(scale, 5) == self.POSITION_SEARCH_SCALE * 1.0:
    #     Image.fromarray((local).astype(np.uint8)).save('local.png')
    #     Image.fromarray((search_image).astype(np.uint8)).save('search_image.png')

    # 使用掩码将需要3倍时间
    # mask = self.get_circle_mask(local)
    # result = cv2.matchTemplate(search_image, local, cv2.TM_CCOEFF_NORMED, mask=mask)
    result = cv2.matchTemplate(search_image, local, cv2.TM_CCOEFF_NORMED)

    result_mask = ~image_center_crop(result_mask, size=image_size(result)).astype(bool)
    result[result_mask] = 0
    cv2.imshow('match_result.png', result)
    cv2.waitKey(0)
    _, sim, _, loca = cv2.minMaxLoc(result)
    # from PIL import Image
    # if round(scale, 3) == self.POSITION_SEARCH_SCALE * 1.0:
    #     result[result <= 0] = 0
    #     Image.fromarray((result * 255).astype(np.uint8)).save('match_result.png')

    # 高斯滤波获取局部最大值
    local_maximum = subtract_blur(result, radius=5)
    # 相乘以去除次级峰值
    cv2.multiply(local_maximum, result, dst=local_maximum)
    cv2.multiply(local_maximum, 10, dst=local_maximum)
    _, local_sim, _, local_loca = cv2.minMaxLoc(local_maximum)
    # if round(scale, 5) == self.POSITION_SEARCH_SCALE * 1.0:
    #     local_maximum[local_maximum < 0] = 0
    #     local_maximum[local_maximum > 1] = 1
    #     Image.fromarray((local_maximum * 255).astype(np.uint8)).save('local_maximum.png')

    # 使用CUBIC计算精确位置
    # precise = crop(result, area=area_offset((-4, -4, 4, 4), offset=local_loca), copy=False)
    # precise_sim, precise_loca = cubic_find_maximum(precise, precision=0.05)
    # precise_loca -= 5
    precise_loca = np.array((0, 0))
    precise_sim = result[local_loca[1], local_loca[0]]
    state = PositionPredictState(
        size=size, scale=scale,
        search_area=search_area, search_image=search_image, result_mask=result_mask, result=result,
        sim=sim, loca=loca, local_sim=local_sim, local_loca=local_loca,
        precise_sim=precise_sim, precise_loca=precise_loca,
    )

    # 在search_image上的位置
    lookup_loca = precise_loca + local_loca + size * scale / 2
    # 在GIMAP上的位置
    global_loca = (lookup_loca + search_area[:2]) / POSITION_SEARCH_SCALE
    # 不知道为什么，但result_of_0.5_lookup_scale + 0.5 ~= result_of_1.0_lookup_scale
    global_loca += POSITION_MOVE_PATCH
    # 移动到地图的原点
    global_loca -= POSITION_FEATURE_PAD

    state.global_loca = global_loca

    return state
def update_position(image):
    """
    获取GIMAP上的位置，耗时约6.57ms。

    将设置以下属性：
    - position_similarity
    - position
    - position_scene
    """
    image = get_minimap(image, radius=POSITION_RADIUS)
    image = map_image_preprocess(image)
    image &= get_circle_mask(image)

    best_sim = -1.
    best_scale = 1.0
    best_state = None
    # 步行时缩放为1.20
    # 跑步时缩放为1.25
    scale_list = [1.00, 1.05, 1.10, 1.15, 1.20, 1.25]

    for scale in scale_list:
        state = _predict_position(image, scale)
        # print([np.round(i, 3) for i in [scale, state.sim, state.local_sim, state.global_loca]])
        if state.sim > best_sim:
            best_sim = state.sim
            best_scale = scale
            best_state = state

    best_state = _predict_precise_position(best_state)

    position_similarity = round(best_state.precise_sim, 3)
    position_similarity_local = round(best_state.local_sim, 3)
    position = tuple(np.round(best_state.global_loca, 1))
    position_scale = round(best_scale, 3)
    print(position_scale)
    return position


if __name__ == "__main__":
    my_screen=cv2.imread("20251021_224505.png")
    print(update_position(my_screen))