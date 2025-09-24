import sys
import os

import pyuac
import yaml
import threading
# 导入项目模块
from utils.simul.config import config as config_simul
from utils.diver.config import config as config_diver
from simul import SimulatedUniverse
from diver import DivergentUniverse
from align_angle import main as align_angle_main
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QLineEdit,
    QComboBox, QCheckBox,  QMessageBox
)

# 导入QMainWindowLoadUI
from load_new_ui import QMainWindowLoadUI

class TaskThread(threading.Thread):
    def __init__(self, target, *args, **kwargs):
        super().__init__()
        self.target = target
        self.args = args
        self.kwargs = kwargs
        self.daemon = True

    def run(self):
        self.target(*self.args, **self.kwargs)


class ConfigSimulPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 开关复选框
        self.Simul_bonus_checkbox = QCheckBox("沉浸奖励")
        self.Simul_bonus_checkbox.setChecked(bool(config_simul.bonus))
        layout.addWidget(self.Simul_bonus_checkbox)

        self.Simul_debug_checkbox = QCheckBox("调试模式")
        self.Simul_debug_checkbox.setChecked(bool(config_simul.debug_mode))
        layout.addWidget(self.Simul_debug_checkbox)

        self.Simul_speed_checkbox = QCheckBox("速通模式")
        self.Simul_speed_checkbox.setChecked(bool(config_simul.speed_mode))
        layout.addWidget(self.Simul_speed_checkbox)

        self.Simul_slow_checkbox = QCheckBox("慢速模式")
        self.Simul_slow_checkbox.setChecked(bool(config_simul.slow_mode))
        layout.addWidget(self.Simul_slow_checkbox)

        # 下拉菜单
        difficulty_layout = QHBoxLayout()
        difficulty_layout.addWidget(QLabel("难度："))
        self.Simul_difficulty_combo = QComboBox()
        self.Simul_difficulty_combo.addItems(["1", "2", "3", "4", "5"])
        self.Simul_difficulty_combo.setCurrentText(str(config_simul.difficult))
        difficulty_layout.addWidget(self.Simul_difficulty_combo)
        layout.addLayout(difficulty_layout)

        fate_layout = QHBoxLayout()
        fate_layout.addWidget(QLabel("命途："))
        self.Simul_fate_combo = QComboBox()
        self.Simul_fate_combo.addItems([
            "存护", "记忆", "虚无", "丰饶", "巡猎", "毁灭", "欢愉", "繁育", "智识"
        ])
        self.Simul_fate_combo.setCurrentText(config_simul.fate)
        fate_layout.addWidget(self.Simul_fate_combo)
        layout.addLayout(fate_layout)

        timezone_layout = QHBoxLayout()
        timezone_layout.addWidget(QLabel("时区："))
        self.Simul_timezone_combo = QComboBox()
        self.Simul_timezone_combo.addItems(["Default", "Asia", "America", "Europe"])
        self.Simul_timezone_combo.setCurrentText(config_simul.timezone)
        timezone_layout.addWidget(self.Simul_timezone_combo)
        layout.addLayout(timezone_layout)

        max_run_layout = QHBoxLayout()
        max_run_layout.addWidget(QLabel("本轮运行次数："))
        self.Simul_max_run_input = QLineEdit(str(config_simul.max_run))
        max_run_layout.addWidget(self.Simul_max_run_input)
        layout.addLayout(max_run_layout)

        self.Simul_save_btn = QPushButton("保存并返回")
        self.Simul_save_btn.clicked.connect(self.save_config)
        layout.addWidget(self.Simul_save_btn)

        back_btn = QPushButton("返回主页")
        back_btn.clicked.connect(lambda: self.main_window.switch_tab("homeTab"))
        layout.addWidget(back_btn)

        self.setLayout(layout)

    def save_config(self):
        config_simul.bonus = int(self.Simul_bonus_checkbox.isChecked())
        config_simul.debug_mode = int(self.Simul_debug_checkbox.isChecked())
        config_simul.speed_mode = int(self.Simul_speed_checkbox.isChecked())
        config_simul.slow_mode = int(self.Simul_slow_checkbox.isChecked())
        config_simul.difficult = self.Simul_difficulty_combo.currentText()
        config_simul.fate = self.Simul_fate_combo.currentText()
        config_simul.timezone = self.Simul_timezone_combo.currentText()
        try:
            config_simul.max_run = int(self.Simul_max_run_input.text())
        except:
            pass
        config_simul.save()
        QMessageBox.information(self, "提示", "配置已保存")

class ConfigDiverPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        self.debug_checkbox = QCheckBox("调试模式")
        self.debug_checkbox.setChecked(bool(config_diver.debug_mode))
        layout.addWidget(self.debug_checkbox)

        self.speed_checkbox = QCheckBox("速通模式")
        self.speed_checkbox.setChecked(bool(config_diver.speed_mode))
        layout.addWidget(self.speed_checkbox)

        self.weekly_checkbox = QCheckBox("周期演算")
        self.weekly_checkbox.setChecked(bool(config_diver.weekly_mode))
        layout.addWidget(self.weekly_checkbox)

        self.cpu_checkbox = QCheckBox("禁用GPU加速")
        self.cpu_checkbox.setChecked(bool(config_diver.cpu_mode))
        layout.addWidget(self.cpu_checkbox)

        difficulty_layout = QHBoxLayout()
        difficulty_layout.addWidget(QLabel("难度："))
        self.difficulty_combo = QComboBox()
        self.difficulty_combo.addItems(["1", "2", "3", "4", "5"])
        self.difficulty_combo.setCurrentText(str(config_diver.difficult))
        difficulty_layout.addWidget(self.difficulty_combo)
        layout.addLayout(difficulty_layout)

        team_layout = QHBoxLayout()
        team_layout.addWidget(QLabel("队伍体系："))
        self.team_combo = QComboBox()
        self.team_combo.addItems(["追击", "dot", "终结技", "击破", "盾反"])
        self.team_combo.setCurrentText(config_diver.team)
        team_layout.addWidget(self.team_combo)
        layout.addLayout(team_layout)

        save_cnt_layout = QHBoxLayout()
        save_cnt_layout.addWidget(QLabel("存档数量："))
        self.save_cnt_combo = QComboBox()
        self.save_cnt_combo.addItems(["0", "1", "2", "3", "4"])
        self.save_cnt_combo.setCurrentText(str(config_diver.save_cnt))
        save_cnt_layout.addWidget(self.save_cnt_combo)
        layout.addLayout(save_cnt_layout)

        timezone_layout = QHBoxLayout()
        timezone_layout.addWidget(QLabel("时区："))
        self.timezone_combo = QComboBox()
        self.timezone_combo.addItems(["Default", "Asia", "America", "Europe"])
        self.timezone_combo.setCurrentText(config_diver.timezone)
        timezone_layout.addWidget(self.timezone_combo)
        layout.addLayout(timezone_layout)

        max_run_layout = QHBoxLayout()
        max_run_layout.addWidget(QLabel("本轮运行次数："))
        self.max_run_input = QLineEdit(str(config_diver.max_run))
        max_run_layout.addWidget(self.max_run_input)
        layout.addLayout(max_run_layout)

        save_btn = QPushButton("保存并返回")
        save_btn.clicked.connect(self.save_config)
        layout.addWidget(save_btn)

        back_btn = QPushButton("返回主页")
        back_btn.clicked.connect(lambda: self.main_window.switch_tab("homeTab"))
        layout.addWidget(back_btn)

        self.setLayout(layout)

    def save_config(self):
        config_diver.debug_mode = int(self.debug_checkbox.isChecked())
        config_diver.speed_mode = int(self.speed_checkbox.isChecked())
        config_diver.weekly_mode = int(self.weekly_checkbox.isChecked())
        config_diver.cpu_mode = int(self.cpu_checkbox.isChecked())
        config_diver.difficult = self.difficulty_combo.currentText()
        config_diver.team = self.team_combo.currentText()
        config_diver.timezone = self.timezone_combo.currentText()
        config_diver.save_cnt = int(self.save_cnt_combo.currentText())
        try:
            config_diver.max_run = int(self.max_run_input.text())
        except:
            pass
        config_diver.save()
        QMessageBox.information(self, "提示", "配置已保存")


