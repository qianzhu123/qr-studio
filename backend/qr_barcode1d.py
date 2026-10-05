"""qr_barcode1d.py - From-scratch 1D barcode encoders.

Implements, with no third-party barcode library:
  - Code 128 (Code B, and Code C for even all-digit runs): full ASCII
  - Code 39 (standard 43-character set)
  - EAN-13, EAN-8, UPC-A (with check-digit computation)
  - ITF (Interleaved 2 of 5, even digit count)

Each encoder returns a list of module columns (1 = bar, 0 = space). Rendering
to PNG lives in render_1d_png.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# Code 128
# --------------------------------------------------------------------------

# 107 patterns of 6 element widths (bar,space,bar,space,bar,space); index=value.
_CODE128 = [
    (2,1,2,2,2,2),(2,2,2,1,2,2),(2,2,2,2,2,1),(1,2,1,2,2,3),(1,2,1,3,2,2),
    (1,3,1,2,2,2),(1,2,2,2,1,3),(1,2,2,3,1,2),(1,3,2,2,1,2),(2,2,1,2,1,3),
    (2,2,1,3,1,2),(2,3,1,2,1,2),(1,1,2,2,3,2),(1,2,2,1,3,2),(1,2,2,2,3,1),
    (1,1,3,2,2,2),(1,2,3,1,2,2),(1,2,3,2,2,1),(2,2,3,2,1,1),(2,2,1,1,3,2),
    (2,2,1,2,3,1),(2,1,3,2,1,2),(2,2,3,1,1,2),(3,1,2,1,3,1),(3,1,1,2,2,2),
    (3,2,1,1,2,2),(3,2,1,2,2,1),(3,1,2,2,1,2),(3,2,2,1,1,2),(3,2,2,2,1,1),
    (2,1,2,1,2,3),(2,1,2,3,2,1),(2,3,2,1,2,1),(1,1,1,3,2,3),(1,3,1,1,2,3),
    (1,3,1,3,2,1),(1,1,2,3,1,3),(1,3,2,1,1,3),(1,3,2,3,1,1),(2,1,1,3,1,3),
    (2,3,1,1,1,3),(2,3,1,3,1,1),(1,1,2,1,3,3),(1,1,2,3,3,1),(1,3,2,1,3,1),
    (1,1,3,1,2,3),(1,1,3,3,2,1),(1,3,3,1,2,1),(3,1,3,1,2,1),(2,1,1,3,3,1),
    (2,3,1,1,3,1),(2,1,3,1,1,3),(2,1,3,3,1,1),(2,1,3,1,3,1),(3,1,1,1,2,3),
    (3,1,1,3,2,1),(3,3,1,1,2,1),(3,1,2,1,1,3),(3,1,2,3,1,1),(3,3,2,1,1,1),
    (3,1,4,1,1,1),(2,2,1,4,1,1),(4,3,1,1,1,1),(1,1,1,2,2,4),(1,1,1,4,2,2),
    (1,2,1,1,2,4),(1,2,1,4,2,1),(1,4,1,1,2,2),(1,4,1,2,2,1),(1,1,2,2,1,4),
    (1,1,2,4,1,2),(1,2,2,1,1,4),(1,2,2,4,1,1),(1,4,2,1,1,2),(1,4,2,2,1,1),
    (2,4,1,2,1,1),(2,2,1,1,1,4),(4,1,3,1,1,1),(2,4,1,1,1,2),(1,3,4,1,1,1),
    (1,1,1,2,4,2),(1,2,1,1,4,2),(1,2,1,2,4,1),(1,1,4,2,1,2),(1,2,4,1,1,2),
    (1,2,4,2,1,1),(4,1,1,2,1,2),(4,2,1,1,1,2),(4,2,1,2,1,1),(2,1,2,1,4,1),
    (2,1,4,1,2,1),(4,1,2,1,2,1),(1,1,1,1,4,3),(1,1,1,3,4,1),(1,3,1,1,4,1),
    (1,1,4,1,1,3),(1,1,4,3,1,1),(4,1,1,1,1,3),(4,1,1,3,1,1),(1,1,3,1,4,1),
    (1,1,4,1,3,1),(3,1,1,1,4,1),(4,1,1,1,3,1),(2,1,1,4,1,2),(2,1,1,2,1,4),
    (2,1,1,2,3,2),
]
_CODE128_STOP = (2, 3, 3, 1, 1, 1, 2)  # 7 elements
_START_B, _START_C = 104, 105


def _code128_values(text: str) -> list[int]:
    """Return code values including start and checksum for Code B / Code C."""
    # Use Code C only when the whole string is an even-length digit run.
    if text.isdigit() and len(text) % 2 == 0 and len(text) >= 2:
        codes = [_START_C]
        i = 0
        while i < len(text):
            codes.append(int(text[i:i + 2])); i += 2
    else:
        codes = [_START_B]
        for ch in text:
            o = ord(ch)
            if not 32 <= o <= 127:
                raise ValueError(f"Code128 supports ASCII 32-127, got {ch!r}")
            codes.append(o - 32)
    check = codes[0]
    for i, v in enumerate(codes[1:], start=1):
        check += i * v
    codes.append(check % 103)
    return codes


def code128(text: str, module_px: int = 1):
    bits: list[int] = []
    for v in _code128_values(text):
        for k, w in enumerate(_CODE128[v]):
            bits += [k % 2 == 0] * w  # even element = bar
    for k, w in enumerate(_CODE128_STOP):
        bits += [k % 2 == 0] * w
    return bits


# --------------------------------------------------------------------------
# Code 39
# --------------------------------------------------------------------------

_CODE39 = {
    "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn",
    "4": "nnnwwnnnw", "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw",
    "8": "wnnwnnwnn", "9": "nnwwnnwnn", "A": "wnnnnwnnw", "B": "nnwnnwnnw",
    "C": "wnwnnwnnn", "D": "nnnnwwnnw", "E": "wnnnwwnnn", "F": "nnwnwwnnn",
    "G": "nnnnnwwnw", "H": "wnnnnwwnn", "I": "nnwnnwwnn", "J": "nnnnwwwnn",
    "K": "wnnnnnnww", "L": "nnwnnnnww", "M": "wnwnnnnwn", "N": "nnnnwnnww",
    "O": "wnnnwnnwn", "P": "nnwnwnnwn", "Q": "nnnnnnwww", "R": "wnnnnnwwn",
    "S": "nnwnnnwwn", "T": "nnnnwnwwn", "U": "wwnnnnnnw", "V": "nwwnnnnnw",
    "W": "wwwnnnnnn", "X": "nwnnwnnnw", "Y": "wwnnwnnnn", "Z": "nwwnwnnnn",
    "-": "nwnnnnwnw", ".": "wwnnnnwnn", " ": "nwwnnnwnn", "$": "nwnwnwnnn",
    "/": "nwnwnnnwn", "+": "nwnnnwnwn", "%": "nnnwnwnwn", "*": "nwnnwnwnn",
}


def code39(text: str, wide: int = 3, narrow: int = 1, gap: int = 1):
    text = text.upper()
    seq = "*" + text + "*"
    bits: list[int] = []
    for ci, ch in enumerate(seq):
        if ch not in _CODE39:
            raise ValueError(f"Code39 cannot encode {ch!r}")
        pat = _CODE39[ch]
        if ci:
            bits += [False] * gap
        for k, e in enumerate(pat):
            bits += [k % 2 == 0] * (wide if e == "w" else narrow)
    return bits


# --------------------------------------------------------------------------
# EAN / UPC
# --------------------------------------------------------------------------

_EAN_L = ["0001101", "0011001", "0010011", "0111101", "0100011",
          "0110001", "0101111", "0111011", "0110111", "0001011"]
_EAN_G = ["0100111", "0110011", "0011011", "0100001", "0011101",
          "0111001", "0000101", "0010001", "0001001", "0010111"]
_EAN_R = ["1110010", "1100110", "1101100", "1000010", "1011100",
          "1001110", "1010000", "1000100", "1001000", "1110100"]
_EAN_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
               "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def ean_checksum(digits: str) -> int:
    total = 0
    for i, d in enumerate(reversed(digits)):
        total += int(d) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def _guard_bits(s: str) -> list[bool]:
    return [c == "1" for c in s]


def ean13(digits: str):
    digits = digits.strip()
    if len(digits) == 12:
        digits += str(ean_checksum(digits))
    if len(digits) != 13 or not digits.isdigit():
        raise ValueError("EAN-13 needs 12 or 13 digits")
    parity = _EAN_PARITY[int(digits[0])]
    bits = _guard_bits("101")
    for i in range(6):
        d = int(digits[1 + i])
        bits += _guard_bits(_EAN_L[d] if parity[i] == "L" else _EAN_G[d])
    bits += _guard_bits("01010")
    for i in range(6):
        bits += _guard_bits(_EAN_R[int(digits[7 + i])])
    bits += _guard_bits("101")
    return bits


def ean8(digits: str):
    digits = digits.strip()
    if len(digits) == 7:
        digits += str(ean_checksum(digits))
    if len(digits) != 8 or not digits.isdigit():
        raise ValueError("EAN-8 needs 7 or 8 digits")
    bits = _guard_bits("101")
    for i in range(4):
        bits += _guard_bits(_EAN_L[int(digits[i])])
    bits += _guard_bits("01010")
    for i in range(4):
        bits += _guard_bits(_EAN_R[int(digits[4 + i])])
    bits += _guard_bits("101")
    return bits


def upca(digits: str):
    digits = digits.strip()
    if len(digits) == 11:
        digits += str(ean_checksum(digits))
    if len(digits) != 12 or not digits.isdigit():
        raise ValueError("UPC-A needs 11 or 12 digits")
    return ean13("0" + digits)


# --------------------------------------------------------------------------
# ITF (Interleaved 2 of 5)
# --------------------------------------------------------------------------

_ITF = ["nnwwn", "wnnnw", "nwnnw", "wwnnn", "nnwnw",
        "wnwnn", "nwwnn", "nnnww", "wnnwn", "nwnwn"]


def itf(text: str, wide: int = 3, narrow: int = 1):
    text = text.strip()
    if not text.isdigit():
        raise ValueError("ITF needs digits")
    if len(text) % 2:
        text = "0" + text  # pad to even length
    bits: list[bool] = []
    # start: narrow bar, narrow space, narrow bar, narrow space
    bits += [True] + [False] + [True] + [False]
    for i in range(0, len(text), 2):
        bars = _ITF[int(text[i])]
        spaces = _ITF[int(text[i + 1])]
        for k in range(5):
            bits += [True] * (wide if bars[k] == "w" else narrow)
            bits += [False] * (wide if spaces[k] == "w" else narrow)
    # stop: wide bar, narrow space, narrow bar
    bits += [True] * (wide * narrow if False else 3) + [False] + [True]
    return bits


# --------------------------------------------------------------------------
# Registry + rendering
# --------------------------------------------------------------------------

NATIVE = {
    "code128": code128,
    "code39": lambda t: code39(t),
    "ean13": ean13,
    "ean8": ean8,
    "upca": upca,
    "itf": itf,
}


def render_1d_png(bits: list[bool], height: int = 220, module_px: int = 3,
                  quiet_zone: int = 20, fg: str = "#000000", bg: str = "#ffffff",
                  text: str | None = None):
    """Render a 1D module list to PNG bytes (quiet_zone in modules)."""
    import io
    from PIL import Image, ImageDraw

    def _c(s):
        s = s.lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))

    n = len(bits) + 2 * quiet_zone
    w = n * module_px
    text_h = 34 if text else 0
    img = Image.new("RGB", (w, height + text_h), bg)
    dr = ImageDraw.Draw(img)
    for i, b in enumerate(bits):
        if b:
            x = (i + quiet_zone) * module_px
            dr.rectangle([x, 0, x + module_px - 1, height - 1], fill=_c(fg))
    if text:
        try:
            from PIL import ImageFont
            font = ImageFont.load_default()
        except Exception:
            font = None
        tw = dr.textlength(text, font=font) if font else len(text) * 6
        dr.text(((w - tw) / 2, height + 6), text, fill=_c(fg), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_1d_svg(bits: list[bool], height: int = 120, module_px: int = 2,
                  quiet_zone: int = 20, fg: str = "#000000", bg: str = "#ffffff") -> str:
    n = len(bits) + 2 * quiet_zone
    w = n * module_px
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{height}" '
             f'viewBox="0 0 {w} {height}" shape-rendering="crispEdges">',
             f'<rect width="{w}" height="{height}" fill="{bg}"/>']
    for i, b in enumerate(bits):
        if b:
            parts.append(f'<rect x="{(i + quiet_zone) * module_px}" y="0" '
                         f'width="{module_px}" height="{height}" fill="{fg}"/>')
    parts.append("</svg>")
    return "\n".join(parts)
