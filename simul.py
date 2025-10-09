import threading
import traceback
import pyautogui
import cv2 as cv
import numpy as np
import time
import win32gui
import random
from copy import deepcopy

from config.Global import key_mouse_manager
from diver import load_actions, merge_text, clean_text
from utils.log import log, set_debug
from utils.simul.map_log import map_log
from utils.simul.update_map import update_map
from utils.simul.utils import UniverseUtils, set_forground, notif, sprint, get_dis
import os
from align_angle import main as align_angle
from utils.simul.config import config
import datetime
import pytz

# 版本号
version = "v6.3"


def get_hwnd_and_text():
    hwnd = win32gui.GetForegroundWindow()
    Text = win32gui.GetWindowText(hwnd)
    return hwnd,Text


class SimulatedUniverse(UniverseUtils):
    def __init__(
        self, find, debug, speed, consumable, slow, nums=-1, unlock=False, bonus=False, update=0, gui=None
    ):
        super().__init__(gui)
        log.info("当前命途：" + self.fate)
        key_mouse_manager.set_config(config)
        # 设置屏幕参数以支持坐标转换
        key_mouse_manager.set_screen_params(self.x1, self.y1, self.xx, self.yy, self.full)
        self.now_map = None
        self.now_map_sim = None
        self.real_loc = [0, 0]
        self.debug_map = np.zeros((8192, 8192), dtype=np.uint8)
        self._stop = True
        self.img_set = []
        self.find = find
        self.debug = debug
        self.speed = speed
        self.consumable = consumable
        self.slow = slow
        self._show_map = debug
        self.floor = 0
        self.count = 0
        self.count_tm = time.time()
        self.floor_tm = time.time()
        self.init_tm = time.time()
        self.my_cnt = 0
        self.re_align = 0
        self.unlock = unlock
        self.check_bonus = bonus
        self.bonus = bonus
        self.kl = 0
        self.fail_count = 0
        self.nums = nums
        self.end = 0
        self.quan = 0
        self.battle = 0
        self.quit = 0
        self.floor_init = 0
        self.confirm_time = 0
        self.threshold = 0.97
        # 添加用于计算FPS的变量
        self.last_get_screen_time = None
        self.fps_list = []
        # 添加地图线程引用
        self.map_thread = None

        self.default_json_path = "config/config/default.json"
        self.default_json = load_actions(self.default_json_path)
        self.action_history = []
        ex_notif = ""
        if debug != 2:
            pyautogui.FAILSAFE = False
        if bonus:
            ex_notif = " 自动领取沉浸奖励"
            log.info(ex_notif)
        self.update_count()
        notif("开始运行" + ex_notif, f"初始计数：{self.count}")
        set_debug(debug > 0)
        if update and find:
            update_map()
        self.lst_changed = time.time()
        log.info("加载地图")
        for file in os.listdir("resource/imgs/maps"):
            pth = "resource/imgs/maps/" + file + "/init.jpg"
            if os.path.exists(pth):
                image = cv.imread(pth)
                self.img_set.append((file, self.extract_features(image)))
                self.img_map[file]= image
        log.info("加载地图完成，共 %d 张" % len(self.img_set))

    # 初始化地图，刚进图时调用
    def init_map(self):
        self.backup_map()
        self.big_map = np.zeros((8192, 8192), dtype=np.uint8)
        self.big_map_c = 0
        self.lst_tm = 0
        self.tries = 0
        self.his_loc = (30, 30)
        self.offset = (30, 30)
        self.now_loc = (4096, 4096)
        self.mini_state = 1
        self.ang_off = 0
        self.ang_neg = 0
        self.first_mini = 1
        self.in_battle = time.time()
        self.map_file = "resource/imgs/maps/my_" + str(random.randint(0, 99999)) + "/"
        if self.find == 0 and not os.path.exists(self.map_file):
            os.mkdir(self.map_file)

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
                    log.warning(f"等待游戏窗口，当前窗口：{Text}")
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
                    if self.click_text(['点击空白','开始游戏'],click=False):
                        key_mouse_manager.click(0.2062, 0.1554)
                        time.sleep(0.5)
                    if self.ts.nothing:
                        self.in_battle = time.time()
                    if time.time()-self.confirm_time>4:
                        if self.threshold == 0.97 and fail_cnt==0:
                            log.info("匹配不到任何图标")
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
        log.info("停止运行")

    def end_of_uni(self):
        self.update_count(0)
        self.my_cnt += 1
        tm = int((time.time() - self.init_tm) / 60)
        remain_round = self.nums-self.my_cnt
        if remain_round > 0:
            remain = int(remain_round * (time.time() - self.init_tm) / self.my_cnt / 60)
        else:
            remain = 0
            remain_round = -1
        notif(
            "已完成",
            f"计数:{self.count} 剩余:{remain_round} 已使用：{tm//60}小时{tm%60}分钟  平均{tm//self.my_cnt}分钟一次  预计剩余{remain//60}小时{remain%60}分钟",
            cnt=str(self.count),
        )
        if self.debug == 0 and self.check_bonus == 0 and self.nums <= self.my_cnt and self.nums >= 0:
            log.info('已完成上限，准备停止运行')
            self.end = 1
        self.floor = 0

    def normal(self):
        # self.lst_changed：最后一次交互时间，长时间无交互则暂离
        bk_lst_changed = self.lst_changed
        self.lst_changed = time.time()
        # 战斗界面
        if self.check("c", 0.988, 0.1028, threshold=0.985) or self.check(
            "auto_2", 0.0583, 0.0769):
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
            self.battle = time.time()
            self.in_battle = time.time()
            return 1
        # 祝福界面/回响界面 （放在一起处理了）
        if self.check("choose_bless", 0.9266, 0.9491):
            time.sleep(0.3)
            chose = 0
            self.battle = 0
            if self.check("reset",0.2938,0.0954):
                for _ in range(14):
                    img_down = self.get_small_interaction_img(x=0.5042,y=0.3204,mask="mask",fresh=True)
                    if (
                        self.ts.split_and_find(self.tk.fates, img_down, mode="bless")[1]
                        or self._stop
                    ):
                        time.sleep(0.2)
                        break
                    if not self.check("choose_bless", 0.9266, 0.9491):
                        return 1
                    time.sleep(0.2)
                img_up = self.get_small_interaction_img(x=0.5047,y=0.5491,mask="mask_bless",fresh=True)
                res_up = self.ts.split_and_find(self.tk.prior_bless, img_up, bless_skip=self.tk.skip)
                img_down = self.get_small_interaction_img(x=0.5042,y=0.3204,mask="mask")
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
                    img_down = self.get_small_interaction_img(x=0.5042,y=0.3204,mask="mask",fresh=True)
                    if self.ts.split_and_find(self.tk.fates, img_down)[1] or self._stop:
                        time.sleep(0.2)
                        break
                    if not self.check("choose_bless", 0.9266, 0.9491):
                        return 1
                    time.sleep(0.2)
                img_up = self.get_small_interaction_img(x=0.5047,y=0.5491,mask="mask_bless",fresh=True)
                res_up = self.ts.split_and_find(self.tk.prior_bless, img_up,bless_skip=self.tk.skip)
                img_down = self.get_small_interaction_img(x=0.5042,y=0.3204,mask="mask")
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
            tm=time.time()
            while time.time()-tm<1.6 and self.check("choose_bless", 0.9266, 0.9491,fresh=True):
                time.sleep(0.1)
            self.confirm_time = time.time()
            if self.quan:
                self.use_e()
            return 1
        # F交互界面
        elif self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96):
            # is_killed：是否是禁用交互（沉浸奖励、复活装置、下载装置）
            is_killed = 0
            time.sleep(0.4)
            if self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96, fresh=True):
                for _ in range(4):
                    img = self.get_small_interaction_img(x=0.3181,y=0.4324,mask="mask_f")
                    text = self.ts.similar_list(self.tk.interacts, img)
                    if text is None:
                        img = self.get_small_interaction_img(x=0.3365,y=0.4231,mask="mask_f")
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
                        key_mouse_manager.press('f',force= True)
                        self.battle = 0
                    else:
                        is_killed = 1
                else:
                    # tele：区域-xx  exit：离开模拟宇宙
                    if self.ts.similar("区域"):
                        log.info(f"识别到传送点")
                        key_mouse_manager.press('f',force= True)
                        return self.nof()
                    elif self.re_align == 1 and self.debug == 0:
                        # align_angle(10, 1)
                        # self.multi = config.multi
                        self.re_align += 1
                    is_killed = text in ["沉浸", "紧锁", "复活", "下载"]
                    if is_killed == 0:
                        key_mouse_manager.press('f',force= True)
                    self.battle = 0
                if is_killed == 0:
                    return 1
        # 跑图状态
        if self.isrun():
            log.info("开始匹配地图")
            #检查黄泉
            if not self.quan and self.check("huangquan", 0.0578,0.7083):
                self.quan = 1
            #长时间离开或者未初始化层数？则重新初始化
            if self.floor_init == 0:
                if self.get_level() == -1:
                    return 1
                self.floor_init = 1
            #上次交互时间
            self.lst_changed = bk_lst_changed
            # self.battle：最后一次处于战斗状态的时间，0表示处于非战斗状态
            self.battle = 0
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
                    if self.floor in [0, 5]:
                        self.mini_state = 0
                        self.stop_move = 0
                        while True:
                            self.exist_minimap()
                            now_map, now_map_sim = self.match_scr(self.loc_scr)
                            if self.now_map_sim < now_map_sim:
                                self.now_map, self.now_map_sim = now_map, now_map_sim
                            if (
                                (self.now_map_sim > 0.65 or time.time() - now_time > 2.5)
                                and self.now_map_sim != -1
                            ) or self._stop:
                                break
                            time.sleep(0.3)
                        log.info(f"地图编号：{self.now_map}  相似度：{self.now_map_sim}")
                        if self.now_map_sim < 0.35:
                            notif("相似度过低", "疑似在黑塔办公室")
                            if self.debug==2:
                                time.sleep(10000)
                            # self.init_map()
                            # return 1
                        if self.debug == 2:
                            try:
                                with open(
                                    "check0.txt",
                                    "r",
                                    encoding="utf-8",
                                    errors="ignore",
                                ) as fh:
                                    s = fh.readline().strip("\n")
                                s = eval(s)
                                self.kl = 0
                                if not self.now_map in s:
                                    s.append(self.now_map)
                                    notif(f"地图编号：{self.now_map}",f"相似度：{self.now_map_sim}")
                                else:
                                    #self.kl = 1
                                    pass
                                with open(
                                    "check0.txt",
                                    "w",
                                    encoding="utf-8",
                                ) as fh:
                                    fh.write(str(s))
                            except:
                                pass
                        self.now_pth = "resource/imgs/maps/" + self.now_map + "/"
                        files = self.find_latest_modified_file(self.now_pth)
                        print("地图文件：", files)
                        self.big_map = cv.imread(files, cv.IMREAD_GRAYSCALE)
                        self.debug_map = deepcopy(self.big_map)
                        xy = files.split("/")[-1].split("_")[1:3]
                        self.now_loc = (4096 - int(xy[0]), 4096 - int(xy[1]))
                        self.target = self.get_target(self.now_pth + "target.jpg")
                        self.get_screen()
                        shape = (int(self.scx * 190), int(self.scx * 190))
                        local_screen = self.get_local(0.9333, 0.8657, shape)
                        self.init_ang = 360 - self.get_now_direct(local_screen) - 90
                        log.info("target %s" % self.target)
                    if self._stop:
                        return 1
                    if self.consumable and (self.check_bonus or self.count<34) and self.floor in [3, 7, 12][-self.consumable:]:
                        self.use_consumable(1, 1)
                    key_mouse_manager.press("1")
                # 录制模式，保存初始小地图
                else:
                    log.info("未找到匹配地图")
                    time.sleep(3)
                    self.mini_state = 0
                    self.exist_minimap()
                    cv.imwrite(self.map_file + "init.jpg", self.loc_scr)
            self.get_screen()
            if time.time() - self.lst_tm > 5 and self.mini_state == 0:
                if self.find == 0:
                    key_mouse_manager.press("s", 0.5)
                    if self._stop == 0:
                        key_mouse_manager.keyDown("w")
                    time.sleep(0.5)
                    self.get_screen()
            self.lst_tm = time.time()
            
            self.kl |= self.floor >= 4 and self.debug == 2
            # 长时间未交互/战斗，暂离或重开
            if (
                (
                    (time.time() - self.lst_changed >= 37 - 4 * self.debug + 8 * self.slow)
                    and self.find == 1
                )
                or (self.floor == 12 and self.mini_state > 4)
                or self.kl
            ):
                time.sleep(2.5)
                key_mouse_manager.press("esc")
                time.sleep(2)
                self.init_map()
                self.floor_init = 0
                if self.floor == 12 or self.kl:
                    self.end_of_uni()
                    key_mouse_manager.click(0.2708, 0.1324)
                    log.info(f"通关！当前层数:{self.floor+1}")
                elif self.debug == 2:
                    log.error(f"地图{self.now_map}出现问题,退出程序")
                    log.info('地图错误')
                    notif(f"地图{self.now_map}出现问题,退出程序", "DEBUG")
                    self._stop = 1
                elif self.fail_count <= 1:
                    notif("暂离", f"地图{self.now_map}，当前层数:{self.floor+1}")
                    log.error(f"地图{self.now_map}未发现目标,相似度{self.now_map_sim}，尝试暂离")
                    key_mouse_manager.click(0.2708, 0.2324)
                    self.re_enter()
                    self.re_align += 1
                    self.fail_count += 1
                else:
                    self.multi = 1.01
                    if self.debug == 0:
                        notif("中途结算", f"地图{self.now_map}，当前层数:{self.floor+1}")
                        self.floor = 0
                        key_mouse_manager.click(0.2708, 0.1324)
                        log.error(
                            f"地图{self.now_map}未发现目标,相似度{self.now_map_sim}，尝试退出重进"
                        )
                        self.fail_count = 0
                    else:
                        self.re_align += 1
                        log.error(
                            f"地图{self.now_map}未发现目标,相似度{self.now_map_sim}，尝试暂离 DEBUG"
                        )
                        key_mouse_manager.click(0.2708, 0.2324)
                        self.re_enter()
                self.lst_changed = time.time()
                return 1
            if self.multi == 1.01:
                align_angle(0, 1, [1], self)
            self.get_screen()
            if self.floor > 0 and self.check("ruan",0.0625,0.7065,threshold=0.95) and not self.check("U", 0.0240,0.7759) and not (self.floor==12 and self.mini_state>1):
                key_mouse_manager.press('e')
                time.sleep(1.5)
                if self.check('e',0.4995,0.7500,fresh= True):
                    self.solve_snack()
            # 寻路
            log.info("开始寻路")
            if self.mini_state:
                #有先验寻路
                self.get_direc_only_minimap()
            else:
                #无先验寻路
                self.get_direc()
            return 2
        elif self.check('e',0.4995,0.7500):
            self.solve_snack()
        elif self.check("init", 0.9120,0.8361):
            if self.end:
                time.sleep(1)
                key_mouse_manager.press('esc')
                self._stop = 1
                log.info('已退出模拟宇宙，自动化结束')
                return 1
            time.sleep(2)
            key_mouse_manager.click(0.3448, 0.4926)
            time.sleep(1)
            self.init_map()
        elif self.check("begin", 0.3578,0.8046):
            con = self.check("conti", 0.1422,0.0907)
            if not con:
                if self.diffi == 5:
                    key_mouse_manager.click(0.9375, 0.5565)
                    time.sleep(0.2)
                key_mouse_manager.click(0.9375, 0.8565 - 0.1 * (self.diffi - 1))
            key_mouse_manager.click(0.1083, 0.1009)
            if con:
                self.get_level()
            else:
                self.floor = 0
            self.floor_init = 1
        elif self.check("start", 0.6594, 0.8389):
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
        elif self.check("fate_2", 0.1182,0.0926):
            key_mouse_manager.click(0.1182,0.0926)
            self.confirm_time = time.time()
        elif self.check("fate", 0.9432,0.9389):
            time.sleep(0.6)
            click_x = [0.02, 0.98]
            n = 4  # 重试次数
            res = None
            while n:
                img = self.get_small_interaction_img(x=0.4969,y=0.3750,mask="mask_fate",fresh=True)
                res = self.ts.split_and_find([self.fate], img)
                if res[1] == 1 and n:
                    # 没有找到命途
                    log.info(f"未找到 {self.fate} 命途，尝试翻页")
                    key_mouse_manager.click(click_x[n % len(click_x)], 0.5)
                    n -= 1
                    time.sleep(0.5)
                    continue
                else:
                    break
            key_mouse_manager.click(*self.calc_point((0.4969, 0.3750), res[0]))
        elif self.check("fate_3", 0.9422, 0.9472):
            if not self.click_text(['2星祝福','奇物']):
                key_mouse_manager.click(0.5047, 0.4917)
            key_mouse_manager.click(0.5062, 0.1065)
            time.sleep(1)
        # 事件界面
        elif self.check("event", 0.9479, 0.9565):
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
                time.sleep(0.3)
                self.get_screen()
                if success and self.check("confirm", 0.1828, 0.5000, mask="mask_event", threshold=0.965):
                    key_mouse_manager.click(self.tx, self.ty)
                elif self.check("wait_room", 0.880, 0.156,threshold=0.95):
                    key_mouse_manager.click(1600, 800)
                else:
                    key_mouse_manager.click(tx, ty)
                    time.sleep(0.3)
                    key_mouse_manager.click(0.1167, ty - 0.1139)
                time.sleep(0.5)
                for _ in range(7):
                    if not self.check("event", 0.9479, 0.9565,fresh=True):
                        break
                    time.sleep(0.1)
                self.lst_changed = time.time()
            else:
                key_mouse_manager.click(0.9479, 0.9565)
        # 选取奇物
        elif self.check("strange", 0.9417, 0.9481):
            time.sleep(0.6)
            img = self.get_small_interaction_img(x=0.5000,y=0.7333,mask="mask_strange",fresh=True)
            res = self.ts.split_and_find(self.tk.strange, img, mode="strange")
            key_mouse_manager.click(*self.calc_point((0.5000, 0.7333), res[0]))
            key_mouse_manager.click(0.1365, 0.1093)
            self.wait_fig(lambda:self.check("strange", 0.9417, 0.9481), 1.4)
        # 丢弃奇物
        elif self.check("drop", 0.9406, 0.9491):
            key_mouse_manager.click(0.4714, 0.5500)
            key_mouse_manager.click(0.1339, 0.1028)
            self.wait_fig(lambda:self.check("drop", 0.9406, 0.9491), 1.4)
        elif self.check("drop_bless", 0.9417, 0.9481, threshold=0.95):
            time.sleep(1.5)
            st = set(self.tk.fates) - set(self.tk.secondary)
            clicked = 0
            for i,ft in enumerate(self.tk.secondary[::-1]):
                if ft != self.fate or i == len(self.tk.secondary):
                    img_down = self.get_small_interaction_img(x=0.5042,y=0.3204,mask="mask",fresh=True)
                    if self.debug==2:
                        print(list(st),self.tk.secondary)
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
        elif self.check("setting", 0.9734, 0.3009, threshold=0.98):
            key_mouse_manager.click(0.2708, 0.2324)
            self.re_enter()
        elif self.check("enhance", 0.9208, 0.9380):
            self.quit = time.time()
            time.sleep(1.5)
            for i in [None, (0.7984, 0.6824), (0.6859, 0.6824)]:
                if self.check("enhance_fail", 0.1068, 0.0907,fresh= True):
                    break
                if i is not None:
                    key_mouse_manager.click(i)
                    time.sleep(0.3)
                key_mouse_manager.click(0.1089, 0.0926)
                time.sleep(0.3)
                tm = time.time()
                while not self.check("enhance", 0.9208, 0.9380,fresh= True) and time.time()-tm<7:
                    key_mouse_manager.click(0.2062, 0.2054)
                    time.sleep(0.3)
            key_mouse_manager.press("esc")
            key_mouse_manager.press("w", 2)
            tm = time.time()
            while time.time()-tm<2 and not self.check("f", 0.4443, 0.4417, mask="mask_f1", threshold=0.96,fresh= True) and not self.isrun():
                time.sleep(0.15)
            # time.sleep(0.35)
            # self.mouse_move(-30)
            self.confirm_time = time.time()
            self.lst_changed = time.time()
            if self.floor >= 12:
                self.floor = 11
        elif self.check("yes1", 0.5, 0.5, mask="mask_end"):
            key_mouse_manager.click(self.tx,self.ty)
            time.sleep(1)
            return 0
        elif self.check("fail", 0.6276, 0.0843):
            key_mouse_manager.click(self.tx, self.ty)
            time.sleep(1.8)
        else:
            return 0
        return 1

    def find_latest_modified_file(self, folder_path):
        files = [
            os.path.join(folder_path, file)
            for file in os.listdir(folder_path)
            if file.split("/")[-1][0] == "m"
        ]
        nx, ny = 4096, 4096
        file = ""
        for i in files:
            try:
                x, y = i.split("_")[-3:-1]
                x, y = int(x), int(y)
                if x < nx or y < ny:
                    nx, ny = x, y
                    file = i
            except:
                pass
        return file

    def update_count(self, read=True):
        file_name = "logs/notif.txt"
        if read:
            new_cnt = 0
            if os.path.exists(file_name):
                time_cnt = os.path.getmtime(file_name)
                with open(file_name, "r", encoding="utf-8", errors="ignore") as fh:
                    s = fh.readlines()
                    try:
                        new_cnt = int(s[0].strip("\n"))
                        time_cnt = float(s[3].strip("\n"))
                    except:
                        pass
            else:
                os.makedirs("logs", exist_ok=1)
                with open(file_name, "w", encoding="utf-8") as file:
                    file.write("0")
                    file.close()
                time_cnt = os.path.getmtime(file_name)
        else:
            new_cnt = self.count + 1
            time_cnt = self.count_tm
        dt = datetime.datetime.now().astimezone()
        """
        America: GMT-5
        Asia: GMT+8
        Europe: GMT+1
        TW, HK, MO: GMT+8
        """
        tz_info = None
        try:
            tz_dict = {
                "Default": None,
                "America": pytz.timezone("US/Central"),
                "Asia": pytz.timezone("Asia/Shanghai"),
                "Europe": pytz.timezone("Europe/London"),
            }
            tz_info = tz_dict[config.timezone]
        except:
            pass

        # convert to server time
        dt = dt.astimezone(tz_info)
        current_weekday = dt.weekday()
        monday = dt + datetime.timedelta(days=-current_weekday)
        target_datetime = datetime.datetime(
            monday.year, monday.month, monday.day, 4, 0, 0, tzinfo=tz_info
        )
        monday_ts = target_datetime.timestamp()
        if dt.timestamp() >= monday_ts and time_cnt < monday_ts:
            self.count = int(not read)
        else:
            self.count = new_cnt
        self.count_tm = time.time()

    def del_pt(self, img, A, S, f):
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
                        p = self.get_center(img, i, j)
                        res.add((p, k))
                        p = (int(p[0]), int(p[1]))
                        self.del_pt(img, p, p, f_set[k])
                        if k == 3:
                            self.last = p
        # cv.imwrite("imgs/tmp1.jpg", img)
        if self.speed:
            dis = 1000000
            pt = None
            for i in res:
                if i[1] == 1 and get_dis(i[0], self.last) < dis:
                    dis = get_dis(i[0], self.last)
                    pt = i
            for i in deepcopy(res):
                if i[1] == 1 and pt != i:
                    res.remove(i)
                    res.add((i[0], 0))
        return res

    def get_center(self, img, i, j):
        rx, ry, rt = 0, 0, 0
        for x in range(-7, 7):
            for y in range(-7, 7):
                if (
                    i + x >= 0
                    and j + y >= 0
                    and i + x < img.shape[0]
                    and j + y < img.shape[1]
                ):
                    s = np.sum(img[i + x, j + y])
                    if s > 30 and s < 255 * 3 - 30:
                        rt += 1
                        rx += x
                        ry += y
        return (i + rx / rt, j + ry / rt)
    
    def backup_map(self):
        try:
            self.bbig_map,self.bbig_map_c,self.blst_tm,self.btries,self.bhis_loc,self.boffset,self.bnow_loc,self.bmini_state,self.bang_off,self.bang_neg,self.bfirst_mini=self.big_map,self.big_map_c,self.lst_tm,self.tries,self.his_loc,self.offset,self.now_loc,self.mini_state,self.ang_off,self.ang_neg,self.first_mini
        except:
            pass
    def restore_map(self):
        self.big_map,self.big_map_c,self.lst_tm,self.tries,self.his_loc,self.offset,self.now_loc,self.mini_state,self.ang_off,self.ang_neg,self.first_mini=self.bbig_map,self.bbig_map_c,self.blst_tm,self.btries,self.bhis_loc,self.boffset,self.bnow_loc,self.bmini_state,self.bang_off,self.bang_neg,self.bfirst_mini

    def re_enter(self):
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

        if self.click_text(text="模拟宇宙",box=[1231, 1360, 595, 631],click=False):
            log.info("已在办公室，打开模拟宇宙")
            key_mouse_manager.press('f')
            return
        log.info("前往黑塔办公室")
        if self.check("smartphone", 0.9833,0.9380, threshold=0.95,fresh=True):
            log.info("打开地图")
            key_mouse_manager.press('m')
            while not self.click_text(text="星轨航图",delay=1,after_delay=0.5,box=[1625, 1732, 143, 176]):
                time.sleep(0.5)
            #拖拽地图到最左
            key_mouse_manager.drag(0.8521,0.5620,0.1521,0.5620)
            key_mouse_manager.drag(0.8521,0.5620,0.1521,0.5620)
            while not self.click_text(text="空间站",delay=3):
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
            while not self.click_text(text="传送",box=[1623, 1687, 951, 990]):
                time.sleep(0.5)
            while not self.click_text(text="黑塔的办公室",box=[59, 185, 16, 39],click=False):
                time.sleep(0.5)
            key_mouse_manager.mouse_move(20)
            key_mouse_manager.keyDown("w")
            sprint()
            key_mouse_manager.sleep(4)
            key_mouse_manager.keyUp("w")
    def loop(self):
        #截图并识别文本
        self.ts.forward(self.get_screen())
        # self.ts.find_with_box()
        # exit()
        res = self.run_static()
        # self.click_target("imgs/c.jpg", threshold=0.9, flag=False)
        #没有检测到已有的存在的文字
        if res == '':
            area_text = clean_text(self.ts.ocr_one_row(self.screen, [50, 350, 3, 35]), char=0)
            if '位面' in area_text or '区域' in area_text or '第' in area_text:
                # self.area()
                self.last_action_time = time.time()

            elif self.check("c", 0.988, 0.1028, threshold=0.925):
                # 未检查到自动战斗,已经入站,清除秘技持续
                self.da_hei_ta_effecting = False
                key_mouse_manager.press('v')
            # else:
                # text = merge_text(self.ts.find_with_box([400, 1920, 100, 600], redundancy=0))
                #速通模式跳过转化
                # if self.speed and '转化' in text and '继续战斗' not in text and ('数据' in text or '过量' in text):
                #     log.info('ready to stop')
                #     time.sleep(6)
                #     tm = time.time()
                #     while time.time() - tm < 15:
                #         log.info('trying to stop')
                #         self.press('esc')
                #         time.sleep(2)
                #         self.ts.forward(self.get_screen())
                #         static_res = self.run_static(action_list=['过量转化'])
                #         if static_res != '':
                #             print(static_res)
                #             break
                # else:
                #     if time.time() - self.last_action_time > 60:
                #         self.click((0.5, 0.1))
                #         self.click((0.5, 0.25))
                #         self.last_action_time = time.time()
        else:
            self.last_action_time = time.time()
        if self.end and res == '加载界面':
            key_mouse_manager.press('esc')
            time.sleep(2)
            key_mouse_manager.press('esc')
            self._stop = True
    def run_static(self, json_path=None, json_file=None, action_list=[], skip_check=0) -> str:
        if json_file is None:
            if json_path is None:
                json_file = self.default_json
            else:
                json_file = load_actions(json_path)
        #查找指定项或者默认项
        for j in action_list if len(action_list) else json_file:
            for i in json_file[j]:
                trigger = i["trigger"]
                #获取指定范围的文字
                text = self.ts.find_with_box(trigger["box"], redundancy=trigger.get("redundancy", 30))
                #强制跳过或者检查是否存在子串
                if skip_check or (len(text) and trigger["text"] in merge_text(text)):
                    log.info(f"触发 {i['name']}:{trigger['text']}")
                    for j in i["actions"]:
                        self.do_action(j)
                    self.action_history.append(i["name"])
                    #记录最近10个动作
                    self.action_history = self.action_history[-10:]
                    #返回触发的名字
                    return i['name']
        return ''
    def do_action(self, action) -> int:
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
                    log.info(f"点击 {action['text']}:{i['box']}")
                    self.click_box(i["box"])
                    return 1
        elif "position" in action:
            log.info(f"点击 {action['position']}")
            self.click_position(action["position"])
            return 1
        elif "sleep" in action:
            self.sleep(float(action["sleep"]))
            return 1
        elif "press" in action:
            key_mouse_manager.press(action["press"], action["time"] if "time" in action else 0)
            return 1
        return 0
    def show_map(self):
        # 创建窗口时使用 WINDOW_FREERATIO 标志以避免自动获取焦点
        cv.namedWindow("Map", cv.WINDOW_FREERATIO | cv.WINDOW_NORMAL)
        angle_history = []
        last_angle_change_time = 0
        
        while not self._stop:
            if self.debug_map.shape[0] == 8192:
                continue
            updated_image = self.debug_map.copy()
            updated_image = cv.cvtColor(updated_image, cv.COLOR_GRAY2RGB)
            updated_image[
                self.real_loc[0] - 2 : self.real_loc[0] + 3,
                self.real_loc[1] - 2 : self.real_loc[1] + 3,
            ] = [49, 49, 140]

            if hasattr(self, 'ang') and self.ang is not None:
                import math
                angle_rad = math.radians(- self.ang)  # 使用正确的坐标转换
                line_length = 20
                end_point = (
                    int(self.real_loc[1] + line_length * math.cos(angle_rad)),
                    int(self.real_loc[0] - line_length * math.sin(angle_rad))  # 注意y轴方向
                )
                cv.arrowedLine(
                    updated_image, 
                    (self.real_loc[1], self.real_loc[0]),
                    end_point, 
                    (0, 255, 0), 
                    2, 
                    tipLength=0.4
                )
            
            # 更新角度历史记录
            current_time = time.time()
            if hasattr(self, 'ang') and self.ang is not None:
                if not angle_history or angle_history[-1][1] != self.ang:
                    angle_history.append((current_time, self.ang))
                    last_angle_change_time = current_time
                # 保留最近5秒的角度记录
                while angle_history and current_time - angle_history[0][0] > 5:
                    angle_history.pop(0)
            
            # 在左上角显示角度数值
            if hasattr(self, 'ang') and self.ang is not None:
                # 计算颜色 (新变更红色，随时间推移逐渐变蓝)
                elapsed_time = current_time - last_angle_change_time
                if elapsed_time < 2:  # 2秒内变为蓝色
                    red = max(0, 255 * (1 - elapsed_time / 2))
                    blue = min(255, 255 * (elapsed_time / 2))
                    color = (int(blue), 0, int(red))  # BGR格式
                else:
                    color = (255, 0, 0)  # 蓝色

                angle_text = f"Angle: {-self.ang:.1f}"
                cv.putText(updated_image, angle_text, (10, 30), 
                          cv.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)
            
            # 将图片放大两倍
            updated_image = cv.resize(
                updated_image, None, fx=2, fy=2, interpolation=cv.INTER_LINEAR
            )

            cv.imshow("Map", updated_image)
            cv.waitKey(1000)

        cv.destroyAllWindows()


    def start(self):
        self._stop = False
        key_mouse_manager.start()
        if self._show_map:
            self.map_thread = threading.Thread(target=self.show_map)
            self.map_thread.start()
        try:
            self.route()
        except Exception as e:
            log.info(f'异常终止进程{e}')
            if not self._stop:
                self.stop()
            # 重新抛出异常，以便上层能够捕获
            raise

    def stop(self, *_, **__):
        log.info("尝试停止运行")
        self._stop = 1
        key_mouse_manager.stop()

        # 等待地图线程结束
        if self.map_thread and self.map_thread.is_alive():
            # 等待最多2秒让线程自行结束
            timeout = 2
            start_time = time.time()
            while self.map_thread.is_alive() and (time.time() - start_time) < timeout:
                time.sleep(0.1)

            # 如果线程仍未结束，强制终止
            if self.map_thread.is_alive():
                import ctypes
                res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                    ctypes.c_long(self.map_thread.ident),
                    ctypes.py_object(SystemExit)
                )
                time.sleep(0.5)  # 短暂等待

        self.map_thread = None