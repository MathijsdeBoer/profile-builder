# Order snapshots and change orders ('what changed since I ordered?')

| | |
|---|---|
| Status | Planned |
| Category | Manufacturing & ordering |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | purchasing-workshop |

## Problem

A common flow in both hobby and professional builds: order the aluminium, wait days or weeks for delivery, and meanwhile move a rail or widen the enclosure by 20 mm. Today the only answer is a fresh cut list compared with the old one by eye. It doesn't say what still needs to be bought, or which pieces already ordered can simply be cut shorter.

## Proposal

A 'Freeze order' command stores the current report as JSON in a document object ('Order Rev A, 2026-09-28'): pieces with marks, miters and operations, sheets, hardware, totals, supplier, date and a revision letter. Several revisions can be kept. 'Compare with order' produces a change-order block in the cut list: added and removed pieces, lengthened pieces that must be re-ordered, and shortened pieces with a proposed re-cut from an ordered piece. The re-cut matching is a small 1D assignment: the new piece must be no longer than the ordered one, the same product, and the same or square miter geometry. The block adds the cost delta, and the revision and date appear in the spreadsheet and CSV headers.

## What exists today

One risk in the proposal is wrong. Report rows are plain ints, floats and strings (qty, product, length, saw, m1, m2, mass, price, cost), not preformatted text, so dataclasses.asdict(report) is already JSON-ready. There is also no piece-marks feature, but diffing by the collect() group key (product, length, saw length, miters) works without marks.

## Implementation approach

1. New orders.py (pure, pytest):
   - snapshot(report, revision, date, supplier) -> dict.
   - diff(old, new), keyed by (product, length, saw length, canonical miters), gives added, removed and changed quantities.
   - recut(): a greedy assignment. It pairs a new or shortened piece with an ordered piece of the same product and the same canonical miter signature (or a square end that can take the new miter), where new length ≤ ordered length − kerf, preferring the smallest surplus.
   - The cost delta comes from ProfilePrices. The snapshot stores Currency and TaxPercent with its totals, so a delta is never computed across currencies or between prices with and without tax.
2. Document object: an 'Order' App::FeaturePython built like pricing.Settings, with Revision, Date, Supplier and a hidden App::PropertyString Snapshot holding the JSON, kept in an 'Orders' group.
3. commands.py: 'Freeze order' and 'Compare with order' (a QInputDialog picks the revision; monkeypatch it in GUI tests). Register both in init_gui.
4. cutlist.Report gets an optional 'changes' list; _blocks adds a 'Change order vs Rev A (date)' block and puts the revision in the titles.
5. Smoke test: freeze the cube, stretch its lines by 1.5 (as the existing test does), compare, and expect 4 × 380 removed and 4 × 570 added with recut suggestions; save and reload keep the snapshot.

## Blockers and caveats

Do miter-plane-key first. Today a sketch line redrawn in the other direction flips the miter signs, and the diff would report it as a changed piece.

## Risks

- Report rows are tuples of preformatted strings, so the report first needs a structured, serialisable form (shared with the workshop pack).
- Diffs are only meaningful with stable piece marks.
- A mitered piece can be re-cut shorter only if the angle and the plane match.

## Prior art

Engineering change orders in PDM/ERP. BOM-diff tools in electronics CAD.

## Modules

- `cutlist.py`
- new freecad/profile_builder/orders.py (pure-Python diff and matching)
- `commands.py`
- `init_gui.py`
- `tests (pytest for the diff, smoke test for freeze/reload)`
