"""Foreground metadata only; no keyboard/mouse/UI control."""
import sys


def foreground_window(monitors):
    if sys.platform != 'win32': return None
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32',use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.GetWindowRect.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.IsIconic.argtypes = [wintypes.HWND]
    handle = user.GetForegroundWindow()
    if not handle or user.IsIconic(handle): return None
    rect = wintypes.RECT()
    if not user.GetWindowRect(handle,ctypes.byref(rect)): return None
    title = ctypes.create_unicode_buffer(min(1024,user.GetWindowTextLengthW(handle)+1))
    user.GetWindowTextW(handle,title,len(title))
    width,height = rect.right-rect.left,rect.bottom-rect.top
    if width <= 0 or height <= 0: return None
    def overlap(m):
        return max(0,min(rect.right,m['x']+m['width'])-max(rect.left,m['x']))*max(0,min(rect.bottom,m['y']+m['height'])-max(rect.top,m['y']))
    monitor = max(monitors,key=overlap) if monitors else None
    return dict(handle=int(handle),title=title.value,monitor=monitor['id'] if monitor else None,
                x=rect.left,y=rect.top,width=width,height=height)
