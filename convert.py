"""
convert.py — Core conversion logic for the EE accessory-diagram formatter.

An "accessory connection diagram" PDF (the *less formatted* input) contains
TWO copies of the same wiring diagram on one A4-style sheet:

  * one copy carries Chinese + English sub-notes  -> the DUAL-language version (-D)
  * one copy carries English-only sub-notes        -> the ENGLISH version      (-E)

This module locates those two diagram boxes, decides which is which by detecting
Chinese characters, crops each one out of the cluttered sheet, rotates it to a
clean upright portrait orientation, and renders it as a high-clarity JPG sized to
a 65 x 90 mm label (3071 x 4252 px @ 1200 dpi).

The heavy lifting is intentionally kept here (no Flask imports) so it can be unit
tested and reused from the command line.

Processing steps (and the functions that do them):
  1) find the matched pair of equal-sized diagram boxes   (_find_diagram_pair)
  2) detect Chinese text to tell -D from -E                (_has_chinese)
  3) crop each box, rotating landscape crops to portrait   (_render_box)
  4) center it on a 65x90 mm white canvas, scaled to fit   (_fit_to_label)
  5) save as a high-clarity JPG (1200 dpi, 3071x4252 px)   (_encode_jpeg / save_version)
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass

import fitz  # PyMuPDF — reads / renders PDFs
from PIL import Image  # Pillow — image scaling / JPG output

# ---------------------------------------------------------------------------
# Output format constants
# ---------------------------------------------------------------------------
# The label is physically 65 mm x 90 mm. Because the source PDF is vector, we can
# render at whatever resolution we like with no quality loss, so the output is
# produced at a high 1200 dpi -- effectively the practical maximum useful detail
# for a label this size:
#   65 / 25.4 * 1200 = 3070.9 -> 3071 px
#   90 / 25.4 * 1200 = 4252.0 -> 4252 px
LABEL_W_MM = 65.0        # label width (mm)
LABEL_H_MM = 90.0        # label height (mm)
TARGET_DPI = 1200        # output resolution (dots per inch; higher = sharper)
TARGET_W = round(LABEL_W_MM / 25.4 * TARGET_DPI)   # = 3071 px (final width)
TARGET_H = round(LABEL_H_MM / 25.4 * TARGET_DPI)   # = 4252 px (final height)
MARGIN = 0.035           # white margin around the drawing (fraction of the canvas)
SUPERSAMPLE = 1.6        # render at 1.6x the target, then downscale for smoother lines (anti-aliasing)
MAX_ZOOM = 60.0          # safety cap on render zoom so memory use stays bounded
JPEG_QUALITY = 96        # JPEG quality (0-100; higher = sharper and larger)
PREVIEW_LONG_PX = 1100   # long side of the in-browser preview (small loads fast; downloads stay full-res)

# Chinese / CJK detection: CJK punctuation, ideographs, compatibility ideographs, fullwidth forms.
# (The third range starts at U+8C48, exactly as in the original version, so it also covers U+A000–U+F8FF.)
_CJK_RE = re.compile(r"[\u3000-\u303f\u3400-\u9fff\u8c48-\ufaff\uff00-\uffef]")


class ConversionError(Exception):
    """Raised when a PDF does not look like a recognizable accessory diagram
    (for example, the two diagram boxes can't be found)."""


@dataclass
class Version:
    """One produced label image."""
    suffix: str          # "D" or "E" — filename suffix for the dual-language / English version
    label: str           # human friendly description
    image: Image.Image   # the finished RGB image (TARGET_W x TARGET_H)


# ---------------------------------------------------------------------------
# Step 1: diagram-box detection
# ---------------------------------------------------------------------------
def _find_diagram_pair(page: "fitz.Page") -> list["fitz.Rect"]:
    """Return the two equal-sized rectangles that frame the diagrams.

    The two diagrams on the sheet are always drawn as a *matched pair* of
    identically sized rectangles. We look at every vector rectangle on the page,
    drop ones that are too small (terminal/resistor boxes) or too big (the page
    border / title block), then find the largest group of same-sized rectangles
    that has at least two members.
    """
    pr = page.rect
    page_area = pr.width * pr.height

    # Collect mid-sized rectangles as candidates.
    candidates: list[fitz.Rect] = []
    for d in page.get_drawings():            # every vector drawing on the page
        r = d["rect"]                        # its bounding rectangle
        if r.width <= 0 or r.height <= 0:
            continue
        area = r.width * r.height
        # Keep mid-sized rectangles only: under 1% of the page is usually a small
        # component box, over 55% is usually the page border / title block.
        if area < 0.01 * page_area or area > 0.55 * page_area:
            continue
        candidates.append(r)

    # Group by rounded dimensions (the pair is the same size to within a few pts):
    # width/height rounded to multiples of 6 pt, so near-identical boxes share a group.
    groups: dict[tuple[int, int], list[fitz.Rect]] = {}
    for r in candidates:
        key = (round(r.width / 6) * 6, round(r.height / 6) * 6)
        groups.setdefault(key, []).append(r)

    # Only keep groups with at least two members (sizes that really come in pairs).
    pairs = [members for members in groups.values() if len(members) >= 2]
    if not pairs:
        return []

    # Prefer the pair whose members enclose the largest area (the actual diagrams,
    # not some incidental repeated small frame).
    pairs.sort(key=lambda members: members[0].width * members[0].height, reverse=True)
    chosen = pairs[0]

    # Take the first two, ordered by reading position (top-to-bottom, then
    # left-to-right) for stable results.
    chosen = sorted(chosen[:2], key=lambda r: (round(r.y0), round(r.x0)))
    return chosen


def _has_chinese(page: "fitz.Page", box: "fitz.Rect") -> bool:
    """True if the text inside *box* (unrotated coords) contains CJK characters."""
    text = page.get_text("text", clip=box)   # read only the text inside this rectangle
    return bool(_CJK_RE.search(text))


# ---------------------------------------------------------------------------
# Steps 3+4: rendering / formatting
# ---------------------------------------------------------------------------
def _render_box(page: "fitz.Page", box: "fitz.Rect") -> Image.Image:
    """Render a single diagram box to a crisp, upright, portrait PIL image."""
    # The diagram boxes come from get_drawings() in *unrotated* page coordinates.
    # If the page itself is rotated (some sheets are saved at 90/270), we must map
    # the box into display coordinates before clipping, otherwise the crop is
    # misaligned. rotation_matrix is identity when the page isn't rotated.
    clip = box * page.rotation_matrix

    long_pt = max(clip.width, clip.height)
    if long_pt <= 0:
        raise ConversionError("Diagram box has zero size.")
    # Render comfortably above the final label resolution, then downscale with
    # LANCZOS so thin lines and CJK strokes stay crisp and anti-aliased.
    target_long_px = max(TARGET_W, TARGET_H) * SUPERSAMPLE
    zoom = max(2.0, min(MAX_ZOOM, target_long_px / long_pt))
    # Render just this clip region to a bitmap at `zoom` (no alpha channel).
    pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(zoom, zoom), alpha=False)

    # Convert the PyMuPDF pixmap to a Pillow image for rotating/scaling.
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    # The diagrams are authored in landscape; the label is portrait. Rotate any
    # landscape crop 90 deg clockwise so terminals read top-to-bottom and the
    # symbols sit upright (matches the established output convention).
    if img.width > img.height:
        img = img.transpose(Image.Transpose.ROTATE_270)  # ROTATE_270 == 90° clockwise

    return _fit_to_label(img)


def _fit_to_label(img: Image.Image) -> Image.Image:
    """Scale *img* to fit inside the label canvas with a uniform white margin."""
    # Usable inner area once the margin is taken off.
    inner_w = int(TARGET_W * (1 - 2 * MARGIN))
    inner_h = int(TARGET_H * (1 - 2 * MARGIN))

    # Use the smaller of the width/height scale factors so the whole image fits undistorted.
    scale = min(inner_w / img.width, inner_h / img.height)
    new_w = max(1, round(img.width * scale))
    new_h = max(1, round(img.height * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)   # LANCZOS: high-quality resampling

    # New white canvas with the scaled image pasted in the center.
    canvas = Image.new("RGB", (TARGET_W, TARGET_H), "white")
    canvas.paste(img, ((TARGET_W - new_w) // 2, (TARGET_H - new_h) // 2))
    return canvas


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def derive_base_name(filename: str) -> str:
    """Turn an input filename into the output base, e.g.

    DWG1234567-105_A.pdf -> DWG1234567-105
    DWG1234567-113.pdf   -> DWG1234567-113
    """
    stem = os.path.splitext(os.path.basename(filename))[0]   # drop the folder and .pdf extension
    # Drop a trailing revision token such as "_A" or "-A" or " A".
    stem = re.sub(r"[ _-][A-Za-z]$", "", stem)
    return stem.strip()


def convert_pdf(data: bytes) -> list[Version]:
    """Convert one PDF (as bytes) into the -D and -E label images.

    Returns a list of Version objects (typically two: D then E). Raises
    ConversionError if the two diagram boxes can't be found.
    """
    doc = fitz.open(stream=data, filetype="pdf")   # open the PDF from in-memory bytes
    try:
        page = doc[0]                              # only the first page is processed

        # Step 1: find the matched pair of diagram boxes.
        boxes = _find_diagram_pair(page)
        if len(boxes) < 2:
            raise ConversionError(
                "Could not locate the two diagram boxes in this PDF. "
                "It may not be an accessory connection diagram, or the "
                "drawing is stored as a flat image rather than vector lines."
            )

        # Step 2: tell -D from -E. The box containing Chinese is the dual-language
        # version (-D); the other is the English version (-E).
        cjk_flags = [_has_chinese(page, b) for b in boxes]

        if cjk_flags[0] and not cjk_flags[1]:
            d_box, e_box = boxes[0], boxes[1]      # first box has Chinese -> it's -D
        elif cjk_flags[1] and not cjk_flags[0]:
            d_box, e_box = boxes[1], boxes[0]      # second box has Chinese -> it's -D
        else:
            # Ambiguous (both or neither have CJK). Fall back to reading order:
            # treat the first box as -D, second as -E so we still produce output.
            d_box, e_box = boxes[0], boxes[1]

        # Steps 3+4: render, rotate and lay out each box as a finished label.
        versions = [
            Version("D", "Dual language (Chinese + English)", _render_box(page, d_box)),
            Version("E", "English only", _render_box(page, e_box)),
        ]
        return versions
    finally:
        doc.close()                                # release the document


def _encode_jpeg(img: Image.Image) -> bytes:
    """Encode a finished label image as a high-quality 4:4:4 JPEG."""
    buf = io.BytesIO()
    img.save(
        buf,
        format="JPEG",
        quality=JPEG_QUALITY,
        subsampling=0,          # 4:4:4 — no chroma subsampling, keeps thin lines and text crisp
        dpi=(TARGET_DPI, TARGET_DPI),
        optimize=True,
    )
    return buf.getvalue()


def save_version(version: Version, path: str) -> None:
    """Write a Version's full-resolution image to *path* as a high-quality JPEG."""
    with open(path, "wb") as fh:
        fh.write(_encode_jpeg(version.image))


def version_jpeg_bytes(version: Version) -> bytes:
    """Return the full-resolution label encoded as JPEG bytes (saving/downloading)."""
    return _encode_jpeg(version.image)


def preview_jpeg_bytes(version: Version, long_px: int = PREVIEW_LONG_PX) -> bytes:
    """Return a small JPEG for fast in-browser preview (full-res stays for download)."""
    img = version.image
    # Shrink the long side to long_px — only when the original is bigger (scale < 1.0).
    scale = long_px / max(img.width, img.height)
    if scale < 1.0:
        img = img.resize(
            (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
            Image.LANCZOS,
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)   # slightly lower quality is fine for previews
    return buf.getvalue()
