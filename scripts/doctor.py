#!/usr/bin/env python3
"""Verify environment and required files for the pipeline and template builder."""

import sys
from pathlib import Path

# Run from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent


def check_import(name: str, pip_name: str | None = None) -> bool:
    """Return True if import succeeds. pip_name is the pip package name (default same as name)."""
    pip_name = pip_name or name
    try:
        __import__(name)
        return True
    except ImportError:
        print(f"  MISSING {name}  ->  {sys.executable} -m pip install {pip_name}")
        return False
    return True


def main() -> int:
    print("=== Environment ===")
    print(f"  Python: {sys.executable}")
    print(f"  Version: {sys.version.split()[0]}")
    print()

    print("=== Dependencies ===")
    deps = [
        ("httpx", "httpx"),
        ("tenacity", "tenacity"),
        ("dotenv", "python-dotenv"),
        ("fitz", "PyMuPDF"),
        ("reportlab", "reportlab"),
        ("pypdf", "pypdf"),
        ("gradio", "gradio"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
    ]
    all_ok = True
    for mod, pip in deps:
        if check_import(mod, pip):
            print(f"  OK {mod}")
        else:
            all_ok = False
    print()

    print("=== Repo paths ===")
    (REPO_ROOT / "artifacts").mkdir(exist_ok=True)
    (REPO_ROOT / "artifacts" / "_templates").mkdir(exist_ok=True)
    (REPO_ROOT / "outbox").mkdir(exist_ok=True)
    print("  OK artifacts/")
    print("  OK artifacts/_templates/")
    print("  OK outbox/")

    schema_path = REPO_ROOT / "app" / "schemas" / "subscription_schema.json"
    if schema_path.is_file():
        print(f"  OK app/schemas/subscription_schema.json")
    else:
        print(f"  MISSING (required) app/schemas/subscription_schema.json")
        all_ok = False

    for label, p in [
        ("app/paths.py", REPO_ROOT / "app" / "paths.py"),
        ("app/progress.py", REPO_ROOT / "app" / "progress.py"),
        ("app/web.py", REPO_ROOT / "app" / "web.py"),
        ("scripts/doctor.py", REPO_ROOT / "scripts" / "doctor.py"),
        ("scripts/analyze_template.py", REPO_ROOT / "scripts" / "analyze_template.py"),
        ("scripts/run_template_builder.py", REPO_ROOT / "scripts" / "run_template_builder.py"),
    ]:
        if p.is_file():
            print(f"  OK {label}")
        else:
            print(f"  WARN (missing) {label}")
    print()

    print("=== Found under artifacts/_templates/ ===")
    templates_dir = REPO_ROOT / "artifacts" / "_templates"
    detected = list(templates_dir.rglob("detected_fields.json"))
    configs = list(templates_dir.rglob("template_config.json"))
    if detected:
        for f in sorted(detected):
            print(f"  detected_fields.json: {f.relative_to(REPO_ROOT)}")
    else:
        print("  detected_fields.json: (none)")
    if configs:
        for f in sorted(configs):
            print(f"  template_config.json: {f.relative_to(REPO_ROOT)}")
    else:
        print("  template_config.json: (none)")
    print()

    if not all_ok:
        print("Fix missing items above, then re-run.")
        return 1
    print("All required checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
