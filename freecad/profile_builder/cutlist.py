"""Cut list, stock plan, sheet list and cost estimate for a document."""

import csv
import re
from collections import OrderedDict
from dataclasses import dataclass, field

from . import brackets, feature, joints, panels, pricing, stock
from .pieces import canonical_cuts, letters, upright

PIECE_HEADER = ("Mark", "Qty", "Product", "Length (mm)", "Saw length (mm)", "Miter start (°)",
                "Miter end (°)", "Miter across (mm)", "Mass each (kg)", "Price/m", "Cost", "Profiles")
STOCK_HEADER = ("Bar", "Product", "Bar length (mm)", "Pieces (mark: saw length)", "Offcut (mm)")
SHEET_HEADER = ("Qty", "Sheet", "Width (mm)", "Height (mm)", "Area each (m²)", "Price/m²", "Cost")
HARDWARE_HEADER = ("Qty", "Item", "Article number", "Placed by")
MARK_TEXT = re.compile(r"Mark [A-Z]+\d+")  # the tree Description that apply_marks writes


@dataclass
class Report:
    currency: str
    mode: str
    pieces: list = field(default_factory=list)  # rows matching PIECE_HEADER
    stock: list = field(default_factory=list)  # rows matching STOCK_HEADER
    sheets: list = field(default_factory=list)  # rows matching SHEET_HEADER
    hardware: list = field(default_factory=list)  # rows matching HARDWARE_HEADER
    summary: list = field(default_factory=list)  # (label, value)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)  # objects left out because they have an error
    marks: dict = field(default_factory=dict)  # profile Name -> piece mark

    @property
    def total(self):
        return self.summary[-1][1] if self.summary else 0.0

    @property
    def piece_count(self):
        return sum(r[PIECE_HEADER.index("Qty")] for r in self.pieces)


def _piece_cuts(obj):
    """Canonical end cuts, described on the upright section (see pieces.upright)."""
    fallback = obj.MiterAcross
    axes = (getattr(obj, "MiterStartAxis", "") or fallback, getattr(obj, "MiterEndAxis", "") or fallback)
    cuts = ((obj.MiterStart.Value, axes[0]), (obj.MiterEnd.Value, axes[1]))
    closed, cuts = upright(feature.closed_faces(obj), cuts, obj.Columns, obj.Rows)
    return canonical_cuts(closed, cuts, obj.Columns == obj.Rows)


def collect(doc):
    """Group identical profile pieces that are up to date: {key: [objects]}, sorted by key.

    The key is (product, length, saw length, canonical cuts). Profiles with a
    problem (see feature.problem) are left out; broken_objects lists them.
    """
    groups = OrderedDict()
    for obj in doc.Objects:
        if not feature.is_profile(obj) or feature.problem(obj):
            continue
        key = (feature.product_key(obj), round(obj.Length.Value, 1), round(obj.OverallLength.Value, 1),
               _piece_cuts(obj))
        groups.setdefault(key, []).append(obj)
    return OrderedDict(sorted(groups.items()))


def _panel_problem(obj):
    if not obj.isValid():
        return _status(obj)
    if "Touched" in obj.State:
        return "not recomputed (recompute the document, or fix the profiles around it)"
    return None


def _status(obj):
    try:
        return obj.getStatusString()
    except Exception:  # noqa: BLE001
        return "error"


def broken_objects(doc):
    """Profiles, joints and panels that are not in the lists, with the reason."""
    found = []
    for obj in doc.Objects:
        if feature.is_profile(obj):
            reason, kind = feature.problem(obj), "profile"
        elif panels.is_panel(obj):
            reason, kind = _panel_problem(obj), "panel"
        elif joints.is_joint(obj):
            reason, kind = (None if obj.isValid() else _status(obj)), "joint"
        elif brackets.is_brackets(obj):
            reason, kind = brackets.problem(obj), "brackets"
        else:
            continue
        if reason:
            found.append(f"{obj.Label} ({kind}): {reason}")
    return found


def _price(mapping, obj, key):
    """Price for a product key, falling back to the key older versions used."""
    value = pricing.lookup(mapping, key)
    if value is None:
        value = pricing.lookup(mapping, feature.legacy_product_key(obj))
    return value


def _across(obj, cuts):
    """Which face width each miter slopes across, e.g. '40' for a 2040 across Y.

    ``cuts`` are described on the upright section, where X is the narrow side.
    """
    narrow, wide = sorted((obj.Columns, obj.Rows))
    widths = {"X": narrow * obj.CellSize.Value, "Y": wide * obj.CellSize.Value}
    axes = list(dict.fromkeys(ax for a, ax in cuts if a))
    return " / ".join(f"{widths[ax]:g}" for ax in axes)


