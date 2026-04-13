import cv2
from utils.utils.image_tool import find_image_in_folder
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
 image = cv2.Canny(image, 100, 200)
 return image
if __name__ == "__main__":
   # 读取测试图像
    test_image = cv2.imread('20260327_223949.png')
   # 预处理
    processed_image = map_image_preprocess(test_image)
   # 保存结果
    cv2.imwrite('test_processed6.png', processed_image)
    print(f"原始图像：{test_image.shape} -> 处理后：{processed_image.shape}")
    print("已保存到 test_processed.png")
