"""qr_decode.py - Multi-engine decode + triage metadata + safe redirect tracing.

Safe by default: tracing follows redirects with HEAD requests only and never
renders or executes the target page.
"""
from __future__ import annotations

import re
import subprocess
from urllib.parse import urlparse, parse_qs, unquote

import cv2
import numpy as np

_PROTOCOLS = [
    ("http://", "URL"), ("https://", "URL"),
    ("wifi:", "WiFi provisioning"), ("begin:vcard", "vCard contact"),
    ("mecard:", "MECARD contact"), ("begin:vevent", "Calendar event"),
    ("tel:", "Telephone"), ("mailto:", "Email"), ("smsto:", "SMS"),
    ("geo:", "Geo coordinates"), ("otpauth:", "TOTP secret (sensitive)"),
    ("bitcoin:", "Crypto payment"), ("weixin://", "WeChat link"),
    ("alipays://", "Alipay link"), ("javascript:", "JS pseudo-protocol (dangerous)"),
    ("data:", "data: URI (dangerous)"), ("intent://", "Android Intent"),
]


def classify(text: str) -> str:
    low = text.strip().lower()
    for prefix, desc in _PROTOCOLS:
        if low.startswith(prefix):
            return desc
    return "Plain text / unrecognized"


def related_links(text: str) -> list[str]:
    """Extract the URL plus any url=/redirect= parameters (nested detection)."""
    out = [text.strip()]
    try:
        q = parse_qs(urlparse(text).query)
        for key in ("url", "u", "target", "redirect", "to", "link"):
            for v in q.get(key, []):
                dec = unquote(v)
                if dec.startswith(("http://", "https://")):
                    out.append(dec)
    except Exception:
        pass
    for m in re.finditer(r"https?%3A%2F%2F[^\s&]+", text, re.I):
        out.append(unquote(m.group(0)))
    return list(dict.fromkeys(out))


def decode_image(bgr) -> dict:
    """Decode with multiple engines; return {text, engine, kind, links, meta}."""
    result = {"text": None, "engine": None, "meta": {}}
    if bgr is None:
        return result

    try:
        import zxingcpp
        for r in zxingcpp.read_barcodes(bgr):
            result["text"] = r.text
            result["engine"] = "zxing-cpp"
            result["meta"] = {
                "format": str(r.format),
                "ec_level": str(getattr(r, "ec_level", "") or ""),
                "version": getattr(r, "version", None),
                "orientation": getattr(r, "orientation", None),
            }
            break
    except Exception:
        pass

    if result["text"] is None:
        try:
            det = cv2.QRCodeDetector()
            text, pts, _ = det.detectAndDecode(bgr)
            if text:
                result["text"] = text
                result["engine"] = "opencv"
                if pts is not None:
                    result["meta"]["corners"] = np.array(pts).reshape(-1, 2).tolist()
        except Exception:
            pass

    if result["text"] is None:
        try:
            from pyzbar.pyzbar import decode as zb
            hits = zb(bgr)
            if hits:
                result["text"] = hits[0].data.decode("utf-8", "replace")
                result["engine"] = "pyzbar"
                result["meta"]["format"] = str(hits[0].type)
        except Exception:
            pass

    if result["text"] is not None:
        result["kind"] = classify(result["text"])
        result["links"] = related_links(result["text"])
    return result


def trace_redirects(url: str, max_hops: int = 8, timeout: int = 8) -> list[dict]:
    """Follow redirects with curl HEAD requests only. Never renders the page."""
    try:
        out = subprocess.run(
            ["curl", "-sIL", "--max-redirs", str(max_hops), "--max-time", str(timeout),
             "-A", "qr-studio-triage/1.0", url],
            capture_output=True, text=True, timeout=timeout + 4,
        ).stdout
    except Exception as e:
        return [{"error": str(e)}]
    chain = []
    for block in re.split(r"\r?\n\r?\n", out):
        if not block.strip():
            continue
        status = re.search(r"HTTP/[\d.]+ (\d+)", block)
        loc = re.search(r"(?im)^location:\s*(\S+)", block)
        entry = {}
        if status:
            entry["status"] = int(status.group(1))
        if loc:
            entry["location"] = loc.group(1)
        if entry:
            chain.append(entry)
    return chain
