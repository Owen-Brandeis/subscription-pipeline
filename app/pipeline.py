"""Local pipeline: read PDF → parse → save → extract with schema → save → return paths."""

import json
import logging
from pathlib import Path

from app.canonicalize import canonicalize
from app.reducto_client import ReductoClient
from app.storage_local import write_artifact
from app.validate import validate_extraction

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "subscription_schema.json"

PARSE_ARTIFACT = "reducto_parse.json"
EXTRACT_RAW_ARTIFACT = "reducto_extract_raw.json"
EXTRACTED_ARTIFACT = "extracted.json"
CANONICAL_ARTIFACT = "canonical.json"
VALIDATION_REPORT_ARTIFACT = "validation_report.json"


def _load_schema() -> dict:
    data = SCHEMA_PATH.read_text(encoding="utf-8")
    return json.loads(data)


def _unwrap_citation_values(obj):
    """If extract used citations, leaf values may be {value: X, citations: [...]}. Unwrap to X for downstream."""
    if isinstance(obj, dict):
        # Citation wrapper: only "value" and optionally "citations" -> use value
        if "citations" in obj and "value" in obj:
            return _unwrap_citation_values(obj["value"])
        return {k: _unwrap_citation_values(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unwrap_citation_values(v) for v in obj]
    return obj


def run_case_local(pdf_path: str | Path, case_id: str) -> dict[str, str]:
    """
    Run parse then extract for one case. Writes artifacts under ./artifacts/{case_id}/.
    Returns dict with paths for reducto_parse.json, reducto_extract_raw.json, extracted.json, canonical.json, validation_report.json.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info("Running local pipeline case_id=%s pdf=%s", case_id, pdf_path)
    pdf_bytes = pdf_path.read_bytes()

    client = ReductoClient()
    parse_response = client.parse_pdf_bytes(pdf_bytes)
    parse_path = write_artifact(
        case_id, PARSE_ARTIFACT, json.dumps(parse_response, indent=2)
    )

    schema = _load_schema()
    logger.info("Using schema title=%s path=%s", schema.get("title"), SCHEMA_PATH)
    extract_raw = client.extract_from_parse(parse_response, schema)

    extracted = {}
    if isinstance(extract_raw, dict) and "result" in extract_raw:
        res = extract_raw["result"]
        if isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict):
            extracted = _unwrap_citation_values(res[0])
        elif isinstance(res, dict):
            extracted = _unwrap_citation_values(res)
        else:
            extracted = _unwrap_citation_values(res)

    extract_raw_path = write_artifact(
        case_id, EXTRACT_RAW_ARTIFACT, json.dumps(extract_raw, indent=2)
    )
    extracted_path = write_artifact(
        case_id, EXTRACTED_ARTIFACT, json.dumps(extracted, indent=2)
    )

    canonical = canonicalize(extracted)
    canonical_path = write_artifact(
        case_id, CANONICAL_ARTIFACT, json.dumps(canonical, indent=2)
    )
    report = validate_extraction(canonical)
    validation_report_path = write_artifact(
        case_id, VALIDATION_REPORT_ARTIFACT, json.dumps(report, indent=2)
    )

    print(extract_raw_path)
    print(extracted_path)
    print(f"Validation status: {report['status']}, issues: {len(report['issues'])}")

    return {
        PARSE_ARTIFACT: str(parse_path),
        EXTRACT_RAW_ARTIFACT: str(extract_raw_path),
        EXTRACTED_ARTIFACT: str(extracted_path),
        CANONICAL_ARTIFACT: str(canonical_path),
        VALIDATION_REPORT_ARTIFACT: str(validation_report_path),
    }
