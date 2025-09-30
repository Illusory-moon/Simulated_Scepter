import queue
import threading
import time
import pyautogui
import win32api
import win32con

from utils.log import log


class KeyMouseManager:
    """
    键鼠操作管理器，通过队列管理所有键鼠操作，确保线程安全和操作顺序
    """

    def __init__(self):
        self.operation_queue = queue.Queue()
        self.worker_thread = None
        self.running = False
        #键鼠配置
        self.config = None
        self.x1 = 0
        self.y1 = 0
        self.xx = 1
        self.yy = 1
        self.full = False
        self.multi = 1.0
        self.scale = 1.0

    def set_config(self, config):
        """
        设置配置对象
        
        Args:
            config: 配置对象，包含键位映射等信息
        """
        self.config = config
        if hasattr(config, 'multi'):
            self.multi = config.multi
        if hasattr(config, 'scale'):
            self.scale = config.scale

    def set_screen_params(self, x1, y1, xx, yy, full=False):
        """
        设置屏幕参数，用于坐标转换
        
        Args:
            x1: 屏幕左边界坐标
            y1: 屏幕上边界坐标
            xx: 屏幕宽度
            yy: 屏幕高度
            full: 是否全屏模式
        """
        self.x1 = x1
        self.y1 = y1
        self.xx = xx
        self.yy = yy
        self.full = full

    def start(self):
        """
        启动键鼠管理器线程
        """
        log.info("启动键鼠管理器线程")
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self._worker, daemon=True)
            self.worker_thread.start()

    def stop(self):
        """
        停止键鼠管理器线程
        """
        log.info("停止键鼠管理器线程")
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            # 清空队列中的操作
            while not self.operation_queue.empty():
                try:
                    self.operation_queue.get_nowait()
                    self.operation_queue.task_done()
                except queue.Empty:
                    break
            # 发送停止信号
            self.operation_queue.put(None)
            self.worker_thread.join()

    def _worker(self):
        """
        工作线程，处理队列中的操作
        """
        while self.running:
            try:
                #未获取到信号则一直阻塞
                operation = self.operation_queue.get(timeout=0.1)
                # None作为停止信号
                if operation is None:
                    self.operation_queue.task_done()
                    break
                    
                self._execute_operation(operation)
                self.operation_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"键鼠操作执行出错: {e}")

    def _get_mapping(self, key):
        """
        获取键位映射
        
        Args:
            key: 原始键位
            
        Returns:
            映射后的键位
        """
        if self.config and hasattr(self.config, 'origin_key') and hasattr(self.config, 'mapping'):
            if key in self.config.origin_key:
                key = self.config.mapping[self.config.origin_key.index(key)]
        return key

    def _convert_coordinates(self, x, y):
        """
        转换坐标格式
        
        Args:
            x: x坐标（可能是浮点数比例，也可能是实际坐标）
            y: y坐标（可能是浮点数比例，也可能是实际坐标）
            
        Returns:
            (actual_x, actual_y): 实际的屏幕坐标
        """
        # 如果是浮点数表示，则计算实际坐标
        if isinstance(x, float):
            actual_x, actual_y = self.x1 - int(x * self.xx), self.y1 - int(y * self.yy)
        else:
            actual_x, actual_y = x, y
            
        # 全屏模式会有一个偏移
        if self.full:
            actual_x += 9
            actual_y += 9
            
        return actual_x, actual_y

    def _execute_operation(self, operation):
        """
        执行单个键鼠操作
        
        Args:
            operation: 操作字典，包含操作类型和参数
        """
        op_type = operation['type']
        log.info(f"执行操作{operation}")
        if op_type == 'keyDown':
            key = self._get_mapping(operation['key'])
            pyautogui.keyDown(key)
            
        elif op_type == 'keyUp':
            key = self._get_mapping(operation['key'])
            # 特殊处理shift键
            if (self.config and hasattr(self.config, 'long_press_sprint') and 
                self.config.long_press_sprint and operation['key'] == 'w'):
                pyautogui.keyUp(self._get_mapping('shift'))
            pyautogui.keyUp(key)
            
        elif op_type == 'press':
            key = self._get_mapping(operation['key'])
            duration = operation.get('duration', 0)
            
            # 检查是否需要跳过该按键
            if operation.get('allow_e', 1) == 0 and key == 'e':
                return
                
            if (self.config and hasattr(self.config, 'slow') and 
                self.config.slow and key == 'shift'):
                return
                
            pyautogui.keyDown(key)
            if duration > 0:
                time.sleep(duration)
                pyautogui.keyUp(key)
                
        elif op_type == 'click':
            x, y = operation['x'], operation['y']
            # 转换坐标
            actual_x, actual_y = self._convert_coordinates(x, y)
            win32api.SetCursorPos((actual_x, actual_y))
            pyautogui.click()
            
        elif op_type == 'mouse_move':
            dx = operation['dx']
            fine = operation.get('fine', 1)
            # 仿照UniverseUtils.mouse_move实现
            self._direct_mouse_move(dx, fine)

            
        elif op_type == 'scroll':
            x, y = operation['x'], operation['y']
            direct = operation['direct']
            # 转换坐标
            actual_x, actual_y = self._convert_coordinates(x, y)
            win32api.SetCursorPos((actual_x, actual_y))
            count = abs(direct)
            for _ in range(count):
                if direct > 0:
                    pyautogui.scroll(120)
                else:
                    pyautogui.scroll(-120)
            
        elif op_type == 'drag':
            start_x, start_y = operation['start_x'], operation['start_y']
            end_x, end_y = operation['end_x'], operation['end_y']
            duration = operation.get('duration', 0.4)
            # 转换起始坐标
            actual_start_x, actual_start_y = self._convert_coordinates(start_x, start_y)
            actual_end_x, actual_end_y = self._convert_coordinates(end_x, end_y)
            win32api.SetCursorPos((actual_start_x, actual_start_y))
            time.sleep(0.2)
            pyautogui.drag(actual_end_x - actual_start_x, actual_end_y - actual_start_y, duration)

    def _direct_mouse_move(self, x, fine=1):
        """
        直接执行鼠标移动，不通过队列
        
        Args:
            dx: x轴移动距离
            fine: 精细度控制参数
        """
        if x > 30 // fine:
            y = 30 // fine
        elif x < -30 // fine:
            y = -30 // fine
        else:
            y = x
        dx = int(16.5 * y * self.multi * self.scale)
        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, dx, 0)  # 进行视角移动
        time.sleep(0.05 * fine)
        if x != y:
            self._direct_mouse_move(x - y, fine)


    def keyDown(self, key):
        """
        按下按键
        
        Args:
            key: 要按下的键
        """
        self.operation_queue.put({
            'type': 'keyDown',
            'key': key
        })

    def keyUp(self, key):
        """
        释放按键
        
        Args:
            key: 要释放的键
        """
        self.operation_queue.put({
            'type': 'keyUp',
            'key': key
        })

    def press(self, key, duration=0, allow_e=1):
        """
        按下并释放按键
        
        Args:
            key: 要按下的键
            duration: 按下持续时间（秒）
            allow_e: 是否允许按下'e'键（用于特殊场景）
        """
        self.operation_queue.put({
            'type': 'press',
            'key': key,
            'duration': duration,
            'allow_e': allow_e
        })

    def click(self, x, y):
        """
        点击指定位置
        
        Args:
            x: 屏幕x坐标（支持浮点数比例坐标和实际坐标）
            y: 屏幕y坐标（支持浮点数比例坐标和实际坐标）
        """
        self.operation_queue.put({
            'type': 'click',
            'x': x,
            'y': y
        })

    def mouse_move(self, dx, fine=1):
        """
        移动鼠标
        
        Args:
            dx: x轴移动距离
            fine: 精细度控制参数
        """
        self.operation_queue.put({
            'type': 'mouse_move',
            'dx': dx,
            'fine': fine
        })

    def scroll(self, direct=1,x=0.5,y=0.5):
        """
        滚动鼠标滚轮
        
        Args:
            x: 滚动位置x坐标（支持浮点数比例坐标和实际坐标）
            y: 滚动位置y坐标（支持浮点数比例坐标和实际坐标）
            direct: 滚动方向和次数，正数向上滚动，负数向下滚动
        """

        self.operation_queue.put({
            'type': 'scroll',
            'x': x,
            'y': y,
            'direct': direct
        })

    def drag(self, start_x, start_y, end_x, end_y, duration=0.4):
        """
        拖拽操作
        
        Args:
            start_x: 起始点x坐标（支持浮点数比例坐标和实际坐标）
            start_y: 起始点y坐标（支持浮点数比例坐标和实际坐标）
            end_x: 结束点x坐标（支持浮点数比例坐标和实际坐标）
            end_y: 结束点y坐标（支持浮点数比例坐标和实际坐标）
            duration: 拖拽持续时间（秒）
        """
        self.operation_queue.put({
            'type': 'drag',
            'start_x': start_x,
            'start_y': start_y,
            'end_x': end_x,
            'end_y': end_y,
            'duration': duration
        })