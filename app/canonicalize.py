"""Minimal v1 canonicalization of extracted subscription data. Does not invent missing values."""

import re
from datetime import datetime
from typing import Any


def _strip_strings(obj: Any) -> Any:
    """Recursively strip whitespace from all string values."""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, dict):
        return {k: _strip_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_strings(v) for v in obj]
    return obj


def _parse_amount_value(val: Any) -> Any:
    """Parse investment.amount.value: '$1,000,000' -> 1000000. Return unchanged if not a string or unparseable."""
    if isinstance(val, (int, float)):
        return val
    if not isinstance(val, str):
        return val
    s = val.strip().lstrip("$").replace(",", "").strip()
    if not s:
        return val
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return val


def _date_to_iso(s: str | None) -> str | None:
    """Best-effort parse common date formats to ISO YYYY-MM-DD. Returns None if missing or unparseable."""
    if not s or not isinstance(s, str):
        return s
    s = s.strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s


def _uppercase_state(val: Any) -> Any:
    """If string is exactly 2 letters, return uppercase. Else return unchanged."""
    if isinstance(val, str) and len(val.strip()) == 2 and val.strip().isalpha():
        return val.strip().upper()
    return val


def _normalize_states_in_addresses(addresses: Any) -> Any:
    if not isinstance(addresses, list):
        return addresses
    out = []
    for addr in addresses:
        if isinstance(addr, dict) and "state" in addr and addr["state"] is not None:
            addr = {**addr, "state": _uppercase_state(addr["state"])}
        out.append(addr)
    return out


def canonicalize(data: dict) -> dict:
    """
    Canonicalize extracted subscription data:
    - strip whitespace on all strings
    - normalize 2-letter state codes to uppercase
    - parse investment.amount.value from string like '$1,000,000' to number
    - parse signatures[0].signed_date to ISO if possible (best effort)
    Does not invent missing values.
    """
    out = _strip_strings(data)
    if not isinstance(out, dict):
        return data

    # State codes in addresses
    if "investor" in out and isinstance(out["investor"], dict) and "addresses" in out["investor"]:
        out["investor"] = {**out["investor"], "addresses": _normalize_states_in_addresses(out["investor"]["addresses"])}

    # investment.amount.value
    if "investment" in out and isinstance(out["investment"], dict):
        inv = out["investment"]
        if "amount" in inv and isinstance(inv["amount"], dict) and "value" in inv["amount"]:
            inv = {**inv, "amount": {**inv["amount"], "value": _parse_amount_value(inv["amount"]["value"])}}
            out = {**out, "investment": inv}

    # signatures[0].signed_date
    if "signatures" in out and isinstance(out["signatures"], list) and len(out["signatures"]) > 0:
        sig0 = out["signatures"][0]
        if isinstance(sig0, dict) and "signed_date" in sig0:
            sig0 = {**sig0, "signed_date": _date_to_iso(sig0.get("signed_date"))}
            out = {**out, "signatures": [sig0] + out["signatures"][1:]}

    return out
