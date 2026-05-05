from datetime import datetime

from tool.utils.image_tool import find_image_by_name
from importing import load_img
load_img()
import cv2
import numpy as np
from scipy import signal
from tool.utils.minimap_util import rgb2yuv, RotationRemapData, peak_confidence, convolve, \
    DIRECTION_RADIUS, DIRECTION_ARROW_COLOR, area_pad, color_similarity_2d, get_bbox, area_limit, image_size, \
    DIRECTION_ROTATION_SCALE, crop, DIRECTION_SEARCH_SCALE, subtract_blur, POSITION_SEARCH_SCALE, cubic_find_maximum, \
    ArrowRotateMap, ArrowRotateMapAll, area_offset, MINIMAP_RADIUS, map_image_preprocess

# matplotlib.use('Qt5Agg')


def detect_minimap_center(image):
    """
    通过白色圆形边缘模板匹配检测小地图中心
    """
    # 创建白色圆形边缘模板
    template = np.zeros((2*MINIMAP_RADIUS, 2*MINIMAP_RADIUS), dtype=np.uint8)
    cv2.circle(template, (MINIMAP_RADIUS, MINIMAP_RADIUS), MINIMAP_RADIUS, 255, 3)
    gray_template = template
    
    result = cv2.matchTemplate(image, gray_template, cv2.TM_CCOEFF_NORMED)
    _, _, _, max_loc = cv2.minMaxLoc(result)
    
    # 计算实际中心坐标
    center_x = max_loc[0] + MINIMAP_RADIUS
    center_y = max_loc[1] + MINIMAP_RADIUS
    print("minimap center:", center_x, center_y)
    return (center_x, center_y)

def get_minimap(image, radius, copy=False, rotation=False, center_radius=80):
    """
    裁剪图像中的小地图区域

    Args:
        image (np.ndarray): 输入图像
        radius (int): 裁剪半径
        copy (bool): 是否复制图像
        rotation (bool): 是否进行旋转校正
        center_radius (int): 中心掩膜半径

    Returns:
        np.ndarray: 处理后的小地图图像
    """
    # 通过模板匹配获取准确的MINIMAP_CENTER
    area = [0,0,245,255]
    MINIMAP_CENTER = detect_minimap_center(map_image_preprocess(crop(image, area, copy=copy)))
    area = area_offset((-radius, -radius, radius, radius), offset=MINIMAP_CENTER)
    image = crop(image, area, copy=copy)
    if rotation:
        from tool.utils.mminimap import update_rotation
        # 获取输入图片的视角角度
        input_rotation = update_rotation(minimap=image)
        # 读取0度视角纹理图
        zero_texture = find_image_by_name("only_rotated.png")

        # 根据输入图片的视角旋转0度视角纹理图
        rotated_texture = rotate_minimap(zero_texture, input_rotation)
        # 从纹理中心裁剪以匹配目标图像尺寸
        if rotated_texture.shape != image.shape:
            tex_h, tex_w = rotated_texture.shape[:2]
            target_h, target_w = image.shape[:2]
            center_y, center_x = tex_h // 2, tex_w // 2
            half_target_h, half_target_w = target_h // 2, target_w // 2

            # 计算裁剪边界
            y1 = max(0, center_y - half_target_h)
            y2 = min(tex_h, center_y + half_target_h + (target_h % 2))
            x1 = max(0, center_x - half_target_w)
            x2 = min(tex_w, center_x + half_target_w + (target_w % 2))

            rotated_texture = rotated_texture[y1:y2, x1:x2]
        image = cv2.subtract(image, rotated_texture)

        # 掩膜掩盖非中心区域避免遇敌红色圈干扰敌人追踪
        image = mask_minimap_center(image, center_radius=center_radius)
    return image
