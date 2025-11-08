import sys
import os
import random
from PyQt5.QtCore import Qt, QTimer, QSize, QPoint
from PyQt5.QtGui import QPixmap, QMovie, QIcon
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QMenu, QAction, QInputDialog


class HuskyPet(QMainWindow):
    def __init__(self):
        super().__init__()

        # 🐾 基础配置
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowIcon(QIcon("husky_icon.ico"))

        # 资源路径
        self.resource_dir = r"C:\www\test\img\py\哈士奇"

        # 当前显示尺寸比例
        self.scale_factor = 1.0

        # 图片资源缓存
        self.image_files = self.load_images()
        self.current_image = None
        self.current_movie = None

        # 主标签（显示宠物）
        self.husky_label = QLabel(self)
        self.husky_label.setAlignment(Qt.AlignCenter)
        self.setCentralWidget(self.husky_label)

        # 初始显示图片
        self.show_random_image()

        # 随机动作定时器
        self.random_timer = QTimer(self)
        self.random_timer.timeout.connect(self.random_behavior)
        self.random_timer.start(8000)  # 每8秒触发一次

        # 拖拽标记
        self.dragging = False
        self.drag_position = QPoint()

        # 右键菜单
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

        # 窗口初始位置
        self.move(100, 100)

    # === 功能1：加载图片资源 ===
    def load_images(self):
        """从资源目录加载png/gif图片"""
        if not os.path.exists(self.resource_dir):
            print(f"❌ 目录不存在：{self.resource_dir}")
            return []
        files = [f for f in os.listdir(self.resource_dir)
                 if f.lower().endswith(('.png', '.gif'))]
        full_paths = [os.path.join(self.resource_dir, f) for f in files]
        print(f"✅ 已加载 {len(full_paths)} 个图片资源")
        return full_paths

    # === 功能2：显示随机图片（支持GIF） ===
    def show_random_image(self):
        """随机显示一张哈士奇图片"""
        if not self.image_files:
            return

        image_path = random.choice(self.image_files)
        self.display_image(image_path)

    def display_image(self, path):
        """显示单张图片或动画"""
        if self.current_movie:
            self.current_movie.stop()

        if path.lower().endswith(".gif"):
            movie = QMovie(path)
            movie.setScaledSize(self.scaled_size(movie.currentImage()))
            self.husky_label.setMovie(movie)
            movie.start()
            self.current_movie = movie
        else:
            pixmap = QPixmap(path)
            scaled = pixmap.scaled(self.scaled_size(pixmap.size()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.husky_label.setPixmap(scaled)
            self.current_movie = None

        self.adjustSize()

    def scaled_size(self, size):
        """根据缩放系数返回缩放后的尺寸"""
        return QSize(int(size.width() * self.scale_factor), int(size.height() * self.scale_factor))

    # === 功能3：随机行为 ===
    def random_behavior(self):
        behavior = random.choice(["move", "change"])
        if behavior == "move":
            self.random_move()
        else:
            self.show_random_image()

    def random_move(self):
        """随机移动位置"""
        screen = QApplication.desktop().screenGeometry()
        x = random.randint(0, screen.width() - self.width())
        y = random.randint(0, screen.height() - self.height())
        self.move(x, y)

    # === 功能4：右键菜单 ===
    def show_menu(self, pos):
        menu = QMenu(self)

        resize_action = QAction("调整大小", self)
        resize_action.triggered.connect(self.change_size)
        menu.addAction(resize_action)

        refresh_action = QAction("换个动作", self)
        refresh_action.triggered.connect(self.show_random_image)
        menu.addAction(refresh_action)

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)

        menu.exec_(self.mapToGlobal(pos))

    # === 功能5：调整大小 ===
    def change_size(self):
        """弹窗输入缩放比例"""
        value, ok = QInputDialog.getDouble(self, "调整大小", "请输入缩放倍数 (0.5~2.0)：", self.scale_factor, 0.1, 5.0, 1)
        if ok:
            self.scale_factor = value
            self.show_random_image()

    # === 功能6：拖拽事件 ===
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPos() - self.drag_position)

    def mouseReleaseEvent(self, event):
        self.dragging = False


if __name__ == '__main__':
    app = QApplication(sys.argv)
    pet = HuskyPet()
    pet.show()
    sys.exit(app.exec_())
