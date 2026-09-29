# Named supplier price books and side-by-side quote comparison

| | |
|---|---|
| Status | Planned |
| Category | Manufacturing & ordering |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | industrial, purchasing-workshop, competitors |

## Problem

The Pricing object holds one supplier's prices per document, and 'Save as my defaults' keeps one set. Buyers often compare suppliers (say an item or Bosch Rexroth dealer, 80/20 or Misumi, a marketplace seller and a local cut-to-size shop), cut-to-size against stock bars, and one build against three, and each comparison means retyping prices back and forth. The report computes only the active mode, so the trade-off is never visible.

## Proposal

Keep named price books in <UserAppData>/ProfileBuilder/suppliers/*.json. Each holds what the Pricing object holds today (ProfilePrices, SheetPrices, StockLengths, cutting, delivery, tax, currency), plus:
- hardware and machining prices, once those features exist;
- supplier rules: min/max cut length, whether it cuts miters, which operations it offers.
The Pricing panel gets a Supplier selector. Choosing a book copies a snapshot into the document and records which book and version was used, so old quotes stay reproducible.

A Compare tab runs build_report (already pure data) for every book and both purchase modes. It shows a table (profiles, cutting, sheets, hardware, delivery, tax, total, bars bought, waste %, missing prices) and highlights the cheapest. BuildQuantity multiplies the pieces before stock planning, so two enclosures nest into fewer bars, with optional quantity price breaks. The comparison exports as a one-page quote summary with project name, date and revision. The report warns about pieces outside a supplier's cut range and about miters it won't cut, and lists those as 'cut yourself'.

## What exists today

Partly exists: the per-document ProfileBuilderPricing object plus one user default set (pricing.json), with 'Save as my defaults' and 'Load my defaults' in pricing_ui. That is effectively one price book. build_report computes only the active PurchaseMode, and missing prices are treated as 0 with a 'No price for' note.

## Implementation approach

Effort M confirmed. The build_report refactor is trivial, because pricing.settings_values(doc) already returns a plain dict: build_report(doc, settings=None) is a two-line change with identical results.

Revised value medium, down from high: a side-by-side 'Cut to size' vs 'Stock bars' comparison at the current prices is S effort and high value on its own. Multiple supplier books only pay off for someone who keeps prices for several suppliers, which is manual data entry that goes stale.

Implementation:
- pricing.py:
  - books_dir() at <UserAppData>/ProfileBuilder/suppliers, plus list_books(), load_book() and save_book(), all using the values() dict shape;
  - normalise(data), which fills missing keys the way settings_values' fallback does;
  - on first use, import the existing pricing.json as the book 'My defaults' without deleting it.
- New FIELDS, added to old documents by add_properties: 'PriceBook' and 'PriceBookSaved' (PropertyString, read-only), 'BuildQuantity' (PropertyInteger, default 1), and supplier rules 'MaxCutLength' and 'CutsMiters', so the rules travel with books.
- cutlist:
  - multiply qty by BuildQuantity before filling pieces_by_product, so several builds nest into shared bars; CutCost is charged per piece;
  - warn for pieces over MaxCutLength and for miters the supplier won't cut;
  - new compare(doc, books) returns rows (book, mode, profiles, cutting, sheets, delivery, tax, total, bars, waste %, missing prices).
- pricing_ui: a Supplier combo and a 'Save as book' button on the Prices page, and a fourth 'Compare' page with a QTableWidget that bolds the cheapest row.
- freecad_smoke: two books give different totals; compare returns books x 2 rows; an old document without PriceBook restores unchanged.

## Blockers and caveats

- No technical blocker.
- Prices are keyed by feature.product_key, which includes the weight class and closed faces, so every variant needs its own entry in each book.
- The Compare table must show missing-price counts, because the current behaviour prices them at 0.
- Books can use different currencies, so Compare shows each total in its book's currency and only marks the cheapest among books that share one. Tax stays per book, because some suppliers quote prices including VAT and others without sales tax.
- ProfilePrices are per metre, but suppliers in inch regions such as 80/20 quote per foot or per inch, so a book needs a price unit that is converted to per metre on entry.

## Risks

- Prices are keyed by product_key (Designation plus closed faces), and weight-class and closed-face variants each need their own entry. Supplier naming differs, so mappings drift.
- Show missing prices per book clearly instead of treating them as 0.
- build_report reads its settings from the document today. Refactor it without changing results.
- Migrate existing documents and the single-set pricing.json without losing saved values.
- Ship templates without prices, since prices go stale.

## Prior art

Vendor tools price and export only their own catalogue. FrameForge stores a single UnitPrice per size in its JSON catalog. Supplier FAQs state the rules a book needs; Motedis, for example, gives a 0.3 mm cut tolerance, asks customers to contact support above 1980 mm and charges more to ship long pieces.

## Modules

- `pricing.py`
- `pricing_ui.py`
- `cutlist.py (build_report accepting a settings dict)`
- `commands.py`
- `tests/freecad_smoke.py`
