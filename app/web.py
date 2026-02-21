"""Minimal FastAPI web UI: upload packet + outline template; template config is resolved or created as starter."""

import asyncio
import hashlib
import json
import logging
import random
import re
import shutil
import string
import time
from pathlib import Path
from typing import AsyncIterator

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse

from app.paths import (
    ARTIFACTS_ROOT,
    OUTBOX_ROOT,
    REPO_ROOT,
    TEMPLATES_ROOT,
    case_dir,
    ensure_dirs,
    inputs_dir,
)
from app.progress import ProgressEvent, emit, finish_subscription, init_case, subscribe

ALLOWED_DOWNLOADS = frozenset({
    "filled.pdf",
    "canonical.json",
    "validation_report.json",
    "extracted.json",
    "reducto_parse.json",
    "reducto_extract_raw.json",
    "template_config_used.json",
})

REQUIRED_PATHS = ["investor.legal_name", "investment.amount.value", "signatures[0].signer_name"]
MIN_REQUIRED_FILLED = 3

logger = logging.getLogger(__name__)

app = FastAPI(title="Subscription pipeline")


@app.on_event("startup")
def _on_startup():
    import os
    os.chdir(REPO_ROOT)
    ensure_dirs()


def _slug(filename: str) -> str:
    stem = Path(filename or "template").stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return slug[:60] if len(slug) > 60 else slug or "template"


def _template_id_from_bytes(template_bytes: bytes, filename: str) -> str:
    sha = hashlib.sha256(template_bytes).hexdigest()
    return f"{_slug(filename)}_{sha[:8]}"


def _default_case_id(packet_filename: str) -> str:
    stem = Path(packet_filename or "packet").stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    slug = slug[:60] if len(slug) > 60 else slug or "doc"
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{slug}_{suffix}"


def _find_template_config_by_sha256(template_sha256: str) -> tuple[Path, dict] | None:
    """Search _templates for template_config.json with matching pdf_sha256 and non-empty fields."""
    for config_path in TEMPLATES_ROOT.rglob("template_config.json"):
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            if cfg.get("pdf_sha256") != template_sha256:
                continue
            fields = cfg.get("fields")
            if isinstance(fields, list) and len(fields) > 0:
                return (config_path, cfg)
        except (json.JSONDecodeError, TypeError, OSError):
            continue
    return None


def _count_required_filled(data: dict) -> int:
    from app.path_get import get_by_path
    n = 0
    for path in REQUIRED_PATHS:
        v = get_by_path(data, path)
        if v is not None and str(v).strip():
            n += 1
    return n


RUN_RESULT_FILENAME = "run_result.json"


