import sys
import pyuac
import threading
import os
import shutil
from utils.simul.config import config as config_simul
from utils.diver.config import config as config_diver
from simul import SimulatedUniverse
from diver import DivergentUniverse
from align_angle import main as align_angle_main
from PyQt5.QtWidgets import (
    QApplication, QLineEdit, QMessageBox
)

from load_new_ui import QMainWindowLoadUI


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
    def __init__(self, target, *args, **kwargs):
        super().__init__()
        self.target = target
        self.args = args
        self.kwargs = kwargs
        self.daemon = True

    def run(self):
        self.target(*self.args, **self.kwargs)


class MainWindow(QMainWindowLoadUI):
    def __init__(self):
        super().__init__()
        self.task_manager = TaskManager()
        self.init_ui()

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
            else:
                QMessageBox.warning(self, "警告", "当前没有运行中的任务")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"停止失败: {e}")

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
            res = align_angle_main()
            # 在主线程中显示结果
            self.run_on_main_thread(lambda: self.show_calibration_result(res))
            
        try:
            self.task_manager.start_task(task)
        except RuntimeError as e:
            QMessageBox.warning(self, "警告", str(e))

    def show_calibration_result(self, res):
        if res == 1:
            QMessageBox.information(None, "成功", "校准成功！")
        else:
            QMessageBox.warning(None, "失败", "校准失败，请重试。")

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
    # if not pyuac.isUserAdmin():
    #     pyuac.runAsAdmin()
    # else:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())