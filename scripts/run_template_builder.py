#!/usr/bin/env python3
"""Minimal Gradio UI to build a template config: upload PDF, pick page, add fields by bbox, save to artifacts/_templates/<id>/template_config.json."""

import json
import sys
from pathlib import Path

# Self-diagnose: require gradio and fitz only
_missing = []
try:
    import gradio as gr
except ImportError:
    _missing.append("gradio")
try:
    import fitz
except ImportError:
    _missing.append("fitz")
if _missing:
    if "gradio" in _missing:
        print("Missing gradio. Install: python3 -m pip install gradio")
    if "fitz" in _missing:
        print("Missing PyMuPDF. Install: python3 -m pip install PyMuPDF")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ZOOM = 1.5


def _page_to_image(pdf_path: str, page_no: int):
    """Render PDF page to PIL Image (RGB). Returns None if invalid."""
    if not pdf_path or not Path(pdf_path).is_file():
        return None
    from PIL import Image

    doc = fitz.open(pdf_path)
    if page_no < 0 or page_no >= len(doc):
        doc.close()
        return None
    page = doc[page_no]
    mat = fitz.Matrix(ZOOM, ZOOM)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    doc.close()
    w, h, n = pix.width, pix.height, pix.n
    if n == 3:
        img = Image.frombytes("RGB", (w, h), pix.samples)
    elif n == 4:
        img = Image.frombytes("RGBA", (w, h), pix.samples).convert("RGB")
    else:
        return None
    return img


def _page_rect(pdf_path: str, page_no: int) -> tuple[float, float]:
    """Return (width, height) of page in PDF points, or (612, 792) if unavailable."""
    if not pdf_path or not Path(pdf_path).is_file():
        return 612.0, 792.0
    doc = fitz.open(pdf_path)
    if page_no < 0 or page_no >= len(doc):
        doc.close()
        return 612.0, 792.0
    r = doc[page_no].rect
    doc.close()
    return r.width, r.height


def _draw_bbox_on_image(img, x0: float, y0: float, x1: float, y1: float, page_w: float, page_h: float):
    """Draw a rectangle on the image. Bbox in PDF points; scale using page_w, page_h. Returns PIL Image or None."""
    if img is None:
        return None
    from PIL import ImageDraw

    img = img.copy()
    w, h = img.size
    scale_x = w / page_w if page_w else 1
    scale_y = h / page_h if page_h else 1
    sx0 = int(x0 * scale_x)
    sy0 = int(y0 * scale_y)
    sx1 = int(x1 * scale_x)
    sy1 = int(y1 * scale_y)
    draw = ImageDraw.Draw(img)
    draw.rectangle([sx0, sy0, sx1, sy1], outline="red", width=3)
    return img


def on_upload(pdf_file) -> tuple[str, str | None, str, int]:
    """When user uploads PDF: return pdf_path, page 0 image, template_id for display, page count."""
    if pdf_file is None:
        return "", None, "", 0
    path = pdf_file if isinstance(pdf_file, str) else (getattr(pdf_file, "name", None) or str(pdf_file))
    if not path or not Path(path).is_file():
        return "", None, "", 0
    template_id = Path(path).stem or "template"
    img = _page_to_image(path, 0)
    doc = fitz.open(path)
    n_pages = len(doc)
    doc.close()
    return path, img, template_id, n_pages


def on_page_change(pdf_path: str, page_no: int):
    """Re-render selected page."""
    if not pdf_path:
        return None
    return _page_to_image(pdf_path, page_no)


def on_preview(pdf_path: str, page_no: int, x0: float, y0: float, x1: float, y1: float):
    """Show page image with bbox overlay."""
    if not pdf_path:
        return None
    pno = int(page_no) if page_no is not None else 0
    img = _page_to_image(pdf_path, pno)
    if img is None:
        return None
    page_w, page_h = _page_rect(pdf_path, pno)
    return _draw_bbox_on_image(img, x0 or 0, y0 or 0, x1 or 100, y1 or 20, page_w, page_h)


