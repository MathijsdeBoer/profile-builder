# Place the user's vendor STEP brackets at every joint

| | |
|---|---|
| Status | Partly done |
| Category | Joints & assembly |
| Effort | L (first estimate L) |
| Value | medium |
| Proposed from | printer-builder |

## Status

The first stage is done (branch `feature/brackets`). The object is called Brackets
(`ProfileBuilder::Brackets` in `brackets.py`, commands in `brackets_ui.py`), not Fitting: that name is
kept for the feet and castors of [end fittings](end-fittings.md).

Done:
- **Brackets object**: an App::LinkPython link array whose LinkedObject is the user's part. `execute`
  writes ElementCount and PlacementList only (ShowElement stays off, so no objects are created during
  recompute). The STEP colours are kept and no geometry is copied. With no positions it keeps one hidden
  element, because a link array without elements would show the part once at the origin.
- **Links, acyclic**: `Joints` plus the hidden `Members` (the profiles) and `FrameJoints` (the other
  joints) of the frame those joints are in: everything connected to them through joints. They are
  updated in `execute`, and `mustExecute` notices a joint or profile joined to the frame later, which
  touches nothing the object links to. Profiles and joints never link to it. `AllJoints` (set when the
  command is run without selecting joints) follows every joint in the document, also ones made later.
- **Placement**, at butt joints with square members:
  - between a profile ending at the joint and the one running through, on the side where that one
    continues (one side at a corner, both at a T-junction);
  - between two profiles ending square to each other against the same profile, if both ends reach the
    other's face. With 3030 posts and 2020 rails they do not, so that corner gets none.
  - One bracket per slot that lines up on both contact faces (within 0.5 mm), so a 40 x 40 profile of
    the 20 series gets two side by side. Closed faces get none; misaligned slots (a flat 2040 rail on a
    2020 post) and a profile with no face square to the other one get a note. That note names the Spin
    only when the Spin is not a multiple of 90°: in a frame turned about Z, the posts need a Spin to line
    up with the rails, although their own Spin is 0.
  - Which leg lies on which of two butting profiles is decided by direction (X, then Y, then Z, then the
    signed direction of the line), never by object names, also in a frame turned by 45°.
  - The brackets follow the profiles' faces, not the sketch lines, so Anchor, Spin and size changes are
    taken into account. A joint `Gap` is bridged (the bracket still sits on both faces); a butting end
    trimmed short of the other profile (negative Extend) leaves no corner, so it gets none.
  - `Rule`: "Inner faces" places brackets on the sides of a T-junction that face into the frame: where
    the profile running through carries on to another joint of the frame. A side where it ends freely
    (a stub, such as a post standing out above a rail) gets none, unless it ends freely both ways (posts
    standing on the floor); then the side where the rest of the frame reaches further gets them, or both
    when they reach equally far. The whole frame counts, not only the selected joints, so a shelf rail
    low in a closed frame or an off-centre middle post gets brackets on both sides. "All open faces"
    always places both.
