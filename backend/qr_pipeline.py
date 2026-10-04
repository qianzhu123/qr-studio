"""qr_pipeline.py - Nested URL wrapping + content transform / injection pipeline.

Scope (important): this module is intended for self-owned or explicitly
authorized test targets and security research. Nested wrapping is for studying
short-link / redirect chains and building lab samples; the injection transforms
are for testing how scanners, parsers and downstream systems handle malformed
input. Do not use against third-party systems without authorization.
"""
from __future__ import annotations

import base64
import urllib.parse
from typing import Callable

# --------------------------------------------------------------------------
# Nested URL wrapping
# --------------------------------------------------------------------------

def wrap_url(target: str, template: str, params: dict | None = None,
             encode: str = "urlencode") -> str:
    """Fill target into a wrapper template, producing an outer URL that embeds
    an inner target. Templates use the {TARGET} placeholder, e.g.
      "https://<host>/r?url={TARGET}&ref={ID}"
    encode: none | urlencode | urlencode_double | base64
    Use your own domain/service as the wrapper layer.
    """
    encoded = target
    if encode == "urlencode":
        encoded = urllib.parse.quote(target, safe="")
    elif encode == "urlencode_double":
        encoded = urllib.parse.quote(urllib.parse.quote(target, safe=""), safe="")
    elif encode == "base64":
        encoded = base64.urlsafe_b64encode(target.encode()).decode()
    filled = template.replace("{TARGET}", encoded)
    for k, v in (params or {}).items():
        filled = filled.replace("{" + k + "}", str(v))
    return filled


def build_chain(target: str, layers: list[dict]) -> tuple[str, list[str]]:
    """Multi-layer wrapping. layers are applied inner-first; returns
    (outermost_url, redirect_chain)."""
    cur = target
    chain = [target]
    for layer in layers:
        cur = wrap_url(cur, layer["template"], layer.get("params"), layer.get("encode", "urlencode"))
        chain.append(cur)
    return cur, list(reversed(chain))


# --------------------------------------------------------------------------
# Content transforms (for authorized security testing)
# --------------------------------------------------------------------------

def t_urlencode(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def t_double_encode(s: str) -> str:
    return urllib.parse.quote(urllib.parse.quote(s, safe=""), safe="")


def t_base64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def t_js_scheme(s: str) -> str:
    return f"javascript:location.href='{s}'"


def t_data_uri(s: str) -> str:
    return "data:text/html;base64," + base64.b64encode(s.encode()).decode()


def t_intent(s: str) -> str:
    return f"intent://{s.lstrip('/')}#Intent;scheme=https;end"


def t_wrap_quotes(s: str) -> str:
    return f'"{s}";'


def t_crlf(s: str) -> str:
    return s + "\r\nX-Injected: 1"


def t_zero_width(s: str) -> str:
    return "​".join(s)


def t_confusable(s: str) -> str:
    table = str.maketrans({"a": "а", "e": "е", "o": "о", "p": "р", "c": "с"})
    return s.translate(table)


TRANSFORMS: dict[str, Callable[[str], str]] = {
    "urlencode": t_urlencode,
    "double_encode": t_double_encode,
    "base64": t_base64,
    "js_scheme": t_js_scheme,
    "data_uri": t_data_uri,
    "intent": t_intent,
    "wrap_quotes": t_wrap_quotes,
    "crlf": t_crlf,
    "zero_width": t_zero_width,
    "confusable": t_confusable,
}


def apply_pipeline(text: str, steps: list[dict], ctx: dict | None = None) -> str:
    """Apply transforms in order.

    steps: [{"op": "urlencode"},
            {"op": "template", "value": "prefix-{TARGET}-suffix"},
            {"op": "replace", "find": "a", "repl": "b"}]
    ctx:   values for {ID}/{seq}-style placeholders (batch generation).
    """
    ctx = ctx or {}
    out = text
    for step in steps:
        op = step.get("op")
        if op in TRANSFORMS:
            out = TRANSFORMS[op](out)
        elif op == "template":
            out = step["value"].replace("{TARGET}", out)
            for k, v in ctx.items():
                out = out.replace("{" + k + "}", str(v))
        elif op == "replace":
            out = out.replace(step.get("find", ""), step.get("repl", ""))
        elif op == "prefix":
            out = step["value"] + out
        elif op == "suffix":
            out = out + step["value"]
        else:
            raise ValueError(f"unknown transform: {op}")
    return out


def batch_generate(text_template: str, rows: list[dict], steps: list[dict] | None = None):
    """Batch: generate one content string per row context (for CSV-driven output)."""
    out = []
    for i, row in enumerate(rows):
        ctx = {**row, "seq": i + 1, "index": i}
        t = text_template
        for k, v in ctx.items():
            t = t.replace("{" + k + "}", str(v))
        if steps:
            t = apply_pipeline(t, steps, ctx)
        out.append(t)
    return out
