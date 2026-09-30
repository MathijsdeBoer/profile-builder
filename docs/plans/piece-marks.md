# Stable piece marks in the cut list, stock plan and 3D view

| | |
|---|---|
| Status | Done |
| Category | Manufacturing & ordering |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | printer-builder, industrial, purchasing-workshop, freecad-ux, competitors |

## Status

Done on 2026-09-30:
- Marks (A1, A2, ...) appear in the cut list and the stock plan, and are stored in each profile's PieceMark and tree description. Sheets get marks too (P-1, P-2, ...).
- They are stable: a hidden `Piece marks` object (`cutlist.MarkStore`) keeps the marks given so far as JSON, and `pieces.assign_marks` keeps a group's mark while its key exists. New groups get the next number, new products the next letter, and marks of vanished groups are retired. **Renumber piece marks** starts again from A1. Storing the marks touches nothing.
- **Show piece marks** draws each mark at the profile's midpoint in the 3D view (a `ShowMark` view property, rebuilt when the document opens, hidden with the profile).

Not done here: printed labels (see [workshop-pack](workshop-pack.md)) and colouring by mark (see [live-cutlist-dock](live-cutlist-dock.md)). A group whose length changes gets a new mark rather than keeping its old one, on purpose: a label on a piece cut at the old length would otherwise be wrong.

## Problem

The cut list says '8 x 380' but not which pieces those are. The stock plan lists only lengths ('380 + 380 + 470'), although stock.plan() carries each piece's label and build_report throws it away when formatting the bar rows. In an enclosure or a machine frame, 380, 384 and 400 mm pieces look identical on the bench, and so do mitered 2040s. The tree shows only '2020 profile0NN'. After cutting, the pieces are anonymous, which leads to wrong assembly.

## Proposal

Give each cut group (the collect() key) a short, stable mark: A, B, C, or a per-product prefix such as '2020-A'. Optionally give each piece its own mark (A1..A8). Store it as a read-only Mark output, or in a separate object (see risks). The mark appears:
- as the first column in the spreadsheet and CSV;
- in the stock plan ('Bar 1: A1 A2 B1 | offcut 412');
- in Label2, so the tree's Description column reads 'B, 380 mm';
- optionally as a 3D text label (Coin SoText2) at the profile's midpoint, toggled by a view property, so a screenshot works as an assembly map.
Existing marks are kept while their key still exists, and new keys get the next free letter. A 'Renumber marks' command reassigns them on purpose.

## What exists today

Not implemented. The stock plan labels are weaker than the proposal assumes: build_report builds pieces_by_product as `[(saw, obj.Label)] * qty`, so every piece in a group carries the label of the group's first object, and the bar rows then drop even that (`for length, _label in bar.pieces`). Probe: setting Label2 (and Label) leaves the object 'Up-to-date', so marks in Label2 cause no recompute. The collect() key ignores MiterAcross, which matters for 2040 miters.

## Implementation approach

Core (S):
- In cutlist.build_report, give each collect() group a letter per product: A..Z, then AA.
- Add a 'Mark' first column to PIECE_HEADER.
- Carry the mark instead of obj.Label in pieces_by_product, and format bar rows as 'A 380 + A 380 + B 470'.
- Extend `cols` in write_spreadsheet beyond 'ABCDEFGHI'. zip() silently truncates, so a 10th column would vanish from the spreadsheet without an error.
- Add MiterAcross to the collect() key.

Stability (M):
- Persist a PropertyMap 'PieceMarks' (a key string such as 'product|len|saw|m1|m2|across' mapped to a mark) on the existing ProfileBuilderPricing settings object, or on a small new 'ProfileBuilderMarks' object. Don't store it on profiles: a normal property touches the profile, though an addProperty attr with Prop_Output (8) would avoid that.
- New keys get the next unused letter, and letters of vanished keys are retired rather than reused. A 'Renumber marks' command clears the map.
- Write Label2 = 'B, 380 mm' from the CutList command. Never write Label: joints.through_member and swap() match obj.Label == joint.Through.

Optional 3D labels:
- ViewProviderProfile.attach() adds an SoSwitch > SoTranslation + SoText2 to vobj.RootNode. updateData('Shape') moves it to the midpoint, and a view property 'ShowMark' toggles it.
- attach runs on restore, so the nodes rebuild themselves.

Add a smoke check that marks survive reload and a length edit of another group.

## Blockers and caveats

None. Marks keyed by length change when the sketch changes, so 'stable' only means stable for unchanged groups. The docs should say that printed labels go stale after edits. For a plain cube (8x380, 4x420) marks add little. The value is in larger frames with near-identical lengths (enclosures, machine frames, workstations), in pieces that a supplier cuts and ships loose, and in FrameForge parity. The S core has the best value for the effort.

## Risks

- Never write marks into Label: joints.through_member matches obj.Label == joint.Through, so relabelling silently breaks Manual joints.
- Writing a property on a profile touches it and triggers a recompute. Keeping marks in the report or in a separate object avoids that.
- Marks must survive reload (add_properties/_restoring pattern), and renumbering after edits makes already-printed labels wrong.
- The grouping key ignores the miter axis today (see miter-plane-key), so two different pieces can share a mark until that is fixed.
- The spreadsheet's 'ABCDEFGHI' column limit must be extended for the new column.
- Coin text nodes must be rebuilt after the document is restored.

## Prior art

FrameForge Populate IDs (one ID per group of identical parts). Part marks in steel detailing tools (Tekla, Advance Steel). OptiCut and CutList Optimizer label pieces on their bar diagrams.

## Modules

- `cutlist.py (marks in Report, stock rows)`
- `stock.py`
- `feature.py (Mark output, ViewProviderProfile label node)`
- `commands.py`
- `init_gui.py`
- `tests/freecad_smoke.py`
