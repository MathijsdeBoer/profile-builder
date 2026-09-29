# Supplier order export with article numbers, part-number templates and cut-length rules

| | |
|---|---|
| Status | Partly done |
| Category | Manufacturing & ordering |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | industrial, purchasing-workshop, competitors |

## Status

Done: CSV with a byte order mark, and a variant with semicolons and decimal commas for Excel in locales that use them (much of continental Europe and South America, among others). Not done: article numbers, part-number templates and cut-length rules.

## Problem

The cut list is a report, not an order. To order, each product and length is retyped into the supplier's configurator, basket or order e-mail, which invites typos in lengths. Suppliers also have rules the report doesn't check: a length resolution (whole millimetres, or a fraction of an inch at inch-based suppliers such as 80/20), a minimum cut length, a maximum length per piece, often set by shipping (Motedis, for example, asks customers to contact support above about 1980 mm), and length tolerances.

## Proposal

Add an ArticleNumbers map next to ProfilePrices and StockLengths (per price book, if those exist), keyed by product key. An entry holds either a fixed number or a template such as 'HFS5-2020-{L}'. {L} is the saw length, rounded by a LengthResolution setting (1 mm, up or to nearest). Inch steps such as 1/16 in switch {L} and the length column to inches for inch-based suppliers. Some suppliers take a fixed article number plus a separate length; others, such as Misumi, put the length in the part number, which the template covers. Machining can add suffixes, e.g. '-TPW' when both ends are tapped. The cut list gets an 'Article no.' column. 'Export order...' writes:
- a generic order CSV (line, article no., description, length, qty, unit, unit price, line total), with a column mapping set per supplier;
- a 'part number<TAB>qty' quick-order text, also copied to the clipboard, for quick-order boxes such as Misumi's.
Sheets and hardware lines are included. Warnings cover pieces below MinCutLength, pieces above MaxLength, and rounding that changes a joint-driven length by more than the tolerance.

## What exists today

Only a generic report CSV exists (cutlist.write_csv). It writes UTF-8 without a BOM and uses a comma delimiter, so Excel in a decimal-comma locale (';' list separator, a legacy ANSI code page) mangles °, ², currency symbols such as € and the decimals. There are no article numbers, rounding rules, or min/max cut-length checks. In Cut to size mode, pieces longer than a supplier's maximum are not warned about at all. The oversize check only runs in Stock bars mode. Price books do not exist.

## Implementation approach

pricing.py:
- Add FIELDS entries 'ArticleNumbers' (PropertyMap, product_key to number or template), 'LengthResolution' (enumeration 0.1 / 1 mm nearest / 1 mm up, plus inch steps), 'MinCutLength', 'MaxCutLength' and 'CutTolerance'.
- Settings.add_properties already adds missing FIELDS on restore, and values() and save_defaults pick them up automatically.

pricing_ui:
- Add an 'Article no.' column to profile_table and sheet_table (_set_rows/_read_column with a 4th mapping).

cutlist:
- A pure helper `article(template, length)` uses str.format with {L}, {L:04d} and so on. Unit-test it in tests/ without FreeCAD.
- build_report adds warnings for pieces under MinCutLength or over MaxCutLength (in both modes), and for pieces where rounding moves a joint-driven length by more than CutTolerance. Rounding applies only to report rows, never to obj.Length.
- write_order_csv(report, path, delimiter) writes line, article, description, length, qty, unit price and total with encoding='utf-8-sig', and uses ';' when the locale's decimal separator is ','.
- `quick_order_text(report)` returns 'part<TAB>qty' lines. QtGui.QGuiApplication.clipboard().setText puts them on the clipboard.

Add a new ExportOrder command in commands.py and register it in init_gui.

## Blockers and caveats

Supplier formats are private and change. Many suppliers, from web configurators such as Motedis to marketplace sellers and local cut-to-size shops, offer no {L} template or bulk upload to target; for them the benefit is the generic CSV (to paste or e-mail) and the cut-length rule checks. Misumi's configurable part numbers and quick order fit the template idea. The catalog has no inch series (such as 80/20's 1010 or 1515) yet, so inch lengths mainly serve metric profiles bought from inch-based suppliers and custom-dimension profiles. Don't ship real vendor numbers. Article numbers are keyed by product_key, like prices, so a change to the designation format orphans them. The min/max length and rounding warnings are S and worth doing even without the export.

## Risks

- Supplier formats are not public and they change, so templates must be user-supplied. Many suppliers have no bulk upload, so the generic CSV is the fallback.
- Don't ship real vendor article numbers: they could be wrong, and they belong to the vendor.
- Article numbers are keyed by product key, so changing the designation format orphans them, just like prices.
- Rounding joint-driven lengths must never feed back into the model.

## Prior art

Misumi configurable part numbers and quick order / CSV import (part number plus quantity). Vendor configurators export order lists with their own article numbers.

## Modules

- `pricing.py`
- `pricing_ui.py`
- `cutlist.py`
- `commands.py`
- `init_gui.py`
- `tests/freecad_smoke.py`
