"""ime_cursor — IME 状態バッジとマウスカーソルの外観をまとめて管理する常駐ツール。

サブモジュール:
    win32        Win32 API (ctypes) の共通定義
    imestate     IME の状態取得
    config       設定ファイル (JSON) の読み書き
    curfile      .cur / .ani の着色と生成
    cursortheme  マウスカーソルの色・サイズの適用 (レジストリ)
    overlay      カーソル追従バッジ
    admin        管理画面 (tkinter)
    app          起動制御 (単一インスタンス・コマンドライン引数)
"""

__all__ = ["__version__"]
__version__ = "2.0.0"
