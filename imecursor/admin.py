"""管理画面 (tkinter)。

- IME モード表示のオン / オフ
- マウスカーソルの色
- マウスカーソルのサイズ

変更するとその場で適用し、設定ファイルにも書き込む。何をしたかは下部の
ログ欄に出るので、うまく反映されないときはログをコピーして持ち出せる。
"""

from __future__ import annotations

import re
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, messagebox, ttk

from . import cursortheme
from .config import (
    COLOR_PRESETS,
    CURSOR_SIZE_MAX,
    CURSOR_SIZE_MIN,
    MARKER_COLOR_PRESETS,
    MARKER_WIDTH_MAX,
    MARKER_WIDTH_MIN,
    PALETTE,
    Config,
    config_path,
    hex_to_rgb,
)
from .marker import Marker
from .overlay import Overlay, pick_font_family
from .win32 import cursor_pixel_size

# サイズのショートカット。Windows の設定画面のスライダーに近い刻み
SIZE_PRESETS = (32, 48, 64, 96, 128, 192, 256)

# サイズのスライダーの刻み (px)
SIZE_STEP = 8

# 「いまの IME」表示の更新間隔 (ミリ秒)
STATUS_INTERVAL_MS = 200

# ログ欄に残す最大行数
LOG_MAX_LINES = 500

DEFAULT_COLOR = "#00a0ff"

# 管理画面の位置だけを表すジオメトリ。マルチモニタで原点が負のときは
# Tk が "+-1920+0" の形を返すので、符号の重なりも許す
_POSITION_ONLY = re.compile(r"[+-]-?\d+[+-]-?\d+")


def _contrast_fg(color: str) -> str:
    """背景色に対して読める文字色 (白か黒) を返す。"""
    r, g, b = hex_to_rgb(color)
    return "#000000" if (r * 77 + g * 151 + b * 28) >> 8 > 140 else "#ffffff"


