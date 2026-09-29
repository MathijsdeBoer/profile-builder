# Place the user's vendor STEP brackets at every joint

| | |
|---|---|
| Status | Planned |
| Category | Joints & assembly |
| Effort | L (first estimate L) |
| Value | medium |
| Proposed from | printer-builder |

## Problem

Bracket modelling was deferred because vendors publish STEP files. But brackets are what clash with panels, doors and T-nuts, and they are half the hardware count. Placing 24 corner brackets by hand is tedious, and they don't follow sketch edits or joint swaps. The new angle: don't model brackets; place the user's own STEP files automatically.

## Proposal

Add a Fitting object that links to one user shape, an imported STEP body. A one-time calibration dialog with a preview sets its reference frame: inner corner at the origin, legs along +X and +Y. Placement rules say where it goes: at each butt joint or on each butting member, on the inner, top or all open faces. The object creates App::Link instances whose placements come from member_frame of the butting and through members, and they update when the frame changes or joint roles swap. Fittings are counted in the hardware list and included in the frame check.

## Implementation approach

L covers a first version: 90° butt corners, one bracket per open slot face, one STEP source. Miter corners, T-junction sides and bracket-to-bracket clash rules push it to XL.
1. New fittings.py. Make the Fitting an App::LinkPython link array: LinkedObject = the imported STEP body, with its own execute setting ElementCount and PlacementList. That keeps the STEP colours and stays light. The proposal's plan of separate App::Link children is not workable: adding objects during recompute is not allowed, and moving other objects' placements from execute breaks recompute ordering.
2. Properties:
   - Joints: PropertyLinkList.
   - Members: a hidden PropertyLinkList of the profiles, so Spin or size changes recompute the fitting after them. This is acyclic, because profiles never link to fittings. The proposal misses this link.
   - Rule: Inner faces / All open faces / Top and bottom.
   - SourceFrame: PropertyPlacement, set by calibration.
   - SlotOffset.
3. Placement maths per joint, using through_member(), ends_of() and passing_of():
   - For each butting member B with away direction a, the corner origin is vertex + a·(through.support(a) + Gap) + n·B.support(n).
   - n is each face normal of B that is ±through.z and points into the through member's length.
   - The legs run along a and n, with one bracket per cell centre (slot) of that face. Skip Closed faces.
   - 'Inner' means n points towards the centroid of the joint's members, or towards the panel side.
4. Calibration command: the user selects the bracket's inner corner vertex and its two contact faces, and SourceFrame is computed from them. No custom 3D preview is needed at first.
5. cutlist: a Hardware block, e.g. '24 × <STEP label>'. Imported labels are often file names, and part-number formats differ per vendor (item, Bosch Rexroth, Misumi, 80/20), so the row should also carry an article number the user types in.
6. Smoke test on the 2020 cube: 24 inner brackets, each touching its two profiles, with common() volume ≈ 0.

## Blockers and caveats

- STEP bodies vary (App::Part containers, arbitrary origins, several sub-bodies), so the calibration step decides whether this is usable.
- Each vendor's bracket needs its own slot-alignment offset.
- Bracket modelling was set aside because vendors publish STEP files. A plain hardware count per joint (part of joint-connection-machining) delivers most of the purchasing value at a fraction of the cost; placement adds the clash checks and a complete model.

## Risks

- STEP orientations vary wildly, so the calibration UX decides whether this is usable at all.
- Placements depend on the through decisions, so swapping a joint must move the brackets.
- The Fitting must link to the joints and never the reverse, to stay acyclic.

## Prior art

The FreeCAD Fasteners workbench auto-places library screws on holes, a similar placement concept.

## Modules

- new freecad/profile_builder/fittings.py
- `joints.py (read-only ends_of / through_member)`
- `feature.py (member_frame)`
- `cutlist.py`
- `commands.py`
- `check.py (from frame-check)`
