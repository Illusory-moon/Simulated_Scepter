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
from utils.thread import ThreadWithException
from config import EXTRA
from route import PATHS
from utils.utils.image_tool import load_all_images_from_directory, find_image_by_name
load_all_images_from_directory()
from utils.simul.config import config as config_simul
from utils.diver.config import config as config_diver

from align_angle import main as align_angle_main
from logger_printer import QMainWindowLog
from PyQt5.QtWidgets import (
    QApplication, QLineEdit, QMessageBox)
from PyQt5.QtCore import pyqtSignal, Qt
from simul import SimulatedUniverse
from diver import DivergentUniverse
from iron_blood import IronBloodUniverse

import faulthandler




class MainWindow(QMainWindowLog):
    calibration_finished = pyqtSignal(object)
    f5_pressed = pyqtSignal()
    f6_pressed = pyqtSignal()
    f7_pressed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        # 任务管理相关属性
        self.current_task = None
        self.task_thread = None
        self._last_key_time = {}
            
        # 加载快捷键配置并注册监听器
        self.hotkey_config = self.load_hotkey_config()
        self.registered_hotkeys = []
    
        self.init_ui()
        self.setup_keyboard_listener()
        # 连接F5/F6/F7按键信号到处理函数
        self.f5_pressed.connect(lambda: self.handle_key_pressed("f5"))
        self.f6_pressed.connect(lambda: self.handle_key_pressed("f6"))
        self.f7_pressed.connect(lambda: self.handle_key_pressed("f7"))
        log_emitter.show_error_signal.connect(self.show_error_message)
        log_emitter.find_path_state_signal.connect(self.set_find_path_state)
        log_emitter.kill_num_signal.connect(self.set_kill_num)
        log_emitter.fps_update_signal.connect(self.set_FPS)
    
    def start_task(self, task_func):
        """
        启动一个新任务
        """
        if self.is_task_running():
            raise RuntimeError("已有任务正在运行")
        self.task_thread = ThreadWithException(target=task_func,name="主任务线程")
        self.task_thread.start()

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
            self.task_thread = None
            self.current_task = None
            return True
        return False


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
        self.Iron_blood_save_btn.clicked.connect(self.save_iron_config)

        with EXTRA.FILE_LOCK:
            with open(PATHS["root"] + "\\config\\config\\settings.json", mode="r", encoding="UTF-8") as file:
                data = json.load(file)
        self.recording_checkBox.setChecked(data.get("recording_state", True))
        self.recording_checkBox2.setChecked(data.get("recording_iron_blood", True))
        self.recording_label_checkbox.setChecked(data.get("record_add_label", True))
        self.early_stop_checkbox.setChecked(data.get("early_stop", False))
        self.recording_time_input.setText(str(data.get("del_record_time", 31)))
        self.Iron_blood_max_run_input.setText(str(int(data.get("max_run_time", 0))))
        self.Iron_blood_first_plane_input.setText(str(data.get("first_plane", 14)))
        self.Iron_blood_second_plane_input.setText(str(data.get("second_plane", 31)))
        self.debug_checkox2.setChecked(data.get("debug", True))
        
        # 初始化快捷键配置输入框
        hotkey_config = data.get("hotkeys", {})
        self.stop_hotkey_input.setText(hotkey_config.get("stop", "f5"))
        self.test_hotkey_input.setText(hotkey_config.get("test", "f6"))
        self.print_hotkey_input.setText(hotkey_config.get("print", "f7"))
        
        # 更新按钮文本显示当前快捷键
        self.update_button_hotkey_text(hotkey_config)
        
        # 设置控件的启用/禁用状态
        self.update_dependent_controls_state()
        
        # 连接信号以实现动态更新
        self.connect_dependency_signals()
    
    def load_hotkey_config(self):
        """从 settings.json 加载快捷键配置"""
        default_config = {
            "stop": "f5",
            "test": "f6",
            "print": "f7"      
        }
            
        try:
            with EXTRA.FILE_LOCK:
                with open(PATHS["root"] + "\\config\\config\\settings.json", mode="r", encoding="UTF-8") as file:
                    data = json.load(file)
                
            hotkey_config = data.get("hotkeys", default_config)
                
            # 确保所有必需的快捷键都存在
            for key in ["stop", "test", "print"]:
                if key not in hotkey_config:
                    hotkey_config[key] = default_config[key]
                
            return hotkey_config
        except Exception as e:
            print(f"加载快捷键配置失败：{e}，使用默认配置")
            return default_config
        
    def setup_keyboard_listener(self):
        """
        设置键盘监听器，根据 UI 配置监听自定义快捷键
        """
        # 使用当前 hotkey_config 注册快捷键监听
        for action, key in self.hotkey_config.items():
            if key and key.lower() != "none":
                keyboard.on_press_key(key.lower(), lambda event, act=action: self._on_hotkey_pressed(event, act))
                self.registered_hotkeys.append(key.lower())

    def save_ui_settings(self):
        """保存 ui 的状态到 settings.json"""
            
        with EXTRA.FILE_LOCK:
            with open(PATHS["root"] + "\\config\\config\\settings.json", mode="r", encoding="UTF-8") as file:
                data = json.load(file)
            
        data["recording_state"] = self.recording_checkBox.isChecked()
        data["recording_iron_blood"] = self.recording_checkBox2.isChecked()
        data["record_add_label"] = self.recording_label_checkbox.isChecked()
        data["early_stop"] = self.early_stop_checkbox.isChecked()
        data["del_record_time"] = int(self.recording_time_input.text())
        data["max_run_time"] = int(self.Iron_blood_max_run_input.text())
        data["first_plane"] = int(self.Iron_blood_first_plane_input.text())
        data["second_plane"] = int(self.Iron_blood_second_plane_input.text())
        data["debug"] = self.debug_checkox2.isChecked()
            
        # 保存快捷键配置
        data["hotkeys"] = {
            "stop": self.stop_hotkey_input.text().strip(),
            "test": self.test_hotkey_input.text().strip(),
            "print": self.print_hotkey_input.text().strip()
        }
    
        with EXTRA.FILE_LOCK:
            with open(PATHS["root"] + "\\config\\config\\settings.json", mode="w", encoding="UTF-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
        self.hotkey_config = data["hotkeys"]
        self.refresh_keyboard_listener()
        self.update_button_hotkey_text(self.hotkey_config)

    def _on_hotkey_pressed(self, event, action):
        """
        当自定义快捷键被按下时的回调函数
        """
        current_time = time.time()
        key = event.name.lower()
            
        # 防重复触发
        last_time = self._last_key_time.get(key, 0)
        if current_time - last_time > 1:
            self._last_key_time[key] = current_time
                
            # 根据动作类型处理
            if action == "stop":
                if self.is_task_running():
                    self.stop_btn.click()
            elif action == "test":
                if self.is_task_running():
                    QMessageBox.warning(self, "警告", "已有任务正在运行")
                else:
                    self.test_btn.click()
            elif action == "print":
                if self.is_task_running():
                    QMessageBox.warning(self, "警告", "已有任务正在运行")
                else:
                    self.print_btn.click()
        
    def update_button_hotkey_text(self, hotkey_config):
        stop_key = hotkey_config.get("stop", "f5").upper()
        test_key = hotkey_config.get("test", "f6").upper()
        print_key = hotkey_config.get("print", "f7").upper()
        
        self.stop_btn.setText(f"停止任务 {stop_key}")
        self.test_btn.setText(f"截图测试 {test_key}")
        self.print_btn.setText(f"打印坐标 {print_key}")
    
    def refresh_keyboard_listener(self):
        keyboard.unhook_all()
        self.registered_hotkeys.clear()
        for action, key in self.hotkey_config.items():
            if key and key.lower() != "none":
                keyboard.on_press_key(key.lower(), lambda event, act=action: self._on_hotkey_pressed(event, act))
                self.registered_hotkeys.append(key.lower())
    
    def update_dependent_controls_state(self):
        debug_and_recording = self.debug_checkox2.isChecked() and self.recording_checkBox2.isChecked()
        self.recording_label_checkbox.setEnabled(debug_and_recording)
        self.recording_time_input.setEnabled(self.recording_checkBox2.isChecked())
        early_stop_enabled = self.early_stop_checkbox.isChecked()
        self.Iron_blood_first_plane_input.setEnabled(early_stop_enabled)
        self.Iron_blood_second_plane_input.setEnabled(early_stop_enabled)
    
    def connect_dependency_signals(self):
        self.debug_checkox2.stateChanged.connect(lambda: self.update_dependent_controls_state())
        self.recording_checkBox2.stateChanged.connect(lambda: self.update_dependent_controls_state())
        self.recording_checkBox2.stateChanged.connect(lambda: self.update_dependent_controls_state())
        self.early_stop_checkbox.stateChanged.connect(lambda: self.update_dependent_controls_state())
    
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
        def task():
            su = SimulatedUniverse(
                1,
                int(config_simul.debug_mode),
                int(config_simul.speed_mode),
                int(config_simul.use_consumable),
                int(config_simul.slow_mode),
                int(config_simul.max_run),
                bonus=config_simul.bonus
            )
            self.current_task = su
            su.save_screen()
            
        try:
            self.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))

    def test_2(self):

        def task():
            su = SimulatedUniverse(
                1,
                int(config_simul.debug_mode),
                int(config_simul.speed_mode),
                int(config_simul.use_consumable),
                int(config_simul.slow_mode),
                int(config_simul.max_run),
                bonus=config_simul.bonus
            )
            self.current_task = su
            print_text = self.PrintEdit.text()
            if self.PrintPhoto.isChecked():
                su.click_target(find_image_by_name(print_text), 0.9, True, use_binary=False)
            elif self.PrintText.isChecked():
                su.click_text(print_text,click=0,find_all=True)
            else:
                su.click_text(print_text,click=1)

        try:
            self.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))
    def run_simul(self):
        def task():
            su = SimulatedUniverse(
                1,
                int(config_simul.debug_mode),
                int(config_simul.speed_mode),
                int(config_simul.use_consumable),
                int(config_simul.slow_mode),
                int(config_simul.max_run),
                bonus=config_simul.bonus
            )
            self.current_task = su
            su.start()

            
        try:
            self.start_task(task)
        except RuntimeError as r:
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
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
            self.current_task = su
            su.start()
            
        try:
            self.start_task(task)
        except RuntimeError as r:
            QMessageBox.warning(self, "警告", str(r))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def run_iron_blood(self):
        def task():
            su = IronBloodUniverse()
            self.current_task = su
            su.start()

        try:
            self.start_task(task)
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
            self.start_task(task)
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

        self.save_ui_settings()
        
        QMessageBox.information(self, "提示", "配置已保存")
    def save_iron_config(self):
        self.save_ui_settings()
        QMessageBox.information(self, "提示", "配置已保存")
    def set_FPS(self,TimePerFrame):
        Fps = 1.0 / float(TimePerFrame)
        Fps = round(Fps, 2)
        self.FPS_Input.setText(str(Fps))

    def set_find_path_state(self, text:str):
        self.state_text.setText(text)
    def set_kill_num(self, num:str):
        self.kill_num_text.setText(num)
def main(show):
    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False


    # 以管理员权限重新运行程序，使用pythonw避免命令行窗口
    def run_as_admin():
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                sys.executable,
                __file__,
                None,
                show
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
        try:
            sys.exit(app.exec())
        except SystemExit as e:
            print(f"异常退出，进程已结束,退出代码:{e.code}")
            input("按Enter键退出...")
if __name__ == "__main__":
    fault_log_file = open("logs/crash_dump.txt", "w", encoding="utf-8")
    faulthandler.enable(file=fault_log_file)
    main(1)