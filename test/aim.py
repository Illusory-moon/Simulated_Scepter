import cv2
import numpy as np
from PIL import Image

from tool.timer import timer

class Lines:
    MID_Y = 360

    def __init__(self, lines, is_horizontal):
        if lines is None or len(lines) == 0:
            self._bool = False
            self.lines = None
        else:
            self._bool = True
            self.lines = np.array(lines)
            if len(self.lines.shape) == 1:
                self.lines = np.array([self.lines])
            self.rho, self.theta = self.lines.T
        self.is_horizontal = is_horizontal

    def __str__(self):
        return str(self.lines)

    __repr__ = __str__

    def __iter__(self):
        return iter(self.lines)

    def __getitem__(self, item):
        return Lines(self.lines[item], is_horizontal=self.is_horizontal)

    def __len__(self):
        if self:
            return len(self.lines)
        else:
            return 0

    def __bool__(self):
        return self._bool

    @property
    def sin(self):
        return np.sin(self.theta)

    @property
    def cos(self):
        return np.cos(self.theta)

    @property
    def mean(self):
        if not self:
            return None
        if self.is_horizontal:
            return np.mean(self.lines, axis=0)
        else:
            x = np.mean(self.mid)
            theta = np.mean(self.theta)
            rho = x * np.cos(theta) + self.MID_Y * np.sin(theta)
            return np.array((rho, theta))

    @property
    def mid(self):
        if not self:
            return np.array([])
        if self.is_horizontal:
            return self.rho
        else:
            return (self.rho - self.MID_Y * self.sin) / self.cos

    def get_x(self, y):
        return (self.rho - y * self.sin) / self.cos

    def get_y(self, x):
        return (self.rho - x * self.cos) / self.sin

    def add(self, other):
        if not other:
            return self
        if not self:
            return other
        lines = np.append(self.lines, other.lines, axis=0)
        return Lines(lines, is_horizontal=self.is_horizontal)

    def move(self, x, y):
        if not self:
            return self
        if self.is_horizontal:
            self.lines[:, 0] += y
        else:
            self.lines[:, 0] += x * self.cos + y * self.sin
        return Lines(self.lines, is_horizontal=self.is_horizontal)

    def sort(self):
        if not self:
            return self
        lines = self.lines[np.argsort(self.mid)]
        return Lines(lines, is_horizontal=self.is_horizontal)

    def group(self, threshold=3):
        if not self:
            return self
        lines = self.sort()
        prev = 0
        regrouped = []
        group = []
        for mid, line in zip(lines.mid, lines.lines):
            line = line.tolist()
            if mid - prev > threshold:
                if len(regrouped) == 0:
                    if len(group) != 0:
                        regrouped = [group]
                else:
                    regrouped += [group]
                group = [line]
            else:
                group.append(line)
            prev = mid
        regrouped += [group]
        regrouped = np.vstack([Lines(r, is_horizontal=self.is_horizontal).mean for r in regrouped])
        return Lines(regrouped, is_horizontal=self.is_horizontal)

    def distance_to_point(self, point):
        x, y = point
        return self.rho - x * self.cos - y * self.sin

    @staticmethod
    def cross_two_lines(lines1, lines2):
        for rho1, sin1, cos1 in zip(lines1.rho, lines1.sin, lines1.cos):
            for rho2, sin2, cos2 in zip(lines2.rho, lines2.sin, lines2.cos):
                a = np.array([[cos1, sin1], [cos2, sin2]])
                b = np.array([rho1, rho2])
                yield np.linalg.solve(a, b)

    def cross(self, other):
        points = np.vstack(self.cross_two_lines(self, other))
        points = Points(points)
        return points

    def delete(self, other, threshold=3):
        if not self:
            return self

        other_mid = other.mid
        lines = []
        for mid, line in zip(self.mid, self.lines):
            if np.any(np.abs(other_mid - mid) < threshold):
                continue
            lines.append(line)

        return Lines(lines, is_horizontal=self.is_horizontal)
