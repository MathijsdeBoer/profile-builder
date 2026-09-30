# Panel fabrication: slot-aligned mounting holes, rounded corners, cutouts, DXF/SVG export

| | |
|---|---|
| Status | Done |
| Category | Manufacturing & ordering |
| Effort | L (first estimate M) |
| Value | high |
| Proposed from | printer-builder, purchasing-workshop |

## Status

Done on 2026-09-30:
- On-face panels get holes on the slot centre lines (`HoleDiameter`, `HoleSpacing`, `EdgeDistance`, `CornerKeepout`, `SlotChoice`). The lines follow each member's real extent after joint trims, are clipped to the sheet shrunk by the edge distance, and keep away from the sheet corners and from every joint in the frame plane. A slot line too close to the edge is reported, not dropped silently. Closed faces get no holes.
- `CornerRadius` rounds the sheet corners (reduced, with a note, when an edge is too short). `Cutouts` links a sketch parallel to the sheet; its closed outlines are cut through (lines, arcs and circles stay exact, other curves are approximated in the files).
- Holes and cutouts are cut from the solid, so the mass is right. `HoleCount` is an output.
- The flat part is computed once (`panels.drawing`) and used for the solid, the files and the cut list.
- **Export panels** writes a DXF R12 (layers CUT, HOLES, MARK) and a true-size SVG per different sheet, with the part's lower-left corner at the origin. The unit (mm or inch) follows FreeCAD's unit schema and is in the file name and the MARK text, because DXF R12 cannot store it. The writers are pure Python (`fabrication.py`, tested with pytest).
- The cut list's sheet rows have a mark (P-1, ...) and a Holes column. Sheets are grouped by a fingerprint of outline, holes and cutouts, so a front and a back sheet, or one turned 90°, are the same part. The Hardware block gets a screw and slot nut per hole, and the notes say to slide in-slot sheets in before the frame is closed.

A review found eleven more defects, all fixed with tests: holes were clipped to a convex, sharp-cornered outline (L-shaped sheets lost holes, rounded corners lost material), slot lines on mitered wide profiles ran past the miter onto solid metal, joint keep-outs were missed for anchored profiles, cutout sketches in a Body were cut in the wrong place, holes inside cutouts were counted, an empty or all-covering cutout sketch misbehaved, and the fingerprint merged sheets with different fan holes (so one was never exported) or split identical ones.

Not done: a price per hole or per cut metre, nesting several parts on one sheet, and brackets as keep-outs (a fixed radius around each joint is used instead). Flipping a sheet over counts as the same part, which is wrong for sheets with a finished face, such as brushed aluminium or printed composite.

## Problem

Enclosure sides, guard infills and machine covers of acrylic, polycarbonate, aluminium composite or sheet metal are laser-cut by a service or CNC-routed in-house, and both need a DXF or SVG. Today a panel is a plain polygon with only a size and a solid. On-face panels need holes exactly on the slot centre lines, because an M5 (or 1/4-20) hole 2 mm off misses the T-nut, and they must stay clear of the corner brackets. Working these positions out by hand is fiddly, although panels.panel_outline() already has the frame geometry needed.

## Proposal

On-face panels get:
- holes on the slot centre line of each member under a panel edge, reusing _face_towards/_check_slot. Closed faces are skipped, and 2040 members get a slot choice.
- properties HoleDiameter (with clearance), HoleSpacing (maximum), EdgeDistance, CornerKeepout, keep-outs at bracket joints, and CornerRadius (rounded corners stop acrylic cracking);
- optional cutouts from a linked sketch (fan, cable gland, filament path).
Holes are cut into the solid so Mass stays right, and the sheet rows list them ('12 x Ø5.5'). Hole counts feed the hardware BOM. In-slot panels get an assembly note that the sheet must be slid in before the last profile is fitted.

'Export panels' writes one DXF R12 file (LINE/CIRCLE/polylines) plus an SVG preview per unique panel, using a small built-in pure-Python writer. The mark and material/thickness go as text on a separate layer, and the file names carry the sheet key and size. DXF R12 has no unit field and cutting services ask for the unit on upload, so the export states the unit in the MARK text and the file name; a wrong guess scales the part by 25.4. A price per hole or per cut metre is optional.

## What exists today

Panels are plain polygon prisms (Mount, Thickness, Clearance, InsertDepth, Margin, Side, PlaneOffset, Material, Density), with no holes, no corner radius and no export. panel_outline() already computes the member frames, the in-plane basis (e1, e2) and the 2D corners, but returns only world points. _face_towards and the slot-position maths in _check_slot are exactly what the hole lines need.

## Implementation approach

Revised effort L, up from M, for everything listed. M covers on-face slot-line holes, CornerRadius and DXF/SVG export; sketch cutouts and keep-outs at joints are the extra.

Implementation:
- In panels.py, split out of panel_outline a helper that returns the 2D corners plus the basis (origin, e1, e2, n, lift), so holes and export share it.
- New properties via add_properties, with defaults that leave restored panels unchanged:
  - HoleDiameter (0 = off), HoleSpacing, EdgeDistance, CornerKeepout, CornerRadius (0);
  - SlotChoice (All / Outer / Inner) for multi-cell members;
  - HoleCount as a read-only output.
- Hole lines, per member:
  - face = _face_towards(frame, n*sign); skip it if Closed<face> is set;
  - slot centres at x0/y0 + (k+0.5)*cell across that face, the same maths as _check_slot;
  - the line runs along frame.z over the member's real extent, from obj.Placement.Base and obj.Length. The Panel links its Profiles, so it recomputes after their joint trims.
- Project each line to (e1, e2), clip it to the polygon inset by EdgeDistance and to CornerKeepout around each corner or joint vertex, and space ceil(len/HoleSpacing)+1 holes evenly.
- Cut Part.makeCylinder tools from the prism, so Mass stays right. Round corners with solid.makeFillet(r, edges parallel to n).
- cutlist.SHEET_HEADER gets a 'Holes' column, still within the spreadsheet writer's 9 columns.
- New pure-Python dxf.py (R12 LINE/ARC/CIRCLE/TEXT on layers CUT, HOLES and MARK) plus an SVG preview, tested with pytest.
- 'Export panels...' command in commands.py writes one file per unique sheet key and size.
- Cutouts: an optional PropertyLink to a sketch that must be parallel to the panel plane (otherwise an error); its closed wires are cut through.
- In-slot panels get an 'insert before closing the frame' note in panel_info and the report.

## Blockers and caveats

- Holes assume the T-nut sits at the slot centre of the face under the panel edge. Members at an angle to the panel edge, or panels over mixed sizes, need per-member handling.
- Keep-outs at brackets depend on a fastening model that doesn't exist; use a fixed CornerKeepout from each joint vertex instead.

## Risks

- Restored documents must default to no holes, so existing panels don't change.
- Members at an angle, or panels over mixed-size members, complicate slot selection.
- Keep-outs need to know where brackets sit, which depends on the fastening model.
- This is not 2D nesting. It is per-panel output that nesting could build on later.

## Prior art

Laser and CNC cutting services (Snijlab, Ponoko, SendCutSend) accept DXF/SVG. FreeCAD's TechDraw/Draft DXF export works, but needs manual page setup per panel, depends on Draft, and changes with preferences.

## Modules

- `panels.py (holes and cutouts in execute, add_properties)`
- `panels.PANEL_FIELDS / simple_panel.py`
- new pure-Python DXF/SVG writer module
- `commands.py`
- `cutlist.py (hole counts)`
- `pricing.py (optional per-hole cost)`
- `tests`
