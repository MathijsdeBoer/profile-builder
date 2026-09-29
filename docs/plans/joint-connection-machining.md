# Connection method per joint, with derived machining: end taps, access holes, counterbores

| | |
|---|---|
| Status | Planned |
| Category | Joints & assembly |
| Effort | L (first estimate L) |
| Value | high |
| Proposed from | printer-builder, industrial, purchasing-workshop, competitors, engineering |

## Problem

Most hobby and industrial butt joints use either a bracket or a tapped end plus an access hole (the blind joint). Which ends to tap, and where to drill the wrench hole in the through profile, is worked out by hand, and a mistake scraps a cut piece. Suppliers (item, Motedis, Misumi, 80/20, and many local cut-to-size shops) sell tapping, counterbores and access holes per operation, often for more than the cut itself. The cut list shows only lengths and miters, and the estimate leaves all this out. Series.tap ('M5') and Series.tappable() (an Ultralight core can't be tapped) exist, but only the task-panel info text uses them, so nothing warns when a design relies on tapping an untappable core.

## Proposal

Add a Connection enumeration to Joint: None / Bracket (no machining) / End tap + access hole / Anchor (central) fastener / Through bolt, and so on. Its parameters come from a small user-editable table per slot system: tap size (default Series.tap), tap depth, access-hole diameter and distance, counterbore.

Operations are derived lazily in execute for every butt joint, the same way adjustment() works:
- The butting end gets 'tap M5 x 15, one per cell'.
- The through member, or the passing member of a T-junction, gets 'access hole Ø7 on its Left face, 390.0 mm from its start'. The position comes from the vertex, the through member's joint offset and the butting member's support().
Free profiles can also carry manual per-end StartMachining/EndMachining and an AccessHoles list.

Outputs:
- A Machining column in the cut list, in vendor-style text. Operations join the collect() grouping key but not product_key, so saved prices keep working.
- Per-operation fees in Pricing (tap, hole, counterbore). CutCost can optionally be split into square and miter cuts.

Checks: Ultralight core or missing centre bore, a tap asked on a mitered end, an access hole on a closed face or beyond the trimmed length, overlapping holes at T-junctions.

Later additions:
- Phase 2: cut real hole geometry into the solid, behind a toggle.
- Engineering add-on: fastener count and torque give an indicative slip-load hint (fasteners x μ x preload, F = T/(K·d)), plus warnings such as 'single end-tap screw: the joint can rotate under torsion'.

## What exists today

Confirmed: Series.tap and Series.tappable() are only used in the info text of taskpanel._update_info (lines 363-366). Nothing in joints, cutlist or pricing knows about machining. PIECE_HEADER has exactly 9 entries and write_spreadsheet zips with 'ABCDEFGHI', so a 10th column would be dropped silently.

## Implementation approach

Work out operations when the report is built, not in Profile.execute. Nothing gets stored, so Swap, Run through and PassingMembers changes are always current, and the staleness risk named in the proposal goes away.
1. profiles.py (pure): add a THREADS table (tap drill M3 2.5, M5 4.2, M6 5.0, M8 6.8, M10 8.5; default tap depth; access-hole Ø) and can_tap(bore_diameter, center_bore, tap). It compares the object's actual BoreDiameter with the tap drill (±0.3 mm), so customised dimensions and CenterBore=False are caught, not only Weight == 'Ultralight'. Inch profiles such as 80/20's 1010 and 1515 are tapped 1/4-20 and 5/16-18, so key the table by thread name rather than assume M sizes, even though the catalog has no inch series yet. Test it with pytest in test_profiles.py.
2. joints.Joint.add_properties: add a Connection enumeration defaulting to 'None' (None / Bracket / End tap + access hole / Anchor / Through bolt), plus optional TapDepth and AccessHole overrides (0 = table value). Old documents pick these up through onDocumentRestored. adjustment() and through_member() stay unchanged.
3. New machining.py (FreeCAD level, no GUI): operations(doc) -> {profile Name: [Op]}. For each joint with a Connection, take through_member(), ends_of() and passing_of().
   - Butting end: one tap per cell centre of its member_frame rect.
   - Through or passing member: one access hole per butting cell centre. Position along it = (vertex - edge start)·z + ExtendStart + JointStartOffset + cell offset. Face = panels._face_towards(through_frame, -away).
   - For the anchor method, the hole goes in the butting member's side instead, so the method table needs a 'hole on through / butting member' flag.
4. Checks, as report warnings: can_tap is false; a tap on a mitered end; the through member's near face is Closed<face>, so the screw head has no slot; a hole outside 0..Length; holes closer than Ø at T-junctions.
5. cutlist.collect(): add a canonical machining signature to the key. Normalise hole positions under end swap (d vs L-d) and section symmetry, or mirror-identical pieces split into separate rows. product_key stays unchanged, so saved prices still apply. Add a Machining column and extend the cols string.
6. pricing.FIELDS: add TapCost, HoleCost and CounterboreCost, and a Machining line in the summary. Add Connection to simple_panel JOINT_FIELDS and three spin boxes in pricing_ui.
7. Smoke test on the existing 2020 cube with End tap: 8 rails × 2 ends tapped, each post gets 4 holes, plus an Ultralight warning case.
Keep phase 2 (hole solids in geometry.make_solid) and the slip-load add-on as separate items: they are what would push this to XL.

## Blockers and caveats

No hard blocker.
- Vendor conventions differ on which member gets the hole: OpenBuilds and Misumi blind joints drill the through member, while 80/20 anchor fasteners drill the butting member. This has to be table data.
- Workshop text like '390 mm from start' is ambiguous at the saw, because nothing marks the start end. Positions need an end reference (for example, measured from the mitered or marked end). Shops that work in inches expect positions in inches, so the Machining text should follow FreeCAD's unit schema instead of always printing mm.
- Phase 1 (report only), including pricing, checks, UI and tests, is already about 4-5 days. The full scope in the proposal is larger than L.

## Risks

- T-junction passing members are referenced by name (PassingMembers), not by link, so their holes go stale unless touch_joints_of also touches passing profiles. Keep phase 1 report-only.
- Always derive operations and never store them, because Swap or Run through changes which member gets the hole.
- The joint must never link back to the profiles.
- Adding machining to the grouping key splits existing cut-list rows.
- write_spreadsheet zips values with the fixed string 'ABCDEFGHI' (9 columns), so a 10th column is dropped silently unless that string is extended.
- Booleans slow recompute, so skip them when no machining is set.
- Hole conventions vary by vendor: keep them as editable table data.
- New Joint properties must go through add_properties.

## Prior art

Misumi alteration codes: LTP/RTP/TPW taps and LCH/LCV/LCP wrench access holes. Motedis per-end machining (M5 tap, D4.5 counterbores). 80/20 fabrication services. item Engineeringtool and Bosch Rexroth MTpro add connector machining automatically. The OpenBuilds blind-joint method. FrameForge has only a manual sketch-based Extruded Cutout.

## Modules

- `joints.py`
- `feature.py (execute collects operations)`
- `geometry.py (hole tools, phase 2)`
- `profiles.py (access-hole diameter, tap depth)`
- `cutlist.py`
- `pricing.py`
- `pricing_ui.py`
- `simple_panel.py`
- `taskpanel.py`
- `tests/freecad_smoke.py`
- `tests/test_profiles.py`