async def process_case(
    case_id: str,
    packet_path: Path,
    template_path: Path,
    template_config: dict,
    template_id: str,
    config_source: str,
    has_fields: bool,
) -> None:
    """Run pipeline + optional fill + deliver; emit progress and write run_result.json."""
    cdir = case_dir(case_id)
    ts = time.time

    try:
        # Parse (overall 10–45): run pipeline in thread, emit indeterminate progress
        emit(case_id, ProgressEvent(case_id, "parse", 0, 10, "Parse: uploading to Reducto…", ts()))
        loop = asyncio.get_event_loop()
        parse_extract_done = asyncio.Event()
        pipeline_exception: BaseException | None = None
        pipeline_result: dict | None = None

        def _run_pipeline() -> None:
            nonlocal pipeline_exception, pipeline_result
            try:
                from app.pipeline import run_case_local
                pipeline_result = run_case_local(str(packet_path), case_id)
            except BaseException as e:
                pipeline_exception = e

        async def _progress_ticker() -> None:
            start = time.time()
            max_wait = 120.0
            while not parse_extract_done.is_set():
                await asyncio.sleep(1.5)
                elapsed = time.time() - start
                if elapsed > max_wait:
                    break
                # Indeterminate: advance parse 20->90 then hold
                step_pct = min(90, 20 + int((elapsed / 20.0) * 70))
                overall = 10 + (step_pct / 100.0) * 35
                emit(case_id, ProgressEvent(
                    case_id, "parse", step_pct, int(overall),
                    "Parse: parsing… Waiting on provider.",
                    ts(),
                ))

        task = asyncio.create_task(asyncio.to_thread(_run_pipeline))
        ticker = asyncio.create_task(_progress_ticker())
        await task
        parse_extract_done.set()
        await ticker
        if pipeline_exception is not None:
            raise pipeline_exception

        emit(case_id, ProgressEvent(case_id, "parse", 100, 45, "Parse complete.", ts()))
        emit(case_id, ProgressEvent(case_id, "extract", 100, 75, "Extract complete.", ts()))

        (cdir / "template_config_used.json").write_text(
            json.dumps(template_config, indent=2), encoding="utf-8"
        )

        # Validate (75–85)
        emit(case_id, ProgressEvent(case_id, "validate", 0, 75, "Validating…", ts()))
        report = _read_json(cdir / "validation_report.json")
        emit(case_id, ProgressEvent(case_id, "validate", 100, 85, "Validation complete.", ts()))

        if not has_fields:
            _write_run_result(case_id, "no_config", template_id=template_id)
            emit(case_id, ProgressEvent(case_id, "done", 100, 100, "Done (no fill; template not configured).", ts()))
            finish_subscription(case_id)
            return

        data = _read_json(cdir / "canonical.json") or _read_json(cdir / "extracted.json")
        if not data:
            raise ValueError("No extraction data after pipeline.")

        # Fill (85–95): percent by fields processed
        from app.filler import fill_template
        filled_path = cdir / "filled.pdf"
        fields = template_config.get("fields") or []
        n_fields = len(fields)

        def _fill_progress(current: int, total: int) -> None:
            if total:
                step_pct = int(current / total * 100)
                overall = 85 + int(step_pct / 100 * 10)
                emit(case_id, ProgressEvent(
                    case_id, "fill", step_pct, overall,
                    f"Filling field {current}/{total}…",
                    ts(),
                ))

        emit(case_id, ProgressEvent(
            case_id, "fill", 0, 85,
            f"Filling template ({n_fields} fields)…",
            ts(),
        ))
        fill_config = _template_config_for_fill(template_config)
        fill_template(
            str(template_path), fill_config, data, str(filled_path),
            progress_callback=_fill_progress,
        )
        emit(case_id, ProgressEvent(case_id, "fill", 100, 95, "Fill complete.", ts()))

        if not filled_path.is_file():
            raise FileNotFoundError("Filled PDF was not produced.")

        # Deliver (95–100)
        outbox_filled = f"{case_id}_filled.pdf"
        total_bytes = filled_path.stat().st_size
        shutil.copy2(filled_path, OUTBOX_ROOT / outbox_filled)
        emit(case_id, ProgressEvent(
            case_id, "deliver", 50, 97,
            "Copying to outbox…",
            ts(),
        ))
        if (cdir / "canonical.json").is_file():
            shutil.copy2(cdir / "canonical.json", OUTBOX_ROOT / f"{case_id}_canonical.json")
        if (cdir / "validation_report.json").is_file():
            shutil.copy2(cdir / "validation_report.json", OUTBOX_ROOT / f"{case_id}_validation_report.json")
        emit(case_id, ProgressEvent(case_id, "deliver", 100, 100, "Delivered to outbox.", ts()))

        validation_status = (report or {}).get("status", "unknown")
        required_filled = _count_required_filled(data)
        needs_review = required_filled < MIN_REQUIRED_FILLED
        missing = [p for p in REQUIRED_PATHS if not _get_path(data, p)]
        _write_run_result(
            case_id, "done",
            template_id=template_id,
            config_source=config_source,
            validation_status=validation_status,
            needs_review=needs_review,
            missing_required=missing,
            outbox_filled_filename=outbox_filled,
        )
        emit(case_id, ProgressEvent(case_id, "done", 100, 100, "Done.", ts()))
    except Exception as e:
        logger.exception("Run failed case_id=%s", case_id)
        _write_run_result(case_id, "error", error_message=f"{type(e).__name__}: {e}")
        emit(case_id, ProgressEvent(
            case_id, "error", 100, 100,
            f"Error: {type(e).__name__}: {e}",
            ts(),
        ))
    finally:
        finish_subscription(case_id)


