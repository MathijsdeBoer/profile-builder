# Cheapest-buy stock planner: mixed bar lengths, packs, per-product mode, offcut inventory

| | |
|---|---|
| Status | Planned |
| Category | Manufacturing & ordering |
| Effort | L (first estimate M) |
| Value | high |
| Proposed from | printer-builder, purchasing-workshop, competitors |

## Problem

stock.plan() packs every product into one bar length and minimises bar count, not cost. Suppliers offer several ways to buy the same profile:
- bars in several lengths (for example 1, 2, 3 and 6 m, or 6 and 12 ft sticks from inch suppliers) at different prices per length, with extra shipping for long bars;
- pieces cut to size, up to a maximum length that varies by supplier;
- pre-cut standard lengths at a special price;
- packs of identical pre-cut pieces, such as Motedis Maker Packs of 12 pieces at 500/1000/1500/1980 mm.
PurchaseMode is global, so a common real order (4040 cut to size, 2020 as bars) can't be priced. And the planner ignores the offcuts from earlier builds that are already in the workshop.

## Proposal

StockLengths per product becomes a list of options: length, price per bar or per metre, pack size, cut fee, maximum length, oversize surcharge and available count. It still parses the old single number.

The planner stays pure Python and pytest-tested. Per product, it:
1. uses inventory offcuts first, at zero cost;
2. runs FFD/BFD for each bar length;
3. runs a downsizing pass that moves each bar's pieces to the cheapest shorter option that still holds them;
4. rounds up to whole packs, with a cut-to-size fallback per piece (and an optional capped exhaustive search for 30 pieces or fewer);
5. keeps the cheapest total.
One global pass then handles delivery thresholds (free above X).

PurchaseMode gets a per-product override (Stock bars / Cut to size / Default) and a new 'Cheapest' mode, which adds an explanation line such as '1 x pack 12x500 mm + 4 pieces cut to size: 38.20; 6 m bars would cost 51.00'. A delivery surcharge tier applies to the longest item.

A user-level offcut inventory lives in user app data (inventory.json), because offcuts sit in the workshop, not in one document. The report says which offcuts it used. After the user confirms, a 'Consume inventory' command removes the used offcuts and adds new ones above MinUsableOffcut.

## What exists today

Confirmed:
- stock.plan() packs into one bar length per product (pricing.lookup(StockLengths) or StockLength) and minimises bar count, not cost.
- PurchaseMode is global.
- ProfilePrices holds one price per metre for both modes, so bars can't be cheaper per metre than cut to size.
- Settings.onDocumentRestored only calls add_properties. A new enumeration value such as 'Cheapest' would never reach old documents unless the list is refreshed, the way Joint does for ThroughRule.

## Implementation approach

The core is M: several bar options per product, a per-product mode, and a 'Cheapest' comparison. Packs, surcharges and the offcut inventory make it L. Ship the core first.
1. stock.py (pure):
   - StockOption(length, price_per_bar or per_m, pack=1, max_count=None).
   - plan_mixed(pieces, options, kerf, end_trim): FFD/BFD on the longest option, then move each bar's pieces to the cheapest option that still holds them, using the same kerf and end-trim rules as _pack.
   - cut_to_size_cost(pieces, per_m, cut_fee, max_length).
   - cheapest() returns the plan plus an explanation string.
   - Leave plan() unchanged so test_stock.py stays green. Add pytest cases with small, known optimal answers.
2. pricing.py:
   - Parse StockLengths values backward-compatibly: '6000' (old) or '6000@12.50; 3000@7.20; 2000' (length@price per bar; no price = per-metre price × length). Separate options with ';', because parse_number accepts a decimal comma ('12,50').
   - Inch suppliers sell sticks in inches and quote cut-to-size prices per foot or per inch, so accept a unit on lengths ('145 in') and on the per-length price ('/ft'), and convert both to mm and per metre on input.
   - Add an App::PropertyMap PurchaseModes (product -> Default / Cut to size / Stock bars / Cheapest), and add 'Cheapest' to PURCHASE_MODES with an enumeration refresh in onDocumentRestored.
   - The defaults JSON keeps working, because values() and apply_values iterate over FIELDS.
3. cutlist.build_report: loop per product with its effective mode, show the option length in the stock rows, and add a note such as '4040: 3 × 2 m bars 38.20; 6 m bars 51.00; cut to size 44.10'. Delivery (free above X) runs once globally after the per-product choice.
4. pricing_ui: the Bar length column accepts the list syntax; add a Mode column.
5. Defer inventory.json and 'Consume inventory' to a separate item.

## Blockers and caveats

- Delivery thresholds couple the products, so per-product optima are not globally optimal; accept a heuristic.
- Supplier pack and oversize rules vary, so keep them as data.
- The offcut inventory is machine-level state outside undo and transactions: it makes a document's estimate depend on the machine and needs a backup and confirmation. That is why it should be split off.

## Risks

- Heterogeneous cutting stock is NP-hard. Keep the heuristic predictable, cap the search, and test against small exact cases.
- Delivery rules couple the products, so per-product optima are not globally optimal.
- Existing modes must give identical results, so the current tests stay green.
- App::PropertyMap values are strings, so old '6000' values need backward-compatible parsing. New pricing fields go through add_properties.
- A machine-level inventory makes a document's estimate depend on the machine. Consuming it is outside undo and transactions, so it needs explicit confirmation and a backup.

## Prior art

CutList Optimizer and OptiCut support several stock lengths and remnant inventories. Supplier pricing schemes to model: Motedis Maker Packs and pre-cut standard-length prices, 80/20 cut-to-size pricing by the inch plus a fee per cut, Misumi volume price breaks. FrameForge's best_fit.py is best-fit decreasing on a single stock length with kerf, with no cost model.

## Modules

- `stock.py`
- `tests/test_stock.py`
- `pricing.py (FIELDS, parsing, defaults file)`
- `pricing_ui.py`
- `cutlist.py (per-product mode, stock rows)`
- `commands.py`
