"""設定ファイル (JSON) の読み書き。

管理画面で変更した内容はここに保存し、次回起動時にそのまま復元する。

    設定     %USERPROFILE%\\.ime_cursor\\config.json
    生成物   %USERPROFILE%\\.ime_cursor\\cursors\\*.cur

置き場所が %APPDATA% ではなくユーザーフォルダ直下なのは、Microsoft Store 版
Python が %APPDATA% / %LOCALAPPDATA% への書き込みをパッケージ配下の LocalCache
に転送してしまうため。生成したカーソルのパスはレジストリに書いて他のプロセス
から開かせる必要があるので、転送されない場所に置く。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "ime_cursor"

# マウスカーソルのサイズ (px)。Windows の「マウスポインターのサイズ」と同じ範囲
CURSOR_SIZE_MIN = 32
CURSOR_SIZE_MAX = 256
CURSOR_SIZE_DEFAULT = 32

# バッジの色分け。IME の状態 (ImeState.kind) ごとの (背景色, 文字色)
PALETTE = {
    "hiragana": ("#d32f2f", "#ffffff"),    # あ  ひらがな
    "kana": ("#f57c00", "#ffffff"),        # カ  カタカナ
    "alnum": ("#37474f", "#ffffff"),       # A   半角英数 / 直接入力
    "alnum-full": ("#00796b", "#ffffff"),  # Ａ  全角英数
    "unknown": ("#6a1b9a", "#ffffff"),     # ?   取得できず
}

# 管理画面とバッジで使うフォント。先頭から順に探し、見つかったものを使う
FONT_CANDIDATES = ("Yu Gothic UI", "游ゴシック", "Meiryo UI", "Meiryo", "BIZ UDGothic")

# ------------------------------------------------ プレゼン用マーカー
# 描画層のキー色 (-transparentcolor)。この色のピクセルは表示も当たり判定も
# 抜けるので、誰も描かない色にしておく
MARKER_KEY_COLOR = "#010203"

MARKER_WIDTH_MIN = 1
MARKER_WIDTH_MAX = 32
MARKER_WIDTH_DEFAULT = 4

MARKER_HOTKEY_DEFAULT = "ctrl+shift+l"

# 溜められる枠の数の上限。増えすぎると描画が重くなる
MARKER_MAX_SHAPES = 200

# 入力を受ける層の不透明度。一律アルファは当たり判定を透過させないので、
# ほぼ透明にしてもドラッグを拾える。ただし 0.0 は「完全透過」扱いになり
# 当たり判定が抜けてしまうため、下限を丸める (実測)
MARKER_CATCH_ALPHA_MIN = 0.01
MARKER_CATCH_ALPHA_MAX = 0.30
MARKER_CATCH_ALPHA_DEFAULT = 0.02

# マーカーの色プリセット (表示名, #RRGGBB)
MARKER_COLOR_PRESETS = (
    ("レッド", "#ff0000"),
    ("イエロー", "#ffff00"),
    ("ライム", "#00ff00"),
    ("シアン", "#00ffff"),
    ("マゼンタ", "#ff00ff"),
    ("ブラック", "#000000"),
)

# 管理画面のカーソル色プリセット (表示名, #RRGGBB)
COLOR_PRESETS = (
    ("ライム", "#00ff00"),
    ("イエロー", "#ffff00"),
    ("オレンジ", "#ff8c00"),
    ("レッド", "#ff0000"),
    ("マゼンタ", "#ff00ff"),
    ("シアン", "#00ffff"),
    ("ブルー", "#1e90ff"),
    ("ブラック", "#000000"),
)


def data_dir() -> Path:
    """設定と生成物の置き場所。仮想化されない、ユーザーフォルダ直下。"""
    base = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(base) / f".{APP_NAME}"


def config_path() -> Path:
    return data_dir() / "config.json"


def cursor_output_dir() -> Path:
    return data_dir() / "cursors"


def show_admin_flag_path() -> Path:
    """2 回目の起動が「管理画面を出して」と伝えるための目印ファイル。"""
    return data_dir() / "show_admin.flag"


@dataclass
class Config:
    # -- IME バッジ --------------------------------------------------------
    badge_enabled: bool = True
    hide_alnum: bool = False      # 半角英数・直接入力のときはバッジを隠す
    verbose: bool = False         # 「あ ひらがな」のように説明も出す
    font_size: int = 16           # バッジの文字サイズ (px)
    alpha: float = 0.85           # 不透明度 (0.0-1.0)
    offset_x: int = 20            # カーソルからのオフセット (px)
    offset_y: int = 20
    follow_cursor_size: bool = True  # カーソルが大きいときオフセットも広げる
    interval_ms: int = 30         # 位置と状態の更新間隔 (ミリ秒)

    # -- マウスカーソル ----------------------------------------------------
    cursor_color: str | None = None       # None なら Windows 既定のまま
    cursor_size: int = CURSOR_SIZE_DEFAULT

    # 初めて色・サイズを変える直前のレジストリ値。「既定に戻す」で使う
    cursor_backup: dict = field(default_factory=dict)

    # -- プレゼン用マーカー ------------------------------------------------
    marker_hotkey_enabled: bool = True                      # ホットキーを登録するか
    marker_hotkey: str = MARKER_HOTKEY_DEFAULT              # モードの切り替え
    marker_color: str = "#ff0000"                           # 枠の色
    marker_width: int = MARKER_WIDTH_DEFAULT                # 枠の太さ (px)
    marker_catch_alpha: float = MARKER_CATCH_ALPHA_DEFAULT  # 入力を受ける層の不透明度

    # -- 管理画面 ----------------------------------------------------------
    admin_geometry: str = ""      # 前回の管理画面の位置

    def clamp(self) -> "Config":
        """設定ファイルを手で書き換えられていても破綻しないよう丸める。"""
        self.font_size = max(6, min(int(self.font_size), 200))
        self.alpha = max(0.1, min(float(self.alpha), 1.0))
        self.interval_ms = max(10, min(int(self.interval_ms), 1000))
        self.cursor_size = max(CURSOR_SIZE_MIN, min(int(self.cursor_size), CURSOR_SIZE_MAX))
        if self.cursor_color is not None:
            self.cursor_color = normalize_hex_color(self.cursor_color)

        self.marker_width = max(
            MARKER_WIDTH_MIN, min(int(self.marker_width), MARKER_WIDTH_MAX)
        )
        # 0.0 まで下げると完全透過とみなされ、当たり判定が抜けてドラッグを
        # 受け取れなくなる。Tk は 1 バイトに量子化するので下限は 0.01
        self.marker_catch_alpha = max(
            MARKER_CATCH_ALPHA_MIN,
            min(float(self.marker_catch_alpha), MARKER_CATCH_ALPHA_MAX),
        )
        self.marker_color = normalize_hex_color(self.marker_color) or "#ff0000"
        if self.marker_color == MARKER_KEY_COLOR:
            self.marker_color = "#ff0000"  # キー色と同じだと枠がまるごと消える
        if not isinstance(self.marker_hotkey, str) or not self.marker_hotkey.strip():
            self.marker_hotkey = MARKER_HOTKEY_DEFAULT
        return self

    def save(self) -> Path:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)  # 書き込み中に落ちても設定を壊さない
        return path


def normalize_hex_color(text: object) -> str | None:
    """色の指定を "#rrggbb" に揃える。解釈できなければ None。

    "#f00" / "ff0000" / "#FF0000" のような書き方をまとめて受け取るため、
    設定ファイルを手で書き換えたときにも、ポップアップの入力欄にも使える。
    """
    if not isinstance(text, str):
        return None
    value = text.strip().lstrip("#").lower()
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)  # #f00 -> #ff0000
    if len(value) != 6:
        return None
    try:
        int(value, 16)
    except ValueError:
        return None
    return f"#{value}"


def _is_hex_color(value: object) -> bool:
    return normalize_hex_color(value) is not None


def load() -> Config:
    """設定を読む。壊れていても既定値で起動する。"""
    path = config_path()
    if not path.exists():
        return Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    if not isinstance(raw, dict):
        return Config()
    known = {f.name for f in fields(Config)}
    return Config(**{k: v for k, v in raw.items() if k in known}).clamp()


def contrast_fg(color: str) -> str:
    """背景色に対して読める文字色 (白か黒) を返す。"""
    r, g, b = hex_to_rgb(color)
    return "#000000" if (r * 77 + g * 151 + b * 28) >> 8 > 140 else "#ffffff"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb
