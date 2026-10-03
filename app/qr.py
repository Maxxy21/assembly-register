"""QR rendering: inline SVG for the admin page, PNG for printing."""

from __future__ import annotations

import io

import qrcode
import qrcode.image.svg
from PIL import Image, ImageDraw, ImageFont


def _qr(url: str, border: int = 2, box_size: int = 10) -> qrcode.QRCode:
    # Error correction M survives a scuffed printout or a glare spot on a
    # projector without making the code too dense to scan from a distance.
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=border,
        box_size=box_size,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr


def qr_svg(url: str) -> str:
    img = _qr(url).make_image(image_factory=qrcode.image.svg.SvgPathImage)
    svg = img.to_string(encoding="unicode")
    # Drop the XML declaration so the markup can be inlined into HTML.
    if svg.startswith("<?xml"):
        svg = svg[svg.index("?>") + 2 :]
    return svg


def qr_png(url: str, caption_lines: list[str] | None = None, box_size: int = 20) -> bytes:
    """A print-ready PNG: large modules, a quiet zone, optional caption."""
    img = _qr(url, border=4, box_size=box_size).make_image().convert("RGB")
    lines = [line for line in (caption_lines or []) if line]
    if lines:
        font_size = max(28, img.width // 18)
        font = ImageFont.load_default(size=font_size)
        probe = ImageDraw.Draw(img)
        # Shrink until the longest line fits inside the image with a margin.
        while font_size > 12 and max(probe.textlength(t, font=font) for t in lines) > img.width * 0.92:
            font_size -= 2
            font = ImageFont.load_default(size=font_size)
        line_height = int(font_size * 1.35)
        height = img.height + line_height * len(lines) + font_size
        canvas = Image.new("RGB", (img.width, height), "white")
        canvas.paste(img, (0, 0))
        draw = ImageDraw.Draw(canvas)
        y = img.height
        for line in lines:
            width = draw.textlength(line, font=font)
            draw.text(((img.width - width) / 2, y), line, fill="black", font=font)
            y += line_height
        img = canvas
    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(300, 300))
    return buf.getvalue()