class AdminWindow:
    """常駐プロセスに 1 つだけ存在する管理画面。閉じても常駐は続く。"""

    def __init__(self, root: tk.Tk, config: Config, overlay: Overlay,
                 marker: Marker, on_quit) -> None:
        self.root = root
        self.config = config
        self.overlay = overlay
        self.marker = marker
        self.on_quit = on_quit
        self._suppress = True  # 初期化中の trace で適用処理を走らせない

        family = pick_font_family()
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=family, size=10)
            except tk.TclError:
                pass
        self.mono = tkfont.Font(family="Consolas", size=9)

        self.win = tk.Toplevel(root)
        self.win.title("ime_cursor 管理画面")
        self.win.resizable(False, True)
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        # 覚えておくのは位置だけ。サイズまで復元すると、セクションが増えた
        # あとの起動で中身がはみ出して切れてしまう
        if _POSITION_ONLY.fullmatch(config.admin_geometry or ""):
            try:
                self.win.geometry(config.admin_geometry)
            except tk.TclError:
                pass

        self._build()
        self._suppress = False
        self._sync_widgets()
        self._poll_status()

        self.log(f"設定ファイル: {config_path()}")
        state = cursortheme.current_state()
        self.log(
            f"起動時のカーソル: CursorBaseSize={state['base_size']} / "
            f"このプロセスから見た実寸={cursor_pixel_size()}px / "
            f"CursorType={state['cursor_type']}"
        )

    # ================================================================ 組み立て
    def _build(self) -> None:
        outer = ttk.Frame(self.win, padding=10)
        outer.pack(fill="both", expand=True)

        self._build_badge_section(outer)
        self._build_marker_section(outer)
        self._build_color_section(outer)
        self._build_size_section(outer)
        self._build_footer(outer)
        self._build_log_section(outer)

    # -- IME モード表示 ----------------------------------------------------
    def _build_badge_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text=" IME モード表示 ", padding=10)
        box.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(box)
        row.pack(fill="x")

        self.badge_button = ttk.Button(row, text="", width=22, command=self.toggle_badge)
        self.badge_button.pack(side="left")

        self.badge_status = tk.Label(row, text="", width=10, padx=8, pady=4, bd=1,
                                     relief="solid")
        self.badge_status.pack(side="left", padx=8)

        ttk.Label(row, text="いまの IME:").pack(side="left", padx=(8, 4))
        self.ime_status = tk.Label(row, text="―", width=14, padx=8, pady=4, bd=1,
                                   relief="solid", anchor="w")
        self.ime_status.pack(side="left")

        opts = ttk.Frame(box)
        opts.pack(fill="x", pady=(10, 0))

        self.var_hide_alnum = tk.BooleanVar(value=self.config.hide_alnum)
        self.var_verbose = tk.BooleanVar(value=self.config.verbose)
        ttk.Checkbutton(opts, text="半角英数・直接入力のときは隠す",
                        variable=self.var_hide_alnum,
                        command=self._on_badge_option).pack(side="left")
        ttk.Checkbutton(opts, text="説明も出す（あ ひらがな）",
                        variable=self.var_verbose,
                        command=self._on_badge_option).pack(side="left", padx=(16, 0))

        size_row = ttk.Frame(box)
        size_row.pack(fill="x", pady=(8, 0))
        ttk.Label(size_row, text="文字サイズ").pack(side="left")
        self.var_font_size = tk.IntVar(value=self.config.font_size)
        ttk.Spinbox(size_row, from_=8, to=72, width=5, textvariable=self.var_font_size,
                    command=self._on_badge_option).pack(side="left", padx=(6, 2))
        ttk.Label(size_row, text="px").pack(side="left")

        ttk.Label(size_row, text="不透明度").pack(side="left", padx=(16, 6))
        self.var_alpha = tk.IntVar(value=round(self.config.alpha * 100))
        ttk.Spinbox(size_row, from_=10, to=100, increment=5, width=5,
                    textvariable=self.var_alpha,
                    command=self._on_badge_option).pack(side="left", padx=(0, 2))
        ttk.Label(size_row, text="%").pack(side="left")

    # -- プレゼン用マーカー ------------------------------------------------
    def _build_marker_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text=" プレゼン用マーカー（矩形） ", padding=10)
        box.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(box)
        row.pack(fill="x")
        self.marker_button = ttk.Button(row, text="", width=22, command=self.toggle_marker)
        self.marker_button.pack(side="left")
        self.marker_status = tk.Label(row, text="", width=10, padx=8, pady=4, bd=1,
                                      relief="solid")
        self.marker_status.pack(side="left", padx=8)
        self.marker_count = ttk.Label(row, text="", width=12)
        self.marker_count.pack(side="left", padx=(4, 0))
        ttk.Button(row, text="枠を消す", command=self.clear_marker).pack(side="left")

        self.marker_hotkey_label = ttk.Label(box, text="")
        self.marker_hotkey_label.pack(anchor="w", pady=(8, 0))

        swatches = ttk.Frame(box)
        swatches.pack(fill="x", pady=(8, 0))
        for label, color in MARKER_COLOR_PRESETS:
            tk.Button(
                swatches, text=label, bg=color, fg=_contrast_fg(color),
                activebackground=color, width=7, bd=1, relief="raised",
                command=lambda c=color: self.set_marker_color(c),
            ).pack(side="left", padx=(0, 4))
        ttk.Button(swatches, text="色を選ぶ…",
                   command=self.choose_marker_color).pack(side="left", padx=(4, 0))

        opts = ttk.Frame(box)
        opts.pack(fill="x", pady=(8, 0))
        ttk.Label(opts, text="線の太さ").pack(side="left")
        self.var_marker_width = tk.IntVar(value=self.config.marker_width)
        ttk.Spinbox(opts, from_=MARKER_WIDTH_MIN, to=MARKER_WIDTH_MAX, width=5,
                    textvariable=self.var_marker_width,
                    command=self._on_marker_option).pack(side="left", padx=(6, 2))
        ttk.Label(opts, text="px").pack(side="left")
        ttk.Label(opts, text="いまの色:").pack(side="left", padx=(16, 4))
        self.marker_preview = tk.Label(opts, text="", width=12, padx=8, pady=4, bd=2,
                                       relief="groove")
        self.marker_preview.pack(side="left")

    # -- マウスカーソルの色 ------------------------------------------------
    def _build_color_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text=" マウスカーソルの色 ", padding=10)
        box.pack(fill="x", pady=(0, 8))

        self.var_color_mode = tk.StringVar(
            value="custom" if self.config.cursor_color else "system"
        )
        ttk.Radiobutton(box, text="変更しない（Windows の設定のまま）",
                        value="system", variable=self.var_color_mode,
                        command=self._on_color_mode).pack(anchor="w")
        ttk.Radiobutton(box, text="色を指定する", value="custom",
                        variable=self.var_color_mode,
                        command=self._on_color_mode).pack(anchor="w")

        swatches = ttk.Frame(box)
        swatches.pack(fill="x", pady=(8, 0))
        for label, color in COLOR_PRESETS:
            tk.Button(
                swatches, text=label, bg=color, fg=_contrast_fg(color),
                activebackground=color, width=7, bd=1, relief="raised",
                command=lambda c=color: self.set_cursor_color(c),
            ).pack(side="left", padx=(0, 4))

        row = ttk.Frame(box)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="色を選ぶ…", command=self.choose_cursor_color).pack(side="left")
        ttk.Label(row, text="いまの色:").pack(side="left", padx=(12, 4))
        self.color_preview = tk.Label(row, text="", width=20, padx=8, pady=4, bd=2,
                                      relief="groove")
        self.color_preview.pack(side="left")

    # -- マウスカーソルのサイズ --------------------------------------------
    def _build_size_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text=" マウスカーソルのサイズ ", padding=10)
        box.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(box)
        row.pack(fill="x")
        self.var_size = tk.IntVar(value=self.config.cursor_size)
        self.size_scale = tk.Scale(
            row, from_=CURSOR_SIZE_MIN, to=CURSOR_SIZE_MAX, resolution=SIZE_STEP,
            orient="horizontal", variable=self.var_size, showvalue=False, length=320,
            highlightthickness=0, takefocus=True,
        )
        self.size_scale.pack(side="left")
        # ドラッグ中は適用しない (離したときだけレジストリに書く)
        self.size_scale.bind("<ButtonRelease-1>", lambda _e: self.apply_cursor_size())
        self.size_scale.bind("<KeyRelease>", lambda _e: self.apply_cursor_size())

        self.size_value = ttk.Label(row, text="", width=8)
        self.size_value.pack(side="left", padx=(10, 0))

        presets = ttk.Frame(box)
        presets.pack(fill="x", pady=(8, 0))
        ttk.Label(presets, text="よく使うサイズ:").pack(side="left", padx=(0, 6))
        for size in SIZE_PRESETS:
            ttk.Button(presets, text=str(size), width=5,
                       command=lambda s=size: self.set_cursor_size(s)).pack(
                           side="left", padx=(0, 3))

    # -- 下部 --------------------------------------------------------------
    def _build_footer(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=4, pady=(2, 10))
        ttk.Button(row, text="カーソルを既定に戻す",
                   command=self.restore_cursor_default).pack(side="left")
        ttk.Button(row, text="管理画面を閉じて常駐",
                   command=self.hide).pack(side="right")
        ttk.Button(row, text="終了", command=self.quit).pack(side="right", padx=(0, 6))

    def _build_log_section(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text=" ログ ", padding=8)
        box.pack(fill="both", expand=True)

        wrap = ttk.Frame(box)
        wrap.pack(fill="both", expand=True)
        self.log_text = tk.Text(wrap, height=6, width=64, font=self.mono, wrap="word",
                                state="disabled", bd=1, relief="solid")
        self.log_text.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.log_text.yview)
        bar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=bar.set)

        row = ttk.Frame(box)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="ログをコピー", command=self.copy_log).pack(side="left")
        ttk.Button(row, text="クリア", command=self.clear_log).pack(side="left", padx=6)
        self.copy_hint = ttk.Label(row, text="")
        self.copy_hint.pack(side="left", padx=6)

    # ================================================================ ログ
    def log(self, message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        extra = int(self.log_text.index("end-1c").split(".")[0]) - LOG_MAX_LINES
        if extra > 0:
            self.log_text.delete("1.0", f"{extra + 1}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def copy_log(self) -> None:
        text = self.log_text.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.copy_hint.configure(text=f"{len(text.splitlines())} 行コピーしました")
        self.win.after(2500, lambda: self.copy_hint.configure(text=""))

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ================================================================ 操作
    def toggle_badge(self) -> None:
        self.config.badge_enabled = not self.config.badge_enabled
        self.overlay.apply_config()
        self._sync_widgets()
        self._save()
        self.log("IME モード表示を "
                 + ("開始しました（マウスカーソルの近くに出ます）"
                    if self.config.badge_enabled else "停止しました"))

    def _on_badge_option(self) -> None:
        if self._suppress:
            return
        self.config.hide_alnum = bool(self.var_hide_alnum.get())
        self.config.verbose = bool(self.var_verbose.get())
        try:
            self.config.font_size = int(self.var_font_size.get())
            self.config.alpha = int(self.var_alpha.get()) / 100
        except (tk.TclError, ValueError):
            pass
        self.config.clamp()
        self.overlay.apply_config()
        self._save()
        self.log(
            f"バッジ設定を更新: 隠す={self.config.hide_alnum} "
            f"説明={self.config.verbose} 文字={self.config.font_size}px "
            f"不透明度={round(self.config.alpha * 100)}%"
        )

    # -- マーカー ----------------------------------------------------------
    def toggle_marker(self) -> None:
        self.marker.toggle()
        self._sync_widgets()

    def clear_marker(self) -> None:
        removed = self.marker.clear()
        self.log(f"マーカーの枠 {removed} 個を消しました")
        self._sync_widgets()

    def set_marker_color(self, color: str) -> None:
        self.config.marker_color = color
        self.config.clamp()
        self.marker.apply_config()
        self._save()
        self._sync_widgets()
        self.log(f"マーカーの色を {self.config.marker_color} にしました")

    def choose_marker_color(self) -> None:
        _rgb, picked = colorchooser.askcolor(color=self.config.marker_color,
                                             parent=self.win, title="マーカーの色")
        if picked:
            self.set_marker_color(picked.lower())

    def _on_marker_option(self) -> None:
        if self._suppress:
            return
        try:
            self.config.marker_width = int(self.var_marker_width.get())
        except (tk.TclError, ValueError):
            return
        self.config.clamp()
        self.marker.apply_config()
        self._save()
        self._sync_widgets()
        self.log(f"マーカーの線の太さを {self.config.marker_width}px にしました")

    # -- 色 ----------------------------------------------------------------
    def _on_color_mode(self) -> None:
        if self._suppress:
            return
        if self.var_color_mode.get() == "system":
            self.config.cursor_color = None
            self._apply_cursor("カーソル色を Windows の設定に戻します")
        else:
            self.set_cursor_color(self.config.cursor_color or DEFAULT_COLOR)

    def set_cursor_color(self, color: str) -> None:
        self.config.cursor_color = color
        self.var_color_mode.set("custom")
        self._apply_cursor(f"カーソル色を {color} にします")

    def choose_cursor_color(self) -> None:
        initial = self.config.cursor_color or DEFAULT_COLOR
        _rgb, picked = colorchooser.askcolor(color=initial, parent=self.win,
                                             title="マウスカーソルの色")
        if picked:
            self.set_cursor_color(picked.lower())

    # -- サイズ ------------------------------------------------------------
    def set_cursor_size(self, size: int) -> None:
        self.var_size.set(size)
        self.apply_cursor_size()

    def apply_cursor_size(self) -> None:
        if self._suppress:
            return
        size = int(self.var_size.get())
        if size == self.config.cursor_size:
            self._sync_widgets()
            return
        self.config.cursor_size = size
        self._apply_cursor(f"カーソルサイズを {size}px にします")

    # -- 共通 --------------------------------------------------------------
    def _apply_cursor(self, headline: str) -> None:
        self.log(headline)
        self.win.configure(cursor="watch")
        self.win.update_idletasks()
        try:
            cursortheme.apply(self.config, log=self.log)
        except Exception as exc:  # レジストリ書き込みや生成の失敗を握りつぶさない
            self.log(f"失敗: {type(exc).__name__}: {exc}")
            messagebox.showerror("ime_cursor", f"カーソル設定を適用できませんでした。\n\n{exc}",
                                 parent=self.win)
        finally:
            self.win.configure(cursor="")
        self.overlay.apply_config()
        self._sync_widgets()
        self._save()

    def restore_cursor_default(self) -> None:
        self.log("カーソルの色とサイズを既定に戻します")
        try:
            cursortheme.restore_default(self.config, log=self.log)
        except Exception as exc:
            self.log(f"失敗: {type(exc).__name__}: {exc}")
        self.var_color_mode.set("system")
        self.var_size.set(self.config.cursor_size)
        self._sync_widgets()
        self._save()

    def _save(self) -> None:
        try:
            # サイズは捨てて位置だけ残す (中身に合わせた高さを毎回使う)
            self.config.admin_geometry = re.sub(r"^\d+x\d+", "", self.win.geometry())
        except tk.TclError:
            pass
        try:
            self.config.save()
        except OSError as exc:
            self.log(f"設定を保存できませんでした: {exc}")

    # ================================================================ 表示更新
    def _sync_widgets(self) -> None:
        on = self.config.badge_enabled
        self.badge_button.configure(text="IME モード表示を停止" if on else "IME モード表示を開始")
        self.badge_status.configure(
            text="表示中" if on else "停止中",
            bg="#2e7d32" if on else "#9e9e9e",
            fg="#ffffff",
        )

        marker_on = self.marker.active
        self.marker_button.configure(
            text="マーカーを停止" if marker_on else "マーカーを開始"
        )
        self.marker_status.configure(
            text="描画中" if marker_on else "停止中",
            bg="#c62828" if marker_on else "#9e9e9e",
            fg="#ffffff",
        )
        self.marker_count.configure(text=f"枠 {self.marker.shape_count()} 個")
        error = self.marker.hotkey_error()
        self.marker_hotkey_label.configure(
            text=f"ショートカット: {self.marker.hotkey_label()}"
                 + (f" — 登録できません（{error}）" if error else "（登録済み）")
        )
        marker_color = self.config.marker_color
        self.marker_preview.configure(text=marker_color.upper(), bg=marker_color,
                                      fg=_contrast_fg(marker_color))
        if int(self.var_marker_width.get() or 0) != self.config.marker_width:
            self.var_marker_width.set(self.config.marker_width)

        color = self.config.cursor_color
        if color:
            self.color_preview.configure(text=color.upper(), bg=color, fg=_contrast_fg(color))
        else:
            self.color_preview.configure(text="Windows の設定のまま", bg="#f0f0f0",
                                         fg="#000000")

        self.size_value.configure(text=f"{self.config.cursor_size} px")
        if int(self.var_size.get()) != self.config.cursor_size:
            self.var_size.set(self.config.cursor_size)

    def _poll_status(self) -> None:
        state = self.overlay.last_state
        if state is None or not self.config.badge_enabled:
            self.ime_status.configure(text="―", bg="#f0f0f0", fg="#000000")
        else:
            bg, fg = PALETTE.get(state.kind, PALETTE["unknown"])
            self.ime_status.configure(text=f"{state.label}  {state.text}", bg=bg, fg=fg)
        self._sync_marker_status()
        self.win.after(STATUS_INTERVAL_MS, self._poll_status)

    def _sync_marker_status(self) -> None:
        """ホットキーで切り替えられた場合でも管理画面の表示を合わせる。"""
        marker_on = self.marker.active
        self.marker_button.configure(
            text="マーカーを停止" if marker_on else "マーカーを開始"
        )
        self.marker_status.configure(
            text="描画中" if marker_on else "停止中",
            bg="#c62828" if marker_on else "#9e9e9e",
            fg="#ffffff",
        )
        self.marker_count.configure(text=f"枠 {self.marker.shape_count()} 個")

    # ================================================================ 開閉
    def show(self) -> None:
        self.win.deiconify()
        # バックグラウンドから起動された直後は前面を奪えない。いったん最前面に
        # してから外すことで、他のアプリの後ろに埋もれるのを防ぐ
        self.win.attributes("-topmost", True)
        self.win.lift()
        self.win.focus_force()
        self.win.after(400, lambda: self._drop_topmost())
        self._sync_widgets()

    def _drop_topmost(self) -> None:
        try:
            self.win.attributes("-topmost", False)
        except tk.TclError:
            pass

    def hide(self) -> None:
        self._save()
        self.win.withdraw()

    def quit(self) -> None:
        self._save()
        self.on_quit()
