"""qr_symbols.py - Non-QR symbol generation.

Two sources:
  - 1D barcodes: from-scratch encoders in qr_barcode1d (Code128, Code39, EAN-13,
    EAN-8, UPC-A, ITF).
  - 2D non-QR (DataMatrix, Aztec, PDF417): generated via zxing-cpp, which is
    already a decode dependency. This is a pragmatic path; the QR encoder and
    the 1D encoders remain fully from-scratch.

Returns the same shape as build.build_qr: {"data", "meta", "verify"}.
"""
from __future__ import annotations

import io

from qr_barcode1d import NATIVE, render_1d_png, render_1d_svg

# id -> (label_en, label_zh, kind)
GENERATABLE = {
    "qr":         ("QR Code", "QR 码", "2d-native"),
    "code128":    ("Code 128", "Code 128", "1d-native"),
    "code39":     ("Code 39", "Code 39", "1d-native"),
    "ean13":      ("EAN-13", "EAN-13", "1d-native"),
    "ean8":       ("EAN-8", "EAN-8", "1d-native"),
    "upca":       ("UPC-A", "UPC-A", "1d-native"),
    "itf":        ("ITF", "ITF", "1d-native"),
    "datamatrix": ("Data Matrix", "Data Matrix", "2d-zxing"),
    "aztec":      ("Aztec", "Aztec", "2d-zxing"),
    "pdf417":     ("PDF417", "PDF417", "2d-zxing"),
}

_ZXING_FMT = {"datamatrix": "DataMatrix", "aztec": "Aztec", "pdf417": "PDF417"}


def symbol_catalog() -> list[dict]:
    return [{"id": k, "label_en": v[0], "label_zh": v[1], "kind": v[2]}
            for k, v in GENERATABLE.items()]


def generate_symbol(fmt: str, text: str, render: dict) -> dict:
    """Generate a non-QR symbol and return {data, meta, verify}."""
    if fmt in NATIVE:
        return _generate_1d(fmt, text, render)
    if fmt in _ZXING_FMT:
        return _generate_zxing(fmt, text, render)
    raise ValueError(f"unsupported symbol format: {fmt}")


def _decode_png(png_bytes: bytes) -> str | None:
    import cv2
    import numpy as np
    import zxingcpp
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    res = zxingcpp.read_barcodes(img)
    return res[0].text if res else None


def _verify(png_bytes: bytes, expected: str) -> dict:
    decoded = _decode_png(png_bytes)

    def norm(s):
        return "".join(c for c in (s or "").upper() if c.isalnum())

    a, b = norm(decoded), norm(expected)
    ok = bool(a) and (a == b or a.lstrip("0").startswith(b.lstrip("0"))
                      or b.lstrip("0").startswith(a.lstrip("0")))
    return {"ok": ok, "decoded": decoded, "expected": expected}


def _generate_1d(fmt: str, text: str, render: dict) -> dict:
    bits = NATIVE[fmt](text)
    r = render or {}
    height = int(r.get("bar_height", 220))
    module_px = int(r.get("module_px") or 3)
    quiet = int(r.get("quiet_zone", 20))
    fg, bg = r.get("fg", "#000000"), r.get("bg", "#ffffff")
    if r.get("format", "png") == "svg":
        data = render_1d_svg(bits, height=height, module_px=module_px,
                             quiet_zone=quiet, fg=fg, bg=bg)
        verify = {"round_trip": None}
    else:
        data = render_1d_png(bits, height=height, module_px=module_px,
                             quiet_zone=quiet, fg=fg, bg=bg,
                             text=None if r.get("show_text", True) is False else None)
        verify = {"round_trip": _verify(data, text)}
    return {"data": data,
            "meta": {"format": fmt, "modules": len(bits), "text": text},
            "verify": verify}


def _generate_zxing(fmt: str, text: str, render: dict) -> dict:
    import numpy as np
    import zxingcpp
    from PIL import Image

    r = render or {}
    width = int(r.get("size_px") or 512)
    height = int(r.get("bar_height") or max(200, width // 3))
    bfmt = getattr(zxingcpp.BarcodeFormat, _ZXING_FMT[fmt])
    vec = zxingcpp.write_barcode(bfmt, text, width=width, height=height)
    arr = np.array(vec)
    img = Image.fromarray(arr).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    return {"data": data,
            "meta": {"format": fmt, "text": text, "width": width, "height": height},
            "verify": {"round_trip": _verify(data, text)}}
