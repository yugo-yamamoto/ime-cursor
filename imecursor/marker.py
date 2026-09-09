"""プレゼン中に画面へ赤い矩形の枠を描くマーカー。

ウィンドウを 2 枚重ねている。「描いた図形だけが見えて、それ以外は下のアプリが
見える」と「マウスのドラッグを奪う」を 1 枚では同時に満たせないため。

    shapes   -transparentcolor でキー色を抜いた層。枠を不透明で描く。
             カラーキーの透過部分は「表示も当たり判定も」抜けるので、下の
             アプリがそのまま見えるしクリックも通る。ただし描いた線の上だけは
             当たり判定が残ってしまう (実測) ため、WS_EX_TRANSPARENT も併用して
             枠の上でクリックが死ぬのを防ぐ。

    catcher  一律アルファをごく薄くかけただけの層。カラーキーや
             WS_EX_TRANSPARENT と違い、一律アルファは当たり判定を透過させない
             ので、事実上見えないままドラッグを受け取り、かつ下のアプリへ
             クリックを通さない。
             アルファ 0.0 は「完全透過」扱いで当たり判定が抜けるため、
             config 側で 0.01 を下限に丸めている。

キーボードはフォーカスを奪わずに下のアプリへ残す (WS_EX_NOACTIVATE)。そのため
マーカーモード中も矢印キーやプレゼンリモコンでスライドを送れる。代わりに
Escape は Tk のバインドでは受け取れないので、モード中だけグローバルホットキー
として登録し、抜けるときに解除する。

Tk の deiconify() は内部で ShowWindow(SW_RESTORE) を呼ぶため、
WS_EX_NOACTIVATE を付けていても表示の瞬間だけフォアグラウンドを奪ってしまう
(実測)。表示直後に元のウィンドウへ返している。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from . import hotkey as hotkey_module
from .config import (
    MARKER_KEY_COLOR,
    MARKER_MAX_SHAPES,
    MARKER_HOTKEY_DEFAULT,
    Config,
)
from .overlay import pick_font_family
from .win32 import (
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TRANSPARENT,
    add_ex_style,
    foreground_window,
    hide_window,
    restore_foreground,
    show_window_no_activate,
    toplevel_hwnd,
    virtual_screen,
)

# ホットキーの名前
HOTKEY_TOGGLE = "marker_toggle"
HOTKEY_ESCAPE = "marker_escape"

# 画面構成の変化 (プレゼン直前にプロジェクタが挿される) を見張る間隔
WATCH_INTERVAL_MS = 1000

# これ未満のドラッグは誤クリックとみなして捨てる (px)
MIN_DRAG = 4

# Canvas のタグ。clear() で消すのは枠だけ
TAG_SHAPE = "shape"
TAG_UI = "ui"


class Marker:
    """画面マーカー。ホットキーと管理画面の両方から操作される。"""

    def __init__(self, root: tk.Tk, config: Config, log=None) -> None:
        self.root = root
        self.config = config
        self.log = log or (lambda _message: None)

        self.active = False
        self.shapes: tk.Toplevel | None = None
        self.catcher: tk.Toplevel | None = None
        self.canvas: tk.Canvas | None = None
        self._shapes_hwnd = 0
        self._catcher_hwnd = 0

        self._hotkeys = hotkey_module.HotkeyListener()
        self._band: int | None = None       # ドラッグ中の枠
        self._origin = (0, 0)               # ドラッグの開始点 (Canvas 座標)
        self._offset = (0, 0)               # 仮想スクリーンの原点
        self._rect = None                   # 最後に適用したジオメトリ
        self._prev_foreground = 0
        self._watch_id: str | None = None

    # ================================================================ ホットキー
    def start_hotkey(self) -> None:
        """モード切り替えのホットキーを登録する。失敗しても常駐は続ける。"""
        if not self.config.marker_hotkey_enabled:
            self.log("マーカーのホットキーは無効に設定されています")
            return
        if not self._hotkeys.start():
            self.log("警告: ホットキーの待ち受けスレッドを起動できませんでした")
            return

        combo = self.config.marker_hotkey
        try:
            self._hotkeys.register(HOTKEY_TOGGLE, combo)
        except ValueError as exc:
            self.log(f"ホットキー '{combo}' を解釈できません ({exc})。既定に戻します")
            self.config.marker_hotkey = combo = MARKER_HOTKEY_DEFAULT
            self._hotkeys.register(HOTKEY_TOGGLE, combo)

        self._hotkeys.pump(self.root, self._on_hotkey)
        self.log(f"マーカー: {self.hotkey_label()} でモードを切り替えます")

    def hotkey_label(self) -> str:
        return hotkey_module.describe_combo(self.config.marker_hotkey)

    def hotkey_error(self) -> str | None:
        return self._hotkeys.error_for(HOTKEY_TOGGLE)

    def _on_hotkey(self, name: str) -> None:
        if name == HOTKEY_TOGGLE:
            self.toggle()
        elif name == HOTKEY_ESCAPE:
            self.escape()

    # ================================================================ 状態
    def shape_count(self) -> int:
        """描かれている枠の数。インジケータは数えない。"""
        if self.canvas is None:
            return 0
        return len(self.canvas.find_withtag(TAG_SHAPE))

    def toggle(self) -> None:
        self.deactivate() if self.active else self.activate()

    def escape(self) -> None:
        """Escape の挙動: 枠を全部消して、モードも終了する。"""
        removed = self.shape_count()
        self.deactivate()
        self.log(f"マーカーを終了しました（枠 {removed} 個を消去）")

    def clear(self) -> int:
        """枠を全部消す。モードは維持する。"""
        removed = self.shape_count()
        if self.canvas is not None:
            self.canvas.delete(TAG_SHAPE)
        self._band = None
        return removed

    # ================================================================ 表示
    def activate(self) -> None:
        if self.active:
            return
        # ウィンドウの生成そのものがフォアグラウンドを奪う (Tk が
        # -transparentcolor / -alpha を反映するときにラッパーを作り直して
        # 表示するため。実測) 。だから生成より先に、今どのアプリが前面かを
        # 覚えておく
        self._prev_foreground = foreground_window()
        self._ensure_windows()
        self._apply_geometry()

        # catcher を先に出し、shapes を後から出す。topmost 同士では後から
        # 表示した方が上に来るので、赤い枠が catcher の薄いベール越しにならない。
        # Tk の deiconify() / lift() はどちらも活性化を伴い、下のアプリから
        # フォーカスを奪ってしまうので使わない (SW_SHOWNA で出す)
        show_window_no_activate(self._catcher_hwnd)
        show_window_no_activate(self._shapes_hwnd)
        for win in (self.catcher, self.shapes):
            win.attributes("-topmost", True)

        # 生成時に奪ったフォアグラウンドを元のアプリへ返す。この時点では
        # こちらが前面なので SetForegroundWindow は拒否されない。
        # これでモード中も下のアプリのキーボード操作 (矢印キーや
        # プレゼンリモコン) がそのまま効く
        restore_foreground(self._prev_foreground)

        self.active = True
        self._draw_indicator()
        try:
            self._hotkeys.register(HOTKEY_ESCAPE, "escape")
        except ValueError:
            pass
        self._watch()
        self.log("マーカーを開始しました（ドラッグで枠、Esc で消去して終了）")

    def deactivate(self) -> None:
        if not self.active:
            return
        self.active = False
        self._hotkeys.unregister(HOTKEY_ESCAPE)
        if self._watch_id is not None:
            self.root.after_cancel(self._watch_id)
            self._watch_id = None
        self.clear()
        if self.canvas is not None:
            self.canvas.delete(TAG_UI)
        for hwnd in (self._shapes_hwnd, self._catcher_hwnd):
            if hwnd:
                hide_window(hwnd)

    # ================================================================ 設定反映
    def apply_config(self) -> None:
        """管理画面で色・太さ・アルファが変わったあとに呼ぶ。"""
        if self.catcher is not None:
            self.catcher.attributes("-alpha", self.config.marker_catch_alpha)
        if self.canvas is not None:
            for item in self.canvas.find_withtag(TAG_SHAPE):
                self.canvas.itemconfigure(
                    item, outline=self.config.marker_color, width=self.config.marker_width
                )
            if self.active:
                self._draw_indicator()

    # ================================================================ ウィンドウ
    def _ensure_windows(self) -> None:
        if self.shapes is not None:
            return

        # 描画層。キー色は表示も当たり判定も抜ける
        self.shapes = tk.Toplevel(self.root)
        self.shapes.overrideredirect(True)
        self.shapes.withdraw()
        self.shapes.configure(bg=MARKER_KEY_COLOR)
        self.shapes.attributes("-topmost", True)
        self.shapes.attributes("-transparentcolor", MARKER_KEY_COLOR)
        self.canvas = tk.Canvas(
            self.shapes, bg=MARKER_KEY_COLOR, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.shapes.update_idletasks()
        self._shapes_hwnd = toplevel_hwnd(self.shapes.winfo_id())
        add_ex_style(
            self._shapes_hwnd,
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        )

        # 入力層。WS_EX_TRANSPARENT を付けてはいけない (当たり判定が抜けて
        # ドラッグを拾えなくなる)。WS_EX_NOACTIVATE は下のアプリから
        # キーボードフォーカスを奪わないために必要
        self.catcher = tk.Toplevel(self.root)
        self.catcher.overrideredirect(True)
        self.catcher.withdraw()
        self.catcher.configure(bg="#000000", cursor="crosshair")
        self.catcher.attributes("-topmost", True)
        self.catcher.attributes("-alpha", self.config.marker_catch_alpha)
        self.catcher.update_idletasks()
        self._catcher_hwnd = toplevel_hwnd(self.catcher.winfo_id())
        add_ex_style(
            self._catcher_hwnd,
            WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        )

        self.catcher.bind("<ButtonPress-1>", self._on_press)
        self.catcher.bind("<B1-Motion>", self._on_motion)
        self.catcher.bind("<ButtonRelease-1>", self._on_release)
        # 右クリックは緊急脱出。固まったときにクリックを食い続けないため
        self.catcher.bind("<ButtonPress-3>", lambda _e: self.escape())

        # 日本語が出るフォントを選ぶ。欧文フォントにフォールバックさせない
        self.font = tkfont.Font(family=pick_font_family(), size=-20, weight="bold")

    def _apply_geometry(self) -> None:
        """仮想スクリーン全体を覆う。

        Tk の geometry は "-x" を「右端からの距離」と解釈するため、原点が負に
        なるマルチモニタでは f"+{x}+{y}" が使えない。f"{x:+d}" にして
        "+-1920" の形にする (実測で GetWindowRect と一致)。
        """
        vx, vy, vw, vh = virtual_screen()
        spec = f"{vw}x{vh}{vx:+d}{vy:+d}"
        for win in (self.shapes, self.catcher):
            win.geometry(spec)
        self._offset = (vx, vy)
        self._rect = (vx, vy, vw, vh)

    def _watch(self) -> None:
        """画面構成が変わったら追従し、topmost も付け直す。"""
        if not self.active:
            return
        if virtual_screen() != self._rect:
            self._apply_geometry()
            self._draw_indicator()
            self.log("画面構成が変わったので、マーカーの範囲を作り直しました")
        # topmost の付け直しは活性化を伴わないので、ここで毎回やってよい
        for win in (self.catcher, self.shapes):
            win.attributes("-topmost", True)
        self._watch_id = self.root.after(WATCH_INTERVAL_MS, self._watch)

    # ================================================================ 描画
    def _to_canvas(self, event) -> tuple[int, int]:
        """画面座標を Canvas 座標へ。event.x ではなく x_root から作る。

        catcher 側に余白やボーダーが入っても位置がずれない。
        """
        vx, vy = self._offset
        return event.x_root - vx, event.y_root - vy

    def _on_press(self, event) -> None:
        if not self.active or self.canvas is None:
            return
        if self.shape_count() >= MARKER_MAX_SHAPES:
            self.log(f"枠が上限の {MARKER_MAX_SHAPES} 個に達しています")
            return
        x, y = self._to_canvas(event)
        self._origin = (x, y)
        self._band = self.canvas.create_rectangle(
            x, y, x, y,
            outline=self.config.marker_color,
            width=self.config.marker_width,
            fill="",  # 内側はキー色 = 透過。枠の中は下のアプリが見えるしクリックも通る
            tags=TAG_SHAPE,
        )

    def _on_motion(self, event) -> None:
        if self._band is None or self.canvas is None:
            return
        x, y = self._to_canvas(event)
        x0, y0 = self._origin
        # 作り直さず座標だけ差し替える。update() は呼ばない (Tk が間引く)
        self.canvas.coords(self._band, x0, y0, x, y)

    def _on_release(self, event) -> None:
        if self._band is None or self.canvas is None:
            return
        x, y = self._to_canvas(event)
        x0, y0 = self._origin
        if abs(x - x0) < MIN_DRAG or abs(y - y0) < MIN_DRAG:
            self.canvas.delete(self._band)  # ただのクリック。点を残さない
        else:
            self.canvas.coords(self._band, x0, y0, x, y)
        self._band = None

    def _draw_indicator(self) -> None:
        """モード中であることと操作方法を左上に出す。"""
        if self.canvas is None:
            return
        self.canvas.delete(TAG_UI)
        text = f"マーカー ON   ドラッグ=枠   Esc=消して終了   {self.hotkey_label()}=終了"
        pad = 10
        item = self.canvas.create_text(
            24 + pad, 24 + pad, text=text, anchor="nw",
            fill="#ffffff", font=self.font, tags=TAG_UI,
        )
        x0, y0, x1, y1 = self.canvas.bbox(item)
        # キー色の上に直接文字を置くと、アンチエイリアスの中間色がキー色に
        # 寄って欠ける。不透明な下地を敷いてからその上に乗せる
        box = self.canvas.create_rectangle(
            x0 - pad, y0 - pad, x1 + pad, y1 + pad,
            fill="#202020", outline=self.config.marker_color, width=2, tags=TAG_UI,
        )
        self.canvas.tag_raise(item, box)

    # ================================================================ 終了
    def stop(self) -> None:
        self.deactivate()
        self._hotkeys.stop()
        for win in (self.shapes, self.catcher):
            if win is not None:
                try:
                    win.destroy()
                except Exception:
                    pass
        self.shapes = self.catcher = self.canvas = None
