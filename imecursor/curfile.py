"""マウスカーソルファイル (.cur / .ani) の着色と生成。

Windows は「マウスポインターの色」を、%SystemRoot%\\cursors\\*.svg から
その場でレンダリングして %LOCALAPPDATA%\\Microsoft\\Windows\\Cursors\\*_eoa.cur
に書き出している。つまりレジストリの CursorColor を書き換えるだけでは
何も起こらない (SPI_SETCURSORS はレジストリが指すファイルを読み直すだけ)。

そこでこのモジュールは、Windows 自身と同じことを自前でやる。

- 「Windows Aero」スキームの aero_*.cur / aero_*.ani は、白い本体と黒い
  縁取りだけのグレースケール画像になっている。各ピクセルの輝度に目的の色を
  掛ければ、白 -> 指定色 / 黒 -> 黒 となり Windows 純正の着色結果と一致する
  (実測: 輝度 255 * 色 250 / 255 = 250、輝度 96 -> 94 と Windows の出力に一致)
- Aero スキームがテキストカーソルと十字カーソルを持たない (OS 内蔵の
  モノクロ版が使われる) ため、この 2 つだけは同じ見た目になるよう自前で描く

いずれも標準ライブラリだけで完結する。画像ライブラリは使わない。
"""

from __future__ import annotations

import struct
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# 自前で描くカーソルの内蔵サイズ。aero_*.cur と同じ 5 段にしておくと、
# Windows が DPI と CursorBaseSize から選ぶときの挙動がそろう
DRAWN_SIZES = (32, 48, 64, 96, 128)


# ------------------------------------------------------------------ 着色

