# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ime_cursor — IME 状態バッジ + マウスカーソルの色・サイズを管理する常駐ツール。

    ime_cursor.pyw                管理画面を出して常駐する
                                  （常駐中にもう一度実行すると管理画面が戻る）
    ime_cursor.pyw --silent       管理画面を出さずに常駐する（自動起動向け）
    ime_cursor.pyw --debug        GUI を出さず IME 状態をコンソールに出す
    ime_cursor.pyw --reset-cursor カーソルの色とサイズを既定に戻して終了する

.pyw は pythonw.exe に関連付けられているため、ダブルクリックでコンソール
（黒い窓）を出さずに起動できる。実装は imecursor パッケージにある。

終了 (コマンドラインで判別するので、他の .pyw スクリプトは巻き込まない):
    powershell -NoProfile -Command "Get-CimInstance Win32_Process |
      Where-Object { $_.CommandLine -like '*ime_cursor.pyw*' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
"""

import sys
from pathlib import Path

# ダブルクリック起動でも、UNC パス経由の起動でも imecursor を見つけられるように
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform != "win32":
    sys.exit(
        "このツールは Windows 上で実行してください。\n"
        "WSL からは: powershell.exe -NoProfile -Command \"pythonw ime_cursor.pyw\""
    )

from imecursor.app import main  # noqa: E402  (sys.path を通したあとに import する)

if __name__ == "__main__":
    raise SystemExit(main())
