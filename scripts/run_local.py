#!/usr/bin/env python3
"""CLI to run the subscription pipeline locally. Usage: python -m scripts.run_local --pdf <path> [--case-id ID]."""

import argparse
import json
import logging
import os
import random
import re
import string
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("REDUCTO_API_KEY", "").strip():
    raise ValueError(
        "REDUCTO_API_KEY missing. Copy .env.example to .env and set REDUCTO_API_KEY."
    )

# Add project root so "app" is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.fill_pdf import fill_pdf
from app.filler import fill_template
from app.pipeline import run_case_local
from app.storage_local import artifact_path, read_artifact_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def default_case_id(pdf_path: Path) -> str:
    """Safe slug from PDF stem: lowercase, non-alphanumeric -> underscore, max 60 chars + 6-char random suffix."""
    stem = pdf_path.stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    slug = slug[:60] if len(slug) > 60 else slug or "doc"
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{slug}_{suffix}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run subscription pipeline locally")
    parser.add_argument("--pdf", required=True, help="Path to input PDF")
    parser.add_argument(
        "--case-id",
        default=None,
        help="Case ID for artifacts (default: slug from PDF name + random suffix)",
    )
    parser.add_argument(
        "--template",
        default=None,
        help="Path to fillable PDF template; if set, fill from canonical and save filled.pdf",
    )
    parser.add_argument(
        "--field-map",
        default=None,
        help="Path to field_map.json (default: app/fill/field_map.json)",
    )
    parser.add_argument(
        "--template-config",
        default=None,
        help="Path to template_config.json for flat PDF filling; use with --template",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        logging.error("PDF not found: %s", pdf_path)
        sys.exit(1)

    case_id = args.case_id or default_case_id(pdf_path)
    try:
        out = run_case_local(pdf_path, case_id)
    except Exception as e:
        logging.exception("Pipeline failed: %s", e)
        sys.exit(1)

    if args.template:
        template_path = Path(args.template)
        if not template_path.is_file():
            logging.error("Template not found: %s", template_path)
            sys.exit(1)
        filled_path = artifact_path(case_id, "filled.pdf")
        if args.template_config:
            config_path = Path(args.template_config)
            if not config_path.is_file():
                logging.error("Template config not found: %s", config_path)
                sys.exit(1)
            with open(config_path, encoding="utf-8") as f:
                template_config = json.load(f)
            try:
                data = read_artifact_json(case_id, "canonical.json")
            except FileNotFoundError:
                try:
                    data = read_artifact_json(case_id, "extracted.json")
                except FileNotFoundError:
                    logging.error("Neither canonical.json nor extracted.json found for case_id=%s", case_id)
                    sys.exit(1)
            fill_template(
                str(template_path),
                template_config,
                data,
                str(filled_path),
            )
            out["filled.pdf"] = str(filled_path)
        else:
            root = Path(__file__).resolve().parent.parent
            field_map_path = Path(args.field_map) if args.field_map else root / "app" / "fill" / "field_map.json"
            if not field_map_path.is_file():
                logging.error("Field map not found: %s", field_map_path)
                sys.exit(1)
            with open(field_map_path, encoding="utf-8") as f:
                field_map = json.load(f)
            canonical = read_artifact_json(case_id, "canonical.json")
            fill_pdf(str(template_path), str(filled_path), canonical, field_map)
            out["filled.pdf"] = str(filled_path)

    print("Artifacts:")
    for name, path in out.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
