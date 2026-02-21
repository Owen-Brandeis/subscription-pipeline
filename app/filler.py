"""Flat PDF filling: draw text/X in bboxes from template_config, merge overlay onto template with pypdf."""

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ProgressCallback = Callable[[int, int], None]  # (current, total) fields processed

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas as rl_canvas

from app.path_get import get_by_path


def _format_value_for_display(val: Any, schema_path: str) -> str:
    """Format extracted value for readable PDF display (amounts with commas, dates as MM/DD/YYYY)."""
    if val is None:
        return ""
    if schema_path.endswith(".value") and "amount" in schema_path:
        # investment.amount.value: show as currency with commas
        try:
            if isinstance(val, (int, float)):
                n = float(val) if not isinstance(val, int) else int(val)
            else:
                s = str(val).strip().lstrip("$").replace(",", "")
                n = float(s) if "." in s else int(s)
            return f"{n:,.0f}" if n == int(n) else f"{n:,.2f}"
        except (ValueError, TypeError):
            return str(val).strip()
    if "date" in schema_path.lower():
        # e.g. signatures[0].signed_date: ISO YYYY-MM-DD -> MM/DD/YYYY for display
        s = str(val).strip()
        if not s:
            return ""
        for fmt_in, fmt_out in [
            ("%Y-%m-%d", "%m/%d/%Y"),
            ("%m/%d/%Y", "%m/%d/%Y"),
            ("%m-%d-%Y", "%m/%d/%Y"),
        ]:
            try:
                dt = datetime.strptime(s, fmt_in)
                return dt.strftime("%m/%d/%Y")
            except ValueError:
                continue
        return s
    return str(val).strip()


def _get_field_type(f: dict) -> str:
    """Field type: prefer 'type', fallback to 'field_type', default 'text'."""
    return (f.get("type") or f.get("field_type") or "text").strip().lower()


def _checkbox_checked(f: dict, val: Any) -> bool:
    """True if checkbox should be drawn: checked_when_equals match, or value truthy."""
    if "checked_when_equals" in f:
        if val is None:
            return False
        return str(val).strip() == str(f["checked_when_equals"]).strip()
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    return s in ("x", "yes", "true", "1", "✓", "check")


def _draw_text_field(
    c: rl_canvas.Canvas,
    x0: float, y0: float, x1: float, y1: float,
    text: str,
    page_h: float,
    font_name: str = "Helvetica",
    font_size: float = 10,
) -> None:
    """Draw text in bbox. Bbox is in PyMuPDF coords (top-left origin, y down); we convert to PDF y-up for drawString."""
    if not text:
        return
    box_w = x1 - x0
    box_h = y1 - y0
    fs = font_size
    while fs >= 4:
        w = pdfmetrics.stringWidth(text, font_name, fs)
        if w <= box_w:
            break
        fs -= 1
    c.setFont(font_name, fs)
    c.setFillColorRGB(0, 0, 0)
    # PyMuPDF: y0=top, y1=bottom. PDF: bottom of box = page_h - y1
    baseline_y = page_h - y1 + min(2, (box_h - fs) / 2)
    c.drawString(x0, baseline_y, text)


def _wrap_lines(text: str, box_w: float, font_name: str, font_size: float) -> list[str]:
    """Split text into lines that fit within box_w (word wrap)."""
    if not text or box_w <= 0:
        return [text] if text else []
    words = text.split()
    lines = []
    current: list[str] = []
    current_w = 0.0
    for w in words:
        segment = " " + w if current else w
        seg_w = pdfmetrics.stringWidth(segment, font_name, font_size)
        if not current or current_w + seg_w <= box_w:
            current.append(w)
            current_w = current_w + seg_w if current_w else pdfmetrics.stringWidth(w, font_name, font_size)
        else:
            lines.append(" ".join(current))
            current = [w]
            current_w = pdfmetrics.stringWidth(w, font_name, font_size)
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_multiline(
    c: rl_canvas.Canvas,
    x0: float, y0: float, x1: float, y1: float,
    text: str,
    page_h: float,
    font_name: str = "Helvetica",
    font_size: float = 10,
) -> None:
    """Draw text wrapped by words within bbox width. Lines from bottom of box upward."""
    if not text:
        return
    box_w = x1 - x0
    box_h = y1 - y0
    lines = _wrap_lines(text.strip(), box_w, font_name, font_size)
    if not lines:
        return
    # Shrink font if too many lines for box height
    line_height = font_size * 1.2
    while len(lines) * line_height > box_h and font_size >= 4:
        font_size -= 1
        line_height = font_size * 1.2
        lines = _wrap_lines(text.strip(), box_w, font_name, font_size)
    c.setFont(font_name, font_size)
    c.setFillColorRGB(0, 0, 0)
    # PyMuPDF: y0=top, y1=bottom. PDF: bottom of box = page_h - y1
    baseline = page_h - y1 + (box_h - len(lines) * line_height) / 2 + font_size * 0.3
    for i, line in enumerate(lines):
        c.drawString(x0, baseline + (len(lines) - 1 - i) * line_height, line)


