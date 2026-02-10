import json
import pyautogui
import cv2 as cv
import numpy as np
import time
import random
from copy import deepcopy

from config.GLOBAL import key_mouse_manager
from config import EXTRA
from diver import load_actions, merge_text
from utils.log import CUS_LOGGER, set_debug
from utils.simul.update_map import update_map
from utils.simul.utils import UniverseUtils, set_forground, sprint, get_dis, extract_features
import os
from align_angle import main as align_angle_main
from utils.simul.config import config
from utils.thread import ThreadWithException
from utils.utils.mminimap import update_minimap_data
from utils.utils.tool import get_hwnd_and_text, find_latest_modified_file, get_center
from utils.window_recorder import WindowRecorder
from route import PATHS


class SimulatedUniverse(UniverseUtils):
    def __init__(self, find, debug, speed, consumable, slow, nums=-1, bonus=False, update=0, gui=None):
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
        super().__init__(speed,gui)
        CUS_LOGGER.info("当前命途：" + self.fate)
        key_mouse_manager.set_config(config)
        # 设置屏幕参数以支持坐标转换
        key_mouse_manager.set_screen_params(self.x1, self.y1, self.xx, self.yy, self.full)
        #目标坐标
        self.target_loc = [0, 0]
        #停止运行标志
        self._stop = True
        #是否为寻路模式
        self.find = find
        #调试级别
        self.debug = debug
        if self.debug:
            set_debug(CUS_LOGGER,True)
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
        #重启次数
        self.re_align = 0
        # 是否仍然可用沉浸器
        self.check_bonus = bonus
        # 是否领取沉浸奖励
        self.bonus = bonus
        # 是否强制结束
        self.must_end = False
        #失败次数
        self.fail_count = 0
        #是否已完成
        self.end = 0
        #上次战斗时间
        self.in_battle = 0
        #是否初始化层数
        self.floor_init = 0
        #上次点击确认时间
        self.confirm_time = 0
        # 添加用于计算FPS的变量
        self.last_get_screen_time = None
        self.fps_list = []
        # 添加地图线程引用
        self.map_thread = None
        #地图的初始化状态
        self.map_init=False
        # 是否首次获取层数
        self.first_get_floor=False
        #事件与行为存储路径
        self.default_json_path = "actions/universe.json"
        self.default_json = load_actions(self.default_json_path)
        self.action_history = []
        if debug != 2:
            #似乎是避免鼠标越界的一个标志
            pyautogui.FAILSAFE = False
        self.update_debug_map()
        self.update_count()
        CUS_LOGGER.info(f"开始运行,初始计数：{self.count}")
        # set_debug(debug > 0)
        if update and find:
            update_map()
        self.lst_changed = time.time()
        CUS_LOGGER.info("加载地图")
        for file in os.listdir("resource/imgs/maps"):
            pth = "resource/imgs/maps/" + file + "/init.jpg"
            if os.path.exists(pth):
                image = cv.imread(pth)
                self.img_set.append((file, extract_features(image)))
                self.img_map[file]= image
        CUS_LOGGER.info("加载地图完成，共 %d 张" % len(self.img_set))
        # 从settings.json获取录制状态
        with EXTRA.FILE_LOCK:
            with open(PATHS["root"] + "\\config\\config\\settings.json", mode="r", encoding="UTF-8") as file:
                data = json.load(file)
        
        self.record = data.get("recording_state", True)
        # 根据self._show_map决定是否叠加地图到录制视频上
        self.recorder = WindowRecorder('logs/video/', fps=30, window_title="崩坏：星穹铁道",window_class_name="UnityWndClass",see_time=True, offsets=[10, 50, 10, 10], overlay_map=self._show_map)


    def route(self):
        self.in_battle = 0
        self.init_map()
        fail_cnt = 0
        fail_time = 0
        fp = 1
        set_forground()
        self.goto_herta_office()
        while not self._stop:
            hwnd,Text = get_hwnd_and_text()
            warn_game = False
            cnt = 0
            while Text != "崩坏：星穹铁道" and Text != "云·星穹铁道" and not self._stop:
                self.lst_changed = time.time()
                if self._stop:
                    raise KeyboardInterrupt
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
            
            self.get_screen()# 从全屏截屏中裁剪得到游戏窗口截屏
            # self.click_target('imgs/fail.jpg',0.9,True) # 如果需要输出某张图片在游戏窗口中的坐标，可以用这个
            res = self.normal()
            # 未匹配到图片，降低匹配阈值，若一直无法匹配则乱点
            if res == 0:
                if time.time()-self.in_battle>7:
                    if time.time()-self.in_battle>90 and self.in_battle>0:
                        key_mouse_manager.press('esc')
                        time.sleep(1)
                        self.in_battle = time.time() - 84 * fp
                        fp = not fp
                        continue
                    if self.click_text(['点击空白','开始游戏'],click=False,warning=False):
                        key_mouse_manager.click(0.2062, 0.1554)
                        time.sleep(0.5)
                    if self.ts.nothing:
                        self.in_battle = time.time()
                    if time.time()-self.confirm_time>4:
                        if self.threshold == 0.97 and fail_cnt==0:
                            CUS_LOGGER.info("匹配不到任何图标")
                            fail_time = time.time()
                        else:
                            time.sleep(0.8)
                        if self.threshold > 0.95:
                            self.threshold -= 0.015
                        elif time.time()-fail_time>7.5:
                            time.sleep(0.15)
                            if fail_cnt <= 1:
                                key_mouse_manager.click(0.5000, 0.1454)
                                fail_cnt += 1
                            else:
                                key_mouse_manager.click(0.2062, 0.2054)
                                fail_cnt = 0
                                fail_time = time.time()
                            time.sleep(0.35)
                            self.threshold = 0.97
                else:
                    time.sleep(0.75)
            # 匹配到图片 res=1时等待一段时间
            else:
                fail_cnt = 0
                self.threshold = 0.97
                fail_time = time.time()
            time.sleep(0.1)
        CUS_LOGGER.info("停止运行")

    def end_of_university(self):
        self.update_count(False)
        self.my_cnt += 1
        tm = int((time.time() - self.init_time) / 60)
        remain_round = self.nums-self.my_cnt
        if remain_round > 0:
            remain = int(remain_round * (time.time() - self.init_time) / self.my_cnt / 60)
        else:
            remain = 0
            remain_round = -1
        CUS_LOGGER.info(f"已完成计数:{self.count} 剩余:{remain_round} 已使用：{tm // 60}小时{tm % 60}分钟  平均{tm // self.my_cnt}分钟一次  预计剩余{remain // 60}小时{remain % 60}分钟")
        if self.debug == 0 and self.check_bonus == 0 and self.my_cnt >= self.nums >= 0:
            CUS_LOGGER.info('已完成上限，准备停止运行')
            self.end = 1
        self.floor = 0

    def normal(self):
        # self.lst_changed：最后一次交互时间，长时间无交互则暂离
        bk_lst_changed = self.lst_changed
        self.lst_changed = time.time()
        self.ts.forward(self.get_screen())
        res,state = self.run_static()
        if res!='':
            return state
        if self.is_run():
            CUS_LOGGER.info("开始匹配地图")
            #检查黄泉
            if not self.quan and self.check("huangquan", 0.0578,0.7083):
                self.quan = 1
            if not self.bai_e and self.check("bai_e", 0.0625,0.7092):
                self.bai_e = 1
            #长时间离开或者未初始化层数？则重新初始化
            if self.floor_init == 0:
                CUS_LOGGER.info("开始重新初始化层数")
                old_floor = self.floor
                if self.get_level() == -1:
                    if old_floor != self.floor:
                        self.map_init = True
                    self.first_get_floor=True
                    return 1
                self.floor_init = 1
            #上次交互时间
            self.lst_changed = bk_lst_changed
            # self.battle：最后一次处于战斗状态的时间，0表示处于非战斗状态
            self.in_battle = 0
            # 刚进图，初始化一些数据
            if self.big_map_c == 0:
                key_mouse_manager.keyUp("w")
                # 黑屏检测
                while 1:
                    men = np.mean(self.get_screen())
                    if men > 12:
                        break
                    time.sleep(0.1)
                    if self._stop:
                        return 1
                if self._stop:
                    return 1
                self.big_map_c = 1
                # 寻路模式，匹配最接近的地图
                if self.find:
                    now_time = time.time()
                    self.now_map_sim = -1
                    self.now_map = -1
                    #只有第一，第六层才寻找匹配的地图
                    if self.click_text(text="战斗", click=False, box=[55, 164, 12, 40],ocr_line=False):
                        if self.first_get_floor:
                            self.first_get_floor = False
                        else:
                            self.map_init = False
                            old_floor=self.floor
                            self.get_level()
                            if old_floor != self.floor:
                                self.map_init = True
                        CUS_LOGGER.debug(f"检查当前层数：{self.floor}，初始化状态{self.map_init}")
                        if self.floor in [0, 5]:
                            self.map_init = False
                            self.mini_state = 0
                            self.stop_move = 0
                            no_find=False
                            while True:
                                self.exist_minimap()
                                now_map, now_map_sim = self.match_scr(self.loc_scr)
                                if self.now_map_sim < now_map_sim:
                                    self.now_map, self.now_map_sim = now_map, now_map_sim
                                # 地图匹配超时或找到相似匹配
                                if (
                                    (self.now_map_sim > 0.85 or time.time() - now_time > 2.5)
                                    and self.now_map_sim != -1
                                ) or self._stop:
                                    break
                                time.sleep(0.3)
                            CUS_LOGGER.info(f"地图编号：{self.now_map}  相似度：{self.now_map_sim}")
                            self.find=True
                            if self.now_map_sim < 0.35 :
                                CUS_LOGGER.warning(f"相似度过低,疑似未找到匹配地图,当前层数{self.floor + 1},匹配地图{self.now_map}")
                                if self.debug==2:
                                    time.sleep(10000)
                                self.find=False
                                self.init_map()
                                no_find=True
                                return 1
                            if "m" in self.now_map:
                                CUS_LOGGER.warning(f"未完成的地图{self.now_map}")
                                self.find = False
                                return 1
                            if not no_find:
                                self.now_pth = "resource/imgs/maps/" + self.now_map + "/"
                                files = find_latest_modified_file(self.now_pth)
                                self.big_map = cv.imread(files, cv.IMREAD_GRAYSCALE)
                                self.debug_map = deepcopy(self.big_map)
                                #从文件名获取初始坐标
                                xy = files.split("/")[-1].split("_")[1:3]
                                self.now_loc = (4096 - int(xy[0]), 4096 - int(xy[1]))
                                #获取目标路径
                                self.target = self.get_target(self.now_pth + "target.jpg")
                                self.get_screen()
                                # shape = (int(self.scx * 190), int(self.scx * 190))
                                self.rotation,d=update_minimap_data(self.screen,rotation=0,direction=0)
                                self.init_ang = 270 + d
                                CUS_LOGGER.info("已从地图获取目标路径点%s" % self.target)
                        else:
                            self.update_debug_map()
                    else:
                        self.update_debug_map()
                    if self._stop:
                        return 1
                    if self.consumable and (self.check_bonus or self.count<34) and self.floor in [3, 7, 12][-self.consumable:]:
                        self.use_consumable(1, 1)
                    key_mouse_manager.press("1")
                # 录制模式，保存初始小地图
                if not self.find:
                    CUS_LOGGER.warning("未找到匹配地图")
                    time.sleep(3)
                    self.mini_state = 0
                    self.exist_minimap()
                    cv.imwrite(self.map_file + "init.jpg", self.loc_scr)
            self.get_screen()
            # if time.time() - self.lst_tm > 5 and self.mini_state == 0 and self.floor not in [0, 5]:
            if time.time() - self.lst_tm > 5 and self.mini_state == 0:
                if self.find == 0:
                    key_mouse_manager.press("s", 0.5)
                    if self._stop == 0:
                        key_mouse_manager.keyDown("w")
                    time.sleep(0.5)
                    self.get_screen()
                    pass
            self.lst_tm = time.time()
            
            self.must_end |= self.floor >= 4 and self.debug == 2
            # 长时间未交互/战斗，暂离或重开
            if ((time.time() - self.lst_changed >= 37 - 4 * self.debug + 8 * self.slow) and self.find == 1)or (self.floor == 12 and self.mini_state > 4)or self.must_end:
                time.sleep(2.5)
                key_mouse_manager.press("esc")
                time.sleep(2)
                self.init_map()
                self.floor_init = 0
                if self.floor == 12 or self.must_end:
                    self.end_of_university()
                    key_mouse_manager.click(0.2708, 0.1324)
                    time.sleep(1)
                    CUS_LOGGER.info(f"通关！当前层数:{self.floor + 1}")
                elif self.debug == 2:
                    CUS_LOGGER.error(f"地图{self.now_map}出现问题,退出程序")
                    CUS_LOGGER.info('地图错误')
                    self._stop = 1
                elif self.fail_count <= 1:
                    CUS_LOGGER.error(f"地图{self.now_map}未发现目标，当前层数:{self.floor + 1},相似度{self.now_map_sim}，尝试暂离")
                    key_mouse_manager.click(0.2708, 0.2324)
                    key_mouse_manager.keyUp("w")
                    self.re_enter()
                    self.re_align += 1
                    self.fail_count += 1
                else:
                    self.multi = 1.01
                    if self.debug == 0:
                        self.floor = 0
                        key_mouse_manager.click(0.2708, 0.1324)
                        CUS_LOGGER.error(
                            f"地图{self.now_map}未发现目标,相似度{self.now_map_sim}，当前层数:{self.floor+1},尝试退出重进"
                        )
                        self.fail_count = 0
                    else:
                        self.re_align += 1
                        CUS_LOGGER.error(
                            f"地图{self.now_map}未发现目标,相似度{self.now_map_sim}，尝试暂离 DEBUG"
                        )
                        key_mouse_manager.click(0.2708, 0.2324)
                        self.re_enter()
                self.lst_changed = time.time()
                return 1
            # if self.multi == 1.01:
            #     align_angle_main(0, [1], self)
            self.get_screen()
            if self.floor > 0 and self.check("ruan",0.0625,0.7065,threshold=0.95) and not self.check("U", 0.0240,0.7759) and not (self.floor==12 and self.mini_state>1):
                key_mouse_manager.press('e')
                time.sleep(1.5)
                if self.click_text(text="快速恢复",box=[864, 1058, 224, 318],click=False,ocr_line=False,warning=False):
                    self.solve_snack()
            # 寻路
            CUS_LOGGER.info("开始寻路")
            if self._stop:
                return 1
            if self.mini_state:
                #无先验寻路
                self.get_direc_only_minimap()
            else:
                #有先验寻路
                self.get_direct_with_big_map()
            return 2
        else:
            return 0

    def auto_battle(self):
        # 需要打开自动战斗
        if self.check("c", 0.988, 0.1028, threshold=0.985):
            key_mouse_manager.press("v")
        if time.time() - self.f_time < 20:
            self.f_time = 0
            self.floor -= 1
            self.restore_map()
        if self.fate == "丰饶":
            if random.randint(0, 6) == 3:
                key_mouse_manager.press("r")
        # self.battle：最后一次处于战斗状态的时间，0表示处于非战斗状态
        self.in_battle = time.time()
        return 1
    # 祝福界面/回响界面 （放在一起处理了）
    def choose_bless(self):
        time.sleep(0.3)
        chose = 0
        self.in_battle = 0
        if self.click_text(text="重置祝福",box=[1268, 1444, 929, 1025],click=False,warning=False):
            for _ in range(14):
                img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask", fresh=True)
                if (
                        self.ts.split_and_find(self.tk.fates, img_down, mode="bless")[1]
                        or self._stop
                ):
                    time.sleep(0.2)
                    break
                if not self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False):
                    return 1
                time.sleep(0.2)
            img_up = self.get_small_interaction_img(x=0.5047, y=0.5491, mask="mask_bless", fresh=True)
            res_up = self.ts.split_and_find(self.tk.prior_bless, img_up, mode="bless_skip=self.tk.skip")
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
        # 未匹配到优先祝福，刷新祝福并再次匹配
        if not chose:
            for _ in range(8):
                img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask", fresh=True)
                if self.ts.split_and_find(self.tk.fates, img_down)[1] or self._stop:
                    time.sleep(0.2)
                    break
                if not self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False):
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
            time.sleep(0.4)
        key_mouse_manager.click(0.1203, 0.1093)
        tm = time.time()
        while time.time() - tm < 1.6 and self.click_text(text="选择祝福",box=[60, 222, 0, 113],click=False,ocr_line=False,warning=False):
            time.sleep(0.1)
        self.confirm_time = time.time()
        if self.quan:
            self.use_e()
        return 1
    # F交互界面
    def do_interaction(self):
        # is_killed：是否是禁用交互（沉浸奖励、复活装置、下载装置）
        is_killed = 0
        time.sleep(0.4)
        if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96, fresh=True):
            for _ in range(4):
                img = self.get_small_interaction_img(x=0.3181, y=0.4324, mask="mask_f")
                text = self.ts.similar_list(self.tk.interacts, img)
                if text is None:
                    img = self.get_small_interaction_img(x=0.3365, y=0.4231, mask="mask_f")
                    text = self.ts.similar_list(self.tk.interacts, img)
                if text is not None:
                    break
                time.sleep(0.3)
                self.get_screen()
            # 黑塔
            if self.ts.similar("黑塔"):
                # 与黑塔交互后30秒内禁止再次交互（防止死循环）
                if time.time() - self.quit > 30 and self.floor:
                    self.quit = time.time()
                    key_mouse_manager.press('f', force=True)
                    self.in_battle = 0
                else:
                    is_killed = 1
            else:
                # tele：区域-xx  exit：离开模拟宇宙
                if self.ts.similar("区域"):
                    CUS_LOGGER.info(f"识别到传送点")
                    key_mouse_manager.press('f', force=True)
                    return self.nof()
                elif self.re_align == 1 and self.debug == 0:
                    # align_angle(10, 1)
                    # self.multi = config.multi
                    self.re_align += 1
                is_killed = text in ["沉浸", "紧锁", "复活", "下载"]
                if is_killed == 0:
                    key_mouse_manager.press('f', force=True)
                self.in_battle = 0
            if is_killed == 0:
                return 1
    # 跑图状态
    def re_init(self):
        if self.end:
            time.sleep(1)
            key_mouse_manager.press('esc')
            self._stop = 1
            CUS_LOGGER.info('已退出模拟宇宙，自动化结束')
            return 1
        time.sleep(2)
        key_mouse_manager.click(0.3448, 0.4926)
        time.sleep(1)
        self.init_map()
    def begin_universe(self):
        con = self.click_text(text="继续进度",box=[1610, 1762, 937, 1023],click=False,ocr_line=False,warning=False)
        if not con:
            if self.diffi == 5:
                key_mouse_manager.click(0.9375, 0.5565)
                time.sleep(0.2)
            key_mouse_manager.click(0.9375, 0.8565 - 0.1 * (self.diffi - 1))
        key_mouse_manager.click(0.1083, 0.1009)
        if con:
            CUS_LOGGER.info(f"继续游戏附带初始化层数,更新前{self.floor + 1}")
            old_floor = self.floor
            self.get_level()
            if old_floor != self.floor:
                CUS_LOGGER.info(f"继续游戏附带初始化层数,更新后{self.floor + 1}")
                self.map_init = True
            self.first_get_floor = True
        else:
            self.floor = 0
            self.map_init = True
        self.floor_init = 1
    def pre_start(self):
        self.fail_count = 0
        self.allow_e = 1
        if self.check("team4", 0.5797, 0.2389):
            dx = 0.9266 - 0.8552
            dy = 0.8194 - 0.6741
            for i in self.order:
                key_mouse_manager.click(
                    0.9266 - dx * ((i - 1) % 3), 0.8194 - dy * ((i - 1) // 3)
                )
                time.sleep(0.3)
        key_mouse_manager.click(0.1635, 0.1056)
    def confirm_fate(self):
        key_mouse_manager.click(0.1182, 0.0926)
        self.confirm_time = time.time()
    def select_fate(self):
        time.sleep(0.6)
        click_x = [0.02, 0.98]
        n = 4  # 重试次数
        res = None
        while n:
            img = self.get_small_interaction_img(x=0.4969, y=0.3750, mask="mask_fate", fresh=True)
            res = self.ts.split_and_find([self.fate], img)
            if res[1] == 1 and n:
                # 没有找到命途
                CUS_LOGGER.info(f"未找到 {self.fate} 命途，尝试翻页")
                key_mouse_manager.click(click_x[n % len(click_x)], 0.5)
                n -= 1
                time.sleep(0.5)
                continue
            else:
                break
        key_mouse_manager.click(*self.calc_point((0.4969, 0.3750), res[0]))
    def select_bless(self):
        if not self.click_text(['2星祝福', '奇物']):
            key_mouse_manager.click(0.5047, 0.4917)
        key_mouse_manager.click(0.5062, 0.1065)
        time.sleep(1)
    # 事件界面
    def select_event(self):
        # 事件界面：选择
        if self.check("arrow", 0.1828, 0.5000, mask="mask_event"):
            key_mouse_manager.click(self.tx, self.ty)
        # 事件界面：退出
        elif self.check("arrow_1", 0.1828, 0.5000, mask="mask_event"):
            key_mouse_manager.click(self.tx, self.ty)
        # 事件选择界面
        elif self.check("star", 0.1828, 0.5000, mask="mask_event", threshold=0.965):
            tx, ty = self.tx, self.ty
            try:
                import yaml
                with open("config/config/info.yml", "r", encoding="utf-8", errors="ignore") as f:
                    event_prior = yaml.safe_load(f)["prior"]["事件"]
            except:
                event_prior = [
                    '购买一个',
                    '丢下雕像',
                    '和序列扑满玩',
                    '信仰星神',
                    '克里珀的恩赐',
                    '哈克的藏品',
                    '动作片',
                    '感恩克里珀星神',
                    '换取1个星祝福',
                    '星神的记载',
                    '翻开牌',
                    '摧毁黑匣',
                    '1个1星祝福',
                    '1个1-星祝福',
                    '选择里奥'
                ]
            event_prior = [self.fate] + event_prior
            success = self.click_text(event_prior)
            time.sleep(1)
            self.get_screen()
            if success and self.check("confirm", 0.1828, 0.5000, mask="mask_event", threshold=0.965):
                key_mouse_manager.click(self.tx, self.ty)
            elif self.click_text(text="休息区",box=[187, 289, 903, 941],click=False,warning=False):
                key_mouse_manager.click(0.1667, 0.2592)
            else:
                key_mouse_manager.click(tx, ty)
                time.sleep(0.3)
                key_mouse_manager.click(0.1167, ty - 0.1139)
            time.sleep(0.5)
            for _ in range(7):
                if not self.click_text(text="事件",box=[6, 196, 0, 102],click=False,ocr_line=False,warning=False):
                    break
                time.sleep(0.1)
            self.lst_changed = time.time()
        else:
            key_mouse_manager.click(0.9479, 0.9565)
    # 选取奇物
    def select_strange(self):
        time.sleep(0.6)
        img = self.get_small_interaction_img(x=0.5000, y=0.7333, mask="mask_strange", fresh=True)
        res = self.ts.split_and_find(self.tk.strange, img, mode="strange")
        key_mouse_manager.click(*self.calc_point((0.5000, 0.7333), res[0]))
        key_mouse_manager.click(0.1365, 0.1093)
        self.wait_flag(lambda: self.click_text(text="选择奇物",box=[5, 219, 3, 111],click=False,ocr_line=False,warning=False), 1.4)
    # 丢弃奇物
    def drop_strange(self):
        key_mouse_manager.click(0.4714, 0.5500)
        key_mouse_manager.click(0.1339, 0.1028)
        self.wait_flag(lambda: self.click_text(text="丢弃奇物",box=[10, 220, 0, 112],click=False,ocr_line=False,warning=False), 1.4)
    def drop_bless(self):
        time.sleep(1.5)
        st = set(self.tk.fates) - set(self.tk.secondary)
        clicked = 0
        for i, ft in enumerate(self.tk.secondary[::-1]):
            if ft != self.fate or i == len(self.tk.secondary):
                img_down = self.get_small_interaction_img(x=0.5042, y=0.3204, mask="mask", fresh=True)
                if self.debug == 2:
                    print(list(st), self.tk.secondary)
                res_down = self.ts.split_and_find(list(st), img_down, mode="bless")
                if res_down[1] == 2:
                    key_mouse_manager.click(*self.calc_point((0.5042, 0.3204), res_down[0]))
                    clicked = 1
                    break
                st.add(ft)
        if not clicked:
            key_mouse_manager.click(0.4714, 0.5500)
        time.sleep(0.5)
        key_mouse_manager.click(0.1203, 0.1093)
        self.confirm_time = time.time()
    def setting(self):
        key_mouse_manager.click(0.2708, 0.2324)
        self.re_enter()
    def enhance(self):
        self.quit = time.time()
        time.sleep(1.5)
        for i in [None, (0.7984, 0.6824), (0.6859, 0.6824)]:
            if self.check("enhance_fail", 0.1068, 0.0907, fresh=True):
                break
            if i is not None:
                key_mouse_manager.click(i[0], i[1])
                time.sleep(0.3)
            key_mouse_manager.click(0.1089, 0.0926)
            time.sleep(0.3)
            tm = time.time()
            while not self.click_text(text="祝福强化",box=[70, 236, 9, 125],click=False,ocr_line=False,warning=False) and time.time() - tm < 7:
                key_mouse_manager.click(0.2062, 0.2054)
                time.sleep(0.3)
        key_mouse_manager.press("esc")
        key_mouse_manager.press("w", 2)
        tm = time.time()
        while time.time() - tm < 2 and not self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,
                                                      fresh=True) and not self.is_run():
            time.sleep(0.15)
        # time.sleep(0.35)
        # self.mouse_move(-30)
        self.confirm_time = time.time()
        self.lst_changed = time.time()
        if self.floor >= 12:
            self.floor = 11
    def confirm_yes(self):
        if self.click_text(text="确认",click=False):
            key_mouse_manager.click(self.tx, self.ty)
        time.sleep(1)
        return 0

    def update_count(self, read=True):
        """
        更新或读取计数器值
        
        该函数用于管理模拟宇宙的运行计数，可以读取保存在文件中的计数器值，
        或将当前计数器值加1后保存到文件中。
        
        参数:
            read: bool，控制操作模式
                  True表示读取模式，从文件中读取计数器值
                  False表示写入模式，将当前计数器值加1后保存到文件中
                  
        返回值:
            无返回值，直接更新实例变量self.count
        """
        file_name = "config/backup/count.txt"
        if read:
            new_cnt = 0
            if os.path.exists(file_name):
                with open(file_name, "r", encoding="utf-8", errors="ignore") as fh:
                    s = fh.readlines()
                    try:
                        new_cnt = int(s[0].strip("\n"))
                    except:
                        pass
            else:
                os.makedirs("config/backup", exist_ok=True)
                with open(file_name, "w", encoding="utf-8") as file:
                    file.write("0")
                    file.close()
        else:
            new_cnt = self.count + 1
        self.count = new_cnt

    def del_pt(self, img, A, S, f):
        """
        递归删除图像中的连接点
        
        该函数通过递归方式删除图像中与起始点相连的像素点，用于清理图像中的特定区域。
        删除条件包括超出边界、像素值为黑色、不满足特定函数条件且距离起始点较远等情况。
        
        参数:
            img: 图像数组，要处理的图像数据
            A: tuple，当前处理的像素点坐标 (row, col)
            S: tuple，起始点坐标 (row, col)
            f: function，判断像素点是否符合条件的函数
            
        返回值:
            无返回值
        """
        if (
            A[0] < 0
            or A[1] < 0
            or A[0] >= img.shape[0]
            or A[1] >= img.shape[1]
            or (img[A] == [0, 0, 0]).all()
            or (not f(img[A]) and get_dis(A, S) > 5)
            or get_dis(A, S) > 10
        ):
            return
        else:
            img[A] = [0, 0, 0]
        for dx, dy in [(0, -1), (0, 1), (1, 0), (-1, 0)]:
            self.del_pt(img, (A[0] + dx, A[1] + dy), S, f)

    def get_target(self, pth):
        """
        根据地图获取目标路径点位及类型
        """
        img = cv.imread(pth)
        res = set()
        f_set = [
            lambda p: p[2] < 85 and p[1] < 85 and p[0] > 180,  # 路径点 蓝
            lambda p: p[2] > 180 and p[1] < 70 and p[0] < 70,  # 怪 红
            lambda p: p[2] < 90 and p[1] > 150 and p[0] < 90,  # 交互点 绿
            lambda p: p[2] > 180 and p[1] > 180 and p[0] < 70,  # 终点 黄
        ]
        for i in range(img.shape[0]):
            for j in range(img.shape[1]):
                for k in range(4):
                    if f_set[k](img[i, j]):
                        p = get_center(img, i, j)
                        #记录坐标，类型，坐标取整
                        res.add((p, k))
                        p = (int(p[0]), int(p[1]))
                        #引用传递，会影响img源图像
                        self.del_pt(img, p, p, f_set[k])
                        if k == 3:
                            #记录终点
                            self.last = p
        if self.speed:
            dis = 1000000
            pt = None
            #找到终点
            for i in res:
                if i[1] == 1 and get_dis(i[0], self.last) < dis:
                    dis = get_dis(i[0], self.last)
                    pt = i
            #将除了终点外的所有路径点改为类型0
            for i in deepcopy(res):
                if i[1] == 1 and pt != i:
                    res.remove(i)
                    res.add((i[0], 0))
        return res


    
    def restore_map(self):
        """
        从磁盘文件恢复地图数据
        
        从磁盘文件中读取并恢复之前备份的地图数据和相关属性，包括：
        1. 从PNG图像文件恢复地图图像数据(big_map)
        2. 从JSON文件恢复其他地图相关属性
        
        备份文件从项目目录下的config/backup文件夹中读取。
        """
        try:
            backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "backup")
            
            # 从磁盘读取 big_map 图像文件
            backup_file = os.path.join(backup_dir, "big_map_backup.png")
            if os.path.exists(backup_file):
                self.big_map = cv.imread(backup_file, cv.IMREAD_GRAYSCALE)
                
            # 从磁盘读取其他属性
            attrs_file = os.path.join(backup_dir, "map_attrs_backup.json")
            if os.path.exists(attrs_file):
                with open(attrs_file, 'r') as f:
                    backup_data = json.load(f)
                    
                self.big_map_c = backup_data.get('big_map_c', self.big_map_c)
                self.lst_tm = backup_data.get('lst_tm', self.lst_tm)
                self.now_loc = tuple(backup_data.get('now_loc', self.now_loc))
                self.mini_state = backup_data.get('mini_state', self.mini_state)
                self.ang_off = backup_data.get('ang_off', self.ang_off)
                self.ang_neg = backup_data.get('ang_neg', self.ang_neg)
                self.first_mini = backup_data.get('first_mini', self.first_mini)
        except:
            pass

    def re_enter(self):
        """
        重新进入游戏场景
        
        当检测到需要重新进入当前场景时调用此函数，通过连续按下'f'键
        来完成重新进入操作。通常用于处理角色卡住或其他需要重新加载场景的情况。
        
        函数会在10秒内持续检测特定画面元素，一旦检测到就执行三次'f'键按下操作，
        每次按下间隔0.5秒，然后退出函数。
        """
        tm = time.time()
        while time.time() - tm < 10:
            self.get_screen()
            if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
                key_mouse_manager.press('f')
                time.sleep(0.5)
                key_mouse_manager.press('f')
                time.sleep(0.5)
                key_mouse_manager.press('f')
                break



    def goto_herta_office(self):
        """
        前往黑塔办公室
        
        该函数负责自动导航到黑塔办公室，主要流程包括：
        1. 检查是否已经在办公室内
        2. 如果不在办公室，则通过地图导航到黑塔办公室
        3. 进行传送操作并移动到最终目的地
        
        函数会利用一系列图像识别和文本识别来确定当前位置，
        并执行相应的点击、拖拽和键盘操作来完成导航。
        """

        if self.click_text(text="模拟宇宙",box=[1231, 1360, 595, 631],click=False,allow_fail= True):
            CUS_LOGGER.info("已在办公室，打开模拟宇宙")
            key_mouse_manager.press('f')
            return
        CUS_LOGGER.info("前往黑塔办公室")
        # if self.check("smartphone", 0.9833, 0.9380, threshold=0.95, fresh=True):
        #     key_mouse_manager.press('f4')
        #     self.click_target('resource/imgs/universe.jpg', threshold=0.9, click=True)
        #     self.click_text(text="模拟宇宙",box=[292, 419, 448, 481])
        #     key_mouse_manager.drag(0.4521,0.2,0.4521,0.9)
        #     key_mouse_manager.drag(0.4521,0.2,0.4521,0.9)
        #     key_mouse_manager.drag(0.4521,0.2,0.4521,0.9)
        #     key_mouse_manager.wait()
        #     self.click_text(text="传送",box=[1513, 1567, 814, 844])#寰宇蝗灾[1515, 1567, 351, 382]
        if self.check("smartphone", 0.9833,0.9380, threshold=0.95,fresh=True):
            CUS_LOGGER.info("打开地图")
            key_mouse_manager.press('m')
            while not self.click_text(text="星轨航图",delay=1,after_delay=0.5,box=[1625, 1732, 143, 176]):
                time.sleep(0.5)
            #拖拽地图到最左
            key_mouse_manager.drag(0.8521,0.5620,0.1521,0.5620)
            key_mouse_manager.drag(0.8521,0.5620,0.1521,0.5620)
            while not self.click_text(text="空间站",delay=3,ocr_line=False,box=[419, 583, 600, 800]):
                time.sleep(0.5)
            while not self.click_text(text="主控舱段",delay=1,after_delay=1,box=[1456, 1600, 338, 367]):
                time.sleep(0.5)
            key_mouse_manager.scroll(-10)#放大地图
            key_mouse_manager.drag(0.5,0.1520,0.5,0.8620)
            key_mouse_manager.drag(0.5,0.1520,0.5,0.8620)
            key_mouse_manager.sleep(0.5)
            while not self.check("herta_office", 0.7740,0.2824, threshold=0.95,fresh=True):
                time.sleep(0.5)
            key_mouse_manager.click(0.7740,0.2824)
            while not self.click_text(text="黑塔的办公室",delay=0.5,after_delay=0.5,box=[844, 998, 739, 768]):
                time.sleep(0.5)
            while not self.click_text(text="传送",box=[1623, 1687, 951, 990],after_delay=0.5):
                time.sleep(0.5)
            while not self.click_text(text="黑塔的办公室",box=[55, 187, 11, 42],click=False,allow_fail= True):
                time.sleep(0.5)
            time.sleep(2)
            key_mouse_manager.mouse_move(15)
            key_mouse_manager.keyDown("w")
            sprint()
            key_mouse_manager.sleep(4)
            key_mouse_manager.keyUp("w")

    def run_static(self, json_path=None, json_file=None, action_list=[], skip_check=0) -> (str,int):
        """
        执行静态动作配置文件中的动作
        
        根据提供的JSON配置文件或路径，查找并执行匹配的动作。
        支持基于文本或图像的触发条件，一旦匹配成功即执行相应动作序列。
        
        参数:
            json_path: JSON配置文件路径，如果提供则加载该文件
            json_file: 已加载的JSON配置对象，优先级高于json_path
            action_list: 指定要执行的动作列表，为空则执行所有动作
            skip_check: 是否跳过触发条件检查，1表示跳过，0表示不跳过
            
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
        for j in action_list if len(action_list) else json_file:
            for i in json_file[j]:
                trigger = i["trigger"]
                #获取指定范围的文字
                if trigger.get("text", None):
                    text = self.ts.find_with_box(trigger["box"], redundancy=trigger.get("redundancy", 30))
                    #强制跳过或者检查是否存在子串
                    if skip_check or (len(text) and trigger["text"] in merge_text(text)):
                        CUS_LOGGER.info(f"触发文本 {i['name']}:{trigger['text']}")
                        for j in i["actions"]:
                            self.do_action(j)
                        self.action_history.append(i["name"])
                        #记录最近10个动作
                        self.action_history = self.action_history[-10:]
                        #返回触发的名字
                        return i['name'],1
                elif trigger.get("photo", None):
                    if self.check(trigger["photo"], trigger["pos"]["x"], trigger["pos"]["y"], mask=trigger.get("mask", None), threshold=trigger.get("threshold", None)):
                        CUS_LOGGER.info(f"触发图像 {i['name']}:{trigger['photo']}")
                        for j in i["actions"]:
                            resu=self.do_action(j)
                        if resu is None:
                            resu=0
                        self.action_history.append(i["name"])
                        #记录最近10个动作
                        self.action_history = self.action_history[-10:]
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
                    CUS_LOGGER.info(f"点击 {action['text']}:{i['box']}")
                    self.click_box(i["box"])
                    return 1
        elif "position" in action:
            CUS_LOGGER.info(f"点击 {action['position']}")
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
        return 0
    def show_map(self):
        """
        实时显示模拟宇宙地图的可视化窗口
        
        该方法在一个独立线程中运行，创建一个OpenCV窗口用于显示当前游戏地图，
        并实时更新玩家位置、目标位置和朝向等信息。主要包括以下功能：
        1. 创建可缩放且不自动聚焦的OpenCV窗口
        2. 监控角色位置、目标位置和朝向等状态变化，仅在有更新时重绘地图
        3. 在地图上绘制当前位置（绿色）、目标位置（根据类型着色）及朝向箭头
        4. 显示当前角度和目标坐标，并通过颜色变化提示角度更新时间
        5. 放大地图图像并维持合理刷新率，按'q'键退出
        
        注意：该方法应在单独的线程中调用，不应直接调用
        """
        try:
            # 创建窗口时使用 WINDOW_FREERATIO 标志以避免自动获取焦点
            cv.namedWindow("Map", cv.WINDOW_FREERATIO | cv.WINDOW_NORMAL)
            # 设置窗口初始大小
            cv.resizeWindow("Map", 200, 600)
            cv.startWindowThread()
            angle_history = []
            last_angle_change_time = 0
        
            # 缓存上一次的状态，避免不必要的重绘
            last_real_loc = None
            last_target_loc = None
            last_target_type = None
            last_ang = None

            while not self._stop:
                if self.debug_map.shape[0] == 8192:
                    # 使用cv.pollKey()替代cv.waitKey()以避免阻塞
                    key = cv.pollKey()
                    if key == ord('q'):
                        break
                    time.sleep(0.1)  # 短暂休眠避免CPU占用过高
                    continue

                # 检查是否有变化，如果没有变化则跳过更新
                current_real_loc = (int(self.real_loc[0]), int(self.real_loc[1]))
                current_target_loc = (int(self.target_loc[0]), int(self.target_loc[1]))
                current_target_type = getattr(self, 'target_type', None)
                current_ang = getattr(self, 'ang', None)

                # 如果没有重要变化，则短暂等待后继续
                if (last_real_loc == current_real_loc and
                    last_target_loc == current_target_loc and
                    last_target_type == current_target_type and
                    last_ang == current_ang):
                    # 使用cv.pollKey()替代cv.waitKey()以避免阻塞
                    key = cv.pollKey()
                    if key == ord('q'):
                        break
                    time.sleep(0.1)  # 短暂休眠避免CPU占用过高
                    continue

                # 更新缓存值
                last_real_loc = current_real_loc
                last_target_loc = current_target_loc
                last_target_type = current_target_type
                last_ang = current_ang

                # 只在需要时才拷贝图像
                updated_image = self.debug_map.copy()
                # 初始化坐标偏移量
                x_offset = 0
                y_offset = 0
                # 检查是否存在tmp地图，如果有则与原始地图拼接
                if hasattr(self, 'tmp_map') and self.tmp_map is not None:
                    try:
                        # 确保tmp_map和debug_map都是彩色图像以进行拼接
                        if len(updated_image.shape) == 2:
                            updated_image = cv.cvtColor(updated_image, cv.COLOR_GRAY2RGB)
                        
                        tmp_map_to_use = self.tmp_map
                        # 确保tmp_map也是彩色图像
                        if len(tmp_map_to_use.shape) == 2:
                            tmp_colored = cv.cvtColor(tmp_map_to_use, cv.COLOR_GRAY2RGB)
                        else:
                            tmp_colored = tmp_map_to_use
                        
                        # 调整图像尺寸以匹配垂直拼接的宽度
                        max_width = max(updated_image.shape[1], tmp_colored.shape[1])

                        # 调整两个图像的宽度以匹配最大宽度
                        if updated_image.shape[1] < max_width:
                            # 为updated_image添加右侧填充
                            width_diff = max_width - updated_image.shape[1]
                            left_pad = width_diff // 2
                            right_pad = width_diff - left_pad
                            updated_image = np.pad(updated_image, ((0, 0), (left_pad, right_pad), (0, 0)), mode='constant', constant_values=0)
                            x_offset = left_pad  # 更新x方向偏移量
                        
                        if tmp_colored.shape[1] < max_width:
                            # 为tmp_colored添加右侧填充
                            width_diff = max_width - tmp_colored.shape[1]
                            left_pad = width_diff // 2
                            right_pad = width_diff - left_pad
                            tmp_colored = np.pad(tmp_colored, ((0, 0), (left_pad, right_pad), (0, 0)), mode='constant', constant_values=0)
                            if x_offset == 0:  # 如果updated_image没有偏移，则使用tmp_colored的偏移
                                x_offset = left_pad
                        
                        # 在正常地图上方添加间距
                        top_spacing = 10  # 上方间距像素
                        top_spacing_img = np.zeros((top_spacing, max_width, 3), dtype=np.uint8)
                        y_offset = top_spacing  # 上方间距
                        # 在两个图像之间添加一些间距
                        middle_spacing = 10  # 间距像素
                        middle_spacing_img = np.zeros((middle_spacing, max_width, 3), dtype=np.uint8)
                        
                        # 垂直拼接：上方间距 + 正常地图 + 中间间距 + tmp地图
                        updated_image = np.vstack((top_spacing_img, updated_image, middle_spacing_img, tmp_colored))
                    except Exception as e:
                        # 如果拼接失败，使用原逻辑
                        try:
                            updated_image = cv.cvtColor(updated_image, cv.COLOR_GRAY2RGB)
                        except:
                            pass  # 如果转换失败，保持原图
                else:
                    # 如果没有tmp地图，使用原逻辑
                    try:
                        updated_image = cv.cvtColor(updated_image, cv.COLOR_GRAY2RGB)
                    except:
                        pass  # 如果转换失败，保持原图

                # 确保坐标值为整数类型，避免切片索引错误
                real_x, real_y = current_real_loc
                target_x, target_y = current_target_loc


                # 调整坐标以适应图像拼接后的偏移
                adjusted_real_x = real_x + y_offset
                adjusted_real_y = real_y + x_offset
                adjusted_target_x = target_x + y_offset
                adjusted_target_y = target_y + x_offset

                # 绘制当前位置（绿色）
                for dx in range(-2, 3):
                    for dy in range(-2, 3):
                        if (0 <= adjusted_real_x + dx < updated_image.shape[0] and
                            0 <= adjusted_real_y + dy < updated_image.shape[1]):
                            updated_image[adjusted_real_x + dx, adjusted_real_y + dy] = [49, 140, 49]

                # 绘制目标位置
                if current_target_type is not None:
                    color_map = {
                        0: [49, 140, 140],  # 黄色
                        1: [49, 49, 140],   # 红色
                        2: [49, 140, 49],   # 绿色
                        3: [140, 140, 49]   # 青色
                    }
                    target_color = color_map.get(current_target_type, [49, 140, 140])

                    for dx in range(-2, 3):
                        for dy in range(-2, 3):
                            if (0 <= adjusted_target_x + dx < updated_image.shape[0] and
                                0 <= adjusted_target_y + dy < updated_image.shape[1]):
                                updated_image[adjusted_target_x + dx, adjusted_target_y + dy] = target_color

                # 绘制朝向箭头
                if current_ang is not None:
                    import math
                    angle_rad = math.radians(-current_ang)
                    line_length = 20
                    end_point = (
                        int(adjusted_real_y + line_length * math.cos(angle_rad)),
                        int(adjusted_real_x - line_length * math.sin(angle_rad))
                    )

                    # 确保线条端点在图像范围内
                    if (0 <= adjusted_real_y < updated_image.shape[1] and
                        0 <= adjusted_real_x < updated_image.shape[0] and
                        0 <= end_point[0] < updated_image.shape[1] and
                        0 <= end_point[1] < updated_image.shape[0]):
                        cv.arrowedLine(
                            updated_image,
                            (adjusted_real_y, adjusted_real_x),
                            end_point,
                            (0, 255, 0),
                            1,
                            tipLength=0.4
                        )

                # 更新角度历史记录
                current_time = time.time()
                if current_ang is not None:
                    if not angle_history or angle_history[-1][1] != current_ang:
                        angle_history.append((current_time, current_ang))
                        last_angle_change_time = current_time
                    # 保留最近5秒的角度记录
                    while angle_history and current_time - angle_history[0][0] > 5:
                        angle_history.pop(0)

                # 在左上角显示角度数值
                if current_ang is not None:
                    # 计算颜色 (新变更红色，随时间推移逐渐变蓝)
                    elapsed_time = current_time - last_angle_change_time
                    if elapsed_time < 2:  # 2秒内变为蓝色
                        red = max(0, 255 * (1 - elapsed_time / 2))
                        blue = min(255, 255 * (elapsed_time / 2))
                        color = (int(blue), 0, int(red))  # BGR格式
                    else:
                        color = (255, 0, 0)  # 蓝色

                    angle_text = f"Angle: {-current_ang:.1f}"
                    cv.putText(updated_image, angle_text, (10 + x_offset, 30),
                              cv.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)

                # 在左上角显示目标坐标
                target_text = f"Target: ({target_x}, {target_y})"
                cv.putText(updated_image, target_text, (10 + x_offset, 50),
                          cv.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 255), 1)

                # 根据窗口大小调整图像尺寸以适应200x600的窗口
                img_height, img_width = updated_image.shape[:2]
                max_width, max_height = 200, 600
                
                # 计算缩放比例，保持宽高比
                scale = min(max_width / img_width, max_height / img_height)
                
                # 调整图像大小以适应窗口
                updated_image = cv.resize(
                    updated_image, None, fx=scale, fy=scale, interpolation=cv.INTER_LINEAR
                )

                cv.imshow("Map", updated_image)
                # 使用cv.pollKey()替代cv.waitKey()以避免阻塞
                key = cv.pollKey()
                if key == ord('q'):
                    break
                # 检查停止标志
                if self._stop:
                    break
        except SystemExit:
            # 捕获强制退出异常，确保窗口被关闭
            pass
        except:
            # 捕获其他异常
            pass
        finally:
            # 无论如何都要确保窗口被关闭
            try:
                CUS_LOGGER.info(f'开始销毁窗口')
                cv.destroyAllWindows()
                CUS_LOGGER.info(f'正在销毁中')
                cv.waitKey(1)
                CUS_LOGGER.info(f'完成窗口关闭')
            except Exception as e:
                CUS_LOGGER.info(f'异常关闭窗口{e}')
                pass
    def start(self):
        """
        启动模拟宇宙自动化程序
        
        该方法负责初始化并启动整个模拟宇宙运行流程，包括：
        1. 初始化运行状态
        2. 启动键盘鼠标管理器
        3. 启动地图显示线程（如果启用）
        4. 开始执行主要路线逻辑
        
        如果在执行过程中发生异常，会尝试停止运行并重新抛出异常。
        """
        self._stop = False
        key_mouse_manager.start()
        if self.record:
            self.recorder.start_recording()
        if self._show_map:
            self.map_thread = ThreadWithException(target=self.show_map,name="地图")
            self.map_thread.start()
        try:
            self.route()
        except Exception as e:
            CUS_LOGGER.info(f'异常终止进程{e}')
            if not self._stop:
                self.stop()
            # 重新抛出异常，以便上层能够捕获
            raise

    def stop(self, *_, **__):
        """
        停止模拟宇宙运行
        
        该方法负责安全地停止所有运行中的线程和操作，包括：
        1. 设置停止标志
        2. 停止键盘鼠标管理器
        3. 等待并终止地图显示线程
        
        参数:
            *_: 忽略的位置参数
            **__: 忽略的关键字参数
        """
        CUS_LOGGER.info("尝试停止运行")
        self._stop = 1
        key_mouse_manager.stop()
        if self.record:
            CUS_LOGGER.info("尝试停止录制")
            try:
                self.recorder.stop_recording()
            except Exception as e:
                CUS_LOGGER.error(f"停止录制时发生错误: {e}")
        # 等待地图线程结束
        # if self.map_thread and self.map_thread.is_alive():
        #     # 等待最多2秒让线程自行结束
        #     timeout = 2
        #     start_time = time.time()
        #     while self.map_thread.is_alive() and (time.time() - start_time) < timeout:
        #         time.sleep(0.1)
        #
        #     # 如果线程仍未结束，强制终止
        #     if self.map_thread.is_alive():
        #         import ctypes
        #         res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        #             ctypes.c_long(self.map_thread.ident),
        #             ctypes.py_object(SystemExit)
        #         )
        #         time.sleep(0.5)  # 短暂等待

        self.map_thread = None
        
        # 确保关闭地图窗口（如果存在）
        # try:
        #     # 先尝试发送q按键来关闭窗口
        #     cv.waitKey(1)  # 允许窗口消息处理
        #     cv.destroyAllWindows()  # 关闭所有OpenCV窗口
        # except:
        #     # 如果窗口不存在，可能会抛出异常，忽略即可
        #     pass
