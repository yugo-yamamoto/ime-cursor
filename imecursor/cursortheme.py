"""マウスカーソルの色とサイズを Windows に適用する。

書き換えるのは HKEY_CURRENT_USER 配下だけで、管理者権限は要らない。

色とサイズは、それぞれ別の仕組みで効く。

色
    Windows は「マウスポインターの色」を %SystemRoot%\\cursors\\*.svg から
    その場でレンダリングし、%LOCALAPPDATA%\\Microsoft\\Windows\\Cursors\\*_eoa.cur
    に書き出している。レジストリの CursorColor を書き換えるだけでは何も起きない
    (SPI_SETCURSORS はレジストリが指すファイルを読み直すだけ)。
    そこで curfile で着色したファイルを自前で生成し、そこを指させる。

サイズ
    SM_CXCURSOR はプロセス起動時にキャッシュされるため、CursorBaseSize を書いて
    SPI_SETCURSORS しても、既に動いているアプリのカーソルは大きくならない。
    そこで LoadImageW で寸法を指定して読み込み、SetSystemCursor でセッション
    全体に載せる。こちらは即座に、全プロセスに効く。
    CursorBaseSize も併せて書いておき、再ログオン後の初期値をそろえる。

適用前のレジストリ値は設定ファイルに退避してあり、restore_default() で戻せる。
"""

from __future__ import annotations

import os
import winreg
from dataclasses import dataclass
from pathlib import Path

from . import curfile
from . import win32
from .config import CURSOR_SIZE_DEFAULT, Config, cursor_output_dir, hex_to_rgb
from .win32 import (
    broadcast_cursor_change,
    load_cursor_at_size,
    real_path,
    set_system_cursor,
)

CURSORS_KEY = r"Control Panel\Cursors"
ACCESSIBILITY_KEY = r"Software\Microsoft\Accessibility"

# CursorType: 0=白(既定) 1=黒 2=反転 6=カスタム色。
# 自前のスキームを Windows の配色機能に上書きされないよう 0 に倒しておく
CURSOR_TYPE_DEFAULT = 0

SCHEME_SOURCE_USER = 2  # 「ユーザー定義」。コントロールパネルの表示用


@dataclass(frozen=True)
class CursorSlot:
    """レジストリの値名と、着色元になる Aero テンプレート。"""

    name: str             # レジストリの値名 (Arrow, IBeam, ...)
    template: str | None  # %SystemRoot%\cursors\ 配下のファイル名。None なら自前で描く
    output: str           # 生成先のファイル名
    label: str            # ログに出す日本語名
    ocr: int | None       # SetSystemCursor で差し替えできる標準カーソル ID


# Aero スキームは Crosshair と IBeam を持たない (OS 内蔵のモノクロ版が使われる)。
# template が None のものは curfile で自前に描く。
# ocr が None のものはサイズを指定して載せられないため、レジストリ経由になる。
SLOTS: tuple[CursorSlot, ...] = (
    CursorSlot("Arrow", "aero_arrow.cur", "arrow.cur", "通常の選択", win32.OCR_NORMAL),
    CursorSlot("Help", "aero_helpsel.cur", "helpsel.cur", "ヘルプの選択", win32.OCR_HELP),
    CursorSlot("AppStarting", "aero_working.ani", "working.ani", "バックグラウンドで作業中",
               win32.OCR_APPSTARTING),
    CursorSlot("Wait", "aero_busy.ani", "busy.ani", "待ち状態", win32.OCR_WAIT),
    CursorSlot("Crosshair", None, "cross.cur", "領域の選択", win32.OCR_CROSS),
    CursorSlot("IBeam", None, "ibeam.cur", "テキストの選択", win32.OCR_IBEAM),
    CursorSlot("NWPen", "aero_pen.cur", "pen.cur", "手書き", None),
    CursorSlot("No", "aero_unavail.cur", "unavail.cur", "利用不可", win32.OCR_NO),
    CursorSlot("SizeNS", "aero_ns.cur", "ns.cur", "上下に拡大／縮小", win32.OCR_SIZENS),
    CursorSlot("SizeWE", "aero_ew.cur", "ew.cur", "左右に拡大／縮小", win32.OCR_SIZEWE),
    CursorSlot("SizeNWSE", "aero_nwse.cur", "nwse.cur", "斜めに拡大／縮小 1",
               win32.OCR_SIZENWSE),
    CursorSlot("SizeNESW", "aero_nesw.cur", "nesw.cur", "斜めに拡大／縮小 2",
               win32.OCR_SIZENESW),
    CursorSlot("SizeAll", "aero_move.cur", "move.cur", "移動", win32.OCR_SIZEALL),
    CursorSlot("UpArrow", "aero_up.cur", "up.cur", "代替の選択", win32.OCR_UP),
    CursorSlot("Hand", "aero_link.cur", "link.cur", "リンクの選択", win32.OCR_HAND),
    CursorSlot("Pin", "aero_pin.cur", "pin.cur", "場所の選択", None),
    CursorSlot("Person", "aero_person.cur", "person.cur", "ユーザーの選択", None),
)

