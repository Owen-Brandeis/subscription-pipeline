"""Auto-detect form field regions and labels on flat (non-AcroForm) PDFs. No ML."""

import hashlib
from pathlib import Path
from typing import Any

try:
    import fitz
except ImportError:
    raise ImportError(
        "Missing dependency PyMuPDF. Run: python3 -m pip install PyMuPDF"
    ) from None


def _rect_to_list(r: Any) -> list[float]:
    """Convert PyMuPDF Rect to [x0, y0, x1, y1]."""
    return [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)]


def _get_input_regions_from_drawings(page: fitz.Page) -> list[tuple[list[float], str]]:
    """Extract potential input region bboxes from drawings. Returns [(bbox, guess_type), ...]."""
    regions: list[tuple[list[float], str]] = []
    try:
        paths = page.get_drawings()
    except Exception:
        return regions
    for path in paths:
        rect = path.get("rect")
        if rect is None:
            continue
        r = _rect_to_list(rect)
        w = r[2] - r[0]
        h = r[3] - r[1]
        if w < 2 or h < 2:
            continue
        # Long horizontal line (underscore): height small vs width
        if h <= 8 and w >= 30:
            regions.append((r, "text"))
        # Small square -> checkbox
        elif 5 <= w <= 30 and 5 <= h <= 30 and 0.5 <= h / w <= 2.0:
            regions.append((r, "checkbox"))
        # Box / rectangle
        elif w >= 10 and h >= 8:
            if w > 0 and 1.5 < h / w < 4:
                regions.append((r, "multiline"))
            else:
                regions.append((r, "text"))
    return regions


def _get_text_blocks(page: fitz.Page) -> list[tuple[list[float], str]]:
    """Return [(bbox, text), ...] for text blocks only. bbox = [x0,y0,x1,y1]."""
    blocks = []
    try:
        raw = page.get_text("blocks")
    except Exception:
        return blocks
    for b in raw:
        if not isinstance(b, (list, tuple)) or len(b) < 7:
            continue
        block_type = b[6]
        if block_type != 0:
            continue
        x0, y0, x1, y1 = float(b[0]), float(b[1]), float(b[2]), float(b[3])
        text = (b[4] or "").strip().replace("\n", " ")
        if not text:
            continue
        blocks.append(([round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)], text))
    return blocks


def _distance_label_to_field(
    label_bbox: list[float],
    field_bbox: list[float],
) -> float:
    """Lower is better. Prefer label to the left or above."""
    lx0, ly0, lx1, ly1 = label_bbox
    fx0, fy0, fx1, fy1 = field_bbox
    # Same row (vertical overlap): use horizontal gap
    if ly1 > fy0 and ly0 < fy1:
        return max(0, fx0 - lx1)
    # Label above
    if ly1 <= fy0:
        return (fx0 - lx1) ** 2 + (fy0 - ly1) ** 2
    # Label to the left but overlapping vertically
    return max(0, fx0 - lx1) + 10 * max(0, ly0 - fy1)


def _find_nearest_label(
    field_bbox: list[float],
    text_blocks: list[tuple[list[float], str]],
) -> tuple[list[float], str] | None:
    """Find nearest text block to the left or above field_bbox. Returns (label_bbox, label_text) or None."""
    best: tuple[float, list[float], str] | None = None
    for bbox, text in text_blocks:
        # Label must be to the left or above (not right or below)
        if bbox[2] > field_bbox[0] + 50 and bbox[3] > field_bbox[1] + 20:
            continue
        dist = _distance_label_to_field(bbox, field_bbox)
        if best is None or dist < best[0]:
            best = (dist, bbox, text)
    if best is None:
        return None
    return (best[1], best[2])


def _confidence(distance: float, label_len: int) -> float:
    """Simple confidence 0-1. Closer label and non-empty label -> higher."""
    if label_len == 0:
        return 0.0
    score = 1.0 - min(1.0, distance / 200.0)
    return round(min(1.0, max(0.0, score)), 2)


def analyze_template(template_pdf_path: str) -> dict[str, Any]:
    """
    Analyze a flat PDF for potential form fields and labels.
    Returns dict with pdf_sha256, page_count, and candidates list.
    Each candidate: page (0-based), label_text, label_bbox, field_bbox, guess_type, confidence.
    """
    path = Path(template_pdf_path)
    raw = path.read_bytes()
    pdf_sha256 = hashlib.sha256(raw).hexdigest()

    doc = fitz.open(template_pdf_path)
    page_count = len(doc)
    candidates: list[dict[str, Any]] = []

    for page_no in range(page_count):
        page = doc[page_no]
        text_blocks = _get_text_blocks(page)
        regions = _get_input_regions_from_drawings(page)

        for field_bbox, guess_type in regions:
            match = _find_nearest_label(field_bbox, text_blocks)
            if match is None:
                continue
            label_bbox, label_text = match
            dist = _distance_label_to_field(label_bbox, field_bbox)
            conf = _confidence(dist, len(label_text))

            candidates.append({
                "page": page_no,
                "label_text": label_text,
                "label_bbox": label_bbox,
                "field_bbox": field_bbox,
                "guess_type": guess_type,
                "confidence": conf,
            })

    doc.close()

    return {
        "pdf_sha256": pdf_sha256,
        "page_count": page_count,
        "candidates": candidates,
    }
