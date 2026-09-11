"""管理画面 (tkinter)。

- IME モード表示のオン / オフ
- コピー通知のオン / オフ
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
from tkinter import messagebox, ttk

from . import cursortheme
from .colorpicker import ask_color
from .config import (
    COLOR_PRESETS,
    MARKER_COLOR_PRESETS,
    MARKER_WIDTH_MAX,
    MARKER_WIDTH_MIN,
    PALETTE,
    Config,
    config_path,
    contrast_fg,
)
from .clipnotice import ClipboardNotice
from .marker import Marker
from .overlay import Overlay, pick_font_family
from .win32 import cursor_pixel_size

# サイズのショートカット。Windows の設定画面のスライダーに近い刻み
SIZE_PRESETS = (32, 48, 64, 96, 128, 192, 256)

# 「いまの IME」表示の更新間隔 (ミリ秒)
STATUS_INTERVAL_MS = 200

# ログ欄に残す最大行数
LOG_MAX_LINES = 500

# セクション間の余白 (px)。塊が分かれて見えるよう広めに取る
SECTION_GAP = 14

# 「クリックすると変えられる」ことを示す印
CLICK_HINT = "  ▾"

# 管理画面の位置だけを表すジオメトリ。マルチモニタで原点が負のときは
# Tk が "+-1920+0" の形を返すので、符号の重なりも許す
_POSITION_ONLY = re.compile(r"[+-]-?\d+[+-]-?\d+")


class AdminWindow:
    """常駐プロセスに 1 つだけ存在する管理画面。閉じても常駐は続く。"""

    def __init__(self, root: tk.Tk, config: Config, overlay: Overlay,
                 marker: Marker, clipnotice: ClipboardNotice, on_quit) -> None:
        self.root = root
        self.config = config
        self.overlay = overlay
        self.marker = marker
        self.clipnotice = clipnotice
        self.on_quit = on_quit
        self._suppress = True  # 初期化中の trace で適用処理を走らせない

        family = pick_font_family()
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=family, size=10)
            except tk.TclError:
                pass
        self.mono = tkfont.Font(family="Consolas", size=9)
        self.heading = tkfont.Font(family=family, size=11, weight="bold")

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
        self._build_clip_section(outer)
        self._build_marker_section(outer)
        self._build_color_section(outer)
        self._build_size_section(outer)
        self._build_footer(outer)
        self._build_log_section(outer)

    def _section(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        """見出し + 下線 + 中身の入れ物を作って返す。

        ttk.LabelFrame は Windows のテーマだと枠線がごく淡く、セクションの
        切れ目が読み取れない。太字の見出しと罫線 1 本に置き換えている。
        """
        holder = ttk.Frame(parent)
        holder.pack(fill="x", pady=(0, SECTION_GAP))
        ttk.Label(holder, text=title, font=self.heading).pack(anchor="w")
        ttk.Separator(holder, orient="horizontal").pack(fill="x", pady=(3, 8))
        body = ttk.Frame(holder)
        body.pack(fill="x", padx=2)
        return body

    # -- IME モード表示 ----------------------------------------------------
    def _build_badge_section(self, parent: ttk.Frame) -> None:
        box = self._section(parent, "IME モード表示")

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
        self._spinbox(size_row, self.var_font_size, self._on_badge_option,
                      from_=8, to=72, width=5).pack(side="left", padx=(6, 2))
        ttk.Label(size_row, text="px").pack(side="left")

        ttk.Label(size_row, text="不透明度").pack(side="left", padx=(16, 6))
        self.var_alpha = tk.IntVar(value=round(self.config.alpha * 100))
        self._spinbox(size_row, self.var_alpha, self._on_badge_option,
                      from_=10, to=100, increment=5, width=5).pack(side="left", padx=(0, 2))
        ttk.Label(size_row, text="%").pack(side="left")

    # -- コピー通知 --------------------------------------------------------
    def _build_clip_section(self, parent: ttk.Frame) -> None:
        box = self._section(parent, "コピー通知")

        self.var_clip_enabled = tk.BooleanVar(value=self.config.clip_notice_enabled)
        self.var_clip_preview = tk.BooleanVar(value=self.config.clip_notice_preview)
        ttk.Checkbutton(box, text="クリップボードにコピーしたら、カーソルの近くに知らせる",
                        variable=self.var_clip_enabled,
                        command=self._on_clip_option).pack(anchor="w")
        ttk.Checkbutton(box, text="コピーした内容の先頭も出す",
                        variable=self.var_clip_preview,
                        command=self._on_clip_option).pack(anchor="w", pady=(6, 0))

        row = ttk.Frame(box)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="表示時間").pack(side="left")
        self.var_clip_ms = tk.IntVar(value=self.config.clip_notice_ms)
        self._spinbox(row, self.var_clip_ms, self._on_clip_option,
                      from_=300, to=10000, increment=100,
                      width=7).pack(side="left", padx=(6, 2))
        ttk.Label(row, text="ミリ秒").pack(side="left")

        ttk.Label(row, text="文字サイズ").pack(side="left", padx=(16, 0))
        self.var_clip_font = tk.IntVar(value=self.config.clip_font_size)
        self._spinbox(row, self.var_clip_font, self._on_clip_option,
                      from_=8, to=72, width=5).pack(side="left", padx=(6, 2))
        ttk.Label(row, text="px").pack(side="left")

        ttk.Button(row, text="テスト表示",
                   command=self.test_clip_notice).pack(side="left", padx=(16, 0))

    # -- プレゼン用マーカー ------------------------------------------------
    def _build_marker_section(self, parent: ttk.Frame) -> None:
        box = self._section(parent, "プレゼン用マーカー（矩形）")

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

        opts = ttk.Frame(box)
        opts.pack(fill="x", pady=(8, 0))
        ttk.Label(opts, text="線の太さ").pack(side="left")
        self.var_marker_width = tk.IntVar(value=self.config.marker_width)
        self._spinbox(opts, self.var_marker_width, self._on_marker_option,
                      from_=MARKER_WIDTH_MIN, to=MARKER_WIDTH_MAX,
                      width=5).pack(side="left", padx=(6, 2))
        ttk.Label(opts, text="px").pack(side="left")
        ttk.Label(opts, text="色").pack(side="left", padx=(16, 4))
        self.marker_preview = self._color_label(opts, self.open_marker_color_popup, 12)
        self.marker_preview.pack(side="left")

        self.var_marker_indicator = tk.BooleanVar(
            value=self.config.marker_show_indicator
        )
        ttk.Checkbutton(box, text="モード中に左上へ操作説明を出す",
                        variable=self.var_marker_indicator,
                        command=self._on_marker_option).pack(anchor="w", pady=(8, 0))

    def _spinbox(self, parent: ttk.Frame, variable, command, **kwargs) -> ttk.Spinbox:
        """数字を打ち込んでも反映される Spinbox。

        ttk.Spinbox の command は上下の矢印を押したときだけ呼ばれる。
        打ち込んだ値も効くように Enter とフォーカス外れも拾う。
        """
        box = ttk.Spinbox(parent, textvariable=variable, command=command, **kwargs)
        box.bind("<Return>", lambda _e: command())
        box.bind("<FocusOut>", lambda _e: command())
        return box

    def _color_label(self, parent: ttk.Frame, command: object, width: int) -> tk.Label:
        """いまの色を出し、押すと色のポップアップを開くラベル。

        色見本ボタンを機能ごとに並べるとパネルが色ボタンで埋まるので、
        現在の色を出すラベル自体を入り口にしている。
        """
        label = tk.Label(parent, text="", width=width, padx=8, pady=4, bd=2,
                         relief="raised", cursor="hand2")
        label.bind("<Button-1>", lambda _e: command())
        return label

    # -- マウスカーソルの色 ------------------------------------------------
    def _build_color_section(self, parent: ttk.Frame) -> None:
        box = self._section(parent, "マウスカーソルの色")

        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="色").pack(side="left", padx=(0, 4))
        self.color_preview = self._color_label(row, self.open_cursor_color_popup, 22)
        self.color_preview.pack(side="left")

    # -- マウスカーソルのサイズ --------------------------------------------
    def _build_size_section(self, parent: ttk.Frame) -> None:
        box = self._section(parent, "マウスカーソルのサイズ")

        row = ttk.Frame(box)
        row.pack(fill="x")
        for size in SIZE_PRESETS:
            ttk.Button(row, text=str(size), width=5,
                       command=lambda s=size: self.set_cursor_size(s)).pack(
                           side="left", padx=(0, 3))
        self.size_value = ttk.Label(row, text="")
        self.size_value.pack(side="left", padx=(12, 0))

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
        box = self._section(parent, "ログ")

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
        # 自分の書き込みでコピー通知が出ると、管理画面の上にトーストが重なる
        self.clipnotice.mute()
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
        # 丸められた場合に、欄の表示を実際に効いた値へそろえる
        self.var_font_size.set(self.config.font_size)
        self.var_alpha.set(round(self.config.alpha * 100))
        self.overlay.apply_config()
        self._save()
        self.log(
            f"バッジ設定を更新: 隠す={self.config.hide_alnum} "
            f"説明={self.config.verbose} 文字={self.config.font_size}px "
            f"不透明度={round(self.config.alpha * 100)}%"
        )

    # -- コピー通知 --------------------------------------------------------
    def _on_clip_option(self) -> None:
        if self._suppress:
            return
        self.config.clip_notice_enabled = bool(self.var_clip_enabled.get())
        self.config.clip_notice_preview = bool(self.var_clip_preview.get())
        try:
            self.config.clip_notice_ms = int(self.var_clip_ms.get())
            self.config.clip_font_size = int(self.var_clip_font.get())
        except (tk.TclError, ValueError):
            pass
        self.config.clamp()
        # 丸められた場合に、欄の表示を実際に効いた値へそろえる
        self.var_clip_ms.set(self.config.clip_notice_ms)
        self.var_clip_font.set(self.config.clip_font_size)
        self.clipnotice.apply_config()
        self._save()
        self.log(
            f"コピー通知: {'あり' if self.config.clip_notice_enabled else 'なし'} / "
            f"内容の先頭 {'あり' if self.config.clip_notice_preview else 'なし'} / "
            f"表示 {self.config.clip_notice_ms} ミリ秒 / "
            f"文字 {self.config.clip_font_size}px"
        )

    def test_clip_notice(self) -> None:
        self.clipnotice.show_test()
        self.log("コピー通知をテスト表示しました（マウスカーソルの近くに出ます）")

    # -- マーカー ----------------------------------------------------------
    def toggle_marker(self) -> None:
        self.marker.toggle()
        self._sync_widgets()

    def clear_marker(self) -> None:
        removed = self.marker.clear()
        self.log(f"マーカーの枠 {removed} 個を消しました")
        self._sync_widgets()

    def open_marker_color_popup(self) -> None:
        changed, color = ask_color(
            self.win, self.config.marker_color, MARKER_COLOR_PRESETS,
            title="マーカーの色", near=self.marker_preview,
        )
        if not changed or color is None:
            return
        self.config.marker_color = color
        self.config.clamp()
        self.marker.apply_config()
        self._save()
        self._sync_widgets()
        self.log(f"マーカーの色を {self.config.marker_color} にしました")

    def _on_marker_option(self) -> None:
        if self._suppress:
            return
        try:
            self.config.marker_width = int(self.var_marker_width.get())
        except (tk.TclError, ValueError):
            return
        self.config.marker_show_indicator = bool(self.var_marker_indicator.get())
        self.config.clamp()
        self.marker.apply_config()
        self._save()
        self._sync_widgets()
        self.log(
            f"マーカー: 線の太さ {self.config.marker_width}px / "
            f"操作説明 {'あり' if self.config.marker_show_indicator else 'なし'}"
        )

    # -- 色 ----------------------------------------------------------------
    def open_cursor_color_popup(self) -> None:
        changed, color = ask_color(
            self.win, self.config.cursor_color, COLOR_PRESETS,
            title="マウスカーソルの色", allow_none=True,
            none_label="Windows の設定のまま", near=self.color_preview,
        )
        if not changed:
            return
        self.config.cursor_color = color
        self.config.clamp()
        self._apply_cursor(
            "カーソル色を Windows の設定に戻します" if color is None
            else f"カーソル色を {self.config.cursor_color} にします"
        )

    # -- サイズ ------------------------------------------------------------
    def set_cursor_size(self, size: int) -> None:
        if self._suppress or size == self.config.cursor_size:
            return
        self.config.cursor_size = size
        self.config.clamp()
        self._apply_cursor(f"カーソルサイズを {self.config.cursor_size}px にします")

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

        if bool(self.var_clip_enabled.get()) != self.config.clip_notice_enabled:
            self.var_clip_enabled.set(self.config.clip_notice_enabled)
        if bool(self.var_clip_preview.get()) != self.config.clip_notice_preview:
            self.var_clip_preview.set(self.config.clip_notice_preview)
        if int(self.var_clip_ms.get() or 0) != self.config.clip_notice_ms:
            self.var_clip_ms.set(self.config.clip_notice_ms)
        if int(self.var_clip_font.get() or 0) != self.config.clip_font_size:
            self.var_clip_font.set(self.config.clip_font_size)

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
        self.marker_preview.configure(text=marker_color.upper() + CLICK_HINT,
                                      bg=marker_color, fg=contrast_fg(marker_color))
        if int(self.var_marker_width.get() or 0) != self.config.marker_width:
            self.var_marker_width.set(self.config.marker_width)
        if bool(self.var_marker_indicator.get()) != self.config.marker_show_indicator:
            self.var_marker_indicator.set(self.config.marker_show_indicator)

        color = self.config.cursor_color
        if color:
            self.color_preview.configure(text=color.upper() + CLICK_HINT,
                                         bg=color, fg=contrast_fg(color))
        else:
            self.color_preview.configure(text="Windows の設定のまま" + CLICK_HINT,
                                         bg="#f0f0f0", fg="#000000")

        self.size_value.configure(text=f"いま {self.config.cursor_size} px")

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
