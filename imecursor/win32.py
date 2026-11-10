"""Win32 API の共通定義。標準ライブラリ (ctypes) のみを使う。"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

if sys.platform != "win32":  # pragma: no cover - Windows 専用
    raise ImportError(
        "ime_cursor は Windows 上で実行してください。\n"
        "WSL からは: powershell.exe -NoProfile -Command \"pythonw ime_cursor.pyw\""
    )

user32 = ctypes.WinDLL("user32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:  # Win8.1 以降。無い環境ではシステム全体の DPI で代用する
    shcore = ctypes.WinDLL("shcore")
except OSError:  # pragma: no cover - 環境依存
    shcore = None

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

# -- DPI -------------------------------------------------------------------
# このプロセスは Per-Monitor v2 なので、Tk の 1 ピクセル = 物理ピクセル。
# 文字や余白を見た目のサイズで揃えるには、モニタの拡大率を掛ける必要がある
BASE_DPI = 96
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0

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

# -- グローバルホットキー --------------------------------------------------
# RegisterHotKey に hwnd=NULL を渡すと WM_HOTKEY は「登録したスレッドの」
# メッセージキューに積まれる。tkinter のメッセージポンプはスレッドメッセージも
# GetMessage で拾ってしまうが、hwnd が NULL なので DispatchMessage が何もせず
# 捨ててしまう。つまり Tk 上で待っていても届かない (hotkey.py 参照)
WM_QUIT = 0x0012
WM_HOTKEY = 0x0312
WM_APP = 0x8000

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # 押しっぱなしで連射させない

VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21    # PageUp
VK_NEXT = 0x22     # PageDown
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28

# -- 低レベルキーボードフック ----------------------------------------------
# RegisterHotKey はキーを奪ってしまう (下のアプリに届かない)。スライド送りの
# キーは「押されたことを知りたいが、下のアプリにもそのまま渡したい」ので、
# WH_KEYBOARD_LL で覗くだけにする。フックはメッセージループを回している
# スレッドで入れる必要がある (hotkey.py のスレッドで入れている)
WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# -- ウィンドウの表示と当たり判定 ------------------------------------------
SW_HIDE = 0
SW_SHOWNA = 8      # activate せずに表示する
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
PM_NOREMOVE = 0x0000
GA_ROOT = 2     # GetAncestor: トップレベルまで遡る

# -- 単一インスタンス ------------------------------------------------------
ERROR_ALREADY_EXISTS = 183

# -- クリップボード --------------------------------------------------------
# 変化の検知は GetClipboardSequenceNumber だけで足りる。セッションごとの DWORD
# で、クリップボードが書き換わるたびに増える。クリップボードを開かないので
# 他アプリのコピーを一切邪魔しない (OpenClipboard はロックを取ってしまう)。
CF_TEXT = 1
CF_BITMAP = 2
CF_DIB = 8
CF_UNICODETEXT = 13
CF_HDROP = 15

# パスワードマネージャなどが「監視するな」の意思表示として載せるフォーマット。
# 名前で登録して IsClipboardFormatAvailable で有無だけ見る (開く必要はない)
EXCLUSION_FORMAT_NAMES = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "Clipboard Viewer Ignore",
)

# OpenClipboard は他アプリが開いている間は失敗する。待ちすぎると GUI が
# 固まるので、ごく短く 1 回だけ待って諦める
CLIPBOARD_RETRY_WAIT = 0.02


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


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
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
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
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
]
user32.GetMessageW.restype = ctypes.c_int  # 失敗時の -1 を取りこぼさない
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT
]
user32.PeekMessageW.restype = wintypes.BOOL
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD
]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND

kernel32.GetCurrentThreadId.restype = wintypes.DWORD

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

user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.CloseClipboard.restype = wintypes.BOOL

kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t

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


def dpi_scale_at(x: int, y: int) -> float:
    """その座標のあるモニタの拡大率 (96dpi = 1.0、200% なら 2.0)。

    マルチモニタで拡大率が違う場合に備えて、システム全体ではなくモニタ単位で
    問い合わせる。取れない環境ではシステム全体の DPI、それも駄目なら 1.0。
    """
    if shcore is not None:
        monitor = user32.MonitorFromPoint(
            wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST
        )
        dpi_x = wintypes.UINT()
        dpi_y = wintypes.UINT()
        if monitor and shcore.GetDpiForMonitor(
            monitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
        ) == 0:
            return (dpi_x.value or BASE_DPI) / BASE_DPI
    try:
        return (int(user32.GetDpiForSystem()) or BASE_DPI) / BASE_DPI
    except AttributeError:  # pragma: no cover - Win8 以前
        return 1.0


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


def toplevel_hwnd(widget_id: int) -> int:
    """tkinter の winfo_id() から、実際のトップレベル HWND を得る。

    Tk のトップレベルは Tk が用意したラッパーウィンドウの子になっている。
    拡張スタイルはラッパー側に付けないと効かない (当たり判定もラッパー単位で
    決まる) ので、必ずこれを通す。
    """
    return int(user32.GetParent(widget_id) or widget_id)


def get_ex_style(hwnd: int) -> int:
    return int(GetWindowLong(hwnd, GWL_EXSTYLE))


def add_ex_style(hwnd: int, flags: int) -> int:
    """既存の拡張スタイルを壊さずに追加する。

    読んで足して書き戻すので、Tk が自分で付けた WS_EX_LAYERED
    (-alpha / -transparentcolor を指定すると付く) を消さない。
    """
    style = get_ex_style(hwnd) | flags
    SetWindowLong(hwnd, GWL_EXSTYLE, style)
    return style


def show_window_no_activate(hwnd: int) -> None:
    """フォアグラウンドを奪わずにウィンドウを出す。

    Tk の deiconify() は内部で ShowWindow(SW_RESTORE) を呼ぶため、
    WS_EX_NOACTIVATE を付けていても表示の瞬間に活性化してしまう (実測)。
    プレゼン中に下のアプリからフォーカスを奪わないよう、表示と非表示は
    Tk ではなく SW_SHOWNA / SW_HIDE で直接行う。
    """
    user32.ShowWindow(hwnd, SW_SHOWNA)


def place_window_no_activate(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    """位置と大きさを決めて、最前面に、活性化せずに表示する。

    Tk の geometry() は withdraw 中のウィンドウには効かない (マップする
    ときにまとめて適用される)。SW_SHOWNA で直接出すとマップを経由しない
    ため、Tk に頼ると左上 (0, 0) に出てしまう (実測)。位置・大きさ・
    Z オーダー・表示を SetWindowPos 1 回で済ませる。
    """
    user32.SetWindowPos(
        hwnd, wintypes.HWND(HWND_TOPMOST), int(x), int(y), int(width), int(height),
        SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )


def hide_window(hwnd: int) -> None:
    user32.ShowWindow(hwnd, SW_HIDE)


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


def restore_foreground(hwnd: int) -> bool:
    """フォアグラウンドを hwnd に返す。

    Tk の deiconify() は内部で ShowWindow(SW_RESTORE) を呼ぶため、
    WS_EX_NOACTIVATE を付けていてもその瞬間だけ活性化してしまう
    (実測)。表示した直後にこれを呼んで、元のアプリに返す。
    こちらがフォアグラウンドを持っている間の呼び出しなので拒否されない。
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    return bool(user32.SetForegroundWindow(hwnd))


