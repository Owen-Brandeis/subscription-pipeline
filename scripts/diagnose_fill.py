#!/usr/bin/env python3
"""
Diagnose why a filled PDF might be blank or wrong.
Usage: python3 scripts/diagnose_fill.py <case_id>
Prints: template config (with fallback), data lookup per field, overlay text sample.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/diagnose_fill.py <case_id>")
        sys.exit(1)
    case_id = sys.argv[1]
    cdir = REPO / "artifacts" / case_id
    if not cdir.is_dir():
        print(f"Case dir not found: {cdir}")
        sys.exit(1)

    from app.path_get import get_by_path
    from app.web import _template_config_for_fill

    config_path = cdir / "template_config_used.json"
    if not config_path.is_file():
        config_path = REPO / "artifacts" / "_templates" / "ttv_fund_vi_l_p_subscription_agreement_ca1b3a8a" / "template_config.json"
    canonical_path = cdir / "canonical.json"
    if not canonical_path.is_file():
        canonical_path = cdir / "extracted.json"
    if not config_path.is_file() or not canonical_path.is_file():
        print("Missing template_config_used.json or canonical/extracted.json")
        sys.exit(1)

    config = json.loads(config_path.read_text())
    data = json.loads(canonical_path.read_text())
    fill_config = _template_config_for_fill(config)

    print("=== Fill config (after fallback) ===\n")
    fields = fill_config.get("fields") or []
    has_any = sum(1 for f in fields if (f.get("schema_path") or "").strip())
    print(f"Total fields: {len(fields)}, with schema_path: {has_any}\n")

    for i, f in enumerate(fields[:10]):
        sp = (f.get("schema_path") or "").strip()
        val = get_by_path(data, sp) if sp else None
        bbox = f.get("bbox")
        print(f"  {i}: schema_path={sp!r} -> val={val!r} bbox={bbox}")

    filled_path = cdir / "filled.pdf"
    if filled_path.is_file():
        from pypdf import PdfReader
        r = PdfReader(str(filled_path))
        print("\n=== Filled PDF page count ===")
        print(len(r.pages))
        for i, page in enumerate(r.pages[:3]):
            t = (page.extract_text() or "").strip()[:150]
            print(f"  Page {i+1}: {t!r}...")
    else:
        print("\n(No filled.pdf yet; run pipeline first)")


if __name__ == "__main__":
    main()
