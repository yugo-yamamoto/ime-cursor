"""クリップボードに入ったことを、マウスカーソルの近くで数秒だけ知らせる。

Ctrl+C を押しても本当にコピーできたのか分からないことがある (選択が外れて
いた、フォーカスが別ペインにあった、アプリが Ctrl+C を食べた)。コピーできた
ときだけ通知を出すことで、**通知が出なければコピーされていない**と分かる。

変化の検知は `GetClipboardSequenceNumber` のポーリング。Windows には
`AddClipboardFormatListener` + `WM_CLIPBOARDUPDATE` という正式なイベントも
あるが、自前の WndProc を持つ HWND が必要になる。Tk のトップレベルの WndProc
は Tcl/Tk のもので差し替えは壊れやすく、避けるならメッセージ専用ウィンドウを
別スレッドに立てることになる。sequence number なら 1 tick あたり user32 の
呼び出し 1 回で済み、クリップボードを開かないので他アプリの邪魔もしない。

ウィンドウの作りはバッジ (overlay.py) と同じ。表示と非表示だけは Tk の
deiconify() ではなく SW_SHOWNA / SW_HIDE で行う。deiconify() は
WS_EX_NOACTIVATE を付けていても表示の瞬間にフォアグラウンドを奪うため
(marker.py の冒頭コメント参照)。コピー通知は「他アプリで入力中」に出るもの
なので、ここは譲れない。
"""

from __future__ import annotations

import ctypes
import re
import time
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

from .config import Config
from .overlay import cursor_scale, pick_font_family
from .win32 import (
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TRANSPARENT,
    add_ex_style,
    clipboard_excluded,
    clipboard_kind,
    clipboard_sequence,
    clipboard_text_head,
    dpi_scale_at,
    hide_window,
    place_window_no_activate,
    toplevel_hwnd,
    user32,
    virtual_screen,
)

# 変化を見張る間隔 (ミリ秒)。通知が切ってあるときは IDLE の方を使う
POLL_INTERVAL_MS = 120
IDLE_INTERVAL_MS = 200

# 1 回のコピーで sequence が数回増えるアプリ (Office など。フォーマットを
# 段階的に載せる) がある。この時間内の変化は出し直さず、表示時間だけ延ばす
DEBOUNCE_MS = 400

# 通知に出すプレビューの文字数
PREVIEW_CHARS = 24

# バッジ (既定 +20/+20) の下に来るオフセット
OFFSET_X = 20
OFFSET_Y = 52

# 見た目。マーカーの操作説明 (marker.py::_draw_indicator) に合わせている。
# 大きさはすべて 96dpi (等倍) での px。出すモニタの拡大率を掛けて使う
ALPHA = 0.92
PADDING_X = 10
PADDING_Y = 6
BORDER = 2
GAP = 6  # 「コピーしました:」と中身のあいだ
BG_COLOR = "#202020"
ACCENT_COLOR = "#4caf50"

# 「コピーしました:」(状態) と、コピーした中身を読み分けられるよう色を変える。
# 中身の方を白 + 太字にして、目が先にそちらへ行くようにしている
TITLE_COLOR = "#8ce99a"
PREVIEW_COLOR = "#ffffff"

# 改行・タブ・制御文字。プレビューは 1 行に潰して出す
_BLANKS = re.compile(r"[\s\x00-\x1f\x7f]+")


def one_line(text: str) -> str:
    """プレビュー用に 1 行へ潰す。"""
    return _BLANKS.sub(" ", text).strip()


