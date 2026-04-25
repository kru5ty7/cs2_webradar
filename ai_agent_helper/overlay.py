"""
CS2 ESP overlay — full-screen transparent always-on-top WebView2 window.
Always click-through (mouse events pass to the game underneath).
Must be started from the main thread (Win32 / pywebview requirement).
"""
import ctypes
import ctypes.wintypes
import logging
import time

log = logging.getLogger("radar")

# Win32 constants
GWL_EXSTYLE       = -20
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
SWP_NOMOVE        = 0x0002
SWP_NOSIZE        = 0x0001
HWND_TOPMOST      = -1

_hwnd: int = 0

# Detect primary monitor resolution once at import time
_SW = ctypes.windll.user32.GetSystemMetrics(0)  # SM_CXSCREEN
_SH = ctypes.windll.user32.GetSystemMetrics(1)  # SM_CYSCREEN


def _get_hwnd(win) -> int:
    try:
        h = int(win.native_handle)
        if h:
            return h
    except Exception:
        pass
    return ctypes.windll.user32.FindWindowW(None, win.title) or 0


def _apply_clickthrough(hwnd: int):
    ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)


def start(url: str, width: int = None, height: int = None, x: int = 0, y: int = 0):
    """
    Open a full-screen transparent click-through overlay showing `url`.
    Blocks until the window is closed — call from the main thread.
    """
    try:
        import webview
    except ImportError:
        log.error("pywebview not installed — overlay unavailable. Run: pip install pywebview")
        return

    global _hwnd

    w = width  or _SW
    h = height or _SH

    win = webview.create_window(
        "CS2Overlay",
        url,
        x=x, y=y,
        width=w,
        height=h,
        resizable=False,
        frameless=True,
        on_top=True,
        transparent=True,
        background_color="#00000000",
        text_select=False,
        zoomable=False,
    )

    def _on_shown():
        global _hwnd
        time.sleep(0.4)
        _hwnd = _get_hwnd(win)
        if not _hwnd:
            log.warning("overlay: could not get HWND")
            return
        _apply_clickthrough(_hwnd)
        ctypes.windll.user32.SetWindowPos(
            _hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE,
        )
        log.info("overlay: ready  hwnd=0x%X  %dx%d  click-through=ON", _hwnd, w, h)

    win.events.shown += _on_shown

    log.info("overlay: starting  %dx%d → %s", w, h, url)
    webview.start(gui="edgechromium", debug=False)
    log.info("overlay: closed")