def _money(value):
    return round(value, 2)


def recompute_if_needed(doc):
    """Recompute first when anything is out of date, so the lists never show stale values.

    That covers touched objects and profiles from older documents whose newer
    outputs (section properties, miter axes) have not been computed yet.
    """
    for obj in doc.Objects:
        if feature.is_profile(obj) and feature.needs_refresh(obj):
            obj.touch()
    if any("Touched" in o.State for o in doc.Objects):
        doc.recompute()


def build_report(doc):
    s = pricing.settings_values(doc)
    report = Report(s["Currency"], s["PurchaseMode"])
    prices, sheet_prices, bar_lengths = s["ProfilePrices"], s["SheetPrices"], s["StockLengths"]
    missing = set()
    report.errors = broken_objects(doc)

    groups = collect(doc)
    products = sorted({key[0] for key in groups})
    letter = {product: letters(i) for i, product in enumerate(products)}
    numbers = {}
    # Within a product, the longest piece is number 1.
    for key in sorted(groups, key=lambda k: (k[0], -k[2], k)):
        numbers[key] = sum(1 for other in numbers if other[0] == key[0]) + 1

    pieces_by_product = OrderedDict()
    mass_per_metre = {}
    sample = {}  # one profile per product, for the legacy price key
    material = cutting = mass = 0.0
    for key, objs in sorted(groups.items(), key=lambda kv: (kv[0][0], numbers[kv[0]])):
        product, length, saw, cuts = key
        obj, qty = objs[0], len(objs)
        mark = f"{letter[product]}{numbers[key]}"
        for o in objs:
            report.marks[o.Name] = mark
        price = _price(prices, obj, product)
        if price is None:
            missing.add(product)
        cost = qty * saw / 1000 * (price or 0.0)
        report.pieces.append((mark, qty, product, length, saw, cuts[0][0], cuts[1][0], _across(obj, cuts),
                              round(obj.Mass, 3), "" if price is None else price, _money(cost),
                              ", ".join(o.Label for o in objs)))
        pieces_by_product.setdefault(product, []).extend((saw, mark) for _o in objs)
        mass_per_metre[product] = obj.MassPerMeter
        sample[product] = obj
        if report.mode == "Cut to size":
            material += cost
            cutting += qty * s["CutCost"]
            mass += qty * obj.Mass

    if report.mode == "Stock bars":
        bar_no = 0
        for product, pieces in pieces_by_product.items():
            bar_length = _price(bar_lengths, sample[product], product) or s["StockLength"]
            result = stock.plan(pieces, bar_length, s["Kerf"], s["EndTrim"])
            price = _price(prices, sample[product], product) or 0.0
            for bar in result.bars:
                bar_no += 1
                cuts = " + ".join(f"{mark}: {length:g}" for length, mark in bar.pieces)
                report.stock.append((bar_no, product, bar_length, cuts, round(bar.offcut, 1)))
            material += result.bought_length / 1000 * price
            mass += result.bought_length / 1000 * mass_per_metre[product]
            for length, mark in result.oversize:
                report.warnings.append(f"{mark} ({length:g} mm) is longer than a {bar_length:g} mm bar "
                                       f"of {product}; order it cut to size")
                material += length / 1000 * price
                mass += length / 1000 * mass_per_metre[product]
            if result.bars:
                report.warnings.append(f"{product}: {len(result.bars)} bar(s), "
                                       f"{result.waste * 100:.0f}% offcut and saw loss")

    sheets = OrderedDict()
    for obj in doc.Objects:
        if panels.is_panel(obj) and not _panel_problem(obj):
            key = (panels.sheet_key(obj), round(obj.Width.Value, 1), round(obj.Height.Value, 1))
            sheets.setdefault(key, [0, obj])[0] += 1
            _need, fit = panels.thermal_fit(obj)
            if fit:
                report.warnings.append(fit)
    sheet_cost = 0.0
    for (key, width, height), (qty, obj) in sorted(sheets.items()):
        price = pricing.lookup(sheet_prices, key)
        if price is None:
            missing.add(key)
        # Priced on the bounding rectangle: that is what gets cut from a sheet.
        area = width * height / 1e6
        cost = qty * area * (price or 0.0)
        sheet_cost += cost
        mass += qty * obj.Mass
        report.sheets.append((qty, key, width, height, round(area, 4), "" if price is None else price,
                              _money(cost)))

    # Placed hardware is counted, not priced yet.
    report.hardware = brackets.hardware(doc)
    report.warnings.extend(brackets.notes(doc))

    goods = material + cutting + sheet_cost
    free = s["FreeDeliveryAbove"] > 0 and goods >= s["FreeDeliveryAbove"]
    delivery = 0.0 if free or goods == 0 else s["DeliveryFlat"] + s["DeliveryPerKg"] * mass
    subtotal = goods + delivery
    tax = subtotal * s["TaxPercent"] / 100
    report.summary = [
        ("Profiles", _money(material)),
        ("Cutting", _money(cutting)),
        ("Sheets", _money(sheet_cost)),
        (f"Delivery ({mass:.1f} kg)" + (", free" if free else ""), _money(delivery)),
        (f"Tax {s['TaxPercent']:g}%", _money(tax)),
        ("Total, incomplete: see Attention" if report.errors else "Total", _money(subtotal + tax)),
    ]
    for key in sorted(missing):
        report.warnings.append(f"No price for {key}")
    return report


