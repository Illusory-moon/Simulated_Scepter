import cv2
import numpy as np

# 模拟必要的常量
MINIMAP_CENTER = (138, 149)
MINIMAP_RADIUS = 93

def detect_minimap_center_by_circle_template(image):
    """
    通过白色圆形边缘模板匹配检测小地图中心
    """
    # 一开始就创建灰度图模板
    template = np.zeros((100, 100), dtype=np.uint8)
    cv2.circle(template, (50, 50), 45, 255, 3)
    
    # 图像也转换为灰度图
    if len(image.shape) == 3:
        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray_image = image
    
    # 模板匹配
    result = cv2.matchTemplate(gray_image, template, cv2.TM_CCOEFF_NORMED)
    _, _, _, max_loc = cv2.minMaxLoc(result)
    
    # 计算实际中心坐标
    center_x = max_loc[0] + 50
    center_y = max_loc[1] + 50
    
    return (center_x, center_y)

# 测试
if __name__ == "__main__":
    # 创建测试图像
    test_img = np.zeros((300, 300, 3), dtype=np.uint8)
    cv2.circle(test_img, (150, 150), 45, (255, 255, 255), 3)
    
    # 测试函数
    center = detect_minimap_center_by_circle_template(test_img)
    print(f"检测到的中心: {center}")