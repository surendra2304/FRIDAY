# -*- coding: utf-8 -*-
"""UI Automation provider abstraction for FRIDAY.

Provides a concrete Windows implementation using `pywinauto` that is imported lazily
and only when the feature flag `ui_automation_enabled` is true on a Windows platform.
"""

import difflib
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("ui_automation.provider")

# Conditional import – avoid ImportError on non‑Windows platforms.
if os.name == "nt":
    try:
        from pywinauto import Application, findwindows
        from pywinauto.controls.uiawrapper import UIAWrapper
    except Exception:
        Application = None  # type: ignore
        findwindows = None  # type: ignore
        UIAWrapper = None  # type: ignore
else:
    Application = None  # type: ignore
    findwindows = None  # type: ignore
    UIAWrapper = None  # type: ignore


@dataclass
class UIElement:
    """Lightweight wrapper around a pywinauto UIA element.
    Exposes only the attributes needed for FRIDAY's matching and actions.
    """

    handle: Any
    automation_id: Optional[str]
    name: Optional[str]
    control_type: Optional[str]
    rectangle: Dict[str, int]

    @staticmethod
    def from_uia(element: "UIAWrapper") -> "UIElement":
        rect = element.rectangle()
        return UIElement(
            handle=element,
            automation_id=element.automation_id(),
            name=element.name(),
            control_type=element.control_type(),
            rectangle={"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
        )


class UIAutomationProvider:
    """Abstract base class – currently only Windows implementation exists.
    All public methods return `None` or raise `NotImplementedError` if the
    platform does not support UI Automation.
    """

    def __init__(self, *, app: Optional[Any] = None):
        self._app = app

    def find_element(self, query: str) -> Optional[UIElement]:
        raise NotImplementedError

    def launch_application(self, executable: str) -> bool:
        raise NotImplementedError

    def click(self, element: UIElement) -> bool:
        raise NotImplementedError

    def double_click(self, element: UIElement) -> bool:
        raise NotImplementedError

    def right_click(self, element: UIElement) -> bool:
        raise NotImplementedError

    def type_text(self, element: UIElement, text: str) -> bool:
        raise NotImplementedError

    def capture_state(self) -> Dict[str, Any]:
        raise NotImplementedError


class WindowsUIAutomationProvider(UIAutomationProvider):
    def __init__(self):
        if Application is None:
            raise RuntimeError("pywinauto is not available on this system.")
        super().__init__(app=Application(backend="uia").connect(path="explorer.exe", timeout=5))

    def _enumerate_all_elements(self) -> List[UIElement]:
        elements: List[UIElement] = []
        for win in findwindows.find_elements():
            try:
                wrapper = UIAWrapper(win)
                elements.append(UIElement.from_uia(wrapper))
            except Exception:
                continue
        return elements

    def find_element(self, query: str) -> Optional[UIElement]:
        candidates = self._enumerate_all_elements()
        query_norm = query.lower().strip()
        best_score = 0.0
        best_el = None
        for el in candidates:
            parts = [p for p in (el.automation_id, el.name, el.control_type) if p]
            if not parts:
                continue
            part_scores = [
                difflib.SequenceMatcher(None, query_norm, p.lower()).ratio() for p in parts
            ]
            combined = " ".join(p.lower() for p in parts)
            score = max(part_scores + [difflib.SequenceMatcher(None, query_norm, combined).ratio()])
            # Reward direct containment (e.g. query "send" inside element name "Send button")
            if any(query_norm in p.lower() for p in parts):
                score = max(score, 0.85)
            if score > best_score:
                best_score = score
                best_el = el
        if best_el:
            # Attach confidence for later use
            setattr(best_el, "confidence", best_score)
        return best_el

    def launch_application(self, executable: str) -> bool:
        """Launch an application natively without pywinauto.

        os.startfile (ShellExecute) resolves the Windows App Paths registry,
        which is where browsers like chrome.exe and msedge.exe are registered
        (they are not on PATH); it also opens protocol URIs such as
        'ms-settings:'. Falls back to subprocess.Popen (shell=True) for
        executables that only resolve via PATH.
        """
        try:
            if not executable.lower().endswith(".exe"):
                # Protocol URIs and registered documents: ShellExecute only.
                os.startfile(executable)
                return True
            try:
                os.startfile(executable)
                return True
            except OSError:
                logger.warning(f"App Paths/ShellExecute failed for '{executable}'; trying PATH via shell.")
            subprocess.Popen(executable, shell=True)
            return True
        except Exception as e:
            logger.error(f"Failed to launch '{executable}': {e}")
            return False

    def click(self, element: UIElement) -> bool:
        try:
            element.handle.click_input()
            return True
        except Exception:
            return False

    def double_click(self, element: UIElement) -> bool:
        try:
            element.handle.double_click_input()
            return True
        except Exception:
            return False

    def right_click(self, element: UIElement) -> bool:
        try:
            element.handle.right_click_input()
            return True
        except Exception:
            return False

    def type_text(self, element: UIElement, text: str) -> bool:
        try:
            element.handle.set_focus()
            element.handle.type_keys(text, with_spaces=True)
            return True
        except Exception:
            return False

    def capture_state(self) -> Dict[str, Any]:
        state = {}
        for win in findwindows.find_elements():
            try:
                wrapper = UIAWrapper(win)
                el = UIElement.from_uia(wrapper)
                state[el.name or "Unnamed"] = {
                    "automation_id": el.automation_id,
                    "control_type": el.control_type,
                    "rect": el.rectangle,
                }
            except Exception:
                continue
        return state

__all__ = ["UIAutomationProvider", "WindowsUIAutomationProvider", "UIElement"]
