import sys
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import QIcon, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTextEdit, QLineEdit, QApplication, QScrollArea, QFrame, QSizePolicy
)
from friday.desktop.orb import FridayOrb

class DesktopOverlay(QWidget):
    # Signals for bridging with the background engine
    toggle_voice_signal = pyqtSignal()
    send_text_signal = pyqtSignal(str)
    close_signal = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        
        # Frameless, transparent, always-on-top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.expanded = False
        self.dragging = False
        self.drag_start_pos = QPoint()
        self.offset = QPoint()
        
        self.init_ui()
        self.resize(320, 150)
        self.move(100, 100) # Default position

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Top Bar / Orb Container (always visible)
        self.top_bar = QFrame()
        self.top_bar.setStyleSheet("""
            QFrame {
                background-color: rgba(10, 15, 20, 180);
                border: 1px solid rgba(0, 200, 255, 60);
                border-radius: 12px;
            }
        """)
        self.top_layout = QHBoxLayout(self.top_bar)
        self.top_layout.setContentsMargins(8, 4, 8, 4)
        
        self.orb = FridayOrb(self)
        self.top_layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Status Label
        self.status_label = QLabel("SYSTEM IDLE")
        self.status_label.setStyleSheet("color: rgba(0, 255, 255, 0.9); font-family: 'Courier New'; font-weight: bold; font-size: 11pt;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.top_layout.addWidget(self.status_label)
        
        # Controls in top bar
        btn_layout = QHBoxLayout()
        self.expand_btn = QPushButton("▾")
        self.expand_btn.setToolTip("Expand / Collapse (or Click the Orb)")
        self.expand_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 200, 255, 30);
                border: 1px solid rgba(0, 200, 255, 80);
                color: #00ffff;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11pt;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background: rgba(0, 200, 255, 70);
            }
        """)
        self.expand_btn.clicked.connect(self.toggle_expanded)
        
        self.close_btn = QPushButton("✕")
        self.close_btn.setToolTip("Hide FRIDAY (Press Ctrl+Shift+Space to show)")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 60, 60, 30);
                border: 1px solid rgba(255, 60, 60, 80);
                color: #ff6666;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10pt;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background: rgba(255, 60, 60, 70);
            }
        """)
        self.close_btn.clicked.connect(self.hide)
        
        btn_layout.addWidget(self.expand_btn)
        btn_layout.addWidget(self.close_btn)
        self.top_layout.addLayout(btn_layout)
        
        self.main_layout.addWidget(self.top_bar)
        
        # Expanded Chat Interface
        self.chat_panel = QFrame()
        self.chat_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(10, 15, 20, 230);
                border: 1px solid rgba(0, 200, 255, 70);
                border-radius: 12px;
            }
        """)
        self.chat_panel.hide()
        
        chat_layout = QVBoxLayout(self.chat_panel)
        
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setStyleSheet("background: transparent; border: none; color: white; font-family: 'Segoe UI'; font-size: 10pt;")
        chat_layout.addWidget(self.transcript)
        
        input_layout = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setStyleSheet("background: rgba(255, 255, 255, 20); border: 1px solid rgba(255,255,255,60); color: white; border-radius: 6px; padding: 6px;")
        self.text_input.setPlaceholderText("Type a command (e.g. open chrome)...")
        self.text_input.returnPressed.connect(self._on_send)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet("background: rgba(0, 200, 255, 60); border: 1px solid rgba(0, 200, 255, 120); color: white; border-radius: 6px; padding: 6px 12px; font-weight: bold;")
        self.send_btn.clicked.connect(self._on_send)
        
        self.mic_btn = QPushButton("Mic")
        self.mic_btn.setStyleSheet("background: rgba(255, 100, 0, 60); border: 1px solid rgba(255, 100, 0, 120); color: white; border-radius: 6px; padding: 6px 12px; font-weight: bold;")
        self.mic_btn.clicked.connect(self.toggle_voice_signal.emit)
        
        input_layout.addWidget(self.text_input)
        input_layout.addWidget(self.send_btn)
        input_layout.addWidget(self.mic_btn)
        
        chat_layout.addLayout(input_layout)
        self.main_layout.addWidget(self.chat_panel)

    def _on_send(self):
        text = self.text_input.text().strip()
        if text:
            self.append_transcript("You", text)
            self.send_text_signal.emit(text)
            self.text_input.clear()

    def append_transcript(self, sender: str, text: str):
        color = "#00ffff" if sender.lower() == "friday" else "#ffffff"
        self.transcript.append(f"<b style='color:{color};'>{sender}:</b> {text}")
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_status(self, text: str, state: str = "idle"):
        self.status_label.setText(text.upper())
        self.orb.set_state(state)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_start_pos = event.position().toPoint()
            self.offset = event.position().toPoint()
        elif event.button() == Qt.MouseButton.RightButton:
            self.toggle_expanded()

    def mouseDoubleClickEvent(self, event):
        self.toggle_expanded()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(self.pos() + event.position().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                delta = (event.position().toPoint() - self.drag_start_pos).manhattanLength()
                if delta < 6:
                    self.toggle_expanded()
            self.dragging = False

    def toggle_expanded(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.chat_panel.show()
            self.expand_btn.setText("▴")
            self.resize(360, 480)
        else:
            self.chat_panel.hide()
            self.expand_btn.setText("▾")
            self.resize(320, 150)
