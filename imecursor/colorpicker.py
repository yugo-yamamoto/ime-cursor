"""色を選ぶ小さなポップアップ。

管理画面には「いまの色」を 16 進で出すラベルだけを置き、そこをクリックすると
これが開く。色見本ボタンを機能ごとに並べるとパネルが色ボタンで埋まるため、
選択肢はこのポップアップの中にまとめている。

ロジックは ColorPopup のメソッドに置き、ask_color は薄いラッパーにしてある。
こうしておくと、テストから show() を呼ばずにインスタンスを作り、入力欄を
差し替えて _on_ok() を叩いて result を確かめられる。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, ttk

from .config import contrast_fg, normalize_hex_color

# 色見本と、入力中の色を映すパッチの幅 (文字数)
_SWATCH_WIDTH = 3
_PATCH_WIDTH = 10

# ポップアップをクリック元からずらす量 (px)
_OFFSET_Y = 8


class ColorPopup:
    """16 進の直接入力と色見本を持つ、色選択のポップアップ。

    allow_none=True のときは「変更しない」も選べる (マウスカーソルの色用)。

    result は (変更したか, 色) で、色は "#rrggbb" か None。まだ閉じていない
    あいだは None。
    """

    def __init__(self, parent: tk.Misc, current: str | None,
                 presets: tuple[tuple[str, str], ...], *, title: str,
                 allow_none: bool = False, none_label: str = "変更しない",
                 near: tk.Misc | None = None) -> None:
        self.result: tuple[bool, str | None] | None = None
        self._allow_none = allow_none

        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.resizable(False, False)
        self.win.transient(parent.winfo_toplevel())
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        outer = ttk.Frame(self.win, padding=12)
        outer.pack(fill="both", expand=True)

        # -- 色見本。押したらその色で即確定する (プリセットは 1 クリックで済ませる)
        swatches = ttk.Frame(outer)
        swatches.pack(fill="x")
        self.preset_buttons: list[tk.Button] = []
        for label, color in presets:
            button = tk.Button(
                swatches, text=" ", bg=color, activebackground=color,
                width=_SWATCH_WIDTH, bd=1, relief="raised",
                command=lambda c=color: self._on_preset(c),
            )
            button.pack(side="left", padx=(0, 3))
            self.preset_buttons.append(button)

        # -- 16 進の直接入力
        entry_row = ttk.Frame(outer)
        entry_row.pack(fill="x", pady=(12, 0))
        ttk.Label(entry_row, text="16 進").pack(side="left")
        self.var_hex = tk.StringVar(value=current or "#ff0000")
        self.entry = ttk.Entry(entry_row, textvariable=self.var_hex, width=12)
        self.entry.pack(side="left", padx=(6, 8))
        self.patch = tk.Label(entry_row, text="", width=_PATCH_WIDTH, bd=2,
                              relief="groove")
        self.patch.pack(side="left")
        self.entry.bind("<KeyRelease>", lambda _e: self._refresh_patch())

        self.notice = ttk.Label(outer, text="")
        self.notice.pack(anchor="w", pady=(6, 0))

        # -- ボタン
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="詳しく…", command=self._on_detail).pack(side="left")
        if allow_none:
            self.none_button = ttk.Button(buttons, text=none_label,
                                          command=self._on_none)
            self.none_button.pack(side="left", padx=(6, 0))
        else:
            self.none_button = None
        ttk.Button(buttons, text="取消", command=self._on_cancel).pack(side="right")
        ttk.Button(buttons, text="OK", command=self._on_ok).pack(side="right", padx=(0, 6))

        self.win.bind("<Return>", lambda _e: self._on_ok())
        self.win.bind("<Escape>", lambda _e: self._on_cancel())

        self._refresh_patch()
        self._place_near(near or parent)

    # ---------------------------------------------------------------- 表示
    def _place_near(self, widget: tk.Misc) -> None:
        """クリック元のすぐ下に出す。画面からはみ出さないように寄せる。"""
        self.win.update_idletasks()
        try:
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height() + _OFFSET_Y
        except tk.TclError:
            return
        width = self.win.winfo_reqwidth()
        height = self.win.winfo_reqheight()
        x = max(0, min(x, self.win.winfo_screenwidth() - width))
        y = max(0, min(y, self.win.winfo_screenheight() - height))
        self.win.geometry(f"+{int(x)}+{int(y)}")

    def show(self) -> tuple[bool, str | None]:
        """閉じるまで待って結果を返す。"""
        self.entry.focus_set()
        self.entry.selection_range(0, "end")
        self.win.grab_set()
        self.win.wait_window()
        return self.result or (False, None)

    # ---------------------------------------------------------------- 中身
    def _refresh_patch(self) -> None:
        """入力中の値を見本パッチに映す。不正なら注意文を出す。"""
        color = normalize_hex_color(self.var_hex.get())
        if color:
            self.patch.configure(text=color.upper(), bg=color, fg=contrast_fg(color))
            self.notice.configure(text="")
        else:
            self.patch.configure(text="?", bg="#f0f0f0", fg="#000000")
            self.notice.configure(text="#RRGGBB の形で入れてください（例: #ff0000）")

    def _close(self, result: tuple[bool, str | None]) -> None:
        self.result = result
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()

    # ---------------------------------------------------------------- 操作
    def _on_preset(self, color: str) -> None:
        self.var_hex.set(color)
        self._refresh_patch()
        self._close((True, color))

    def _on_detail(self) -> None:
        current = normalize_hex_color(self.var_hex.get()) or "#ff0000"
        _rgb, picked = colorchooser.askcolor(color=current, parent=self.win)
        if picked:
            self.var_hex.set(str(picked).lower())
            self._refresh_patch()

    def _on_none(self) -> None:
        self._close((True, None))

    def _on_ok(self) -> None:
        color = normalize_hex_color(self.var_hex.get())
        if color is None:
            self._refresh_patch()  # 注意文を出したまま閉じない
            self.entry.focus_set()
            return
        self._close((True, color))

    def _on_cancel(self) -> None:
        self._close((False, None))


def ask_color(parent: tk.Misc, current: str | None,
              presets: tuple[tuple[str, str], ...], **kwargs) -> tuple[bool, str | None]:
    """ColorPopup を出して結果を返す。(変更したか, 色)。"""
    return ColorPopup(parent, current, presets, **kwargs).show()
