# QR Studio

A local QR toolkit with a **from-scratch encoder**. It generates QR codes with
fine-grained, fully reproducible control, decodes existing codes with multiple
engines, and produces a triage report that explains what a code is before you
ever visit its target.

No third-party QR library is used for encoding. The matrix is built byte by
byte from the ISO/IEC 18004 specification: GF(256) Reed-Solomon, block
interleaving, function patterns, format/version info, mask selection. The test
suite proves the output is **cell-for-cell identical** to a reference
implementation for identical version / EC level / mask.

## Why

Most QR tools give you size, EC level and a color picker. That is not enough
when you need to reproduce a code exactly, study how scanners handle edge
cases, or understand a code you did not create. QR Studio exposes the full
parameter surface and keeps every step inspectable.

- **Generate** with control down to mode, charset, ECI, FNC1, forced version,
  forced mask, module shape, eye shape, gradient and embedded logo.
- **Inspect** any code: type, decoder metadata (version, EC level, orientation),
  protocol classification, nested links, and an optional redirect trace that
  never renders the target page.
- **Control** behavior through a JSON config that round-trips: same config in,
  same bytes out.

## Features

| Area | Capability |
|---|---|
| Encoding | numeric / alphanumeric / byte / kanji modes, auto mode selection |
| | ECI designator, arbitrary charset (UTF-8, GBK, Shift_JIS, ...) |
| | FNC1 / GS1 prefix, structured append |
| | versions 1..40, EC levels L/M/Q/H, all 8 masks |
| Error correction | Reed-Solomon over GF(256), blocks + interleaving per spec |
| Rendering | PNG (Pillow), SVG (hand-written), ASCII / terminal |
| Styling | module shapes (square/dot/rounded/smooth), eye shapes, eye color, gradient, embedded logo with ECC-aware knockout |
| Decoding | cv2 + zxing-cpp + pyzbar, cross-engine |
| Triage | protocol classification, nested-link extraction, HEAD-only redirect tracing |
| Advanced | nested URL wrapper (multi-layer), content transform pipeline, batch generation |
| Safety | round-trip verification, local-only, never opens decoded URLs by default |

## Install

```bash
pip install -r requirements.txt        # runtime
pip install -r requirements-dev.txt    # adds pytest + reference lib for tests
```

The encoder itself needs nothing beyond the standard library. OpenCV, Pillow,
numpy and zxing-cpp power rendering and decoding.

## Usage

### Web GUI

```bash
python backend/server.py            # http://127.0.0.1:8788
```

On Windows you can also double-click `start-qr-studio.vbs`: it checks whether the
server is already listening on the port, stops that exact process if so, starts a
fresh one, then opens the browser. Only the PID owning the port is killed, so
other `pythonw` processes are left alone. Stop it manually with
`taskkill /IM pythonw.exe /F`.

Two views: **Generate** (paste or type content, tune every parameter, watch the
live preview and round-trip check) and **Inspect** (drop or paste an image to
decode and triage it). The interface is bilingual (English / Chinese) with a
language toggle in the header; the choice is remembered. Everything runs locally
against `127.0.0.1`.

### Command line

```bash
python backend/cli.py gen "https://example.com" -o qr.png --ec H
python backend/cli.py gen "hello" --ascii
python backend/cli.py gen "data" --shape dot --eye-shape rounded --fg "#111" --bg "#fff"
python backend/cli.py decode qr.png
python backend/cli.py triage qr.png --trace      # HEAD-only redirect chain
python backend/cli.py decode --clipboard
python backend/cli.py watch-clipboard            # decode on clipboard change
```

### Config (the reproducible unit)

```jsonc
{
  "content": { "text": "https://example.com", "mode": "auto",
               "charset": "UTF-8", "eci": null, "fnc1": false },
  "symbol":  { "version": null, "ec_level": "M", "mask": null },
  "render":  { "format": "png", "size_px": 1024, "quiet_zone": 4,
               "fg": "#000000", "bg": "#ffffff",
               "module_shape": "square", "eye_shape": "square",
               "eye_color": null, "gradient": null },
  "logo":    null,
  "wrapper": null,
  "pipeline": [],
  "verify":  { "round_trip": true }
}
```

The same config produces the same code, every time. `verify.round_trip`
re-decodes the result and fails loudly if it does not match.

## Advanced features

### Nested URL wrapper

Reproduce and study the "outer URL embeds an inner target" pattern seen in
short-link and redirect-chain codes: fill an inner target into an outer wrapper
template, optionally across multiple layers, with per-layer encoding
(urlencode / double-encode / base64).

```jsonc
"wrapper": {
  "template": "https://your.host/r?url={TARGET}&ref={ID}",
  "params": { "ID": "a1" },
  "encode": "urlencode"
}
```

### Transform pipeline

Insert a sequence of content transforms before encoding: urlencode, base64,
protocol handlers (`javascript:`, `data:`, `intent://`), parameter-boundary
wrapping, CRLF, zero-width and confusable-character obfuscation. Intended for
testing how scanners and parsers handle malformed or adversarial input.

### Batch generation

Drive from CSV rows, generating one code per row with `{column}` placeholders
and a `{seq}` counter. See `qr_pipeline.batch_generate`.

## Safety boundary

The nested wrapper and the transform pipeline are for **self-owned or
explicitly authorized** targets and for security research. They exist so you
can build your own lab samples and study scanner/parser behavior. Do not use
them against third-party systems without authorization.

Decoding is local and read-only. The triage redirect trace issues HEAD requests
only and never renders or executes the target page.

## Project layout

```
qr-studio/
  backend/
    qr_encoder.py    from-scratch encoder (RS, masks, format info, interleave)
    qr_render.py     PNG / SVG / ASCII rendering, styling, logo embedding
    qr_decode.py     multi-engine decode + triage classification + tracing
    qr_pipeline.py   nested wrapper + transform pipeline
    build.py         config -> pipeline -> encode -> render -> verify
    cli.py           command line interface
    server.py        local HTTP API + static frontend (stdlib only)
  frontend/
    index.html       single-page UI (Generate + Inspect)
  profiles/          saved config profiles (JSON)
  tests/             encoder equivalence, round-trip, render, pipeline tests
  start-qr-studio.vbs  Windows one-click launcher
```

## Testing

```bash
python -m pytest tests/ -q
```

The structural tests build the matrix and compare it against a reference
implementation cell by cell; a diff of zero is the strongest equivalence
statement available. Round-trip tests decode generated codes back and compare.

## License

MIT. See `LICENSE`.