def _luminance_luts(rgb: tuple[int, int, int]) -> tuple[bytes, bytes, bytes]:
    """輝度 0-255 を、指定色を掛けた B / G / R の値に写す変換表。"""
    r, g, b = rgb
    return (
        bytes((lum * b) // 255 for lum in range(256)),
        bytes((lum * g) // 255 for lum in range(256)),
        bytes((lum * r) // 255 for lum in range(256)),
    )


def _colorize_dib(buf: bytearray, start: int, limit: int, luts) -> bool:
    """32bpp の DIB 1 枚を、その場で着色する。アルファはそのまま残す。"""
    if start + 40 > limit:
        return False
    if bytes(buf[start:start + 8]) == PNG_SIGNATURE:
        return False  # PNG 圧縮エントリ (.ico 由来) は扱わない

    bi_size, width, height, _planes, bit_count = struct.unpack_from("<IiiHH", buf, start)
    if bit_count != 32 or bi_size < 40 or width <= 0:
        return False

    rows = abs(height) // 2 or abs(height)  # XOR マスクと AND マスクで 2 倍
    pixels = start + bi_size
    count = width * rows
    if count <= 0 or pixels + count * 4 > limit:
        return False

    lut_b, lut_g, lut_r = luts
    end = pixels + count * 4
    # テンプレートはグレースケールなので、緑をそのまま輝度として使える。
    # bytes.translate は C 側のループなので、.ani の全フレームでも一瞬で終わる
    lum = bytes(buf[pixels + 1:end:4])
    buf[pixels:end:4] = lum.translate(lut_b)
    buf[pixels + 2:end:4] = lum.translate(lut_r)
    buf[pixels + 1:end:4] = lum.translate(lut_g)
    return True


def _colorize_icon_blob(buf: bytearray, base: int, limit: int, luts) -> int:
    """base から始まる .cur / .ico を着色し、着色した画像の枚数を返す。"""
    if base + 6 > limit:
        return 0
    reserved, kind, count = struct.unpack_from("<HHH", buf, base)
    if reserved != 0 or kind not in (1, 2) or not 0 < count < 64:
        return 0

    done = 0
    for i in range(count):
        entry = base + 6 + 16 * i
        if entry + 16 > limit:
            break
        offset = struct.unpack_from("<I", buf, entry + 12)[0]
        if _colorize_dib(buf, base + offset, limit, luts):
            done += 1
    return done


def _colorize_ani(buf: bytearray, luts) -> int:
    """RIFF/ACON を走査し、フレームごとの icon チャンクを着色する。"""
    done = 0

    def walk(pos: int, end: int) -> None:
        nonlocal done
        while pos + 8 <= end:
            chunk_id = bytes(buf[pos:pos + 4])
            size = struct.unpack_from("<I", buf, pos + 4)[0]
            body = pos + 8
            if body + size > end:
                break
            if chunk_id == b"LIST":
                walk(body + 4, body + size)
            elif chunk_id == b"icon":
                done += _colorize_icon_blob(buf, body, body + size, luts)
            pos = body + size + (size & 1)  # チャンクは 2 バイト境界

    walk(12, len(buf))
    return done


def colorize(src: Path, dst: Path, rgb: tuple[int, int, int]) -> int:
    """src のカーソルを rgb で着色して dst に書き出す。着色した画像の枚数を返す。"""
    buf = bytearray(src.read_bytes())
    luts = _luminance_luts(rgb)

    if bytes(buf[0:4]) == b"RIFF" and bytes(buf[8:12]) == b"ACON":
        done = _colorize_ani(buf, luts)
    else:
        done = _colorize_icon_blob(buf, 0, len(buf), luts)

    if not done:
        raise ValueError(f"着色できる 32bpp 画像が見つかりません: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(buf))
    return done


# ------------------------------------------------------------------ 自前描画

def _write_cur(images: list[tuple[int, tuple[int, int], bytearray]]) -> bytes:
    """(サイズ, ホットスポット, 上から下の BGRA) の並びから .cur を組み立てる。"""
    count = len(images)
    entries = bytearray()
    blobs = bytearray()
    offset = 6 + 16 * count

    for size, (hx, hy), bgra in images:
        header = struct.pack(
            "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0
        )
        # DIB は下から上へ並べる
        rows = [bgra[y * size * 4:(y + 1) * size * 4] for y in range(size)]
        xor = b"".join(bytes(r) for r in reversed(rows))
        # 32bpp ではアルファが透過を決めるので、AND マスクは全ビット 0 (不透明)
        mask_stride = ((size + 31) // 32) * 4
        and_mask = b"\x00" * (mask_stride * size)

        blob = header + xor + and_mask
        entries += struct.pack(
            "<BBBBHHII", size & 0xFF, size & 0xFF, 0, 0, hx, hy, len(blob), offset
        )
        blobs += blob
        offset += len(blob)

    return struct.pack("<HHH", 0, 2, count) + bytes(entries) + bytes(blobs)


def _render(size: int, rects: list[tuple[int, int, int, int]], rgb: tuple[int, int, int],
            outline: int) -> bytearray:
    """矩形の集合を本体として塗り、外側に黒い縁取りを付けた BGRA を返す。

    各行を int のビットマスクで持ち、縁取りは横方向 -> 縦方向の 2 段で
    膨張させてから本体を引く (分離可能なので、半径に依存せず速い)。
    """
    body = [0] * size
    for x0, y0, x1, y1 in rects:
        x0 = max(0, x0); x1 = min(size, x1)
        if x1 <= x0:
            continue
        span = ((1 << (x1 - x0)) - 1) << x0
        for y in range(max(0, y0), min(size, y1)):
            body[y] |= span

    full = (1 << size) - 1
    wide = []
    for mask in body:
        acc = mask
        for k in range(1, outline + 1):
            acc |= (mask << k) | (mask >> k)
        wide.append(acc & full)

    r, g, b = rgb
    body_pixel = bytes((b, g, r, 255))
    out = bytearray(size * size * 4)
    for y in range(size):
        grown = 0
        for k in range(max(0, y - outline), min(size, y + outline + 1)):
            grown |= wide[k]
        filled = body[y]
        edge = grown & ~filled
        if not grown:
            continue
        base = y * size * 4
        for x in range(size):
            bit = 1 << x
            if filled & bit:
                out[base + x * 4:base + x * 4 + 4] = body_pixel
            elif edge & bit:
                out[base + x * 4 + 3] = 255  # 黒 (BGR は 0 のまま) で不透明
    return out


def _scaled(size: int, ratio: float, minimum: int) -> int:
    return max(minimum, round(size * ratio))


def build_ibeam(rgb: tuple[int, int, int], sizes=DRAWN_SIZES) -> bytes:
    """テキストカーソル (I 字) を描いた .cur を作る。"""
    images = []
    for size in sizes:
        stem = _scaled(size, 0.05, 2)
        serif_w = _scaled(size, 0.1875, 6)
        serif_t = _scaled(size, 0.05, 2)
        total_h = _scaled(size, 0.625, 14)
        cx = cy = size // 2
        top = cy - total_h // 2
        bottom = top + total_h
        rects = [
            (cx - stem // 2, top, cx - stem // 2 + stem, bottom),                    # 縦棒
            (cx - serif_w // 2, top, cx - serif_w // 2 + serif_w, top + serif_t),    # 上の横棒
            (cx - serif_w // 2, bottom - serif_t, cx - serif_w // 2 + serif_w, bottom),
        ]
        outline = max(1, round(size / 32))
        images.append((size, (cx, cy), _render(size, rects, rgb, outline)))
    return _write_cur(images)


def build_crosshair(rgb: tuple[int, int, int], sizes=DRAWN_SIZES) -> bytes:
    """十字カーソルを描いた .cur を作る。"""
    images = []
    for size in sizes:
        arm = _scaled(size, 0.4375, 10)
        thick = _scaled(size, 0.0625, 2)
        cx = cy = size // 2
        half = thick // 2
        rects = [
            (cx - arm, cy - half, cx + arm, cy - half + thick),  # 横棒
            (cx - half, cy - arm, cx - half + thick, cy + arm),  # 縦棒
        ]
        outline = max(1, round(size / 32))
        images.append((size, (cx, cy), _render(size, rects, rgb, outline)))
    return _write_cur(images)
