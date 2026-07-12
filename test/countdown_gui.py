"""
单图推演 GUI Demo — 拖拽图片 → 设置参数 → 点开始 → 查看日志。
用法: python test/countdown_gui.py
"""
import os, sys, io, traceback
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'test'))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox, QFormLayout,
    QSpinBox, QComboBox, QFileDialog, QSplitter,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QDragEnterEvent, QDropEvent, QFont


class AnalyzeThread(QThread):
    log_signal = pyqtSignal(str)
    done_signal = pyqtSignal(dict)

    def __init__(self, image_path, params):
        super().__init__()
        self.image_path = image_path
        self.params = params

    def run(self):
        old_stdout = sys.stdout
        sys.stdout = _StreamRedirect(self.log_signal)
        try:
            from test_countdown_optimizer import analyze_single_map
            result = analyze_single_map(
                image_path=self.image_path,
                **self.params,
            )
            self.done_signal.emit(result)
        except Exception:
            self.log_signal.emit(traceback.format_exc())
        finally:
            sys.stdout = old_stdout


class _StreamRedirect(io.StringIO):
    def __init__(self, signal):
        super().__init__()
        self._signal = signal

    def write(self, s):
        super().write(s)
        if s.strip():
            self._signal.emit(s)

    def flush(self):
        pass


