# -*- coding: utf-8 -*-
"""Regression tests for Windows Screen Capture Win32 GDI integer-width, ctypes definitions, and display metadata."""

import ctypes
from ctypes import wintypes
import pytest

from friday.vision.windows_screen import WindowsScreenCaptureProvider, BITMAPINFOHEADER


def test_windows_screen_gdi_types_configured():
    """Verify that Win32 GDI function prototypes are explicitly configured with accurate ctypes."""
    provider = WindowsScreenCaptureProvider()

    # Verify GDI types
    assert provider._gdi32.GetDIBits.restype == wintypes.INT
    assert len(provider._gdi32.GetDIBits.argtypes) == 7
    assert provider._gdi32.GetDIBits.argtypes[0] == wintypes.HDC
    assert provider._gdi32.GetDIBits.argtypes[1] == wintypes.HBITMAP
    assert provider._gdi32.GetDIBits.argtypes[2] == wintypes.UINT
    assert provider._gdi32.GetDIBits.argtypes[3] == wintypes.UINT
    assert provider._gdi32.GetDIBits.argtypes[4] == wintypes.LPVOID
    assert provider._gdi32.GetDIBits.argtypes[5] == ctypes.c_void_p
    assert provider._gdi32.GetDIBits.argtypes[6] == wintypes.UINT

    # Verify BitBlt types
    assert provider._gdi32.BitBlt.restype == wintypes.BOOL
    assert len(provider._gdi32.BitBlt.argtypes) == 9


def test_bitmapinfoheader_structure():
    """Verify BITMAPINFOHEADER struct packing and field sizes."""
    bmi = BITMAPINFOHEADER()
    assert ctypes.sizeof(BITMAPINFOHEADER) == 40
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = 1536
    bmi.biHeight = -864
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    assert bmi.biWidth == 1536
    assert bmi.biHeight == -864


def test_encode_png_deterministic():
    """Verify that _encode_png produces valid PNG header, IHDR, IDAT, and IEND chunks."""
    provider = WindowsScreenCaptureProvider()
    width, height = 10, 10
    # 10x10 BGRA buffer
    raw_bgra = bytearray(width * height * 4)
    for i in range(0, len(raw_bgra), 4):
        raw_bgra[i] = 255      # B
        raw_bgra[i + 1] = 128  # G
        raw_bgra[i + 2] = 64   # R
        raw_bgra[i + 3] = 255  # A

    png_bytes = provider._encode_png(raw_bgra, width, height)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in png_bytes
    assert b"IDAT" in png_bytes
    assert png_bytes.endswith(b"IEND\xaeB`\x82") or b"IEND" in png_bytes
