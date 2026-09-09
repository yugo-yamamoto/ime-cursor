"""マウスカーソルに追従して IME の状態を出すバッジ。

tkinter のトップレベルウィンドウに、以下の拡張スタイルを付けている。

    WS_EX_LAYERED      半透明表示
    WS_EX_TRANSPARENT  クリックスルー (マウス操作を透過させる)
    WS_EX_NOACTIVATE   クリックされてもフォーカスを奪わない
    WS_EX_TOOLWINDOW   Alt+Tab とタスクバーに出さない
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from .config import FONT_CANDIDATES, PALETTE, Config
from .imestate import ImeState, ImeWatcher
from .win32 import (
    GWL_EXSTYLE,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TRANSPARENT,
    GetWindowLong,
    SetWindowLong,
    cursor_pixel_size,
    user32,
    virtual_screen,
)
import ctypes
from ctypes import wintypes

# バッジを止めているときの見張り間隔 (ミリ秒)。IME への問い合わせはしない
IDLE_INTERVAL_MS = 200

# offset_* は 32px のカーソルを前提にした値。それより大きいカーソルでは
# バッジがカーソルの下に隠れるので、この比率で押し出す
BASE_CURSOR_SIZE = 32


def pick_font_family() -> str:
    """日本語が出るフォントを選ぶ。欧文フォントにフォールバックさせない。"""
    families = set(tkfont.families())
    return next((f for f in FONT_CANDIDATES if f in families), FONT_CANDIDATES[-1])


class Overlay:
    """カーソル追従バッジ。管理画面から表示のオン / オフを切り替えられる。"""

    def __init__(self, root: tk.Tk, config: Config) -> None:
        self.root = root
        self.config = config
        self.watcher = ImeWatcher()
        self.running = True
        self._last_key: tuple | None = None
        self._last_state: ImeState | None = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", config.alpha)
        self.win.configure(bg=PALETTE["alnum"][0])
        self.win.withdraw()

        self.font = tkfont.Font(
            family=pick_font_family(), size=-config.font_size, weight="bold"
        )
        self.label = tk.Label(
            self.win,
            text="A",
            font=self.font,
            bg=PALETTE["alnum"][0],
            fg=PALETTE["alnum"][1],
            padx=6,
            pady=1,
            bd=0,
        )
        self.label.pack()

        self.win.update_idletasks()
        self._make_click_through()
        self.tick()

    # -- 状態 --------------------------------------------------------------
    @property
    def last_state(self) -> ImeState | None:
        """管理画面が「いまの IME」を表示するために覗く。"""
        return self._last_state

    def apply_config(self) -> None:
        """管理画面で設定が変わったあとに呼ぶ。"""
        self.font.configure(size=-self.config.font_size)
        self.win.attributes("-alpha", self.config.alpha)
        self._last_key = None  # 次の tick で色と文字を貼り直させる
        if not self.config.badge_enabled:
            self.win.withdraw()

    # -- Win32 まわり ------------------------------------------------------
    def _hwnd(self) -> int:
        hwnd = user32.GetParent(self.win.winfo_id())
        return hwnd or self.win.winfo_id()

    def _make_click_through(self) -> None:
        hwnd = self._hwnd()
        style = GetWindowLong(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        SetWindowLong(hwnd, GWL_EXSTYLE, style)

    # -- メインループ ------------------------------------------------------
    def tick(self) -> None:
        if not self.running:
            return

        if not self.config.badge_enabled:
            if self.win.winfo_viewable():
                self.win.withdraw()
            self.root.after(IDLE_INTERVAL_MS, self.tick)
            return

        state = self.watcher.read()
        self._last_state = state

        if self.config.hide_alnum and state.kind in ("alnum", "unknown"):
            self.win.withdraw()
        else:
            text = f"{state.label} {state.text}" if self.config.verbose else state.label
            key = (text, state.kind)
            if key != self._last_key:
                bg, fg = PALETTE.get(state.kind, PALETTE["unknown"])
                self.label.configure(text=text, bg=bg, fg=fg)
                self.win.configure(bg=bg)
                self._last_key = key
                self.win.update_idletasks()
            if not self.win.winfo_viewable():
                self.win.deiconify()
                self.win.attributes("-topmost", True)
            self._move_to_cursor()

        self.root.after(self.config.interval_ms, self.tick)

    def _offsets(self) -> tuple[int, int]:
        if not self.config.follow_cursor_size:
            return self.config.offset_x, self.config.offset_y
        ratio = max(1.0, cursor_pixel_size() / BASE_CURSOR_SIZE)
        return round(self.config.offset_x * ratio), round(self.config.offset_y * ratio)

    def _move_to_cursor(self) -> None:
        pt = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return
        w = self.win.winfo_width() or 1
        h = self.win.winfo_height() or 1
        off_x, off_y = self._offsets()

        vx, vy, vw, vh = virtual_screen()
        x = min(max(pt.x + off_x, vx), vx + vw - w)
        y = min(max(pt.y + off_y, vy), vy + vh - h)
        self.win.geometry(f"+{int(x)}+{int(y)}")

    def stop(self) -> None:
        self.running = False
        try:
            self.win.destroy()
        except Exception:
            pass
