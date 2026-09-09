"""IME の状態 (ひらがな / カタカナ / 英数 など) を取得する。

1. GetForegroundWindow -> GetGUIThreadInfo で入力フォーカスを持つウィンドウを特定
2. ImmGetDefaultIMEWnd で対応する IME ウィンドウのハンドルを得る
3. WM_IME_CONTROL を送り、開閉状態と変換モードのビットフラグを読む

取得に一時的に失敗しても直前の状態を保持し、表示のちらつきを防ぐ。
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from .win32 import (
    IMC_GETCONVERSIONMODE,
    IMC_GETOPENSTATUS,
    IME_CMODE_FULLSHAPE,
    IME_CMODE_KATAKANA,
    IME_CMODE_NATIVE,
    LANG_JAPANESE,
    SMTO_ABORTIFHUNG,
    WM_IME_CONTROL,
    GUITHREADINFO,
    imm32,
    user32,
)

# 取得に失敗しても直前の状態を保持する回数
STICKY_LIMIT = 8

# IME の状態を色分けするための種別
KIND_HIRAGANA = "hiragana"
KIND_KANA = "kana"
KIND_ALNUM = "alnum"
KIND_ALNUM_FULL = "alnum-full"
KIND_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ImeState:
    label: str          # バッジに出す短い文字 ("あ" など)
    text: str           # 説明 ("ひらがな" など)
    kind: str           # 色分け用の種別 (KIND_*)
    open: int | None    # IME のオン / オフ。取得できなければ None
    mode: int | None    # IMC_GETCONVERSIONMODE の生の値


def _focus_hwnd() -> int:
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


def _query(ime_wnd: int, command: int) -> int | None:
    """応答しないアプリが前面にあってもフリーズしないよう、タイムアウト付きで送る。"""
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
    """フォーカス側 -> 前面ウィンドウ側の順に IME へ問い合わせる。"""
    fg = user32.GetForegroundWindow()
    candidates: list[int] = []
    focus = _focus_hwnd()
    if focus:
        candidates.append(focus)
    if fg and fg not in candidates:
        candidates.append(fg)

    for hwnd in candidates:
        ime_wnd = imm32.ImmGetDefaultIMEWnd(hwnd)
        if not ime_wnd:
            continue
        is_open = _query(ime_wnd, IMC_GETOPENSTATUS)
        if is_open is None:
            continue
        mode = _query(ime_wnd, IMC_GETCONVERSIONMODE) or 0
        return int(is_open), int(mode)
    return None


class ImeWatcher:
    """IME の状態を取得する。取得失敗時のちらつき防止のため状態を持つ。"""

    def __init__(self, sticky_limit: int = STICKY_LIMIT) -> None:
        self.sticky_limit = sticky_limit
        self._last_good: ImeState | None = None
        self._miss_count = 0

    def read(self) -> ImeState:
        langid = _keyboard_layout_langid() & 0x3FF
        queried = _query_open_and_mode()

        if queried is None:
            self._miss_count += 1
            if self._last_good is not None and self._miss_count <= self.sticky_limit:
                return self._last_good
            return ImeState("?", "IME 不明", KIND_UNKNOWN, None, None)

        self._miss_count = 0
        is_open, mode = queried

        if not is_open:
            # 日本語 IME 以外のレイアウト (英語配列など) もここに来る
            text = "直接入力" if langid == LANG_JAPANESE else "英字入力"
            self._last_good = ImeState("A", text, KIND_ALNUM, 0, mode)
            return self._last_good

        native = bool(mode & IME_CMODE_NATIVE)
        katakana = bool(mode & IME_CMODE_KATAKANA)
        full = bool(mode & IME_CMODE_FULLSHAPE)

        if native and katakana and full:
            label, text, kind = "カ", "全角カタカナ", KIND_KANA
        elif native and katakana:
            label, text, kind = "ｶ", "半角カタカナ", KIND_KANA
        elif native and full:
            label, text, kind = "あ", "ひらがな", KIND_HIRAGANA
        elif native:
            label, text, kind = "ｱ", "半角ひらがな", KIND_KANA
        elif full:
            label, text, kind = "Ａ", "全角英数", KIND_ALNUM_FULL
        else:
            label, text, kind = "A", "半角英数", KIND_ALNUM

        self._last_good = ImeState(label, text, kind, 1, mode)
        return self._last_good
