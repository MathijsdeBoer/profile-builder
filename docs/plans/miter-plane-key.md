# Miter plane in the piece key, and a workshop-readable miter description

| | |
|---|---|
| Status | Done |
| Category | Manufacturing & ordering |
| Effort | S (first estimate S) |
| Value | medium |
| Proposed from | purchasing-workshop, competitors |

## Status

The per-end miter axis is stored on the profile (MiterStartAxis/MiterEndAxis) and pieces are grouped by a canonical form of their cuts, so mirror-identical pieces share a row. The cut list shows which face width each miter slopes across. It shows the width as a number ('40'), not the prose descriptions proposed below, so the column needs no translation for shops that work in other languages.

## Problem

collect() groups pieces only by product_key, length, saw length and the two miter angles. joints.adjustment() returns a per-end miter axis, and Profile.execute uses it locally, but never stores it. Even the profile's own MiterAcross is not in the key. So a piece mitered across X at both ends is merged with one mitered across X at one end and Y at the other. Those are physically different pieces, so the cut list is wrong. The signed angles ('45, -45') also don't tell the person at the saw whether the cuts are parallel (a parallelogram) or opposed (a trapezoid), or which face of a 2040 they cut across.

## Proposal

Store the effective axis of each end as read-only outputs, MiterStartAcross and MiterEndAcross, and add them to the collect() key. Describe each cut in workshop terms in the cut list:
- 'both ends 45°, opposed (trapezoid), cut across the 40 mm face';
- 'parallel';
- 'ends in perpendicular planes (rotated 90°)'.
An optional small side-view hint can go with it. Handle symmetry: on an all-open square profile only the relation between the two ends matters, while on 2040s and on profiles with closed faces the face matters too.

## What exists today

Partly. OverallLength is already in the collect() key, so on non-square sections across X and across Y are already separate. A probe in FreeCAD 1.1.3 showed a 2040 × 500 at 45° is 520 mm across X and 540 mm across Y. The claimed merge only happens on square sections: closed-face profiles cut across X vs across Y, or pieces with mixed X/Y ends. Mixed ends are rare, because joints only miter where exactly two profiles meet.
The probe also found the opposite bug, which is more common. In a mitered 400 × 300 2020 ring whose opposite lines run the same direction, collect() gives 4 rows for 2 identical pairs: 300 × (-45, -45), 300 × (45, 45), 400 × (-45, -45) and 400 × (45, 45). The signed angles follow the edge direction, so mirror-identical pieces split into separate rows.

## Implementation approach

Reframe the item as a canonical cut description. It fixes both the rare merge and the common over-split.
1. profiles.py (pure): canonical_cut(width, height, closed_faces, start=(angle, axis), end=(angle, axis)).
   - It lists the rigid motions that map the section onto itself: 180° about the axis when the closed-face pattern allows it, 90° when the section is square and the closed faces match, and end-for-end flip.
   - It applies them to the pair and returns the lexicographically smallest result.
   - describe_cut() returns text such as 'both ends 45°, opposed (trapezoid), across the 20 mm face', 'parallel' or 'ends in perpendicular planes'.
   - Test with pytest.
2. feature.py: add read-only outputs MiterStartAcross and MiterEndAcross (enumeration, mode=1) through add_properties. Set them in execute from the local 'across' list, only when the value changed.
3. cutlist.collect(): build the key from canonical_cut instead of the raw m1/m2, and show the description (a new column means extending the cols string).
4. Smoke tests:
   - The inconsistent-direction ring must give 2 rows.
   - Check canonical_cut against real geometry: build both candidate solids with geometry.make_solid and compare Volume and principal moments.

## Blockers and caveats

None. Rows will merge or split in existing documents' cut lists, which is intended; mention it in the changelog.

## Risks

- Face naming depends on Spin and on the Frame axes. Reuse panels._face_towards-style logic, so 'across the 40 face' is correct for spun members.
- Old documents gain the new properties through add_properties.
- Rows that used to be merged may split. That is correct, but users will notice.

## Prior art

FrameForge's cut-list legend in create_bom.py: '*' for angles rotated 90° along the edge, '-' for both cuts in the same direction.

## Modules

- `feature.py (per-end across outputs in execute)`
- `cutlist.py (collect key, description column)`
- `joints.py`
- `tests/freecad_smoke.py`
