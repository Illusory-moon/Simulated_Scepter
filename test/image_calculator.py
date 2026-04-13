import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, 
    QVBoxLayout, QHBoxLayout, QMessageBox
)
from PyQt5.QtCore import Qt
import cv2


class ImageCalculator(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('图像坐标计算器')
        self.setGeometry(100, 100, 400, 200)
        
        # 文件名输入框
        self.filename_label = QLabel('文件名:')
        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText('请输入文件名（例如: example）')
        
        # 归一化坐标输入框
        self.coord_label = QLabel('归一化坐标:')
        self.coord_input = QLineEdit()
        self.coord_input.setPlaceholderText('请输入归一化坐标X,Y (例如: 0.9266, 0.9491)')
        
        # 计算按钮
        self.calculate_button = QPushButton('计算坐标')
        self.calculate_button.clicked.connect(self.calculate_coordinates)
        
        # 结果显示 (改为可选择的LineEdit)
        self.result_label = QLabel('结果:')
        self.result_display = QLineEdit()
        self.result_display.setReadOnly(True)
        
        # 布局
        layout = QVBoxLayout()
        
        # 文件名布局
        filename_layout = QHBoxLayout()
        filename_layout.addWidget(self.filename_label)
        filename_layout.addWidget(self.filename_input)
        layout.addLayout(filename_layout)
        
        # 坐标布局
        coord_layout = QHBoxLayout()
        coord_layout.addWidget(self.coord_label)
        coord_layout.addWidget(self.coord_input)
        layout.addLayout(coord_layout)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.calculate_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # 结果布局
        result_layout = QHBoxLayout()
        result_layout.addWidget(self.result_label)
        result_layout.addWidget(self.result_display)
        layout.addLayout(result_layout)
        
        self.setLayout(layout)
        
    def calculate_coordinates(self):
        try:
            # 获取输入值
            filename = self.filename_input.text().strip()
            coord_text = self.coord_input.text().strip()
            
            # 解析坐标
            try:
                coords = [float(c.strip()) for c in coord_text.split(',')]
                if len(coords) != 2:
                    raise ValueError("需要输入两个坐标值")
                normalized_x = 1.0 - coords[0]
                normalized_y = 1.0 - coords[1]
            except ValueError as ve:
                QMessageBox.warning(self, '输入错误', f'坐标格式错误: {str(ve)}')
                return
            
            # 检查文件名
            if not filename:
                QMessageBox.warning(self, '输入错误', '请输入文件名')
                return
                
            # 检查归一化坐标范围
            if not (0 <= coords[0] <= 1):
                QMessageBox.warning(self, '输入错误', '归一化X坐标必须在0-1之间')
                return
                
            if not (0 <= coords[1] <= 1):
                QMessageBox.warning(self, '输入错误', '归一化Y坐标必须在0-1之间')
                return
            
            # 构建完整路径 (使用指定的resource\imgs目录)，统一添加.jpg后缀
            image_path = os.path.join('../resource', 'imgs', filename + '.jpg')
            if not os.path.exists(image_path):
                # 如果 resource\imgs 目录中没有，则在当前目录查找
                image_path = filename + '.jpg'
                if not os.path.exists(image_path):
                    QMessageBox.warning(self, '文件错误', f'找不到文件: {filename}.jpg')
                    return
            
            # 读取图片获取实际尺寸
            image = cv2.imread(image_path)
            if image is None:
                QMessageBox.warning(self, '文件错误', f'无法读取图片文件: {filename}.jpg')
                return
                
            height, width = image.shape[0]+60, image.shape[1]+60

            # 计算归一化坐标中心点
            img_center_x = int(normalized_x * 1920)
            img_center_y = int(normalized_y * 1080)

            img_left_x = int(max(0, img_center_x - width // 2+1))
            img_right_x = int(min(1920, img_center_x + width // 2+1))
            img_top_y = int(max(0, img_center_y - height // 2+1))
            img_bottom_y = int(min(1080, img_center_y + height // 2+1))
            


            # 显示结果
            result_text = f"[{img_left_x}, {img_right_x}, {img_top_y}, {img_bottom_y}]"
            self.result_display.setText(result_text)
            
        except ValueError:
            QMessageBox.warning(self, '输入错误', '请输入有效的数字')
        except Exception as e:
            QMessageBox.critical(self, '错误', f'计算过程中出现错误: {str(e)}')


def main():
    app = QApplication(sys.argv)
    calculator = ImageCalculator()
    calculator.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()