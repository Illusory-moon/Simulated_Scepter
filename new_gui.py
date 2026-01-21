import ctypes
import json
import logging
import sys
import threading
import os
import shutil
import keyboard
import time

import pyuac

from utils.log import CUS_LOGGER, log_emitter
from config import EXTRA
from route import PATHS

from utils.simul.config import config as config_simul
from utils.diver.config import config as config_diver

from align_angle import main as align_angle_main
from logger_printer import QMainWindowLog
from PyQt5.QtWidgets import (
    QApplication, QLineEdit, QMessageBox)
from PyQt5.QtCore import pyqtSignal, Qt
from pathlib import Path
from simul import SimulatedUniverse
from diver import DivergentUniverse
from iron_blood import IronBloodUniverse




class TaskManager:
    """
    任务管理器，负责运行和控制各种任务
    """
    def __init__(self):
        self.current_task = None
        self.task_thread = None

    def start_task(self, task_func, *args, **kwargs):
        """
        启动一个新任务
        """
        if self.is_task_running():
            raise RuntimeError("已有任务正在运行")

        self.task_thread = TaskThread(target=self._task_wrapper, args=(task_func, args, kwargs))
        self.task_thread.start()

    def _task_wrapper(self, task_func, args, kwargs):
        """
        包装任务函数，用于设置和清理current_task
        """
        try:
            self.current_task = object()
            task_func(*args, **kwargs)
        except Exception as e:
            import traceback
            error_msg = f"{traceback.format_exc()}"
            log_emitter.show_error_signal.emit(f"任务执行过程中发生异常：{str(e)}", error_msg)
            CUS_LOGGER.error(error_msg)

        finally:
            self.current_task = None
            self.task_thread = None

    def is_task_running(self):
        """
        检查是否有任务正在运行
        """
        return self.task_thread is not None and self.task_thread.is_alive()

    def stop_task(self):
        """
        停止当前任务
        """
        if self.current_task and hasattr(self.current_task, 'stop'):
            self.current_task.stop()
            self.task_thread=None
            return True
        return False

    def kill_task(self):
        """
        直接终止当前任务线程，包括其创建的所有子线程
        """
        if self.task_thread and self.task_thread.is_alive():
            import ctypes
            import time
            
            # 首先尝试正常方式通知任务停止
            if self.current_task and hasattr(self.current_task, 'stop'):
                try:
                    self.current_task.stop()
                    time.sleep(0.2)
                except:
                    pass
            if self.task_thread.is_alive():
                thread_id = self.task_thread.ident
                res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                    ctypes.c_long(thread_id),
                    ctypes.py_object(SystemExit)
                )

                timeout = 3
                start_time = time.time()
                while self.task_thread.is_alive() and (time.time() - start_time) < timeout:
                    time.sleep(0.1)

                if self.task_thread.is_alive():
                    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                        ctypes.c_long(thread_id),
                        ctypes.py_object(SystemExit)
                    )
                    time.sleep(0.5)
                    
            self.task_thread = None
            self.current_task = None
            return True
        return False


class TaskThread(threading.Thread):
    def __init__(self, target, args=None, kwargs=None):
        super().__init__()
        self.target = target
        self.args = args if args is not None else ()
        self.kwargs = kwargs if kwargs is not None else {}
        self.daemon = True

    def run(self):
        self.target(*self.args, **self.kwargs)
            
    def join(self, timeout=None):
        super().join(timeout)


