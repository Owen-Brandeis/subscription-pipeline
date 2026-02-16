"""Centralized artifact and repo path handling."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
TEMPLATES_ROOT = ARTIFACTS_ROOT / "_templates"
OUTBOX_ROOT = REPO_ROOT / "outbox"


def case_dir(case_id: str) -> Path:
    """Artifacts directory for a case: artifacts/<case_id>/."""
    return ARTIFACTS_ROOT / case_id


def inputs_dir(case_id: str) -> Path:
    """Inputs directory for a case: artifacts/<case_id>/inputs/."""
    return case_dir(case_id) / "inputs"


def ensure_dirs() -> None:
    """Create artifacts, _templates, and outbox if missing."""
    ARTIFACTS_ROOT.mkdir(exist_ok=True)
    TEMPLATES_ROOT.mkdir(exist_ok=True)
    OUTBOX_ROOT.mkdir(exist_ok=True)