# 修改MainWindow类，使其继承QMainWindowLoadUI
class MainWindow(QMainWindowLoadUI):
    def __init__(self):
        super().__init__()
        
        # 初始化页面
        self.config_simul_page = ConfigSimulPage(self)
        self.config_diver_page = ConfigDiverPage(self)
        
        # 将页面添加到对应的tab中
        self.setup_tabs()
        
        self.current_task = None
        self.init_ui()
    def init_ui(self):
        self.run_simul_btn.clicked.connect(self.run_simul)
        self.config_simul_btn.clicked.connect(self.open_config_simul)
        self.run_diver_btn.clicked.connect(self.run_diver)
        self.config_diver_btn.clicked.connect(lambda: self.switch_tab("ConfigDivertab"))
        self.calibrate_btn.clicked.connect(self.calibrate)
        self.test_btn.clicked.connect(self.test)
        self.stop_btn.clicked.connect(self.stop_task)

        
    def setup_tabs(self):
        """设置所有tab页面"""
        # 确保tabWidget存在
        if not hasattr(self, 'tabWidget'):
            print("tabWidget not found")
            return
            
        # 定义tab名称和对应页面的映射
        tab_mapping = {
            "ConfigSimultab": self.config_simul_page,
            "ConfigDivertab": self.config_diver_page
        }
        
        # 遍历映射，为每个tab设置页面
        for tab_name, page in tab_mapping.items():
            tab_widget = self.findChild(QWidget, tab_name)
            if tab_widget:
                self.setup_tab_content(tab_widget, page)
            else:
                print(f"Tab {tab_name} not found")

    def setup_tab_content(self, tab_widget, page):
        """为特定tab设置内容"""
        # 检查是否已有布局
        layout = tab_widget.layout()
        if layout is None:
            # 只有在没有布局时才创建新布局
            layout = QVBoxLayout(tab_widget)
            layout.setContentsMargins(10, 10, 10, 10)
        
        # 清理现有控件（如果有的话）
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().setParent(None)
                child.widget().deleteLater()
        
        # 添加页面到布局中
        layout.addWidget(page)
        
    def switch_tab(self, tab_name):
        """切换到指定的tab"""
        if not hasattr(self, 'tabWidget'):
            return
            
        target_tab = self.findChild(QWidget, tab_name)
        if target_tab:
            index = self.tabWidget.indexOf(target_tab)
            if index >= 0:
                self.tabWidget.setCurrentIndex(index)

    def test(self):
        from utils.diver.args import args
        def task():
            args.cpu = int(config_diver.cpu_mode)
            su = DivergentUniverse(
                int(config_diver.debug_mode),
                int(config_diver.max_run),
                int(config_diver.speed_mode)
            )
            self.current_task = su
            su.screen_test()
            self.current_task = None

        TaskThread(task).start()

    def stop_task(self):
        try:
            if hasattr(self, 'current_task') and self.current_task:
                self.current_task._stop = 1
                QMessageBox.information(self, "提示", "已发送停止信号...")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"停止失败: {e}")
    def open_config_simul(self):
        self.switch_tab("ConfigSimultab")

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
            self.current_task = su
            su.start()
        TaskThread(task).start()

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
        TaskThread(task).start()

    def calibrate(self):
        def task():
            res = align_angle_main()
            if res == 1:
                QMessageBox.information(None, "成功", "校准成功！")
            else:
                QMessageBox.warning(None, "失败", "校准失败，请重试。")
        TaskThread(task).start()

if __name__ == "__main__":
    if not pyuac.isUserAdmin():
        pyuac.runAsAdmin()
    else:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())