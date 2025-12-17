import ctypes
import datetime
import time
from threading import Thread

import cv2
import numpy as np
import win32con
import win32gui
import win32ui
from PIL import ImageGrab


class WindowRecorder:
    def __init__(self, output_file="window_recording.mp4", handle=None, fps=30.0, window_title=None, window_class_name=None, see_time=False,
                 is_show=False):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = output_file + f"{timestamp}.mp4"
        self.fps = fps
        self.window_title = window_title
        self.window_class_name = window_class_name
        self.recording = False
        self.recording_thread = None
        self.hwnd = handle
        self.out = None
        self.width = 0
        self.height = 0
        self.see_time = see_time
        self.is_show = is_show

    def start_recording(self):
        """开始录制指定窗口"""
        if self.recording:
            print("Already recording")
            return
            
        # 查找目标窗口
        if not self.hwnd:
            self.hwnd = win32gui.FindWindow(self.window_class_name, self.window_title)
            print(f"找到窗口句柄: {self.hwnd}")
            
        if not self.hwnd:
            if self.window_class_name:
                raise ValueError(f"未找到类名为 '{self.window_class_name}' 且标题包含 '{self.window_title}' 的窗口")
            else:
                raise ValueError(f"未找到标题包含 '{self.window_title}' 的窗口")
        
        # 确保窗口可见且有效
        if not win32gui.IsWindowVisible(self.hwnd):
            print("警告: 窗口不可见")
            
        if not win32gui.IsWindow(self.hwnd):
            raise ValueError("窗口句柄无效")

        # 设置DPI感知
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 2 = Per-monitor v2 DPI awareness
        except Exception as e:
            print(f"无法设置DPI感知级别: {e}")
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception as e:
                print(f"无法设置DPI感知级别(备用方法): {e}")
        
        # 获取窗口位置和尺寸
        try:
            # 获取窗口位置
            rect = win32gui.GetWindowRect(self.hwnd)
            self.left, self.top, self.right, self.bottom = rect
            self.width = self.right - self.left
            self.height = self.bottom - self.top
            
            print(f"窗口位置: ({self.left}, {self.top}, {self.right}, {self.bottom}), 尺寸: {self.width}x{self.height}")
        except Exception as e:
            print(f"获取窗口位置失败: {e}")
            raise

        # 确保输出目录存在
        import os
        output_dir = os.path.dirname(self.output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # 设置视频写入器
        print(f"初始化视频写入器，尺寸: {self.width}x{self.height}")
        self.out = cv2.VideoWriter(
            self.output_file,
            cv2.VideoWriter_fourcc(*'mp4v'),
            self.fps,
            (self.width, self.height)
        )
        
        if not self.out.isOpened():
            raise RuntimeError("无法初始化视频写入器")

        # 启动录制线程
        self.recording = True
        self.recording_thread = Thread(target=self._record_window, daemon=True)
        self.recording_thread.start()

    def _record_window(self):
        """实际的窗口录制线程"""
        try:
            while self.recording:
                try:
                    # 使用ImageGrab直接捕获窗口区域
                    bbox = (self.left, self.top, self.right, self.bottom)
                    img = ImageGrab.grab(bbox=bbox)
                    
                    # 转换为OpenCV格式
                    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                    
                    # 添加时间戳
                    if self.see_time:
                        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
                        current_time = datetime.datetime.now().strftime("%H:%M:%S")

                        # 配置参数
                        font_scale = 0.5
                        font_thickness = 2
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        line_spacing = 15
                        h_padding = 6
                        v_padding = 20

                        # 获取文本尺寸
                        (text_width1, text_height1), _ = cv2.getTextSize(current_date, font, font_scale, font_thickness)
                        (text_width2, text_height2), _ = cv2.getTextSize(current_time, font, font_scale, font_thickness)

                        # 计算最大宽度和总高度
                        max_text_width = max(text_width1, text_width2)
                        total_text_height = text_height1 + text_height2 + line_spacing

                        # 优化背景框尺寸计算
                        rect_width = max_text_width + h_padding * 2
                        rect_height = total_text_height + v_padding * 2

                        # 绘制白色背景矩形
                        cv2.rectangle(img_cv,
                                      (5, 5),
                                      (5 + rect_width, 5 + rect_height),
                                      (255, 255, 255),
                                      -1)

                        # 优化文字绘制位置
                        line1_y = 5 + v_padding + text_height1
                        line2_y = line1_y + text_height2 + line_spacing

                        cv2.putText(img_cv, current_date,
                                    (5 + h_padding, line1_y),
                                    font,
                                    font_scale,
                                    (0, 0, 255),
                                    font_thickness)

                        cv2.putText(img_cv, current_time,
                                    (5 + h_padding, line2_y),
                                    font,
                                    font_scale,
                                    (0, 0, 255),
                                    font_thickness)

                    # 写入视频文件
                    self.out.write(img_cv)
                    
                    if self.is_show:
                        # 实时显示当前帧
                        cv2.imshow('Window Recorder', img_cv)
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            print("用户按 q 键，停止录制")
                            self.stop_recording()
                            break

                    # 控制帧率
                    time.sleep(1 / self.fps)
                    
                except Exception as e:
                    print(f"录制单帧时发生错误: {e}")
                    continue

        except Exception as e:
            import traceback
            traceback.print_exc()
        finally:
            # 释放资源
            if self.out:
                self.out.release()
                self.out = None
            cv2.destroyAllWindows()
            print("视频写入器已释放")

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        if self.out:
            self.out.release()
            self.out = None
        print("视频写入器已释放")


if __name__ == "__main__":
    try:
        window_title = "崩坏：星穹铁道"
        output_file = "../logs/video/"
        fps = 10

        print("准备开始录制（5秒后自动停止）...")
        print(f"请在5秒内打开窗口：{window_title}")
        time.sleep(2)

        recorder = WindowRecorder(output_file, fps=fps, window_title=window_title,window_class_name="UnityWndClass")
        recorder.start_recording()
        print(f"正在录制窗口：{window_title}")
        print("录制将持续5秒，请在目标窗口中进行一些操作")

        time.sleep(5)

        recorder.stop_recording()
        print("录制已完成！")
        print(f"视频已保存为：{output_file}")

    except Exception as e:
        print(f"发生错误: {str(e)}")