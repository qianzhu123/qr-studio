"""qr_render.py - Render a QR matrix to PNG / SVG / ASCII with styling support.

No third-party QR library. PNG uses Pillow; SVG is hand written; ASCII is
emitted directly.
"""
from __future__ import annotations

import io
from typing import Optional


def _eye_origins(size: int):
    return [(0, 0), (0, size - 7), (size - 7, 0)]


def _is_eye(r: int, c: int, size: int) -> bool:
    for dr, dc in _eye_origins(size):
        if dr <= r < dr + 7 and dc <= c < dc + 7:
            return True
    return False


def _hex(s: str):
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def _draw_module(dr, x, y, m, shape, color):
    if shape == "dot":
        pad = m * 0.08
        dr.ellipse([x + pad, y + pad, x + m - pad, y + m - pad], fill=color)
    elif shape == "rounded":
        dr.rounded_rectangle([x, y, x + m - 1, y + m - 1], radius=m * 0.28, fill=color)
    elif shape == "smooth":
        dr.ellipse([x, y, x + m - 1, y + m - 1], fill=color)
    else:
        dr.rectangle([x, y, x + m - 1, y + m - 1], fill=color)


def render_png(
    matrix, size_px: int = 1024, module_px: Optional[int] = None,
    quiet_zone: int = 4, fg: str = "#000000", bg: str = "#ffffff",
    module_shape: str = "square", eye_shape: str = "square",
    eye_color: Optional[str] = None, gradient: Optional[tuple] = None,
    logo=None, logo_scale: float = 0.22, logo_knockout: bool = True,
) -> bytes:
    from PIL import Image, ImageDraw

    n = len(matrix)
    m = module_px or max(1, size_px // (n + 2 * quiet_zone))
    total = (n + 2 * quiet_zone) * m
    img = Image.new("RGB", (total, total), bg)
    dr = ImageDraw.Draw(img)

    fg_rgb = _hex(fg)
    eye_rgb = _hex(eye_color) if eye_color else fg_rgb
    grad = (_hex(gradient[0]), _hex(gradient[1])) if gradient else None

    for r in range(n):
        for c in range(n):
            if not matrix[r][c]:
                continue
            x = (c + quiet_zone) * m
            y = (r + quiet_zone) * m
            eye = _is_eye(r, c, n)
            if grad and not eye:
                t = (r + c) / (2 * n)
                color = tuple(int(grad[0][k] + (grad[1][k] - grad[0][k]) * t) for k in range(3))
            else:
                color = eye_rgb if eye else fg_rgb
            _draw_module(dr, x, y, m, eye_shape if eye else module_shape, color)

    if logo is not None:
        _paste_logo(img, logo, logo_scale, logo_knockout, bg)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _paste_logo(img, logo, scale, knockout, bg):
    from PIL import Image, ImageDraw

    if isinstance(logo, (bytes, bytearray)):
        logo = Image.open(io.BytesIO(logo))
    logo = logo.convert("RGBA")
    side = len(img)
    target = max(8, int(side * scale))
    logo = logo.resize((target, target))
    pos = ((side - target) // 2, (side - target) // 2)
    if knockout:
        pad = int(target * 0.12)
        quad = Image.new("RGBA", (target + 2 * pad, target + 2 * pad), _hex(bg) + (255,))
        img.paste(quad, (pos[0] - pad, pos[1] - pad))
    img.paste(logo, pos, logo)


def render_svg(matrix, module_px: Optional[int] = None, quiet_zone: int = 4,
               fg: str = "#000000", bg: str = "#ffffff") -> str:
    module_px = module_px or 8
    n = len(matrix)
    side = (n + 2 * quiet_zone) * module_px
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" height="{side}" '
             f'viewBox="0 0 {side} {side}" shape-rendering="crispEdges">',
             f'<rect width="{side}" height="{side}" fill="{bg}"/>']
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                parts.append(f'<rect x="{(c + quiet_zone) * module_px}" '
                             f'y="{(r + quiet_zone) * module_px}" '
                             f'width="{module_px}" height="{module_px}" fill="{fg}"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def render_ascii(matrix, quiet_zone: int = 2, on: str = "##", off: str = "  ") -> str:
    n = len(matrix)
    lines = [off * (n + 2 * quiet_zone) for _ in range(quiet_zone)]
    for r in range(n):
        lines.append(off * quiet_zone + "".join(on if matrix[r][c] else off for c in range(n)) + off * quiet_zone)
    lines += [off * (n + 2 * quiet_zone) for _ in range(quiet_zone)]
    return "\n".join(lines)


def render(matrix, fmt: str = "png", **kw) -> bytes | str:
    if fmt == "png":
        return render_png(matrix, **kw)
    if fmt == "svg":
        return render_svg(matrix, **{k: v for k, v in kw.items()
                                     if k in ("module_px", "quiet_zone", "fg", "bg")})
    if fmt in ("ascii", "txt", "terminal"):
        return render_ascii(matrix, **{k: v for k, v in kw.items() if k in ("quiet_zone",)})
    raise ValueError(f"unsupported format: {fmt}")
