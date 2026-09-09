"""起動制御。

多重起動すると同じバッジが 2 枚重なるため、名前付きミューテックスで 1 プロセス
に制限する。2 回目以降の起動は目印ファイルを置いてすぐ終了し、常駐している側が
それを見て管理画面を出す。つまり ime_cursor.pyw をもう一度ダブルクリックすれば
管理画面が戻ってくる。
"""

from __future__ import annotations

import sys
import time

from . import config as config_module
from . import cursortheme
from .imestate import ImeWatcher
from .win32 import acquire_single_instance, enable_dpi_awareness, message_box

MUTEX_NAME = "Local\\ime_cursor.singleton"

# 「管理画面を出して」の目印ファイルを見張る間隔 (ミリ秒)
FLAG_POLL_MS = 400

USAGE = """ime_cursor - IME 状態バッジ + マウスカーソルの色・サイズ

    ime_cursor.pyw                管理画面を出して常駐する
                                  （常駐中にもう一度実行すると管理画面が戻る）
    ime_cursor.pyw --silent       管理画面を出さずに常駐する（自動起動向け）
    ime_cursor.pyw --debug        GUI を出さず IME 状態をコンソールに出す
                                  （pythonw ではなく python で実行すること）
    ime_cursor.pyw --reset-cursor カーソルの色とサイズを既定に戻して終了する
    ime_cursor.pyw --help         この説明を出す

常駐中のショートカット:
    Ctrl+Shift+L                  プレゼン用マーカーの開始 / 終了
                                  （モード中はドラッグで赤い枠、Esc で消して終了）
"""


def _make_console_lenient() -> None:
    """コンソールが cp932 でも、絵文字やダッシュで落ちないようにする。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def console_monitor() -> int:
    """GUI を出さずに IME の状態遷移だけを出し続ける (デバッグ用)。"""
    watcher = ImeWatcher()
    last = None
    print("IME 状態を監視中 (Ctrl+C で終了)")
    while True:
        state = watcher.read()
        key = (state.label, state.text, state.mode)
        if key != last:
            mode = "-" if state.mode is None else f"0x{state.mode:02x}"
            print(f"{state.label:<2} {state.text:<8} open={state.open} mode={mode}",
                  flush=True)
            last = key
        time.sleep(0.1)


def reset_cursor() -> int:
    """GUI を起動せずにカーソルを戻す。管理画面が開けないときの逃げ道。"""
    cfg = config_module.load()
    cursortheme.restore_default(cfg, log=lambda message: print(message, flush=True))
    cfg.save()
    return 0


def _reapply_saved_cursor(cfg: config_module.Config, log) -> None:
    """保存した色とサイズを入れ直す。

    サイズは SetSystemCursor でセッションに載せているだけなので、サインアウト
    すると失われる。色も、Windows の「マウスポインターの色」機能が動くと
    上書きされることがある。どちらも起動時に一度入れ直しておく。
    """
    if cfg.cursor_color is None and cfg.cursor_size == config_module.CURSOR_SIZE_DEFAULT:
        return
    log("保存されたカーソルの色とサイズを適用します")
    cursortheme.apply(cfg, log=log)


def run_gui(show_admin: bool) -> int:
    try:
        import tkinter as tk
    except ImportError:
        message_box(
            "tkinter が見つかりません。tkinter 同梱の Python で実行してください。",
            icon=0x10,
        )
        return 1

    from .admin import AdminWindow
    from .marker import Marker
    from .overlay import Overlay

    cfg = config_module.load()

    root = tk.Tk()
    root.withdraw()

    overlay = Overlay(root, cfg)
    marker = Marker(root, cfg)
    admin = AdminWindow(
        root, cfg, overlay, marker, on_quit=lambda: _quit(root, overlay, marker)
    )
    marker.log = admin.log      # 管理画面ができてからログの行き先を差し替える
    marker.start_hotkey()       # 登録に失敗してもログに出すだけで常駐は続ける

    if show_admin:
        admin.show()
    else:
        admin.hide()

    try:
        _reapply_saved_cursor(cfg, admin.log)
    except Exception as exc:
        admin.log(f"カーソル設定の再適用に失敗: {type(exc).__name__}: {exc}")

    flag = config_module.show_admin_flag_path()
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.unlink(missing_ok=True)  # 前回の残りで勝手に開かないようにする

    def poll_flag() -> None:
        if flag.exists():
            flag.unlink(missing_ok=True)
            admin.log("2 回目の起動を検知したので、管理画面を前に出します")
            admin.show()
        root.after(FLAG_POLL_MS, poll_flag)

    root.after(FLAG_POLL_MS, poll_flag)
    root.protocol("WM_DELETE_WINDOW", lambda: _quit(root, overlay, marker))

    try:
        root.mainloop()
    except KeyboardInterrupt:
        _quit(root, overlay, marker)
    return 0


def _quit(root, overlay, marker=None) -> None:
    # マーカーを先に畳む。ホットキーの解除とスレッドの終了を待つ必要がある
    if marker is not None:
        marker.stop()
    overlay.stop()
    try:
        root.destroy()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _make_console_lenient()

    if "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0

    enable_dpi_awareness()

    if "--debug" in argv:
        try:
            return console_monitor()
        except KeyboardInterrupt:
            return 0

    if "--reset-cursor" in argv:
        return reset_cursor()

    unknown = [a for a in argv if a not in ("--silent", "--no-admin")]
    if unknown:
        message_box("使い方が違います:\n  " + " ".join(unknown) + "\n\n" + USAGE, icon=0x30)
        return 2

    if not acquire_single_instance(MUTEX_NAME):
        # 既に常駐している。目印を置いて、そちらに管理画面を出させる
        flag = config_module.show_admin_flag_path()
        try:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("show", encoding="utf-8")
        except OSError as exc:
            message_box(f"既に常駐していますが、管理画面を呼び出せませんでした。\n{exc}",
                        icon=0x30)
        return 0

    return run_gui(show_admin="--silent" not in argv and "--no-admin" not in argv)
