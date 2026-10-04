"""Tests for structured payload builders and mixed-mode / structured-append."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from qr_payloads import build_payload, type_schema  # noqa: E402
from qr_encoder import make_qr, split_structured_append  # noqa: E402


def test_all_types_have_builder():
    for tp in type_schema():
        try:
            text, fnc1 = build_payload(tp["id"], {})
            assert isinstance(text, str) and isinstance(fnc1, bool)
        except ValueError:
            pass  # types with required fields may reject empty input


def test_unknown_type_raises():
    try:
        build_payload("nope", {})
        assert False
    except ValueError:
        pass


def test_wifi_escaping():
    text, fnc1 = build_payload("wifi", {"ssid": "My;Net", "security": "WPA", "password": "p:a,s"})
    assert text == r"WIFI:T:WPA;S:My\;Net;P:p\:a\,s;;"
    assert fnc1 is False


def test_wifi_nopass_omits_password():
    text, _ = build_payload("wifi", {"ssid": "Open", "security": "NOPASS"})
    assert "P:" not in text


def test_vcard_structure():
    text, _ = build_payload("vcard", {"first": "Ada", "last": "Lovelace", "email": "a@b.io"})
    assert text.startswith("BEGIN:VCARD\r\n") and text.rstrip().endswith("END:VCARD")
    assert "FN:Ada Lovelace" in text and "EMAIL:a@b.io" in text


def test_vcard_escaping():
    text, _ = build_payload("vcard", {"first": "A;B,C", "last": "X"})
    assert "N:X;A\\;B\\,C;;;" in text


def test_mecard():
    text, _ = build_payload("mecard", {"first": "Ada", "last": "L", "phone": "+1"})
    assert text == "MECARD:N:L,Ada;TEL:+1;;"


def test_email_and_tel_and_sms():
    assert build_payload("email", {"to": "a@b.com", "subject": "hi"})[0].startswith("mailto:a@b.com?")
    assert build_payload("tel", {"number": "+86"})[0] == "tel:+86"
    assert build_payload("sms", {"number": "10086", "body": "hi"})[0] == "SMSTO:10086:hi"


def test_geo():
    assert build_payload("geo", {"lat": "1.5", "lng": "2.5"})[0] == "geo:1.5,2.5"


def test_otpauth():
    text, _ = build_payload("otpauth", {"label": "a@b.com", "secret": "ABCD", "issuer": "ACME"})
    assert text.startswith("otpauth://totp/ACME%3Aa%40b.com?")
    assert "secret=ABCD" in text and "digits=6" in text


def test_otpauth_requires_secret():
    try:
        build_payload("otpauth", {"label": "x"})
        assert False
    except ValueError:
        pass


def test_sepa_format():
    text, _ = build_payload("sepa", {"name": "Max", "iban": "DE12", "amount": "10"})
    lines = text.split("\r\n")
    assert lines[0] == "BCD" and "EUR10.00" in lines


def test_gs1_needs_fnc1():
    text, fnc1 = build_payload("gs1", {"elements": "01:123\n10:ABC"})
    assert text == "0112310ABC"
    assert fnc1 is True


# --------------------------------------------------------------------------
# Encoder: mixed mode + structured append
# --------------------------------------------------------------------------

def test_optimize_reduces_or_matches():
    t = "https://a.com/x?n=123456789012"
    on = make_qr(t, optimize=True)
    off = make_qr(t, optimize=False)
    assert on.version <= off.version


def test_uniform_modes_unchanged():
    assert make_qr("HELLO", optimize=True).mode == "alphanumeric"
    assert make_qr("12345", optimize=True).mode == "numeric"


def test_structured_append_split_and_decode():
    import numpy as np
    import cv2
    big = "abcdefghij" * 300  # 3000 bytes, forces a split
    chunks, params = split_structured_append(big, ec="M")
    assert len(chunks) == len(params) >= 2
    assert "".join(chunks) == big
    # parity must be identical across parts
    assert len({p["parity"] for p in params}) == 1
    for chunk, p in zip(chunks, params):
        res = make_qr(chunk, ec="M", structured_append=p)
        n = res.size
        m = np.ones((n + 8, n + 8), np.uint8) * 255
        for r in range(n):
            for c in range(n):
                if res.matrix[r][c]:
                    m[r + 4][c + 4] = 0
        img = cv2.resize(m, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
        dec, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        assert dec == chunk
