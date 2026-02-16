#!/usr/bin/env python3
"""Analyze a flat PDF template and write detected fields to artifacts/_templates/<name>/detected_fields.json."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.template_analyzer import analyze_template


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze template PDF and save detected fields")
    parser.add_argument("--template", required=True, help="Path to template PDF")
    args = parser.parse_args()

    template_path = Path(args.template)
    if not template_path.is_file():
        print(f"Error: template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    result = analyze_template(str(template_path))
    template_name = template_path.stem
    out_dir = Path("artifacts") / "_templates" / template_name
    out_dir.mkdir(parents=True, exist_ok=True)

    detected_path = out_dir / "detected_fields.json"
    detected_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    config_path = out_dir / "template_config.json"
    if not config_path.exists():
        slug = template_name
        starter = {
            "template_id": slug,
            "pdf_sha256": result.get("pdf_sha256", ""),
            "page_count": result.get("page_count", 0),
            "fields": [],
        }
        config_path.write_text(json.dumps(starter, indent=2), encoding="utf-8")

    n = len(result.get("candidates", []))
    print(detected_path.resolve())
    print(config_path.resolve())
    print(f"Candidates: {n}")
    print("NEXT: python3 scripts/run_template_builder.py")


if __name__ == "__main__":
    main()
