"""Validation of canonicalized extraction. Returns status and list of issues."""

import re
from typing import Any

ALLOWED_ENTITY_TYPES = frozenset(
    {"Individual", "Joint", "Trust", "IRA", "LLC", "Corporation", "Partnership", "Other"}
)


def _issues_append(
    issues: list[dict[str, str]], severity: str, field: str, reason: str
) -> None:
    issues.append({"severity": severity, "field": field, "reason": reason})


def _tax_id_format_valid(tax_type: str | None, value: str | None) -> bool:
    """True if value matches common format for type. Best effort."""
    if not value or not isinstance(value, str):
        return False
    digits = re.sub(r"\D", "", value)
    if tax_type == "SSN" or tax_type == "ITIN":
        return len(digits) == 9
    if tax_type == "EIN":
        return len(digits) == 9  # 2-7 or 9 digits
    return True


def validate_extraction(data: dict) -> dict[str, Any]:
    """
    Validate canonicalized extraction.
    Returns {"status": "pass"|"needs_review", "issues": [{"severity":"high"|"low","field":"...","reason":"..."}]}.
    """
    issues: list[dict[str, str]] = []

    investor = data.get("investor") if isinstance(data.get("investor"), dict) else None
    investment = data.get("investment") if isinstance(data.get("investment"), dict) else None
    signatures = data.get("signatures") if isinstance(data.get("signatures"), list) else None

    # High: investor.legal_name present
    if not investor:
        _issues_append(issues, "high", "investor", "investor missing")
    else:
        legal_name = investor.get("legal_name")
        if legal_name is None or (isinstance(legal_name, str) and not legal_name.strip()):
            _issues_append(issues, "high", "investor.legal_name", "investor.legal_name missing")

        # High: entity_type present and in allowed set
        et = investor.get("entity_type")
        if et is None or (isinstance(et, str) and not et.strip()):
            _issues_append(issues, "high", "investor.entity_type", "investor.entity_type missing")
        elif isinstance(et, str) and et.strip() not in ALLOWED_ENTITY_TYPES:
            _issues_append(issues, "high", "investor.entity_type", f"investor.entity_type not in allowed set: {list(ALLOWED_ENTITY_TYPES)}")

        # Low: tax_id.value present but invalid format
        tax_id = investor.get("tax_id") if isinstance(investor.get("tax_id"), dict) else None
        if tax_id and tax_id.get("value"):
            if not _tax_id_format_valid(tax_id.get("type"), tax_id.get("value")):
                _issues_append(issues, "low", "investor.tax_id.value", "tax_id.value present but invalid format")

        # Low: missing address pieces
        addrs = investor.get("addresses")
        if isinstance(addrs, list):
            for i, addr in enumerate(addrs):
                if not isinstance(addr, dict):
                    continue
                for key in ("line1", "city", "state", "postal_code", "country"):
                    if not addr.get(key) or (isinstance(addr.get(key), str) and not addr.get(key).strip()):
                        _issues_append(issues, "low", f"investor.addresses[{i}].{key}", f"missing or empty {key}")

    # High: investment.amount.value parses to number > 0
    if not investment:
        _issues_append(issues, "high", "investment", "investment missing")
    else:
        amount = investment.get("amount") if isinstance(investment.get("amount"), dict) else None
        if not amount:
            _issues_append(issues, "high", "investment.amount", "investment.amount missing")
        else:
            v = amount.get("value")
            if v is None:
                _issues_append(issues, "high", "investment.amount.value", "investment.amount.value missing")
            elif not isinstance(v, (int, float)):
                _issues_append(issues, "high", "investment.amount.value", "investment.amount.value must be a number")
            elif v <= 0:
                _issues_append(issues, "high", "investment.amount.value", "investment.amount.value must be > 0")

    # High: signatures[0].signer_name present
    if not signatures or len(signatures) == 0:
        _issues_append(issues, "high", "signatures", "signatures missing or empty")
    else:
        sig0 = signatures[0] if isinstance(signatures[0], dict) else None
        if not sig0:
            _issues_append(issues, "high", "signatures[0]", "signatures[0] missing")
        else:
            sn = sig0.get("signer_name")
            if sn is None or (isinstance(sn, str) and not sn.strip()):
                _issues_append(issues, "high", "signatures[0].signer_name", "signatures[0].signer_name missing")

    status = "pass" if not any(i["severity"] == "high" for i in issues) else "needs_review"
    return {"status": status, "issues": issues}
