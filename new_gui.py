import ctypes
import sys
import threading
import os
import shutil
import keyboard
import time


from utils.simul.config import config as config_simul
from utils.diver.config import config as config_diver
from simul import SimulatedUniverse
from diver import DivergentUniverse
from align_angle import main as align_angle_main
from PyQt5.QtWidgets import (
    QApplication, QLineEdit, QMessageBox
)
from PyQt5.QtCore import pyqtSignal
from logger_printer import QMainWindowLog
from pathlib import Path


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
        if self.current_task and hasattr(self.current_task, '_stop'):
            self.current_task._stop = 1
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


class MainWindow(QMainWindowLog):
    # 定义校准完成信号
    calibration_finished = pyqtSignal(object)
    
    def __init__(self):
        super().__init__()
        self.task_manager = TaskManager()
        self._last_f5_time = 0

        self.init_ui()
        self.setup_keyboard_listener()

    def init_ui(self):
        # 连接按钮信号
        self.run_simul_btn.clicked.connect(self.run_simul)
        self.run_diver_btn.clicked.connect(self.run_diver)
        self.calibrate_btn.clicked.connect(self.calibrate)
        self.test_btn.clicked.connect(self.test)
        self.stop_btn.clicked.connect(self.stop_task)
        self.clear_logs_btn.clicked.connect(self.clear_logs)  # 新增清除日志按钮连接

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

        self.calibration_finished.connect(self.show_calibration_result)

    def setup_keyboard_listener(self):
        """
        设置键盘监听器，监听F5按键以停止任务
        """
        keyboard.on_press_key("f5", self._on_f5_pressed)
        
    def _on_f5_pressed(self, event):
        """
        当F5按键被按下时的回调函数
        """
        current_time = time.time()
        # 防止频繁触发，限制1秒内只能触发一次
        if current_time - self._last_f5_time > 1:
            self._last_f5_time = current_time
            # 检查是否有任务正在运行，如果有则停止任务
            if self.task_manager.is_task_running():
                # 使用Qt的信号机制在主线程中安全地调用stop_task
                self.stop_btn.click()
        
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

    def stop_task(self):
        try:
            if self.task_manager.stop_task():
                QMessageBox.information(self, "提示", "已发送停止信号...")
        except Exception as e:
            pass
        
    def run_simul(self):
        def task():
            su = SimulatedUniverse(
                1,
                int(config_simul.debug_mode),
                int(config_simul.show_map_mode),
                int(config_simul.speed_mode),
                int(config_simul.use_consumable),
                int(config_simul.slow_mode),
                int(config_simul.max_run),
                unlock=True,
                bonus=config_simul.bonus,
                gui=1
            )
            self.task_manager.current_task = su
            su.start()
            
        try:
            self.task_manager.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))

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
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))

    def calibrate(self):
        def task():
            try:
                res = align_angle_main()
                # 通过信号在主线程中显示结果
                self.calibration_finished.emit(res)
            except Exception as e:
                # 通过信号在主线程中显示错误信息
                self.calibration_finished.emit(e)
            
        try:
            self.task_manager.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))

    def show_calibration_result(self, result):
        # 检查result是返回值还是异常
        if isinstance(result, Exception):
            QMessageBox.critical(self, "错误", f"校准失败: {str(result)}")
        elif result == 1:
            QMessageBox.information(self, "成功", "校准成功！")
        else:
            QMessageBox.warning(self, "失败", "校准失败，请重试。")

    def run_on_main_thread(self, func):
        """
        在主线程中执行函数，用于更新UI
        """
        func()

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
            pass  # 保持原值
            
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
            pass  # 保持原值

        # 保存配置到文件
        config_simul.save()
        config_diver.save()
        QMessageBox.information(self, "提示", "配置已保存")


if __name__ == "__main__":
    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False


    # 以管理员权限重新运行程序，使用pythonw避免命令行窗口
    def run_as_admin():
        script = Path(sys.argv[0]).resolve()
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "pythonw.exe",
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
        sys.exit(app.exec_())