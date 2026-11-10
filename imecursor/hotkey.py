"""グローバルホットキーを専用スレッドで待ち受ける。

`RegisterHotKey` に `hwnd=NULL` を渡すと `WM_HOTKEY` は「登録したスレッドの」
メッセージキューに積まれる。tkinter のメッセージポンプはスレッドメッセージも
`GetMessage` で拾ってしまうが、`hwnd` が NULL なので `DispatchMessage` が何も
せずに捨ててしまう。つまり Tk のイベントループで待っていても永久に届かない。

そこで登録と `GetMessageW` ループを専用スレッドに閉じ込め、押されたことだけを
`queue.Queue` 経由で Tk 側へ渡す (`RegisterHotKey` とメッセージループは同じ
スレッドである必要がある)。Tk のウィジェットはこのスレッドから触らない。

登録・解除の指示も、`GetMessageW` がブロックしていてキューを覗けないので
`PostThreadMessageW` でスレッドへ送る。

`RegisterHotKey` は押されたキーを奪う (下のアプリに届かない)。「押されたことは
知りたいが、キーは下のアプリにもそのまま渡したい」もの (マーカー中のスライド
送り) は `watch_keys` で低レベルキーボードフックを入れて覗く。フックも
メッセージループを回すスレッドで入れる必要があるので、同じスレッドに置く。
"""

from __future__ import annotations

import queue
import sys
import threading
from tkinter import TclError as tk_error

from .win32 import (
    ERROR_HOTKEY_ALREADY_REGISTERED,
    HC_ACTION,
    KBDLLHOOKSTRUCT,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    PM_NOREMOVE,
    VK_ESCAPE,
    VK_SPACE,
    WH_KEYBOARD_LL,
    WM_APP,
    WM_HOTKEY,
    WM_KEYDOWN,
    WM_QUIT,
    WM_SYSKEYDOWN,
    LowLevelKeyboardProc,
    kernel32,
    user32,
)
import ctypes
from ctypes import wintypes

# スレッドへ送る指示 (PostThreadMessageW の uMsg)
_MSG_REGISTER = WM_APP + 1
_MSG_UNREGISTER = WM_APP + 2
_MSG_HOOK = WM_APP + 3      # キーボードフックを入れる
_MSG_UNHOOK = WM_APP + 4    # キーボードフックを外す

# 押されたホットキーを Tk 側へ吸い出す間隔 (ミリ秒)
POLL_INTERVAL_MS = 40

# スレッドの起動と終了を待つ上限 (秒)
_START_TIMEOUT = 2.0
_STOP_TIMEOUT = 1.0

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "alt": MOD_ALT,
    "win": MOD_WIN,
}

_NAMED_KEYS = {
    "escape": VK_ESCAPE,
    "esc": VK_ESCAPE,
    "space": VK_SPACE,
}


def parse_combo(text: str) -> tuple[int, int]:
    """"ctrl+shift+l" を (修飾子ビット, 仮想キーコード) に変換する。

    修飾子は ctrl / control / shift / alt / win。キーは英数字 1 文字、
    f1〜f12、escape、space。解釈できなければ ValueError。
    """
    parts = [p.strip().lower() for p in str(text).split("+") if p.strip()]
    if not parts:
        raise ValueError("ホットキーが空です")

    mods = MOD_NOREPEAT
    key: int | None = None
    for part in parts:
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif key is not None:
            raise ValueError(f"キーが 2 つ以上あります: {text}")
        elif part in _NAMED_KEYS:
            key = _NAMED_KEYS[part]
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 12:
            key = 0x70 + int(part[1:]) - 1
        else:
            raise ValueError(f"解釈できないキーです: {part}")

    if key is None:
        raise ValueError(f"修飾子だけでキーがありません: {text}")
    return mods, key


def describe_combo(text: str) -> str:
    """"ctrl+shift+l" を "Ctrl+Shift+L" のような表示用の文字列にする。"""
    labels = {"ctrl": "Ctrl", "control": "Ctrl", "shift": "Shift", "alt": "Alt",
              "win": "Win", "escape": "Esc", "esc": "Esc", "space": "Space"}
    parts = [p.strip().lower() for p in str(text).split("+") if p.strip()]
    return "+".join(labels.get(p, p.upper()) for p in parts)


class HotkeyListener:
    """ホットキーの登録と受信。Tk とは Queue 越しにやりとりする。"""

    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._ids: dict[str, int] = {}       # 名前 -> ホットキー ID
        self._next_id = 1
        self._errors: dict[str, str] = {}    # 名前 -> 失敗理由
        self._lock = threading.Lock()
        self._pumping = False                # Tk 側のポーリングを続けるか
        self._root = None                    # ポーリングを張っている Tk のルート
        self._after_id: str | None = None    # 入れてある after の予約
        # watch_keys: 覗いているキー (仮想キーコード -> 名前)。フックの
        # コールバック (待ち受けスレッド) から読むので、差し替えは丸ごと代入で
        self._watched: dict[int, str] = {}

    # ---------------------------------------------------------------- 起動
    def start(self) -> bool:
        """待ち受けスレッドを立ち上げる。すでに動いていれば何もしない。"""
        if self._thread and self._thread.is_alive():
            return True
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="ime_cursor-hotkey", daemon=True
        )
        self._thread.start()
        return self._ready.wait(_START_TIMEOUT)

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def error_for(self, name: str) -> str | None:
        return self._errors.get(name)

    # ------------------------------------------------------------ 登録/解除
    def register(self, name: str, combo: str) -> None:
        """ホットキーを登録するようスレッドへ指示する (結果は非同期)。

        失敗しても例外は投げない。error_for(name) に理由が入る。
        """
        mods, key = parse_combo(combo)  # ここでの ValueError は呼び出し側で扱う
        with self._lock:
            hotkey_id = self._ids.get(name)
            if hotkey_id is None:
                hotkey_id = self._next_id
                self._next_id += 1
                self._ids[name] = hotkey_id
        self._errors.pop(name, None)
        self._post(_MSG_REGISTER, hotkey_id, (mods & 0xFFFF) | (key << 16))

    def unregister(self, name: str) -> None:
        hotkey_id = self._ids.get(name)
        if hotkey_id is not None:
            self._post(_MSG_UNREGISTER, hotkey_id, 0)

    def watch_keys(self, keys: dict[int, str]) -> None:
        """キーを奪わずに覗く。{仮想キーコード: 名前} を渡す。

        押されると名前が on_hotkey へ届く。キーは下のアプリにもそのまま渡る。
        失敗しても例外は投げない。error_for(名前) に理由が入る。
        """
        for name in set(keys.values()):
            self._errors.pop(name, None)
        self._watched = dict(keys)
        self._post(_MSG_HOOK, 0, 0)

    def unwatch_keys(self) -> None:
        # 先に空にしておけば、フックが外れるまでの間に押されても何も届かない
        self._watched = {}
        self._post(_MSG_UNHOOK, 0, 0)

    def _post(self, message: int, wparam: int, lparam: int) -> bool:
        if not self._thread_id:
            return False
        return bool(user32.PostThreadMessageW(self._thread_id, message, wparam, lparam))

    # ------------------------------------------------------------ Tk 側の受信
    def pump(self, root, on_hotkey, interval_ms: int = POLL_INTERVAL_MS) -> None:
        """押されたホットキーを Tk のイベントループで受け取る。

        root.after で自分を再スケジュールし続ける。on_hotkey は Tk スレッドで
        呼ばれるので、そのままウィジェットを触ってよい。
        """
        self._pumping = True
        self._root = root

        def poll() -> None:
            self._after_id = None
            if not self._pumping:
                return
            while True:
                try:
                    name = self._queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    on_hotkey(name)
                except Exception as exc:
                    # 1 回の失敗でポーリングを止めない。ただし黙って捨てない
                    # (ここで飲み込むと、抜けられない不具合の原因が見えなくなる)
                    print(f"ime_cursor: ホットキー {name} の処理で例外: "
                          f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            try:
                self._after_id = root.after(interval_ms, poll)
            except tk_error:
                self._pumping = False  # root が壊された後は静かに止まる

        self._after_id = root.after(interval_ms, poll)

    # ---------------------------------------------------------------- 終了
    def stop(self) -> None:
        """スレッドを畳む。登録の解除は登録したスレッド自身にやらせる。"""
        # 入れてある after を取り消す。残したまま root.destroy() されると
        # 「invalid command name ...poll」で Tcl のエラーになる
        self._pumping = False
        if self._after_id is not None and self._root is not None:
            try:
                self._root.after_cancel(self._after_id)
            except tk_error:
                pass
            self._after_id = None
        if not self.alive:
            return
        self._post(WM_QUIT, 0, 0)
        self._thread.join(_STOP_TIMEOUT)  # daemon なので念のため程度

    # ------------------------------------------------------- スレッド本体
    def _run(self) -> None:
        self._thread_id = int(kernel32.GetCurrentThreadId())
        registered: dict[int, str] = {}
        hook = None

        def on_key(code: int, wparam: int, lparam: int) -> int:
            # ここで時間をかけると全アプリのキー入力が詰まるので、名前を
            # キューに積むだけにする。戻り値は必ず CallNextHookEx に任せる
            # (キーを下のアプリへ渡す)
            if code == HC_ACTION and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                name = self._watched.get(int(info.vkCode))
                if name:
                    self._queue.put(name)
            return user32.CallNextHookEx(None, code, wparam, lparam)

        # コールバックは参照を握っておかないと GC されて落ちる
        hook_proc = LowLevelKeyboardProc(on_key)

        # PeekMessage を 1 回呼んでスレッドのメッセージキューを作らせる。
        # キューができる前に PostThreadMessageW が来ると取りこぼす
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_NOREMOVE)
        self._ready.set()

        while True:
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result in (0, -1):  # WM_QUIT または失敗
                break

            if message.message == WM_HOTKEY:
                name = registered.get(int(message.wParam))
                if name:
                    self._queue.put(name)

            elif message.message == _MSG_REGISTER:
                hotkey_id = int(message.wParam)
                mods = int(message.lParam) & 0xFFFF
                key = (int(message.lParam) >> 16) & 0xFFFF
                name = self._name_for(hotkey_id)
                user32.UnregisterHotKey(None, hotkey_id)  # 二重登録を避ける
                if user32.RegisterHotKey(None, hotkey_id, mods, key):
                    registered[hotkey_id] = name
                else:
                    code = ctypes.get_last_error()
                    registered.pop(hotkey_id, None)
                    self._errors[name] = (
                        "他のアプリが使用中です"
                        if code == ERROR_HOTKEY_ALREADY_REGISTERED
                        else f"登録に失敗しました (エラー {code})"
                    )

            elif message.message == _MSG_UNREGISTER:
                hotkey_id = int(message.wParam)
                user32.UnregisterHotKey(None, hotkey_id)
                registered.pop(hotkey_id, None)

            elif message.message == _MSG_HOOK:
                if not hook:
                    hook = user32.SetWindowsHookExW(
                        WH_KEYBOARD_LL, hook_proc, kernel32.GetModuleHandleW(None), 0
                    )
                    if not hook:
                        code = ctypes.get_last_error()
                        for name in set(self._watched.values()):
                            self._errors[name] = f"キーの監視に失敗しました (エラー {code})"

            elif message.message == _MSG_UNHOOK:
                if hook:
                    user32.UnhookWindowsHookEx(hook)
                    hook = None

        for hotkey_id in list(registered):
            user32.UnregisterHotKey(None, hotkey_id)
        if hook:
            user32.UnhookWindowsHookEx(hook)
        self._thread_id = 0

    def _name_for(self, hotkey_id: int) -> str:
        with self._lock:
            for name, value in self._ids.items():
                if value == hotkey_id:
                    return name
        return str(hotkey_id)
