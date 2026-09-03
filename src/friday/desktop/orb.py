"""Holographic 9-state animated PyQt6 orb widget inspired by Iron Man HUD & Sagar Tamang."""

from __future__ import annotations

import math
from typing import Any
from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

STATE_COLORS: dict[str, tuple[QColor, str]] = {
    "idle": (QColor(0, 210, 255), "Holographic Cyan"),
    "listening": (QColor(0, 255, 128), "Active Green"),
    "thinking": (QColor(180, 80, 255), "Cognitive Purple"),
    "planning": (QColor(80, 150, 255), "Strategy Azure"),
    "executing": (QColor(255, 205, 0), "Reactor Gold"),
    "confirmation": (QColor(255, 150, 0), "Warning Amber"),
    "speaking": (QColor(255, 85, 25), "Voice Orange"),
    "error": (QColor(255, 35, 50), "Alert Crimson"),
    "disconnected": (QColor(115, 125, 135), "Offline Steel"),
}


class FridayOrb(QWidget):
    """Futuristic holographic orb with multi-ring counter-rotation and 9 visual states."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(130, 130)
        self.state = "idle"

        self.time_elapsed = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate_step)
        self.timer.start(25)  # 40 FPS smooth rendering

    def _animate_step(self) -> None:
        # State-dependent animation velocity
        speed = 0.05
        if self.state in ("thinking", "executing"):
            speed = 0.10
        elif self.state in ("listening", "speaking"):
            speed = 0.08
        elif self.state in ("idle", "disconnected"):
            speed = 0.03

        self.time_elapsed += speed
        self.update()

    def set_state(self, state: str) -> None:
        s = state.lower().strip()
        if s in STATE_COLORS:
            self.state = s
        else:
            self.state = "idle"
        self.update()

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.rect().center())
        base_radius = min(self.width(), self.height()) / 2.0 - 12.0

        base_color, _ = STATE_COLORS.get(self.state, (QColor(0, 210, 255), "Cyan"))

        pulse = (math.sin(self.time_elapsed * 2.5) + 1.0) / 2.0
        fast_pulse = (math.sin(self.time_elapsed * 6.0) + 1.0) / 2.0

        # 1. Diffuse Holographic Outer Aura
        aura_radius = base_radius + (pulse * 12.0)
        gradient = QRadialGradient(center, aura_radius)
        gradient.setColorAt(0.0, QColor(base_color.red(), base_color.green(), base_color.blue(), 160))
        gradient.setColorAt(0.6, QColor(base_color.red(), base_color.green(), base_color.blue(), 40))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, aura_radius, aura_radius)

        # 2. Outer Wireframe / Ring Segments
        ring_radius = base_radius * 0.88
        pen = QPen(base_color, 1.8)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.state in ("thinking", "planning", "executing"):
            # Dynamic spinning HUD arcs
            rot_angle = (self.time_elapsed * 120.0) % 360.0
            painter.drawArc(
                int(center.x() - ring_radius),
                int(center.y() - ring_radius),
                int(ring_radius * 2),
                int(ring_radius * 2),
                int(rot_angle * 16),
                int(100 * 16),
            )
            painter.drawArc(
                int(center.x() - ring_radius),
                int(center.y() - ring_radius),
                int(ring_radius * 2),
                int(ring_radius * 2),
                int((rot_angle + 180) * 16),
                int(100 * 16),
            )
        elif self.state == "listening":
            # Expanding audio wave ripple
            painter.drawEllipse(center, ring_radius + (fast_pulse * 4), ring_radius + (fast_pulse * 4))
        else:
            painter.drawEllipse(center, ring_radius, ring_radius)

        # 3. Intermediate Counter-Rotating Ring
        mid_radius = base_radius * 0.65
        mid_pen = QPen(QColor(base_color.red(), base_color.green(), base_color.blue(), 190), 2.2)
        painter.setPen(mid_pen)
        counter_angle = -(self.time_elapsed * 90.0) % 360.0
        painter.drawArc(
            int(center.x() - mid_radius),
            int(center.y() - mid_radius),
            int(mid_radius * 2),
            int(mid_radius * 2),
            int(counter_angle * 16),
            int(140 * 16),
        )

        # 4. Dense Inner Core Sphere
        core_scale = 1.0
        if self.state == "speaking":
            core_scale = 1.0 + (fast_pulse * 0.25)
        elif self.state == "confirmation":
            core_scale = 1.0 + (pulse * 0.15)

        core_radius = base_radius * 0.42 * core_scale
        core_grad = QRadialGradient(center, core_radius)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 230))
        core_grad.setColorAt(0.5, base_color)
        core_grad.setColorAt(1.0, QColor(base_color.red(), base_color.green(), base_color.blue(), 100))

        painter.setBrush(core_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, core_radius, core_radius)

        # 5. Core Center Highlight
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawEllipse(center, core_radius * 0.25, core_radius * 0.25)
