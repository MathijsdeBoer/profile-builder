# Enclosure doors: sheet doors and framed guard doors with hinge gaps and a swing check

| | |
|---|---|
| Status | Planned |
| Category | Design & modelling |
| Effort | XL (first estimate L) |
| Value | medium |
| Proposed from | printer-builder, industrial |

## Problem

Enclosures for 3D printers, CNC machines and test rigs need at least a front door, and machine guards and workstations need framed doors. Today a door is an On-face panel with a guessed hinge gap, or an extra sketch for a door frame (often a lighter profile, such as 30x30 in a 40x40 frame). Gaps are worked out by hand and redone whenever the opening changes. The overlap on the latch side gets forgotten, and a door swing that hits the table, a wall or the neighbouring panel is only found at assembly.

## Proposal

Stage 1, sheet door, built on the panel outline:
- choice of hinge member, and overlap and gap per edge;
- optional split into two leaves;
- an OpenAngle property that rotates the sheet about the hinge axis, for a visual fit check and for the frame check;
- hinge count by door height, and handle and magnetic-catch positions.
The cut list lists the doors as sheets plus hinge, handle and magnet hardware, and the door holes go into the panel DXF export.

Stage 2, framed door: select the profiles around an opening, as for Panel.
- A DoorOutline FeaturePython builds a rectangular wire with panel_outline-style maths: the frame's inner faces minus HingeGap, LatchGap, TopGap and BottomGap, mounted in-plane or overlapping.
- Door profiles use PathEdge on the outline's edges, create_joints makes the corners (miter or butt), and make_panel adds the infill.
- A hinge-count rule by height and mass, with a warning when the door mass (profiles plus panel, both already computed) is above the hinge rating.
- OpenAngle rotates the whole outline, so the framed door follows for clearance checks.

## What exists today

Not implemented. The proposal relies on things that don't exist: there is no panel DXF export anywhere in the code (grep finds no DXF), and no hardware or line-item concept in cutlist or pricing for hinges, handles or magnets. Other claims check out:
- feature._edge_placement fixes local X to world X for vertical edges (`V(0,0,1).cross(z)` is zero, falls back to V(1,0,0)).
- Panel.execute resets `obj.Placement = App.Placement()` after assigning the shape. So an OpenAngle must be baked into the points or geometry (as the anchor is for profiles), not applied with Shape.rotate or Placement.

## Implementation approach

Stage 1 (M-L), sheet door:
- A Door FeaturePython in a new doors.py. It reuses panels.panel_outline for the opening, then offsets each edge by HingeGap, LatchGap, TopGap and BottomGap, or by an overlap for doors mounted on the face.
- Optional two leaves. The hinge member is picked from Profiles.
- OpenAngle rotates the corner points about the hinge-edge axis before Part.Face and extrude. Width and Height come from the unrotated outline, so the cut list is unaffected.
- The cut list gets the doors as sheets (a panels.sheet_key-style key).
- Hinge, handle and magnet counts first appear as report notes. Priced lines need a separate hardware feature: a 'Hardware' map in pricing.FIELDS and a HARDWARE block in cutlist._blocks. Hinge and latch products, part numbers and ratings differ per supplier and region, so these items must be user-editable entries, not a built-in list.

Stage 2 (L), framed door:
- A DoorOutline Part::FeaturePython whose Shape is a rectangular wire computed only from member_frame() of the opening's profiles. Frames only, never their shapes, to avoid cycles.
- Door profiles use PathEdge=(outline, 'EdgeN'). joints.create_joints makes the corners, and panels.make_panel adds the infill.
- The vertical door members need an optional reference normal in _edge_placement, taken from the path object's Placement or plane. It must be opt-in per profile, for example a new 'OrientFromPath' bool added via add_properties with default False, so existing documents keep their orientation.

Update simple_panel fields, commands, init_gui and the smoke tests.

## Blockers and caveats

No FreeCAD blocker. Hardware line items and DXF export are prerequisite features of their own. Changing _edge_placement for everyone would re-orient vertical 2040 posts in saved documents, which must not happen. Both stages together are more than a week. Many enclosures (3D printers, small CNC machines, electronics cabinets) use a simple on-face sheet door with bought or printed hinges, so stage 1 alone covers most of them. Stage 2 matters mainly for machine guarding and workstations.

## Risks

- Hinge thickness adds a product-dependent gap, so it must be a parameter. OpenAngle must not change the sheet size in the cut list.
- feature._edge_placement fixes local X to world X for vertical edges (V(0,0,1).cross(z) is zero), so the vertical members of an opened framed door would not turn with it. That needs an optional reference normal from the path object's plane, which would also fix posts in rotated frames.
- Framed doors are created by a command, so changing the door type or size class means regenerating.
- The outline must depend only on the members' frames, not on their shapes, to avoid cycles.

## Prior art

The door and guarding modules in item Engineeringtool and Bosch Rexroth MTpro. 80/20 and Misumi sell hinges, handles and latches for their own profiles.

## Modules

- `panels.py`
- new freecad/profile_builder/doors.py
- `joints.py`
- `feature.py (_edge_placement reference normal)`
- `cutlist.py`
- `pricing.py / pricing_ui.py (hardware items)`
- `simple_panel.py`
- `commands.py`
- `init_gui.py`
- `tests/freecad_smoke.py`