- **Calibration** (`brackets.calibrate`, command **Calibrate bracket**, and **Brackets...** itself): the
  user picks the two contact faces, first the one on the profile that ends at the joint. The origin
  goes on the line where their planes meet, in the middle of the whole part's width, so a key split
  face or a chamfered corner does not matter. The corner vertex is optional and only checked. Picks
  work on a Part feature, a PartDesign body or a link, through an App::Part (as STEP imports are) and
  plain groups, and on a placed bracket. The part is the picked object, or the App::Part directly
  around it when that holds one bracket (a body, perhaps with its screws). A library of brackets or a
  whole design in an App::Part around it is passed over, and a part that is or holds a profile, joint,
  panel or Brackets object is refused, also by **Brackets...** without picks (a selected group of the
  frame's profiles). Picking the inner faces of the L is refused.
- `SwapLegs` and `SlotOffset` (along the bracket's width) adjust the frame.
- The **Brackets...** command hides the original part (the brackets show it in the corners); deleting
  the Brackets object shows it again unless another Brackets object places it.
- **Cut list**: a "Hardware (counted, not priced)" block with quantity, item (the part's label or a
  typed `Item`) and a typed `ArticleNumber`. A broken Brackets object is listed under Attention and not
  counted; its notes go to Notes.
- **Tests**: `tests/freecad_brackets.py`. The 400 mm 2020 cube gets 24 inner brackets, each touching
  exactly its two profiles, with no overlap between brackets and profiles or between brackets. The test
  bracket has slot keys, so a bracket off the slot centre would hit the lips. It is also written to a
  real STEP file and imported again (an App::Part holding the body, with its own Origin), calibrated
  through the import and placed on a second cube. The test also covers joint swaps, SwapLegs,
  SlotOffset, joint gaps, trimmed ends, anchors, Spin, size changes, two slots per face, stretched
  sketches, save/reopen, undo, rules at T-junctions (a goalpost, a closed frame with a low shelf, posts
  standing out above the top rail, an off-centre middle post, a joint added later on a stub), closed
  faces, misaligned slots, frames turned 30°, 45° and 135° about Z (made in two orders), nested
  App::Parts (a library of brackets, a whole design), a PartDesign body, miter joints, a missing part,
  AllJoints and the command flow (with a stand-in for the GUI selection, also refusing a selected group
  or link that holds the frame's profiles). End plates are tested at T-junctions, a cross, a 3D T and
  on a 2040 rail (with and without `PerSlot`), and claims, joint deletion, the style switch, the pick
  order and an old document are covered too.
- **Different brackets at different joints**: give each Brackets object its own joints. An all-joints
  object made by the command has `SkipClaimed` on, so it leaves out the joints other objects claim, and
  `ExcludedJoints` removes further joints from it (both only apply with `AllJoints`; edit `ExcludedJoints`
  in the property editor). Claims are decided from the joints alone: a butt joint, and for End plate
  objects only T-junctions. A Joints list filled by `AllJoints` (`JointsComputed`) claims nothing until the
  user edits it; FreeCAD dropping a deleted joint from the list is no edit (`onBeforeChange` keeps the old
  names). Single corners are switched off with `SkippedCorners` (a checklist in the task panel, from
  `Corners`/`CornerLabels`; the key names the joint, both profiles and the corner position, by object
  name). A skipped corner stays listed. Documents saved before `Corners` existed get the checklist filled
  when the task panel opens (`fill_corners`).
- **End plates** (`Style = "End plate"`, command **End plates...**): a flat plate on the outer face of a
  T-junction, one per side (or per slot with `PerSlot`). Calibrated from the face that lies on the profiles
  and the face at the end of the stem (`plate_frame`). Faces picked in the wrong order are refused (the
  contact face must be the larger one), and a bar end picked as the stem end gets a note. The bar's outer
  end sits flush with the through profile's far face (`PlateOffset` adjusts). Needs the two profiles' faces
  flush on that side (else a note). L corners get a note, `Rule` is ignored, and `SlotOffset` and
  `SwapLegs` do not apply. Where two profiles end on opposite faces of the through profile (a cross), no
  plates are placed, with a note. Where they end on two adjacent faces (a 3D T), each gets one plate, on
  the through profile's face away from the other, with a note.

Not done yet:
- Miter corners (noted in the object's Notes) and angled butt joints.
- Corners whose slots do not line up, such as a 2020 rail centred on the wide face of a 2040 post, get a
  note instead of a bracket. Offset brackets, or brackets that span a wider face, are not modelled.
- Flat L-shaped corner plates and gussets on the outside faces of an L corner. Only T-junctions get flat
  plates (End plates).
- A single plate over a cross of three or more members, and a preview for end plates.
- One Brackets object with several bracket parts, and per-series filters.
- Pricing and pack sizes of hardware, and hardware mass in the delivery weight: see
  [hardware BOM](hardware-bom.md), which should extend the Hardware block.
- Clash checks (bracket against panel, door or other bracket): see [frame check](frame-check.md). The
  brackets have a real shape (`Part.getShape(obj)`) for it.
- The "towards the panel side" variant of the inner rule, and a "Top and bottom" rule.
- A preview in the calibration step, and GUI testing of the two commands and the task panel (the
  commands were only run headless with a stand-in selection).
- A bracket kit whose bracket and fasteners are separate App::Parts inside one App::Part looks like a
  library of brackets, so calibrating on it places only the picked App::Part. Putting the kit's bodies
  in one App::Part places the whole kit.
- The "Inner faces" rule decides per T-junction side and adds no note for a side it leaves out; the
  count in the task panel and the cut list is for the brackets actually placed.

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

- new freecad/profile_builder/brackets.py (was planned as fittings.py) and brackets_ui.py
- `joints.py (read-only ends_of / through_member)`
- `feature.py (member_frame)`
- `cutlist.py`
- `commands.py`
- `check.py (from frame-check)`
