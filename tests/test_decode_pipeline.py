"""Tests for decoding, triage classification and the transform pipeline."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from qr_decode import classify, related_links  # noqa: E402
from qr_pipeline import apply_pipeline, build_chain, wrap_url  # noqa: E402


def test_classify_protocols():
    assert classify("https://example.com") == "URL"
    assert classify("WIFI:S:net;T:WPA;P:pass;;") == "WiFi provisioning"
    assert classify("otpauth://totp/x") == "TOTP secret (sensitive)"
    assert classify("hello world") == "Plain text / unrecognized"


def test_related_links_nested():
    inner = "https://inner.example/a?b=1"
    outer = f"https://wrap.example/r?url={__import__('urllib.parse', fromlist=['quote']).quote(inner, safe='')}"
    links = related_links(outer)
    assert outer in links
    assert inner in links


def test_wrap_url_urlencode():
    out = wrap_url("https://t.local/a?b=1", "https://w.local/r?url={TARGET}&ref={ID}",
                   {"ID": "x"}, "urlencode")
    assert "url=https%3A%2F%2Ft.local%2Fa%3Fb%3D1" in out
    assert "ref=x" in out


def test_build_chain_multilayer():
    outer, chain = build_chain("https://t.local", [
        {"template": "https://w1.local/r?url={TARGET}", "encode": "urlencode"},
        {"template": "https://w2.local/r?url={TARGET}", "encode": "urlencode"},
    ])
    assert chain[0] == outer          # outermost first
    assert chain[-1] == "https://t.local"  # innermost target last
    assert len(chain) == 3


def test_pipeline_transforms():
    assert apply_pipeline("a b", [{"op": "urlencode"}]) == "a%20b"
    assert apply_pipeline("x", [{"op": "template", "value": "[{TARGET}]"}]) == "[x]"
    assert apply_pipeline("hello", [{"op": "replace", "find": "l", "repl": "L"}]) == "heLLo"


def test_pipeline_crlf_and_wrap():
    out = apply_pipeline("value", [{"op": "crlf"}])
    assert "\r\n" in out
    assert apply_pipeline("v", [{"op": "wrap_quotes"}]) == '"v";'
