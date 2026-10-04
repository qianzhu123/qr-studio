"""Tests for rendering and the build orchestration."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from build import build_qr  # noqa: E402
from qr_encoder import make_qr  # noqa: E402
from qr_render import render  # noqa: E402


def test_render_png_signature():
    res = make_qr("PNG TEST")
    data = render(res.matrix, fmt="png", size_px=256)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_svg():
    res = make_qr("SVG TEST")
    svg = render(res.matrix, fmt="svg")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")


def test_render_ascii():
    res = make_qr("ASCII")
    art = render(res.matrix, fmt="ascii")
    assert "##" in art and "\n" in art


def test_shapes_produce_valid_png():
    for shape in ("square", "dot", "rounded", "smooth"):
        res = make_qr("SHAPE")
        data = render(res.matrix, fmt="png", size_px=256, module_shape=shape)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_build_round_trip():
    out = build_qr({
        "content": {"text": "https://example.com/build"},
        "symbol": {"ec_level": "H"},
        "render": {"format": "png", "size_px": 512},
        "verify": {"round_trip": True},
    })
    assert out["verify"]["round_trip"]["ok"] is True


def test_build_wrapper_chain():
    out = build_qr({
        "content": {"text": "https://my-lab.local/target"},
        "wrapper": {"template": "https://my-lab.local/r?url={TARGET}&ref={ID}",
                    "params": {"ID": "a1"}, "encode": "urlencode"},
        "render": {"format": "png", "size_px": 512},
        "verify": {"round_trip": True},
    })
    chain = out["meta"]["wrapper_chain"]
    assert chain[0] == "https://my-lab.local/target"
    assert "url=https%3A%2F%2F" in chain[1]
    assert out["verify"]["round_trip"]["ok"] is True


def test_build_pipeline():
    out = build_qr({
        "content": {"text": "https://my-lab.local/x"},
        "pipeline": [{"op": "template", "value": "scan:{TARGET}"}],
        "render": {"format": "png", "size_px": 512},
        "verify": {"round_trip": True},
    })
    assert out["meta"]["content"].startswith("scan:https://")