class Points:
    def __init__(self, points):
        if points is None or len(points) == 0:
            self._bool = False
            self.points = None
        else:
            self._bool = True
            self.points = np.array(points)
            if len(self.points.shape) == 1:
                self.points = np.array([self.points])
            self.x, self.y = self.points.T

    def __str__(self):
        return str(self.points)

    __repr__ = __str__

    def __iter__(self):
        return iter(self.points)

    def __getitem__(self, item):
        return self.points[item]

    def __len__(self):
        if self:
            return len(self.points)
        else:
            return 0

    def __bool__(self):
        return self._bool

    def link(self, point, is_horizontal=False):
        if is_horizontal:
            lines = [[y, np.pi / 2] for y in self.y]
            return Lines(lines, is_horizontal=True)
        else:
            x, y = point
            theta = -np.arctan((self.x - x) / (self.y - y))
            rho = self.x * np.cos(theta) + self.y * np.sin(theta)
            lines = np.array([rho, theta]).T
            return Lines(lines, is_horizontal=False)

    def mean(self):
        if not self:
            return None

        return np.round(np.mean(self.points, axis=0)).astype(int)

    def group(self, threshold=3):
        if not self:
            return np.array([])
        groups = []
        points = self.points
        if len(points) == 1:
            return np.array([points[0]])

        while len(points):
            p0, p1 = points[0], points[1:]
            distance = np.sum(np.abs(p1 - p0), axis=1)
            new = Points(np.append(p1[distance <= threshold], [p0], axis=0)).mean().tolist()
            groups.append(new)
            points = p1[distance > threshold]

        return np.array(groups)


def group_points(points, threshold=3):
    """
    对点集进行分组，依据点之间的曼哈顿距离是否小于阈值 threshold。

    参数:
        points (np.ndarray): 形状为 (N, 2) 的点集，例如 [[x1, y1], [x2, y2], ...]
        threshold (int): 分组的距离阈值

    返回:
        np.ndarray: 每组点的平均坐标，形状为 (M, 2)
    """
    if points is None or len(points) == 0:
        return np.array([])

    groups = []
    points = np.array(points)  # 确保输入为 NumPy 数组
    if len(points) == 1:
        return np.array([points[0]])

    while len(points):
        p0, p1 = points[0], points[1:]
        # 计算当前点与其他点的曼哈顿距离
        distance = np.sum(np.abs(p1 - p0), axis=1)
        # 找出距离小于阈值的点，组成新组
        new_group = np.append(p1[distance <= threshold], [p0], axis=0)
        # 计算该组的平均坐标并加入结果列表
        groups.append(np.round(np.mean(new_group, axis=0)).astype(int))
        # 移除已处理的点
        points = p1[distance > threshold]

    return np.array(groups)


def create_circle(min_radius, max_radius):
    """
    创建一个 min_radius <= R <= max_radius 的圆。
    1 表示圆形，0 表示背景

    参数:
        min_radius:
        max_radius:

    返回:
        np.ndarray:
    """
    circle = np.ones((max_radius * 2 + 1, max_radius * 2 + 1), dtype=np.uint8)
    center = np.array((max_radius, max_radius))
    points = np.array(np.meshgrid(np.arange(circle.shape[0]), np.arange(circle.shape[1]))).T
    distance = np.linalg.norm(points - center, axis=2)
    circle[distance < min_radius] = 0
    circle[distance > max_radius] = 0
    return circle
