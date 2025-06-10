import sys
import os

import pyuac
import yaml
import ctypes
import threading


# 导入项目模块
from utils.simul.config import config as config_simul
from utils.diver.config import config as config_diver
from simul import SimulatedUniverse
from diver import DivergentUniverse
from align_angle import main as align_angle_main
from abyss import Abyss
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QLineEdit,
    QComboBox, QCheckBox,  QMessageBox
)
from PyQt5.QtCore import Qt

class TaskThread(threading.Thread):
    def __init__(self, target, *args, **kwargs):
        super().__init__()
        self.target = target
        self.args = args
        self.kwargs = kwargs
        self.daemon = True

    def run(self):
        self.target(*self.args, **self.kwargs)

class HomePage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        title = QLabel("AutoSimulatedUniverse")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("开源免费，任何收费行为均为倒卖！")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color: red;")
        layout.addWidget(desc)

        btn_layout = QHBoxLayout()
        self.run_simul_btn = QPushButton("运行模拟宇宙")
        self.run_simul_btn.clicked.connect(self.run_simul)
        btn_layout.addWidget(self.run_simul_btn)

        self.config_simul_btn = QPushButton("设置模拟宇宙")
        self.config_simul_btn.clicked.connect(self.open_config_simul)
        btn_layout.addWidget(self.config_simul_btn)

        layout.addLayout(btn_layout)

        btn_layout2 = QHBoxLayout()
        self.run_diver_btn = QPushButton("运行差分宇宙")
        self.run_diver_btn.clicked.connect(self.run_diver)
        btn_layout2.addWidget(self.run_diver_btn)

        self.config_diver_btn = QPushButton("设置差分宇宙")
        self.config_diver_btn.clicked.connect(lambda: self.main_window.switch_page("ConfigDiverPage"))
        btn_layout2.addWidget(self.config_diver_btn)

        layout.addLayout(btn_layout2)

        abyss_btn = QPushButton("忘却之庭配置")
        abyss_btn.clicked.connect(lambda: self.main_window.switch_page("AbyssPage"))
        layout.addWidget(abyss_btn)

        calibrate_btn = QPushButton("校准角度")
        calibrate_btn.clicked.connect(self.calibrate)
        layout.addWidget(calibrate_btn)

        self.test_btn = QPushButton("截图测试")
        self.test_btn.clicked.connect(self.test)
        layout.addWidget(self.test_btn)

        self.stop_btn = QPushButton("停止任务")
        self.stop_btn.clicked.connect(self.stop_task)
        layout.addWidget(self.stop_btn)

        exit_btn = QPushButton("退出")
        exit_btn.clicked.connect(QApplication.instance().quit)
        layout.addWidget(exit_btn)

        self.setLayout(layout)

    def test(self):
        from utils.diver.args import args
        def task():
            args.cpu = int(config_diver.cpu_mode)
            su = DivergentUniverse(
                int(config_diver.debug_mode),
                int(config_diver.max_run),
                int(config_diver.speed_mode)
            )
            self.main_window.current_task = su
            su.screen_test()
            self.main_window.current_task = None

        TaskThread(task).start()

    def stop_task(self):
        try:
            if hasattr(self.main_window, 'current_task') and self.main_window.current_task:
                self.main_window.current_task._stop = 1
                QMessageBox.information(self, "提示", "已发送停止信号...")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"停止失败: {e}")
    def open_config_simul(self):
        self.main_window.switch_page("ConfigSimulPage")

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
            self.main_window.current_task = su
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
            self.main_window.current_task = su
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

class ConfigSimulPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 开关复选框
        self.bonus_checkbox = QCheckBox("沉浸奖励")
        self.bonus_checkbox.setChecked(bool(config_simul.bonus))
        layout.addWidget(self.bonus_checkbox)

        self.debug_checkbox = QCheckBox("调试模式")
        self.debug_checkbox.setChecked(bool(config_simul.debug_mode))
        layout.addWidget(self.debug_checkbox)

        self.speed_checkbox = QCheckBox("速通模式")
        self.speed_checkbox.setChecked(bool(config_simul.speed_mode))
        layout.addWidget(self.speed_checkbox)

        self.slow_checkbox = QCheckBox("慢速模式")
        self.slow_checkbox.setChecked(bool(config_simul.slow_mode))
        layout.addWidget(self.slow_checkbox)

        # 下拉菜单
        difficulty_layout = QHBoxLayout()
        difficulty_layout.addWidget(QLabel("难度："))
        self.difficulty_combo = QComboBox()
        self.difficulty_combo.addItems(["1", "2", "3", "4", "5"])
        self.difficulty_combo.setCurrentText(str(config_simul.difficult))
        difficulty_layout.addWidget(self.difficulty_combo)
        layout.addLayout(difficulty_layout)

        fate_layout = QHBoxLayout()
        fate_layout.addWidget(QLabel("命途："))
        self.fate_combo = QComboBox()
        self.fate_combo.addItems([
            "存护", "记忆", "虚无", "丰饶", "巡猎", "毁灭", "欢愉", "繁育", "智识"
        ])
        self.fate_combo.setCurrentText(config_simul.fate)
        fate_layout.addWidget(self.fate_combo)
        layout.addLayout(fate_layout)

        timezone_layout = QHBoxLayout()
        timezone_layout.addWidget(QLabel("时区："))
        self.timezone_combo = QComboBox()
        self.timezone_combo.addItems(["Default", "Asia", "America", "Europe"])
        self.timezone_combo.setCurrentText(config_simul.timezone)
        timezone_layout.addWidget(self.timezone_combo)
        layout.addLayout(timezone_layout)

        max_run_layout = QHBoxLayout()
        max_run_layout.addWidget(QLabel("本轮运行次数："))
        self.max_run_input = QLineEdit(str(config_simul.max_run))
        max_run_layout.addWidget(self.max_run_input)
        layout.addLayout(max_run_layout)

        save_btn = QPushButton("保存并返回")
        save_btn.clicked.connect(self.save_config)
        layout.addWidget(save_btn)

        back_btn = QPushButton("返回主页")
        back_btn.clicked.connect(lambda: self.main_window.switch_page("HomePage"))
        layout.addWidget(back_btn)

        self.setLayout(layout)

    def save_config(self):
        config_simul.bonus = int(self.bonus_checkbox.isChecked())
        config_simul.debug_mode = int(self.debug_checkbox.isChecked())
        config_simul.speed_mode = int(self.speed_checkbox.isChecked())
        config_simul.slow_mode = int(self.slow_checkbox.isChecked())
        config_simul.difficult = self.difficulty_combo.currentText()
        config_simul.fate = self.fate_combo.currentText()
        config_simul.timezone = self.timezone_combo.currentText()
        try:
            config_simul.max_run = int(self.max_run_input.text())
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
        back_btn.clicked.connect(lambda: self.main_window.switch_page("HomePage"))
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

class AbyssPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        # 创建主布局
        layout = QVBoxLayout()
        
        # 配队1输入区域
        team1_layout = QHBoxLayout()
        self.entry1 = QLineEdit()
        team1_layout.addWidget(QLabel("配队1（空格分隔数字）"))
        team1_layout.addWidget(self.entry1)
        
        # 配队2输入区域
        team2_layout = QHBoxLayout()
        self.entry2 = QLineEdit()
        team2_layout.addWidget(QLabel("配队2（空格分隔数字）"))
        team2_layout.addWidget(self.entry2)

        # 按钮布局
        btn_layout = QHBoxLayout()
        run_btn = QPushButton("运行深渊")
        run_btn.clicked.connect(self.run_abyss)
        btn_layout.addWidget(run_btn)
        
        back_btn = QPushButton("返回主页")
        back_btn.clicked.connect(lambda: self.main_window.switch_page("HomePage"))
        btn_layout.addWidget(back_btn)

        # 组合所有布局
        layout.addLayout(team1_layout)
        layout.addLayout(team2_layout)
        layout.addLayout(btn_layout)
        
        # 设置间距和边距以优化视觉效果
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        self.setLayout(layout)

    def run_abyss(self):
        order1 = self.entry1.text().strip().split()
        order2 = self.entry2.text().strip().split()

        try:
            order1 = [int(x) for x in order1]
            order2 = [int(x) for x in order2]
        except:
            QMessageBox.critical(self, "错误", "请输入有效的数字编号")
            return

        order1 += [0] * (4 - len(order1))
        order2 += [0] * (4 - len(order2))
        final_order = [order1[:4], order2[:4]]

        os.makedirs('abyss', exist_ok=True)
        with open('abyss/info.yml', 'w', encoding='utf-8') as f:
            yaml.safe_dump({'order_text': final_order[0] + final_order[1]}, f, allow_unicode=True)

        def task():
            abyss = Abyss()
            abyss.start_abyss()
        TaskThread(task).start()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoSimulatedUniverse")
        self.resize(800, 600)

        self.pages = {
            "HomePage": HomePage(self),
            "ConfigSimulPage": ConfigSimulPage(self),
            "ConfigDiverPage": ConfigDiverPage(self),
            "AbyssPage": AbyssPage(self),
        }

        self.stacked_widget = QStackedWidget()
        for page in self.pages.values():
            self.stacked_widget.addWidget(page)

        self.setCentralWidget(self.stacked_widget)

    def switch_page(self, page_name):
        self.stacked_widget.setCurrentWidget(self.pages[page_name])

if __name__ == "__main__":
    if not pyuac.isUserAdmin():
        pyuac.runAsAdmin()
    else:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