def update_rotation(or_image=None,minimap=None):
    """
    获取角色方向，耗时约0.66ms。

    将设置以下属性：
    - direction_similarity
    - direction
    """
    d = MINIMAP_RADIUS * 2
    scale = 1
    # 提取
    if minimap is None:
        minimap = get_minimap(or_image, radius=MINIMAP_RADIUS)
    image = rgb2yuv(minimap)[:, :, 1].copy()
    cv2.subtract(src1=184, src2=image, dst=image)

    cv2.GaussianBlur(image, (3, 3), 0, dst=image)
    # 将圆形展开为矩形
    remap = cv2.remap(image, *RotationRemapData(), cv2.INTER_LINEAR)[d * 1 // 10:d * 6 // 10].astype(np.float32)

    remap = cv2.resize(remap, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    # remap = cv2.warpPolar(image, (d,d), (d//2,d//2),d//2, cv2.WARP_POLAR_LINEAR).T[d * 1 // 10:d * 6 // 10]#.astype(np.float32)

    # 查找导数
    gradx = cv2.Scharr(remap, cv2.CV_32F, 1, 0)
    # cv2.imshow("minimap", gradx)
    # cv2.waitKey(0)
    # import matplotlib.pyplot as plt
    # plt.imshow(gradx)
    # plt.show()

    # scipy.find_peaks的魔法参数
    para = {
        # 'height': (50, 800),
        'height': 35,
        # 'prominence': (0, 400),
        # 'width': (0, d * scale / 20),
        # 'distance': d * scale / 18,
        'wlen': d * scale,
    }
    # plt.plot(gradx[d * 3 // 10])
    # plt.show()

    # `l`表示视线区域的左侧，导数为正
    # `r`表示视线区域的右侧，导数为负
    l = np.bincount(signal.find_peaks(gradx.ravel(), **para)[0] % (d * scale), minlength=d * scale)
    r = np.bincount(signal.find_peaks(-gradx.ravel(), **para)[0] % (d * scale), minlength=d * scale)
    l, r = np.maximum(l - r, 0), np.maximum(r - l, 0)
    # plt.plot(l)
    # plt.plot(np.roll(r, -d * scale // 4))
    # plt.show()

    conv0 = []
    kernel = 2 * scale
    r_expanded = np.concatenate([r, r, r])
    r_length = len(r)

    # 比嵌套调用np.roll()更快
    def roll_r(shift):
        return r_expanded[r_length - shift:r_length * 2 - shift]

    def convolve_r(ker, shift):
        return sum(roll_r(shift + i) * (ker - abs(i)) // ker for i in range(-ker + 1, ker))

    for offset in range(-kernel + 1, kernel):
        result = l * convolve_r(ker=3 * kernel, shift=-d * scale // 4 + offset)
        # result = l * convolve(np.roll(r, -d * scale // 4 + offset), kernel=3 * scale)
        # minus = l * convolve(np.roll(r, offset), kernel=10 * scale) // 5
        # if offset == 0:
        #     plt.plot(result)
        #     plt.plot(-minus)
        #     plt.show()
        # result -= minus
        # result = convolve(result, kernel=3 * scale)
        conv0 += [result]
    # plt.figure(figsize=(20, 16))
    # for row in conv0:
    #     plt.plot(row)
    # plt.show()

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
    # plt.plot(maximum)
    # plt.plot(result)
    # plt.show()

    # 将匹配点转换为角度
    degree = np.argmax(result) / (d * scale) * 360 + 135
    degree = int(degree % 360)

    rotation_confidence = rotation_confidence
    print('rotation:', degree, 'confidence:', rotation_confidence)

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
        return int((x * DIRECTION_RADIUS * 2 + DIRECTION_RADIUS) * 0.5)

    row = int(degree // 8) + 45
    row = (row - 2, row + 3)
    row = (to_map(row[0]) - 5, to_map(row[1]) + 5)
    precise_map = ArrowRotateMapAll[row[0]:row[1], :].copy()

    result = cv2.matchTemplate(precise_map, mapping, cv2.TM_CCOEFF_NORMED)
    result = subtract_blur(result, 5)

    _, _, _, precise_loc = cv2.minMaxLoc(result)


    def to_map(x):
        return int((x * DIRECTION_RADIUS * 2) * 0.5)

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
def get_now_direct(loc_scr):
    """
        计算小地图中蓝色箭头的角度，以正上为0度，逆时针增加
    """
    hsv = cv2.cvtColor(loc_scr, cv2.COLOR_BGR2HSV)  # 转HSV
    lower = np.array([93, 120, 60])  # 90 改成120只剩箭头，但是角色移动过的印记会消失
    upper = np.array([97, 255, 255])


    mask = cv2.inRange(hsv, lower, upper)  # 创建掩膜
    loc_tp = cv2.bitwise_and(loc_scr, loc_scr, mask=mask)
    # bgr=cv2.cvtColor(loc_tp, cv2.COLOR_HSV2BGR)
    # cv2.imshow("blue",bgr)
    # loc_tp[np.sum(np.abs(loc_tp - blue), axis=-1) > 0] = [0, 0, 0]
    # 裁剪loc_tp至中心24x24区域
    h, w = loc_tp.shape[:2]
    center_h, center_w = h // 2, w // 2
    crop_size = 12  # 24x24区域的一半是12
    loc_tp = loc_tp[center_h - crop_size - 5:center_h + crop_size - 5,
             center_w - crop_size:center_w + crop_size]
    path = "../resource/imgs/combined_arrows.jpg"
    arrows_img = cv2.imread(path)
    # 在拼接的大图上进行一次匹配
    result = cv2.matchTemplate(arrows_img, loc_tp, cv2.TM_SQDIFF)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    # 根据匹配位置计算对应的角度
    best_row = (min_loc[1] + 12) // 26  # 行号
    best_col = (min_loc[0] + 12) // 26  # 列号
    ang = best_row * 12 + best_col  # 对应的角度
    # 在combined_img上框出匹配到的结果
    # combined_img_with_rect = arrows_img.copy()
    # # log.info(f"角度：{ang}行：{best_row}列：{best_col}")
    # cv2.rectangle(combined_img_with_rect, min_loc,
    #             (min_loc[0] + loc_tp.shape[1], min_loc[1] + loc_tp.shape[0]),
    #             (0, 0, 255), 1)
    # cv2.imshow("匹配结果", loc_tp)
    # cv2.imshow("匹配目标", combined_img_with_rect)
    # cv2.waitKey(0)
    print(f"角度：{ang}行：{best_row}列：{best_col}")
    return -ang
def show_minimap(image,rotation,direction=0):
    # image = cv2.cvtColor(self.assets_floor, cv2.COLOR_RGB2BGR)
    # direction=direction%360
    print('视角:', rotation, '角色朝向:', direction)
    position = np.array((93,93)).astype(int)

    def vector(degree):
        degree = np.deg2rad(degree - 90)
        point = np.array(position) + np.array((np.cos(degree), np.sin(degree))) * 30
        return point.astype(int)

    image = cv2.circle(image, position, radius=2, color=(0, 0, 255), thickness=-1)
    image = cv2.line(image, position, vector(direction), color=(0, 255, 0), thickness=1)#绿线
    image = cv2.line(image, position, vector(rotation), color=(255, 0, 0), thickness=1)#蓝线
    cv2.imshow('MinimapTracking', image)
    cv2.waitKey(0)

def update_minimap_data(image=None,rotation_minimap=None, direction_minimap=None):
    if rotation_minimap is None:
        rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS,copy=True)
    if direction_minimap is None:
        direction_minimap = get_minimap(image, radius=DIRECTION_RADIUS,copy=True)
    rotation = update_rotation(minimap=rotation_minimap)
    direction=update_direction(minimap=direction_minimap)
    return rotation, direction
def analyze_red(img):
    red = [115, 100, 200]#[207,96,102] [232,46,46]
    minimap_img = get_minimap(img, radius=MINIMAP_RADIUS, copy=True)

    # 显示红色通道图像
    red_channel = minimap_img[:, :, 2]  # OpenCV中BGR格式，索引2为红色通道
    cv2.imshow('Red Channel', red_channel)
    cv2.waitKey(0)

    # 显示 (minimap_img - red) ** 2 的结果（转换为灰度图）
    squared_diff = (minimap_img - red) ** 2
    # 将小于0的值置为0（虽然平方后不应该有负数，但为了安全起见）
    squared_diff = np.maximum(squared_diff, 0).astype(np.uint8)
    # 转换为灰度图
    squared_diff_gray = np.sum(squared_diff, axis=-1).astype(np.uint8)
    cv2.imshow('Minimap Squared Diff (Grayscale)', squared_diff_gray)
    cv2.waitKey(0)
    
    # 原始彩色版本（如果您还需要对比）
    cv2.imshow('Minimap Squared Diff (Color)', squared_diff)
    cv2.waitKey(0)
    
    rd = np.where(np.sum((minimap_img - red) ** 2, axis=-1) <= 512)
    
    # 创建一个副本用于显示
    display_img = minimap_img.copy()
    
    # 检查是否有检测到的红点
    if len(rd[0]) > 0 and len(rd[1]) > 0:
        # 仅在第一个检测到的红点位置标记
        y, x = rd[0][0], rd[1][0]
        cv2.circle(display_img, (x, y), 2, (0, 255, 0), -1)  # 用绿色圆圈标记第一个红点
    
    # 显示图像
    cv2.imshow('First Detected Red Point', display_img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    
    print(rd)

def rotate_minimap(minimap, angle):
    """
    以(93,93)为中心旋转小地图
    
    Args:
        minimap: 小地图图像数组
        angle: 旋转角度（度），正数为顺时针
        
    Returns:
        旋转后的小地图图像
    """
    # 获取图像尺寸
    height, width = minimap.shape[:2]
    
    # 定义旋转中心
    center = (93, 93)
    
    # 计算旋转矩阵
    rotation_matrix = cv2.getRotationMatrix2D(center, -angle, 1.0)  # 负号是因为OpenCV中正角度是逆时针
    
    # 执行旋转
    rotated_minimap = cv2.warpAffine(minimap, rotation_matrix, (width, height), 
                                     flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, 
                                     borderValue=(0, 0, 0))  # 使用黑色填充边界
    
    return rotated_minimap

def mask_minimap_center(minimap, center_radius=40):
    """
    保留小地图圆心区域，其余部分用黑色遮蔽
    
    Args:
        minimap: 小地图图像数组
        center_radius: 圆心区域的半径，默认为40
        
    Returns:
        处理后的小地图图像，仅保留中心圆形区域
    """
    # 获取图像尺寸
    height, width = minimap.shape[:2]
    
    # 定义中心点（根据代码中的信息，小地图中心为(93,93)）
    center = (93, 93)
    
    # 创建一个黑色掩码
    mask = np.zeros((height, width), dtype=np.uint8)
    
    # 在掩码上绘制一个白色圆形区域
    cv2.circle(mask, center, center_radius, (255), -1)
    
    # 将掩码应用到原图像
    masked_minimap = cv2.bitwise_and(minimap, minimap, mask=mask)
    
    return masked_minimap

def mask_minimap_outside(minimap, center_radius=40, outer_radius=None):
    """
    保留小地图圆环区域（环形区域），圆心和外围部分用黑色遮蔽
    
    Args:
        minimap: 小地图图像数组
        center_radius: 圆心区域的半径，默认为 40
        outer_radius: 外圆半径，默认为 None（使用图像最大半径减 5）
        
    Returns:
        处理后的小地图图像，仅保留圆环区域
    """
    # 获取图像尺寸
    height, width = minimap.shape[:2]
    center = (93, 93)
    max_radius = min(width, height) // 2
    if outer_radius is None:
        outer_radius = max_radius - 5
    else:
        outer_radius = min(outer_radius, max_radius)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.circle(mask, center, outer_radius, (255), -1)
    cv2.circle(mask, center, min(center_radius, outer_radius - 5), (0), -1)
    masked_minimap = cv2.bitwise_and(minimap, minimap, mask=mask)
    
    return masked_minimap


def subtract_rotated_texture(image_path, zero_degree_texture_path):
    """
    传入一张图片，获取其minimap与其视角，然后根据其视角旋转该视角纹理图，
    然后把传入的图片的minimap旋转对应角度的视角纹理相减以获取正确的小地图背景
    
    Args:
        image_path (str): 输入图片路径
        zero_degree_texture_path (str): 0度视角纹理图路径
        
    Returns:
        np.ndarray: 相减后的小地图背景
    """
    # 读取输入图片
    img = cv2.imread(image_path)
    if img is None:
        print(f"无法读取图片: {image_path}")
        return None
    
    # 获取输入图片的小地图区域
    input_minimap = get_minimap(img, radius=MINIMAP_RADIUS)
    
    # 获取输入图片的视角角度
    input_rotation = update_rotation(minimap=input_minimap)
    print(f"输入图片的视角角度为: {input_rotation}度")
    
    # 读取0度视角纹理图
    zero_texture = cv2.imread(zero_degree_texture_path)
    if zero_texture is None:
        print(f"无法读取0度视角纹理图: {zero_degree_texture_path}")
        return None
    
    # 根据输入图片的视角旋转0度视角纹理图
    rotated_texture = rotate_minimap(zero_texture, input_rotation)
    
    # 将输入图片的小地图与旋转后的视角纹理相减
    background_diff = cv2.subtract(input_minimap, rotated_texture)
    
    # 显示结果
    cv2.imshow("Minimap Background Difference", background_diff)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"minimap_background_diff_{timestamp}.png"
    success = cv2.imwrite(output_path, background_diff)
    if success:
        print(f"小地图背景差异图已保存至: {output_path}")
    else:
        print(f"小地图背景差异图保存失败: {output_path}")
    
    return background_diff

def test_mask_minimap_center(image_path, center_radius=40):
    """
    测试函数：传入完整图片，提取小地图，应用中心区域掩码，并保存结果
    
    Args:
        image_path (str): 完整图片路径
        center_radius (int): 圆心区域的半径，默认为40
        
    Returns:
        np.ndarray: 应用掩码后的小地图图像
    """
    # 读取完整图片
    img = cv2.imread(image_path)
    if img is None:
        print(f"无法读取图片: {image_path}")
        return None
    
    # 从小地图中提取指定半径的区域
    minimap = get_minimap(img, radius=MINIMAP_RADIUS)
    
    # 应用中心区域掩码
    masked_minimap = mask_minimap_center(minimap, center_radius=center_radius)
    
    # 显示结果
    cv2.imshow("Original Minimap", minimap)
    cv2.imshow("Masked Minimap Center", masked_minimap)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    
    # 保存结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"masked_minimap_center_{timestamp}.png"
    success = cv2.imwrite(output_path, masked_minimap)
    if success:
        print(f"中心区域掩码小地图已保存至: {output_path}")
    else:
        print(f"中心区域掩码小地图保存失败: {output_path}")
    
    return masked_minimap

def test_mask_minimap_outside(image_path):
    """
    测试函数：传入完整图片，提取小地图，应用非圆心区域掩码（圆环区域），并保存结果
    
    Args:
        image_path (str): 完整图片路径
        center_radius (int): 圆心区域的半径，默认为40
        
    Returns:
        np.ndarray: 应用掩码后的小地图图像
    """
    # 读取完整图片
    img = cv2.imread(image_path)
    if img is None:
        print(f"无法读取图片: {image_path}")
        return None
    
    # 从小地图中提取指定半径的区域
    minimap = get_minimap(img, radius=MINIMAP_RADIUS)
    
    # 应用非圆心区域掩码（圆环区域）
    masked_minimap = mask_minimap_outside(minimap, center_radius=80)
    
    # 在掩码后的小地图中查找红色点 [47, 47, 232]
    red = [47, 47, 232]
    rd = np.where(
        np.sum((masked_minimap - red) ** 2, axis=-1) <= 512)
    print(rd[0].shape[0])

    cv2.imshow("Masked Minimap Outside (Ring)", masked_minimap)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    
    # 打印rd结果
    print('rd:', rd)
    
    # 保存结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"masked_minimap_outside_{timestamp}.png"
    success = cv2.imwrite(output_path, masked_minimap)
    if success:
        print(f"圆环区域掩码小地图已保存至: {output_path}")
    else:
        print(f"圆环区域掩码小地图保存失败: {output_path}")
    
    return masked_minimap

if __name__ == "__main__":
    pth="./20260322_002336.png"
    # test_mask_minimap_outside(pth)
    image = cv2.imread(pth)
    # # analyze_red(image)
    rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS,copy=True)
    # # direction_minimap = get_minimap(image.copy(), radius=DIRECTION_RADIUS)
    # # s_time = time.time()
    # # rotation=update_rotation(minimap=rotation_minimap)
    # # d_time = time.time()
    # # # direct=get_now_direct(minimap)
    # # direct=update_direction(image)
    # # e_time = time.time()
    # # print('更新视角耗时:', d_time - s_time, '更新方向耗时:', e_time - d_time)
    rotation, direct =update_minimap_data(image)
    show_minimap(rotation_minimap, rotation, direct)
    # pth1 = "./rotated_minimap_20251230_171434.png"
    # pth2 = "./20251021_203128.png"
    # pth2= "../temp/20251230_164150.png"
    # compare_minimap_textures(pth1, pth2)
    # img = cv2.imread(pth1)
    # test_rotation_with_minimap(img)
    # 测试获取视角角度
    # rotation = get_minimap_rotation(pth1)
    # test_mask_minimap_outside(pth2, center_radius=40)
    # subtract_rotated_texture(pth2, pth1)