import json
import os
from datetime import datetime
from pathlib import Path
import pyautogui
import cv2 as cv
import numpy as np
import time

import win32api
import win32print
import win32con
from copy import deepcopy
import math
import random
import win32gui, win32com.client, pythoncom
import sys
import ctypes
from PIL import Image, ImageDraw, ImageFont
from math import sin, cos
import traceback

from config.GLOBAL import key_mouse_manager
from diver import merge_text
from utils.simul.config import config
from utils.log import log
import utils.simul.ocr as ocr
from utils.screenshot import Screen
import threading

from utils.simul.text_key import text_keys
from utils.utils.Error import BigAngError
from utils.utils.get_win_rect import get_window_rect
from utils.utils.minimap_util import get_minimap, MINIMAP_RADIUS
from utils.utils.mminimap import update_minimap_data


def set_forground():
    config.read()
    try:
        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("WScript.Shell")
        if getattr(sys, 'frozen', False):
            shell.SendKeys(" ")  # Undocks my focus from Python IDLE
        else:
            shell.SendKeys("")
        game_nd = win32gui.FindWindow("UnityWndClass", "崩坏：星穹铁道")
        if game_nd == 0:
            game_nd = win32gui.FindWindow(None, "云·星穹铁道")
        win32gui.SetForegroundWindow(game_nd)
    except:
        pass


def sprint():
    if config.long_press_sprint:
        key_mouse_manager.keyDown('shift')
    else:
        key_mouse_manager.press('shift')


def get_dis(x, y):
    """
    返回两点间的直线距离
    """
    return ((x[0] - y[0]) ** 2 + (x[1] - y[1]) ** 2) ** 0.5


def extract_features(img):
    img = img[50:-50,50:-50,:]
    orb = cv.ORB_create()
    # 检测关键点和计算描述符
    keypoints, descriptors = orb.detectAndCompute(img, None)
    return descriptors