def _write_run_result(
    case_id: str,
    result_type: str,
    *,
    template_id: str | None = None,
    config_source: str | None = None,
    validation_status: str | None = None,
    needs_review: bool = False,
    missing_required: list[str] | None = None,
    outbox_filled_filename: str | None = None,
    error_message: str | None = None,
) -> None:
    payload = {"result_type": result_type}
    if template_id is not None:
        payload["template_id"] = template_id
    if config_source is not None:
        payload["config_source"] = config_source
    if validation_status is not None:
        payload["validation_status"] = validation_status
    if needs_review is not None:
        payload["needs_review"] = needs_review
    if missing_required is not None:
        payload["missing_required"] = missing_required
    if outbox_filled_filename is not None:
        payload["outbox_filled_filename"] = outbox_filled_filename
    if error_message is not None:
        payload["error_message"] = error_message
    (case_dir(case_id) / RUN_RESULT_FILENAME).write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _read_run_result(case_id: str) -> dict | None:
    p = case_dir(case_id) / RUN_RESULT_FILENAME
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _template_config_for_fill(template_config: dict) -> dict:
    """
    Return a copy of template_config. If any field has schema_path set, return as-is.
    If all fields have null schema_path, assign REQUIRED_PATHS to the first N text/multiline
    fields in document order so Reducto-extracted data gets drawn (avoids blank output).
    """
    fields = template_config.get("fields")
    if not isinstance(fields, list) or not fields:
        return template_config
    has_any_path = any((f.get("schema_path") or "").strip() for f in fields if isinstance(f, dict))
    if has_any_path:
        return template_config
    # Sort by page then -y0 (top-first) then x0 for document order
    def _key(f: dict) -> tuple:
        page = int(f.get("page", 0))
        bbox = f.get("bbox") or [0, 0, 0, 0]
        y0 = float(bbox[1]) if len(bbox) >= 2 else 0
        x0 = float(bbox[0]) if len(bbox) >= 1 else 0
        return (page, -y0, x0)
    sorted_fields = sorted(
        [dict(f) for f in fields if isinstance(f, dict)],
        key=_key,
    )
    default_paths = list(REQUIRED_PATHS)
    path_idx = 0
    for f in sorted_fields:
        if path_idx >= len(default_paths):
            break
        if (f.get("schema_path") or "").strip():
            continue
        if _get_field_type_for_fill(f) not in ("text", "multiline"):
            continue
        f["schema_path"] = default_paths[path_idx]
        path_idx += 1
    return {**template_config, "fields": sorted_fields}


def _get_field_type_for_fill(f: dict) -> str:
    t = (f.get("type") or f.get("field_type") or "text")
    return str(t).strip().lower()


@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!DOCTYPE html>
<html>
<head><title>Subscription pipeline</title></head>
<body>
  <h1>Upload & fill</h1>
  <form action="/run" method="post" enctype="multipart/form-data">
    <p>
      <label>Packet PDF (required): <input type="file" name="filled_packet_pdf" accept=".pdf" required></label>
    </p>
    <p>
      <label>Outline template PDF (required): <input type="file" name="outline_template_pdf" accept=".pdf" required></label>
    </p>
    <p><button type="submit">Run</button></p>
  </form>