class ClipboardNotice:
    """クリップボードの変化を見張って、カーソル脇にトーストを出す。"""

    def __init__(self, root: tk.Tk, config: Config, log=None) -> None:
        self.root = root
        self.config = config
        self.log = log or (lambda _message: None)

        self.running = True
        self._sequence = clipboard_sequence()  # 起動直後の中身では通知しない
        self._visible = False
        self._shown_at = 0.0
        self._mute_until = 0.0
        self._hide_id: str | None = None
        self._scale = 0.0  # 最後に反映したモニタの拡大率

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.withdraw()
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", ALPHA)
        self.win.configure(bg=ACCENT_COLOR)  # 内側との差分が 2px の縁になる

        family = pick_font_family()
        self.title_font = tkfont.Font(family=family)
        self.preview_font = tkfont.Font(family=family, weight="bold")
        self.body = tk.Frame(self.win, bg=BG_COLOR)
        self.body.pack()
        self.title_label = tk.Label(
            self.body, text="", font=self.title_font,
            bg=BG_COLOR, fg=TITLE_COLOR, bd=0,
        )
        self.title_label.pack(side="left")
        self.preview_label = tk.Label(
            self.body, text="", font=self.preview_font,
            bg=BG_COLOR, fg=PREVIEW_COLOR, bd=0,
        )
        self._pad_x = PADDING_X
        self._pad_y = PADDING_Y
        self._gap = GAP
        self._apply_scale(1.0)

        self.win.update_idletasks()
        self._hwnd = toplevel_hwnd(self.win.winfo_id())
        add_ex_style(
            self._hwnd,
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        )
        self.tick()

    # ================================================================ 監視
    def tick(self) -> None:
        if not self.running:
            return
        if not self.config.clip_notice_enabled:
            # 切っている間の変化は溜めない。入れ直した瞬間に出てしまわないよう、
            # 見張らないあいだも現在値だけは追いかけておく
            self._sequence = clipboard_sequence()
            self.root.after(IDLE_INTERVAL_MS, self.tick)
            return

        try:
            self._check()
        except Exception as exc:  # 1 回の失敗で見張りを止めない
            self.log(f"コピー通知でエラー: {type(exc).__name__}: {exc}")

        self.root.after(POLL_INTERVAL_MS, self.tick)

    def _check(self) -> None:
        sequence = clipboard_sequence()
        if sequence == self._sequence:  # 折り返すので大小では比べない
            return
        self._sequence = sequence

        now = time.monotonic()
        if now < self._mute_until:  # 自分で書いた分 (mute 参照)
            return
        if self._visible and (now - self._shown_at) * 1000 < DEBOUNCE_MS:
            self._arm_hide()  # 同じコピーの続き。出し直さず時間だけ延ばす
            return
        self._show(*self._compose())

    def _compose(self) -> tuple[str, str]:
        """(見出し, 中身) に分けて返す。中身が無いときは空文字。"""
        kind = clipboard_kind()
        if kind == "files":
            return "ファイルをコピーしました", ""
        if kind == "image":
            return "画像をコピーしました", ""
        if kind == "text" and self.config.clip_notice_preview and not clipboard_excluded():
            # 空白で始まるテキストでもプレビューが空にならないよう多めに読む
            head = clipboard_text_head(PREVIEW_CHARS * 2 + 1)
            preview = one_line(head or "")
            if preview:
                if len(preview) > PREVIEW_CHARS:
                    preview = preview[:PREVIEW_CHARS] + "…"
                return "コピーしました:", preview
        return "コピーしました", ""

    # ================================================================ 表示
    def _apply_scale(self, scale: float) -> None:
        """出すモニタの拡大率に合わせて、文字と余白を作り直す。

        Per-Monitor v2 のプロセスでは Tk の 1 ピクセルが物理ピクセルなので、
        px 指定のままだと 200% のディスプレイで半分の大きさに見える。
        """
        if scale == self._scale:
            return
        self._scale = scale
        size = -max(1, round(self.config.clip_font_size * scale))
        self.title_font.configure(size=size)
        self.preview_font.configure(size=size)
        self._pad_x = round(PADDING_X * scale)
        self._pad_y = round(PADDING_Y * scale)
        self._gap = round(GAP * scale)
        # 外枠の色が見える幅 = 縁の太さ
        self.body.pack_configure(
            padx=round(BORDER * scale), pady=round(BORDER * scale)
        )

    def _set_text(self, title: str, preview: str) -> None:
        """見出しと中身を貼る。中身が無いときは右側のラベルを畳む。"""
        self.title_label.configure(text=title)
        if preview:
            self.title_label.pack_configure(padx=(self._pad_x, 0), pady=self._pad_y)
            self.preview_label.configure(text=preview)
            self.preview_label.pack(
                side="left", padx=(self._gap, self._pad_x), pady=self._pad_y
            )
        else:
            self.preview_label.pack_forget()
            self.title_label.pack_configure(padx=self._pad_x, pady=self._pad_y)

    def _show(self, title: str, preview: str = "") -> None:
        point = self._cursor_point()
        self._apply_scale(dpi_scale_at(*point) if point else 1.0)
        self._set_text(title, preview)
        self.win.update_idletasks()
        # Tk のマップを経由せずに出すので、Tk から見ると withdraw のまま。
        # 実サイズはまだ入っていないため、要求サイズを使う
        width = self.win.winfo_reqwidth()
        height = self.win.winfo_reqheight()
        x, y = self._position(point, width, height)
        # 原点が負になるマルチモニタでは "+{x}" が右端からの距離と解釈される。
        # 符号付きの書式にすること (marker.py::_apply_geometry 参照)。
        # ただし withdraw 中は Tk が反映しないので、表示は SetWindowPos で行う
        self.win.geometry(f"{width}x{height}{x:+d}{y:+d}")
        place_window_no_activate(self._hwnd, x, y, width, height)
        self._visible = True
        self._shown_at = time.monotonic()
        self._arm_hide()

    def _cursor_point(self) -> tuple[int, int] | None:
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        return int(point.x), int(point.y)

    def _position(self, point: tuple[int, int] | None,
                  width: int, height: int) -> tuple[int, int]:
        vx, vy, vw, vh = virtual_screen()
        if point is None:  # カーソルの位置が取れないときは画面の中央に出す
            return vx + (vw - width) // 2, vy + (vh - height) // 2
        ratio = cursor_scale(self.config.follow_cursor_size)
        x = point[0] + round(OFFSET_X * ratio)
        y = point[1] + round(OFFSET_Y * ratio)
        # 右端・下端に寄せてから左端・上端で止める。この順なら、通知が画面より
        # 大きい極端な場合でも画面外 (左や上) には出ない
        return (
            int(max(min(x, vx + vw - width), vx)),
            int(max(min(y, vy + vh - height), vy)),
        )

    def _arm_hide(self) -> None:
        self._cancel_hide()
        self._hide_id = self.root.after(self.config.clip_notice_ms, self.hide)

    def _cancel_hide(self) -> None:
        if self._hide_id is None:
            return
        try:
            self.root.after_cancel(self._hide_id)
        except tk.TclError:
            pass
        self._hide_id = None

    def hide(self) -> None:
        self._hide_id = None
        if not self._visible:
            return
        self._visible = False
        hide_window(self._hwnd)

    # ================================================================ 外から
    def show_test(self) -> None:
        """管理画面の「テスト表示」。設定を変えながら見え方を確かめる。"""
        self._show("コピーしました:", "テスト表示")

    def mute(self, milliseconds: int = 800) -> None:
        """これから自分で書き込む分を通知しない (管理画面の「ログをコピー」)。

        Tk のクリップボード書き込みは所有権の取得と実際の描き出しが分かれて
        いて sequence が複数回増えることがあるため、時間で塞ぐ。
        """
        self._sequence = clipboard_sequence()
        self._mute_until = time.monotonic() + milliseconds / 1000

    def apply_config(self) -> None:
        """管理画面で設定が変わったあとに呼ぶ。"""
        self._scale = 0.0  # 次に出すときに文字サイズを作り直させる
        if not self.config.clip_notice_enabled:
            self._cancel_hide()
            self.hide()

    def stop(self) -> None:
        self.running = False
        self._cancel_hide()
        try:
            self.win.destroy()
        except Exception:
            pass
