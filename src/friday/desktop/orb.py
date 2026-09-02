import math
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

class FridayOrb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(120, 120)
        self.state = "idle" # idle, listening, thinking, speaking, error
        
        self._pulse_value = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_pulse)
        self.timer.start(30)
        
        self.time_elapsed = 0.0

    def update_pulse(self):
        self.time_elapsed += 0.05
        self.update()

    def set_state(self, state: str):
        self.state = state
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # In PyQt6, we need QPointF for gradients
        center = QPointF(self.rect().center())
        radius = min(self.width(), self.height()) / 2.0 - 10
        
        base_color = QColor(0, 200, 255) # Cyan futuristic
        if self.state == "listening":
            base_color = QColor(0, 255, 100) # Greenish
        elif self.state == "thinking":
            base_color = QColor(200, 0, 255) # Purple
        elif self.state == "speaking":
            base_color = QColor(255, 100, 0) # Orange
        elif self.state == "error":
            base_color = QColor(255, 0, 0) # Red
            
        pulse = (math.sin(self.time_elapsed) + 1.0) / 2.0
        
        # Outer glow
        gradient = QRadialGradient(center, radius + pulse * 10)
        gradient.setColorAt(0, base_color)
        gradient.setColorAt(1, QColor(0, 0, 0, 0))
        
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        # drawEllipse requires floats or QPointF
        painter.drawEllipse(center, radius + pulse * 10, radius + pulse * 10)
        
        # Inner core
        core_radius = radius * 0.6
        if self.state == "thinking":
            # Spinning arc
            pen = QPen(base_color, 4)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arc_len = 120 + pulse * 60
            start_angle = int((self.time_elapsed * 100) % 360 * 16)
            painter.drawArc(
                int(center.x() - core_radius), 
                int(center.y() - core_radius), 
                int(core_radius * 2), 
                int(core_radius * 2), 
                start_angle, 
                int(arc_len * 16)
            )
        else:
            painter.setBrush(base_color)
            painter.drawEllipse(center, core_radius, core_radius)
            
        # Inner-inner detail
        painter.setBrush(QColor(255, 255, 255, 150))
        painter.drawEllipse(center, core_radius * 0.3, core_radius * 0.3)
