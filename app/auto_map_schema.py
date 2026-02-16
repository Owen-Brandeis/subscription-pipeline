"""Map detected field candidates to schema paths using simple keyword rules. No LLM."""

from typing import Any

# Rules: (schema_path, list of keyword phrases; label matched case-insensitive)
SCHEMA_RULES = [
    ("investor.legal_name", ["name", "legal name", "investor name", "entity name", "subscriber name", "name of subscriber", "name of investor"]),
    ("investor.entity_type", ["entity type", "type of entity", "entity type"]),
    ("investment.amount.value", ["amount", "subscription amount", "investment amount", "commitment", "aggregate subscription", "dollar amount"]),
    ("investor.tax_id.value", ["ein", "ssn", "itin", "tax id", "tax identification", "taxpayer identification"]),
    ("signatures[0].signed_date", ["date", "signed date", "signing date", "date signed"]),
    ("signatures[0].signer_name", ["signature", "signer", "authorized signatory", "signed by", "name of signatory"]),
]

MIN_CONFIDENCE = 0.5


def _label_matches(label: str, keywords: list[str]) -> bool:
    if not label:
        return False
    lower = label.lower()
    return any(kw in lower for kw in keywords)


def map_candidates_to_schema(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Set schema_path on candidates when label matches a rule and confidence >= MIN_CONFIDENCE.
    Returns list of field dicts with schema_path set or null; other keys preserved.
    """
    out = []
    for i, c in enumerate(candidates):
        field = {
            "id": c.get("id") or f"auto_{i}",
            "schema_path": None,
            "page": c.get("page", 0),
            "bbox": c.get("field_bbox") or c.get("bbox"),
            "type": c.get("guess_type") or c.get("type", "text"),
            "font_size": c.get("font_size", 10),
            "label_text": c.get("label_text", ""),
            "confidence": c.get("confidence", 0),
        }
        conf = float(c.get("confidence", 0))
        if conf >= MIN_CONFIDENCE:
            label = (c.get("label_text") or "").strip()
            for schema_path, keywords in SCHEMA_RULES:
                if _label_matches(label, keywords):
                    field["schema_path"] = schema_path
                    break
        out.append(field)
    return out
