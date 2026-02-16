"""Fill AcroForm PDF from canonical data using a field mapping."""

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter


def _get_by_path(data: dict, path: str) -> Any:
    """Get value from nested dict using path like 'investor.legal_name' or 'signatures[0].signer_name'."""
    parts = re.split(r"\.|\[|\]", path)
    parts = [p for p in parts if p != ""]
    obj: Any = data
    for i, p in enumerate(parts):
        if p.isdigit():
            if isinstance(obj, list) and 0 <= int(p) < len(obj):
                obj = obj[int(p)]
            else:
                return None
        else:
            if isinstance(obj, dict) and p in obj:
                obj = obj[p]
            else:
                return None
    return obj


def _to_field_value(val: Any) -> str:
    """Convert value for PDF form: None -> '', numbers -> string."""
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        return str(val)
    return str(val)


def fill_pdf(
    template_path: str,
    output_path: str,
    data: dict,
    field_map: dict[str, str],
) -> None:
    """
    Fill AcroForm fields in template_path with values from data using field_map.
    field_map: data path (e.g. investor.legal_name) -> PDF field name (e.g. InvestorName).
    Writes filled PDF to output_path. Converts None to "", numbers to strings.
    """
    reader = PdfReader(template_path)
    writer = PdfWriter()
    writer.append(reader)

    values: dict[str, str] = {}
    for data_path, pdf_field_name in field_map.items():
        val = _get_by_path(data, data_path)
        values[pdf_field_name] = _to_field_value(val)

    for page in writer.pages:
        writer.update_page_form_field_values(
            page,
            values,
            auto_regenerate=False,
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)
