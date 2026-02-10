from copy import deepcopy

import cv2 as cv
import numpy as np

from utils.utils.minimap_util import rotate_minimap, mask_minimap_center, crop
MINIMAP_RADIUS = 93
#(138,149)精准中心点
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
def get_minimap(image, copy=False,rotation=False):
    """
    Crop the minimap area on image.
    """
    area = [45,56,231,242]#[45,56,231,242]左上，右下
    image = crop(image, area, copy=copy)
    if rotation:
        from utils.utils.mminimap import update_rotation
        # 获取输入图片的视角角度
        input_rotation = update_rotation(minimap=image)
        # 读取0度视角纹理图
        zero_degree_texture_path = "resource/imgs/only_rotated.png"
        zero_texture = cv.imread(zero_degree_texture_path)
        # 根据输入图片的视角旋转0度视角纹理图
        rotated_texture = rotate_minimap(zero_texture, input_rotation)
        # 将输入图片的小地图与旋转后的视角纹理相减
        image = cv.subtract(image, rotated_texture)
        #掩膜掩盖非中心区域避免遇敌红色圈干扰敌人追踪
        image = mask_minimap_center(image, center_radius=80)
    return image


def get_bw_map(self, local_screen=None, re_screen=1):
    """
        进一步得到小地图的黑白格式
        re_screen：是否重新截图
        大小是186*186
    """
    try:
        if re_screen and self.click_text(text="选择祝福", box=[60, 222, 0, 113], click=False, ocr_line=False,
                                         warning=False):
            return None
        black = np.array([0, 0, 0])
        white = np.array([210, 210, 210])
        gray = np.array([55, 55, 55])
        # local_screen=screen[46:222,43:219]#[43,46,219,222]源范围  正确范围#[45,56,231,242]
        # local_screen=screen[56:242,45:231]#[43,46,219,222]源范围  正确范围#[45,56,231,242] 偏移[2,10,12,20]
        if local_screen is None:
            local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True, rotation=True)
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
            (np.sum((local_screen - white) ** 2, axis=-1) <= 4800)
            & (grey_map > 200)
            ] = 255
        # 排除半径85以外的像素点
        for i in range(bw_map.shape[0]):
            for j in range(bw_map.shape[1]):
                if ((i - 93) ** 2 + (j - 93) ** 2) > 85 ** 2:
                    bw_map[i, j] = 0
        cv.imwrite("bwmap.jpg", bw_map)
        return bw_map
    except Exception as e:
        print(f"get_bw_map函数执行出错: {str(e)}")
        return None
        return None
if __name__ == "__main__":
    my_screen=cv.imread("20251021_203128.png")
    minimap_img = get_minimap(my_screen, copy=True)
    cv.imwrite("minimap.png", minimap_img)
    get_bw_map(my_screen)