def on_add_field(
    fields_json: str,
    schema_path: str,
    field_type: str,
    x0: float, y0: float, x1: float, y1: float,
    page_no: int,
) -> str:
    """Append one field to the list; return updated JSON string of fields."""
    try:
        fields = json.loads(fields_json) if fields_json.strip() else []
    except json.JSONDecodeError:
        fields = []
    fields.append({
        "schema_path": schema_path.strip(),
        "field_type": (field_type or "text").strip() or "text",
        "bbox": [round(float(x0 or 0), 2), round(float(y0 or 0), 2), round(float(x1 or 0), 2), round(float(y1 or 0), 2)],
        "page": int(page_no) if page_no is not None else 0,
    })
    return json.dumps(fields, indent=2)


def on_save(template_id: str, fields_json: str) -> str:
    """Write template_config.json to artifacts/_templates/<template_id>/template_config.json. Returns message."""
    repo_root = Path(__file__).resolve().parent.parent
    template_id = (template_id or "template").strip() or "template"
    try:
        fields = json.loads(fields_json) if fields_json.strip() else []
    except json.JSONDecodeError:
        return "Error: invalid fields JSON"
    out_dir = repo_root / "artifacts" / "_templates" / template_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "template_config.json"
    config = {"template_id": template_id, "fields": fields}
    out_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    out_path = out_path.resolve()
    if not out_path.is_file():
        raise RuntimeError(f"Save failed: file not found after write: {out_path}")
    saved_path = str(out_path)
    next_msg = (
        "NEXT: python3 scripts/run_local.py --pdf <packet> --template <template> --template-config " + saved_path
    )
    print(saved_path)
    print(next_msg)
    return f"Saved to {saved_path}\n\n{next_msg}"


def build_ui():
    with gr.Blocks(title="Template Builder") as demo:
        gr.Markdown("## Template Builder\nUpload a PDF, select page, add fields by bbox, then Save.")
        pdf_path = gr.State("")
        with gr.Row():
            pdf_upload = gr.File(label="Template PDF", type="filepath")
            template_id_out = gr.Textbox(label="Template ID (from filename)", interactive=False)
        with gr.Row():
            page_no = gr.Number(label="Page (0-based)", value=0, precision=0, minimum=0)
            page_btn = gr.Button("Show page")
        page_image = gr.Image(label="Page preview")
        gr.Markdown("### Field bbox (PDF points, e.g. 72, 100, 400, 120)")
        with gr.Row():
            schema_path = gr.Textbox(label="schema_path", placeholder="e.g. investor.legal_name")
            field_type = gr.Dropdown(choices=["text", "multiline", "checkbox", "date"], value="text", label="field_type")
        with gr.Row():
            x0 = gr.Number(label="x0", value=0)
            y0 = gr.Number(label="y0", value=0)
            x1 = gr.Number(label="x1", value=100)
            y1 = gr.Number(label="y1", value=20)
        with gr.Row():
            preview_btn = gr.Button("Preview bbox")
            add_btn = gr.Button("Add Field")
        fields_json = gr.Textbox(label="Fields (JSON)", value="[]", lines=8)
        with gr.Row():
            save_btn = gr.Button("Save template_config.json")
            save_msg = gr.Textbox(label="Save result", interactive=False)

        def upload_and_set(pdf_file):
            path, img, tid, n = on_upload(pdf_file)
            return path, img, tid, gr.update(maximum=max(0, n - 1))

        pdf_upload.change(
            upload_and_set,
            inputs=[pdf_upload],
            outputs=[pdf_path, page_image, template_id_out, page_no],
        )

        def show_page(path, pno):
            return on_page_change(path, int(pno) if pno is not None else 0)

        page_btn.click(
            show_page,
            inputs=[pdf_path, page_no],
            outputs=[page_image],
        )

        def do_preview(path, pno, a, b, c, d):
            return on_preview(path, int(pno) if pno is not None else 0, a or 0, b or 0, c or 100, d or 20)

        preview_btn.click(
            do_preview,
            inputs=[pdf_path, page_no, x0, y0, x1, y1],
            outputs=[page_image],
        )

        add_btn.click(
            on_add_field,
            inputs=[fields_json, schema_path, field_type, x0, y0, x1, y1, page_no],
            outputs=[fields_json],
        )

        def save(tid, fj):
            return on_save(tid, fj)

        save_btn.click(save, inputs=[template_id_out, fields_json], outputs=[save_msg])

    return demo


def main():
    demo = build_ui()
    demo.launch()


if __name__ == "__main__":
    main()
