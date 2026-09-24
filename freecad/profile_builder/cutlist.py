"""Cut list, stock plan, sheet list and cost estimate for a document."""

import csv
from collections import OrderedDict
from dataclasses import dataclass, field

from . import feature, panels, pricing, stock

PIECE_HEADER = ("Qty", "Product", "Length (mm)", "Saw length (mm)", "Miter start (°)",
                "Miter end (°)", "Mass each (kg)", "Price/m", "Cost")
STOCK_HEADER = ("Bar", "Product", "Bar length (mm)", "Pieces (mm)", "Offcut (mm)")
SHEET_HEADER = ("Qty", "Sheet", "Width (mm)", "Height (mm)", "Area each (m²)", "Price/m²", "Cost")


@dataclass
class Report:
    currency: str
    mode: str
    pieces: list = field(default_factory=list)  # rows matching PIECE_HEADER
    stock: list = field(default_factory=list)  # rows matching STOCK_HEADER
    sheets: list = field(default_factory=list)  # rows matching SHEET_HEADER
    summary: list = field(default_factory=list)  # (label, value)
    warnings: list = field(default_factory=list)

    @property
    def total(self):
        return self.summary[-1][1] if self.summary else 0.0


def collect(doc):
    """Group identical profile pieces: {key: [qty, representative object]}."""
    groups = OrderedDict()
    for obj in doc.Objects:
        if not feature.is_profile(obj) or not obj.isValid():
            continue
        key = (feature.product_key(obj), round(obj.Length.Value, 1), round(obj.OverallLength.Value, 1),
               round(obj.MiterStart.Value, 1), round(obj.MiterEnd.Value, 1))
        groups.setdefault(key, [0, obj])[0] += 1
    return OrderedDict(sorted(groups.items()))


def _money(value):
    return round(value, 2)


def build_report(doc):
    s = pricing.settings_values(doc)
    report = Report(s["Currency"], s["PurchaseMode"])
    prices, sheet_prices, bar_lengths = s["ProfilePrices"], s["SheetPrices"], s["StockLengths"]
    missing = set()

    groups = collect(doc)
    pieces_by_product = OrderedDict()
    mass_per_metre = {}
    material = cutting = mass = 0.0
    for (product, length, saw, m1, m2), (qty, obj) in groups.items():
        price = pricing.lookup(prices, product)
        if price is None:
            missing.add(product)
        cost = qty * saw / 1000 * (price or 0.0)
        report.pieces.append((qty, product, length, saw, m1, m2, round(obj.Mass, 3),
                              "" if price is None else price, _money(cost)))
        pieces_by_product.setdefault(product, []).extend([(saw, obj.Label)] * qty)
        mass_per_metre[product] = obj.MassPerMeter
        if report.mode == "Cut to size":
            material += cost
            cutting += qty * s["CutCost"]
            mass += qty * obj.Mass

    if report.mode == "Stock bars":
        bar_no = 0
        for product, pieces in pieces_by_product.items():
            bar_length = pricing.lookup(bar_lengths, product) or s["StockLength"]
            result = stock.plan(pieces, bar_length, s["Kerf"], s["EndTrim"])
            price = pricing.lookup(prices, product) or 0.0
            for bar in result.bars:
                bar_no += 1
                cuts = " + ".join(f"{length:g}" for length, _label in bar.pieces)
                report.stock.append((bar_no, product, bar_length, cuts, round(bar.offcut, 1)))
            material += result.bought_length / 1000 * price
            mass += result.bought_length / 1000 * mass_per_metre[product]
            for length, label in result.oversize:
                report.warnings.append(f"{label} ({length:g} mm) is longer than a {bar_length:g} mm bar "
                                       f"of {product}; order it cut to size")
                material += length / 1000 * price
                mass += length / 1000 * mass_per_metre[product]
            if result.bars:
                report.warnings.append(f"{product}: {len(result.bars)} bar(s), "
                                       f"{result.waste * 100:.0f}% offcut and saw loss")

    sheets = OrderedDict()
    for obj in doc.Objects:
        if panels.is_panel(obj) and obj.isValid():
            key = (panels.sheet_key(obj), round(obj.Width.Value, 1), round(obj.Height.Value, 1))
            sheets.setdefault(key, [0, obj])[0] += 1
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
        ("Total", _money(subtotal + tax)),
    ]
    for key in sorted(missing):
        report.warnings.append(f"No price for {key}")
    return report


def _blocks(report):
    """The report as (title, header, rows) blocks, shared by spreadsheet and CSV."""
    pieces = sum(r[0] for r in report.pieces)
    saw = sum(r[0] * r[3] for r in report.pieces)
    blocks = [(f"Cut list ({pieces} pieces, {saw / 1000:.2f} m)", PIECE_HEADER, report.pieces)]
    if report.stock:
        blocks.append((f"Stock plan ({len(report.stock)} bars)", STOCK_HEADER, report.stock))
    if report.sheets:
        blocks.append(("Sheets", SHEET_HEADER, report.sheets))
    blocks.append((f"Costs ({report.mode}, {report.currency})", ("Item", "Amount"),
                   [list(r) for r in report.summary]))
    if report.warnings:
        blocks.append(("Notes", ("Note",), [(w,) for w in report.warnings]))
    return blocks


def write_csv(report, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for title, header, rows in _blocks(report):
            writer.writerow((title,))
            writer.writerow(header)
            writer.writerows(rows)
            writer.writerow(())


def write_spreadsheet(doc, report, name="CutList"):
    sheet = doc.getObject(name)
    if sheet is None or sheet.TypeId != "Spreadsheet::Sheet":
        sheet = doc.addObject("Spreadsheet::Sheet", name)
        sheet.Label = "Cut list"
    sheet.clearAll()
    cols = "ABCDEFGHI"
    row = 1
    for title, header, rows in _blocks(report):
        sheet.set(f"A{row}", f"'{title}")
        sheet.setStyle(f"A{row}", "bold")
        row += 1
        for c, text in zip(cols, header):
            sheet.set(f"{c}{row}", f"'{text}")
        sheet.setStyle(f"A{row}:{cols[len(header) - 1]}{row}", "bold")
        row += 1
        for values in rows:
            for c, value in zip(cols, values):
                # A leading quote keeps text such as "2040 (20-6)" from being parsed.
                sheet.set(f"{c}{row}", str(value) if isinstance(value, (int, float)) else f"'{value}")
            row += 1
        row += 1
    sheet.setColumnWidth("A", 150)
    sheet.setColumnWidth("B", 190)
    sheet.setColumnWidth("D", 230)
    doc.recompute()
    return sheet
