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
        self.offset = QPoint()
        
        self.init_ui()
        self.resize(300, 150)
        self.move(100, 100) # Default position, should ideally save to settings

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        
        # Orb Container (always visible)
        self.orb_container = QWidget()
        self.orb_layout = QHBoxLayout(self.orb_container)
        self.orb_layout.setContentsMargins(0, 0, 0, 0)
        
        self.orb = FridayOrb(self)
        self.orb_layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Status Label
        self.status_label = QLabel("SYSTEM IDLE")
        self.status_label.setStyleSheet("color: rgba(0, 255, 255, 0.7); font-family: 'Courier New'; font-weight: bold;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.orb_layout.addWidget(self.status_label)
        self.layout.addWidget(self.orb_container)
        
        # Expanded Chat Interface
        self.chat_panel = QFrame()
        self.chat_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(10, 15, 20, 200);
                border: 1px solid rgba(0, 200, 255, 50);
                border-radius: 10px;
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
        self.text_input.setStyleSheet("background: rgba(255, 255, 255, 20); border: 1px solid rgba(255,255,255,50); color: white; border-radius: 5px; padding: 5px;")
        self.text_input.setPlaceholderText("Type a command...")
        self.text_input.returnPressed.connect(self._on_send)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet("background: rgba(0, 200, 255, 50); border: 1px solid rgba(0, 200, 255, 100); color: white; border-radius: 5px; padding: 5px;")
        self.send_btn.clicked.connect(self._on_send)
        
        self.mic_btn = QPushButton("Mic")
        self.mic_btn.setStyleSheet("background: rgba(255, 100, 0, 50); border: 1px solid rgba(255, 100, 0, 100); color: white; border-radius: 5px; padding: 5px;")
        self.mic_btn.clicked.connect(self.toggle_voice_signal.emit)
        
        input_layout.addWidget(self.text_input)
        input_layout.addWidget(self.send_btn)
        input_layout.addWidget(self.mic_btn)
        
        chat_layout.addLayout(input_layout)
        self.layout.addWidget(self.chat_panel)

    def _on_send(self):
        text = self.text_input.text().strip()
        if text:
            self.append_transcript("You", text)
            self.send_text_signal.emit(text)
            self.text_input.clear()

    def append_transcript(self, sender: str, text: str):
        color = "#00c8ff" if sender.lower() == "friday" else "#ffffff"
        self.transcript.append(f"<b style='color:{color};'>{sender}:</b> {text}")
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_status(self, text: str, state: str = "idle"):
        self.status_label.setText(text.upper())
        self.orb.set_state(state)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.offset = event.position().toPoint()
        elif event.button() == Qt.MouseButton.RightButton:
            # Right click to toggle expanded view
            self.toggle_expanded()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(self.pos() + event.position().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False

    def toggle_expanded(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.chat_panel.show()
            self.resize(350, 450)
        else:
            self.chat_panel.hide()
            self.resize(300, 150)
