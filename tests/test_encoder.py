"""Tests for the from-scratch QR encoder.

Round-trip tests decode generated codes; structural tests cross-check the
matrix against a reference implementation (qrcode) for identical
version/EC/mask, which is the strongest possible equivalence check.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from qr_encoder import make_qr  # noqa: E402

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import qrcode as qrlib
except ImportError:
    qrlib = None

EC_MAP = {}
if qrlib:
    EC_MAP = {
        "L": qrlib.constants.ERROR_CORRECT_L,
        "M": qrlib.constants.ERROR_CORRECT_M,
        "Q": qrlib.constants.ERROR_CORRECT_Q,
        "H": qrlib.constants.ERROR_CORRECT_H,
    }


def _to_image(matrix, scale=8, border=4):
    n = len(matrix)
    m = np.ones((n + 2 * border, n + 2 * border), np.uint8) * 255
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                m[r + border][c + border] = 0
    if cv2 is not None:
        return cv2.resize(m, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    return m


# --------------------------------------------------------------------------
# Structural equivalence against the reference library
# --------------------------------------------------------------------------

@pytest.mark.skipif(qrlib is None, reason="reference qrcode library not installed")
@pytest.mark.parametrize("version,ec,mask,text", [
    (1, "M", 0, "HELLO WORLD"),
    (1, "M", 3, "HELLO WORLD"),
    (2, "M", None, "https://example.com/x?a=1"),
    (4, "Q", 5, "https://example.com/x?a=1"),
    (7, "H", 7, "https://example.com/longer/path?token=abcdef"),
    (10, "L", None, "A" * 300),
    (14, "Q", None, "https://example.com/longer/path?with=query&and=more"),
    (25, "M", None, "B" * 800),
])
def test_matrix_matches_reference(version, ec, mask, text):
    res = make_qr(text, ec=ec, version=version, mask=mask)
    chosen = mask if mask is not None else res.mask
    ref = qrlib.QRCode(version=version, error_correction=EC_MAP[ec], mask_pattern=chosen, border=0)
    ref.add_data(text, optimize=0)
    ref.make(fit=False)
    rmat = ref.get_matrix()
    diff = sum(1 for r in range(res.size) for c in range(res.size)
               if bool(rmat[r][c]) != res.matrix[r][c])
    assert diff == 0, f"matrix mismatch: {diff} differing modules"


# --------------------------------------------------------------------------
# Round-trip decode
# --------------------------------------------------------------------------

@pytest.mark.skipif(cv2 is None, reason="opencv not installed")
@pytest.mark.parametrize("text,kw", [
    ("HELLO WORLD", {}),
    ("12345678901234567890", {}),
    ("https://example.com/abc?x=1", {}),
    ("https://example.com", {"ec": "H"}),
    ("MIXED 123 abc", {"mask": 3}),
    ("A" * 300, {}),
    ("Payload with spaces and symbols !@#$%", {}),
])
def test_round_trip(text, kw):
    res = make_qr(text, **kw)
    img = _to_image(res.matrix)
    dec, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    assert dec == text


@pytest.mark.skipif(cv2 is None, reason="opencv not installed")
def test_round_trip_forced_version_and_mask():
    text = "FORCED"
    res = make_qr(text, ec="Q", version=5, mask=4)
    assert res.version == 5 and res.mask == 4
    dec, _, _ = cv2.QRCodeDetector().detectAndDecode(_to_image(res.matrix))
    assert dec == text


def test_version_auto_grows_with_length():
    small = make_qr("A")
    large = make_qr("A" * 300)
    assert large.version > small.version


def test_content_too_long_raises():
    with pytest.raises(ValueError):
        make_qr("A" * 5000, ec="H")


def test_mode_selection():
    assert make_qr("12345").mode == "numeric"
    assert make_qr("HELLO").mode == "alphanumeric"
    assert make_qr("hello world").mode == "byte"
