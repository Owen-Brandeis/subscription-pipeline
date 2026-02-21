"""Map detected field candidates to schema paths using simple keyword rules. No LLM."""

from typing import Any

# Rules: (schema_path, list of keyword phrases; label matched case-insensitive)
# Order matters: first match wins. Put more specific labels before generic (e.g. "signed date" before "date").
SCHEMA_RULES = [
    ("investor.legal_name", ["legal name", "investor name", "entity name", "subscriber name", "name of subscriber", "name of investor", "name"]),
    ("investor.entity_type", ["entity type", "type of entity", "type of subscriber"]),
    ("investment.amount.value", ["subscription amount", "aggregate subscription", "commitment amount", "dollar amount", "investment amount", "amount of subscription", "commitment", "amount"]),
    ("investment.fund_name", ["fund name", "name of fund", "partnership"]),
    ("investment.class_series", ["class", "series", "class a", "series 1"]),
    ("investor.tax_id.value", ["ein", "ssn", "itin", "tax id", "tax identification", "taxpayer identification", "federal tax"]),
    ("investor.tax_id.type", ["tax id type", "identification type"]),
    ("investor.addresses[0].line1", ["address", "street", "street address", "line 1", "address line 1"]),
    ("investor.addresses[0].line2", ["address line 2", "suite", "unit", "line 2"]),
    ("investor.addresses[0].city", ["city"]),
    ("investor.addresses[0].state", ["state", "province"]),
    ("investor.addresses[0].postal_code", ["zip", "postal code", "zip code"]),
    ("investor.addresses[0].country", ["country"]),
    ("investor.contact.email", ["email", "e-mail"]),
    ("investor.contact.phone", ["phone", "telephone", "fax"]),
    ("signatures[0].signer_name", ["signature", "signer", "authorized signatory", "signed by", "name of signatory", "print name"]),
    ("signatures[0].signer_title", ["title", "signer title"]),
    ("signatures[0].signed_date", ["signed date", "signing date", "date signed", "execution date", "date"]),
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
