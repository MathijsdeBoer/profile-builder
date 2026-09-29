# International use: units, imperial profiles and translations

| | |
|---|---|
| Status | Partly done |
| Category | FreeCAD integration & UX |
| Effort | L |
| Value | high |
| Proposed from | review of regional assumptions, 2026-09-29 |

## Status

Done:
- The currency defaults to the system region's symbol.
- Amounts in the pricing estimate and messages use the region's money format.
- The CSV export describes its two variants neutrally (decimal point with commas, or decimal comma with semicolons) and offers the system's format first.
- Tax is described as VAT, GST or sales tax.

Not done: everything below.

## Problem

The workbench assumes a metric user in several places.
- The task panels use spin boxes with a hard-coded "mm" suffix, so they ignore FreeCAD's unit schema (Edit → Preferences → General → Units). A user on "US customary" or "Imperial decimal" sees inches in the property editor but millimetres in the dialogs.
- Prices are per metre and per m², stock lengths default to 6000 mm, and reports show millimetres.
- North American suppliers sell by the foot or the inch (for example 145" or 242" bars) and quote kerf in inches.
- The catalog has only metric series. Imperial fractional profiles, such as 80/20's 10 series (1 inch) and 15 series (1.5 inch), are missing, although they are the standard in North America.
- The interface is English only.

## Proposal

1. **Units in the dialogs.** Replace the plain spin boxes in `taskpanel.py`, `simple_panel.py` and `pricing_ui.py` with FreeCAD's `Gui::QuantitySpinBox`, created with `FreeCADGui.UiLoader().createWidget("Gui::QuantitySpinBox")`. It follows the user's unit schema and accepts input such as `1 1/2 in` or `=Spreadsheet.Width`. The properties are already quantities, so the document itself does not change.
2. **Report units.** Add a Units setting to the pricing object: "Metric (mm, per m, per m²)" or "Imperial (in, per ft, per ft²)", defaulting from the unit schema. Show lengths in the cut list, stock plan and CSV in that unit, with a sensible rounding (1 mm, or 1/16 in / 0.01 in). Store prices with their unit, so that switching the display does not change the meaning of a stored price.
3. **Imperial catalog.** Add fractional series with a clear `system` (for example "80/20 fractional"). Their dimensions in inches are converted exactly to millimetres (1 in = 25.4 mm) for the geometry, and their designations follow the vendor's (1010, 1020, 1515, ...), not the metric grid naming. The designation code currently builds names from the cell size in millimetres (`profiles.designation`), so it needs a per-series naming rule.
4. **Translations.** Wrap user-visible strings in `QT_TRANSLATE_NOOP` / `FreeCAD.Qt.translate`, ship `.ts`/`.qm` files, and load them in `init_gui.py`. See [Addon Manager readiness](addon-manager-readiness.md), which lists the same scaffolding.

## Implementation approach

- **Dialogs:** a small helper `quantity_spin(value, unit="mm")` in a shared GUI module, used wherever `_spin` is used today. Read values with `widget.property("rawValue")` (internal millimetres), and write with `setProperty("rawValue", v)`. The GUI smoke scripts must switch the unit schema to check that inch input gives the same model.
- **Reports:** `cutlist.build_report` keeps computing in millimetres; formatting happens in `_blocks()`, `write_csv` and `write_spreadsheet`, from the chosen unit. The stock planner stays in millimetres. `pricing.lookup` converts a stored price per foot to per metre (1 ft = 0.3048 m) where costs are computed.
- **Catalog:** `profiles.Series` gets optional `unit` and `name_rule` fields; `designation()` uses them. Validation and the weight-class rules are unit-free already.
- **Tests:** pytest for the unit conversion and naming; the FreeCAD smoke test builds each imperial series; a GUI check with the "Imperial decimal" schema.

## Blockers and caveats

- Imperial profile dimensions have to come from vendor drawings. Guessed values would be worse for these than for the metric series, because imperial users often buy connectors from the same vendor.
- Saved documents keep their prices keyed per metre. The Units setting must default to metric for documents that already have prices, so their totals do not change.
- Translations need translators; FreeCAD's own translations are on Crowdin, and an addon can ship its own `.qm` files.

## Modules

- `taskpanel.py`, `simple_panel.py`, `pricing_ui.py` (quantity spin boxes)
- `pricing.py`, `cutlist.py` (report units, price units)
- `profiles.py` (imperial series, naming)
- `init_gui.py` (translations)
- `tests/`