class UniverseUtils:
    def __init__(self,speed=False,gui=None):
        #是否速通
        self.speed = speed
        #当前计算坐标
        self.now_loc = [0,0]
        self.mini_state = 0
        self.ang_off = 0
        self.target = set()
        self.fps_list = []
        set_forground()
        self.check_bonus = 1
        self._stop = False
        self.stop_move = 0
        self.move = 0
        self.multi = config.multi
        self.diffi = config.diffi
        self.fate = config.fate
        self.my_fate = -1
        self.fail_count = 0
        self.first_mini = 1
        self.ts = ocr.My_TS(father=self)
        self.last_info = ''
        self.mini_target = 0
        self.f_time = 0
        self.slow = 0
        self.init_ang = 0
        self.allow_e = 1
        self.quan = 0
        self.img_map = dict()
        self.gui=gui
        self.should_update_map=True
        self.big_map = np.zeros((8192, 8192), dtype=np.uint8)
        #地图集合
        self.img_set = []
        #是否拥有黄泉
        self.quan = 0
        #上次交互时间
        self.quit = 0
        #调试显示用地图
        self.debug_map = np.zeros((8192, 8192), dtype=np.uint8)
        # 用于存储tmp地图
        self.tmp_map = None
        #当前层数
        self.floor = -1
        # 玩家真实坐标
        self.real_loc = [0, 0]
        #最佳匹配地图编号
        self.now_map = None
        # 最佳匹配地图相似度
        self.now_map_sim = None
        #上次截屏时间
        self.last_get_screen_time = None
        #上次路径状态日志时间
        self.last_path_state_time = None
        #默认匹配阈值
        self.threshold = 0.97
        # 用户选择的命途
        for i in range(len(config.fates)):
            if config.fates[i] == self.fate:
                self.my_fate = i
        if self.my_fate == -1:
            log.info("info有误，自动选择巡猎命途    错误：" + self.fate)
            self.my_fate = 4
        self.tk = text_keys(self.my_fate)
        self.debug, self.find = 0, 0
        self.bx, self.by = 1920, 1080
        log.warning("等待游戏窗口")
        while True:
            try:
                hwnd = win32gui.GetForegroundWindow()  # 根据当前活动窗口获取句柄
                Text = win32gui.GetWindowText(hwnd)
                self.x0, self.y0, self.x1, self.y1 = win32gui.GetClientRect(hwnd)
                self.xx = self.x1 - self.x0
                self.yy = self.y1 - self.y0
                # self.x0, self.y0, self.x1, self.y1 = win32gui.GetWindowRect(hwnd)
                self.x0, self.y0, self.x1, self.y1 = get_window_rect(hwnd)
                self.full = self.x0 == 0 and self.y0 == 0
                self.x0 = max(0, self.x1 - self.xx) #+ 9 * self.full
                self.y0 = max(0, self.y1 - self.yy) #+ 9 * self.full
                if (
                    (self.xx == 1920 or self.yy == 1080)
                    and self.xx >= 1920
                    and self.yy >= 1080
                ):
                    self.x0 += (self.xx - 1920) // 2
                    self.y0 += (self.yy - 1080) // 2
                    self.x1 -= (self.xx - 1920) // 2
                    self.y1 -= (self.yy - 1080) // 2
                    self.xx, self.yy = 1920, 1080
                self.scx = self.xx / self.bx
                self.scy = self.yy / self.by
                dc = win32gui.GetWindowDC(hwnd)
                dpi_x = win32print.GetDeviceCaps(dc, win32con.LOGPIXELSX)
                dpi_y = win32print.GetDeviceCaps(dc, win32con.LOGPIXELSY)
                win32gui.ReleaseDC(hwnd, dc)
                scale_x = dpi_x / 96
                scale_y = dpi_y / 96
                try:
                    self.scale = ctypes.windll.user32.GetDpiForWindow(hwnd) / 96.0
                except:
                    log.info('DPI获取失败')
                    self.scale = 1.0
                log.info(
                    "DPI: " + str(self.scale) + " A:" + str(int(self.multi * 100) / 100)
                )
                log.info("TEXT: " + str(Text))
                # 计算出真实分辨率
                self.real_width = int(self.xx * scale_x)
                # x01y01:窗口左上右下坐标
                # xx yy:窗口大小
                # scx scy:当前窗口和基准窗口（1920*1080）缩放大小比例
                if Text == "崩坏：星穹铁道" or Text == "云·星穹铁道":
                    time.sleep(1)
                    if self.xx != 1920 or self.yy != 1080:
                        log.error("分辨率错误")
                    break
                else:
                    time.sleep(0.3)
            except Exception:
                traceback.print_exc()
                time.sleep(0.3)
                pass
        self.order = config.order
        self.sct = Screen()

    def gen_hotkey_img(self,hotkey="e",bg="resource/imgs/f_bg.jpg"):
        hotkey = hotkey.upper()
        image = Image.open(bg)
        font = ImageFont.truetype("resource/imgs/base.ttf", 24)
        d = ImageDraw.Draw(image)
        position = (2,-3)
        color = (152, 214, 241)
        d.text(position, hotkey, font=font, fill=color)
        return np.array(image)


    # example: self.wait_fig(lambda:self.check("strange", 0.9417, 0.9481), 1.4)
    def wait_flag(self, f, timeout=3.0):
        tm=time.time()
        while time.time()-tm<timeout:
            if not f():
                return 1
            time.sleep(0.1)
            self.get_screen()
        return 0

    def use_it(self, x, y):
        if x != 1 or y != 1:
            key_mouse_manager.click(0.903 - 0.06 * (x - 1), 0.827 - 0.14 * (y - 1))
            time.sleep(0.5)
        # 点击使用
        key_mouse_manager.click(0.154,0.088)
        self.wait_flag(lambda:not self.click_text(text="确认",box=[1126, 1252, 716, 812],click=False,ocr_line=False,warning=False), 1.2)
        # 点击确认
        key_mouse_manager.click(0.386,0.294)
        r = self.wait_flag(lambda:not self.click_text(text="替换同类",box=[816, 1006, 284, 380],click=False,warning=False), 0.8)
        if r:
            # 覆盖效果
            key_mouse_manager.click(0.386,0.294)

    def use_consumable(self, x=1, y=1):
        """
        使用x排，y列的消耗品
        """
        key_mouse_manager.press("b")
        if self.wait_flag(lambda:not self.check("use_package", 0.5182, 0.9407), 3):
            time.sleep(0.4)
            key_mouse_manager.click(0.3677,0.0861)
            time.sleep(0.4)
            self.get_screen()
            if self.wait_flag(lambda:not self.check("use_star", 0.8828, 0.8648, threshold=0.9), 0.8):
                self.use_it(x, y)
                if self.wait_flag(lambda:not self.check("use_def", 0.3198, 0.0880), 2.2):
                    time.sleep(0.4)
                    key_mouse_manager.click(0.3198,0.0880)
                    time.sleep(0.4)
                    self.get_screen()
                    if self.wait_flag(lambda:not self.check("use_star", 0.8828, 0.8648, threshold=0.9), 0.6):
                        self.use_it(x, y)
                        self.wait_flag(lambda:not self.check("use_package", 0.5182, 0.9407), 2)
                        time.sleep(0.3)
                    key_mouse_manager.press("esc")
            else:
                key_mouse_manager.press("esc")
        if not self.is_run():
            for _ in range(3):
                key_mouse_manager.press("esc")
                if self.wait_flag(lambda:not self.is_run(), 3):
                    return

    def get_point(self, x, y):
        # 得到一个点的浮点表示
        x = self.x1 - x
        y = self.y1 - y
        print("获取到点：{:.4f},{:.4f}".format(x / self.xx, y / self.yy))

    def calc_point(self, point, offset):
        return point[0] - offset[0] / self.xx, point[1] - offset[1] / self.yy

    def click_text(self, text,delay=0,box=None,after_delay=0,click=True,find_all=False,warning=True,ocr_line=True,need_fresh=True,allow_fail=False):
        if delay:
            time.sleep(delay)
        if not ocr_line:
            ocr_text = self.ts.find_with_box(box)
            if len(ocr_text) and text in merge_text(ocr_text):
                return True
            else:
                if warning:
                    log.warning(f"{text}文本未找到(非单行)当前返回结果{ocr_text}")
        if need_fresh:
            img = self.get_screen()
        else:
            img = self.screen
        if box:
            match=self.ts.ocr_one_row(img,box)
            log.info(f"尝试匹配：{text}匹配结果：{match}")
            # 检查匹配结果是否包含目标文本
            if len(match) and text in match:
                if click:
                    key_mouse_manager.click(
                        (box[0]+box[1])//2,
                        (box[2]+box[3])//2
                    )
                if after_delay:
                    time.sleep(after_delay)
                return True
            elif allow_fail:
                return False
        pt = self.ts.find_text(img, text,find_all)
        if pt is not None:
            if click:
                key_mouse_manager.click(
                        1 - (pt[0][0] + pt[1][0]) / 2 / self.xx,
                        1 - (pt[0][1] + pt[2][1]) / 2 / self.yy
                )
            if after_delay:
                time.sleep(after_delay)
            return True
        if warning:
            log.warning(f"{text}文本未找到")
        return False

    # 由click_target调用，返回图片匹配结果
    def scan_screenshot(self, prepared):
        temp = pyautogui.screenshot()
        screenshot = np.array(temp)
        screenshot = cv.cvtColor(screenshot, cv.COLOR_BGR2RGB)
        result = cv.matchTemplate(screenshot, prepared, cv.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        return {
            "screenshot": screenshot,
            "min_val": min_val,
            "max_val": max_val,
            "min_loc": min_loc,
            "max_loc": max_loc,
        }

    # 计算匹配中心点坐标
    def calculated(self, result, shape):
        mat_top, mat_left = result["max_loc"]
        prepared_height, prepared_width, prepared_channels = shape
        x = int((mat_top + mat_top + prepared_width) / 2)
        y = int((mat_left + mat_left + prepared_height) / 2)
        return x, y





    # 点击与模板匹配的点，flag=True表示必须匹配，不匹配就会一直寻找直到出现匹配
    def click_target(self, target_path, threshold, flag=True, sub=True, click=False):
        target = cv.imread(target_path)
        while True:
            result = self.scan_screenshot(target)
            if result["max_val"] > threshold:
                log.info(f"匹配度{result['max_val']}")
                points = self.calculated(result, target.shape)
                self.get_point(*points)
                log.info(f"target shape: {target.shape}")
                if click:
                    key_mouse_manager.click(points)
                return
            if not flag:
                return
            elif sub:  # 降低阈值直到匹配到为止
                threshold -= 0.01

    # 在截图中裁剪需要匹配的部分
    def get_local(self, x, y, size, large=True):
        sx, sy = size[0] + 60 * large, size[1] + 60 * large
        bx, by = self.xx - int(x * self.xx), self.yy - int(y * self.yy)
        return self.screen[
            max(0, by - sx // 2) : min(self.yy, by + sx // 2),
            max(0, bx - sy // 2) : min(self.xx, bx + sy // 2),
            :,
        ]

    def format_path(self, path):
        return f"./resource/imgs/{path}.jpg"

    def get_small_interaction_img(self,x, y, mask=None,fresh=False):
        """
        截取指定点位特定模板大小的图片
        x,y：匹配中心点，
        mask：以mask大小为基准裁剪截图
        """
        if fresh:
            self.get_screen()
        path = self.format_path('z')
        target = cv.imread(path)
        target = cv.resize(
            target,
            dsize=(int(self.scx * target.shape[1]), int(self.scx * target.shape[0])),
        )
        if mask is None:
            shape = target.shape
        else:
            mask_img = cv.imread(self.format_path(mask))
            shape = (
                int(self.scx * mask_img.shape[0]),
                int(self.scx * mask_img.shape[1]),
            )
        local_screen = self.get_local(x, y, shape, False)
        return local_screen
    def check(self, path, x, y, mask=None, threshold=None, use_binary=False,fresh=False):
        """
        判断截图中匹配中心点附近是否存在匹配模板
        path：匹配模板的路径，
        x,y：匹配中心点，
        mask：如果存在，则以mask大小为基准裁剪截图，
        threshold：匹配阈值
        """
        if fresh:
            self.get_screen()
        if threshold is None:
            threshold = self.threshold
        path = self.format_path(path)
        target = cv.imread(path)
        if path == './resource/imgs/f.jpg' and config.mapping[0]!='f':
            target = self.gen_hotkey_img(config.mapping[0])
            threshold -= 0.01
        target = cv.resize(
            target,
            dsize=(int(self.scx * target.shape[1]), int(self.scx * target.shape[0])),
        )
        if mask is None:
            shape = target.shape
        else:
            mask_img = cv.imread(self.format_path(mask))
            shape = (
                int(self.scx * mask_img.shape[0]),
                int(self.scx * mask_img.shape[1]),
            )
        local_screen = self.get_local(x, y, shape)
        if use_binary:
            # 将截图和模板图像转换为灰度图
            if len(local_screen.shape) == 3:
                gray_screen = cv.cvtColor(local_screen, cv.COLOR_BGR2GRAY)
            else:
                gray_screen = local_screen
                
            if len(target.shape) == 3:
                gray_target = cv.cvtColor(target, cv.COLOR_BGR2GRAY)
            else:
                gray_target = target
            
            # 对截图和模板进行二值化处理
            _, binary_screen = cv.threshold(gray_screen, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
            _, binary_target = cv.threshold(gray_target, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
            
            # 使用二值化图像进行匹配
            result = cv.matchTemplate(binary_screen, binary_target, cv.TM_CCORR_NORMED)
        else:
            result = cv.matchTemplate(local_screen, target, cv.TM_CCORR_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        self.tx = x - (max_loc[0] - 0.5 * local_screen.shape[1] + 0.5 * target.shape[1]) / self.xx
        self.ty = y - (max_loc[1] - 0.5 * local_screen.shape[0] + 0.5 * target.shape[0]) / self.yy
        if path == "./resource/imgs/run.jpg" and 0:
            print(max_val)
            cv.imwrite('target.jpg',target)
            cv.imwrite('local.jpg',local_screen)
            #print(self.tx,self.ty)
            #print(x,y,max_loc,local_screen.shape)
            #self.click((self.tx,self.ty),click=0)
            #exit()
        self.tm = max_val
        if max_val > threshold:
            if self.last_info != path:
                log.info("匹配到图片 %s 相似度 %f 阈值 %f" % (path, max_val, threshold))
            self.last_info = path
        return max_val > threshold

    def get_end_point(self, mask=0):
        self.get_screen()
        local_screen = self.get_local(0.4979, 0.6296, (715, 1399))
        black = np.array([0, 0, 0])
        white = np.array([255, 255, 255])
        bw_map = np.zeros(local_screen.shape[:2], dtype=np.uint8)
        b_map = deepcopy(bw_map)
        b_map[np.sum((local_screen - black) ** 2, axis=-1) <= 1600] = 255
        w_map = deepcopy(bw_map)
        w_map[np.sum((local_screen - white) ** 2, axis=-1) <= 1600] = 255
        kernel = np.zeros((7, 7), np.uint8)  # 设置kenenel大小
        kernel += 1
        b_map = cv.dilate(b_map, kernel, iterations=1)  # 膨胀还原图形
        bw_map[(b_map > 200) & (w_map > 200)] = 255
        cen = 660
        if mask:
            try:
                bw_map[:, : cen - 350 // mask] = 0
                bw_map[:, cen + 350 // mask :] = 0
            except:
                pass
        region = cv.imread("resource/imgs/region.jpg", cv.IMREAD_GRAYSCALE)
        result = cv.matchTemplate(bw_map, region, cv.TM_CCORR_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        if max_val < 0.6:
            return None
        else:
            dx = max_loc[0] - cen
            if dx > 0:
                return dx**0.7
            else:
                return -((-dx) ** 0.7)

    def move_to_end(self, i=0):
        dx = self.get_end_point(i)
        if dx is None:
            if i:
                return 0
            win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, 0, -200)
            time.sleep(0.3)
            dx = self.get_end_point()
            off = 0
            if dx is None:
                log.debug(f'旋转查找终点')
                for k in [60,120,60,60,30,30,-60,-60,-60,-60,-60,-60]:
                    if self.ang_neg:
                        key_mouse_manager.mouse_move(k)
                        off -= k
                    else:
                        key_mouse_manager.mouse_move(-k)
                        off += k
                    time.sleep(0.3)
                    dx = self.get_end_point()
                    if dx is not None:
                        break
                if dx is None:
                    key_mouse_manager.mouse_move(off*1.03)
                    time.sleep(0.3)
                    return 0
        log.debug(f"移动面向终点 参数{i}移动距离{dx}" )
        if i == 0:
            key_mouse_manager.mouse_move(dx / 3)
            time.sleep(0.3)
        else:
            key_mouse_manager.mouse_move(dx / 5)
            time.sleep(0.3)
        if i == 0 and abs(dx / 3) > 30:
            time.sleep(0.3)
            dx = self.get_end_point(1)
            if dx is not None:
                key_mouse_manager.mouse_move(dx / 4)
                time.sleep(0.3)
        return 1



    def exist_minimap(self):
        """
        初步裁剪小地图，并增强小地图中的蓝色箭头
        """
        self.get_screen()
        shape = (int(self.scx * 190), int(self.scx * 190))
        local_screen = self.get_local(0.9333, 0.8657, shape)
        blue = np.array([234, 191, 4])
        local_screen[np.sum(np.abs(local_screen - blue), axis=-1) <= 50] = blue
        self.loc_scr = local_screen

    # 从全屏截屏中裁剪得到游戏窗口截屏
    def get_screen(self):
        current_time = time.time()
        if hasattr(self, 'last_get_screen_time') and self.last_get_screen_time is not None:
            interval = current_time - self.last_get_screen_time
            self.fps_list.append(interval)
            if len(self.fps_list) > 30:
                self.fps_list.pop(0)
            if hasattr(self, 'gui') and self.gui is not None and hasattr(self.gui, 'set_FPS'):
                avg_interval = sum(self.fps_list) / len(self.fps_list)
                try:
                    self.gui.set_FPS(avg_interval)
                    # log.info(f"平均FPS: {1 / avg_interval:.2f}")
                except:
                    pass
        self.last_get_screen_time = current_time
        self.screen = self.sct.grab(self.x0, self.y0)
        return self.screen

    def set_path_state(self, text):
        current_time = time.time()
        if self.last_path_state_time is not None:
            elapsed_time = current_time - self.last_path_state_time
            log.debug(f"{text} (距离上次日志: {elapsed_time:.2f}秒)")
        else:
            log.debug(text)
        self.last_path_state_time = current_time
        
        if hasattr(self, 'gui') and self.gui is not None and hasattr(self.gui, 'set_find_path_state'):
            try:
                self.gui.set_find_path_state(text)
            except:
                pass

    def get_bw_map(self, re_screen=1, local_screen=None):
        """
            进一步得到小地图的黑白格式
            re_screen：是否重新截图
        """
        self.mag = "self._stop = os.system('pi"
        yellow = np.array([145, 192, 220])
        black = np.array([0, 0, 0])
        white = np.array([210, 210, 210])
        gray = np.array([55, 55, 55])
        shape = (int(self.scx * 190), int(self.scx * 190))
        if re_screen and self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False):
            return None
        if local_screen is None:
            local_screen = self.get_local(0.9333, 0.8657, shape)
        bw_map = np.zeros(local_screen.shape[:2], dtype=np.uint8)
        # 灰块、白线：小地图中的可移动区域、可移动区域的边缘
        # b_map：当前像素点是否是灰块。只允许灰块附近（2像素）的像素被识别为白线
        b_map = deepcopy(bw_map)
        b_map[
            np.sum((local_screen - gray) ** 2, axis=-1) <= 3200 + self.find * 1600
        ] = 255
        blk_map = deepcopy(bw_map)
        blk_map[
            np.sum((local_screen - black) ** 2, axis=-1) <= 800 + self.find * 800
        ] = 255
        kernel = np.zeros((9, 9), np.uint8)  # 设置kenenel大小
        kernel += 1
        dilate = cv.dilate(blk_map, kernel, iterations=1)  # 膨胀还原图形
        kernel = np.zeros((5, 5), np.uint8)  # 设置kenenel大小
        kernel += 1
        b_map = cv.dilate(b_map, kernel, iterations=1)
        bw_map[
            (np.sum((local_screen - white) ** 2, axis=-1) <= 3200 + self.find * 1600)
            & (b_map > 200)
        ] = 255
        # 再次精确裁剪，这里区别模式只是防止bug，find=1时的裁剪是最精确的（中心点即为人物坐标）
        if self.find == 0:
            bw_map = bw_map[
                int(shape[0] * 0.5) - 68 : int(shape[0] * 0.5) + 108,
                int(shape[1] * 0.5) - 48 : int(shape[1] * 0.5) + 128,
            ]
        else:
            bw_map = bw_map[
                int(shape[0] * 0.5) - 68 - 2 : int(shape[0] * 0.5) + 108 - 2,
                int(shape[1] * 0.5) - 48 - 8 : int(shape[1] * 0.5) + 128 - 8,
            ]
        # 排除半径85以外的像素点
        for i in range(bw_map.shape[0]):
            for j in range(bw_map.shape[1]):
                if ((i - 88) ** 2 + (j - 88) ** 2) > 85**2:
                    bw_map[i, j] = 0
        if self.find == 0:
            cv.imwrite(self.map_file + "bwmap.jpg", bw_map)
        return bw_map


    def get_now_direct(self, loc_scr):
        """
            计算小地图中蓝色箭头的角度，以正上为0度，逆时针增加
        """
        hsv = cv.cvtColor(loc_scr, cv.COLOR_BGR2HSV)  # 转HSV
        lower = np.array([93, 120, 60])  # 90 改成120只剩箭头，但是角色移动过的印记会消失
        upper = np.array([97, 255, 255])
        mask = cv.inRange(hsv, lower, upper)  # 创建掩膜
        loc_tp = cv.bitwise_and(loc_scr, loc_scr, mask=mask)
        # loc_tp[np.sum(np.abs(loc_tp - blue), axis=-1) > 0] = [0, 0, 0]
        # 裁剪loc_tp至中心24x24区域
        h, w = loc_tp.shape[:2]
        center_h, center_w = h // 2, w // 2
        crop_size = 12  # 24x24区域的一半是12
        loc_tp = loc_tp[center_h - crop_size-5:center_h + crop_size-5,
                        center_w - crop_size:center_w + crop_size]
        arrows_img = self.format_path("combined_arrows")
        arrows_img = cv.imread(arrows_img)
        # 在拼接的大图上进行一次匹配
        result = cv.matchTemplate(arrows_img, loc_tp, cv.TM_SQDIFF)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        # 根据匹配位置计算对应的角度
        best_row = (min_loc[1]+12) // 26  # 行号
        best_col = (min_loc[0]+12) // 26  # 列号
        ang = best_row * 12 + best_col  # 对应的角度
        # 在combined_img上框出匹配到的结果
        # combined_img_with_rect = arrows_img.copy()
        # log.info(f"角度：{ang}行：{best_row}列：{best_col}")
        # cv.rectangle(combined_img_with_rect, min_loc,
        #             (min_loc[0] + loc_tp.shape[1], min_loc[1] + loc_tp.shape[0]),
        #             (0, 0, 255), 1)
        # cv.imshow("匹配结果", loc_tp)
        # cv.imshow("匹配目标", combined_img_with_rect)
        # cv.waitKey(0)
        
        return ang

    def get_level(self):
        tm = time.time()
        #等待检测到正在跑图标志或者超时
        while not self.is_run() and time.time() - tm < 8:
            time.sleep(0.1)
            self.get_screen()
        if time.time() - tm >= 8:
            return -1
        time.sleep(max(0, (self.fail_count - 1) * 10)+1)
        #检测当前层数
        key_mouse_manager.press("m", 0.2)
        time.sleep(2.5)
        tm = time.time()
        self.floor_init = 0
        old_floor= self.floor
        while time.time()-tm<5 and not self.floor_init:
            self.get_screen()
            for i in range(12, -1, -1):
                if self.check("floor/ff" + str(i + 1), 0.0589, 0.8796):
                    self.floor = i
                    log.info(f"当前层数：{i+1}")
                    self.floor_init = 1
                    break
        if self.floor!=old_floor and old_floor!=0:
            log.error(f"层数已更新为：{self.floor+1}")
            # raise FloorError(f"层数不一致旧{old_floor+1}, 新{self.floor+1}")
        key_mouse_manager.press("m", 0.2)
        time.sleep(1)
        return 0

    def good_f(self):
        """
        不是"沉浸", "紧锁", "复活", "下载"的交互
        """
        log.debug("尝试判断当前交互是否最佳")
        t_start=time.time()
        if not self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True):
            return False,0
        img = self.get_small_interaction_img(x=0.3344,y=0.4241,mask="mask_f")
        text = self.ts.similar_list(self.tk.interacts, img)
        if text is None:
            # 使用新坐标重新尝试
            img = self.get_small_interaction_img(x=0.3181,y=0.4324,mask="mask_f")
            text = self.ts.similar_list(self.tk.interacts, img)
        is_killed = text in ["沉浸", "紧锁", "复活", "下载"]
        if text is not None:
            log.info('识别到交互信息：'+text)
        log.debug(f"交互最佳结果判断{text is not None and not is_killed}")
        t_end=time.time()
        return text is not None and not is_killed, t_end-t_start

    def get_recent_target(self):
        """
        寻找最近的目标点位与类型
        """
        has_removed = False
        mn_dis = 100000
        recent_loc = 0
        recent_type = -1
        # log.info(f"当前状态{self.target}")
        for target_loc, target_type in self.target:
            # log.info(f"遍历当前状态{self.target}")
            dis=get_dis(target_loc, self.real_loc)
            if dis < mn_dis:
                mn_dis = dis
                recent_loc = target_loc
                recent_type = target_type
                has_removed = False
        # 如果找不到，将最后一个完成的目标点作为目标点
        if recent_loc == 0:
            recent_loc = self.last
            recent_type = 3
        if recent_type==1 and mn_dis<40:
            red = [47, 47, 232]
            rd = np.where(np.sum((get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True,rotation=True) - red) ** 2, axis=-1) <= 4500)
            if not has_removed:
                self.target.remove((recent_loc, 1))
                log.info(f"移除目标{recent_loc},当前状态{self.target},距离{mn_dis}")
                has_removed = True
            if rd[0].shape[0] > 0:
                recent_loc = (self.real_loc[0]+rd[0][0]-93, self.real_loc[1]+rd[1][0]-93)
                self.target.add((recent_loc, 1))
                log.info(f"找到新的敌对目标点：{recent_loc}")
            else:
                self.target.add((recent_loc, 0))
                log.info(f"未找到敌对目标点，使用当前作为路径点位：{recent_loc}")
                recent_type=0
        return recent_loc, recent_type

    def move_to_interact(self, ii=0):
        self.get_screen()
        log.info("正在寻找交互点")
        threshold = 0.88
        # shape = (int(self.scx * 190), int(self.scx * 190))
        # curloc = (118 + 2, 125 + 2)
        # blue = np.array([234, 191, 4])
        local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True,rotation=True)
        target = ((-1, -1), 0)
        mini_icon = cv.imread(self.format_path("mini" + str(ii + 1)))
        sp = mini_icon.shape
        #小地图查找交互点并获取其位置
        result = cv.matchTemplate(local_screen, mini_icon, cv.TM_CCORR_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
        if max_val > threshold:
            nearest = (max_loc[1] + sp[0] // 2, max_loc[0] + sp[1] // 2)
            target = (nearest, 1)
            log.info(f"交互点相似度{max_val}，位置{max_loc[1]},{max_loc[0]},图像序号{ii}")
            
            if self.floor >= 12:
                self.floor = 11
        else:  # 226 64 66
            #再试试另外一张图，即黑塔图
            mini_icon = cv.imread(self.format_path("mini" + str(ii + 2)))
            sp = mini_icon.shape
            result = cv.matchTemplate(local_screen, mini_icon, cv.TM_CCORR_NORMED)
            min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
            if max_val > threshold-0.035*(self.floor in [4,8,11]):
                nearest = (max_loc[1] + sp[0] // 2, max_loc[0] + sp[1] // 2)
                target = (nearest, 2)
                log.info(f"黑塔相似度{max_val}，位置{max_loc[1]},{max_loc[0]}")

                
                if self.floor >= 12:
                    self.floor = 11
        #在图像上绘制一个以(120, 128)为中心、半径为82的圆形遮罩，圆形区域外的所有像素都被涂黑
        for i in range(local_screen.shape[0]):
            for j in range(local_screen.shape[1]):
                if get_dis((120, 128), (i, j)) >= 82:
                    local_screen[i, j] = [0, 0, 0]
        #两个交互都没有找红色点位（应该是敌人）
        if max_val <= threshold:
            red = [47, 47, 232]
            rd = np.where(np.sum((local_screen - red) ** 2, axis=-1) <= 4500)
            if rd[0].shape[0] > 0:
                nearest = (rd[0][0], rd[1][0])
                target = (nearest, 3)
                if self.floor == 11:
                    self.floor = 12
        if self.mini_target == 0:
            self.mini_target = target[1]
        if target[1] >= 1:
            log.info(f"交互点类型{target[1]}，位置{target[0][0]},{target[0][1]}")
            self.get_screen()
            # shape = (int(self.scx * 190), int(self.scx * 190))
            # local_screen = self.get_local(0.9333, 0.8657, shape)
            self.update_direction_data(mode=2,target=target)
            # if ii == 0:
            #     sub = 0
            # return sub
        else:
            return 0

    def move_thread(self):
        log.info("启动移动线程")
        me = 0
        if self.mini_state > 2:
            me = self.move_to_end()
            # self.is_target+=me
        else:
            # self.ang_off += self.move_to_interact(2)
            self.move_to_interact(2)
            # self.is_target+=self.ang_off
        self.ready = 1
        now_time = time.time()
        if me == 0:
            me = 0.5
        while not self.stop_move and time.time() - now_time < 3:
            if self.mini_state <= 2:
                # self.ang_off += self.move_to_interact()
                self.move_to_interact()
            else:
                me = max(self.move_to_end(me), me)
        log.info("停止移动线程")
        try:
            '''
            exec(
                self.mag
                + "p show numpy > NUL 2>&1') and not self.unlock"
            )
            '''
            pass
        except:
            pass

    def backup_map(self):
        """
        备份当前地图数据到磁盘文件

        将当前的地图数据和相关属性保存到磁盘文件中，包括：
        1. 地图图像数据(big_map)保存为PNG图像文件
        2. 其他地图相关属性保存为JSON文件

        备份文件保存在项目目录下的config/backup文件夹中。
        """
        try:
            # 确保备份目录存在（相对于项目根目录）
            backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "backup")
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)

            # 保存 big_map 到磁盘作为图像文件
            if hasattr(self, 'big_map') and self.big_map is not None:
                cv.imwrite(os.path.join(backup_dir, "big_map_backup.png"), self.big_map)

            # 保存其他属性到JSON文件
            backup_data = {
                'big_map_c': self.big_map_c,
                'lst_tm': self.lst_tm,
                'now_loc': self.now_loc,
                'mini_state': self.mini_state,
                'ang_off': self.ang_off,
                'ang_neg': self.ang_neg,
                'first_mini': self.first_mini
            }
            with open(os.path.join(backup_dir, "map_attrs_backup.json"), 'w') as f:
                json.dump(backup_data, f)
        except:
            pass
    # 初始化地图，刚进图时调用
    def init_map(self):
        self.backup_map()
        self.big_map = np.zeros((8192, 8192), dtype=np.uint8)
        self.big_map_c = 0
        self.lst_tm = 0
        self.now_loc = (4096, 4096)
        self.mini_state = 1
        self.ang_off = 0
        self.ang_neg = 0
        self.first_mini = 1
        self.in_battle = time.time()
        self.map_file = "resource/imgs/maps/my_" + str(random.randint(0, 99999)) + "/"
        if self.find == 0 and not os.path.exists(self.map_file):
            os.mkdir(self.map_file)
    def nof(self,must_be=None):
        """
        检查当前没有f交互
        """
        tm = time.time()
        ava = False
        if must_be is None and self.ts.similar("区域"):
            must_be='tp'
        while not ava and time.time()-tm<1.6:
            if not self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True) and (not self.is_run() or must_be == 'tp'):
                ava = True
        if ava:
            log.debug('交互点生效')
            if must_be == 'event':
                self.mini_state += 2
            elif must_be== 'tp':
                self.init_map()
                self.floor += 1
                self.f_time = time.time()
                self.lst_changed = time.time()
                log.info(f"地图{self.now_map}已完成,相似度{self.now_map_sim},进入{self.floor+1}层")
            else:
                if self.ts.similar("黑塔"):
                    self.quit = time.time()
                self.mini_state += 2
        else:
            log.warning('交互点未生效')
        return ava
    def save_screen(self, save_path=r"./temp",force=False,not_now=False):
        """
        获取截图并保存到指定路径
        :param save_path: 保存截图的路径
        :param force: 是否展示
        """
        if not_now:
            sc=self.screen
        else:
            sc = self.get_screen()

        # 如果截图是 numpy.ndarray 类型，将其转换为 PIL.Image
        if isinstance(sc, np.ndarray):
            # OpenCV使用BGR格式，PIL使用RGB格式，需要转换
            rgb_img = cv.cvtColor(sc, cv.COLOR_BGR2RGB)
            nc = Image.fromarray(rgb_img)
        else:
            nc = sc
        save_path = Path(save_path)
        save_path.mkdir(parents=True, exist_ok=True)
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
        nc.save(save_path / filename)
        return sc if force else nc
    def update_direction_data(self,mode=None,target=None):
        self.rotation, d = update_minimap_data(self.screen,rotation=self.rotation if hasattr(self, 'rotation') else 0,direction=self.ang - 270 if hasattr(self, 'ang') else 0)
        log.debug(f"视角{self.rotation}朝向{d}模式{mode}目标{target}")
        log.debug(f"当前点位{self.real_loc}目标点位{self.target_loc}")
        if 20<abs(self.rotation-d)<340:
            key_mouse_manager.wait()
            self.rotation, d = update_minimap_data(self.get_screen(),rotation=self.rotation, direction=self.ang - 270)
            if 20<abs(self.rotation-d)<340 and mode !=1:
                # cv.imshow("now", self.screen)
                self.save_screen(not_now=True)
                log.error(f"角度误差过大视角{self.rotation}朝向{d}模式{mode}")
                raise BigAngError(f"角度误差过大视角{self.rotation}朝向{d}")
            elif 20<abs(self.rotation-d)<340:
                log.debug(f"角度误差过大视角{self.rotation}朝向{d}模式1")
                d=self.rotation
        self.ang = 270 + d
        self.ang%=360
        if mode==2:
            self.real_loc=(93,93)
            self.target_loc= target[0]
        # 当前坐标与目标点连成的直线的斜率（大概）
        ang = (
                math.atan2(self.target_loc[0] - self.real_loc[0], self.target_loc[1] - self.real_loc[1])
                / math.pi
                * 180
        )
        # 视角需要旋转的角度，规范到[-180,180]
        sub = ang - self.ang
        sub = (sub + 180) % 360 - 180
        if  mode==2 and sub==0:
            sub=1e-9
        key_mouse_manager.mouse_move(sub)
        log.debug(f"当前人物角度为：{str(self.ang)}变换后角度{ang},视角移动{sub}"  )
        # 此处变换为了目标角度
        self.ang = ang
    # 寻路函数
    def get_direct_with_big_map(self):
        """
        np.array颜色为（b,g,r)
        """
        log.info("开始有地图寻路")
        self.set_path_state("开始有地图寻路")
        bw_map = self.get_bw_map(re_screen=0)
        self.loc_off = 0
        self.get_loc(bw_map, rg = 40 - self.find * 10)
        self.set_path_state("获取完路径1")
        if self.find == 1:
            key_mouse_manager.press("w", 0.2)
        self.get_screen()
        #截下当前小地图
        # local_screen = self.get_local(0.9333, 0.8657, shape)
        # 录图模式，将小地图覆盖到录制的大地图中
        if self.find == 0:
            log.debug("尝试记录地图中")
            self.write_map(bw_map)
            log.debug("尝试查找地图中")
            self.get_map()
        # 寻路模式
        else:
            self.set_path_state("开始寻路")
            if self.now_map == '19787':
                key_mouse_manager.press('w',0.3)
                self.get_screen()
                # local_screen = self.get_local(0.9333, 0.8657, shape)
                self.now_map = '19788'
            # 如果当前就在交互点上：直接返回
            if self.good_f()[0] and not self.ts.similar("黑塔"):
                self.set_path_state("位于交互点，移除交互点")
                for j in deepcopy(self.target):
                    #类型为二，交互点
                    if j[1] == 2:
                        self.target.remove(j)
                        log.info("检测到交互点，已移除目标:" + str(j))
                return
            self.set_path_state("开始更新方向1")
            #纠正为标准坐标系然后上下反转的坐标系角度（取反估计是为了便于底层操作向左为负，向右为正）
            if not hasattr(self, 'ang'):
                self.ang=270
            self.get_real_loc()
            self.target_loc, self.target_type = self.get_recent_target()
            self.update_direction_data()
            threshold_distance = [13,9 + self.quan*7,11,7]
            if self._stop == 0:
                key_mouse_manager.keyDown("w")
            time.sleep(0.25)
            is_sprinting=0
            if self.target_type != 3:
                sprint()
                is_sprinting = 1
            time.sleep(0.25)
            bw_map = self.get_bw_map()
            if bw_map is None:
                return
            self.set_path_state("开始获取真实路径")
            self.get_loc(bw_map, rg=30, offset=self.get_offset(4))
            self.get_real_loc(1)
            # 复杂的定位、寻路过程
            ds = get_dis(self.real_loc, self.target_loc)#可能是当前点距离与目标点距离
            distance_list = [100000]
            dtm = [time.time()]
            go_direct = 2
            go_time=random.uniform(0, 1.5)
            retry_time = 0
            has_not_found_red=False
            for i in range(3000):
                self.set_path_state("开始定位寻路")
                log.info("第{}次定位寻路".format(i))
                if self._stop == 1:
                    key_mouse_manager.keyUp("w")
                    return
                self.get_screen()
                bw_map = self.get_bw_map()
                if bw_map is None:
                    self.set_path_state("获取地图失败")
                    return
                #预判实际点位
                self.get_loc(bw_map, fbw=1, offset=self.get_offset(2 + (retry_time <= 2)),
                             rg=10 + 6 * (retry_time <= 2))
                self.get_real_loc(2 + is_sprinting * 5)
                if self.target_type==1:
                    self.set_path_state("先验遇敌")
                    now_distance = get_dis(self.real_loc, self.target_loc)
                    if now_distance<35:
                        self.set_path_state("距离敌人过近")
                        red = [47, 47, 232]
                        rd = np.where(
                            np.sum((get_minimap(self.screen, radius=MINIMAP_RADIUS, copy=True,rotation=True) - red) ** 2, axis=-1) <= 4500)
                        log.info(f"距离小于35,开始清除{(self.target_loc, 1)}从{self.target}")
                        self.target.remove((self.target_loc, 1))
                        if rd[0].shape[0] > 0:
                            self.set_path_state("尝试找新的敌人点位")
                            recent_loc = (self.real_loc[0] + rd[0][0] - 93, self.real_loc[1] + rd[1][0] - 93)
                            log.info(f"当前目标集合{self.target}")
                            self.target.add((recent_loc, 1))
                            self.target_loc=recent_loc
                            log.info(f"找到新的敌对目标点：{recent_loc}")
                        else:
                            self.set_path_state("未找到红色敌人！！！")
                            self.save_screen(not_now= True)
                            # self.save_screen(not_now=True)
                            has_not_found_red= True

                            # self.target_loc, type = self.get_recent_target()
                        if has_not_found_red:
                            self.set_path_state("未找到敌人！！！")
                            break
                ds = get_dis(self.real_loc, self.target_loc)
                if ds>threshold_distance[self.target_type]:
                    self.set_path_state("距离较远，开始更新方向2")
                    self.update_direction_data(mode=1)
                if self.debug:
                    self.big_map[
                        self.real_loc[0] - 1 : self.real_loc[0] + 2,
                        self.real_loc[1] - 1 : self.real_loc[1] + 2,
                    ] = 49
                    # 轨迹图
                    cv.imwrite("debug/bigmap.jpg", self.big_map)
                self.set_path_state("获取当前距离目标距离")
                now_distance = get_dis(self.real_loc, self.target_loc)
                # 1秒内没有离目标点更近：开始尝试绕过障碍
                if distance_list[0] <= now_distance:
                    self.set_path_state("尝试绕过障碍")
                    ts = " da"
                    if go_direct > 0:
                        log.info(f"尝试绕过障碍向{ts[go_direct]}")
                        key_mouse_manager.keyUp("w")
                        key_mouse_manager.press("s", 0.35)
                        if go_direct==2:
                            key_mouse_manager.press(ts[go_direct], go_time)
                        else:
                            key_mouse_manager.press(ts[go_direct], go_time+random.uniform(0, 1.5))
                        key_mouse_manager.press("w", 0.3)
                        self.move = 1
                        self.get_screen()
                        threading.Thread(target=self.keep_move).start()
                        bw_map = self.get_bw_map(re_screen=0)
                        self.get_loc(bw_map, rg=28, fbw=1)
                        self.get_real_loc()
                        self.move = 0
                        time.sleep(0.12)
                        go_direct -= 1
                        distance_list = [100000]
                        dtm = [time.time()]
                        sprint()
                        retry_time = 0
                        is_sprinting = 1
                    else:
                        log.info("尝试次数过多，不再尝试绕过障碍")
                        key_mouse_manager.keyUp("w")
                        break
                self.set_path_state("距离目标更近了")
                if now_distance <= threshold_distance[self.target_type]:
                    self.set_path_state("距离目标小于阈值")
                    if self.target_type == 0:
                        distance_list = [100000]
                        dtm = [time.time()]
                        self.target.remove((self.target_loc, self.target_type))
                        log.info("已到达路径点" + str((self.target_loc, self.target_type)))
                        self.lst_changed = time.time()
                        self.target_loc, self.target_type = self.get_recent_target()
                        if self.target_type == 3:
                            sprint()
                            is_sprinting = 0
                        ds = get_dis(self.real_loc, self.target_loc)
                        go_direct = 2
                    else:
                        key_mouse_manager.keyUp("w")
                        break
                else:
                    self.set_path_state("正常逼近目标")
                    self.get_screen()
                    if self.target_type == 3 and self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                        key_mouse_manager.press('f',force= True)
                        key_mouse_manager.keyUp("w")
                        if self.nof(must_be='tp'):
                            log.info('大图识别到传送点!')
                            return
                    elif (self.target_type != 3 and self.good_f()[0]) or not self.is_run():
                        key_mouse_manager.keyUp("w")
                        break
                ds = now_distance
                distance_list.append(ds)
                dtm.append(time.time())
                # 正常情况：1.7s
                # 快速移动时：2.7s
                # 慢速移动时：1.3s
                # 既快速又慢速时?：2.3s
                while dtm[0] < time.time() - 1.7 + is_sprinting * 1 - self.slow * 0.4:
                    dtm = dtm[1:]
                    distance_list = distance_list[1:]
                retry_time += 1
                self.set_path_state("重试寻路")
            self.set_path_state("跳出寻路")
            log.info(f"进入新地图或者进入战斗 {now_distance}")
            if self.target_type == 0:
                self.lst_tm = time.time()
            if self.target_type == 1:
                if has_not_found_red:
                    self.target.add((self.target_loc, 0))
                    self.target_type = 0
                    log.info(f"寻路时未找到敌对目标点，强行攻击后把旧目标点视作路径")
                self.set_path_state("准备开战")
                log.info("准备开战")
                if not self.quan:
                    if self._stop == 0:
                        key_mouse_manager.click(0.5,0.5)
                    time.sleep(1.1)
                    key_mouse_manager.press("s")
                    if self._stop == 0:
                        key_mouse_manager.click(0.5,0.5)
                    time.sleep(0.8)
                    if len(self.target) <= 2:
                        time.sleep(0.3)
                        key_mouse_manager.press("s")
                        key_mouse_manager.click(0.5,0.5)
                        time.sleep(0.6)
                        key_mouse_manager.press("s", 0.5)
                        key_mouse_manager.click(0.5,0.5)
                        time.sleep(0.5)
                        key_mouse_manager.press("w", 1.6)
                        key_mouse_manager.click(0.5,0.5)
                else:
                    key_mouse_manager.keyUp("w")
                    for ii in range(1):
                        self.use_e()
                        if ii:
                            time.sleep(0.6)
                        self.use_e()
                        bw_map = self.get_bw_map()
                        if bw_map is None:
                            continue
                        self.get_loc(bw_map, fbw=1, offset=self.get_offset(2), rg=24)
                        self.get_real_loc(1)
                        key_mouse_manager.press('w')
                        self.bless()
            if self.target_type == 3:
                self.set_path_state("当前寻找终点")
                for i in range(9):
                    self.get_screen()
                    if self.quan and self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False):
                        return
                    if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                        log.info("大图识别到类型三传送点")
                        key_mouse_manager.press('f',force= True)
                        if self.nof(must_be='tp'):
                            time.sleep(1.5)
                            break
                    self.get_screen()
                    if self.is_run():
                        if i in [0,4]:
                            self.move_to_end()
                        key_mouse_manager.press('w', 0.5)
                        time.sleep(0.2)
            # 离目标点挺近了，准备找下一个目标点
            elif now_distance <= 20:
                self.set_path_state("距离目标非常近2")
                try:
                    self.target.remove((self.target_loc, self.target_type))
                    log.info("靠近目标点，移除:" + str((self.target_loc, self.target_type)))
                    self.lst_changed = time.time()
                except:
                    pass
            self.set_path_state("结束寻路")
    def keep_move(self):
        op = 'ws'
        i = 0
        log.info("开始持续移动")
        while self.move and not self._stop:
            key_mouse_manager.press(op[i], 0.05)
            time.sleep(0.08)
            i ^= 1
        if not self._stop:
            key_mouse_manager.keyDown("w")
        log.info("结束持续移动")


    def write_map(self, bw_map):
        """
        绘制self.big_map，从当前小地图获取白线信息，再根据小地图中心（即自身点位）设置大地图对应点位为白线
        """
        for i in range(bw_map.shape[0]):
            for j in range(bw_map.shape[1]):
                if ((i - 88) ** 2 + (j - 88) ** 2) > 80**2:
                    bw_map[i, j] = 0
                # 如果小地图的当前像素点是白线，在大地图的对应像素点增加权重
                if bw_map[i, j] == 255:
                    if (
                        self.big_map[self.now_loc[0] - 88 + i, self.now_loc[1] - 88 + j]
                        < 250
                    ):
                        self.big_map[
                            self.now_loc[0] - 88 + i, self.now_loc[1] - 88 + j
                        ] += 50


    def get_loc(self, bw_map, rg=10, fbw=0, offset=None):
        """
        移动后根据旧坐标获得新坐标（匹配）
        rg：匹配的范围（以旧坐标为中心） fbw：是否进行缩放
        fbw：（人物静止/移动时小地图会有个缩放的过程，
        fbw=0表示当前人物是静止状态，因此缩放到移动状态与大地图匹配）
        ps：大地图是移动状态录制的
        """
        log.info(f"获取新坐标,当前坐标{self.now_loc}范围{rg},是否移动{fbw},偏移{offset}")
        rge = 88 + rg
        #创建一个2rge大小的地图
        loc_big = np.zeros((rge * 2, rge * 2), dtype=self.big_map.dtype)
        tpl = (self.now_loc[0], self.now_loc[1])
        if offset is not None:
            tpl = (tpl[0]+int(offset[0]),tpl[1]+int(offset[1]))
        x0, y0 = max(rge - tpl[0], 0), max(rge - tpl[1], 0)
        x1, y1 = max(tpl[0] + rge - self.big_map.shape[0], 0), max(
            tpl[1] + rge - self.big_map.shape[1], 0
        )
        # 从大地图中截取对应部分（tpl为中心，rge为匹配范围）
        loc_big[x0 : rge * 2 - x1, y0 : rge * 2 - y1] = self.big_map[
            tpl[0] - rge + x0 : tpl[0] + rge - x1, tpl[1] - rge + y0 : tpl[1] + rge - y1
        ]
        max_val, max_loc = -1, 0
        #bo_1：原始二值地图中白色区域
        bo_1 = bw_map == 255
        tt = 4
        kernel = np.zeros((5, 5), np.uint8)
        kernel += 1
        log.info(f"从大地图中截取对应部分")
        if self.find and fbw == 0:
            #用150这个阈值二值化
            tbw = cv.resize(bw_map, (176 + tt * 2, 176 + tt * 2))
            tbw[tbw > 150] = 255
            tbw[tbw <= 150] = 0
            tbw = tbw[tt : 176 + tt, tt : 176 + tt]
            #bo_2：缩放、阈值处理和裁剪后的地图中白色区域的掩码
            bo_2 = tbw == 255
            b_map = cv.dilate(tbw, kernel, iterations=1)
            #bo_5：处理后的图像(tbw)膨胀后新增的区域
            bo_5 = (b_map != 0) & (bo_2 == 0)
        bo_3 = loc_big >= 50
        b_map = cv.dilate(bw_map, kernel, iterations=1)
        #bo_4：原图中不存在但在膨胀后出现的区域
        bo_4 = (b_map != 0) & (bo_1 == 0)
        # 枚举匹配，找到匹配点最多的坐标（2rg范围内）
        log.info("开始枚举匹配")
        for i in range(rge * 2 - 176):
            for j in range(rge * 2 - 176):
                if (i - rge + 88) ** 2 + (j - rge + 88) ** 2 > rg**2:
                    continue
                p = 2*np.count_nonzero(bo_3[i : i + 176, j : j + 176] & bo_1)
                p += np.count_nonzero(bo_3[i : i + 176, j : j + 176] & bo_4)
                if p > max_val:
                    max_val = p
                    max_loc = (i, j)
                    if self.debug:
                        tmp = np.zeros((176,176), dtype=np.uint8)
                        tpp = bo_3[i : i + 176, j : j + 176]
                        tmp[tpp!=0]=255
                        tmp[bo_1!=0]=150
                        tmp[bo_4!=0]=50
                if self.find and fbw == 0:
                    p = 2*np.count_nonzero(bo_3[i : i + 176, j : j + 176] & bo_2)
                    p += np.count_nonzero(bo_3[i : i + 176, j : j + 176] & bo_5)
                    if p > max_val:
                        max_val = p
                        max_loc = (i, j)
        log.info(f"结束枚举匹配")
        if max_val != 0:
            self.now_loc = (
                max_loc[0] + 88 - rge + self.now_loc[0],
                max_loc[1] + 88 - rge + self.now_loc[1],
            )
        log.info("新坐标：" + str(self.now_loc))
        if self.debug:
            cv.imwrite('tp/'+str(time.time())+'.jpg',tmp)
            # log.debug("匹配结果已写入")
            # 保存tmp地图供show_map函数使用
            self.tmp_map = tmp.copy()
            log.debug(f"tmp地图已保存，形状: {self.tmp_map.shape if self.tmp_map is not None else 'None'}")

    def get_real_loc(self,delta=0):
        x, y = self.now_loc
        dx, dy = self.get_offset(delta=delta)
        self.real_loc = (int(x+10+dx),int(y+dy))

    def get_offset(self,delta=1):
        if self.slow:
            delta /= 2
        pi = 3.141592653589
        dx, dy = sin(self.ang/180*pi), cos(self.ang/180*pi)
        return delta * dx * 3, delta * dy * 3

    # 从8192*8192的超大地图中找到有意义的大地图
    def get_map(self):
        """
        先对self.big_map裁剪出含有白色的所有有效区域
        """
        x1, x2, y1, y2 = 0, 8191, 0, 8191
        while x1 < 8192 and np.sum(self.big_map[x1, :]) == 0:
            x1 += 1
        while y1 < 8192 and np.sum(self.big_map[:, y1]) == 0:
            y1 += 1
        while x2 > 0 and np.sum(self.big_map[x2, :]) == 0:
            x2 -= 1
        while y2 > 0 and np.sum(self.big_map[:, y2]) == 0:
            y2 -= 1
        if x1 >= x2 or y1 >= y2:
            return
        # 权重得大于一个值，才能被判定为白线（否则是噪声）
        weight = deepcopy(self.big_map[x1 - 1 : x2 + 2, y1 - 1 : y2 + 2])
        weight[weight >= 100] = 255
        #下面似乎是检查邻域是否有白线的代码，但是取值只有某个点本身，没有任何作用
        # bk = deepcopy(weight)
        # for i in range(weight.shape[0]):
        #     for j in range(weight.shape[1]):
        #         f = 0
        #         for ii in range(0, 1):
        #             for jj in range(0, 1):
        #                 if 0 <= i + ii < weight.shape[0]and 0 <= j + jj < weight.shape[1]:
        #                     if bk[i + ii, j + jj] == 255:
        #                         f = 1
        #                         break
        #         if f:
        #             weight[i, j] = 255
        weight[weight < 100] = 0
        cv.imwrite(
            self.map_file + "map_" + str(x1 - 1) + "_" + str(y1 - 1) + "_.jpg", weight
        )
        cv.imwrite(self.map_file + "target.jpg", weight)

    # 匹配地图，找到最相似的地图，确定当前房间对应的地图
    def match_scr(self, img):
        key = extract_features(img)
        img = self.get_bw_map(re_screen=0, local_screen=img)
        sim = -1
        ans = -1
        matcher = cv.BFMatcher(cv.NORM_HAMMING, crossCheck=True)
        res = []
        for i, j in self.img_set:
            try:
                matches = matcher.match(key, j)
                similarity_score = len(matches) / max(len(key), len(j))
                res.append((similarity_score,i))
            except:
                pass
        res = sorted(res, key=lambda x: x[0])[-3:]
        try:
            if res[-1][0]>res[-2][0]+0.065 and (res[-1][0]>0.4 or self.debug!=2):
                return res[-1][1], 0.9
        except:
            return -1, -1
        i_s = [x[1] for x in res]
        for i in i_s[::-1]:
            bw_j = self.get_bw_map(re_screen=0, local_screen=self.img_map[i])
            big_bw_j = np.zeros((bw_j.shape[0]+28,bw_j.shape[1]+28),dtype=bw_j.dtype)
            big_bw_j[14:-14,14:-14] = bw_j
            result = cv.matchTemplate(big_bw_j, img, cv.TM_CCORR_NORMED)
            min_val, max_val, min_loc, max_loc = cv.minMaxLoc(result)
            if max_val > sim:
                sim = max_val
                ans = i
        return ans, sim


    def print_stack(self, num=1):
        """
        在调试模式下打印调用栈信息
        
        Args:
            num (int): 要打印的堆栈层数，默认为1层
            
        Returns:
            None: 仅打印堆栈信息到控制台，无返回值
        """
        if self.debug:
            stk = traceback.extract_stack()
            for i in range(num):
                try:
                    # 打印调用栈信息：当前函数名、文件名、函数名和行号
                    print(stk[-2].name,stk[-3-i].filename.split('\\')[-1].split('.')[0],stk[-3-i].name,stk[-3-i].lineno)
                except:
                    pass

    
    def is_run(self):
        scr = self.screen
        shape = (int(self.scx * 12), int(self.scx * 12))
        loc_scr = self.get_local(0.9333, 0.8657, shape)
        hsv = cv.cvtColor(loc_scr, cv.COLOR_BGR2HSV)  # 转HSV
        lower = np.array([93, 120, 60])  # 90 改成120只剩箭头，但是角色移动过的印记会消失
        upper = np.array([97, 255, 255])
        mask = cv.inRange(hsv, lower, upper)  # 创建掩膜
        sum_blue = np.sum(mask)
        scr_bak = deepcopy(scr)
        scr[np.min(scr,axis=-1)<=220]=[0,0,0]
        scr[np.min(scr,axis=-1)>220]=[255,255,255]
        res = self.check('run', 0.876, 0.7815, threshold=0.91) and 40000 < sum_blue < 65000
        if self.tm>0.96:
            res = 1
        self.screen = deepcopy(scr_bak)
        if res:
            self.f_time = 0
        return res
    def update_debug_map(self):
        self.debug_map = deepcopy(get_minimap(self.get_screen(), radius=MINIMAP_RADIUS))
    def auto_update_map(self):
        while self.should_update_map and not self._stop:
            log.debug("更新一次地图")
            self.update_debug_map()
            time.sleep(2)
    def get_direc_only_minimap(self):
        """
        self.ang_off 含义
        角度偏移值,表示视角需要旋转的角度偏移量
        用于记录当前视角相对于目标方向的角度偏差,当检测到需要调整视角时，会累积角度偏移值，
        后续通过 key_mouse_manager.mouse_move(-self.ang_off*1.2) 进行视角校正
        self.mini_state 含义
        0: 初始状态
        1: 寻路中状态
        3: 接近目标点状态
        >=7: 完成一轮寻路
        self.check_bonus含义
        是否领取沉浸奖励
        """
        log.info("开始无地图寻路")
        self.should_update_map=True
        threading.Thread(target=self.auto_update_map).start()
        if self.debug:
            log.debug(f'当前状态{self.ang_off},{self.mini_state}')
        self.ang_neg=self.ang_off<0
        if self.ang_off:
            #存在角度偏移值则使视线与角色朝向一致
            time.sleep(0.6)
            log.debug(f'无地图视角补正{-self.ang_off*1.2}')
            key_mouse_manager.mouse_move(-self.ang_off*1.2)
            time.sleep(0.3)
            key_mouse_manager.press('w',0.3)
        if self.mini_state==1 and self.floor in [4,8,11]:
            time.sleep(0.5)
            key_mouse_manager.press('w',0.55)
            key_mouse_manager.click(0.5,0.5)
            time.sleep(2)
            key_mouse_manager.press('w')
            time.sleep(0.4)
        #12层并且不要奖励
        if self.mini_state==3 and self.floor==12 and not self.check_bonus:
            self.mini_state=5
            self.should_update_map = False
            return
        #3，7，12层领奖
        if self.mini_state==3 and self.floor in [3,7,12] and self.check_bonus:
            key_mouse_manager.press('d',0.6)
            key_mouse_manager.keyDown('w')
            nt = time.time()
            while time.time()-nt<1.3:
                if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh=True):
                    key_mouse_manager.press('f',force= True)
                    key_mouse_manager.keyUp('w')
                    break
            key_mouse_manager.keyUp('w')
            key_mouse_manager.press('f',force= True)
            time.sleep(1)
            for _ in range(2):
                if not self.check_bonus:
                    break
                #领取沉浸奖励
                if self.check('bonus_c',0.2385,0.6685,fresh=True):
                    key_mouse_manager.click(0.4453,0.3250)
                    time.sleep(1.5)
                    if self.click_text(text="储存沉浸器",box=[838, 1070, 298, 400],click=False,ocr_line=False,warning=False):
                        self.check_bonus = 0
                    key_mouse_manager.click(0.5062, 0.1454)
                    time.sleep(1.4)
            key_mouse_manager.keyUp('w')
            if self.check('bonus_c',0.2385,0.6685,fresh=True):
                key_mouse_manager.click(0.2385,0.6685)
            self.mini_state=5
            if self.floor==12:
                self.should_update_map = False
                return
            key_mouse_manager.press('s',0.4)
        self.ang_off=0
        self.stop_move=0
        self.ready=0
        self.mini_target=0
        self.get_screen()
        self.is_target=0
        first = self.first_mini
        threading.Thread(target=self.move_thread).start()
        while not self.ready:
            time.sleep(0.1)
        if not self.ang_off and self.mini_state == 1:
            if self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95):
                if self.floor == 11:
                    self.floor = 12
        key_mouse_manager.keyDown("w")
        wt = 3
        self.first_mini = 0
        is_sprinting = 0
        if self.mini_state==1:
            wt += 1
            if self.mini_target!=2:
                sprint()
                is_sprinting = 1
            if self.mini_target==1:
                wt += 0.8
        need_confirm=0
        init_time = time.time()
        while True:
            log.info("开始检测交互点循环")
            self.get_screen()
            if self._stop == 1:
                key_mouse_manager.keyUp("w")
                self.stop_move=1
                break
            if self.mini_target==1:
                if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                    key_mouse_manager.keyUp("w")
                    key_mouse_manager.press('f')
                    log.info('发现事件交互')
                    self.stop_move=1
                    need_confirm = 1
                    if self.nof(must_be='event'):
                        self.should_update_map = False
                        return
                    break
            else:
                judge,use_time=self.good_f()
                if judge and not (self.ts.similar("黑塔") and time.time() - self.quit < 30):
                    if self.speed <= 0 or not self.ts.similar("黑塔"):
                        key_mouse_manager.clean()
                        if is_sprinting:
                            key_mouse_manager.press("shift")
                        key_mouse_manager.keyUp("w",force=True)
                        key_mouse_manager.press('f',force=True)
                        key_mouse_manager.press("s",use_time)
                        key_mouse_manager.sleep(0.2)
                        key_mouse_manager.press('f')
                        self.stop_move=1
                        need_confirm = 1
                        key_mouse_manager.wait()
                        log.info('等待验证交互文本 '+self.ts.text)
                        if self.nof():
                            key_mouse_manager.keyUp("w")
                            self.should_update_map = False
                            return
                        break
                    else:
                        self.quit = time.time()
                        key_mouse_manager.keyUp("w")
                        self.stop_move=1
                        self.mini_state+=2
                        self.should_update_map = False
                        return
                if self.check("auto_2", 0.0583, 0.0769): 
                    key_mouse_manager.keyUp("w")
                    self.stop_move=1
                    self.mini_state+=2
                    break
                if self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95):
                    self.stop_move=1
                    # time.sleep(1.7+self.slow*1.1-(self.quan and self.floor not in [3, 7, 12])*0.5)
                    if self.mini_state==1 and self.floor in [3, 7, 12] and not self.quan:
                        key_mouse_manager.keyUp("w")
                        if not self.check("ruan",0.0625,0.7065,threshold=0.95) and not self.check("U", 0.0240,0.7759):
                            for i in range([3, 7, 12].index(self.floor)+2):
                                key_mouse_manager.press(str(i+1))
                                time.sleep(0.4)
                                self.use_e()
                                self.get_screen()
                                if not self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95):
                                    break
                                if self._stop:
                                    break
                            key_mouse_manager.keyDown("w")
                    iters = 0
                    while self.check("z",0.5906,0.9537,mask="mask_z",threshold=0.95,fresh=True) and not self._stop:
                        log.info("检测到怪物，准备攻击")
                        key_mouse_manager.keyUp("w")
                        iters+=1
                        if iters>4:
                            break
                        curloc = (120, 127)
                        shape = (int(self.scx * 190), int(self.scx * 190))
                        local_screen = get_minimap(self.screen, radius=MINIMAP_RADIUS,copy=True,rotation=True)
                        red = [47, 47, 232]
                        rd = np.where(np.sum((local_screen - red) ** 2, axis=-1) <= 4500)
                        if rd[0].shape[0] > 0:
                            target = ((rd[0][0], rd[1][0]), 3)
                            self.get_screen()
                            # local_screen = self.get_local(0.9333, 0.8657, shape)
                            self.update_direction_data(mode=2,target=target)
                        ds = get_dis(self.real_loc, self.target_loc)
                        if ds>28:
                            log.debug(f"距离目标{ds},太远，等待{(ds-20)//8}秒")
                            time.sleep((ds-20)//8)
                        if self.quan:
                            key_mouse_manager.keyUp("w")
                            self.use_e()
                            if self.floor not in [3, 7, 12]:
                                for _ in range(4):
                                    self.use_e()
                                self.stop_move=1
                                self.mini_state+=2
                                time.sleep(0.4)
                                key_mouse_manager.press('w')
                                time.sleep(1.4)
                                self.should_update_map = False
                                return
                            else:
                                time.sleep(0.8)
                                key_mouse_manager.keyDown("w")
                        else:
                            key_mouse_manager.click(0.5,0.5)
                        if iters + self.quan == 2:
                            time.sleep(0.9)
                            key_mouse_manager.press('d',0.85)
                            key_mouse_manager.press('a',0.3)
                        else:
                            time.sleep(1.2)
                    self.mini_state+=2
                    break
            if time.time()-init_time>wt:
                self.stop_move=1
                key_mouse_manager.keyUp("w")
                self.mini_state+=2
                if self.mini_state>=7:
                    self.lst_changed = 0
                    self.should_update_map = False
                    return
                key_mouse_manager.press('s',0.3)
                key_mouse_manager.press('a',0.7)
                key_mouse_manager.press('d',0.45)
                key_mouse_manager.press('w',0.5)
                break
            time.sleep(0.1)
        self.stop_move=1
        key_mouse_manager.keyUp("w")
        if need_confirm or (first and self.mini_target!=2):
            log.info("尝试乱转找到交互点")
            for i in "sasddwwaa":
                if self._stop:
                    self.should_update_map = False
                    return
                self.get_screen()
                if self.mini_target==1:
                    log.info(f"必须找到交互点，尝试寻找")
                    if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                        key_mouse_manager.press('f',force= True)
                        if self.nof(must_be='event'):
                            self.should_update_map = False
                            return
                elif self.good_f()[0] and not (self.ts.similar("黑塔") and time.time() - self.quit < 30):
                    # cv.imshow("f",self.screen)
                    log.info(f"找到最佳交互点")
                    key_mouse_manager.press('f',force= True)
                    self.get_screen()
                    # cv.imshow("newf",self.screen)
                    # cv.waitKey(0)
                    if self.nof():
                        self.should_update_map = False
                        return
                key_mouse_manager.press(i, 0.25)
                log.info(f"向{i}走0.25秒")
                time.sleep(0.65)
            key_mouse_manager.click(0.5,0.5)
            self.should_update_map = False

    def solve_snack(self):
        if self.check('snack', 0.3844,0.5065, mask='mask_snack',fresh= True):
            key_mouse_manager.click(self.tx,self.ty)
            time.sleep(0.3)
            self.click_position([1184, 815])
            time.sleep(0.4)
        else:
            self.allow_e = 0
            time.sleep(1.0)
        self.click_position([768, 815])
        time.sleep(0.6)
        if self.allow_e:
            key_mouse_manager.press('e')
    
    def use_e(self):
        key_mouse_manager.press('e',force= bool(self.quan))
        time.sleep(0.4)
        if not self.quan:
            time.sleep(0.8)
        if self.click_text(text="快速恢复",box=[864, 1058, 224, 318],click=False,ocr_line=False,warning=False):
            self.solve_snack()
    def reset_bless(self,chose=0):
        if self.click_text(text="重置祝福", box=[1268, 1444, 929, 1025], click=False, warning=False):
            for _ in range(14):
                img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask", fresh=True)
                if self.ts.split_and_find(self.tk.fates, img_down, mode="bless")[1]or self._stop:
                    time.sleep(0.2)
                    break
                if not self.click_text(text="选择祝福", box=[60, 222, 0, 113], click=False, ocr_line=False,
                                       warning=False):
                    return 1
                time.sleep(0.2)
            img_up = self.get_small_interaction_img(x=0.5047, y=0.5491, mask="mask_bless", fresh=True)
            res_up = self.ts.split_and_find(self.tk.prior_bless, img_up, bless_skip=self.tk.skip)
            img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask")
            res_down = self.ts.split_and_find([self.fate], img_down, mode="bless")
            if res_up[1] == 2:
                key_mouse_manager.click(*self.calc_point((0.5047, 0.5491), res_up[0]))
                chose = 1
            elif res_down[1] == 2:
                key_mouse_manager.click(*self.calc_point((0.5042, 0.3204), res_down[0]))
                chose = 1
            if not chose:
                key_mouse_manager.click(0.2990, 0.1046)
                time.sleep(1.2)
        if not chose:
            for _ in range(8):
                img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask", fresh=True)
                if self.ts.split_and_find(self.tk.fates, img_down)[1] or self._stop:
                    time.sleep(0.2)
                    break
                if not self.click_text(text="选择祝福", box=[60, 222, 0, 113], click=False, ocr_line=False,
                                       warning=False):
                    return 1
                time.sleep(0.2)
            img_up = self.get_small_interaction_img(x=0.5047, y=0.5491, mask="mask_bless", fresh=True)
            res_up = self.ts.split_and_find(self.tk.prior_bless, img_up, bless_skip=self.tk.skip)
            img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask")
            res_down = self.ts.split_and_find(
                self.tk.secondary, img_down, mode="bless"
            )
            if res_up[1] == 2:
                key_mouse_manager.click(*self.calc_point((0.5047, 0.5491), res_up[0]))
            elif res_down[1] >= 2:
                key_mouse_manager.click(*self.calc_point((0.5042, 0.3204), res_down[0]))
            else:
                key_mouse_manager.click(*self.calc_point((0.5047, 0.5491), res_up[0]))
            time.sleep(0.5)
    def bless(self):
        self.get_screen()
        if self.wait_flag(lambda:not self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False), 2.3):
            self.wait_flag(lambda:not self.click_text(text="重置祝福",box=[1268, 1444, 929, 1025],click=False,warning=False), 0.7)
            time.sleep(1.2)
        else:
            return
        for _ in range(6):
            self.in_battle = 0
            self.get_screen()
            self.reset_bless()
            # 未匹配到优先祝福，刷新祝福并再次匹配
            key_mouse_manager.click(0.1203, 0.1093)
            time.sleep(1.7)
            self.get_screen()
            if not self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False):
                return

    def click_box(self, box):
        """
        点击给定坐标框的中心位置
        
        Args:
            box: 坐标框，格式为[x1, x2, y1, y2]，其中x1,x2为横向坐标，y1,y2为纵向坐标
        """
        x = (box[0] + box[1]) / 2
        y = (box[2] + box[3]) / 2
        key_mouse_manager.click(1 - x / self.xx, 1 - y / self.yy)

    def click_position(self, position):
        """
        点击给定位置坐标
        
        Args:
            position: 位置坐标，格式为[x, y]，其中x为横向坐标，y为纵向坐标
        """
        self.click_box([position[0], position[0], position[1], position[1]])