def _draw_checkbox(c: rl_canvas.Canvas, x0: float, y0: float, x1: float, y1: float, page_h: float) -> None:
    """Draw 'X' centered in bbox. Bbox in PyMuPDF coords (y down); convert to PDF y-up."""
    from reportlab.pdfbase import pdfmetrics

    cx = (x0 + x1) / 2
    box_h = y1 - y0
    fs = max(6, min(12, box_h * 0.8))
    c.setFont("Helvetica-Bold", fs)
    c.setFillColorRGB(0, 0, 0)
    w = pdfmetrics.stringWidth("X", "Helvetica-Bold", fs)
    baseline_y = page_h - y1 + (box_h - fs) / 2
    c.drawString(cx - w / 2, baseline_y, "X")


def _create_overlay_pages(
    template_pdf_path: str,
    template_config: dict,
    data: dict,
    progress_callback: ProgressCallback | None = None,
) -> list[tuple[float, float, bytes]]:
    """Create overlay PDF bytes per page that has fields. Returns [(width, height, pdf_bytes), ...] indexed by page no."""
    reader = PdfReader(template_pdf_path)
    fields = template_config.get("fields")
    if fields is None:
        raise ValueError("template_config missing 'fields' key")
    if not isinstance(fields, list):
        raise ValueError("template_config['fields'] must be a list")
    if len(fields) == 0:
        raise ValueError("template_config['fields'] is empty; add fields via template builder")
    by_page: dict[int, list[dict]] = {}
    for f in fields:
        if not isinstance(f, dict):
            continue
        page_no = int(f.get("page", 0))
        by_page.setdefault(page_no, []).append(f)

    total_fields = sum(len(fl) for fl in by_page.values())
    field_done = 0
    overlays = []
    for page_no in range(len(reader.pages)):
        page = reader.pages[page_no]
        mb = page.mediabox
        width = float(mb.width)
        height = float(mb.height)
        page_fields = by_page.get(page_no, [])
        if not page_fields:
            overlays.append((width, height, b""))
            continue
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=(width, height))
        c.setFont("Helvetica", 10)
        c.setFillColorRGB(0, 0, 0)
        for f in page_fields:
            schema_path = (f.get("schema_path") or "").strip()
            if not schema_path:
                continue
            field_type = _get_field_type(f)
            font_size = float(f.get("font_size", 10))
            bbox = f.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            val = get_by_path(data, schema_path)
            if field_type == "checkbox":
                if _checkbox_checked(f, val):
                    _draw_checkbox(c, x0, y0, x1, y1, height)
            else:
                text = _format_value_for_display(val, schema_path)
                if field_type == "multiline":
                    _draw_multiline(c, x0, y0, x1, y1, text, height, font_size=font_size)
                else:
                    _draw_text_field(c, x0, y0, x1, y1, text, height, font_size=font_size)
            field_done += 1
            if progress_callback and total_fields:
                progress_callback(field_done, total_fields)
        c.showPage()
        c.save()
        buf.seek(0)
        overlays.append((width, height, buf.read()))
    return overlays


def fill_template(
    template_pdf_path: str,
    template_config: dict,
    data: dict,
    output_pdf_path: str,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """
    Draw text/checkbox values into field bboxes from template_config, merge overlay onto template.
    Uses reportlab for overlay pages and pypdf to merge onto template.
    progress_callback(current, total) is called as each field is processed.
    Raises ValueError if template_config missing 'fields' or fields list is empty.
    """
    if "fields" not in template_config:
        raise ValueError("template_config missing 'fields' key")
    if not isinstance(template_config.get("fields"), list) or len(template_config["fields"]) == 0:
        raise ValueError("template_config['fields'] is empty; add fields via template builder")
    overlays = _create_overlay_pages(
        template_pdf_path, template_config, data, progress_callback=progress_callback
    )
    reader = PdfReader(template_pdf_path)
    writer = PdfWriter(clone_from=template_pdf_path)
    for page_no, (_, _, pdf_bytes) in enumerate(overlays):
        if not pdf_bytes or page_no >= len(writer.pages):
            continue
        overlay_reader = PdfReader(io.BytesIO(pdf_bytes))
        if not overlay_reader.pages:
            continue
        overlay_page = overlay_reader.pages[0]
        writer.pages[page_no].merge_page(overlay_page, over=True)
    Path(output_pdf_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_pdf_path, "wb") as f:
        writer.write(f)
