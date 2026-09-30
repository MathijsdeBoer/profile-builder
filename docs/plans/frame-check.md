# Frame check: one list of clashes, unjoined ends and other silent order errors

| | |
|---|---|
| Status | Done |
| Category | Analysis |
| Effort | L (first estimate M) |
| Value | high |
| Proposed from | printer-builder, freecad-ux |

## Status

Done: broken profiles, joints and panels are listed at the top of the cut list and the total is marked incomplete; near-miss vertices are reported when creating joints; inserting twice on the same edges is prevented.

Done on 2026-09-30: the **Check frame** command (`check.py`, `check_ui.py`) lists findings by severity. Clicking one selects its objects and zooms to them. It checks:
- broken objects;
- two profiles on one edge (Fix: delete the extra ones);
- ends that meet or nearly meet another profile or joint without a joint (Fix: join; the panel says the real fix is the sketch);
- overlaps between profiles and panels, on each profile's outer box with its real length and miters, leaving out a panel in its own slots;
- panel fit warnings and drawing notes, carriage warnings, and pieces longer than a stock bar;
- lengths that differ by less than 1 mm, sketch edges without a profile, and the outside size.
Distances follow the unit schema; small gaps are written with enough digits to mean something in inches too. The Cut list command prints a one-line summary of the quick checks. A 12-profile cube checks in 0.1 s.

A review of the first version found five defects, all fixed with tests: the join fix could turn a near-miss corner into a T-junction, a three-way near miss offered a fix that could never work, the duplicate fix could delete the copy a panel uses, collinear bars were reported as overlapping, and small gaps printed as 0 in inch schemas.

Not done: a temporary 3D highlight (selection is used instead), panels whose members are no longer coplanar (they already fail with an error), and a check when inserting on an edge that already has a profile (inserting skips such edges instead).

## Problem

Fit problems are found by eye, or not at all.
- create_joints matches vertices within 1e-3 mm. A post whose sketch vertex is 0.2 mm off a corner, or a newly drawn edge that never went through Joints, gets no joint and overlaps the rails at full length. The cut list still looks plausible.
- Inserting a size with a sketch selected creates a profile on every straight edge. selected_edges() never checks whether an edge already carries a profile, so a second click silently doubles the cut list.
- A failed joint shows up only as a report-view traceback on one profile.
- The pairwise overlap check exists only in tests/freecad_smoke.py.

## Proposal

A 'Check frame' command opens a task panel that lists findings by severity. Clicking a finding selects and zooms to the objects involved, with a temporary highlight that is cleared when the panel closes. Where the repair is obvious, a Fix button appears. Checks:
- Profile/profile and profile/panel clashes: bounding-box prefilter, then Shape.common volume above a tolerance.
- Two profiles on the same edge. Fix: delete the extra one.
- Free ends within a few mm of another profile, path or joint but not joined ('not joined, sketch vertex 0.2 mm off'). Fix: run create_joints on the pair.
- Profiles, joints and panels in an error state, with their status strings (e.g. a non-perpendicular butt).
- Panels that cut into a slot bottom or into each other, or whose members are no longer coplanar.
- Pieces longer than the stock bar.
- Straight sketch edges without a profile.
- Near-duplicate cut lengths (380.0 vs 380.4), with a suggestion to equalise them.
- Overall outside dimensions of the frame or of the selection.
The same check functions also warn when a profile is inserted on an edge that already has one (skip or replace), and run at the end of Cut list, which then warns 'N issues, see Check frame'.

## What exists today

Partly exists. The report already warns about pieces longer than a stock bar, but only in Stock bars mode (cutlist.build_report, result.oversize). PropertyTaskPanel shows getStatusString() for an invalid joint or panel, but only when that object is opened. The pairwise common() overlap check exists only in tests/freecad_smoke.py. None of the other checks exist. A FreeCAD 1.1 probe confirmed the silent failures:
- cutlist.collect() skips profiles with `not obj.isValid()` and gives no warning. A document with 8 profiles, one of them invalid, reported 7 pieces. joints.adjustment() raises inside the profile's execute, so the butting profile becomes invalid and drops out of the order.
- A post whose vertex is 0.2 mm off: create_joints made no joint, and the two profiles overlapped by 453 mm³ with no message.
- commands.selected_edges() never checks for an existing profile on the same edge.

