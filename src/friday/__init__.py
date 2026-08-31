"""FRIDAY — Fully Responsive Intelligent Digital Assistant for You."""

import warnings

# Suppress noisy upstream Google GenAI SDK AFC warnings and pywinauto COM threading notifications
warnings.filterwarnings("ignore", message=".*automatic function calling.*")
warnings.filterwarnings("ignore", message=".*Revert to STA COM threading mode.*")

__version__ = "2.0.0"

