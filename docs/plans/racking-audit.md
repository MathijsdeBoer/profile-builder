# Racking and bracing audit for frames

| | |
|---|---|
| Status | Planned |
| Category | Analysis |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | engineering |

## Problem

The usual stiffness problem in a T-slot box frame, such as a printer frame, enclosure, workstation or machine base, is racking: the box shears into a parallelogram, because every face relies on its corner joints alone. Section properties don't catch this, and it is often discovered only after assembly.

## Proposal

A 'Check frame' step builds the member graph. Nodes are the joint vertices plus the T-junction points from PassingMembers, and edges are the profiles on path edges. It finds the closed planar loops, typically the 6 faces of a cube, and classifies each one:
- braced: an On-face panel whose Profiles cover the loop, or a diagonal profile whose ends lie near opposite corners. Diagonals are detected geometrically, because butt joints reject non-perpendicular members today;
- weakly braced: an In-slot panel, which floats with Clearance and carries little shear, rated by sheet material;
- unbraced.
The audit reports in words, e.g. 'Left side (YZ): unbraced, racks on 4 corner joints only. Add an on-face panel, a diagonal or corner gussets.' It can highlight the loop in the 3D view, and adds a 'Frame' section to the report notes. This gives most of the practical benefit of a frame analysis, with no numbers to over-trust.

## What exists today

Nothing like it exists. The data it needs is there: joints have a vertex Shape, profiles have StartJoint/EndJoint, T-junctions are in PassingMembers (names), and panels list their Profiles and Mount.

## Implementation approach

A new bracing.py, or better, one section of check.py:

1. Nodes are joint vertices (joints.is_joint, Shape.Vertexes[0].Point).
2. Edges are profiles with a PathEdge and both ends in a joint. Split a passing member into segments at the T-joints that list it, ordered by projecting the joint points onto member_frame().z.
3. Find planar 4-cycles by brute force over edge pairs sharing nodes, which is fine below about 300 edges. Check planarity with the triple product. For a cube (Q3) that gives exactly 6 cycles, and faces split by middle bars give smaller 4-cycles once passing members are split.
4. Classify each cycle:
   - braced: an On-face panel whose Profiles cover every cycle member, or a profile not on the cycle whose path-edge endpoints lie within a few mm of two cycle edges on opposite sides;
   - weak: an In-slot panel;
   - otherwise unbraced.
5. Name each face by its normal ('Left side (YZ)').
6. Output: findings for the frame-check panel and one 'Frame:' note in build_report warnings.

Smoke test: the cube gives 6 unbraced faces; adding an on-face panel on one side gives 5.

## Blockers and caveats

Findings depend on things the model can't see:
- Corner gussets, brackets and 3-way corner cubes aren't modelled (brackets were deferred, and STEP parts are not profiles), so braced frames get reported as unbraced.
- Clip-mounted or foam-taped panels, as on Voron-style printers, count as On-face even though they float.
- Free profiles (no PathEdge) and ends without joints are invisible.
- Many frames are deliberately open on some faces (open-frame printers, machine frames with an open operator side, conveyor stands), so the audit often restates what the builder chose.
This makes it medium rather than high. It is worth doing as a qualitative section of frame-check, with a way to mark a face as 'braced by hardware'.

## Risks

- Loop detection on arbitrary frames needs care. Restrict it to planar 4-cycles at first, which covers cubes and enclosures.
- Free-placed profiles (no PathEdge) are invisible to the graph.
- How much an in-slot panel counts depends on fit and material, so it stays a qualitative 'weak' class, not a number.
- It fits naturally as a section of the frame-check panel.

## Prior art

Common advice in printer build guides: Voron and similar frames rely on panels and bracing. Profile vendors sell gusset plates and diagonal braces for the same reason. Not in FrameForge, FreeCAD FEM or vendor configurators.

## Modules

- new freecad/profile_builder/bracing.py
- `joints.py`
- `panels.py`
- `feature.py`
- `cutlist.py`
- `commands.py (or the frame-check panel)`
- `tests/freecad_smoke.py`
