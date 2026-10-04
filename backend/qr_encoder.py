"""qr_encoder.py - A from-scratch QR Code encoder (no third-party QR library).

Scope (ISO/IEC 18004):
  - Data modes: numeric / alphanumeric / byte / kanji (Shift-JIS) / ECI /
    FNC1 (GS1) / structured append
  - Reed-Solomon error correction over GF(256) (primitive polynomial 0x11D)
  - Versions 1..40, error levels L/M/Q/H
  - Function patterns: finders, separators, alignment, timing, dark module,
    format info, version info
  - All 8 masks with penalty scoring (auto pick) or a forced mask
  - Optional round-trip verification hook (see build.py)

Design goal: full controllability down to mode / charset / ECI / FNC1 /
forced version / forced mask / structured append.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------------
# Constant tables
# --------------------------------------------------------------------------

# Error-correction codewords per block. Index = version (slot 0 unused).
ECC_CODEWORDS_PER_BLOCK = {
    "L": [0, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28,
          28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    "M": [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26,
          26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    "Q": [0, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26,
          30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    "H": [0, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26,
          28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
}

# Number of error-correction blocks. Index = version (slot 0 unused).
ECC_BLOCKS = {
    "L": [0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7,
          8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    "M": [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14,
          16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
    "Q": [0, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21,
          20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
    "H": [0, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25,
          25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81],
}

EC_ORDER = ["L", "M", "Q", "H"]
# 2-bit EC indicator used inside the format information (note: not L,M,Q,H order)
EC_FORMAT_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}

ALIGN_POSITIONS = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
    11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62], 14: [6, 26, 46, 66],
    15: [6, 26, 48, 70], 16: [6, 26, 50, 74], 17: [6, 30, 54, 78], 18: [6, 30, 56, 82],
    19: [6, 30, 58, 86], 20: [6, 34, 62, 90], 21: [6, 28, 50, 72, 94], 22: [6, 26, 50, 74, 98],
    23: [6, 30, 54, 78, 102], 24: [6, 28, 54, 80, 106], 25: [6, 32, 58, 84, 110],
    26: [6, 30, 58, 86, 114], 27: [6, 34, 62, 90, 118], 28: [6, 26, 50, 74, 98, 122],
    29: [6, 30, 54, 78, 102, 126], 30: [6, 26, 52, 78, 104, 130], 31: [6, 30, 56, 82, 108, 134],
    32: [6, 34, 60, 86, 112, 138], 33: [6, 30, 58, 86, 114, 142], 34: [6, 34, 62, 90, 118, 146],
    35: [6, 30, 54, 78, 102, 126, 150], 36: [6, 24, 50, 76, 102, 128, 154],
    37: [6, 28, 54, 80, 106, 132, 158], 38: [6, 32, 58, 84, 110, 136, 162],
    39: [6, 26, 54, 82, 110, 138, 166], 40: [6, 30, 58, 86, 114, 142, 170],
}

# Mode indicators
MODE_NUMERIC = 0x1
MODE_ALPHANUMERIC = 0x2
MODE_BYTE = 0x4
MODE_KANJI = 0x8
MODE_ECI = 0x7
MODE_FNC1_FIRST = 0x5
MODE_FNC1_SECOND = 0x9
MODE_STRUCTURED = 0x3

ALNUM_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"


# --------------------------------------------------------------------------
# GF(256) and Reed-Solomon
# --------------------------------------------------------------------------

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D  # primitive polynomial
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator_poly(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        new = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            new[j] ^= _gf_mul(c, 1)
            new[j + 1] ^= _gf_mul(c, _EXP[i])
        poly = new
    return poly


def _rs_encode(data: list[int], ecc_len: int) -> list[int]:
    gen = _rs_generator_poly(ecc_len)
    res = [0] * ecc_len
    for b in data:
        factor = b ^ res[0]
        res = res[1:] + [0]
        for i in range(ecc_len):
            res[i] ^= _gf_mul(gen[i + 1], factor)
    return res


# --------------------------------------------------------------------------
# Capacity
# --------------------------------------------------------------------------

def _num_raw_data_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        numalign = ver // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if ver >= 7:
            result -= 36
    return result


def num_data_codewords(ver: int, ec: str) -> int:
    total = _num_raw_data_modules(ver) // 8
    return total - ECC_CODEWORDS_PER_BLOCK[ec][ver] * ECC_BLOCKS[ec][ver]


def char_count_bits(ver: int, mode: int) -> int:
    group = 0 if ver <= 9 else (1 if ver <= 26 else 2)
    table = {
        MODE_NUMERIC: (10, 12, 14),
        MODE_ALPHANUMERIC: (9, 11, 13),
        MODE_BYTE: (8, 16, 16),
        MODE_KANJI: (8, 10, 12),
    }
    return table[mode][group]


# --------------------------------------------------------------------------
# Bit buffer
# --------------------------------------------------------------------------

class _BitBuf:
    def __init__(self):
        self.bits: list[int] = []

    def append(self, value: int, length: int):
        for i in range(length - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def __len__(self):
        return len(self.bits)


# --------------------------------------------------------------------------
# Segment encoding
# --------------------------------------------------------------------------

@dataclass
class _Segment:
    mode: int
    data: str | bytes
    charset: str = "UTF-8"
    eci: Optional[int] = None


def _encode_segment(seg: "_Segment", ver: int) -> _BitBuf:
    buf = _BitBuf()
    mode = seg.mode
    if seg.eci is not None:
        buf.append(MODE_ECI, 4)
        buf.append(seg.eci, 8 if seg.eci < 128 else 16)
    buf.append(mode, 4)
    data = seg.data
    if mode == MODE_NUMERIC:
        buf.append(len(data), char_count_bits(ver, mode))
        i = 0
        while i < len(data):
            chunk = data[i:i + 3]
            buf.append(int(chunk), {1: 4, 2: 7, 3: 10}[len(chunk)])
            i += 3
    elif mode == MODE_ALPHANUMERIC:
        buf.append(len(data), char_count_bits(ver, mode))
        i = 0
        while i + 1 < len(data):
            v = ALNUM_CHARSET.index(data[i]) * 45 + ALNUM_CHARSET.index(data[i + 1])
            buf.append(v, 11)
            i += 2
        if i < len(data):
            buf.append(ALNUM_CHARSET.index(data[i]), 6)
    elif mode == MODE_BYTE:
        raw = data.encode(seg.charset) if isinstance(data, str) else data
        buf.append(len(raw), char_count_bits(ver, mode))
        for b in raw:
            buf.append(b, 8)
    elif mode == MODE_KANJI:
        buf.append(len(data), char_count_bits(ver, mode))
        for ch in data:
            sj = ch.encode("shift_jis")
            code = (sj[0] << 8) | sj[1]
            if 0x8140 <= code <= 0x9FFC:
                code -= 0x8140
            else:
                code -= 0xC140
            buf.append((code >> 8) * 0xC0 + (code & 0xFF), 13)
    return buf


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

@dataclass
class QRResult:
    version: int
    ec: str
    mask: int
    mode: str
    matrix: list[list[bool]]
    size: int
    text: str
    meta: dict = field(default_factory=dict)


_MODE_CONST = {"numeric": MODE_NUMERIC, "alphanumeric": MODE_ALPHANUMERIC,
               "byte": MODE_BYTE, "kanji": MODE_KANJI}

_ALNUM_SET = set(ALNUM_CHARSET)


def _pick_mode(text: str, mode: str) -> str:
    if mode != "auto":
        return mode
    if text.isdigit():
        return "numeric"
    if text and all(c in _ALNUM_SET for c in text):
        return "alphanumeric"
    try:
        text.encode("shift_jis")
        if any(ord(c) > 0x7F for c in text):
            return "kanji"
    except UnicodeEncodeError:
        pass
    return "byte"


def _build_segments(text: str, mode: str, charset: str, optimize: bool) -> list["_Segment"]:
    """Split text into one or more segments.

    Without optimize: a single segment using the best-fitting mode.
    With optimize: greedily extract numeric / alphanumeric runs that are long
    enough to beat byte encoding after paying the segment header, producing a
    mixed-mode stream (smaller symbol for mixed content).
    """
    if mode != "auto":
        return [_Segment(mode=_MODE_CONST[mode], data=text, charset=charset)]
    best = _pick_mode(text, "auto")
    if not optimize or best != "byte":
        # uniform numeric / alphanumeric / kanji text is already optimal
        return [_Segment(mode=_MODE_CONST[best], data=text, charset=charset)]

    segs: list[_Segment] = []
    i, n = 0, len(text)
    NUM_MIN, ALNUM_MIN = 4, 6  # break-even run lengths vs byte encoding
    while i < n:
        if text[i].isdigit():
            j = i
            while j < n and text[j].isdigit():
                j += 1
            if j - i >= NUM_MIN:
                segs.append(_Segment(MODE_NUMERIC, text[i:j], charset))
                i = j
                continue
        if text[i] in _ALNUM_SET:
            j = i
            while j < n and text[j] in _ALNUM_SET:
                j += 1
            if j - i >= ALNUM_MIN:
                segs.append(_Segment(MODE_ALPHANUMERIC, text[i:j], charset))
                i = j
                continue
        # byte run until the next worthwhile numeric/alnum run
        j = i + 1
        while j < n:
            if text[j].isdigit():
                k = j
                while k < n and text[k].isdigit():
                    k += 1
                if k - j >= NUM_MIN:
                    break
            if text[j] in _ALNUM_SET:
                k = j
                while k < n and text[k] in _ALNUM_SET:
                    k += 1
                if k - j >= ALNUM_MIN:
                    break
            j += 1
        segs.append(_Segment(MODE_BYTE, text[i:j], charset))
        i = j
    return segs or [_Segment(MODE_BYTE, text, charset)]


def _total_bits(segs: list["_Segment"], ver: int) -> int:
    return sum(len(_encode_segment(s, ver)) for s in segs)


def make_qr(
    text: str,
    ec: str = "M",
    version: Optional[int] = None,
    mask: Optional[int] = None,
    mode: str = "auto",
    charset: str = "UTF-8",
    eci: Optional[int] = None,
    fnc1: bool = False,
    structured_append: Optional[dict] = None,
    optimize: bool = True,
) -> QRResult:
    """Build a QR matrix.

    ec        error level L/M/Q/H
    version   force version 1..40; None = smallest fitting version
    mask      force mask 0..7; None = auto pick by penalty
    mode      auto|numeric|alphanumeric|byte|kanji
    charset   byte-mode text encoding (UTF-8 / GBK / Shift_JIS / ...)
    eci       explicit ECI designator (e.g. 26 = UTF-8)
    fnc1      prepend FNC1 (GS1)
    structured_append  {"index":1,"total":2,"parity":0}
    optimize  split text into mixed-mode segments when it reduces the symbol
    """
    ec = ec.upper()
    if ec not in EC_ORDER:
        raise ValueError(f"unsupported EC level: {ec}")

    segs = _build_segments(text, mode, charset, optimize)
    real_mode = "mixed" if len(segs) > 1 else \
        {v: k for k, v in _MODE_CONST.items()}[segs[0].mode]

    overhead = 0
    if fnc1:
        overhead += 4
    if structured_append:
        overhead += 4 + 4 + 4 + 8
    if eci is not None:
        overhead += 4 + (8 if eci < 128 else 16)

    if version is None:
        chosen = None
        for v in range(1, 41):
            if overhead + _total_bits(segs, v) <= num_data_codewords(v, ec) * 8:
                chosen = v
                break
        if chosen is None:
            raise ValueError("content too long for QR version 40")
        version = chosen
    else:
        if overhead + _total_bits(segs, version) > num_data_codewords(version, ec) * 8:
            raise ValueError(f"content exceeds capacity of version {version} at level {ec}")

    buf = _BitBuf()
    if fnc1:
        buf.append(MODE_FNC1_FIRST, 4)
    if structured_append:
        buf.append(MODE_STRUCTURED, 4)
        buf.append(structured_append.get("index", 0), 4)
        buf.append(structured_append.get("total", 1) - 1, 4)
        buf.append(structured_append.get("parity", 0), 8)
    for k, seg in enumerate(segs):
        seg.eci = eci if (k == 0 and eci is not None) else None
        buf.bits.extend(_encode_segment(seg, version).bits)

    cap_bits = num_data_codewords(version, ec) * 8
    for _ in range(min(4, cap_bits - len(buf))):
        buf.bits.append(0)
    while len(buf) % 8 != 0:
        buf.bits.append(0)

    data_bytes = bytearray()
    for i in range(0, len(buf.bits), 8):
        val = 0
        for b in buf.bits[i:i + 8]:
            val = (val << 1) | b
        data_bytes.append(val)
    pad = [0xEC, 0x11]
    p = 0
    while len(data_bytes) < num_data_codewords(version, ec):
        data_bytes.append(pad[p % 2])
        p += 1

    # Split into blocks, add RS parity, interleave -> final codeword stream
    codewords = _add_ecc_and_interleave(list(data_bytes), version, ec)
    matrix = _build_matrix(version, ec, codewords, mask)

    return QRResult(version=version, ec=ec, mask=_chosen_mask, mode=real_mode,
                    matrix=matrix, size=len(matrix), text=text,
                    meta={"fnc1": fnc1, "eci": eci, "charset": charset,
                          "structured_append": structured_append})


# --------------------------------------------------------------------------
# ECC + interleave
# --------------------------------------------------------------------------

def _add_ecc_and_interleave(data: list[int], ver: int, ec: str) -> list[int]:
    num_blocks = ECC_BLOCKS[ec][ver]
    ecc_len = ECC_CODEWORDS_PER_BLOCK[ec][ver]
    raw_total = num_data_codewords(ver, ec) + ecc_len * num_blocks
    short_len = raw_total // num_blocks
    num_short = num_blocks - raw_total % num_blocks
    short_data_len = short_len - ecc_len

    blocks = []
    k = 0
    for i in range(num_blocks):
        dlen = short_data_len + (0 if i < num_short else 1)
        d = data[k:k + dlen]
        k += dlen
        blocks.append((d, _rs_encode(d, ecc_len)))

    result = []
    for i in range(short_data_len + 1):
        for d, _ in blocks:
            if i < len(d):
                result.append(d[i])
    for i in range(ecc_len):
        for _, e in blocks:
            result.append(e[i])
    return result


# --------------------------------------------------------------------------
# Matrix construction
# --------------------------------------------------------------------------

def _build_matrix(ver: int, ec: str, data: list[int], force_mask: Optional[int]):
    global _chosen_mask
    n = ver * 4 + 17
    modules = [[False] * n for _ in range(n)]
    is_func = [[False] * n for _ in range(n)]

    def setf(r, c, val):
        if 0 <= r < n and 0 <= c < n:
            modules[r][c] = val
            is_func[r][c] = True

    # Finder patterns (three corners)
    for (dr, dc) in [(0, 0), (0, n - 7), (n - 7, 0)]:
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = dr + r, dc + c
                if not (0 <= rr < n and 0 <= cc < n):
                    continue
                inside = (0 <= r <= 6 and 0 <= c <= 6)
                border = (r in (0, 6) or c in (0, 6))
                core = (2 <= r <= 4 and 2 <= c <= 4)
                setf(rr, cc, inside and (border or core))

    # Timing patterns (before alignment so alignment can overlay them)
    for i in range(8, n - 8):
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)

    # Alignment patterns: skip the three corners occupied by finders;
    # draw every other center, including those sitting on the timing lines
    # at (6, *) and (*, 6).
    pos = ALIGN_POSITIONS[ver]
    for i, r in enumerate(pos):
        for j, c in enumerate(pos):
            if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    setf(r + dr, c + dc, max(abs(dr), abs(dc)) != 1)

    # Dark module
    setf(n - 8, 8, True)

    # Reserve format areas (skip row/col 6 - that is the timing pattern)
    for i in range(9):
        if i == 6:
            continue
        setf(8, i, False)
        setf(i, 8, False)
    for i in range(8):
        setf(8, n - 1 - i, False)
        setf(n - 1 - i, 8, False)
    if ver >= 7:
        for i in range(6):
            for j in range(3):
                setf(n - 11 + j, i, False)
                setf(i, n - 11 + j, False)

    _place_data(modules, is_func, data, n)

    def apply_mask(m):
        for r in range(n):
            for c in range(n):
                if not is_func[r][c] and _mask_fn(m, r, c):
                    modules[r][c] = not modules[r][c]

    if force_mask is not None:
        apply_mask(force_mask)
        _draw_format(modules, ec, force_mask, n)
        if ver >= 7:
            _draw_version(modules, ver, n)
        _chosen_mask = force_mask
        return modules

    best, best_score = None, None
    for m in range(8):
        apply_mask(m)
        _draw_format(modules, ec, m, n)
        if ver >= 7:
            _draw_version(modules, ver, n)
        score = _penalty(modules, n)
        if best_score is None or score < best_score:
            best_score, best = score, m
        apply_mask(m)
    apply_mask(best)
    _draw_format(modules, ec, best, n)
    if ver >= 7:
        _draw_version(modules, ver, n)
    _chosen_mask = best
    return modules


def _place_data(modules, is_func, data: list[int], n: int):
    bit_idx = 0
    total_bits = len(data) * 8
    up = True
    col = n - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(n - 1, -1, -1) if up else range(n)
        for r in rows:
            for c in (col, col - 1):
                if is_func[r][c]:
                    continue
                bit = False
                if bit_idx < total_bits:
                    bit = (data[bit_idx // 8] >> (7 - (bit_idx % 8))) & 1 == 1
                    bit_idx += 1
                modules[r][c] = bit
        up = not up
        col -= 2


def _mask_fn(m: int, r: int, c: int) -> bool:
    if m == 0:
        return (r + c) % 2 == 0
    if m == 1:
        return r % 2 == 0
    if m == 2:
        return c % 3 == 0
    if m == 3:
        return (r + c) % 3 == 0
    if m == 4:
        return (r // 2 + c // 3) % 2 == 0
    if m == 5:
        return (r * c) % 2 + (r * c) % 3 == 0
    if m == 6:
        return ((r * c) % 2 + (r * c) % 3) % 2 == 0
    return ((r + c) % 2 + (r * c) % 3) % 2 == 0


def _bch_format(data5: int) -> int:
    g = 0b10100110111
    v = data5 << 10
    for i in range(4, -1, -1):
        if v & (1 << (i + 10)):
            v ^= g << i
    return ((data5 << 10) | v) ^ 0b101010000010010


def _draw_format(modules, ec: str, mask: int, n: int):
    """Place both copies of the 15-bit format info, cell-aligned to the spec."""
    bits = _bch_format((EC_FORMAT_BITS[ec] << 3) | mask)

    def b(i):
        return (bits >> i) & 1 == 1

    # Copy 1 (top-left): vertical 8 + horizontal 7. set(col, row).
    for i in range(6):
        modules[i][8] = b(i)
    modules[7][8] = b(6)
    modules[8][8] = b(7)
    modules[8][7] = b(8)
    for i in range(9, 15):
        modules[8][14 - i] = b(i)

    # Copy 2 (top-right, row 8) and copy 3 (bottom-left, col 8)
    for i in range(8):
        modules[8][n - 1 - i] = b(i)
    for i in range(8, 15):
        modules[n - 15 + i][8] = b(i)
    modules[n - 8][8] = True  # fixed dark module


def _bch_version(ver: int) -> int:
    g = 0b1111100100101
    v = ver << 12
    for i in range(5, -1, -1):
        if v & (1 << (i + 12)):
            v ^= g << i
    return (ver << 12) | v


def _draw_version(modules, ver: int, n: int):
    bits = _bch_version(ver)
    for i in range(18):
        b = (bits >> i) & 1 == 1
        r, c = i // 3, i % 3
        modules[n - 11 + c][r] = b
        modules[r][n - 11 + c] = b


def _penalty(modules, n: int) -> int:
    score = 0
    lines = list(modules) + [list(col) for col in zip(*modules)]
    # Rule 1: runs of same color
    for line in lines:
        run = 1
        for i in range(1, n):
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    # Rule 2: 2x2 same-color blocks
    for r in range(n - 1):
        for c in range(n - 1):
            v = modules[r][c]
            if modules[r][c + 1] == v and modules[r + 1][c] == v and modules[r + 1][c + 1] == v:
                score += 3
    # Rule 3: finder-like patterns
    pat1 = [True, False, True, True, True, False, True, False, False, False, False]
    pat2 = [False, False, False, False, True, False, True, True, True, False, True]
    for line in lines:
        for i in range(n - 10):
            if line[i:i + 11] == pat1 or line[i:i + 11] == pat2:
                score += 40
    # Rule 4: dark/light balance
    dark = sum(sum(row) for row in modules)
    score += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
    return score


_chosen_mask = 0


def split_structured_append(text: str, ec: str = "M", charset: str = "UTF-8",
                            optimize: bool = True, mode: str = "auto"):
    """Split text into up to 16 chunks that each fit a version-40 symbol.

    Returns (chunks, params) where params[i] is the structured-append dict for
    chunk i (shared parity = XOR of all content bytes, per spec).
    """
    max_bits = num_data_codewords(40, ec) * 8
    chunks, cur = [], []
    for ch in text:
        cur.append(ch)
        if _total_bits(_build_segments("".join(cur), mode, charset, optimize), 40) + 20 > max_bits:
            cur.pop()
            chunks.append("".join(cur))
            cur = [ch]
    if cur:
        chunks.append("".join(cur))
    if len(chunks) > 16:
        raise ValueError("content too long even for 16 structured-append symbols")

    parity = 0
    for b in text.encode(charset):
        parity ^= b
    params = [{"index": i + 1, "total": len(chunks), "parity": parity}
              for i in range(len(chunks))]
    return chunks, params