## Implementation approach

Stage it.

First an S-sized step: in cutlist.build_report, warn for each invalid profile or panel with obj.getStatusString(), and for each (PathEdge object, sub) pair used by more than one profile.

Then add a new check.py. It holds pure functions that return Finding(severity, text, objects, fix=None) records:
- `invalid_objects(doc)`
- `duplicate_edges(doc)`, grouping by (p.PathEdge[0].Name, p.PathEdge[1][0])
- `near_miss_ends(doc, tol=2.0)`: free ends, i.e. StartJoint/EndJoint None, whose `joints._end_point` lies within tol of another end, a joint vertex or an edge (Part.Vertex.distToShape) but beyond joints.TOLERANCE
- `clashes(doc)`: AABB prefilter on Shape.BoundBox shrunk by 0.05 mm. Run the boolean on envelope solids rather than the slotted shapes: Part.makeBox from member_frame().rect over the length, with the miter cut via geometry.make_solid on a plain rectangle face. This is 10-50x faster and avoids slivers from slots. Report common().Volume above about 1 mm³.
- `unprofiled_edges(doc)`: straight edges of objects already used as a PathEdge source that carry no profile
- `near_duplicate_lengths(report)`: reuse collect() keys and cluster lengths within 1 mm
- in-slot panels whose InsertDepth is above SlotDepth, and panel/panel clashes

Tolerances stay in mm internally, but finding texts format distances with App.Units.Quantity(...).UserString, so they follow the user's unit schema (mm or inches).

The GUI is a task panel with a QTreeWidget grouped by severity:
- On click, use Gui.Selection.clearSelection/addSelection plus Gui.SendMsgToActiveView('ViewSelection'). For the highlight, use selection or a temporary SoSeparator on the active view's scene graph. Don't write ShapeColor: view-property changes are saved in GuiDocument.xml and can be recorded in an open transaction.
- Fix buttons only for 'delete duplicate' and 'join anyway', which calls joints.create_joints(doc, pair, tolerance=d+0.01). The panel should tell the user that the real fix is the sketch, because the remaining offset stays in the length.
- Register in commands.register and init_gui.

Run the cheap checks (invalid, duplicate, near-miss) at the end of the CutList command and print 'N issues, see Check frame'. In QuickProfile, skip edges that already carry a profile and print a console message rather than opening a modal dialog, which would block GUI tests.

Add smoke cases: the 0.2 mm post, a duplicate insert, an invalid profile, and the cube with no clash.

## Blockers and caveats

None hard. Booleans on slotted solids are slow at 100+ profiles, so use envelope solids. Butted faces that only touch must fall under the volume tolerance. Full scope (9 checks, Fix buttons, highlight, insert-time handling, tests) is about a week. The cut-list warnings plus a read-only findings list are M (2-3 days) and cover most of the value.

## Risks

- Pairwise booleans on slotted solids are O(n^2) and slow for 50-100+ profiles, so the bounding-box prefilter is essential.
- Butted faces that only touch produce sliver volumes, so a sensible volume tolerance is needed.
- The highlight must not be saved as a permanent ShapeColor or end up on the undo stack.

## Prior art

The smoke test's pairwise common() overlap check. FreeCAD's Part > Check geometry validates single shapes, not clashes between them or frame logic.

## Modules

- new freecad/profile_builder/check.py
- `commands.py (selected_edges warning)`
- `cutlist.py (reuse collect for near-duplicates)`
- `joints.py (tolerance, ends_of)`
- `init_gui.py`
- `tests/freecad_smoke.py`