class DropLabel(QLabel):
    image_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumSize(400, 300)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #666;
                border-radius: 10px;
                background: #1a1a26;
                color: #777;
                font-size: 14px;
            }
        """)
        self.setText('拖拽 PNG 图片到这里\n或点击选择文件')
        self._orig_path = None

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择地图图片', '', 'PNG Images (*.png);;All Files (*)')
        if path:
            self._set_image(path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path):
                self._set_image(path)
                return

    def _set_image(self, path):
        self._orig_path = path
        self._show_pixmap(path)
        self.image_dropped.emit(path)

    def _show_pixmap(self, path):
        pix = QPixmap(path)
        if not pix.isNull():
            scaled = pix.scaled(self.width() - 24, self.height() - 24,
                                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.setPixmap(scaled)

    def show_annotated(self, annotated_path):
        """推理完成后切到 annotated 图，原图路径不变，缩放时保持 annotated。"""
        self._annotated_path = annotated_path
        if os.path.isfile(annotated_path):
            self._show_pixmap(annotated_path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 优先显示 annotated，其次原图
        current = getattr(self, '_annotated_path', None)
        if not current or not os.path.isfile(current):
            current = self._orig_path
        if current and os.path.isfile(current):
            self._show_pixmap(current)

    @property
    def path(self):
        return self._orig_path


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('倒计时优化器 v1.1.1 — GUI Demo')
        self.setMinimumSize(1100, 750)

        cw = QWidget()
        self.setCentralWidget(cw)
        root = QHBoxLayout(cw)
        root.setSpacing(10)

        # ---- 左侧主区域：图片  ----
        left = QVBoxLayout()
        self.drop_label = DropLabel()
        self.drop_label.image_dropped.connect(self._on_image)
        left.addWidget(self.drop_label, stretch=1)

        # 按钮栏
        btn_row = QHBoxLayout()
        self.btn_run = QPushButton('▶  开始推理')
        self.btn_run.setMinimumHeight(40)
        self.btn_run.setEnabled(False)
        self.btn_run.setStyleSheet("""
            QPushButton {
                background: #4caf50; color: white; font-size: 15px;
                border-radius: 8px; font-weight: bold; padding: 6px 24px;
            }
            QPushButton:disabled { background: #444; color: #888; }
            QPushButton:hover:!disabled { background: #43a047; }
        """)
        self.btn_run.clicked.connect(self._run)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch()
        left.addLayout(btn_row)

        root.addLayout(left, stretch=3)

        # ---- 右侧：参数面板 ----
        params_box = QGroupBox('推理参数')
        form = QFormLayout()
        form.setHorizontalSpacing(12)

        def _spin(min_v, max_v, default, step=1):
            s = QSpinBox()
            s.setRange(min_v, max_v)
            s.setValue(default)
            s.setSingleStep(step)
            return s

        self.spin_cheat = _spin(0, 99, 3)
        form.addRow('Cheat 次数:', self.spin_cheat)
        self.spin_reroll = _spin(0, 99, 1)
        form.addRow('Reroll 次数:', self.spin_reroll)
        self.spin_cd = _spin(0, 999, 15)
        form.addRow('初始 CD:', self.spin_cd)

        self.spin_target = _spin(0, 999, 20)
        self.spin_target.setSpecialValueText('不设目标')
        form.addRow('目标 CD (0=不计):', self.spin_target)

        self.combo_observed = QComboBox()
        self.combo_observed.addItem('无', None)
        for name, num in [('浇灌', 1), ('为善', 2), ('对症', 3),
                          ('慈怀', 4), ('归心', 5), ('可憎', 6)]:
            self.combo_observed.addItem(f'{name} ({num})', num)
        self.combo_observed.setCurrentIndex(2)  # 默认 为善=2
        form.addRow('观察效果:', self.combo_observed)

        self.combo_effect_state = QComboBox()
        self.combo_effect_state.addItem('未锁定 (unlocked)', 'unlocked')
        self.combo_effect_state.addItem('已锁定 (locked)', 'locked')
        self.combo_effect_state.addItem('已结算 (settled)', 'settled')
        form.addRow('效果状态:', self.combo_effect_state)

        self.spin_plane = _spin(1, 3, 2)
        form.addRow('位面:', self.spin_plane)
        self.spin_match_mode = _spin(1, 3, 3)
        form.addRow('匹配模式:', self.spin_match_mode)
        self.spin_train = _spin(100, 999999, 15000, 500)
        form.addRow('训练轮数:', self.spin_train)
        self.spin_trials = _spin(100, 999999, 15000, 500)
        form.addRow('评估次数:', self.spin_trials)

        params_box.setLayout(form)
        right = QVBoxLayout()
        right.addWidget(params_box)

        # 结果展示
        result_box = QGroupBox('推理结果')
        rf = QFormLayout()
        self.lbl_winrate = QLabel('--')
        self.lbl_winrate.setStyleSheet('font-size: 20px; font-weight: bold; color: #4caf50;')
        rf.addRow('目标胜率:', self.lbl_winrate)
        self.lbl_recommend = QLabel('--')
        self.lbl_recommend.setStyleSheet('font-size: 14px; color: #ff9800; font-weight: bold;')
        self.lbl_recommend.setWordWrap(True)
        rf.addRow('推荐首步:', self.lbl_recommend)
        result_box.setLayout(rf)
        right.addWidget(result_box)
        right.addStretch()
        root.addLayout(right, stretch=1)

        # ---- 底部：日志 ----
        bottom_widget = QWidget()
        bottom = QVBoxLayout(bottom_widget)
        bottom.setContentsMargins(0, 0, 0, 0)
        log_header = QLabel('推理日志')
        log_header.setStyleSheet('font-weight: bold; font-size: 13px; padding: 2px 0;')
        bottom.addWidget(log_header)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(180)
        self.log_view.setFont(QFont('Consolas', 10))
        self.log_view.setStyleSheet("""
            QTextEdit {
                background: #111118; color: #c0c0cc;
                border: 1px solid #333; border-radius: 4px;
            }
        """)
        bottom.addWidget(self.log_view)

        # 用 QSplitter 把左右区和底部分开
        main_splitter = QSplitter(Qt.Vertical)
        top_panel = QWidget()
        top_panel.setLayout(root)
        main_splitter.addWidget(top_panel)
        main_splitter.addWidget(bottom_widget)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 1)

        outer = QVBoxLayout(cw)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(main_splitter)

        self._image_path = None
        self._thread = None

    def _on_image(self, path):
        self._image_path = path
        self.btn_run.setEnabled(True)
        self._log(f'[GUI] 已加载: {os.path.basename(path)}')

    def _log(self, text):
        self.log_view.append(text.rstrip())
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _run(self):
        if not self._image_path:
            return
        self.btn_run.setEnabled(False)
        self.log_view.clear()
        self._log('=' * 60)
        self._log(f'[GUI] 开始推理: {os.path.basename(self._image_path)}')

        params = dict(
            cheat=self.spin_cheat.value(),
            reroll=self.spin_reroll.value(),
            initial_countdown=self.spin_cd.value(),
            target_cd=self.spin_target.value() if self.spin_target.value() > 0 else None,
            observed_effect=self.combo_observed.currentData(),
            effect_state=self.combo_effect_state.currentData(),
            plane=self.spin_plane.value(),
            match_mode=self.spin_match_mode.value(),
            n_train=self.spin_train.value(),
            n_sim_trials=self.spin_trials.value(),
            verbose=True,
        )
        self._thread = AnalyzeThread(self._image_path, params)
        self._thread.log_signal.connect(self._log)
        self._thread.done_signal.connect(self._on_done)
        self._thread.start()

    def _on_done(self, result):
        self._log('')
        self._log(f'[GUI] 推理完成。可编程字段: {list(result.keys())}')
        self.btn_run.setEnabled(True)
        # 胜率
        wr = result.get('win_rate')
        if wr is not None:
            self.lbl_winrate.setText(f'{wr * 100:.2f}%')
            self.lbl_winrate.setStyleSheet(
                'font-size: 20px; font-weight: bold; color: #4caf50;' if wr > 0 else
                'font-size: 20px; font-weight: bold; color: #f44336;')
        else:
            self.lbl_winrate.setText('未设置目标')
            self.lbl_winrate.setStyleSheet('font-size: 14px; color: #888;')
        # 推荐首步
        ra = result.get('recommended_action', '--')
        self.lbl_recommend.setText(ra)
        # 切到 annotated 图
        annotated_path = self._image_path[:-4] + '_annotated.png'
        self.drop_label.show_annotated(annotated_path)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    dark = """
        QMainWindow, QWidget { background: #1c1c28; color: #ddd; }
        QGroupBox {
            border: 1px solid #444; border-radius: 6px; margin-top: 10px;
            padding-top: 8px; font-weight: bold; font-size: 13px;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #ccc; }
        QSpinBox, QComboBox {
            background: #252530; color: #ddd; border: 1px solid #444;
            border-radius: 3px; padding: 3px 6px; min-width: 80px;
        }
        QSplitter::handle { background: #333; height: 3px; }
        QScrollBar:vertical {
            background: #1c1c28; width: 10px;
        }
        QScrollBar::handle:vertical {
            background: #444; border-radius: 5px; min-height: 20px;
        }
        QScrollBar:horizontal {
            background: #1c1c28; height: 10px;
        }
        QScrollBar::handle:horizontal {
            background: #444; border-radius: 5px; min-width: 20px;
        }
    """
    app.setStyleSheet(dark)

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
