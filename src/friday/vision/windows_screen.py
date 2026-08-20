# -*- coding: utf-8 -*-
"""Windows native desktop screen capture provider using Win32 GDI API and fallback PowerShell capture.

Provides direct ctypes Win32 GDI BitBlt capture with automatic PowerShell .NET fallback
for headless/service or restricted window station environments. Pure Python with zero heavy GUI dependencies.
"""

import base64
import ctypes
from ctypes import wintypes
from datetime import datetime
import os
import struct
import subprocess
import time
from typing import Any, Dict, List, Optional
import zlib

import numpy as np

from friday.core.logging import get_logger
from friday.vision.screen_base import BaseScreenCaptureProvider, ScreenSnapshot

logger = get_logger("vision.screen.windows")

SRCCOPY = 0x00CC0020
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_CMONITORS = 80
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class WindowsScreenCaptureProvider(BaseScreenCaptureProvider):
    """Windows native screen capture using Win32 GDI BitBlt and PowerShell .NET fallback."""

    def __init__(self) -> None:
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32

        # Configure Win32 GDI types
        self._user32.GetDC.restype = wintypes.HDC
        self._user32.GetDC.argtypes = [wintypes.HWND]
        self._user32.ReleaseDC.restype = wintypes.INT
        self._user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self._gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self._gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self._gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self._gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, wintypes.INT, wintypes.INT]
        self._gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self._gdi32.BitBlt.restype = wintypes.BOOL
        self._gdi32.BitBlt.argtypes = [
            wintypes.HDC, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.INT,
            wintypes.HDC, wintypes.INT, wintypes.INT, wintypes.DWORD
        ]
        self._gdi32.DeleteObject.restype = wintypes.BOOL
        self._gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self._gdi32.DeleteDC.restype = wintypes.BOOL
        self._gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self._gdi32.GetDIBits.restype = wintypes.INT
        self._gdi32.GetDIBits.argtypes = [
            wintypes.HDC,
            wintypes.HBITMAP,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.LPVOID,
            ctypes.c_void_p,
            wintypes.UINT,
        ]

    def list_displays(self) -> List[Dict[str, Any]]:
        """Enumerate display monitors on Windows."""
        displays: List[Dict[str, Any]] = []

        primary_w = self._user32.GetSystemMetrics(SM_CXSCREEN)
        primary_h = self._user32.GetSystemMetrics(SM_CYSCREEN)
        monitors_count = self._user32.GetSystemMetrics(SM_CMONITORS) or 1

        displays.append({
            "id": "primary",
            "index": 0,
            "is_primary": True,
            "width": primary_w if primary_w > 0 else 1920,
            "height": primary_h if primary_h > 0 else 1080,
            "x": 0,
            "y": 0,
        })

        if monitors_count > 1:
            virt_w = self._user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            virt_h = self._user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            virt_x = self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            virt_y = self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            displays.append({
                "id": "virtual_desktop",
                "index": 1,
                "is_primary": False,
                "width": virt_w,
                "height": virt_h,
                "x": virt_x,
                "y": virt_y,
            })

        return displays

    def _encode_png(self, bgra_data: bytearray, width: int, height: int) -> bytes:
        """Encode raw top-down BGRA buffer to standard PNG bytes."""
        arr = np.frombuffer(bgra_data, dtype=np.uint8).reshape((height, width, 4))

        rgba = np.empty((height, width, 4), dtype=np.uint8)
        rgba[:, :, 0] = arr[:, :, 2]  # R
        rgba[:, :, 1] = arr[:, :, 1]  # G
        rgba[:, :, 2] = arr[:, :, 0]  # B
        rgba[:, :, 3] = 255           # A

        filter_col = np.zeros((height, 1), dtype=np.uint8)
        raw_scanlines = np.hstack([filter_col, rgba.reshape(height, width * 4)]).tobytes()

        compressed = zlib.compress(raw_scanlines, level=4)

        png = bytearray(b"\x89PNG\r\n\x1a\n")
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        png.extend(struct.pack(">I", len(ihdr_data)))
        png.extend(b"IHDR")
        png.extend(ihdr_data)
        png.extend(struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF))

        png.extend(struct.pack(">I", len(compressed)))
        png.extend(b"IDAT")
        png.extend(compressed)
        png.extend(struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF))

        png.extend(struct.pack(">I", 0))
        png.extend(b"IEND")
        png.extend(struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF))

        return bytes(png)

    def _capture_via_powershell(self, display: str = "primary") -> Optional[ScreenSnapshot]:
        """Capture screenshot via Windows PowerShell .NET as a reliable fallback."""
        try:
            ps_script = (
                "[Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                "[Reflection.Assembly]::LoadWithPartialName('System.Drawing') | Out-Null; "
                "$scr = [System.Windows.Forms.Screen]::PrimaryScreen; "
                "$b = $scr.Bounds; "
                "$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height); "
                "$g = [System.Drawing.Graphics]::FromImage($bmp); "
                "try { $g.CopyFromScreen($b.X, $b.Y, 0, 0, $b.Size) } catch {}; "
                "$ms = New-Object System.IO.MemoryStream; "
                "$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); "
                "[Console]::Out.Write([Convert]::ToBase64String($ms.ToArray())); "
                "$g.Dispose(); $bmp.Dispose(); $ms.Dispose();"
            )
            res = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=8.0,
            )
            b64_output = res.stdout.strip()
            if b64_output:
                png_bytes = base64.b64decode(b64_output)
                if png_bytes.startswith(b"\x89PNG"):
                    w = self._user32.GetSystemMetrics(SM_CXSCREEN) or 1920
                    h = self._user32.GetSystemMetrics(SM_CYSCREEN) or 1080
                    return ScreenSnapshot(
                        image_data=png_bytes,
                        mime_type="image/png",
                        width=w,
                        height=h,
                        display_id=display,
                        captured_at=datetime.utcnow(),
                        is_error=False,
                    )
        except Exception as e:
            logger.debug(f"PowerShell screen capture fallback error: {e}")
        return None

    def capture_screen(
        self,
        display: str = "primary",
        **kwargs: Any,
    ) -> ScreenSnapshot:
        """Capture screenshot using Win32 GDI BitBlt with PowerShell fallback."""
        h_desktop_dc = None
        h_capture_dc = None
        h_bitmap = None

        try:
            width = self._user32.GetSystemMetrics(SM_CXSCREEN)
            height = self._user32.GetSystemMetrics(SM_CYSCREEN)
            src_x, src_y = 0, 0

            if display.lower() in ("virtual", "all", "1") and self._user32.GetSystemMetrics(SM_CMONITORS) > 1:
                width = self._user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
                height = self._user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
                src_x = self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
                src_y = self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN)

            if width <= 0 or height <= 0:
                raise RuntimeError(f"Invalid display dimensions detected: {width}x{height}")

            h_desktop_dc = self._user32.GetDC(0)
            if not h_desktop_dc:
                raise RuntimeError("Failed to acquire Desktop Device Context (GetDC returned NULL)")

            h_capture_dc = self._gdi32.CreateCompatibleDC(h_desktop_dc)
            if not h_capture_dc:
                raise RuntimeError("Failed to create compatible memory Device Context")

            h_bitmap = self._gdi32.CreateCompatibleBitmap(h_desktop_dc, width, height)
            if not h_bitmap:
                raise RuntimeError("Failed to create compatible GDI bitmap")

            old_obj = self._gdi32.SelectObject(h_capture_dc, h_bitmap)

            success = self._gdi32.BitBlt(
                h_capture_dc, 0, 0, width, height, h_desktop_dc, src_x, src_y, SRCCOPY
            )
            if not success:
                # If Win32 GDI BitBlt fails in background context, attempt PowerShell fallback
                logger.info("Win32 BitBlt failed; attempting PowerShell screen capture fallback...")
                ps_snap = self._capture_via_powershell(display=display)
                if ps_snap is not None:
                    return ps_snap
                raise RuntimeError("Win32 BitBlt screenshot transfer failed and fallback was unavailable")

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0

            buf_size = width * height * 4
            raw_bytes = bytearray(buf_size)
            buf = (ctypes.c_char * buf_size).from_buffer(raw_bytes)

            copied_lines = self._gdi32.GetDIBits(
                h_capture_dc, h_bitmap, 0, height, buf, ctypes.byref(bmi), 0
            )
            if copied_lines != height:
                raise RuntimeError(f"GetDIBits failed to copy full scanlines ({copied_lines}/{height})")

            png_data = self._encode_png(raw_bytes, width, height)

            return ScreenSnapshot(
                image_data=png_data,
                mime_type="image/png",
                width=width,
                height=height,
                display_id=display,
                captured_at=datetime.utcnow(),
                is_error=False,
            )

        except Exception as e:
            logger.error(f"Windows screen capture failed: {e}")
            return ScreenSnapshot(
                image_data=b"",
                mime_type="image/png",
                display_id=display,
                is_error=True,
                error_message=str(e),
            )

        finally:
            if h_bitmap:
                self._gdi32.DeleteObject(h_bitmap)
            if h_capture_dc:
                self._gdi32.DeleteDC(h_capture_dc)
            if h_desktop_dc:
                self._user32.ReleaseDC(0, h_desktop_dc)
