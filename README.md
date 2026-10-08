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
| | mixed-mode segmentation optimization (smaller symbols for mixed content) |
| | ECI designator, arbitrary charset (UTF-8, GBK, Shift_JIS, ...) |
| | FNC1 / GS1 prefix, structured append (multi-symbol split for long content) |
| | versions 1..40, EC levels L/M/Q/H, all 8 masks |
| Payload types | text, URL, vCard, MECARD, email, tel, SMS, geo, WiFi, TOTP (otpauth), calendar event, SEPA transfer, GS1 element string, JSON, key=value |
| Symbols | QR (from scratch); 1D from scratch: Code 128, Code 39, EAN-13, EAN-8, UPC-A, ITF; 2D via zxing: Data Matrix, Aztec, PDF417 |
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

On Windows you can also double-click **`start-qr-studio.cmd`**: it starts the
server in the background (no console window) on `http://127.0.0.1:8788`.

**Start at login:** copy `start-qr-studio.cmd` into your Startup folder
(`Win+R` → `shell:startup`). It uses absolute paths, so it works from there.
The server is then available after every boot.

Two views: **Generate** (paste or type content, tune every parameter, watch the
live preview and round-trip check) and **Inspect** (drop or paste an image to
decode and triage it). The interface is bilingual (English / Chinese) with a
language toggle in the header; the choice is remembered. Everything runs locally
against `127.0.0.1`.

### Command line

```bash
python backend/cli.py gen "https://example.com" -o qr.png --ec H
python backend/cli.py gen --list-types
python backend/cli.py gen --type wifi --fields '{"ssid":"Net","password":"pw"}'
python backend/cli.py gen --type vcard --fields '{"first":"Ada","last":"Lovelace"}'
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
  "content": { "text": "https://example.com", "type": "text", "fields": {},
               "mode": "auto", "charset": "UTF-8", "eci": null,
               "fnc1": false, "optimize": true, "structured_append": null },
  "symbol":  { "format": "qr", "version": null, "ec_level": "M", "mask": null },
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

### Payload types (advanced usage)

A QR code encodes an arbitrary string; the "advanced" uses are well-known
formats that a consuming app parses. Pick a type in the GUI (or `--type` on the
CLI) and the fields are assembled and validated for you:

- `text`, `url`, `json`, `kv`
- `vcard`, `mecard` (contacts, RFC 6350 / MECARD escaping)
- `email` (mailto with subject/body), `tel`, `sms`
- `geo` (latitude/longitude)
- `wifi` (WPA/WEP/open, hidden SSID, escaping)
- `otpauth` (TOTP: secret, issuer, algorithm, digits, period)
- `event` (calendar VEVENT)
- `sepa` (EPC069-12 credit transfer)
- `gs1` (GS1 element string; FNC1 is applied automatically)

### Mixed-mode optimization

For mixed content (letters + digits + punctuation), the encoder greedily splits
the text into numeric / alphanumeric / byte segments to reduce the symbol
version. Toggle it with the "Optimize" checkbox or `optimize` in the config.

### Structured append

Content too long for one symbol can be split across up to 16 structured-append
symbols that a reader reassembles (shared parity per spec). Enable the
"Split into structured-append symbols" checkbox; the GUI shows every part.

### Symbols beyond QR

The **Symbol format** selector switches the whole generator:

- `qr` — the from-scratch QR encoder (all options above).
- `code128`, `code39`, `ean13`, `ean8`, `upca`, `itf` — **from-scratch 1D
  encoders** (`qr_barcode1d.py`), including EAN/UPC check-digit computation.
- `datamatrix`, `aztec`, `pdf417` — 2D symbols generated through zxing-cpp.

Decoding, by contrast, is multi-symbology already: the Inspect view reads QR,
Data Matrix, Aztec, PDF417 and the common 1D codes, and reports the detected
format in the result metadata.

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
    qr_encoder.py    from-scratch QR encoder (RS, masks, format info, interleave)
    qr_barcode1d.py  from-scratch 1D encoders (Code128/39, EAN/UPC, ITF)
    qr_symbols.py    symbol registry + non-QR generation (1D native, 2D via zxing)
    qr_payloads.py   structured payload builders + schema (vCard, WiFi, ...)
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
  start-qr-studio.cmd  Windows launcher (background server)
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