def draw_circle(image, circle, points):
    """
    在图像上添加一个圆。
    无返回值，更改写入到 `image`

    参数:
        image:
        circle: 由 create_circle() 创建
        points: (x, y)，要绘制的圆的中心
    """
    width, height = image_size(circle)
    x1 = -int(width // 2)
    y1 = -int(height // 2)
    x2 = width + x1
    y2 = height + y1
    for point in points:
        x, y = point
        # Fancy index is faster
        index = image[y + y1:y + y2, x + x1:x + x2]
        # print(index.shape)
        cv2.add(index, circle, dst=index)
def inrange(image, lower=0, upper=255):
    """
    获取范围内像素的坐标。
    等效于 `np.array(np.where(lower <= image <= upper))` 但更快。
    注意此方法会改变 `image`。

    `cv2.findNonZero()` 比 `np.where` 更快
    points = np.array(np.where(y > 24)).T[:, ::-1]
    points = np.array(cv2.findNonZero((y > 24).astype(np.uint8)))[:, 0, :]

    `cv2.inRange(y, 24)` 比 `y > 24` 更快
    cv2.inRange(y, 24, 255, dst=y)
    y = y > 24

    返回:
        np.ndarray: 形状 (N, 2)
            例如 [[x1, y1], [x2, y2], ...]
    """
    cv2.inRange(image, lower, upper, dst=image)
    try:
        return np.array(cv2.findNonZero(image))[:, 0, :]
    except IndexError:
        # Empty result
        # IndexError: too many indices for array: array is 0-dimensional, but 3 were indexed
        return np.array([])
def remove_border(image, radius):
    """
    将边缘像素涂黑。
    无返回值，更改写入到 `image`

    参数:
        image:
        radius:
    """
    width, height = image_size(image)
    image[:, :radius + 1] = 0
    image[:, width - radius:] = 0
    image[:radius + 1, :] = 0
    image[height - radius:, :] = 0
def subtract_blur(image, radius=3, negative=False):
    """
    如果您更关心性能而非质量：
    - radius=3，使用 medianBlur
    - radius=5,7,9,11，使用 GaussianBlur
    - radius>11，使用 stackBlur（需要 opencv >= 4.7.0）

    参数:
        image:
        radius:
        negative:

    返回:
        np.ndarray:
    """
    if radius <= 3:
        blur = cv2.medianBlur(image, radius)
    elif radius <= 11:
        blur = cv2.GaussianBlur(image, (radius, radius), 0)
    else:
        blur = cv2.stackBlur(image, (radius, radius), 0)

    if negative:
        cv2.subtract(blur, image, dst=blur)
    else:
        cv2.subtract(image, blur, dst=blur)
    return blur
def image_size(image):
    """
    Args:
        image (np.ndarray):

    Returns:
        int, int: width, height
    """
    shape = image.shape
    return shape[1], shape[0]
def dict_to_kv(dictionary, allow_none=True):
    """
    Args:
        dictionary: Such as `{'path': 'Scheduler.ServerUpdate', 'value': True}`
        allow_none (bool):

    Returns:
        str: Such as `path='Scheduler.ServerUpdate', value=True`
    """
    return ', '.join([f'{k}={repr(v)}' for k, v in dictionary.items() if allow_none or v is not None])
def image_channel(image):
    """
    Args:
        image (np.ndarray):

    Returns:
        int: 0 for grayscale, 3 for RGB.
    """
    return image.shape[2] if len(image.shape) == 3 else 0
def load_image(file, area=None):
    """
    Load an image like pillow and drop alpha channel.

    Args:
        file (str):
        area (tuple):

    Returns:
        np.ndarray:
    """
    # always remember to close Image object
    with Image.open(file) as f:
        if area is not None:
            f = f.crop(area)

        image = np.array(f)

    channel = image_channel(image)
    if channel == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)

    return image
def predict_enemy(h, v,radius_enemy,mask_interact,circle_enemy):
    min_radius, max_radius = radius_enemy
    width, height = image_size(v)

    # 获取白色圆形 `y`
    y = subtract_blur(h, 3, negative=False)
    cv2.inRange(h, 168, 255, dst=h)
    cv2.bitwise_and(y, h, dst=y)
    # 获取红色光晕 `v`
    cv2.inRange(v, 168, 255, dst=v)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cv2.dilate(v, kernel, dst=v)
    # 去除噪声，只保留红色圆形
    cv2.bitwise_and(y, v, dst=y)
    # cv2.imshow('predict_enemy', y)
    # 去除游戏UI
    cv2.bitwise_and(y, mask_interact, dst=y)
    # 去除边缘上的点，否则 draw_circle() 会溢出
    remove_border(y, max_radius)

    # 获取所有像素
    points = inrange(y, lower=18)
    if points.shape[0] > 1000:
        print(f'AimDetector.predict_enemy() 绘制点过多: {points.shape}')
    # 绘制圆形
    draw = np.zeros((height, width), dtype=np.uint8)
    draw_circle(draw, circle_enemy, points)
    draw_enemy = cv2.multiply(draw, 4)
    draw_enemy = subtract_blur(draw_enemy, 3)

    # 寻找峰值
    points = inrange(draw_enemy, lower=36)

    points=group_points(points,10)
    if points.shape[0] > 3:
        print(f'AimDetector.predict_enemy() 峰值过多: {points.shape}')
    points_enemy = points
    # print(points)
    return draw_enemy,points_enemy


def predict_item(v,radius_item,mask_interact,circle_item):
    min_radius, max_radius = radius_item
    width, height = image_size(v)

    # 获取白色圆形 `y`
    y = subtract_blur(v, 9)

    white = cv2.inRange(v, 125, 128)
    cv2.bitwise_and(y, white, dst=y)
    # 获取青色光晕 `v`
    cv2.inRange(v, 50, 84, dst=v)


    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cv2.dilate(v, kernel, dst=v)
    # 去除噪声，只保留青色圆形
    cv2.bitwise_and(y, v, dst=y)
    # 去除游戏UI
    cv2.bitwise_and(y, mask_interact, dst=y)
    # 去除边缘上的点，否则 draw_circle() 会溢出
    remove_border(y, max_radius)

    # 获取所有像素
    points = inrange(y, lower=18)
    # print(points.shape)
    if points.shape[0] > 1000:
        print(f'AimDetector.predict_item() 绘制点过多: {points.shape}')
    # 绘制圆形
    draw = np.zeros((height, width), dtype=np.uint8)
    draw_circle(draw, circle_item, points)
    draw = subtract_blur(draw, 5)
    draw_item = cv2.multiply(draw, 4)
    cv2.imshow('predict_item', draw_item)
    cv2.waitKey(0)
    # 寻找峰值
    points = inrange(draw_item, lower=18)
    points=group_points(points,10)
    if points.shape[0] > 3:
        print(f'AimDetector.predict_item() 峰值过多: {points.shape}')
    points_item = points
    # print(points)
    return draw_item,points_item
def aimed_enemy(points_enemy) -> tuple[int, int] | None:
    if points_enemy is None:
        return None

    count = len(points_enemy)
    if count >= 2:
        print(f'发现多个瞄准的敌人: {points_enemy}')
    try:
        point = points_enemy[0]
        return tuple(point)
    except IndexError:
        return None
def aimed_item(points_item) -> tuple[int, int] | None:
    if points_item is None:
        return None
    try:
        _ = points_item[1]
        print(f'发现多个瞄准的物品，使用第一个点 {points_item}')
    except IndexError:
        pass
    try:
        point = points_item[0]
        return tuple(point)
    except IndexError:
        return None


@timer
def predict(image, enemy=True, item=True, show_log=True, debug=False):
    """
    在图像上预测 `瞄准`，耗时约 10.0~10.5ms。

    参数:
        image:
        enemy: True 表示预测敌人
        item: True 表示预测物品
        show_log:
        debug: True 表示显示 AimDetector 图像
    """

    draw_item = None
    draw_enemy = None
    points_item = None
    points_enemy = None




    # 1.5~2.0ms
    yuv = cv2.cvtColor(image, cv2.COLOR_RGB2YUV)
    v = yuv[:, :, 2]
    h = yuv[:, :, 0]
    # 4.0~4.5ms
    if enemy:
        draw_enemy,points_enemy =predict_enemy(h.copy(), v.copy(), radius_enemy,mask_interact,circle_enemy)
    # 3.0~3.5ms
    if item:
        draw_item,points_item =predict_item(v.copy(), radius_item,mask_interact,circle_item)

    if show_log:
        kv = {}
        kv['enemy'] = aimed_enemy(points_enemy)
        kv['item'] = aimed_item(points_item)
        if kv:
            print(f'Aimed: {dict_to_kv(kv)}')
    if debug:
        show_aim(draw_enemy,draw_item)


def show_aim(draw_enemy,draw_item):
    if draw_enemy is None:
        if draw_item is None:
            return
        else:
            r = g = b = draw_item
    else:
        if draw_item is None:
            r = g = b = draw_enemy
        else:
            r = draw_enemy
            g = b = draw_item

    image = cv2.merge([b, g, r])

    cv2.imshow('AimDetector', image)
    cv2.waitKey(0)
if __name__ == '__main__':
    radius_enemy = (24, 25)
    radius_item = (5, 7)
    mask_interact = load_image('./MASK_MAP_INTERACT.png')
    mask_interact = cv2.cvtColor(mask_interact, cv2.COLOR_BGR2GRAY)
    circle_enemy=create_circle(*radius_enemy)
    circle_item=create_circle(*radius_item)
    image=load_image('./20260219_104046.png')
    if isinstance(image, str):
        image = load_image(image)
    predict(image,debug= False)