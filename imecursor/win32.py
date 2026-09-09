"""Win32 API の共通定義。標準ライブラリ (ctypes) のみを使う。"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform != "win32":  # pragma: no cover - Windows 専用
    raise ImportError(
        "ime_cursor は Windows 上で実行してください。\n"
        "WSL からは: powershell.exe -NoProfile -Command \"pythonw ime_cursor.pyw\""
    )

user32 = ctypes.WinDLL("user32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# -- IME -------------------------------------------------------------------
WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 0x0001
IMC_GETOPENSTATUS = 0x0005

IME_CMODE_ALPHANUMERIC = 0x0000
IME_CMODE_NATIVE = 0x0001
IME_CMODE_KATAKANA = 0x0002
IME_CMODE_FULLSHAPE = 0x0008
IME_CMODE_ROMAN = 0x0010

SMTO_ABORTIFHUNG = 0x0002

LANG_JAPANESE = 0x11

# -- ウィンドウスタイル ----------------------------------------------------
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

# -- システムメトリクス ----------------------------------------------------
SM_CXCURSOR = 13
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# -- カーソルの差し替え ----------------------------------------------------
# SM_CXCURSOR はプロセス起動時にキャッシュされるため、CursorBaseSize を書いて
# SPI_SETCURSORS しても「サイズ」は変わらない (ファイルの読み直しだけ)。
# サイズを実際に変えるには、LoadImageW で寸法を指定して読み込んだカーソルを
# SetSystemCursor でセッション全体に載せる。
IMAGE_CURSOR = 2
LR_LOADFROMFILE = 0x0010

# SetSystemCursor で差し替えできる標準カーソル (OCR_*)
OCR_NORMAL = 32512
OCR_IBEAM = 32513
OCR_WAIT = 32514
OCR_CROSS = 32515
OCR_UP = 32516
OCR_SIZENWSE = 32642
OCR_SIZENESW = 32643
OCR_SIZEWE = 32644
OCR_SIZENS = 32645
OCR_SIZEALL = 32646
OCR_NO = 32648
OCR_HAND = 32649
OCR_APPSTARTING = 32650
OCR_HELP = 32651

# -- SystemParametersInfo --------------------------------------------------
# SPI_SETCURSORS は pvParam を取らないため SPIF_UPDATEINIFILE を渡すと
# ERROR_INVALID_HANDLE で失敗する。SPIF_SENDCHANGE だけを指定すること。
SPI_SETCURSORS = 0x0057
SPIF_SENDCHANGE = 0x02

# -- 単一インスタンス ------------------------------------------------------
ERROR_ALREADY_EXISTS = 183


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
user32.GetKeyboardLayout.restype = wintypes.HKL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM
user32.SystemParametersInfoW.argtypes = [
    wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT
]
user32.SystemParametersInfoW.restype = wintypes.BOOL

imm32.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]
imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND

user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.CopyImage.argtypes = [
    wintypes.HANDLE, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT
]
user32.CopyImage.restype = wintypes.HANDLE
user32.SetSystemCursor.argtypes = [wintypes.HANDLE, wintypes.DWORD]
user32.SetSystemCursor.restype = wintypes.BOOL
user32.DestroyCursor.argtypes = [wintypes.HANDLE]
user32.DestroyCursor.restype = wintypes.BOOL
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]

kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.GetFinalPathNameByHandleW.argtypes = [
    wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD
]
kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

FILE_SHARE_READ_WRITE = 0x00000003
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

# 64bit では *Ptr* 版を使う。32bit の Python には存在しないためフォールバックする
GetWindowLong = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
SetWindowLong = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLong.restype = ctypes.c_ssize_t
SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
SetWindowLong.restype = ctypes.c_ssize_t


def enable_dpi_awareness() -> None:
    """カーソル座標とウィンドウ座標を物理ピクセルで一致させる。"""
    try:  # Per-Monitor v2 (Win10 1703+)
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def broadcast_cursor_change() -> bool:
    """レジストリに書いたカーソル設定を、再ログオンなしで全プロセスへ反映する。"""
    return bool(user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, SPIF_SENDCHANGE))


def cursor_pixel_size() -> int:
    """このプロセスが認識しているカーソルのピクセルサイズ。

    SM_CXCURSOR はプロセスごとにキャッシュされるので、実行中に変わることは
    ない。あくまで「起動時点のシステム設定」を見るための値。
    """
    return int(user32.GetSystemMetrics(SM_CXCURSOR)) or 32


def load_cursor_at_size(path: str | None, ocr: int | None, size: int) -> int | None:
    """指定サイズのカーソルハンドルを作る。呼び出し側が所有権を持つ。

    path があればそのファイルから、無ければ OS 内蔵カーソルを複製して拡縮する。
    """
    if path:
        handle = user32.LoadImageW(None, path, IMAGE_CURSOR, size, size, LR_LOADFROMFILE)
        if handle:
            return int(handle)
    if ocr is None:
        return None
    # 内蔵カーソルは共有ハンドルなので、そのまま SetSystemCursor に渡せない。
    # CopyImage で指定サイズの非共有コピーを作る
    shared = user32.LoadCursorW(None, ctypes.cast(ocr, wintypes.LPCWSTR))
    if not shared:
        return None
    copied = user32.CopyImage(shared, IMAGE_CURSOR, size, size, 0)
    return int(copied) if copied else None


def set_system_cursor(handle: int, ocr: int) -> bool:
    """カーソルをセッション全体に載せる。成功するとハンドルの所有権は OS に移る。"""
    if user32.SetSystemCursor(handle, ocr):
        return True
    user32.DestroyCursor(handle)
    return False


def virtual_screen() -> tuple[int, int, int, int]:
    """仮想デスクトップ全体の (x, y, 幅, 高さ)。"""
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def message_box(text: str, title: str = "ime_cursor", icon: int = 0x40) -> None:
    """pythonw では stderr が None なので、致命的な通知はダイアログで出す。"""
    user32.MessageBoxW(None, text, title, icon)


def real_path(path: str) -> str:
    """仮想化を通り抜けた実体パスを返す。解決できなければ元のパスを返す。

    Microsoft Store 版 Python は %LOCALAPPDATA% / %APPDATA% への書き込みを
    パッケージ配下の LocalCache に転送する。レジストリに書くパスは、他の
    プロセスからも開ける実体でなければ意味がないため、ここで解決する。
    """
    handle = kernel32.CreateFileW(
        path, 0, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS, None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        return path
    try:
        buf = ctypes.create_unicode_buffer(1024)
        length = kernel32.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
        if not length or length >= len(buf):
            return path
        resolved = buf.value[:length]
    finally:
        kernel32.CloseHandle(handle)
    # カーソルの読み込みは \\?\ 付きの長いパス形式を受け付けないので外す
    if resolved.startswith("\\\\?\\UNC\\"):
        return "\\\\" + resolved[8:]
    if resolved.startswith("\\\\?\\"):
        return resolved[4:]
    return resolved


def acquire_single_instance(name: str) -> bool:
    """名前付きミューテックスを取る。既に他プロセスが持っていれば False。"""
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True  # 取得できない環境では多重起動チェックを諦める
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS
