# -*- coding: utf-8 -*-
"""
OCR 数字识别模块
功能：裁剪图像区域，进行多目标模板匹配，NMS 去重并按从左到右排序
"""
import cv2
import numpy as np
import os
import re
from importing import load_img
from route import PATHS
from tool.utils.image_tool import find_image_in_folder


def extract_number(s):
    """从字符串中提取 + 开头、% 结尾的中间数字"""
    match = re.search(r'\+(\d+)%', s)
    return match.group(1) if match else None


def match_skill_numbers_in_region(or_image, threshold=0.9):
    """
    在指定区域匹配数字模板

    Args:
        or_image: 输入图像数组
        threshold: 匹配阈值
    Returns:
        str: 匹配结果列表，已按从左到右排序
    """
    or_image = or_image[823:870, 1675:1713].copy()
    gray = cv2.cvtColor(or_image, cv2.COLOR_BGR2GRAY)
    mask = cv2.inRange(gray, 200, 255)
    white_region = cv2.bitwise_and(gray, gray, mask=mask)
    best_match = None
    best_score = -1
    
    for template_name in ["0","1","2","3","4","5","6","7","8"]:
        template = find_image_in_folder("gray_image/num", template_name)
        res = cv2.matchTemplate(white_region, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = max_val
            best_match = int(template_name)
    
    return best_match if best_score >= threshold else None


if __name__ == "__main__":
    load_img()
    image = cv2.imread("20260403_221449.png")
    results = match_skill_numbers_in_region(image)
    # 组合识别出的数字
    print(f"\n识别到的数字序列：{results}")