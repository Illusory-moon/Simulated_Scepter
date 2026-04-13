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
from utils.utils.image_tool import find_image_in_folder


def extract_number(s):
    """从字符串中提取 + 开头、% 结尾的中间数字"""
    match = re.search(r'\+(\d+)%', s)
    return match.group(1) if match else None


def match_numbers_in_region(or_image, threshold=0.9):
    """
    在指定区域匹配数字模板
    
    Args:
        or_image: 输入图像数组
        threshold: 匹配阈值
    Returns:
        str: 匹配结果列表，已按从左到右排序
    """
    or_image = or_image[691:1003, 80:195].copy()
    full_folder_path = os.path.join(PATHS["image"], "nums")
    templates = []
    if os.path.exists(full_folder_path):
        for file in os.listdir(full_folder_path):
            if file.lower().endswith('.png'):
                template_name = os.path.splitext(file)[0]
                templates.append(template_name)
        templates.sort()
    all_matches = []
    for template_name in templates:
        template = find_image_in_folder("nums", template_name)
        th, tw = template.shape[:2]
        res = cv2.matchTemplate(or_image, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        for x, y in zip(xs, ys):
            all_matches.append({'name': template_name, 'location': (x + 80, y + 691), 'similarity': round(float(res[y, x]), 3), 'size': (tw, th)})
    
    # NMS 去重
    boxes = [[m['location'][0] - 80, m['location'][1] - 691, m['size'][0], m['size'][1]] for m in all_matches]
    scores = [m['similarity'] for m in all_matches]
    indices = cv2.dnn.NMSBoxes(boxes, scores, 0.0, 0.3)
    all_matches = [all_matches[i] for i in indices]

    sorted_matches = sorted(all_matches, key=lambda x: x['location'][0] + x['size'][0] / 2)
    number_str = ''.join([m['name'] for m in sorted_matches])
    return number_str


if __name__ == "__main__":
    load_img()
    image = cv2.imread("20260316_231349.png")
    results = match_numbers_in_region(image)
    # 组合识别出的数字
    print(f"\n识别到的数字序列：{extract_number(results)}")