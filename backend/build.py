"""build.py - Orchestration: config -> (pipeline) -> encode -> render -> verify.

Single entry point shared by the HTTP server and the CLI. Given a config dict
it produces the rendered artifact plus metadata, and (optionally) decodes the
result back to prove it round-trips.
"""
from __future__ import annotations

import base64

from qr_encoder import make_qr
from qr_pipeline import apply_pipeline
from qr_render import render

DEFAULT_CONFIG = {
    "content": {"text": "", "mode": "auto", "charset": "UTF-8", "eci": None,
                "fnc1": False, "structured_append": None},
    "symbol": {"version": None, "ec_level": "M", "mask": None},
    "render": {"format": "png", "size_px": 1024, "module_px": None,
               "quiet_zone": 4, "fg": "#000000", "bg": "#ffffff",
               "module_shape": "square", "eye_shape": "square",
               "eye_color": None, "gradient": None},
    "logo": None,
    "wrapper": None,
    "pipeline": [],
    "verify": {"round_trip": True},
}


def _merge(base: dict, override: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def build_qr(config: dict) -> dict:
    cfg = _merge(DEFAULT_CONFIG, config or {})
    content = cfg["content"]
    text = content.get("text", "")

    # Wrapper / pipeline are applied before encoding
    if cfg.get("wrapper"):
        from qr_pipeline import wrap_url, build_chain
        w = cfg["wrapper"]
        if w.get("layers"):
            text, chain = build_chain(text, w["layers"])
        else:
            text = wrap_url(text, w["template"], w.get("params"), w.get("encode", "urlencode"))
            chain = [content.get("text", ""), text]
        cfg["_wrapper_chain"] = chain
    if cfg.get("pipeline"):
        text = apply_pipeline(text, cfg["pipeline"])

    sa = content.get("structured_append")
    result = make_qr(
        text,
        ec=cfg["symbol"].get("ec_level", "M"),
        version=cfg["symbol"].get("version"),
        mask=cfg["symbol"].get("mask"),
        mode=content.get("mode", "auto"),
        charset=content.get("charset", "UTF-8"),
        eci=content.get("eci"),
        fnc1=bool(content.get("fnc1")),
        structured_append=sa,
    )

    logo = None
    if cfg.get("logo") and cfg["logo"].get("data"):
        logo = base64.b64decode(cfg["logo"]["data"].split(",", 1)[-1])

    r = cfg["render"]
    data = render(
        result.matrix, fmt=r.get("format", "png"),
        size_px=r.get("size_px", 1024), module_px=r.get("module_px"),
        quiet_zone=r.get("quiet_zone", 4), fg=r.get("fg", "#000000"),
        bg=r.get("bg", "#ffffff"), module_shape=r.get("module_shape", "square"),
        eye_shape=r.get("eye_shape", "square"), eye_color=r.get("eye_color"),
        gradient=tuple(r["gradient"]) if r.get("gradient") else None,
        logo=logo, logo_scale=(cfg.get("logo") or {}).get("scale", 0.22),
        logo_knockout=(cfg.get("logo") or {}).get("knockout", True),
    )

    meta = {
        "version": result.version,
        "size": result.size,
        "ec_level": result.ec,
        "mask": result.mask,
        "mode": result.mode,
        "content": text,
        "wrapper_chain": cfg.get("_wrapper_chain"),
    }

    verify = {"round_trip": None}
    if cfg["verify"].get("round_trip") and r.get("format", "png") == "png":
        verify["round_trip"] = _round_trip(data, text)

    return {"data": data, "meta": meta, "verify": verify}


def _round_trip(png_bytes: bytes, expected: str) -> dict:
    import cv2
    import numpy as np
    from qr_decode import decode_image

    buf = np.frombuffer(png_bytes, np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    res = decode_image(img)
    return {"ok": res.get("text") == expected, "decoded": res.get("text")}
