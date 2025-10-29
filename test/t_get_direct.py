import cv2
import numpy as np
from scipy import signal
from utils.utils.minimap_util import MINIMAP_RADIUS, get_minimap, rgb2yuv, RotationRemapData, peak_confidence, convolve, \
    DIRECTION_RADIUS, DIRECTION_ARROW_COLOR, area_pad, color_similarity_2d, get_bbox, area_limit, image_size, \
    DIRECTION_ROTATION_SCALE, crop, DIRECTION_SEARCH_SCALE, subtract_blur, POSITION_SEARCH_SCALE, cubic_find_maximum, \
     ArrowRotateMap, ArrowRotateMapAll


import matplotlib
matplotlib.use('TkAgg')


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
    cv2.imshow("minimap", image)
    cv2.waitKey(0)
    cv2.GaussianBlur(image, (3, 3), 0, dst=image)
    # 将圆形展开为矩形
    remap = cv2.remap(image, *RotationRemapData(), cv2.INTER_LINEAR)[d * 1 // 10:d * 6 // 10].astype(np.float32)

    remap = cv2.resize(remap, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    # remap = cv2.warpPolar(image, (d,d), (d//2,d//2),d//2, cv2.WARP_POLAR_LINEAR).T[d * 1 // 10:d * 6 // 10]#.astype(np.float32)

    # 查找导数
    gradx = cv2.Scharr(remap, cv2.CV_32F, 1, 0)
    cv2.imshow("minimap", gradx)
    cv2.waitKey(0)
    import matplotlib.pyplot as plt
    plt.imshow(gradx)
    plt.show()

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

def update_direction(or_image=None,minimap=None):
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
        # IndexError: index 0 is out of bounds for axis 0 with size 0
        # log.warning('小地图上没有方向箭头')
        print('小地图上没有方向箭头')
        return None

    image = crop(image, area=area, copy=False)
    # cv2.imshow("minimap", image)
    # cv2.waitKey(0)
    scale = DIRECTION_ROTATION_SCALE * DIRECTION_SEARCH_SCALE
    mapping = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)

    result = cv2.matchTemplate(ArrowRotateMap, mapping, cv2.TM_CCOEFF_NORMED)
    result = subtract_blur(result, 5)
    _, sim, _, loca = cv2.minMaxLoc(result)
    
    # 在ArrowRotateMap上绘制匹配位置（使用白色框）
    arrow_map_copy = ArrowRotateMap.copy()
    # 将ArrowRotateMap转换为BGR格式以便绘制彩色框
    if len(arrow_map_copy.shape) == 2:  # 灰度图
        arrow_map_copy = cv2.cvtColor(arrow_map_copy, cv2.COLOR_GRAY2BGR)
    
    # 将匹配位置转换为ArrowRotateMap上的坐标
    match_x, match_y = loca
    cv2.rectangle(arrow_map_copy, 
                  (match_x, match_y), 
                  (match_x + mapping.shape[1], match_y + mapping.shape[0]),
                  (0, 0, 255), 2)  # 红色框

    loca = np.array(loca) / DIRECTION_SEARCH_SCALE // (DIRECTION_RADIUS * 2)
    # cv2.imshow("ArrowRotateMap with match", arrow_map_copy)
    # cv2.waitKey(0)
    degree = int((loca[0] + loca[1] * 8) * 5)
    def to_map(x):
        return int((x * DIRECTION_RADIUS * 2 + DIRECTION_RADIUS) * POSITION_SEARCH_SCALE)

    # ArrowRotateMapAll上的行
    row = int(degree // 8) + 45
    # 计算+-1行以获得精度为1的结果
    row = (row-2 , row + 3)
    # 转换为ArrowRotateMapAll并放大5px
    row = (to_map(row[0]) - 5, to_map(row[1]) + 5)
    precise_map = ArrowRotateMapAll[row[0]:row[1], :].copy()
    
    # 在精确匹配区域上绘制匹配结果
    # if len(precise_map.shape) == 2:  # 灰度图
    #     precise_display = cv2.cvtColor(precise_map, cv2.COLOR_GRAY2BGR)
    # else:
    #     precise_display = precise_map.copy()
        
    result = cv2.matchTemplate(precise_map, mapping, cv2.TM_CCOEFF_NORMED)
    result = subtract_blur(result, 5)
    
    # 在精确匹配区域上找到最佳匹配位置并绘制框
    _, _, _, precise_loc = cv2.minMaxLoc(result)
    # cv2.rectangle(precise_display,
    #               (precise_loc[0], precise_loc[1]),
    #               (precise_loc[0] + mapping.shape[1], precise_loc[1] + mapping.shape[0]),
    #               (0, 255, 0), 0)  # 绿色框
    
    # 将原始图像叠加到匹配区域
    # resized_image = cv2.resize(image, (mapping.shape[1], mapping.shape[0]))
    # if len(resized_image.shape) == 2:  # 灰度图转BGR
    #     resized_image = cv2.cvtColor(resized_image, cv2.COLOR_GRAY2BGR)
    
    # 在匹配位置叠加原始图像
    # x, y = precise_loc
    # h, w = resized_image.shape[:2]
    # if y + h <= precise_display.shape[0] and x + w <= precise_display.shape[1]:
    #     precise_display[y:y+h, x:x+w] = cv2.addWeighted(
    #         precise_display[y:y+h, x:x+w], -0.5, resized_image, 0.5, 0)
    
    # cv2.imshow("Precise matching area with match", precise_display)
    # cv2.waitKey(0)

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
        rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS)
    if direction_minimap is None:
        direction_minimap = get_minimap(image, radius=DIRECTION_RADIUS)
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
if __name__ == "__main__":
    pth="../temp/20251029_205039.png"
    image = cv2.imread(pth)
    analyze_red(image)
    # rotation_minimap = get_minimap(image, radius=MINIMAP_RADIUS)
    # # direction_minimap = get_minimap(image.copy(), radius=DIRECTION_RADIUS)
    # # s_time = time.time()
    # # rotation=update_rotation(minimap=rotation_minimap)
    # # d_time = time.time()
    # # # direct=get_now_direct(minimap)
    # # direct=update_direction(image)
    # # e_time = time.time()
    # # print('更新视角耗时:', d_time - s_time, '更新方向耗时:', e_time - d_time)
    # rotation, direct =update_minimap_data(image)
    # show_minimap(rotation_minimap, rotation, direct)