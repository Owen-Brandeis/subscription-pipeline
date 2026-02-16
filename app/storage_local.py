"""Local artifact storage under ./artifacts/{case_id}/."""

import json
import logging
from pathlib import Path

from app.paths import ARTIFACTS_ROOT

logger = logging.getLogger(__name__)


def _case_dir(case_id: str) -> Path:
    d = ARTIFACTS_ROOT / case_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def artifact_path(case_id: str, name: str) -> Path:
    """Path for an artifact file (does not create it)."""
    return _case_dir(case_id) / name


def write_artifact(case_id: str, name: str, content: bytes | str) -> Path:
    """Write artifact; content can be bytes or str (e.g. JSON string). Returns path."""
    path = artifact_path(case_id, name)
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)
    logger.info("Wrote artifact %s", path)
    return path


def read_artifact(case_id: str, name: str) -> bytes:
    """Read artifact as bytes."""
    path = artifact_path(case_id, name)
    return path.read_bytes()


def read_artifact_json(case_id: str, name: str) -> dict:
    """Read artifact as JSON dict."""
    raw = read_artifact(case_id, name).decode("utf-8")
    return json.loads(raw)
