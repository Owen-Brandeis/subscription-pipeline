"""Regression tests for web and path handling. Do not call external APIs; use mocks or env REDUCTO_MOCK=1."""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_web_path_precedence_regression():
    """Ensure no code contains path / \"file\".write_text or .write_bytes (operator precedence bug)."""
    # Bad: "/ \"file\".write_text("  Good: ").write_text(" (path in parens).
    bad = re.compile(r'"\.write_(?:text|bytes)\s*\(')
    found = []
    for py_path in REPO_ROOT.rglob("*.py"):
        if "venv" in str(py_path) or ".venv" in str(py_path) or "tests" in str(py_path):
            continue
        text = py_path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            for m in bad.finditer(line):
                # Good: ) before this "  (i.e. (path / "file").write_)
                idx = m.start()
                if idx > 0 and line[idx - 1] == ")":
                    continue
                found.append((str(py_path.relative_to(REPO_ROOT)), i, line.strip()))
                break
    assert not found, f"Path precedence bug: use (path / \"file\").write_text(...). Found: {found}"


def test_template_config_written_when_config_exists(tmp_path, monkeypatch):
    """When run completes with existing config, template_config_used.json is written under case dir."""
    import json as _json
    from app.paths import ARTIFACTS_ROOT, TEMPLATES_ROOT, ensure_dirs

    monkeypatch.chdir(REPO_ROOT)
    ensure_dirs()
    case_id = "test_case_config"
    cdir = ARTIFACTS_ROOT / case_id
    cdir.mkdir(parents=True, exist_ok=True)
    inp = cdir / "inputs"
    inp.mkdir(parents=True, exist_ok=True)
    template_bytes = b"%PDF-1.4 minimal template"
    import hashlib
    template_sha256 = hashlib.sha256(template_bytes).hexdigest()
    (inp / "packet.pdf").write_bytes(b"%PDF-1.4 minimal packet")
    (inp / "template.pdf").write_bytes(template_bytes)
    template_id = f"minimal_template_{template_sha256[:8]}"
    tdir = TEMPLATES_ROOT / template_id
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "template.pdf").write_bytes(template_bytes)
    config_with_fields = {
        "template_id": template_id,
        "pdf_sha256": template_sha256,
        "page_count": 1,
        "fields": [{"schema_path": "investor.legal_name", "page": 0, "bbox": [100, 100, 200, 120]}],
    }
    (tdir / "template_config.json").write_text(
        _json.dumps(config_with_fields, indent=2), encoding="utf-8"
    )
    (cdir / "canonical.json").write_text(
        _json.dumps({"investor": {"legal_name": "Acme"}}, indent=2), encoding="utf-8"
    )
    (cdir / "validation_report.json").write_text(
        _json.dumps({"status": "ok", "issues": []}, indent=2), encoding="utf-8"
    )

    with patch("app.pipeline.run_case_local"):
        with patch("app.filler.fill_template"):
            from fastapi.testclient import TestClient
            from app.web import app, RUN_RESULT_FILENAME

            client = TestClient(app)
            with open(inp / "packet.pdf", "rb") as f1, open(inp / "template.pdf", "rb") as f2:
                r = client.post(
                    "/run",
                    data={"case_id": case_id},
                    files={
                        "filled_packet_pdf": ("packet.pdf", f1.read(), "application/pdf"),
                        "outline_template_pdf": ("template.pdf", f2.read(), "application/pdf"),
                    },
                )
    assert r.status_code == 200
    # Wait for background task to finish (poll run_result.json)
    import time
    for _ in range(50):
        if (cdir / RUN_RESULT_FILENAME).is_file():
            break
        time.sleep(0.2)
    used = cdir / "template_config_used.json"
    assert used.is_file(), "template_config_used.json should be written when config exists"
    data = _json.loads(used.read_text(encoding="utf-8"))
    assert data.get("fields") and len(data["fields"]) > 0


def test_outbox_copy_when_filled_pdf_exists(tmp_path, monkeypatch):
    """When filled.pdf is produced, outbox/<case_id>_filled.pdf exists after run."""
    import json as _json
    import hashlib
    from app.paths import ARTIFACTS_ROOT, OUTBOX_ROOT, TEMPLATES_ROOT, ensure_dirs

    monkeypatch.chdir(REPO_ROOT)
    ensure_dirs()
    case_id = "test_outbox_case"
    cdir = ARTIFACTS_ROOT / case_id
    cdir.mkdir(parents=True, exist_ok=True)
    inp = cdir / "inputs"
    inp.mkdir(parents=True, exist_ok=True)
    packet_bytes = b"%PDF-1.4 packet"
    template_bytes = b"%PDF-1.4 template"
    (inp / "packet.pdf").write_bytes(packet_bytes)
    (inp / "template.pdf").write_bytes(template_bytes)
    template_sha256 = hashlib.sha256(template_bytes).hexdigest()
    template_id = f"template_{template_sha256[:8]}"
    tdir = TEMPLATES_ROOT / template_id
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "template.pdf").write_bytes(template_bytes)
    config = {
        "template_id": template_id,
        "pdf_sha256": template_sha256,
        "page_count": 1,
        "fields": [{"schema_path": "investor.legal_name", "page": 0, "bbox": [100, 100, 200, 120]}],
    }
    (tdir / "template_config.json").write_text(_json.dumps(config, indent=2), encoding="utf-8")
    (cdir / "canonical.json").write_text(
        _json.dumps({"investor": {"legal_name": "Acme"}}, indent=2), encoding="utf-8"
    )
    (cdir / "validation_report.json").write_text(
        _json.dumps({"status": "ok", "issues": []}, indent=2), encoding="utf-8"
    )

    def _mock_fill(template_pdf_path, template_config, data, output_pdf_path):
        Path(output_pdf_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_pdf_path).write_bytes(b"%PDF-1.4 filled")

    with patch("app.pipeline.run_case_local"):
        with patch("app.filler.fill_template", side_effect=_mock_fill):
            from fastapi.testclient import TestClient
            from app.web import app, RUN_RESULT_FILENAME

            client = TestClient(app)
            with open(inp / "packet.pdf", "rb") as f1, open(inp / "template.pdf", "rb") as f2:
                r = client.post(
                    "/run",
                    data={"case_id": case_id},
                    files={
                        "filled_packet_pdf": ("packet.pdf", f1.read(), "application/pdf"),
                        "outline_template_pdf": ("template.pdf", f2.read(), "application/pdf"),
                    },
                )
    assert r.status_code == 200
    import time
    for _ in range(50):
        if (cdir / RUN_RESULT_FILENAME).is_file():
            break
        time.sleep(0.2)
    outbox_pdf = OUTBOX_ROOT / f"{case_id}_filled.pdf"
    assert outbox_pdf.is_file(), "outbox/<case_id>_filled.pdf should exist after successful run"
