"""cli.py - Command line interface for qr-studio.

Examples:
  python backend/cli.py gen "https://example.com" -o out.png --ec H
  python backend/cli.py gen "hello" --ascii
  python backend/cli.py decode some.png
  python backend/cli.py decode --clipboard
  python backend/cli.py triage some.png
  python backend/cli.py watch-clipboard
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build import build_qr  # noqa: E402
from qr_decode import decode_image, trace_redirects  # noqa: E402


def _decode_path(path):
    import cv2
    img = cv2.imread(path)
    if img is None:
        print(f"cannot read image: {path}", file=sys.stderr)
        return None
    return decode_image(img)


def _report(res: dict):
    print("=" * 64)
    print(f"[kind]    {res.get('kind', '-')}")
    print(f"[engine]  {res.get('engine', '-')}")
    meta = {k: v for k, v in (res.get("meta") or {}).items() if v not in (None, "", "None")}
    if meta:
        print(f"[meta]    {json.dumps(meta, ensure_ascii=False)}")
    print(f"[content] {res.get('text')}")
    links = res.get("links") or []
    if len(links) > 1:
        print("[nested links]")
        for l in links[1:]:
            print(f"    -> {l}")
    print("=" * 64)


def cmd_gen(args):
    cfg = {
        "content": {"text": args.text or "", "type": args.type,
                    "fields": json.loads(args.fields) if args.fields else {},
                    "mode": args.mode, "charset": args.charset, "fnc1": args.fnc1},
        "symbol": {"version": args.version, "ec_level": args.ec, "mask": args.mask},
        "render": {"format": "ascii" if args.ascii else "png",
                   "size_px": args.size, "module_px": args.module,
                   "fg": args.fg, "bg": args.bg,
                   "module_shape": args.shape, "eye_shape": args.eye_shape},
        "verify": {"round_trip": True},
    }
    out = build_qr(cfg)
    if args.ascii:
        print(out["data"])
    else:
        with open(args.out, "wb") as f:
            f.write(out["data"])
        print(f"wrote {args.out}  ({len(out['data'])} bytes)")
    m = out["meta"]
    print(f"version={m['version']} size={m['size']}x{m['size']} ec={m['ec_level']} "
          f"mask={m['mask']} mode={m['mode']}")
    rt = out["verify"]["round_trip"]
    if rt is not None:
        print(f"round-trip: {'OK' if rt['ok'] else 'FAIL'}")


def cmd_decode(args):
    if args.clipboard:
        from PIL import ImageGrab
        import cv2
        import numpy as np
        img = ImageGrab.grabclipboard()
        if img is None or not hasattr(img, "convert"):
            print("clipboard has no image", file=sys.stderr)
            return 1
        bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
        _report(decode_image(bgr))
        return 0
    res = _decode_path(args.path)
    if res is None:
        return 1
    _report(res)
    return 0


def cmd_triage(args):
    res = _decode_path(args.path)
    if res is None:
        return 1
    _report(res)
    url = res.get("text") or ""
    if args.trace and url.startswith(("http://", "https://")):
        print("[redirect chain] (HEAD requests only, page never rendered)")
        for hop in trace_redirects(url):
            print(f"    {hop}")
    return 0


def cmd_watch(_args):
    import time
    from PIL import ImageGrab
    import cv2
    import numpy as np
    print("watching clipboard... press Ctrl+C to stop")
    last = None
    try:
        while True:
            img = ImageGrab.grabclipboard()
            if img is not None and hasattr(img, "convert"):
                bgr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
                key = hash(bgr.tobytes())
                if key != last:
                    last = key
                    res = decode_image(bgr)
                    if res.get("text"):
                        _report(res)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nstopped")


def main():
    p = argparse.ArgumentParser(prog="qr-studio")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen", help="generate a QR code")
    g.add_argument("text", nargs="?", default="")
    g.add_argument("-o", "--out", default="qr.png")
    g.add_argument("--type", default="text",
                   help="payload type: text|url|vcard|mecard|email|tel|sms|geo|wifi|"
                        "otpauth|event|sepa|gs1|json|kv")
    g.add_argument("--fields", default="", help='JSON object of field values, e.g. \'{"ssid":"x"}\'')
    g.add_argument("--list-types", action="store_true", help="print payload types and exit")
    g.add_argument("--ec", default="M", choices=["L", "M", "Q", "H"])
    g.add_argument("--version", type=int, default=None)
    g.add_argument("--mask", type=int, default=None)
    g.add_argument("--mode", default="auto",
                   choices=["auto", "numeric", "alphanumeric", "byte", "kanji"])
    g.add_argument("--charset", default="UTF-8")
    g.add_argument("--fnc1", action="store_true")
    g.add_argument("--size", type=int, default=1024)
    g.add_argument("--module", type=int, default=None)
    g.add_argument("--fg", default="#000000")
    g.add_argument("--bg", default="#ffffff")
    g.add_argument("--shape", default="square",
                   choices=["square", "dot", "rounded", "smooth"])
    g.add_argument("--eye-shape", dest="eye_shape", default="square",
                   choices=["square", "dot", "rounded", "smooth"])
    g.add_argument("--ascii", action="store_true")
    g.set_defaults(func=cmd_gen)

    d = sub.add_parser("decode", help="decode a QR image")
    d.add_argument("path", nargs="?")
    d.add_argument("--clipboard", action="store_true")
    d.set_defaults(func=cmd_decode)

    t = sub.add_parser("triage", help="decode + metadata + optional redirect trace")
    t.add_argument("path")
    t.add_argument("--trace", action="store_true")
    t.set_defaults(func=cmd_triage)

    w = sub.add_parser("watch-clipboard", help="decode clipboard on change")
    w.set_defaults(func=cmd_watch)

    args = p.parse_args()
    if args.cmd == "gen" and getattr(args, "list_types", False):
        from qr_payloads import type_schema
        for tp in type_schema():
            fields = ", ".join(f["name"] for f in tp["fields"])
            print(f"{tp['id']:9s} {tp['label_en']:22s} fields: {fields}")
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
