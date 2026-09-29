"""Metre ware: material bought by length, such as the belts of carriages.

Suppliers quote these per metre, or per foot (and sometimes per inch or
yard), so a price is a number per metre, or a number with a unit: "2.40",
"2,40", "2.40/m", "0.75/ft". A decimal comma is fine.

``parse_price`` is pure Python (pytest loads this module without FreeCAD);
``report`` reads the document and is called by ``cutlist.build_report``.
"""

import re
from collections import OrderedDict

HEADER = ("Qty", "Item", "Length each (mm)", "Price", "Per", "Cost", "Used by")
UNITS = {"m": 1.0, "ft": 0.3048, "in": 0.0254, "yd": 0.9144}
_PRICE = re.compile(r"\s*([0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)\s*(?:/\s*([a-zA-Z]+)\.?)?\s*")
_UNIT_NAMES = {"m": "m", "metre": "m", "meter": "m", "ft": "ft", "foot": "ft", "feet": "ft",
               "in": "in", "inch": "in", "yd": "yd", "yard": "yd"}


def parse_price(text):
    """(price, unit) from a price text, or None when it is empty or not understood.

    The unit is one of UNITS; a plain number is per metre.
    """
    m = _PRICE.fullmatch(str(text or ""))
    if not m:
        return None
    unit = _UNIT_NAMES.get((m.group(2) or "m").lower())
    if unit is None:
        return None
    return float(m.group(1).replace(",", ".")), unit


def _problem(obj):
    if not obj.isValid():
        try:
            return obj.getStatusString()
        except Exception:  # noqa: BLE001
            return "error"
    if "Touched" in obj.State:
        return "not recomputed (recompute the document, or fix the object it depends on)"
    return None


def report(doc, prices):
    """(rows matching HEADER, cost, items without a price, errors) for the metre ware of a document.

    Carriages with a belt are grouped by item and length. A carriage with an
    error is listed in the errors instead, so its belt does not silently go
    missing from the order.
    """
    from . import linear
    groups = OrderedDict()
    errors = []
    for obj in doc.Objects:
        if not linear.is_carriage(obj) or not getattr(obj, "BeltItem", ""):
            continue
        reason = _problem(obj)
        if reason:
            errors.append(f"{obj.Label} (carriage with belt {obj.BeltItem}): {reason}")
            continue
        groups.setdefault((obj.BeltItem, round(obj.BeltLength.Value, 1)), []).append(obj)
    rows, cost, missing = [], 0.0, set()
    for (item, length), objs in sorted(groups.items()):
        parsed = parse_price((prices or {}).get(item, ""))
        if parsed is None:
            missing.add(item)
            price, unit, each = "", "", 0.0
        else:
            price, unit = parsed
            each = length / 1000 * price / UNITS[unit]
        line = len(objs) * each
        cost += line
        rows.append((len(objs), item, length, price, unit, round(line, 2), ", ".join(o.Label for o in objs)))
    return rows, cost, missing, errors
