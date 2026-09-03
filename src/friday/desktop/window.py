"""Futuristic Windows Desktop Companion Overlay for FRIDAY.

Provides a frameless, always-on-top, translucent glassmorphic interface
supporting all 9 visual assistant states, interactive confirmation prompts,
draggable placement, and Windows global activation hotkey (Ctrl + Shift + Space).
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from friday.desktop.orb import STATE_COLORS, FridayOrb

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK_SPACE = 0x20
WM_HOTKEY = 0x0312
HOTKEY_ID = 1001


class DesktopOverlay(QWidget):
    """Futuristic floating desktop assistant overlay for FRIDAY."""

    toggle_voice_signal = pyqtSignal()
    send_text_signal = pyqtSignal(str)
    confirmation_response_signal = pyqtSignal(bool)
    close_signal = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()

        # Frameless, translucent, always-on-top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.expanded = False
        self.dragging = False
        self.drag_start_pos = QPoint()
        self.offset = QPoint()
        self.current_state = "idle"

        self._hotkey_registered = False

        self.init_ui()
        self.resize(340, 160)
        self.move(100, 100)

        self._setup_global_hotkey()

    def _setup_global_hotkey(self) -> None:
        """Register global Windows hotkey: Ctrl + Shift + Space."""
        if sys.platform == "win32":
            try:
                hwnd = int(self.winId())
                ok = ctypes.windll.user32.RegisterHotKey(
                    hwnd, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT, VK_SPACE
                )
                self._hotkey_registered = bool(ok)
            except Exception:
                self._hotkey_registered = False

        # In-app fallback shortcut
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+Space"), self)
        shortcut.activated.connect(self.toggle_visibility_or_focus)

    def nativeEvent(self, event_type: Any, message: Any) -> tuple[bool, int]:
        """Intercept Windows WM_HOTKEY messages."""
        if sys.platform == "win32" and event_type == b"windows_generic_MSG":
            try:
                import ctypes.wintypes

                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.toggle_visibility_or_focus()
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def toggle_visibility_or_focus(self) -> None:
        if self.isVisible():
            if self.isActiveWindow():
                self.hide()
            else:
                self.activateWindow()
                self.raise_()
        else:
            self.show()
            self.activateWindow()
            self.raise_()

    def init_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(6)

        # 1. Top Bar / Compact Floating Orb Container
        self.top_bar = QFrame()
        self.top_bar.setStyleSheet("""
            QFrame {
                background-color: rgba(6, 12, 20, 210);
                border: 1px solid rgba(0, 210, 255, 75);
                border-radius: 16px;
            }
        """)
        self.top_layout = QHBoxLayout(self.top_bar)
        self.top_layout.setContentsMargins(12, 6, 12, 6)

        # The 9-State Animated Holographic Orb
        self.orb = FridayOrb(self)
        self.top_layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignCenter)

        # Live Status & Telemetry Readout
        status_vbox = QVBoxLayout()
        self.status_title = QLabel("F.R.I.D.A.Y.")
        self.status_title.setStyleSheet("color: rgba(0, 230, 255, 0.95); font-family: 'Segoe UI'; font-weight: bold; font-size: 13pt; letter-spacing: 2px;")
        
        self.status_label = QLabel("SYSTEM IDLE")
        self.status_label.setStyleSheet("color: rgba(0, 210, 255, 0.85); font-family: 'Consolas'; font-size: 9.5pt;")
        
        status_vbox.addWidget(self.status_title)
        status_vbox.addWidget(self.status_label)
        self.top_layout.addLayout(status_vbox)

        # Header Control Buttons (Expand, Mic, Close)
        btn_layout = QHBoxLayout()
        self.expand_btn = QPushButton("▾")
        self.expand_btn.setToolTip("Expand / Collapse Transcript (or click orb)")
        self.expand_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 210, 255, 30);
                border: 1px solid rgba(0, 210, 255, 90);
                color: #00ffff;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12pt;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(0, 210, 255, 80);
            }
        """)
        self.expand_btn.clicked.connect(self.toggle_expanded)

        self.close_btn = QPushButton("✕")
        self.close_btn.setToolTip("Hide FRIDAY (Press Ctrl+Shift+Space to show)")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 50, 50, 30);
                border: 1px solid rgba(255, 50, 50, 90);
                color: #ff6666;
                border-radius: 6px;
                font-weight: bold;
                font-size: 10pt;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background: rgba(255, 50, 50, 80);
            }
        """)
        self.close_btn.clicked.connect(self.hide)

        btn_layout.addWidget(self.expand_btn)
        btn_layout.addWidget(self.close_btn)
        self.top_layout.addLayout(btn_layout)

        self.main_layout.addWidget(self.top_bar)

        # 2. Interactive Confirmation Prompt (for SENSITIVE / DANGEROUS actions)
        self.confirm_panel = QFrame()
        self.confirm_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 20, 5, 230);
                border: 1px solid rgba(255, 170, 0, 180);
                border-radius: 12px;
                padding: 6px;
            }
        """)
        self.confirm_panel.hide()
        confirm_layout = QVBoxLayout(self.confirm_panel)
        confirm_layout.setContentsMargins(8, 8, 8, 8)

        self.confirm_label = QLabel("Authorize sensitive action?")
        self.confirm_label.setStyleSheet("color: #ffcc00; font-weight: bold; font-size: 9.5pt;")
        self.confirm_label.setWordWrap(True)
        confirm_layout.addWidget(self.confirm_label)

        confirm_btns = QHBoxLayout()
        self.confirm_btn = QPushButton("Authorize")
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 200, 100, 70);
                border: 1px solid rgba(0, 255, 128, 150);
                color: white;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(0, 255, 128, 120); }
        """)
        self.confirm_btn.clicked.connect(lambda: self._handle_confirmation(True))

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: rgba(200, 50, 50, 70);
                border: 1px solid rgba(255, 60, 60, 150);
                color: white;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(255, 60, 60, 120); }
        """)
        self.cancel_btn.clicked.connect(lambda: self._handle_confirmation(False))

        confirm_btns.addWidget(self.confirm_btn)
        confirm_btns.addWidget(self.cancel_btn)
        confirm_layout.addLayout(confirm_btns)
        self.main_layout.addWidget(self.confirm_panel)

        # 3. Expanded Conversation & Controls Panel
        self.chat_panel = QFrame()
        self.chat_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(6, 12, 20, 235);
                border: 1px solid rgba(0, 210, 255, 80);
                border-radius: 14px;
            }
        """)
        self.chat_panel.hide()

        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(10, 10, 10, 10)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setStyleSheet("""
            QTextEdit {
                background: transparent;
                border: none;
                color: white;
                font-family: 'Segoe UI';
                font-size: 10pt;
            }
        """)
        chat_layout.addWidget(self.transcript)

        # 4. Live Task Execution Checklist (Microsoft JARVIS Task Graph HUD)
        self._task_labels: dict[str, QLabel] = {}
        self.tasks_frame = QFrame()
        self.tasks_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(15, 25, 35, 180);
                border: 1px solid rgba(0, 210, 255, 60);
                border-radius: 8px;
                padding: 4px;
            }
        """)
        self.tasks_frame.hide()
        self.tasks_layout = QVBoxLayout(self.tasks_frame)
        self.tasks_layout.setContentsMargins(6, 4, 6, 4)
        self.tasks_layout.setSpacing(2)
        chat_layout.addWidget(self.tasks_frame)

        input_layout = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 255, 255, 15);
                border: 1px solid rgba(0, 210, 255, 60);
                color: white;
                border-radius: 6px;
                padding: 7px 10px;
                font-size: 10pt;
            }
            QLineEdit:focus {
                border: 1px solid rgba(0, 230, 255, 150);
            }
        """)
        self.text_input.setPlaceholderText("Ask FRIDAY or enter command...")
        self.text_input.returnPressed.connect(self._on_send)

        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 210, 255, 60);
                border: 1px solid rgba(0, 210, 255, 120);
                color: white;
                border-radius: 6px;
                padding: 7px 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(0, 210, 255, 100); }
        """)
        self.send_btn.clicked.connect(self._on_send)

        self.mic_btn = QPushButton("Mic")
        self.mic_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 90, 30, 60);
                border: 1px solid rgba(255, 90, 30, 120);
                color: white;
                border-radius: 6px;
                padding: 7px 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(255, 90, 30, 110); }
        """)
        self.mic_btn.clicked.connect(self.toggle_voice_signal.emit)

        input_layout.addWidget(self.text_input)
        input_layout.addWidget(self.send_btn)
        input_layout.addWidget(self.mic_btn)
        chat_layout.addLayout(input_layout)

        self.main_layout.addWidget(self.chat_panel)

    def _on_send(self) -> None:
        text = self.text_input.text().strip()
        if text:
            self.append_transcript("You", text)
            self.send_text_signal.emit(text)
            self.text_input.clear()

    def append_transcript(self, sender: str, text: str) -> None:
        color = "#00ffff" if sender.lower() == "friday" else "#ffffff"
        self.transcript.append(f"<b style='color:{color};'>{sender}:</b> {text}")
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_status(self, text: str, state: str = "idle") -> None:
        """Transition between the 9 visual assistant states."""
        self.current_state = state.lower().strip()
        self.status_label.setText(text.upper())
        self.orb.set_state(self.current_state)

        # Style status text with state theme
        base_color, _ = STATE_COLORS.get(self.current_state, (QColor(0, 210, 255), "Cyan"))
        self.status_label.setStyleSheet(
            f"color: rgb({base_color.red()}, {base_color.green()}, {base_color.blue()}); "
            f"font-family: 'Consolas'; font-size: 9.5pt; font-weight: bold;"
        )

    def update_task_progress(self, task_id: str, desc: str, status: str) -> None:
        """Update live task progress checklist item (✓ completed, ● running, ○ pending, ✕ failed)."""
        status_lower = status.lower()
        symbol = "○"
        color = "#888888"
        if "complete" in status_lower or "done" in status_lower:
            symbol = "✓"
            color = "#00ff88"
        elif "running" in status_lower or "start" in status_lower:
            symbol = "●"
            color = "#ffcc00"
        elif "failed" in status_lower or "error" in status_lower:
            symbol = "✕"
            color = "#ff3344"

        clean_desc = desc[:65] + "..." if len(desc) > 65 else desc
        label_text = f"<span style='color:{color}; font-weight:bold;'>{symbol}</span> <span style='color:#e0e0e0;'>{clean_desc}</span>"

        if task_id in self._task_labels:
            self._task_labels[task_id].setText(label_text)
        else:
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-family: 'Consolas', 'Segoe UI'; font-size: 9pt;")
            lbl.setWordWrap(True)
            self.tasks_layout.addWidget(lbl)
            self._task_labels[task_id] = lbl
            self.tasks_frame.show()

    def clear_task_progress(self) -> None:
        """Clear all items in the task execution checklist."""
        for lbl in list(self._task_labels.values()):
            self.tasks_layout.removeWidget(lbl)
            lbl.deleteLater()
        self._task_labels.clear()
        self.tasks_frame.hide()

    def request_confirmation(self, prompt: str) -> None:
        """Display the interactive confirmation prompt."""
        self.confirm_label.setText(prompt)
        self.confirm_panel.show()
        self.set_status("Awaiting Confirmation", state="confirmation")

    def _handle_confirmation(self, approved: bool) -> None:
        self.confirm_panel.hide()
        self.confirmation_response_signal.emit(approved)
        if approved:
            self.set_status("Authorized", state="executing")
        else:
            self.set_status("Operation Cancelled", state="idle")

    # Mouse & Window Dragging Handling
    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_start_pos = event.position().toPoint()
            self.offset = event.position().toPoint()
        elif event.button() == Qt.MouseButton.RightButton:
            self.toggle_expanded()

    def mouseDoubleClickEvent(self, event: Any) -> None:
        self.toggle_expanded()

    def mouseMoveEvent(self, event: Any) -> None:
        if self.dragging:
            self.move(self.pos() + event.position().toPoint() - self.offset)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                delta = (event.position().toPoint() - self.drag_start_pos).manhattanLength()
                if delta < 6:
                    self.toggle_expanded()
            self.dragging = False

    def toggle_expanded(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.chat_panel.show()
            self.expand_btn.setText("▴")
            self.resize(360, 500)
        else:
            self.chat_panel.hide()
            self.expand_btn.setText("▾")
            self.resize(340, 160)

    def closeEvent(self, event: Any) -> None:
        if sys.platform == "win32" and self._hotkey_registered:
            try:
                ctypes.windll.user32.UnregisterHotKey(int(self.winId()), HOTKEY_ID)
            except Exception:
                pass
        self.close_signal.emit()
        super().closeEvent(event)
