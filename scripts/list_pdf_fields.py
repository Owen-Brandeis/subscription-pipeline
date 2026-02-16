#!/usr/bin/env python3
"""List all AcroForm field names in a PDF template."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader


def main() -> None:
    parser = argparse.ArgumentParser(description="List AcroForm field names in a PDF")
    parser.add_argument("--template", required=True, help="Path to PDF template")
    args = parser.parse_args()

    path = Path(args.template)
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    reader = PdfReader(str(path))
    fields = reader.get_fields()
    if fields is None:
        names = []
    elif isinstance(fields, dict):
        names = sorted(fields.keys())
    else:
        names = sorted(getattr(f, "name", str(f)) for f in fields)

    for name in names:
        print(name)
    print(f"Count: {len(names)}")


if __name__ == "__main__":
    main()