</body>
</html>
"""


@app.post("/run", response_class=HTMLResponse)
async def run(
    background_tasks: BackgroundTasks,
    filled_packet_pdf: UploadFile = File(...),
    outline_template_pdf: UploadFile = File(...),
    case_id: str = Form(""),
):
    if not filled_packet_pdf or not (filled_packet_pdf.filename or "").strip():
        return _error_html("Packet PDF upload is missing or has no filename. Please select a file for &quot;Packet PDF&quot;.")
    if not outline_template_pdf or not (outline_template_pdf.filename or "").strip():
        return _error_html("Outline template PDF upload is missing or has no filename. Please select a file for &quot;Outline template PDF&quot;.")

    raw_case_id = (case_id or "").strip()
    if raw_case_id and any(c in raw_case_id for c in "/\\."):
        raw_case_id = ""
    case_id = raw_case_id or _default_case_id(filled_packet_pdf.filename or "")
    init_case(case_id)
    cdir = case_dir(case_id)
    inp = inputs_dir(case_id)
    inp.mkdir(parents=True, exist_ok=True)

    packet_path = inp / "packet.pdf"
    try:
        packet_bytes = await filled_packet_pdf.read()
        packet_path.write_bytes(packet_bytes)
        emit(case_id, ProgressEvent(case_id, "upload", 50, 5, "Packet saved.", time.time()))
    except Exception as e:
        logger.exception("Saving packet failed")
        return _error_html(f"Failed to save packet upload: {e}")

    template_bytes = await outline_template_pdf.read()
    template_filename = (outline_template_pdf.filename or "").strip() or "template.pdf"
    if not template_bytes:
        return _error_html("Outline template PDF is empty. Please upload a non-empty template file.")
    template_path_in_inputs = inp / "template.pdf"
    try:
        template_path_in_inputs.write_bytes(template_bytes)
        emit(case_id, ProgressEvent(case_id, "upload", 100, 10, "Uploads saved.", time.time()))
    except Exception as e:
        logger.exception("Saving template to inputs failed")
        return _error_html(f"Failed to save template upload: {e}")

    logger.info("case_id=%s saved_packet=%s saved_template=%s", case_id, str(packet_path.resolve()), str(template_path_in_inputs.resolve()))

    template_sha256 = hashlib.sha256(template_bytes).hexdigest()
    template_id = _template_id_from_bytes(template_bytes, template_filename)
    tdir = TEMPLATES_ROOT / template_id
    tdir.mkdir(parents=True, exist_ok=True)
    template_path = tdir / "template.pdf"
    if not template_path.is_file():
        template_path.write_bytes(template_bytes)
        logger.info("New template_id created: %s", template_id)

    template_config = None
    config_source = "existing"
    found = _find_template_config_by_sha256(template_sha256)
    if found:
        _config_path, template_config = found
        config_source = "existing"

    if template_config is None:
        from app.template_analyzer import analyze_template
        try:
            result = analyze_template(str(template_path))
        except Exception as e:
            logger.exception("analyze_template failed")
            return _error_html(f"Template analysis failed: {type(e).__name__}: {e}. Check server logs.")
        (tdir / "detected_fields.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        from app.auto_map_schema import map_candidates_to_schema
        candidates = result.get("candidates") or []
        mapped_fields = map_candidates_to_schema(candidates)
        starter_config = {
            "template_id": template_id,
            "pdf_sha256": result.get("pdf_sha256", template_sha256),
            "page_count": result.get("page_count", 0),
            "fields": mapped_fields,
        }
        (tdir / "template_config.json").write_text(json.dumps(starter_config, indent=2), encoding="utf-8")
        template_config = starter_config
        config_source = "starter"

    fields = template_config.get("fields") if isinstance(template_config, dict) else []
    has_fields = isinstance(fields, list) and len(fields) > 0

    background_tasks.add_task(
        process_case,
        case_id,
        packet_path,
        template_path,
        template_config,
        template_id,
        config_source,
        has_fields,
    )
    return _progress_html(case_id)


def _get_path(data: dict, path: str):
    from app.path_get import get_by_path
    v = get_by_path(data, path)
    return v is not None and str(v).strip()


def _read_json(p: Path) -> dict | None:
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _progress_html(case_id: str) -> str:
    """HTML page with progress bar and JS that subscribes to SSE, then redirects to /result on done/error."""
    escaped_id = _escape(case_id)
    return f"""
<!DOCTYPE html>
<html>
<head><title>Processing</title></head>
<body>
  <h1>Processing</h1>
  <p>Case ID: <code>{escaped_id}</code></p>
  <div id="progress" style="max-width:400px;border:1px solid #ccc;height:24px;border-radius:4px;overflow:hidden;">
    <div id="bar" style="height:100%;width:0%;background:#0a0;transition:width 0.2s;"></div>
  </div>
  <p id="msg" style="margin-top:8px;"></p>
  <p id="links" style="margin-top:12px;"></p>
  <script>
    const caseId = {json.dumps(case_id)};
    const bar = document.getElementById("bar");
    const msg = document.getElementById("msg");
    const links = document.getElementById("links");
    const es = new EventSource("/events/" + encodeURIComponent(caseId));
    es.onmessage = function(e) {{
      const d = JSON.parse(e.data);
      bar.style.width = d.overall_percent + "%";
      msg.textContent = d.message || "";
      if (d.step === "done" || d.step === "error") {{
        es.close();
        window.location.href = "/result/" + encodeURIComponent(caseId);
      }}
    }};
    es.onerror = function() {{
      msg.textContent = "Connection closed. Check /result/" + caseId + " for status.";
      es.close();
    }};
  </script>
</body>
</html>
"""


def _error_html(message: str, link_html: str | None = None) -> str:
    p_content = _escape(message)
    if link_html:
        p_content += link_html
    return f"""
<!DOCTYPE html>
<html>
<head><title>Error</title></head>
<body>
  <h1>Error</h1>
  <p>{p_content}</p>
  <p><a href="/">Back to form</a></p>
</body>
</html>
"""


def _no_config_result_html(case_id: str, template_id: str) -> str:
    base = f"/download/{case_id}"
    return f"""
