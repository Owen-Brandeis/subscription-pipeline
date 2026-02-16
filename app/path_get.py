"""Get nested dict/list values by path like 'signatures[0].signer_name'."""

import re
from typing import Any


def get_by_path(data: dict | list, path: str) -> Any:
    """
    Get value from nested dict/list using path with dots and [index].
    Example: get_by_path(data, "signatures[0].signer_name") -> value or None.
    """
    parts = re.split(r"\.|\[|\]", path)
    parts = [p.strip() for p in parts if p.strip()]
    obj: Any = data
    for p in parts:
        if p.isdigit():
            idx = int(p)
            if isinstance(obj, list) and 0 <= idx < len(obj):
                obj = obj[idx]
            else:
                return None
        else:
            if isinstance(obj, dict) and p in obj:
                obj = obj[p]
            else:
                return None
    return obj
