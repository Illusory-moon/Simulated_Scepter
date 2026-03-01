import ctypes
import datetime
import time

import cv2
import numpy as np
import win32con
import win32gui
import win32ui
from PIL import ImageGrab

# 导入必要的 Windows API 函数
from ctypes import windll, wintypes, byref

# 导入日志模块
from utils.log import CUS_LOGGER
from utils.thread import ThreadWithException


class WindowRecorder:
    def __init__(self, output_path="window_recording.mp4", handle=None, fps=30.0, window_title=None, window_class_name=None, see_time=False,
                 is_show=False, offsets=None, overlay_map=False, map_alpha=0.7):
        self.output_path=output_path
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
        # 偏移参数，用于收缩录制范围 [left, top, right, bottom]
        if offsets is None:
            offsets = [0, 0, 0, 0]
        self.offsets = offsets
        self.left_offset = offsets[0]
        self.top_offset = offsets[1]
        self.right_offset = offsets[2]
        self.bottom_offset = offsets[3]
        # 是否叠加地图窗口
        self.overlay_map = overlay_map
        # 地图透明度 (0.0-1.0，1.0为完全不透明)
        self.map_alpha = map_alpha
        
    def capture_window_background(self, hwnd):
        """使用 PrintWindow API 后台截图指定窗口"""
        if not hwnd or not win32gui.IsWindow(hwnd):
            return None
            
        # 获取窗口尺寸
        try:
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            
            if width <= 0 or height <= 0:
                return None
                
            # 创建设备上下文和位图
            hwnd_dc = None
            mfc_dc = None
            save_dc = None
            save_bit_map = None
            old_bitmap = None
            
            try:
                # 获取窗口DC
                hwnd_dc = win32gui.GetWindowDC(hwnd)
                if not hwnd_dc:
                    return None
                    
                # 创建DC对象
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()
                
                # 创建位图
                save_bit_map = win32ui.CreateBitmap()
                save_bit_map.CreateCompatibleBitmap(mfc_dc, width, height)
                old_bitmap = save_dc.SelectObject(save_bit_map)
                
                # 使用 PrintWindow API 后台截图
                result = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
                
                if result == 1:  # 成功
                    # 转换为 numpy 数组
                    bmp_info = save_bit_map.GetInfo()
                    bmp_str = save_bit_map.GetBitmapBits(True)
                    img = np.frombuffer(bmp_str, dtype=np.uint8)
                    img.shape = (bmp_info['bmHeight'], bmp_info['bmWidth'], 4)  # BGRA
                    
                    # 转换为 BGR 格式
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    return img
                else:
                    return None
                    
            finally:
                # 确保所有资源都被正确释放 - 关键修复点
                try:
                    if old_bitmap and save_dc:
                        save_dc.SelectObject(old_bitmap)
                except Exception as e:
                    CUS_LOGGER.warning(f"恢复位图选择失败: {e}")
                    
                try:
                    if save_bit_map:
                        win32gui.DeleteObject(save_bit_map.GetHandle())
                except Exception as e:
                    CUS_LOGGER.warning(f"删除位图对象失败: {e}")
                    
                try:
                    if save_dc:
                        save_dc.DeleteDC()
                except Exception as e:
                    CUS_LOGGER.warning(f"删除保存DC失败: {e}")
                    
                try:
                    if mfc_dc:
                        mfc_dc.DeleteDC()
                except Exception as e:
                    CUS_LOGGER.warning(f"删除MFC DC失败: {e}")
                    
                try:
                    if hwnd_dc:
                        win32gui.ReleaseDC(hwnd, hwnd_dc)
                except Exception as e:
                    CUS_LOGGER.warning(f"释放窗口DC失败: {e}")
                    
        except Exception as e:
            CUS_LOGGER.warning(f"后台截图窗口失败: {e}")
            # 发生异常时也要确保资源清理
            import gc
            gc.collect()
            return None

    def start_recording(self,timestamp):
        """开始录制指定窗口"""
        CUS_LOGGER.debug(f"启动录制{timestamp}")
        if self.recording:
            CUS_LOGGER.info("Already recording")
            return
        self.output_file = self.output_path + f"{timestamp}轮回.mp4"
        # 查找目标窗口
        if not self.hwnd:
            self.hwnd = win32gui.FindWindow(self.window_class_name, self.window_title)
            CUS_LOGGER.info(f"找到窗口句柄: {self.hwnd}")
            
        if not self.hwnd:
            if self.window_class_name:
                CUS_LOGGER.error(f"未找到类名为 '{self.window_class_name}' 且标题包含 '{self.window_title}' 的窗口")
                raise ValueError(f"未找到类名为 '{self.window_class_name}' 且标题包含 '{self.window_title}' 的窗口")
            else:
                CUS_LOGGER.error(f"未找到标题包含 '{self.window_title}' 的窗口")
                raise ValueError(f"未找到标题包含 '{self.window_title}' 的窗口")
        
        # 确保窗口可见且有效
        if not win32gui.IsWindowVisible(self.hwnd):
            CUS_LOGGER.warning("警告: 窗口不可见")
            
        if not win32gui.IsWindow(self.hwnd):
            CUS_LOGGER.error("窗口句柄无效")
            raise ValueError("窗口句柄无效")

        # 设置DPI感知
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 2 = Per-monitor v2 DPI awareness
        except Exception as e:
            CUS_LOGGER.warning(f"无法设置DPI感知级别: {e}")
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception as e:
                CUS_LOGGER.warning(f"无法设置DPI感知级别(备用方法): {e}")
        
        # 获取窗口位置和尺寸
        try:
            # 获取窗口位置
            rect = win32gui.GetWindowRect(self.hwnd)
            self.left, self.top, self.right, self.bottom = rect
            self.width = self.right - self.left
            self.height = self.bottom - self.top
            
            CUS_LOGGER.info(f"窗口位置: ({self.left}, {self.top}, {self.right}, {self.bottom}), 尺寸: {self.width}x{self.height}")
        except Exception as e:
            CUS_LOGGER.error(f"获取窗口位置失败: {e}")
            raise

        # 确保输出目录存在
        import os
        output_dir = os.path.dirname(self.output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # 应用偏移后的实际录制尺寸
        actual_width = self.width - self.offsets[0] - self.offsets[2]  # 减去左右偏移
        actual_height = self.height - self.offsets[1] - self.offsets[3]  # 减去上下偏移
        
        # 设置视频写入器
        CUS_LOGGER.info(f"初始化视频写入器，尺寸: {actual_width}x{actual_height}")
        self.out = cv2.VideoWriter(
            self.output_file,
            cv2.VideoWriter_fourcc(*'mp4v'),
            self.fps,
            (actual_width, actual_height)
        )
        
        if not self.out.isOpened():
            CUS_LOGGER.error("无法初始化视频写入器")
            raise RuntimeError("无法初始化视频写入器")

        # 启动录制线程
        self.recording = True
        self.recording_thread = ThreadWithException(target=self._record_window, daemon=True,name="视频录制")
        self.recording_thread.start()

    def _record_window(self):
        """实际的窗口录制线程"""
        try:
            while self.recording:
                try:
                    # 应用偏移值来收缩录制范围 [left, top, right, bottom]
                    adjusted_left = self.left + self.offsets[0]
                    adjusted_top = self.top + self.offsets[1]
                    adjusted_right = self.right - self.offsets[2]
                    adjusted_bottom = self.bottom - self.offsets[3]
                    
                    # 使用ImageGrab直接捕获窗口区域
                    bbox = (adjusted_left, adjusted_top, adjusted_right, adjusted_bottom)
                    img = ImageGrab.grab(bbox=bbox)
                    
                    # 转换为OpenCV格式
                    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                    
                    # 检查是否需要叠加地图窗口
                    if self.overlay_map:
                        # 尝试查找地图窗口（"Map"窗口）
                        map_hwnd = win32gui.FindWindow(None, "Map")
                        if map_hwnd:
                            try:
                                # 使用后台截图方式获取地图窗口图像
                                map_img_cv = self.capture_window_background(map_hwnd)
                                
                                if map_img_cv is not None:
                                    # 进一步缩小地图图像尺寸
                                    map_scale = 0.3  # 缩放到原图的10%，更小一些
                                    map_resized_width = int(img_cv.shape[1] * map_scale)  # 基于主窗口宽度计算
                                    map_resized_height = int(map_resized_width * (map_img_cv.shape[0] / map_img_cv.shape[1]))  # 保持比例
                                    map_img_resized = cv2.resize(map_img_cv, (map_resized_width, map_resized_height))
                                    
                                    # 将调整后的地图图像叠加到主图像的左下角上方（带透明度）
                                    margin = 10
                                    # 计算时间戳区域的高度
                                    # 预先计算时间戳尺寸，以便地图放置在时间戳上方
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
                                        max_text_width = max(text_width1, text_height2)
                                        total_text_height = text_height1 + text_height2 + line_spacing

                                        # 优化背景框尺寸计算
                                        rect_width = max_text_width + h_padding * 2
                                        rect_height = total_text_height + v_padding * 2

                                        # 将地图放在时间戳上方
                                        timestamp_bottom_y = img_cv.shape[0] - 5
                                        timestamp_top_y = timestamp_bottom_y - rect_height
                                        map_bottom_y = timestamp_top_y - margin  # 地图在时间戳上方，留出间距
                                        map_top_y = map_bottom_y - map_resized_height
                                        
                                        # 确保地图在窗口范围内
                                        if map_top_y > margin:  # 如果地图放置在时间戳上方后仍在窗口内
                                            # 实现透明度叠加
                                            roi = img_cv[map_top_y:map_bottom_y, margin:margin+map_resized_width]
                                            # 将地图图像转换为相同数据类型
                                            map_img_resized = map_img_resized.astype(np.float32)
                                            roi = roi.astype(np.float32)
                                            # 使用加权叠加实现透明效果
                                            cv2.addWeighted(map_img_resized, self.map_alpha, roi, 1-self.map_alpha, 0, roi)
                                            # 转换回uint8并更新原图像
                                            img_cv[map_top_y:map_bottom_y, margin:margin+map_resized_width] = roi.astype(np.uint8)
                                        else:
                                            # 如果放不下，则不叠加地图
                                            pass
                                    else:
                                        # 如果不需要时间戳，将地图放在左下角（带透明度）
                                        roi = img_cv[img_cv.shape[0]-map_resized_height-margin:img_cv.shape[0]-margin, 
                                                    margin:margin+map_resized_width]
                                        # 将地图图像转换为相同数据类型
                                        map_img_resized = map_img_resized.astype(np.float32)
                                        roi = roi.astype(np.float32)
                                        # 使用加权叠加实现透明效果
                                        cv2.addWeighted(map_img_resized, self.map_alpha, roi, 1-self.map_alpha, 0, roi)
                                        # 转换回uint8并更新原图像
                                        img_cv[img_cv.shape[0]-map_resized_height-margin:img_cv.shape[0]-margin, 
                                              margin:margin+map_resized_width] = roi.astype(np.uint8)
                                else:
                                    CUS_LOGGER.warning("后台获取地图窗口失败，跳过叠加")
                            except Exception as e:
                                CUS_LOGGER.warning(f"叠加地图窗口失败: {e}")
                                # 如果叠加地图失败，继续录制主窗口
                                pass

                    # 添加时间戳（如果需要）
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

                        # 计算左下角位置（距离底部和左边5像素）
                        bottom_y = img_cv.shape[0] - 5
                        left_x = 5

                        # 绘制白色背景矩形
                        cv2.rectangle(img_cv,
                                      (left_x, bottom_y - rect_height),
                                      (left_x + rect_width, bottom_y),
                                      (255, 255, 255),
                                      -1)

                        # 优化文字绘制位置
                        line1_y = bottom_y - rect_height + v_padding + text_height1
                        line2_y = line1_y + text_height2 + line_spacing

                        cv2.putText(img_cv, current_date,
                                    (left_x + h_padding, line1_y),
                                    font,
                                    font_scale,
                                    (0, 0, 255),
                                    font_thickness)

                        cv2.putText(img_cv, current_time,
                                    (left_x + h_padding, line2_y),
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
                            CUS_LOGGER.info("用户按 q 键，停止录制")
                            self.stop_recording()
                            break

                    # 控制帧率
                    time.sleep(1 / self.fps)
                    
                except Exception as e:
                    CUS_LOGGER.warning(f"录制单帧时发生错误: {e}")
                    continue

        except Exception as e:
            import traceback
            traceback.print_exc()
        finally:
            # 释放资源
            if self.out:
                self.out.release()
                self.out = None
            CUS_LOGGER.info("视频写入器已释放")

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        if self.out:
            self.out.release()
            self.out = None
        CUS_LOGGER.debug(f"停止录制{self.output_file}")


if __name__ == "__main__":
    try:
        window_title = "崩坏：星穹铁道"
        output_file = "../logs/video/test_recording_"
        fps = 10

        CUS_LOGGER.info("=== 窗口录制器测试 (带透明度地图叠加) ===")
        CUS_LOGGER.info("准备开始录制（5秒后自动停止）...")
        CUS_LOGGER.info(f"请在5秒内打开窗口：{window_title}")
        CUS_LOGGER.info("地图将以60%透明度叠加显示在左下角")
        time.sleep(2)

        # 创建带透明度的地图叠加录制器
        recorder = WindowRecorder(
            output_file=output_file, 
            fps=fps, 
            window_title=window_title,
            window_class_name="UnityWndClass", 
            offsets=[10, 50, 10, 10],
            overlay_map=True,      # 启用地图叠加
            map_alpha=0.6,         # 60%透明度
            see_time=True          # 显示时间戳
        )
        
        recorder.start_recording()
        CUS_LOGGER.info(f"正在录制窗口：{window_title}")
        CUS_LOGGER.info("录制将持续5秒，请在目标窗口中进行一些操作")
        CUS_LOGGER.info("地图窗口会以半透明形式显示在录制画面左下角")

        time.sleep(5)

        recorder.stop_recording()
        CUS_LOGGER.info("录制已完成！")
        CUS_LOGGER.info(f"视频已保存为：{recorder.output_file}")
        CUS_LOGGER.info("请检查生成的视频文件，确认透明度叠加效果正常")

    except Exception as e:
        CUS_LOGGER.error(f"发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
