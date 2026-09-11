"""Windows Laptop System Controller for FRIDAY.

Provides comprehensive, native Windows laptop control:
- Instant website & media launch (YouTube, Google, GitHub, etc.)
- YouTube video and music playback directly in Google Chrome
- Volume & multimedia controls (mute, volume up/down, exact percentage, play/pause, skip)
- Window management (show desktop, minimize all, close window, lock pc)
- System lock, sleep, and power operations
- Application launching & closing (Chrome, VS Code, Notepad, Calc, Terminal, Settings, Task Manager, Spotify, etc.)
- Keyboard & typing automation (typing, key presses, hotkeys)
- Display brightness adjustment
- System telemetry (battery percentage, power status, CPU, RAM, disk)
- Network status (WiFi, IP address, ping latency)
- Filesystem folder shortcuts (Downloads, Desktop, Documents, Pictures, Videos, C:)
- Direct PowerShell execution for arbitrary laptop directives
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from typing import Any, Tuple

import psutil
from friday.core.logging import get_logger
from friday.devices.app_launcher import launch_desktop_app

logger = get_logger("devices.windows_friday")

# Virtual-Key Codes for Windows multimedia & volume
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_LWIN = 0x5B
KEYEVENTF_KEYUP = 0x0002

COMMON_WEBSITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "github": "https://www.github.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://www.twitter.com",
    "x": "https://www.x.com",
    "chatgpt": "https://chatgpt.com",
    "openai": "https://www.openai.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "amazon": "https://www.amazon.com",
    "wikipedia": "https://www.wikipedia.org",
    "gmail": "https://mail.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "linkedin": "https://www.linkedin.com",
    "stackoverflow": "https://stackoverflow.com",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
}

APP_PROCESS_MAP = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
    "vs code": "Code.exe",
    "vscode": "Code.exe",
    "code": "Code.exe",
    "spotify": "Spotify.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "task manager": "Taskmgr.exe",
    "taskmgr": "Taskmgr.exe",
    "camera": "WindowsCamera.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "vlc": "vlc.exe",
    "discord": "Discord.exe",
    "whatsapp": "WhatsApp.exe",
}

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def get_chrome_path() -> str | None:
    """Find installed Google Chrome executable path."""
    for p in CHROME_PATHS:
        if p and os.path.exists(p):
            return p
    return None


class WindowsFridayController:
    """Master laptop controller providing autonomous OS control for FRIDAY on Windows."""

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32

    def _send_key_event(self, vk: int) -> None:
        """Simulate single key press and release."""
        self.user32.keybd_event(vk, 0, 0, 0)
        self.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    # -------------------------------------------------------------------------
    # 1. Web, YouTube & Search Control
    # -------------------------------------------------------------------------
    def open_url(self, url: str) -> bool:
        """Open an arbitrary web URL in Google Chrome (preferred) or default browser."""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        try:
            chrome = get_chrome_path()
            if chrome:
                subprocess.Popen([chrome, url])
                logger.info(f"Opened URL in Chrome: {url}")
                return True
            webbrowser.open(url)
            logger.info(f"Opened URL: {url}")
            return True
        except Exception as e:
            logger.error(f"Failed to open URL {url}: {e}")
            try:
                webbrowser.open(url)
                return True
            except Exception:
                return False

    def open_website(self, site_name: str) -> Tuple[bool, str]:
        """Open a named website (YouTube, Google, GitHub, etc.) or web address."""
        clean = site_name.lower().strip()
        if clean in COMMON_WEBSITES:
            url = COMMON_WEBSITES[clean]
            ok = self.open_url(url)
            return ok, f"Opened {site_name.capitalize()} in your browser."

        for name, url in COMMON_WEBSITES.items():
            if name in clean:
                ok = self.open_url(url)
                return ok, f"Opened {name.capitalize()} in your browser."

        if re.search(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/.*)?$", clean):
            ok = self.open_url(clean)
            return ok, f"Opened {clean} in your browser."

        encoded = urllib.parse.quote_plus(site_name)
        url = f"https://www.google.com/search?q={encoded}"
        ok = self.open_url(url)
        return ok, f"Searching Google for '{site_name}'."

    def _get_first_youtube_video(self, query: str) -> str | None:
        """Resolve top YouTube watch URL directly from search results."""
        try:
            import urllib.request
            encoded = urllib.parse.quote_plus(query)
            search_url = f"https://www.youtube.com/results?search_query={encoded}"
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                matches = re.findall(r"watch\?v=([a-zA-Z0-9_-]{11})", html)
                if matches:
                    return f"https://www.youtube.com/watch?v={matches[0]}"
        except Exception as e:
            logger.debug(f"Direct YouTube video resolution skipped ({e}), falling back to search URL.")
        return None

    def play_youtube(self, query: str) -> Tuple[bool, str]:
        """Search and play a video or music query directly on YouTube in Chrome."""
        raw_q = query.strip()
        clean_q = raw_q
        for _ in range(3):
            clean_q = re.sub(
                r"^(?:please|can you|could you|would you|hey friday|friday|i want to|let\'s|lets|just)\s+",
                "",
                clean_q,
                flags=re.IGNORECASE,
            ).strip()
            clean_q = re.sub(
                r"^(?:open\s+(?:chrome|browser|google\s+chrome)\s+and\s+)",
                "",
                clean_q,
                flags=re.IGNORECASE,
            ).strip()
            clean_q = re.sub(
                r"^(?:open\s+youtube\s+and\s+)",
                "",
                clean_q,
                flags=re.IGNORECASE,
            ).strip()
            clean_q = re.sub(
                r"^(?:on\s+youtube\s+(?:and\s+)?)",
                "",
                clean_q,
                flags=re.IGNORECASE,
            ).strip()
            clean_q = re.sub(
                r"^(?:play\s+(?:the\s+)?(?:song\s+|video\s+|music\s+|track\s+)?|play\s+)",
                "",
                clean_q,
                flags=re.IGNORECASE,
            ).strip()
            clean_q = re.sub(
                r"\s+(?:on|in)\s+youtube[\.\!\?]*$",
                "",
                clean_q,
                flags=re.IGNORECASE,
            ).strip()
        clean_q = clean_q.rstrip(".!? ")

        if not clean_q or clean_q.lower() in ["youtube", "yt", "video"]:
            ok = self.open_url("https://www.youtube.com")
            return ok, "Opened YouTube in Google Chrome."

        direct_url = self._get_first_youtube_video(clean_q)
        if direct_url:
            ok = self.open_url(direct_url)
            return ok, f"Playing '{clean_q}' on YouTube in Google Chrome."

        encoded = urllib.parse.quote_plus(clean_q)
        search_url = f"https://www.youtube.com/results?search_query={encoded}"
        ok = self.open_url(search_url)
        return ok, f"Searching and playing '{clean_q}' on YouTube."

    def search_google(self, query: str) -> Tuple[bool, str]:
        """Perform a Google search in browser."""
        clean = query.strip()
        for prefix in ["search google for", "search for", "google search", "google"]:
            if clean.lower().startswith(prefix):
                clean = clean[len(prefix):].strip()
        encoded = urllib.parse.quote_plus(clean)
        url = f"https://www.google.com/search?q={encoded}"
        self.open_url(url)
        return True, f"Searching Google for '{clean}'."

    def _get_active_browser_hwnd(self, keywords: list[str] | None = None) -> int | None:
        """Find the active or topmost browser window (Chrome/Edge/WhatsApp) matching keywords or browser window class."""
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)

            search_keywords = [k.lower() for k in (keywords or ["whatsapp", "chrome", "google chrome", "gmail"])]
            candidates: list[tuple[int, int, str]] = []

            def _enum_cb(hwnd, _):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                title = ""
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.strip()

                cname_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cname_buf, 256)
                cname = cname_buf.value.strip()

                title_lower = title.lower()

                # Priority 0: Exact WhatsApp Web tab or standalone app (filter out search pages)
                if any(kw in title_lower for kw in ["whatsapp", "wa"]):
                    if "google search" not in title_lower and ("google chrome" in title_lower or title_lower == "whatsapp"):
                        candidates.append((0, hwnd, title))
                        return True

                # Priority 1: Primary keyword in title (excluding google search pages)
                primary_kw = search_keywords[0] if search_keywords else ""
                if primary_kw and primary_kw in title_lower and "google search" not in title_lower:
                    candidates.append((1, hwnd, title))
                    return True

                # Priority 2: Any search keyword in title (excluding google search pages)
                for kw in search_keywords[1:]:
                    if kw in title_lower and "google search" not in title_lower:
                        candidates.append((2, hwnd, title))
                        return True

                # Priority 3: Chrome or Mozilla browser window class
                if cname in ("Chrome_WidgetWin_1", "MozillaWindowClass"):
                    if title:
                        candidates.append((3, hwnd, title))
                        return True

                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)

            if not candidates:
                return None

            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]
        except Exception as e:
            logger.debug(f"_get_active_browser_hwnd error: {e}")
            return None

    def _activate_browser_tab(self, hwnd: int, tab_keyword: str) -> bool:
        """Find and select a specific tab inside a browser window via UI Automation."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)

            from pywinauto import Desktop
            desktop = Desktop(backend="uia")
            w = desktop.window(handle=hwnd)
            tabs = w.descendants(control_type="TabItem")
            for t in tabs:
                txt = t.window_text().lower()
                if tab_keyword.lower() in txt and "google search" not in txt:
                    try:
                        t.click_input()
                        return True
                    except Exception:
                        try:
                            t.select()
                            return True
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"_activate_browser_tab error: {e}")
        return False

    def _check_and_dismiss_whatsapp_modal(self, hwnd: int, display_phone: str = "") -> bool:
        """Detect and dismiss WhatsApp Web 'The number isn't on WhatsApp' error dialog."""
        try:
            from pywinauto import Desktop
            desktop = Desktop(backend="uia")
            w = desktop.window(handle=hwnd)
            for el in w.descendants():
                t = el.window_text()
                if "isn't on whatsapp" in t.lower() or "is not on whatsapp" in t.lower():
                    logger.warning(f"WhatsApp Web error: {t}")
                    parent = el.parent()
                    if parent:
                        for btn in parent.descendants(control_type="Button"):
                            if btn.window_text() == "OK":
                                try:
                                    btn.click_input()
                                except Exception:
                                    pass
                                break
                    from friday.voice.native_tts import native_tts
                    msg = f"The number {display_phone} is not registered on WhatsApp."
                    logger.info(msg)
                    try:
                        native_tts.speak(msg)
                    except Exception:
                        pass
                    return True
        except Exception as e:
            logger.debug(f"_check_and_dismiss_whatsapp_modal error: {e}")
        return False

    def _search_and_open_whatsapp_chat(self, hwnd: int, name: str) -> bool:
        """Search and select a contact name in WhatsApp Web search box."""
        try:
            import time
            from pywinauto import Desktop
            from friday.vision.windows_input_driver import WindowsNativeInputDriver
            desktop = Desktop(backend="uia")
            w = desktop.window(handle=hwnd)
            driver = WindowsNativeInputDriver()

            edits = w.descendants(control_type="Edit")
            for e in edits:
                txt = e.window_text().lower()
                if "search or start" in txt or "search" in txt:
                    e.set_focus()
                    time.sleep(0.2)
                    driver.hotkey(["ctrl", "a"])
                    time.sleep(0.1)
                    driver.type_text(name)
                    time.sleep(0.8)
                    driver.press_key("enter")
                    time.sleep(0.5)
                    return True
        except Exception as e:
            logger.debug(f"_search_and_open_whatsapp_chat error: {e}")
        return False

    def open_gmail(self, to: str = "", subject: str = "", body: str = "") -> Tuple[bool, str]:
        """Send email via SMTP if configured, or open Gmail compose in Google Chrome and auto-send."""
        to_clean = to.strip()
        subj_clean = subject.strip()
        body_clean = body.strip()

        # 1. Try sending directly via SMTP if credentials are configured
        if to_clean and (subj_clean or body_clean):
            try:
                from friday.tools.builtin.email_tools import _send_smtp_email
                from friday.core.config import get_settings
                settings = get_settings()
                sender = getattr(settings, "email_address", None) or os.getenv("FRIDAY_EMAIL_ADDRESS")
                password = getattr(settings, "email_app_password", None) or os.getenv("FRIDAY_EMAIL_APP_PASSWORD")
                if sender and password:
                    sent_ok, sent_msg = _send_smtp_email(
                        to_address=to_clean,
                        subject=subj_clean or "Message from FRIDAY",
                        body=body_clean,
                    )
                    if sent_ok:
                        return True, f"Email sent successfully to {to_clean}."
                    logger.debug(f"Direct SMTP send failed ({sent_msg}), falling back to Gmail Web.")
            except Exception as e:
                logger.debug(f"SMTP check failed: {e}")

        # 2. Web fallback: open Gmail compose window in browser
        params = {"view": "cm", "fs": "1"}
        if to_clean:
            params["to"] = to_clean
        if subj_clean:
            params["su"] = subj_clean
        if body_clean:
            params["body"] = body_clean
        query_str = urllib.parse.urlencode(params)
        url = f"https://mail.google.com/mail/?{query_str}"
        ok = self.open_url(url)

        # If recipient and content are provided, auto-send via Ctrl+Enter after compose loads
        if to_clean and (body_clean or subj_clean):
            def _auto_send_gmail():
                try:
                    import time
                    import ctypes
                    user32 = ctypes.windll.user32
                    h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
                    if h_desk:
                        user32.SetThreadDesktop(h_desk)

                    from friday.devices.app_launcher import force_window_foreground
                    from friday.vision.windows_input_driver import WindowsNativeInputDriver

                    driver = WindowsNativeInputDriver()
                    for wait_time in [4.5, 2.5]:
                        time.sleep(wait_time)
                        hwnd = self._get_active_browser_hwnd(["gmail", "mail", "chrome"])
                        if hwnd:
                            force_window_foreground(hwnd)
                            time.sleep(0.3)
                            # Ctrl+Enter sends email in Gmail compose
                            driver.hotkey(["ctrl", "enter"])
                except Exception as e:
                    logger.debug(f"Gmail auto-send error: {e}")

            import threading
            threading.Thread(target=_auto_send_gmail, daemon=True).start()
            return ok, f"Sending email to {to_clean} with subject '{subj_clean or '(no subject)'}' via Gmail."

        target = f" to {to_clean}" if to_clean else ""
        return ok, f"Opened Gmail compose window{target} in Google Chrome."

    # -------------------------------------------------------------------------
    # Contact Management & Resolution
    # -------------------------------------------------------------------------
    @staticmethod
    def _contacts_file_path() -> str:
        base = os.path.expanduser("~/.friday")
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "contacts.json")

    def save_contact(self, name: str, phone: str) -> Tuple[bool, str]:
        """Persist a contact name and phone number locally and into Memora."""
        clean_name = name.strip().title()
        if not clean_name:
            return False, "Contact name cannot be empty."

        clean_digits = re.sub(r"[^\d+]", "", phone.strip())
        pure_digits = re.sub(r"[^\d]", "", clean_digits)
        if len(pure_digits) < 10:
            return False, f"Invalid phone number '{phone}' (must contain at least 10 digits)."

        # Normalize 10-digit Indian numbers to include country code +91
        if len(pure_digits) == 10 and pure_digits[0] in "6789":
            formatted_phone = f"+91{pure_digits}"
        elif clean_digits.startswith("+"):
            formatted_phone = clean_digits
        else:
            formatted_phone = f"+{pure_digits}"

        filepath = self._contacts_file_path()
        data: dict[str, Any] = {}
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[clean_name.lower()] = {
                "name": clean_name,
                "phone": formatted_phone,
                "updated_at": time.time(),
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write to contacts.json: {e}")

        # Also store into Memora local records
        try:
            from friday.memory.memora_client import memora_client
            memora_client.record_interaction_async(
                user_input=f"Save contact: {clean_name} is {formatted_phone}",
                agent_output=f"Saved contact {clean_name} with phone number {formatted_phone}.",
                agent_name="friday",
                event_type="fact",
                tags=["contact", "address_book"],
            )
        except Exception as me:
            logger.debug(f"Memora contact sync skipped: {me}")

        return True, f"Saved contact '{clean_name}' with phone number {formatted_phone}."

    def get_all_contacts(self) -> dict[str, dict[str, Any]]:
        """Retrieve dictionary of all stored contacts."""
        filepath = self._contacts_file_path()
        if not os.path.exists(filepath):
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"Could not read contacts.json: {e}")
            return {}

    def delete_contact(self, name: str) -> Tuple[bool, str]:
        """Delete a contact from local storage."""
        clean_name = name.strip().lower()
        filepath = self._contacts_file_path()
        if not os.path.exists(filepath):
            return False, f"Contact '{name}' not found."
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if clean_name in data:
                del data[clean_name]
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                return True, f"Removed contact '{name}'."
            return False, f"Contact '{name}' not found."
        except Exception as e:
            return False, f"Failed to delete contact: {e}"

    def _lookup_contact_phone(self, name: str) -> str | None:
        """Attempt to resolve a contact name to a phone number from local contacts or Memora."""
        if not name:
            return None
        clean_name = name.lower().strip()

        # 1. Local contacts.json lookup (exact or fuzzy)
        contacts = self.get_all_contacts()
        if clean_name in contacts:
            return contacts[clean_name].get("phone")
        for k, v in contacts.items():
            if clean_name in k or k in clean_name:
                return v.get("phone")

        # 2. Memora memory database lookup
        try:
            from friday.memory.memora_client import memora_client
            if hasattr(memora_client, "local_db_path") and os.path.exists(memora_client.local_db_path):
                import sqlite3
                with sqlite3.connect(memora_client.local_db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT content_text FROM memory_records WHERE content_text LIKE ?",
                        (f"%{clean_name}%",)
                    )
                    for (text,) in cursor.fetchall():
                        m = re.search(r"(?:phone|number|mobile|whatsapp|wa)?\s*(?:is|:)?\s*([+\d\s-]{10,16})", text, re.IGNORECASE)
                        if m:
                            clean_digits = re.sub(r"[^\d+]", "", m.group(1))
                            if len(re.sub(r"[^\d]", "", clean_digits)) >= 10:
                                return clean_digits
        except Exception:
            pass
        return None

    def open_whatsapp(self, phone: str = "", message: str = "", recipient: str = "") -> Tuple[bool, str]:
        """Open WhatsApp Web or desktop with optional recipient and pre-filled message, then dispatch."""
        clean_phone = re.sub(r"[^\d+]", "", phone) if phone else ""
        if not clean_phone and recipient:
            resolved_phone = self._lookup_contact_phone(recipient)
            if resolved_phone:
                clean_phone = resolved_phone

        # Normalize phone number:
        # WhatsApp Web 'phone=' parameter expects digits without leading '+'
        phone_param = ""
        display_phone = clean_phone
        if clean_phone:
            pure_digits = re.sub(r"[^\d]", "", clean_phone)
            # Prepend 91 for 10-digit Indian numbers without country code
            if len(pure_digits) == 10 and pure_digits[0] in "6789":
                phone_param = "91" + pure_digits
                display_phone = f"+91{pure_digits}"
            else:
                phone_param = pure_digits
                display_phone = f"+{pure_digits}" if not clean_phone.startswith("+") else clean_phone

        params = {}
        if phone_param:
            params["phone"] = phone_param
        if message:
            params["text"] = message.strip()

        if params:
            query_str = urllib.parse.urlencode(params)
            url = f"https://web.whatsapp.com/send/?{query_str}"
        else:
            url = "https://web.whatsapp.com"

        ok = self.open_url(url)

        # Background automation to bring window into foreground and send the message
        if message or phone_param or recipient:
            def _auto_dispatch():
                try:
                    import time
                    import ctypes
                    user32 = ctypes.windll.user32
                    h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
                    if h_desk:
                        user32.SetThreadDesktop(h_desk)

                    from friday.devices.app_launcher import force_window_foreground
                    from friday.vision.windows_input_driver import WindowsNativeInputDriver

                    driver = WindowsNativeInputDriver()

                    if phone_param:
                        # Direct phone URL opens chat directly into conversation with pre-filled text.
                        # Progressive dispatch: WhatsApp Web loading takes between 3.5s and 7s.
                        # Multiple Enter attempts ensure message is sent as soon as DOM loads,
                        # and on WhatsApp Web an Enter on an empty input box is a safe no-op.
                        for wait_time in [3.5, 2.0, 2.0]:
                            time.sleep(wait_time)
                            hwnd = self._get_active_browser_hwnd(["whatsapp", "chrome"])
                            if hwnd:
                                force_window_foreground(hwnd)
                                self._activate_browser_tab(hwnd, "whatsapp")
                                time.sleep(0.3)

                                # Check if WhatsApp Web displayed "The number ... isn't on WhatsApp" modal dialog
                                modal_dismissed = self._check_and_dismiss_whatsapp_modal(hwnd, display_phone)
                                if modal_dismissed:
                                    return

                                driver.press_key("enter")
                    elif recipient:
                        # Modal / chat list contact search: search contact directly in WhatsApp Web chat list
                        time.sleep(3.0)
                        hwnd = self._get_active_browser_hwnd(["whatsapp", "chrome"])
                        if hwnd:
                            force_window_foreground(hwnd)
                            self._activate_browser_tab(hwnd, "whatsapp")
                            time.sleep(0.4)

                            search_ok = self._search_and_open_whatsapp_chat(hwnd, recipient)
                            if search_ok and message:
                                time.sleep(0.5)
                                driver.type_text(message)
                                time.sleep(0.3)
                                driver.press_key("enter")
                except Exception as e:
                    logger.debug(f"WhatsApp auto-dispatch error: {e}")

            import threading
            threading.Thread(target=_auto_dispatch, daemon=True).start()

        if phone_param:
            target_str = f" to {recipient} ({display_phone})" if recipient and recipient != clean_phone else f" to {display_phone}"
            msg_str = f" with message '{message}'" if message else ""
            return ok, f"Sending message{msg_str}{target_str} on WhatsApp."
        else:
            target_str = f" for '{recipient}'" if recipient else ""
            msg_str = f" with message '{message}'" if message else ""
            hint = f" (Tip: Say 'save contact {recipient} <number>' to message them directly next time!)" if recipient else ""
            return ok, f"Opened WhatsApp Web{target_str}{msg_str} and dispatched.{hint}"

    # -------------------------------------------------------------------------
    # 2. Audio, Volume & Media Playback Control
    # -------------------------------------------------------------------------
    def volume_up(self, steps: int = 5) -> str:
        """Increase system master volume."""
        for _ in range(steps):
            self._send_key_event(VK_VOLUME_UP)
        return "Volume increased."

    def volume_down(self, steps: int = 5) -> str:
        """Decrease system master volume."""
        for _ in range(steps):
            self._send_key_event(VK_VOLUME_DOWN)
        return "Volume decreased."

    def volume_mute(self) -> str:
        """Toggle system volume mute/unmute."""
        self._send_key_event(VK_VOLUME_MUTE)
        return "Toggled system mute."

    def set_volume_percent(self, percent: int) -> Tuple[bool, str]:
        """Set exact master volume percentage (0 to 100)."""
        target = max(0, min(100, percent))
        try:
            from pycaw.pycaw import AudioUtilities
            dev = AudioUtilities.GetSpeakers()
            if dev and hasattr(dev, "EndpointVolume"):
                vol = dev.EndpointVolume
                vol.SetMasterVolumeLevelScalar(target / 100.0, None)
                if target > 0 and vol.GetMute():
                    vol.SetMute(0, None)
                return True, f"Volume set to {target}%."
        except Exception as e:
            logger.debug(f"pycaw volume set failed: {e}")

        # Fallback via key events: mute then step up
        self._send_key_event(VK_VOLUME_MUTE)
        steps = int(target / 2)
        for _ in range(steps):
            self._send_key_event(VK_VOLUME_UP)
        return True, f"Volume set to approximately {target}%."

    def get_volume_percent(self) -> int | None:
        """Get current master volume percentage."""
        try:
            from pycaw.pycaw import AudioUtilities
            dev = AudioUtilities.GetSpeakers()
            if dev and hasattr(dev, "EndpointVolume"):
                return round(dev.EndpointVolume.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            pass
        return None

    def media_play_pause(self) -> str:
        """Toggle media play / pause on laptop."""
        self._send_key_event(VK_MEDIA_PLAY_PAUSE)
        return "Toggled media playback."

    def media_next(self) -> str:
        """Skip to next media track."""
        self._send_key_event(VK_MEDIA_NEXT_TRACK)
        return "Skipped to next track."

    def media_prev(self) -> str:
        """Go to previous media track."""
        self._send_key_event(VK_MEDIA_PREV_TRACK)
        return "Returned to previous track."

    def media_stop(self) -> str:
        """Stop media playback."""
        self._send_key_event(VK_MEDIA_STOP)
        return "Media playback stopped."

    # -------------------------------------------------------------------------
    # 3. Window & Desktop Management
    # -------------------------------------------------------------------------
    def show_desktop(self) -> str:
        """Minimize/restore all windows to show desktop (Win + D)."""
        self.user32.keybd_event(VK_LWIN, 0, 0, 0)
        self.user32.keybd_event(ord('D'), 0, 0, 0)
        self.user32.keybd_event(ord('D'), 0, KEYEVENTF_KEYUP, 0)
        self.user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
        return "Desktop toggled."

    def lock_workstation(self) -> str:
        """Lock the Windows laptop workstation."""
        try:
            self.user32.LockWorkStation()
            return "Workstation locked."
        except Exception as e:
            return f"Failed to lock workstation: {e}"

    def close_active_window(self) -> str:
        """Close the currently active foreground window (Alt + F4)."""
        VK_MENU = 0x12  # Alt
        VK_F4 = 0x73    # F4
        self.user32.keybd_event(VK_MENU, 0, 0, 0)
        self.user32.keybd_event(VK_F4, 0, 0, 0)
        self.user32.keybd_event(VK_F4, 0, KEYEVENTF_KEYUP, 0)
        self.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        return "Closed active window."

    def minimize_active_window(self) -> str:
        """Minimize the active foreground window (Win + Down)."""
        VK_DOWN = 0x28
        self.user32.keybd_event(VK_LWIN, 0, 0, 0)
        self.user32.keybd_event(VK_DOWN, 0, 0, 0)
        self.user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
        self.user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
        return "Minimized active window."

    def maximize_active_window(self) -> str:
        """Maximize the active foreground window (Win + Up)."""
        VK_UP = 0x26
        self.user32.keybd_event(VK_LWIN, 0, 0, 0)
        self.user32.keybd_event(VK_UP, 0, 0, 0)
        self.user32.keybd_event(VK_UP, 0, KEYEVENTF_KEYUP, 0)
        self.user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
        return "Maximized active window."

    def take_screenshot(self) -> Tuple[bool, str, str | None]:
        """Capture desktop screenshot, save to Pictures/Screenshots and return base64."""
        try:
            import io
            import base64
            from PIL import ImageGrab
            from datetime import datetime
            img = ImageGrab.grab()
            save_dir = os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")
            os.makedirs(save_dir, exist_ok=True)
            filename = f"FRIDAY_Screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            path = os.path.join(save_dir, filename)
            img.save(path)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            b64_str = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"
            return True, f"Screenshot captured and saved to {path}.", b64_str
        except Exception as e:
            subprocess.Popen("start ms-screenclip:", shell=True)
            return True, "Snipping Tool activated.", None

    # -------------------------------------------------------------------------
    # 4. Applications & Process Control
    # -------------------------------------------------------------------------
    def launch_app(self, app_name: str) -> Tuple[bool, str]:
        """Launch or bring to front any Windows application."""
        clean = app_name.lower().strip()
        if any(k in clean for k in ["chrome", "google chrome"]):
            chrome = get_chrome_path()
            if chrome:
                subprocess.Popen([chrome])
                return True, "Opened Google Chrome."
        if any(k in clean for k in ["youtube", "yt"]):
            return self.open_website("youtube")
        if any(k in clean for k in ["camera"]):
            subprocess.Popen("start microsoft.windows.camera:", shell=True)
            return True, "Opened Camera."
        if any(k in clean for k in ["snipping tool", "snip", "screenshot tool"]):
            subprocess.Popen("start ms-screenclip:", shell=True)
            return True, "Opened Snipping Tool."
        if any(k in clean for k in ["control panel"]):
            subprocess.Popen("control", shell=True)
            return True, "Opened Control Panel."
        if any(k in clean for k in ["task manager", "taskmgr"]):
            subprocess.Popen("taskmgr", shell=True)
            return True, "Opened Task Manager."
        if any(k in clean for k in ["terminal", "wt"]):
            subprocess.Popen("wt", shell=True)
            return True, "Opened Windows Terminal."
        if any(k in clean for k in ["cmd", "command prompt"]):
            subprocess.Popen("start cmd.exe", shell=True)
            return True, "Opened Command Prompt."
        if any(k in clean for k in ["powershell"]):
            subprocess.Popen("start powershell.exe", shell=True)
            return True, "Opened PowerShell."

        return launch_desktop_app(app_name)

    def close_app(self, app_name: str) -> Tuple[bool, str]:
        """Gracefully close or terminate an application by name or process."""
        clean = app_name.lower().strip()
        exe = APP_PROCESS_MAP.get(clean)

        # Fuzzy match in map
        if not exe:
            for k, v in APP_PROCESS_MAP.items():
                if k in clean:
                    exe = v
                    break

        if exe:
            try:
                cmd = ["taskkill.exe", "/IM", exe, "/T", "/F"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if res.returncode == 0 or "not found" in res.stderr.lower():
                    return True, f"Closed {clean.title()}."
            except Exception as e:
                logger.warning(f"taskkill failed for {exe}: {e}")

        # Process iteration search
        terminated_count = 0
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if clean in pname or (exe and exe.lower() in pname):
                    proc.terminate()
                    terminated_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if terminated_count > 0:
            return True, f"Closed {clean.title()} ({terminated_count} process instances terminated)."

        return False, f"Could not find running process for '{app_name}'."

    def list_running_apps(self) -> list[str]:
        """Enumerate visible desktop application windows."""
        titles: list[str] = []
        user32 = self.user32

        def enum_cb(hwnd: int, lparam: int) -> bool:
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    t = buff.value.strip()
                    excluded = ("Program Manager", "Settings", "Windows Input Experience", "Task Switching")
                    if t and t not in excluded and not t.startswith("Popup"):
                        titles.append(t)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return list(dict.fromkeys(titles))

    # -------------------------------------------------------------------------
    # 5. Keyboard & Typing Automation
    # -------------------------------------------------------------------------
    def type_text(self, text: str) -> Tuple[bool, str]:
        """Type text into the currently focused window."""
        try:
            from friday.vision.windows_input_driver import WindowsNativeInputDriver
            ok = WindowsNativeInputDriver().type_text(text)
            return ok, f"Typed: {text}" if ok else "Failed to type text."
        except Exception as e:
            return False, f"Typing error: {e}"

    def press_key(self, key_name: str) -> Tuple[bool, str]:
        """Press and release a keyboard key (enter, space, tab, escape, etc.)."""
        try:
            from friday.vision.windows_input_driver import WindowsNativeInputDriver
            ok = WindowsNativeInputDriver().press_key(key_name.lower().strip())
            return ok, f"Pressed {key_name}." if ok else f"Unknown key: {key_name}"
        except Exception as e:
            return False, f"Key press error: {e}"

    def send_hotkey(self, keys: list[str]) -> Tuple[bool, str]:
        """Execute a key combination (e.g. ['ctrl', 'c'], ['alt', 'tab'])."""
        try:
            from friday.vision.windows_input_driver import WindowsNativeInputDriver
            ok = WindowsNativeInputDriver().hotkey(keys)
            combo = "+".join(keys)
            return ok, f"Executed shortcut: {combo}"
        except Exception as e:
            return False, f"Hotkey error: {e}"

    # -------------------------------------------------------------------------
    # 6. Display Brightness Control
    # -------------------------------------------------------------------------
    def get_brightness(self) -> int | None:
        """Get current laptop display brightness level (0 to 100)."""
        try:
            cmd = "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -ExpandProperty CurrentBrightness"
            res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                return int(res.stdout.strip().split()[0])
        except Exception as e:
            logger.debug(f"Could not read brightness: {e}")
        return None

    def set_brightness(self, percent: int) -> Tuple[bool, str]:
        """Set laptop display brightness level (0 to 100)."""
        target = max(0, min(100, percent))
        try:
            cmd = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {target})"
            res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=8)
            if res.returncode == 0:
                return True, f"Brightness set to {target}%."
        except Exception as e:
            logger.debug(f"Could not set brightness: {e}")
        return False, "Display brightness control is not supported on this monitor."

    # -------------------------------------------------------------------------
    # 7. System Hardware Telemetry & Network
    # -------------------------------------------------------------------------
    def get_battery_info(self) -> str:
        """Get laptop battery percentage and power plugged-in status."""
        try:
            battery = psutil.sensors_battery()
            if not battery:
                return "Battery sensor not detected (desktop or AC power)."
            percent = round(battery.percent)
            plugged = battery.power_plugged
            status = "Plugged in (Charging)" if plugged else "Discharging (On Battery)"
            secs = battery.secsleft
            time_str = ""
            if secs and secs > 0 and not plugged:
                hrs = secs // 3600
                mins = (secs % 3600) // 60
                time_str = f", approximately {hrs}h {mins}m remaining"
            return f"Battery is at {percent}% — {status}{time_str}."
        except Exception as e:
            return f"Could not read battery: {e}"

    def get_system_specs(self) -> str:
        """Report CPU, RAM, Disk, OS, and hostname summary."""
        cpu_usage = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        total_ram = round(vm.total / (1024**3), 1)
        used_ram = round(vm.used / (1024**3), 1)
        cores = psutil.cpu_count(logical=True)
        try:
            disk = psutil.disk_usage("C:\\")
            disk_free_gb = round(disk.free / (1024**3), 1)
            disk_total_gb = round(disk.total / (1024**3), 1)
            disk_info = f" C: drive has {disk_free_gb} GB free of {disk_total_gb} GB."
        except Exception:
            disk_info = ""
        return (
            f"Laptop Status: CPU load is {cpu_usage}% across {cores} logical cores. "
            f"Memory usage is {vm.percent}% ({used_ram} GB of {total_ram} GB used).{disk_info} "
            f"All cognitive and device subsystems are active."
        )

    def get_network_status(self) -> str:
        """Report network connection, local IP address, and gateway connectivity."""
        try:
            host_name = socket.gethostname()
            local_ip = socket.gethostbyname(host_name)
            # Ping Google DNS to test internet
            ping_res = subprocess.run(
                ["ping", "-n", "1", "-w", "1500", "8.8.8.8"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            online = ping_res.returncode == 0
            net_state = "Connected to the Internet" if online else "Offline / No Internet Connection"
            return f"Network: {net_state}. Local IP address is {local_ip} on host '{host_name}'."
        except Exception as e:
            return f"Network query error: {e}"

    def sleep_laptop(self) -> str:
        """Put the Windows laptop to sleep."""
        try:
            subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
            return "Putting laptop to sleep."
        except Exception as e:
            return f"Failed to put laptop to sleep: {e}"

    def open_folder(self, folder_name: str) -> Tuple[bool, str]:
        """Open standard user folders or direct directory paths."""
        low = folder_name.lower().strip()
        home = os.path.expanduser("~")
        folder_map = {
            "downloads": os.path.join(home, "Downloads"),
            "download": os.path.join(home, "Downloads"),
            "desktop": os.path.join(home, "Desktop"),
            "documents": os.path.join(home, "Documents"),
            "document": os.path.join(home, "Documents"),
            "pictures": os.path.join(home, "Pictures"),
            "photos": os.path.join(home, "Pictures"),
            "videos": os.path.join(home, "Videos"),
            "music": os.path.join(home, "Music"),
            "c drive": "C:\\",
            "c:": "C:\\",
            "home": home,
            "friday": r"d:\FRIDAY Universe\FRIDAY",
            "universe": r"d:\FRIDAY Universe",
        }

        for k, p in folder_map.items():
            if k in low:
                if os.path.exists(p):
                    os.startfile(p)
                    return True, f"Opened {k.title()} folder: {p}"

        if os.path.exists(folder_name):
            os.startfile(folder_name)
            return True, f"Opened directory: {folder_name}"

        return False, f"Directory '{folder_name}' not found."

    def run_powershell(self, command: str) -> Tuple[bool, str]:
        """Execute an arbitrary PowerShell command and return output."""
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=15,
            )
            out = res.stdout.strip() or res.stderr.strip()
            return res.returncode == 0, out or "Command executed successfully."
        except subprocess.TimeoutExpired:
            return False, "Command timed out after 15 seconds."
        except Exception as e:
            return False, f"Execution failed: {e}"

    def is_contact_directive(self, command: str) -> bool:
        """Check if command matches contact management directives (save, list, delete)."""
        if not command or not command.strip():
            return False
        cmd = command.strip().lower().rstrip(".!? ")
        if cmd in ["contacts", "list contacts", "show contacts", "my contacts", "view contacts", "all contacts"]:
            return True
        if re.search(r"^(?:save|add|remember|set)\s+(?:contact\s+)?[a-zA-Z\s]+?(?:'s)?\s*(?:number|phone|mobile|whatsapp)?\s*(?:is|as|=|:)?\s*[+\d\s-]{10,16}$", cmd):
            return True
        if re.search(r"^[a-zA-Z\s]+?(?:'s)?\s+(?:phone|number|mobile|whatsapp)\s+(?:is|=|:)?\s*[+\d\s-]{10,16}$", cmd):
            return True
        if re.search(r"^[a-zA-Z]+\s+is\s+[+\d\s-]{10,16}$", cmd):
            return True
        if re.search(r"^(?:delete|remove)\s+contact\s+[a-zA-Z\s]+$", cmd):
            return True
        return False

    def is_gmail_directive(self, command: str) -> bool:
        """Check if command is an actionable Gmail/email directive."""
        if not command or not command.strip():
            return False
        cmd = command.strip().lower().rstrip(".!? ")
        if cmd in [
            "open gmail", "launch gmail", "start gmail", "gmail",
            "compose email", "compose gmail", "new email", "write email",
            "send gmail", "send email"
        ]:
            return True
        if re.search(r"^(?:open|compose|write|send)\s+(?:an?\s+)?(?:gmail|email)\b", cmd):
            return True
        if re.search(r"\bto\s+[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", cmd):
            return True
        if re.search(r"^(?:send|email)\s+.+?\s+to\s+[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", cmd):
            return True
        return False

    def is_whatsapp_directive(self, command: str) -> bool:
        """Check if command is an actionable WhatsApp/messaging directive."""
        if not command or not command.strip():
            return False
        cmd = command.strip().lower().rstrip(".!? ")
        # Explicit WhatsApp keywords
        if cmd in ["whatsapp", "open whatsapp", "launch whatsapp", "start whatsapp", "open whatsapp web", "whatsapp web", "wa"]:
            return True
        if re.search(r"^(?:open|launch|start|send|text|message)\s+(?:an?\s+)?(?:whats?a?app\b|.*\bwhats?a?app\b)", cmd):
            return True
        if re.search(r"^whats?a?app\s+[^\s]+\s+.+$", cmd):
            return True
        if re.search(r"\b(?:in|on|via|through)\s+whats?a?app$", cmd):
            return True

        # Send/text/message to phone number (e.g. "send hi to 9014603029", "text 9014603029 hello")
        if re.search(r"^(?:send|text|message)\s+.+?\s+to\s+[+\d\s-]{10,16}$", cmd):
            return True
        if re.search(r"^(?:text|message)\s+[+\d\s-]{10,16}\b", cmd):
            return True
        if re.search(r"^(?:send\s+(?:a\s+)?message\s+to\s+[+\d\s-]{10,16})", cmd):
            return True

        # Check if command is "send <msg> to <contact>" where contact is a saved contact in address book
        m_contact = re.search(r"^(?:send|text|message)\s+(?:a\s+message\s+to|.+?\s+to)\s+(?P<name>[a-zA-Z\s]+?)(?:\s+(?:in|on|via)\s+whats?a?app)?$", cmd)
        if m_contact:
            name = m_contact.group("name").strip()
            if name and name not in ("me", "him", "her", "them", "someone") and self._lookup_contact_phone(name):
                return True

        return False

    def handle_contact_directive(self, command: str) -> Tuple[bool, str, dict[str, Any]]:
        """Process contact listing, saving, or deleting."""
        cmd = command.strip().lower().rstrip(".!? ")
        raw = command.strip()

        # 1. List contacts
        if cmd in ["contacts", "list contacts", "show contacts", "my contacts", "view contacts", "all contacts"]:
            all_c = self.get_all_contacts()
            if not all_c:
                return True, "No saved contacts found. You can say 'save contact <name> <phone>' to store someone.", {"action": "list_contacts", "count": 0}
            lines = ["Saved Contacts:"]
            for k, v in sorted(all_c.items()):
                lines.append(f"  - {v.get('name', k.title())}: {v.get('phone', 'N/A')}")
            return True, "\n".join(lines), {"action": "list_contacts", "count": len(all_c)}

        # 2. Delete contact
        m_del = re.search(r"^(?:delete|remove)\s+contact\s+(?P<name>[a-zA-Z\s]+)$", cmd)
        if m_del:
            target_name = m_del.group("name").strip()
            ok, msg = self.delete_contact(target_name)
            return True, msg, {"action": "delete_contact", "name": target_name, "success": ok}

        # 3. Save contact
        name = ""
        phone = ""

        mA = re.search(
            r"^(?:save|add|remember|set)\s+(?:contact\s+)?(?P<name>[a-zA-Z\s]+?)(?:'s)?\s*(?:number|phone|mobile|whatsapp)?\s*(?:is|as|=|:)?\s*(?P<phone>[+\d\s-]{10,16})$",
            raw,
            re.IGNORECASE,
        )
        mB = re.search(
            r"^(?P<name>[a-zA-Z\s]+?)(?:'s)?\s+(?:phone|number|mobile|whatsapp)\s+(?:is|=|:)?\s*(?P<phone>[+\d\s-]{10,16})$",
            raw,
            re.IGNORECASE,
        )
        mC = re.search(
            r"^(?P<name>[a-zA-Z]+)\s+is\s+(?P<phone>[+\d\s-]{10,16})$",
            raw,
            re.IGNORECASE,
        )

        if mA:
            name = mA.group("name").strip()
            phone = mA.group("phone").strip()
        elif mB:
            name = mB.group("name").strip()
            phone = mB.group("phone").strip()
        elif mC:
            name = mC.group("name").strip()
            phone = mC.group("phone").strip()

        if name and phone:
            for prefix in ["save", "add", "remember", "set", "contact"]:
                if name.lower().startswith(prefix + " "):
                    name = name[len(prefix) + 1:].strip()
            name = name.strip().title()
            ok, msg = self.save_contact(name, phone)
            reply = f"{msg} You can now say 'send hi to {name.lower()} in whatsapp' to message them directly!"
            return True, reply, {"action": "save_contact", "name": name, "phone": phone, "success": ok}

        return False, "Could not parse contact details.", {"action": "contact_error"}

    def can_handle(self, command: str) -> bool:
        """Check if command matches any FRIDAY OS directive without executing side effects."""
        if not command or not command.strip():
            return False
        cmd = command.strip().lower().rstrip(".!? ")
        if self.is_contact_directive(cmd):
            return True
        if "play " in cmd or cmd.startswith("play") or ("youtube" in cmd and any(k in cmd for k in ["play", "song", "music", "video", "track"])):
            return True
        if any(cmd == k or cmd == f"open {k}" or cmd == f"launch {k}" for k in ["youtube", "yt"]):
            return True
        if cmd in ["open chrome", "launch chrome", "start chrome", "chrome", "google chrome", "open google chrome"]:
            return True
        if cmd.startswith("search google for ") or cmd.startswith("search for ") or cmd.startswith("google "):
            return True
        for site in COMMON_WEBSITES:
            if cmd == f"open {site}" or cmd == f"launch {site}" or cmd == site:
                return True
        if any(k in cmd for k in [
            "volume up", "volume down", "increase volume", "decrease volume",
            "turn up volume", "turn down volume", "raise volume", "lower volume",
            "raise the volume", "lower the volume", "boost volume", "crank up volume",
            "pump up volume", "brightness up", "brightness down", "increase brightness",
            "decrease brightness", "turn up brightness", "turn down brightness"
        ]):
            return True
        if re.search(r"^(?:please\s+)?(?:unmute|mute)\s*(?:the\s+)?(?:volume|audio|system|pc|laptop)?$", cmd):
            return True
        if re.search(r"(?:set|change|turn|put|increase|decrease|raise|lower|boost|bring|adjust|make)\s+(?:the\s+)?(?:volume|brightness)\s+(?:to\s+|at\s+)?(\d{1,3})\s*%?", cmd):
            return True
        if self.is_gmail_directive(cmd):
            return True
        if self.is_whatsapp_directive(cmd):
            return True
        if any(k in cmd for k in ["pause", "resume", "next song", "previous song", "stop music"]):
            return True
        if any(k in cmd for k in ["show desktop", "minimize windows", "close window", "lock pc", "lock laptop", "sleep laptop"]):
            return True
        if cmd.startswith("close ") or cmd.startswith("kill ") or cmd.startswith("exit "):
            return True
        if cmd in ["battery", "battery status", "battery level", "power status"]:
            return True
        if re.search(r"^(?:what is|how is|check|tell me|get|show)\s+(?:the\s+)?(?:battery|power)\b", cmd):
            return True
        if any(k in cmd for k in ["what apps are open", "list open apps", "running apps", "screenshot", "system specs", "laptop specs", "system status", "hardware status", "wifi status", "network status", "what time is it", "today's date"]):
            return True
        if cmd.startswith("type ") or cmd.startswith("write ") or cmd.startswith("press "):
            return True
        if cmd.startswith("open ") or cmd.startswith("launch ") or cmd.startswith("start ") or cmd.startswith("powershell ") or cmd.startswith("run command ") or cmd.startswith("execute command "):
            return True
        return False

    # -------------------------------------------------------------------------
    # 8. Natural Language FRIDAY Directive Dispatcher
    # -------------------------------------------------------------------------
    def handle_directive(self, command: str) -> Tuple[bool, str, dict[str, Any]]:
        """Evaluate natural language command and execute appropriate Windows action."""
        raw = command.strip()
        cmd = raw.lower()

        # Clean trailing punctuation
        cmd_clean = cmd.rstrip(".!? ")

        # A. YouTube Video / Music Playback
        if (
            "play " in cmd
            or cmd.startswith("play")
            or "play the song" in cmd
            or "play song" in cmd
            or ("youtube" in cmd and any(k in cmd for k in ["play", "song", "music", "video", "track"]))
        ):
            ok, reply = self.play_youtube(raw)
            return True, reply, {"action": "play_youtube", "success": ok}

        # B. YouTube Direct Website
        if any(cmd_clean == k or cmd_clean == f"open {k}" or cmd_clean == f"launch {k}" or cmd_clean == f"go to {k}" for k in ["youtube", "yt"]):
            ok = self.open_url("https://www.youtube.com")
            return True, "Opened YouTube in Google Chrome.", {"action": "open_youtube", "success": ok}

        if "youtube" in cmd and any(k in cmd for k in ["open", "launch", "go to", "show me", "start"]):
            ok = self.open_url("https://www.youtube.com")
            return True, "Opened YouTube in Google Chrome.", {"action": "open_youtube", "success": ok}

        # C. Direct Chrome launch
        if cmd_clean in ["open chrome", "launch chrome", "start chrome", "chrome", "google chrome", "open google chrome"]:
            ok, reply = self.launch_app("chrome")
            return True, reply, {"action": "launch_app", "app": "chrome", "success": ok}

        # D. Search Web / Google
        if cmd.startswith("search google for ") or cmd.startswith("search for ") or cmd.startswith("google "):
            ok, reply = self.search_google(raw)
            return True, reply, {"action": "search_google", "success": ok}

        # E.1 Gmail / Email Compose & Send
        if self.is_gmail_directive(raw):
            to_addr = ""
            subject = ""
            body = ""
            m_to = re.search(r"\b([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", raw)
            if m_to:
                to_addr = m_to.group(1)

            m_subj = re.search(r"\b(?:about|with\s+subject|subject)\s+['\"]?([^'\"\n]+?)['\"]?(?:\s+(?:and\s+)?(?:with\s+body|saying|body|message)\b|$)", raw, re.IGNORECASE)
            if m_subj:
                subject = m_subj.group(1).strip()

            m_body = re.search(r"\b(?:saying|with\s+body|body|message)\s+['\"]?([^'\"\n]+)['\"]?$", raw, re.IGNORECASE)
            if m_body:
                body = m_body.group(1).strip()

            if not body:
                m_send = re.search(r"^(?:send|email)\s+(?P<msg>.+?)\s+to\s+[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", raw, re.IGNORECASE)
                if m_send:
                    cand = m_send.group("msg").strip()
                    if not any(k in cand.lower() for k in ["email", "gmail"]):
                        body = cand

            ok, reply = self.open_gmail(to=to_addr, subject=subject, body=body)
            return True, reply, {"action": "open_gmail", "to": to_addr, "subject": subject, "body": body, "success": ok}

        # E.1.5 Contact Management (Save, List, Delete)
        if self.is_contact_directive(cmd_clean):
            handled, reply, meta = self.handle_contact_directive(raw)
            if handled:
                return True, reply, meta

        # E.2 WhatsApp Launch / Web Message
        if self.is_whatsapp_directive(raw):
            recipient = ""
            phone = ""
            msg = ""

            # Pattern 1: send (a )?(whatsapp )?message to <recipient> saying/with text/message <msg>
            m1 = re.search(
                r"^(?:send\s+(?:a\s+)?(?:whats?a?app\s+)?message\s+to|send\s+whats?a?app\s+to)\s+(?P<recipient>[^,\n:]+?)(?:\s+(?:on|in|via)\s+whats?a?app)?(?:\s*(?::|saying|with\s+(?:text|message)|that)\s*(?P<msg>.+))?$",
                raw,
                re.IGNORECASE,
            )
            # Pattern 2: text/message <recipient> <msg>
            m2 = re.search(
                r"^(?:text|message)\s+(?P<recipient>[+\d\s-]{10,16}|[a-zA-Z]+)\s+(?:saying\s+|with\s+text\s+|that\s+)?(?P<msg>.+)$",
                raw,
                re.IGNORECASE,
            )
            # Pattern 3: send <msg> to <recipient> (in|on|via whatsapp)?
            m3 = re.search(
                r"^(?:send|text|message)\s+(?P<msg>.+?)\s+to\s+(?P<recipient>[^,\n]+?)(?:\s+(?:in|on|via|through)\s+whats?a?app)?$",
                raw,
                re.IGNORECASE,
            )
            # Pattern 4: whatsapp <recipient> <msg>
            m4 = re.search(r"^whats?a?app\s+(?P<recipient>[^\s]+)\s+(?P<msg>.+)$", raw, re.IGNORECASE)

            if m1:
                recipient = m1.group("recipient").strip().strip("'\"")
                msg = m1.group("msg").strip().strip("'\"") if m1.group("msg") else ""
            elif m2:
                recipient = m2.group("recipient").strip().strip("'\"")
                msg = m2.group("msg").strip().strip("'\"")
            elif m3:
                msg = m3.group("msg").strip().strip("'\"")
                recipient = m3.group("recipient").strip().strip("'\"")
            elif m4:
                recipient = m4.group("recipient").strip().strip("'\"")
                msg = m4.group("msg").strip().strip("'\"")

            # If recipient is an email address, reroute to Gmail
            if recipient and "@" in recipient:
                ok, reply = self.open_gmail(to=recipient, body=msg)
                return True, reply, {"action": "open_gmail", "to": recipient, "body": msg, "success": ok}

            if recipient and not phone:
                clean_digits = re.sub(r"[^\d+]", "", recipient)
                if len(re.sub(r"[^\d]", "", clean_digits)) >= 10:
                    phone = clean_digits

            ok, reply = self.open_whatsapp(phone=phone, message=msg, recipient=recipient)
            return True, reply, {"action": "open_whatsapp", "phone": phone, "recipient": recipient, "message": msg, "success": ok}

        # E.3 Open Known Websites
        for site in COMMON_WEBSITES:
            if (
                cmd_clean == f"open {site}"
                or cmd_clean == f"go to {site}"
                or cmd_clean == f"launch {site}"
                or cmd_clean == site
                or f"open {site} in browser" in cmd
            ):
                ok, reply = self.open_website(site)
                return True, reply, {"action": "open_website", "site": site, "success": ok}

        # F. Volume Controls
        vol_pct_match = re.search(r"(?:set|change|turn|put|increase|decrease|raise|lower|boost|bring|adjust|make)\s+(?:the\s+)?volume\s+(?:to\s+|at\s+)?(\d{1,3})\s*%?", cmd)
        if vol_pct_match:
            pct = int(vol_pct_match.group(1))
            ok, reply = self.set_volume_percent(pct)
            return True, reply, {"action": "set_volume", "percent": pct, "success": ok}

        if any(k in cmd for k in ["volume up", "increase volume", "louder", "turn up volume", "raise volume", "raise the volume", "boost volume", "crank up volume", "pump up volume"]):
            reply = self.volume_up(6)
            return True, reply, {"action": "volume_up"}
        if any(k in cmd for k in ["volume down", "decrease volume", "quieter", "lower volume", "lower the volume", "turn down volume", "bring down volume", "reduce volume"]):
            reply = self.volume_down(6)
            return True, reply, {"action": "volume_down"}
        if re.search(r"^(?:please\s+)?(?:unmute|mute)\s*(?:the\s+)?(?:volume|audio|system|pc|laptop)?$", cmd) or cmd in ["mute", "unmute", "mute audio", "unmute audio", "silence audio", "toggle mute"]:
            reply = self.volume_mute()
            return True, reply, {"action": "volume_mute"}

        # G. Display Brightness Controls
        bright_pct_match = re.search(r"(?:set|change|turn|put|increase|decrease|raise|lower|boost|bring|adjust|make)\s+(?:the\s+)?brightness\s+(?:to\s+|at\s+)?(\d{1,3})\s*%?", cmd)
        if bright_pct_match:
            pct = int(bright_pct_match.group(1))
            ok, reply = self.set_brightness(pct)
            return True, reply, {"action": "set_brightness", "percent": pct, "success": ok}

        if any(k in cmd for k in ["brightness up", "increase brightness", "brighter", "turn up brightness"]):
            cur = self.get_brightness() or 50
            target = min(100, cur + 20)
            ok, reply = self.set_brightness(target)
            return True, reply, {"action": "set_brightness", "percent": target, "success": ok}

        if any(k in cmd for k in ["brightness down", "decrease brightness", "dimmer", "turn down brightness", "dim screen"]):
            cur = self.get_brightness() or 50
            target = max(10, cur - 20)
            ok, reply = self.set_brightness(target)
            return True, reply, {"action": "set_brightness", "percent": target, "success": ok}

        # H. Media Controls
        if any(k in cmd for k in ["pause music", "pause video", "pause playback", "pause", "resume music", "resume playback"]):
            reply = self.media_play_pause()
            return True, reply, {"action": "media_play_pause"}
        if any(k in cmd for k in ["next song", "next track", "skip song", "skip track", "next video"]):
            reply = self.media_next()
            return True, reply, {"action": "media_next"}
        if any(k in cmd for k in ["previous song", "previous track", "prev song", "last song"]):
            reply = self.media_prev()
            return True, reply, {"action": "media_prev"}
        if any(k in cmd for k in ["stop music", "stop audio", "stop playback"]):
            reply = self.media_stop()
            return True, reply, {"action": "media_stop"}

        # I. Window & Desktop Management
        if any(k in cmd for k in ["show desktop", "minimize all", "minimize windows", "hide all windows"]):
            reply = self.show_desktop()
            return True, reply, {"action": "show_desktop"}
        if any(k in cmd for k in ["close window", "close active window", "close this window"]):
            reply = self.close_active_window()
            return True, reply, {"action": "close_active_window"}
        if any(k in cmd for k in ["minimize window", "minimize active window"]):
            reply = self.minimize_active_window()
            return True, reply, {"action": "minimize_active_window"}
        if any(k in cmd for k in ["maximize window", "maximize active window", "full screen window"]):
            reply = self.maximize_active_window()
            return True, reply, {"action": "maximize_active_window"}
        if any(k in cmd for k in ["lock laptop", "lock pc", "lock computer", "lock screen", "lock workstation"]):
            reply = self.lock_workstation()
            return True, reply, {"action": "lock_workstation"}
        if any(k in cmd for k in ["sleep laptop", "put laptop to sleep", "sleep pc"]):
            reply = self.sleep_laptop()
            return True, reply, {"action": "sleep_laptop"}

        # J. Close Specific Applications
        if cmd.startswith("close ") or cmd.startswith("kill ") or cmd.startswith("exit ") or cmd.startswith("terminate "):
            app_to_close = re.sub(r"^(?:close|kill|exit|terminate)\s+(?:the\s+)?(?:app|application|program)?\s*", "", raw, flags=re.IGNORECASE).strip()
            if app_to_close and app_to_close.lower() not in ("window", "this window", "active window"):
                ok, reply = self.close_app(app_to_close)
                if ok:
                    return True, reply, {"action": "close_app", "app": app_to_close, "success": ok}

        # K. List Running Apps
        if any(k in cmd for k in ["what apps are open", "list open apps", "list running apps", "running apps", "open windows", "list windows"]):
            apps = self.list_running_apps()
            if apps:
                summary = "Open applications on your desktop:\n" + "\n".join(f" - {a}" for a in apps[:10])
                return True, summary, {"action": "list_running_apps", "apps": apps}
            return True, "No top-level application windows detected.", {"action": "list_running_apps", "apps": []}

        # L. Screenshots & Display Capture
        if any(k in cmd for k in ["take screenshot", "take a screenshot", "capture screen", "screenshot", "screen capture"]):
            ok, reply, b64_img = self.take_screenshot()
            meta: dict[str, Any] = {"action": "screenshot", "success": ok}
            if b64_img:
                meta["image_b64"] = b64_img
            return True, reply, meta

        # M. Keyboard & Typing Automation
        type_match = re.match(r"^(?:type|write|enter text)\s+(.+)$", raw, flags=re.IGNORECASE)
        if type_match:
            text_to_type = type_match.group(1).strip()
            ok, reply = self.type_text(text_to_type)
            return True, reply, {"action": "type_text", "success": ok}

        press_match = re.match(r"^(?:press|hit)\s+(enter|space|tab|escape|esc|backspace|delete|up|down|left|right)$", raw, flags=re.IGNORECASE)
        if press_match:
            key_name = press_match.group(1).strip()
            ok, reply = self.press_key(key_name)
            return True, reply, {"action": "press_key", "key": key_name, "success": ok}

        hotkey_match = re.match(r"^(?:press|hit|execute)\s+(?:hotkey|shortcut)?\s*([a-z0-9+]+)$", cmd)
        if hotkey_match and "+" in hotkey_match.group(1):
            keys = hotkey_match.group(1).split("+")
            ok, reply = self.send_hotkey(keys)
            return True, reply, {"action": "hotkey", "keys": keys, "success": ok}

        # N. Real-time Clock & Date
        if any(k in cmd for k in ["what time is it", "what is the time", "current time", "tell me the time", "what's the time"]):
            from datetime import datetime
            now_str = datetime.now().strftime("%I:%M %p")
            return True, f"The current time is {now_str}.", {"action": "time"}
        if any(k in cmd for k in ["what is today's date", "today's date", "what's the date", "what is the date", "current date"]):
            from datetime import datetime
            date_str = datetime.now().strftime("%A, %B %d, %Y")
            return True, f"Today is {date_str}.", {"action": "date"}

        # O. Settings & System Tools
        if any(k in cmd for k in ["open settings", "windows settings", "system settings"]):
            subprocess.Popen("start ms-settings:", shell=True)
            return True, "Opened Windows Settings.", {"action": "open_settings"}

        # P. Battery & Hardware Telemetry
        if (
            cmd in ["battery", "battery status", "battery level", "power status", "charging", "battery percent", "battery percentage"]
            or any(cmd == k or cmd == f"check {k}" or cmd == f"get {k}" or cmd == f"show {k}" for k in ["battery", "battery status", "battery level", "power status"])
            or re.search(r"^(?:what is|how is|check|tell me|get|show)\s+(?:the\s+)?(?:battery|power|charging)\b", cmd)
        ):
            reply = self.get_battery_info()
            return True, reply, {"action": "battery_info"}
        if any(k in cmd for k in ["system specs", "specs", "laptop specs", "hardware status"]) or cmd in ("system status", "hardware"):
            reply = self.get_system_specs()
            return True, reply, {"action": "specs"}

        # Q. Network Status
        if any(k in cmd for k in ["wifi status", "network status", "internet status", "my ip", "check internet", "ip address"]):
            reply = self.get_network_status()
            return True, reply, {"action": "network_status"}

        # R. User Folders
        if cmd.startswith("open ") or cmd.startswith("go to "):
            folder_candidate = re.sub(r"^(?:open|go to)\s+(?:the\s+)?(?:folder|directory)?\s*", "", raw, flags=re.IGNORECASE).strip()
            if folder_candidate.lower() in [
                "downloads", "download", "desktop", "documents", "document", "pictures", "photos", "videos", "music", "c drive", "friday"
            ]:
                ok, reply = self.open_folder(folder_candidate)
                if ok:
                    return True, reply, {"action": "open_folder", "success": ok}

        # S. Arbitrary PowerShell command execution
        if cmd.startswith("powershell ") or cmd.startswith("run command ") or cmd.startswith("execute command ") or cmd.startswith("run powershell "):
            ps_cmd = re.sub(r"^(?:powershell|run command|execute command|run powershell)\s+", "", raw, flags=re.IGNORECASE).strip()
            if ps_cmd:
                ok, output = self.run_powershell(ps_cmd)
                return True, f"Command output:\n{output}", {"action": "powershell", "success": ok}

        # T. Launch Applications (Fallback)
        if cmd.startswith("open ") or cmd.startswith("launch ") or cmd.startswith("start "):
            app_candidate = re.sub(r"^(?:open|launch|start)\s+(?:the\s+)?(?:app|application|program)?\s*", "", raw, flags=re.IGNORECASE).strip()
            ok, reply = self.launch_app(app_candidate)
            if ok:
                return True, reply, {"action": "launch_app", "app": app_candidate, "success": ok}

        return False, "", {}


# Global singleton instance
windows_friday = WindowsFridayController()