def window_at(x: int, y: int) -> int:
    """その座標のクリックを受け取るトップレベル HWND (当たり判定の確認用)。"""
    found = user32.WindowFromPoint(wintypes.POINT(x, y))
    if not found:
        return 0
    return int(user32.GetAncestor(found, GA_ROOT) or found)


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


def clipboard_sequence() -> int:
    """クリップボードが書き換わるたびに増える番号。

    クリップボードを開かないので、他アプリのコピーと競合しない。折り返しが
    あるので、大小ではなく「前回と違うか」だけを見ること。
    """
    return int(user32.GetClipboardSequenceNumber())


def clipboard_kind() -> str:
    """いま入っているものの種類。"text" / "image" / "files" / "other"。

    IsClipboardFormatAvailable はクリップボードを開かずに答えられる。
    ファイル → 画像 → テキストの順に見る (エクスプローラのファイルコピーや
    画像のコピーには、説明用のテキストが一緒に載っていることがあるため)。
    """
    if user32.IsClipboardFormatAvailable(CF_HDROP):
        return "files"
    if user32.IsClipboardFormatAvailable(CF_BITMAP) or user32.IsClipboardFormatAvailable(CF_DIB):
        return "image"
    if user32.IsClipboardFormatAvailable(CF_UNICODETEXT) or user32.IsClipboardFormatAvailable(CF_TEXT):
        return "text"
    return "other"


_exclusion_formats: list[int] = []


def clipboard_excluded() -> bool:
    """「中身を覗くな」の印が付いているか (パスワードマネージャなど)。"""
    if not _exclusion_formats:
        for name in EXCLUSION_FORMAT_NAMES:
            fmt = int(user32.RegisterClipboardFormatW(name))
            if fmt:
                _exclusion_formats.append(fmt)
    return any(user32.IsClipboardFormatAvailable(fmt) for fmt in _exclusion_formats)


def _open_clipboard() -> bool:
    """他アプリが開いている場合に備えて 1 回だけ待ち直す。"""
    if user32.OpenClipboard(None):
        return True
    time.sleep(CLIPBOARD_RETRY_WAIT)
    return bool(user32.OpenClipboard(None))


def clipboard_text_head(limit: int) -> str | None:
    """テキストの先頭 limit 文字だけを読む。読めなければ None。

    全体を読まないのは、数 MB のコピーでも一定の速さで済ませるため。
    開いている間は他アプリがクリップボードを触れないので、必ず閉じる。
    """
    if limit <= 0 or not _open_clipboard():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            available = int(kernel32.GlobalSize(handle)) // ctypes.sizeof(ctypes.c_wchar)
            count = min(limit, max(available, 0))
            if count <= 0:
                return ""
            text = ctypes.wstring_at(pointer, count)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    return text.split("\x00", 1)[0]  # 終端の NUL より先は読まない


def acquire_single_instance(name: str) -> bool:
    """名前付きミューテックスを取る。既に他プロセスが持っていれば False。"""
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True  # 取得できない環境では多重起動チェックを諦める
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS
