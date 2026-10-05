"""Tests for from-scratch 1D barcodes and non-QR symbol generation."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from qr_barcode1d import NATIVE, ean_checksum, render_1d_png  # noqa: E402

try:
    import zxingcpp
except ImportError:
    zxingcpp = None


def _decode(png_bytes):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    res = zxingcpp.read_barcodes(img)
    return res[0].text if res else None


def test_ean_checksum():
    assert ean_checksum("590123412345") == 7
    assert ean_checksum("9638507") == 4


def test_code128_values_encode_ascii():
    bits = NATIVE["code128"]("ABC-123")
    assert bits and all(isinstance(b, bool) for b in bits)


def test_code128_non_ascii_rejected():
    with pytest.raises(ValueError):
        NATIVE["code128"]("café")


def test_code39_rejects_unknown():
    with pytest.raises(ValueError):
        NATIVE["code39"]("A@B")  # '@' is not in the Code 39 character set


def test_itf_pads_to_even():
    bits = NATIVE["itf"]("123")  # odd -> padded
    assert bits


@pytest.mark.skipif(zxingcpp is None, reason="zxing-cpp not installed")
@pytest.mark.parametrize("kind,data", [
    ("code128", "ABC-12345"),
    ("code128", "1234567890"),
    ("code39", "HELLO-39"),
    ("ean13", "590123412345"),
    ("ean8", "9638507"),
    ("upca", "03600029145"),
    ("itf", "1234567890"),
])
def test_1d_round_trip(kind, data):
    png = render_1d_png(NATIVE[kind](data), height=160, module_px=3, quiet_zone=25)
    decoded = _decode(png)
    assert decoded is not None
    norm = lambda s: "".join(c for c in s.upper() if c.isalnum())
    a, b = norm(decoded), norm(data)
    assert a == b or a.lstrip("0").startswith(b.lstrip("0"))


@pytest.mark.skipif(zxingcpp is None, reason="zxing-cpp not installed")
@pytest.mark.parametrize("fmt", ["datamatrix", "aztec", "pdf417"])
def test_2d_non_qr_round_trip(fmt):
    from qr_symbols import generate_symbol
    out = generate_symbol(fmt, "HELLO-2D", {"format": "png", "size_px": 400})
    assert out["verify"]["round_trip"]["ok"] is True


def test_symbol_catalog_has_all():
    from qr_symbols import symbol_catalog
    ids = {s["id"] for s in symbol_catalog()}
    assert {"qr", "code128", "code39", "ean13", "ean8", "upca", "itf",
            "datamatrix", "aztec", "pdf417"} <= ids