# 退避しておくスカラー値 (カーソルファイル以外)。"" は既定値 = スキーム名
_EXTRA_VALUES = ("CursorBaseSize", "Scheme Source", "")


def _template_dir() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Cursors"


# ------------------------------------------------------------------ レジストリ

def _read_value(key_path: str, name: str) -> tuple[object, int] | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            return winreg.QueryValueEx(key, name)
    except OSError:
        return None


def _write_value(key_path: str, name: str, value: object, kind: int) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, kind, value)


def _delete_value(key_path: str, name: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except OSError:
        pass


def read_backup() -> dict:
    """現在のレジストリ値を、あとで戻せる形で読み出す。

    設定ファイルを消したあとに退避を取り直すと、自前で生成したカーソルを
    「元の状態」として覚えてしまう。生成先を指しているエントリは、退避対象
    ではなく「値なし（削除）」として扱う。
    """
    generated_dir = str(cursor_output_dir()).lower()
    backup: dict[str, object] = {}
    for name in [slot.name for slot in SLOTS] + list(_EXTRA_VALUES):
        found = _read_value(CURSORS_KEY, name)
        if found is not None and isinstance(found[0], str) \
                and found[0].lower().startswith(generated_dir):
            found = None
        backup[f"Cursors/{name}"] = None if found is None else [found[0], found[1]]
    for name in ("CursorType", "CursorColor"):
        found = _read_value(ACCESSIBILITY_KEY, name)
        backup[f"Accessibility/{name}"] = None if found is None else [found[0], found[1]]
    return backup


def _apply_backup(backup: dict) -> None:
    for full_name, saved in backup.items():
        key_path, _, name = full_name.partition("/")
        target = CURSORS_KEY if key_path == "Cursors" else ACCESSIBILITY_KEY
        if saved is None:
            _delete_value(target, name)
        else:
            value, kind = saved
            _write_value(target, name, value, int(kind))


def current_state() -> dict:
    """いまレジストリに書かれているカーソル設定 (診断・管理画面の表示用)。"""
    size = _read_value(CURSORS_KEY, "CursorBaseSize")
    cursor_type = _read_value(ACCESSIBILITY_KEY, "CursorType")
    arrow = _read_value(CURSORS_KEY, "Arrow")
    return {
        "base_size": int(size[0]) if size else CURSOR_SIZE_DEFAULT,
        "cursor_type": int(cursor_type[0]) if cursor_type else 0,
        "arrow": str(arrow[0]) if arrow else "(既定)",
    }


def _registry_sources() -> dict[str, str]:
    """いまレジストリが指しているカーソルファイルのパス。

    REG_EXPAND_SZ なので %SystemRoot% などを展開する。空文字のエントリ
    (OS 内蔵カーソルを使う指定) は含めない。
    """
    sources: dict[str, str] = {}
    for slot in SLOTS:
        found = _read_value(CURSORS_KEY, slot.name)
        if not found or not isinstance(found[0], str) or not found[0].strip():
            continue
        path = os.path.expandvars(found[0])
        if Path(path).exists():
            sources[slot.name] = path
    return sources


# ------------------------------------------------------------------ 生成と適用

def generate_cursor_files(color: str, out_dir: Path | None = None) -> dict[str, str]:
    """指定色のカーソル一式を生成し、{レジストリ値名: パス} を返す。"""
    rgb = hex_to_rgb(color)
    out_dir = out_dir or cursor_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    templates = _template_dir()

    written: dict[str, str] = {}
    for slot in SLOTS:
        dst = out_dir / slot.output
        if slot.template is None:
            builder = curfile.build_ibeam if slot.name == "IBeam" else curfile.build_crosshair
            dst.write_bytes(builder(rgb))
        else:
            src = templates / slot.template
            if not src.exists():
                continue  # テンプレートが無い Windows では、その種別だけ既定のまま
            curfile.colorize(src, dst, rgb)
        # レジストリに書くパスは、仮想化を通り抜けた実体でなければならない
        written[slot.name] = real_path(str(dst))
    return written


def install_system_cursors(sources: dict[str, str], size: int, log=None) -> tuple[int, int]:
    """指定サイズのカーソルをセッション全体に載せる。(成功数, 対象数) を返す。

    SM_CXCURSOR を無視して寸法を直接指定するので、既に起動しているアプリにも
    その場で効く。ファイルの指定が無い種別は OS 内蔵カーソルを拡縮して使う。
    """
    say = log or (lambda _message: None)
    targets = [slot for slot in SLOTS if slot.ocr is not None]
    installed = 0
    failed: list[str] = []

    for slot in targets:
        handle = load_cursor_at_size(sources.get(slot.name), slot.ocr, size)
        if handle and set_system_cursor(handle, slot.ocr):
            installed += 1
        else:
            failed.append(slot.label)

    if failed:
        say("差し替えできなかったカーソル: " + "、".join(failed))
    skipped = [slot.label for slot in SLOTS if slot.ocr is None]
    if skipped:
        say("サイズ指定に対応しない種別（再ログオン後に反映）: " + "、".join(skipped))
    return installed, len(targets)


def apply(config: Config, log=None) -> None:
    """設定の色・サイズを Windows に反映する。

    log: 進捗を受け取る呼び出し可能オブジェクト (管理画面のログ欄など)
    """
    say = log or (lambda _message: None)

    if not config.cursor_backup:
        config.cursor_backup = read_backup()
        say("現在のカーソル設定を退避しました（「既定に戻す」で復元できます）")

    generated: dict[str, str] = {}
    if config.cursor_color is None:
        # 色は Windows 既定のまま。ファイルの指定だけ元に戻す
        _apply_backup(config.cursor_backup)
        say("カーソル色: Windows の設定のまま")
    else:
        generated = generate_cursor_files(config.cursor_color)
        say(f"カーソル画像 {len(generated)} 個を {config.cursor_color} で生成しました")
        for name, path in generated.items():
            _write_value(CURSORS_KEY, name, path, winreg.REG_SZ)
        _write_value(CURSORS_KEY, "Scheme Source", SCHEME_SOURCE_USER, winreg.REG_DWORD)
        _write_value(CURSORS_KEY, "", "ime_cursor", winreg.REG_SZ)
        # Windows 側の配色機能を切る。付けたままだと再ログオン時に上書きされる
        _write_value(ACCESSIBILITY_KEY, "CursorType", CURSOR_TYPE_DEFAULT, winreg.REG_DWORD)
        say(f"カーソル色: {config.cursor_color}")

    # 再ログオン後の初期値。実行中のサイズ変更は SetSystemCursor が受け持つ
    _write_value(CURSORS_KEY, "CursorBaseSize", config.cursor_size, winreg.REG_DWORD)

    # まずレジストリの内容を全プロセスに読み直させ (色と、サイズ非対応の種別)、
    # そのうえで寸法を指定したカーソルを載せる。順番を逆にすると上書きされる
    if not broadcast_cursor_change():
        say("警告: SPI_SETCURSORS が失敗しました")

    installed, total = install_system_cursors(
        generated if config.cursor_color else _registry_sources(), config.cursor_size, say
    )
    say(f"サイズ {config.cursor_size}px のカーソルを {installed}/{total} 種類に適用しました")


def restore_default(config: Config, log=None) -> None:
    """色・サイズを、このツールを使う前の状態に戻す。"""
    say = log or (lambda _message: None)

    if config.cursor_backup:
        _apply_backup(config.cursor_backup)
        say("退避してあったカーソル設定に戻しました")
    else:
        for slot in SLOTS:
            _delete_value(CURSORS_KEY, slot.name)
        _write_value(CURSORS_KEY, "CursorBaseSize", CURSOR_SIZE_DEFAULT, winreg.REG_DWORD)
        say("退避データが無いため、Windows 標準のカーソルに戻しました")

    config.cursor_color = None
    config.cursor_size = current_state()["base_size"]

    # SPI_SETCURSORS はレジストリからカーソルを読み直すので、
    # SetSystemCursor で載せたものもここで捨てられる
    if broadcast_cursor_change():
        say(f"カーソルを元に戻しました（サイズ {config.cursor_size}px）")
    else:
        say("警告: SPI_SETCURSORS が失敗しました。サインアウトすると反映されます")