def _blocks(report):
    """The report as (title, header, rows) blocks, shared by spreadsheet and CSV."""
    saw = sum(r[PIECE_HEADER.index("Qty")] * r[PIECE_HEADER.index("Saw length (mm)")] for r in report.pieces)
    blocks = []
    if report.errors:
        blocks.append((f"Attention: {len(report.errors)} object(s) have errors and are NOT in these lists",
                       ("Problem",), [(e,) for e in report.errors]))
    blocks.append((f"Cut list ({report.piece_count} pieces, {saw / 1000:.2f} m)", PIECE_HEADER, report.pieces))
    if report.stock:
        blocks.append((f"Stock plan ({len(report.stock)} bars)", STOCK_HEADER, report.stock))
    if report.sheets:
        blocks.append(("Sheets", SHEET_HEADER, report.sheets))
    if report.hardware:
        blocks.append(("Hardware (counted, not priced)", HARDWARE_HEADER, report.hardware))
    blocks.append((f"Costs ({report.mode}, {report.currency})", ("Item", "Amount"),
                   [list(r) for r in report.summary]))
    if report.warnings:
        blocks.append(("Notes", ("Note",), [(w,) for w in report.warnings]))
    return blocks


def write_csv(report, path, delimiter=",", decimal="."):
    """Write the report as CSV.

    For spreadsheet programs in regions that use a decimal comma, pass
    ``delimiter=";"`` and ``decimal=","``. The file starts with a UTF-8 byte
    order mark, which Excel needs to show characters such as °, ² and currency
    symbols correctly.
    """
    def cell(value):
        if isinstance(value, float) and decimal != ".":
            # 12 significant digits: "g" alone keeps only 6 and turns 10234.56 into 10234.6.
            return format(value, ".12g").replace(".", decimal)
        return value

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=delimiter)
        for title, header, rows in _blocks(report):
            writer.writerow((title,))
            writer.writerow(header)
            writer.writerows([cell(v) for v in row] for row in rows)
            writer.writerow(())


def _column(index):
    return letters(index)


def write_spreadsheet(doc, report, name="CutList"):
    sheet = doc.getObject(name)
    if sheet is None or sheet.TypeId != "Spreadsheet::Sheet":
        sheet = doc.addObject("Spreadsheet::Sheet", name)
        sheet.Label = "Cut list"
    sheet.clearAll()
    row = 1
    for title, header, rows in _blocks(report):
        sheet.set(f"A{row}", f"'{title}")
        sheet.setStyle(f"A{row}", "bold")
        row += 1
        for c, text in enumerate(header):
            sheet.set(f"{_column(c)}{row}", f"'{text}")
        sheet.setStyle(f"A{row}:{_column(len(header) - 1)}{row}", "bold")
        row += 1
        for values in rows:
            for c, value in enumerate(values):
                # A leading quote keeps text such as "2040 (20-6)" from being parsed.
                text = str(value) if isinstance(value, (int, float)) else f"'{value}"
                sheet.set(f"{_column(c)}{row}", text)
            row += 1
        row += 1
    for col, width in (("A", 110), ("C", 190), ("D", 230), ("L", 260)):
        sheet.setColumnWidth(col, width)
    doc.recompute()
    return sheet


def apply_marks(doc, report):
    """Store each piece's mark on its profile (PieceMark, and the tree's Description).

    PieceMark is an output property, so this does not trigger a recompute. The
    Description (Label2) is only written when it is empty or holds a mark
    written earlier ("Mark A1").
    """
    for obj in doc.Objects:
        if not feature.is_profile(obj):
            continue
        mark = report.marks.get(obj.Name, "")
        if "PieceMark" in obj.PropertiesList and obj.PieceMark != mark:
            obj.PieceMark = mark
        # Only replace a Description this function wrote, never the user's own text.
        if obj.Label2 == "" or MARK_TEXT.fullmatch(obj.Label2):
            text = f"Mark {mark}" if mark else ""
            if obj.Label2 != text:
                obj.Label2 = text