class MainWindow(QMainWindowLog):
    calibration_finished = pyqtSignal(object)
    f5_pressed = pyqtSignal()
    f6_pressed = pyqtSignal()
    f7_pressed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.task_manager = TaskManager()
        self._last_key_time = {}  # 合并f5,f6,f7时间记录

        self.init_ui()
        self.setup_keyboard_listener()
        # 连接F5/F6/F7按键信号到处理函数
        self.f5_pressed.connect(lambda: self.handle_key_pressed("f5"))
        self.f6_pressed.connect(lambda: self.handle_key_pressed("f6"))
        self.f7_pressed.connect(lambda: self.handle_key_pressed("f7"))
        log_emitter.show_error_signal.connect(self.show_error_message)
    
    def show_error_message(self, title, error_msg):
        """显示错误消息弹窗，支持复制内容并强制置顶"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("出错了！！！")
        msg.setText(title)
        msg.setStandardButtons(QMessageBox.Ok)
        
        # 设置窗口标志，确保弹窗置顶显示
        msg.setWindowFlags(msg.windowFlags() | Qt.WindowStaysOnTopHint)
        
        # 设置详细文本，这样用户可以选中并复制内容
        msg.setDetailedText(error_msg)
        
        # 显示弹窗并强制置顶
        msg.show()
        msg.raise_()
        msg.activateWindow()
        
        # 等待用户关闭弹窗
        msg.exec_()


    def init_ui(self):
        # 连接按钮信号
        self.run_simul_btn.clicked.connect(self.run_simul)
        self.run_diver_btn.clicked.connect(self.run_diver)
        self.iron_blood_btn.clicked.connect(self.run_iron_blood)
        self.calibrate_btn.clicked.connect(self.calibrate)
        self.test_btn.clicked.connect(self.test)
        self.print_btn.clicked.connect(self.test_2)
        self.stop_btn.clicked.connect(self.stop_task)
        self.clear_logs_btn.clicked.connect(self.clear_logs)

        # 初始化模拟宇宙配置界面
        self.Simul_bonus_checkbox.setChecked(bool(config_simul.bonus))
        self.Simul_debug_checkbox.setChecked(bool(config_simul.debug_mode))
        self.Simul_speed_checkbox.setChecked(bool(config_simul.speed_mode))
        self.Simul_slow_checkbox.setChecked(bool(config_simul.slow_mode))
        self.Simul_difficulty_combo.addItems(["1", "2", "3", "4", "5"])
        self.Simul_difficulty_combo.setCurrentText(str(config_simul.difficult))
        self.Simul_fate_combo.addItems([
            "存护", "记忆", "虚无", "丰饶", "巡猎", "毁灭", "欢愉", "繁育", "智识"
        ])
        self.Simul_fate_combo.setCurrentText(config_simul.fate)
        self.Simul_timezone_combo.addItems(["Default", "Asia", "America", "Europe"])
        self.Simul_timezone_combo.setCurrentText(config_simul.timezone)
        self.Simul_max_run_input = QLineEdit(str(config_simul.max_run))

        # 初始化差分宇宙配置界面
        self.Diver_debug_checkbox.setChecked(bool(config_diver.debug_mode))
        self.Diver_speed_checkbox.setChecked(bool(config_diver.speed_mode))
        self.Diver_weekly_checkbox.setChecked(bool(config_diver.weekly_mode))
        self.Diver_cpu_checkbox.setChecked(bool(config_diver.cpu_mode))
        self.Diver_difficulty_combo.addItems(["1", "2", "3", "4", "5"])
        self.Diver_difficulty_combo.setCurrentText(str(config_diver.difficult))
        self.Diver_team_combo.addItems(["追击", "dot", "终结技", "击破", "盾反"])
        self.Diver_save_cnt_combo.addItems(["0", "1", "2", "3", "4"])
        self.Diver_save_cnt_combo.setCurrentText(str(config_diver.save_cnt))
        self.Diver_timezone_combo.addItems(["Default", "Asia", "America", "Europe"])
        self.Diver_timezone_combo.setCurrentText(config_diver.timezone)
        self.Diver_max_run_input = QLineEdit(str(config_diver.max_run))

        # 连接配置保存按钮
        self.config_save_btn.clicked.connect(self.save_config)
        
        # 初始化recording_checkBox状态
        with EXTRA.FILE_LOCK:
            with open(PATHS["root"] + "\\config\\config\\settings.json", mode="r", encoding="UTF-8") as file:
                data = json.load(file)
        
        recording_state = data.get("recording_state", True)
        self.recording_checkBox.setChecked(recording_state)

        self.calibration_finished.connect(self.show_calibration_result)



    def setup_keyboard_listener(self):
        """
        设置键盘监听器，监听F5/F6/F7按键
        """
        keyboard.on_press_key("f5", self._on_key_pressed)
        keyboard.on_press_key("f6", self._on_key_pressed)
        keyboard.on_press_key("f7", self._on_key_pressed)

    def save_recording_checkbox_state_to_settings(self):
        """保存recording_checkBox的状态到settings.json"""
        
        with EXTRA.FILE_LOCK:
            with open(PATHS["root"] + "\\config\\config\\settings.json", mode="r", encoding="UTF-8") as file:
                data = json.load(file)
        
        data["recording_state"] = self.recording_checkBox.isChecked()
        
        with EXTRA.FILE_LOCK:
            with open(PATHS["root"] + "\\config\\config\\settings.json", mode="w", encoding="UTF-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=4)

    def _on_key_pressed(self, event):
        """
        当F5/F6/F7按键被按下时的回调函数
        """
        current_time = time.time()
        key = event.name.lower()
        
        # 只处理F5/F6/F7按键
        if key in ["f5", "f6", "f7"]:
            last_time = self._last_key_time.get(key, 0)
            if current_time - last_time > 1:  # 1秒防重复
                self._last_key_time[key] = current_time
                if key == "f5":
                    self.f5_pressed.emit()
                elif key == "f6":
                    self.f6_pressed.emit()
                elif key == "f7":
                    self.f7_pressed.emit()
            
    def handle_key_pressed(self, key):
        """
        统一处理F5/F6/F7按键事件
        """
        if key == "f5":
            if self.task_manager.is_task_running():
                self.stop_btn.click()
        elif key == "f6":
            if self.task_manager.is_task_running():
                QMessageBox.warning(self, "警告", "已有任务正在运行")
            else:
                self.test_btn.click()
        elif key == "f7":
            if self.task_manager.is_task_running():
                QMessageBox.warning(self, "警告", "已有任务正在运行")
            else:
                self.print_btn.click()
        
    def closeEvent(self, event):
        """
        窗口关闭事件，清理键盘监听器
        """
        keyboard.unhook_all()
        super().closeEvent(event)
        
    def clear_logs(self):
        """
        清除logs目录下的所有文件，跳过被占用的文件
        """
        try:
            logs_dir = "logs"
            if not os.path.exists(logs_dir):
                QMessageBox.warning(self, "警告", "日志目录不存在")
                return

            failed_files = []
            success_count = 0

            # 删除logs目录下的所有文件和子目录
            for filename in os.listdir(logs_dir):
                file_path = os.path.join(logs_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                    success_count += 1
                except Exception as e:
                    failed_files.append(filename)

            if failed_files:
                QMessageBox.warning(
                    self, 
                    "完成（部分失败）", 
                    f"成功删除 {success_count} 个文件/目录\n以下文件/目录删除失败:\n" + "\n".join(failed_files)
                )
            else:
                QMessageBox.information(self, "成功", f"成功删除 {success_count} 个文件/目录")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"清除日志失败: {str(e)}")

    def test(self):
        from utils.diver.args import args
        
        def task():
            args.cpu = int(config_diver.cpu_mode)
            su = DivergentUniverse(
                int(config_diver.debug_mode),
                int(config_diver.max_run),
                int(config_diver.speed_mode)
            )
            self.task_manager.current_task = su
            su.screen_test()
            
        try:
            self.task_manager.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))

    def test_2(self):
        from utils.diver.args import args

        def task():
            args.cpu = int(config_diver.cpu_mode)
            su = DivergentUniverse(
                int(config_diver.debug_mode),
                int(config_diver.max_run),
                int(config_diver.speed_mode)
            )
            self.task_manager.current_task = su
            print_text = self.PrintEdit.text()
            if self.PrintPhoto.isChecked():
                su.click_target(f'test/{print_text}', 0.9, True, use_binary=False)
            elif self.PrintText.isChecked():
                su.click_text(print_text,click=0)
            else:
                su.click_text(print_text,click=1)

        try:
            self.task_manager.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))
    def stop_task(self):
        try:
            if self.task_manager.kill_task():
                QMessageBox.information(self, "提示", "任务线程已终止")
        except Exception as e:
            pass
        
    def run_simul(self):
        def task():
            su = SimulatedUniverse(
                1,
                int(config_simul.debug_mode),
                int(config_simul.speed_mode),
                int(config_simul.use_consumable),
                int(config_simul.slow_mode),
                int(config_simul.max_run),
                bonus=config_simul.bonus,
                gui=self
            )
            self.task_manager.current_task = su
            su.start()

            
        try:
            self.task_manager.start_task(task)
        except RuntimeError as r:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", str(e))

    def run_diver(self):
        from utils.diver.args import args
        
        def task():
            args.cpu = int(config_diver.cpu_mode)
            su = DivergentUniverse(
                int(config_diver.debug_mode),
                int(config_diver.max_run),
                int(config_diver.speed_mode)
            )
            self.task_manager.current_task = su
            su.start()
            
        try:
            self.task_manager.start_task(task)
        except RuntimeError as r:
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def run_iron_blood(self):
        def task():
            su = IronBloodUniverse(
                1,
                int(config_simul.debug_mode),
                int(config_simul.speed_mode),
                int(config_simul.use_consumable),
                int(config_simul.slow_mode),
                int(config_simul.max_run),
                bonus=config_simul.bonus,
                gui=self
            )
            self.task_manager.current_task = su
            su.start()

        try:
            self.task_manager.start_task(task)
        except RuntimeError as r:
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def calibrate(self):
        def task():
            try:
                res = align_angle_main()
                self.calibration_finished.emit(res)
            except Exception as e:
                self.calibration_finished.emit(e)
            
        try:
            self.task_manager.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))

    def show_calibration_result(self, result):
        if isinstance(result, Exception):
            QMessageBox.critical(self, "错误", f"校准失败: {str(result)}")
        elif result == 1:
            QMessageBox.information(self, "成功", "校准成功！")
        else:
            QMessageBox.warning(self, "失败", "校准失败，请重试。")


    def save_config(self):
        # 保存模拟宇宙配置
        config_simul.bonus = int(self.Simul_bonus_checkbox.isChecked())
        config_simul.debug_mode = int(self.Simul_debug_checkbox.isChecked())
        config_simul.speed_mode = int(self.Simul_speed_checkbox.isChecked())
        config_simul.slow_mode = int(self.Simul_slow_checkbox.isChecked())
        config_simul.difficult = self.Simul_difficulty_combo.currentText()
        config_simul.fate = self.Simul_fate_combo.currentText()
        config_simul.timezone = self.Simul_timezone_combo.currentText()
        try:
            config_simul.max_run = int(self.Simul_max_run_input.text())
        except ValueError:
            pass
            
        # 保存差分宇宙配置
        config_diver.debug_mode = int(self.Diver_debug_checkbox.isChecked())
        config_diver.speed_mode = int(self.Diver_speed_checkbox.isChecked())
        config_diver.weekly_mode = int(self.Diver_weekly_checkbox.isChecked())
        config_diver.cpu_mode = int(self.Diver_cpu_checkbox.isChecked())
        config_diver.difficult = self.Diver_difficulty_combo.currentText()
        config_diver.team = self.Diver_team_combo.currentText()
        config_diver.timezone = self.Diver_timezone_combo.currentText()
        config_diver.save_cnt = int(self.Diver_save_cnt_combo.currentText())
        try:
            config_diver.max_run = int(self.Diver_max_run_input.text())
        except ValueError:
            pass

        # 保存配置到文件
        config_simul.save()
        config_diver.save()
        
        # 保存recording_checkBox状态到settings.json
        self.save_recording_checkbox_state_to_settings()
        
        QMessageBox.information(self, "提示", "配置已保存")

    def set_FPS(self,TimePerFrame):
        Fps = 1.0 / float(TimePerFrame)
        Fps = round(Fps, 2)
        self.FPS_Input.setText(str(Fps))

    def set_find_path_state(self, text:str):
        self.state_text.setText(text)
def main(show):
    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False


    # 以管理员权限重新运行程序，使用pythonw避免命令行窗口
    def run_as_admin():
        script = Path(sys.argv[0]).resolve()
        if show:
            ex="python.exe"
        else:
            ex="pythonw.exe"
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                ex,
                f'"{script}"',
                None,
                1
            )
            return True
        except:
            return False


    if not is_admin():

        if run_as_admin():
            sys.exit(0)
        else:
            import tkinter
            from tkinter import messagebox

            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("权限错误", "此程序需要管理员权限才能正常运行。请右键点击程序并选择'以管理员身份运行'。")
            root.destroy()
    else:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        app.exec_()
if __name__ == "__main__":
    main(1)