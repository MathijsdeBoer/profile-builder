# Linear axis on a profile: carriage, usable stroke and belt length

| | |
|---|---|
| Status | Partly done |
| Category | Design & modelling |
| Effort | L (first estimate M) |
| Value | low |
| Proposed from | industrial |

## Status

The proposal is built (2026-09-29), with the gaps listed at the end. The code is in the new modules `linear.py` (document object), `stroke.py` (pure-Python rules), `metreware.py` (metre ware in the cut list) and `linear_ui.py` (command and task panel):

- **Carriage object** linked to a rail profile and one of its faces (Top/Bottom/Left/Right as on the section). It has CarriageLength, EnvelopeWidth, EnvelopeHeight, Wrap (how far it reaches back around the rail's sides), EndStopLength, RequiredStroke, Run, and a position given in percent of the stroke or as a distance. Expressions work on the position, for simple motion checks.
- **Clear run from what really blocks the envelope**, as corrected below:
  - Every other profile and panel, plus the objects listed in Obstacles, is tested against the envelope swept along the rail: first a bounding box in the rail's frame, then a boolean with the envelope prism.
  - A member butting against another face does not block, unless the carriage wraps around that face. A T-junction member on the carriage's face splits the rail into runs; Run picks one (0 = the longest). A panel in the face's slot blocks the whole rail, which is reported as an error.
  - Mitered rail ends make the face under the carriage shorter (the inner face of a frame) or longer (the outer face) than the axis; the part of the face under the carriage's whole width decides.
- **Outputs**: ClearRun, Stroke, Travel, Limits (what ends the run), Runs (all runs) and Warning. Warning covers a stroke below RequiredStroke, a carriage that does not fit, and a position outside the stroke. Warnings go to the report view, the Check frame findings and the cut-list Notes block; the tree's description shows the stroke. Lengths are formatted in the user's unit system.
- **No cycles**: the carriage links to the rail and, through a Neighbours list (global-scope links, hidden in the property editor), to the profiles and panels whose bounding box reaches its swept envelope. It therefore recomputes after them, for example when the posts change from 40 to 45, and it never writes to them.
  - Members outside the envelope are not dependencies. A broken member elsewhere in the document (a deleted sketch line, a panel that is too thick) does not stop the carriage, and a member that rides on the carriage, such as a gantry beam standing on it, can follow it by an expression or on a sketch that does.
  - A profile or panel that moves into the envelope marks the carriage for recompute (`member_moved`, called when its Placement changes, which it also does at the end of each recompute). During a recompute FreeCAD recomputes such a carriage in its second pass, so it is found in the same recompute. New profiles and panels made by the workbench also mark carriages for recompute.
- **Shape**: a placeholder box, or the shape of a linked Body (for example an imported STEP) in carriage coordinates, adjusted with BodyPlacement.
- **Belt drive**:
  - With BeltItem set (for example "GT2 6 mm"), the carriage gives BeltLength = 2 × PulleyCentres + π × pitch diameter + ClampAllowance, rounded up to whole teeth of BeltPitch.
  - PulleyCentres 0 means the clear run, and the pitch diameter comes from PulleyDiameter or from PulleyTeeth × BeltPitch / π.
  - A belt without a pulley size is an error, so the cut list never lists a belt of the wrong length.
- **Metre ware in the cut list**:
  - Belts get their own "Metre ware" block (Qty, Item, Length each, Price, Per, Cost, Used by), grouped by item and length, and a "Metre ware" cost line that only appears when there is some.
  - Prices are stored in a new MetrePrices map of the Pricing object, edited in the Pricing dialog. A price is per metre, or has a unit: "0.75/ft", "0.10/in", "1.20/yd", with a decimal point or comma.
  - A carriage with a belt and an error is listed under Attention, and the total is marked incomplete.
- **GUI**: a Carriage command (click the face it runs on; a selected solid becomes the Body) and a task panel with live preview, which shows the position in percent or as a distance.
- **Tests**: `tests/test_stroke.py` covers the rules and the belt formula, and `tests/test_metreware.py` the price parsing. `tests/freecad_linear.py` covers:
  - a rail between two posts, including 40 to 45 mm posts;
  - T-junctions on the carriage face, on another face, and with wrap;
  - a through rail on posts; the inner and outer faces of a mitered ring and of a vertical mitered frame; a single miter on a free rail (so a sign error fails);
  - only the members that reach the envelope are linked: a broken profile elsewhere does not stop the carriage or drop its belt, a member moved onto the rail (directly, or through the line it follows) is found in the same recompute, and a gantry beam and a second carriage on it follow the carriage by an expression;
  - make_carriage keywords in any order (Position before PositionMode);
  - an obstacle, a panel in the slot and a linked body;
  - save and reload, undo, the carriage task panel and a user's own description;
  - belts in the cut list, the CSV and the spreadsheet, prices per foot, a missing price, a missing pulley size, and the Pricing dialog.
  - carriage warnings in the frame check and cut-list Notes block.

Not done yet:
- **Belts**: pulleys of different sizes, closed-loop belts sold by tooth count, and buying in whole metres or fixed lengths are not handled. The cost is the exact length times the price. Belt mass is not added to the delivery weight.
- **Other shapes**: only profiles and panels are found automatically. A Draft array of profiles, a bracket or a motor mount must be listed in Obstacles.
- **Members inside the envelope cannot follow the carriage**: such a member is a dependency of the carriage, so an expression or attachment that makes it follow the carriage would be a cycle, and FreeCAD refuses it. What rides on the carriage has to sit outside the envelope, for example a gantry beam standing on it (touching counts as outside).
- **Simplifications**: two carriages on one rail do not block each other. The envelope is always centred on the face, and one end stop length applies to both ends.
- **Units**: the task panel shows lengths in mm, like the other simple panels, and the metre-ware block's length column is in mm, like the rest of the cut list (see international-units-and-formats.md).
- **Link**: the body is shown by copying its shape into the carriage (like a Draft clone), not through an App::Link.
- **GUI testing**: the command, face picking and both dialogs inside FreeCAD's GUI were not run. The dialog logic is tested headless.

## Problem

Fixtures, gantries, pick-and-place units and printer axes run a carriage along a profile. The builder needs the profile length for a required stroke (stroke plus carriage plus end stops), and the belt length for the drive; both are hand calculations. When the frame changes, say posts from 40 to 45 or an end joint swapped, the butting members take up more of the run and the usable stroke drops without any warning.

## Proposal

A Carriage object linked to a profile and one of its faces, with CarriageLength, EndStopLength and Position (mm or percent).
- It computes the clear run between the faces of the members at each end, from JointStartOffset/JointEndOffset and, for a through member with ExtendThrough, its support().
- From the clear run it gives the stroke, and it warns when that is below an optional RequiredStroke.
- It places a placeholder block, or an App::Link to the user's carriage STEP, at Position on the face using member_frame. Position can be driven by expressions for simple motion checks.
- Optional belt drive: pulley pitch diameter and clamp allowance give an open-belt length (2C + πd for equal pulleys). The belt appears in the cut list as metre ware (e.g. 'GT2 6 mm') with a price per metre, or per foot where suppliers sell it that way.

## What exists today

The first stage (see Status) follows the corrected approach below. Before it, nothing existed. Deriving the stroke from JointStartOffset/JointEndOffset and support() is too simple. Which members block the carriage depends on the face it runs on and on how far the carriage wraps around the profile; V-wheel plates wrap 2-3 faces. A member that butts against a different face of a through rail doesn't block, and T-junction members in the middle of the rail do. There is also no metre-ware or hardware line type for a belt in cutlist or pricing.

## Implementation approach

New linear.py with a Carriage Part::FeaturePython:
- Properties: Rail (PropertyLink to a profile, not a sub-link, so frames are used and shapes never are), Face (enumeration from profiles.FACES), CarriageLength, EnvelopeWidth/Height, EndStopLength, Position, RequiredStroke.
- Clear run: from feature.member_frame(rail), build the swept envelope box of the carriage section along the rail axis. Intersect its AABB with the BoundBoxes of the other profiles and panels, taking candidates from the rail's joints (ends_of, passing_of) plus AABB-overlapping neighbours, and project them onto the rail axis to find the free interval around Position.
- Stroke = free interval - CarriageLength - 2*EndStopLength. Warn when it is below RequiredStroke, and never write back to the rail, to avoid a cycle.
- Shape: a placeholder box, or App::Link to a user STEP body placed with member_frame.

Belt:
- open-belt length L = 2C + π·d, rounded up to the tooth pitch;
- reported in a new 'Hardware / metre ware' block in cutlist._blocks, priced via a new pricing.FIELDS map.

Also: a command, init_gui registration, and a smoke test with a rail between two posts.

## Blockers and caveats

No FreeCAD blocker. Carriages vary too much (V-wheel vs profile rail) for more than an envelope. The hardware line concept doesn't exist yet. Printer and CNC builders usually take motion geometry from an existing design, and machine builders who buy complete linear units size them in the vendor's configurator, so the value is low compared with the effort.

## Risks

- The carriage depends on the profile, so it must never write back to the profile's Length, which would create a cycle. RequiredStroke can only warn, or suggest ExtendEnd.
- CoreXY / H-bot belt layouts are out of scope.
- Carriages differ a lot (V-wheels vs profile rail guides), so this is only a parametric envelope.

## Prior art

item, Bosch Rexroth and Misumi linear unit configurators compute length from stroke. OpenBuilds publishes carriage sizes for its V-slot gantry kits, and 80/20 for its linear bearings that run on its profiles.

## Modules

- new freecad/profile_builder/linear.py
- `feature.py`
- `joints.py`
- `cutlist.py`
- `pricing.py`
- `commands.py`
