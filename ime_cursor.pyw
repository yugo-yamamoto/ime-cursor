# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
マウスカーソルの横に現在の IME の状態を表示する常駐オーバーレイ。

- Windows の Win32 API (imm32 / user32) を ctypes で直接呼び出して IME 状態を取得
- tkinter のクリックスルー・最前面ウィンドウをカーソル追従させて表示

起動 (コンソールを出さずに常駐させる):
    エクスプローラーで ime_cursor.pyw をダブルクリック
    pythonw ime_cursor.pyw

終了 (コマンドラインで判別するので、他の .pyw スクリプトは巻き込まない):
    powershell -NoProfile -Command "Get-CimInstance Win32_Process |
      Where-Object { $_.CommandLine -like '*ime_cursor.pyw*' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

設定はコマンドラインオプションではなく、下の「設定」セクションの定数を書き換える。
標準ライブラリのみで動作するため、追加インストールは不要。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform != "win32":
    sys.exit(
        "このスクリプトは Windows 上で実行してください。\n"
        "WSL からは:  powershell.exe -NoProfile -Command \"pythonw ime_cursor.pyw\""
    )

# =================================================================== 設定
# 表示を変えたいときは、以下の定数を書き換える。

# カーソルからの表示オフセット (px)。負の値にすればカーソルの左上に出せる
OFFSET_X = 20
OFFSET_Y = 20

# 位置と状態の更新間隔 (ミリ秒)。小さいほど追従が滑らかで、CPU 使用率は上がる
INTERVAL_MS = 30

# バッジの文字サイズ (px) と内側の余白 (px)
FONT_SIZE = 16
PAD_X = 6
PAD_Y = 1

# 不透明度 (0.0 = 透明, 1.0 = 不透明)
ALPHA = 0.85

# True にすると、半角英数・直接入力のときはバッジを隠す
# (日本語入力中だけ表示したい場合に使う)
HIDE_ALNUM = False

# True にすると「あ ひらがな」のように説明も表示する
VERBOSE = False

# 使用するフォント。先頭から順に探し、見つかったものを使う
FONT_CANDIDATES = ("Yu Gothic UI", "游ゴシック", "Meiryo UI", "Meiryo", "BIZ UDGothic")

# IME の状態ごとの (背景色, 文字色)
PALETTE = {
    "hiragana": ("#d32f2f", "#ffffff"),    # あ  ひらがな
    "kana": ("#f57c00", "#ffffff"),        # カ  カタカナ
    "alnum": ("#37474f", "#ffffff"),       # A   半角英数 / 直接入力
    "alnum-full": ("#00796b", "#ffffff"),  # Ａ  全角英数
    "unknown": ("#6a1b9a", "#ffffff"),     # ?   取得できず
}

# True にすると GUI を出さず、IME の状態をコンソールに出力し続ける (デバッグ用)。
# pythonw では print が捨てられるため、python コマンドで起動すること
DEBUG_CONSOLE = False


# ---------------------------------------------------------------- Win32 定義

user32 = ctypes.WinDLL("user32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)

WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 0x0001
IMC_GETOPENSTATUS = 0x0005

IME_CMODE_ALPHANUMERIC = 0x0000
IME_CMODE_NATIVE = 0x0001
IME_CMODE_KATAKANA = 0x0002
IME_CMODE_FULLSHAPE = 0x0008
IME_CMODE_ROMAN = 0x0010

SMTO_ABORTIFHUNG = 0x0002

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

LANG_JAPANESE = 0x11


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
imm32.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]
imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND

_GetWindowLong = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_SetWindowLong = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
_GetWindowLong.restype = ctypes.c_ssize_t
_SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_SetWindowLong.restype = ctypes.c_ssize_t


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


# ---------------------------------------------------------------- IME 状態取得

def _ime_target_hwnd() -> int:
    """入力フォーカスを持つウィンドウ (無ければ前面ウィンドウ) を返す。"""
    fg = user32.GetForegroundWindow()
    if not fg:
        return 0
    tid = user32.GetWindowThreadProcessId(fg, None)
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if tid and user32.GetGUIThreadInfo(tid, ctypes.byref(info)) and info.hwndFocus:
        return info.hwndFocus
    return fg


def _ime_query(ime_wnd: int, command: int) -> int | None:
    result = ctypes.c_size_t(0)
    ok = user32.SendMessageTimeoutW(
        ime_wnd, WM_IME_CONTROL, command, 0, SMTO_ABORTIFHUNG, 120, ctypes.byref(result)
    )
    return None if not ok else int(result.value)


def _keyboard_layout_langid() -> int:
    fg = user32.GetForegroundWindow()
    tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    hkl = user32.GetKeyboardLayout(tid)
    return hkl & 0xFFFF if hkl else 0


def _query_open_and_mode() -> tuple[int, int] | None:
    """フォーカス側 → 前面ウィンドウ側の順に IME へ問い合わせる。"""
    fg = user32.GetForegroundWindow()
    candidates: list[int] = []
    focus = _ime_target_hwnd()
    if focus:
        candidates.append(focus)
    if fg and fg not in candidates:
        candidates.append(fg)

    for hwnd in candidates:
        ime_wnd = imm32.ImmGetDefaultIMEWnd(hwnd)
        if not ime_wnd:
            continue
        is_open = _ime_query(ime_wnd, IMC_GETOPENSTATUS)
        if is_open is None:
            continue
        mode = _ime_query(ime_wnd, IMC_GETCONVERSIONMODE) or 0
        return int(is_open), int(mode)
    return None


# 取得に一時的に失敗しても直前の状態を保持し、表示のちらつきを防ぐ
_STICKY_LIMIT = 8
_last_good: dict | None = None
_miss_count = 0


def get_ime_state() -> dict:
    """現在の IME 状態を dict で返す。

    key: 'label'(短い表示) / 'text'(説明) / 'kind'(色分け用) / 'open' / 'mode'
    """
    global _last_good, _miss_count

    langid = _keyboard_layout_langid() & 0x3FF
    queried = _query_open_and_mode()

    if queried is None:
        _miss_count += 1
        if _last_good is not None and _miss_count <= _STICKY_LIMIT:
            return _last_good
        return _state("?", "IME 不明", "unknown", None, None)

    _miss_count = 0
    is_open, mode = queried

    if not is_open:
        # 日本語 IME 以外のレイアウト (英語配列など) もここに来る
        text = "直接入力" if langid == LANG_JAPANESE else "英字入力"
        _last_good = _state("A", text, "alnum", 0, mode)
        return _last_good

    native = bool(mode & IME_CMODE_NATIVE)
    katakana = bool(mode & IME_CMODE_KATAKANA)
    full = bool(mode & IME_CMODE_FULLSHAPE)

    if native and katakana and full:
        label, text, kind = "カ", "全角カタカナ", "kana"
    elif native and katakana:
        label, text, kind = "ｶ", "半角カタカナ", "kana"
    elif native and full:
        label, text, kind = "あ", "ひらがな", "hiragana"
    elif native:
        label, text, kind = "ｱ", "半角ひらがな", "kana"
    elif full:
        label, text, kind = "Ａ", "全角英数", "alnum-full"
    else:
        label, text, kind = "A", "半角英数", "alnum"

    _last_good = _state(label, text, kind, 1, mode)
    return _last_good


def _state(label: str, text: str, kind: str, open_: int | None, mode: int | None) -> dict:
    return {"label": label, "text": text, "kind": kind, "open": open_, "mode": mode}


# ---------------------------------------------------------------- オーバーレイ

class ImeCursorOverlay:
    def __init__(self) -> None:
        import tkinter as tk
        import tkinter.font as tkfont

        self.running = True
        self.last_key: tuple | None = None

        self.root = tk.Tk()
        self.root.withdraw()

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", ALPHA)
        self.win.configure(bg=PALETTE["alnum"][0])

        # 日本語対応フォントを優先
        families = set(tkfont.families())
        family = next((f for f in FONT_CANDIDATES if f in families), FONT_CANDIDATES[-1])
        self.font = tkfont.Font(family=family, size=-FONT_SIZE, weight="bold")

        self.label = tk.Label(
            self.win,
            text="A",
            font=self.font,
            bg=PALETTE["alnum"][0],
            fg=PALETTE["alnum"][1],
            padx=PAD_X,
            pady=PAD_Y,
            bd=0,
        )
        self.label.pack()

        self.win.update_idletasks()
        self._make_click_through()

        self.root.protocol("WM_DELETE_WINDOW", self.stop)
        self.tick()

    # -- Win32 まわり ------------------------------------------------------
    def _hwnd(self) -> int:
        hwnd = user32.GetParent(self.win.winfo_id())
        return hwnd or self.win.winfo_id()

    def _make_click_through(self) -> None:
        hwnd = self._hwnd()
        style = _GetWindowLong(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        _SetWindowLong(hwnd, GWL_EXSTYLE, style)

    # -- メインループ ------------------------------------------------------
    def tick(self) -> None:
        if not self.running:
            return

        state = get_ime_state()
        if HIDE_ALNUM and state["kind"] in ("alnum", "unknown"):
            self.win.withdraw()
        else:
            text = f"{state['label']} {state['text']}" if VERBOSE else state["label"]
            key = (text, state["kind"])
            if key != self.last_key:
                bg, fg = PALETTE.get(state["kind"], PALETTE["unknown"])
                self.label.configure(text=text, bg=bg, fg=fg)
                self.win.configure(bg=bg)
                self.last_key = key
                self.win.update_idletasks()
            if not self.win.winfo_viewable():
                self.win.deiconify()
                self.win.attributes("-topmost", True)
            self._move_to_cursor()

        self.root.after(INTERVAL_MS, self.tick)

    def _move_to_cursor(self) -> None:
        pt = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return
        w = self.win.winfo_width() or 1
        h = self.win.winfo_height() or 1
        x = pt.x + OFFSET_X
        y = pt.y + OFFSET_Y

        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        x = min(max(x, vx), vx + vw - w)
        y = min(max(y, vy), vy + vh - h)

        self.win.geometry(f"+{int(x)}+{int(y)}")

    def stop(self) -> None:
        self.running = False
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.stop()


# ---------------------------------------------------------------- エントリ

def console_monitor() -> None:
    import time

    last = None
    print("IME 状態を監視中 (Ctrl+C で終了)")
    while True:
        s = get_ime_state()
        key = (s["label"], s["text"], s["mode"])
        if key != last:
            mode = "-" if s["mode"] is None else f"0x{s['mode']:02x}"
            print(f"{s['label']:<2} {s['text']:<8} open={s['open']} mode={mode}", flush=True)
            last = key
        time.sleep(0.1)


def main() -> int:
    enable_dpi_awareness()

    if DEBUG_CONSOLE:
        try:
            console_monitor()
        except KeyboardInterrupt:
            pass
        return 0

    try:
        import tkinter  # noqa: F401
    except ImportError:
        # pythonw では stderr が None なのでダイアログで知らせる
        ctypes.windll.user32.MessageBoxW(
            None, "tkinter が見つかりません。tkinter 同梱の Python で実行してください。",
            "ime_cursor", 0x10)
        return 1

    ImeCursorOverlay().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