<!DOCTYPE html>
<html>
<head><title>Template not configured</title></head>
<body>
  <h1>Template mapping not configured yet</h1>
  <p>No filled PDF produced. Extraction and validation ran for case <code>{_escape(case_id)}</code>.</p>
  <p>Template ID: <code>{_escape(template_id)}</code></p>
  <p><strong>Download the starter template config</strong> to configure field mapping (add schema_path and bbox), then re-upload:</p>
  <p><a href="{base}/template_config_used.json">Download template_config_used.json (starter)</a></p>
  <p><a href="{base}/validation_report.json">Download validation_report.json</a></p>
  <p><a href="/">Run another</a></p>
</body>
</html>
"""


def _result_html(
    case_id: str,
    validation_status: str,
    template_id: str,
    config_source: str,
    needs_review: bool,
    missing_required: list[str],
    outbox_filled_filename: str,
) -> str:
    base = f"/download/{case_id}"
    outbox_base = "/download_outbox"
    missing_blurb = ""
    if needs_review and missing_required:
        missing_blurb = f"<p>Missing or empty required fields: {_escape(', '.join(missing_required))}. Template config may be incomplete.</p>"
    return f"""
<!DOCTYPE html>
<html>
<head><title>Done</title></head>
<body>
  <h1>Done</h1>
  <p>Case ID: <code>{_escape(case_id)}</code></p>
  <p>Validation status: <strong>{_escape(validation_status)}</strong></p>
  <p>Template ID: <code>{_escape(template_id)}</code> (config: {_escape(config_source)})</p>
  {missing_blurb}
  <p><strong><a href="{outbox_base}/{_escape(outbox_filled_filename)}">Download Filled PDF</a></strong></p>
  <p>Saved to outbox/{_escape(outbox_filled_filename)}</p>
  <p><a href="{base}/filled.pdf">Download filled.pdf (artifacts)</a></p>
  <p><a href="{base}/canonical.json">Download canonical.json</a></p>
  <p><a href="{base}/validation_report.json">Download validation_report.json</a></p>
  <p><a href="{base}/template_config_used.json">Download template config used</a></p>
  <p><a href="/">Run another</a></p>
</body>
</html>
"""


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@app.get("/download/{case_id}/{filename}")
def download(case_id: str, filename: str):
    if "/" in case_id or "\\" in case_id or case_id in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid case_id")
    if filename not in ALLOWED_DOWNLOADS:
        raise HTTPException(status_code=400, detail="Filename not allowed")
    path = (ARTIFACTS_ROOT / case_id / filename).resolve()
    if not str(path).startswith(str(ARTIFACTS_ROOT.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)


@app.get("/download_outbox/{filename}")
def download_outbox(filename: str):
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.endswith(".pdf") and not filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .pdf and .json files allowed")
    path = (OUTBOX_ROOT / filename).resolve()
    if not str(path).startswith(str(OUTBOX_ROOT.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)


@app.get("/events/{case_id}")
async def events(case_id: str):
    """Stream progress events as Server-Sent Events. Closes when step is done or error."""
    if "/" in case_id or "\\" in case_id or case_id in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid case_id")

    async def stream() -> AsyncIterator[str]:
        async for event in subscribe(case_id):
            yield f"data: {json.dumps(event.to_dict())}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/result/{case_id}", response_class=HTMLResponse)
def result(case_id: str):
    """Render final result page from run_result.json (after SSE reports done/error)."""
    if "/" in case_id or "\\" in case_id or case_id in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid case_id")
    r = _read_run_result(case_id)
    if r is None:
        raise HTTPException(
            status_code=404,
            detail="Result not ready. Processing may still be running or the case_id is unknown.",
        )
    result_type = r.get("result_type", "error")
    if result_type == "done":
        return _result_html(
            case_id=case_id,
            validation_status=r.get("validation_status", "unknown"),
            template_id=r.get("template_id", ""),
            config_source=r.get("config_source", ""),
            needs_review=r.get("needs_review", False),
            missing_required=r.get("missing_required", []),
            outbox_filled_filename=r.get("outbox_filled_filename", f"{case_id}_filled.pdf"),
        )
    if result_type == "no_config":
        return _no_config_result_html(case_id=case_id, template_id=r.get("template_id", ""))
    return _error_html(
        r.get("error_message", "Unknown error."),
        link_html=f' <a href="/download/{case_id}/validation_report.json">Download validation_report.json</a>' if (case_dir(case_id) / "validation_report.json").is_file() else None,
    )
