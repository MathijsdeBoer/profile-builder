# Hardware BOM from joints and panels, with pack sizes and T-nut preload warnings

| | |
|---|---|
| Status | Planned |
| Category | Manufacturing & ordering |
| Effort | L (first estimate L) |
| Value | high |
| Proposed from | printer-builder, purchasing-workshop, competitors |

## Problem

On a small frame, brackets, T-nuts and screws can cost a third or more of the order. Nobody counts them until ordering, and a second order for 20 forgotten nuts costs a full delivery charge. A common assembly failure: after the frame is bolted together, the slot needed for a power supply, a linear rail, a cable duct or a guard bracket turns out to be closed at both ends, and slide-in nuts can no longer go in. Nothing in the workbench counts or prices hardware, so the estimate is low by that amount.

## Proposal

Each joint connection (from the connection-method feature) and each panel mount gets a kit: a list of (item, qty per joint / per butting member / per cell / per open-face pair), for example 'Inner corner bracket 20 B-type x2, M5 slide-in T-nut x4, M5x10 ISO 7380 x4'. Item names are free text, so kits for inch systems such as 80/20's 10 series (1/4-20 screws and nuts) fit the same scheme once the catalog has inch series. Kits live in a user-editable JSON next to pricing.json, plus a per-document copy as for prices. The rules are pure Python in hardware.py, so pytest can cover them. On-face panels add screws and nuts from their hole spacing, and end taps add their screws.

The report gets a Hardware block in the cost summary: totals, price per item, and rounding up to the vendor's pack sizes, e.g. 10/50/100 ('buy 2 packs of 50 T-nuts, 12 spare').

A slot-occupancy model walks each open slot of each profile. Butting joints and bracket nuts block the slot ends, and in-slot panels fill the whole slot. It reports:
- closed segments: 'post B3, Left slot between J2 and J6 is closed: preload spare nuts or use drop-in nuts';
- conflicts: 'bracket at J4 needs the slot panel P1 sits in';
- a per-piece preload checklist.

## What exists today

No hardware handling exists. Joint has only Type/ThroughRule/Through/ExtendThrough/Gap, and the 'connection-method feature' and piece marks this proposal leans on do not exist in the code. Useful existing pieces:
- joints.ends_of, passing_of and through_member give the butting-member count per joint;
- Series.tap and Series.tappable(weight) give the end-tap thread;
- pricing FIELDS plus Settings.add_properties make a new App::PropertyMap price table backward compatible;
- values() and apply_values carry it into pricing.json automatically.

## Implementation approach

Effort L confirmed: counts, kits, pack rounding and the report block are M; preload warnings add S-M; slot conflicts with in-slot panels add M.

Implementation:
- New pure-Python hardware.py with Kit items (item, qty, per), where per is joint / butting member / cell / free end. count() aggregates the totals, and packs(qty, sizes) returns (packs, spare). Test it in tests/test_hardware.py.
- Default kits live in resources/hardware_kits.json, with a user copy at <UserAppData>/ProfileBuilder/hardware.json. Key them by slot system and cell (profiles.SERIES[obj.Series].system plus cell, e.g. 'B-type 20') rather than by Designation, so all weight classes share one kit.
- Joint gets a 'Connection' enumeration (None / Inner bracket / Angle bracket / End tap / Custom) via add_properties, with its list refreshed in onDocumentRestored like ThroughRule. The default is None, so restored documents don't change their totals silently.
- Connections per butt joint = ends minus the through member, plus all ends at a T-junction. For per-cell kits, count the butting member's cells along the contact face from member_frame(butter).rect.
- End tap checks tappable(weight) and warns for Ultralight.
- cutlist.build_report adds report.hardware rows and a 'Hardware' summary line before Delivery. _blocks gets a HARDWARE_HEADER block, and hardware mass is added to the delivery mass.
- pricing.FIELDS gets 'HardwarePrices' (App::PropertyMap with values like '0.35' or '12.50/50', parsed by a helper next to parse_number).
- Preload check: a profile whose two ends are both butting ends (not the through member, not free) has every open slot closed at both ends. The report then gives a warning naming its open faces. Through members with a flush ExtendThrough end count as open.
- freecad_smoke: a Vertical-rule cube gives 16 connections (8 corners x 2 butting rails) and warns for all 8 rails.

## Blockers and caveats

- Kit contents and pack sizes are vendor data the repo doesn't have. Ship clearly marked example kits for the catalog's slot systems (B-type, I-type, Misumi).
- Which slot faces a bracket occupies is unknown without a face choice per connection, so conflicts with in-slot panels are rule-based guesses.
- Plan it together with accessories-from-model so there is one price table and one report block.

## Risks

- Kits are vendor-specific and opinionated: ship editable examples and keep them as data, not code.
- 2-way corners, 3-way corners and T-junctions need different multipliers.
- Which slot ends a joint blocks is a geometric approximation, and without modelled brackets, clashes are rule-based.
- Keep it 'count only' so it doesn't reopen the bracket-geometry scope.
- Kit keys join on series/product keys, which must never be renamed.
- It works best on top of the connection-method feature, but plain bracket counts can ship without it.

## Prior art

item Engineeringtool, Bosch Rexroth MTpro and Misumi FRAMES compile fastener BOMs automatically. 3D printer build guides such as Voron's list nuts per assembly step by hand. FrameForge only counts manually placed App::Links.

## Modules

- new freecad/profile_builder/hardware.py (pure-Python rules)
- `joints.py`
- `panels.py`
- `cutlist.py (_blocks, build_report)`
- `pricing.py`
- `pricing_ui.py`
- `tests/test_hardware.py`
- `tests/freecad_smoke.py`
