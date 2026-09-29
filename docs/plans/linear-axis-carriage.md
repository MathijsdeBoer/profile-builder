# Linear axis on a profile: carriage, usable stroke and belt length

| | |
|---|---|
| Status | Partly done |
| Category | Design & modelling |
| Effort | L (first estimate M) |
| Value | low |
| Proposed from | industrial |

## Status

First stage done (2026-09-29), in the new modules `linear.py` (document object), `stroke.py` (pure-Python rules) and `linear_ui.py` (command and task panel):

- **Carriage object** linked to a rail profile and one of its faces (Top/Bottom/Left/Right as on the section). It has CarriageLength, EnvelopeWidth, EnvelopeHeight, Wrap (how far it reaches back around the rail's sides), EndStopLength, RequiredStroke, Run, and a position given in percent of the stroke or as a distance. Expressions work on the position, for simple motion checks.
- **Clear run from what really blocks the envelope**, as corrected below:
  - Every other profile and panel, plus the objects listed in Obstacles, is tested against the envelope swept along the rail: first a bounding box in the rail's frame, then a boolean with the envelope prism.
  - A member butting against another face does not block, unless the carriage wraps around that face. A T-junction member on the carriage's face splits the rail into runs; Run picks one (0 = the longest). A panel in the face's slot blocks the whole rail, which is reported as an error.
  - Mitered rail ends shorten the face under the carriage.
- **Outputs**: ClearRun, Stroke, Travel, Limits (what ends the run), Runs (all runs) and Warning. Warning covers a stroke below RequiredStroke, a carriage that does not fit, and a position outside the stroke. Warnings also go to the report view, and the tree's description shows the stroke. Lengths are formatted in the user's unit system.
- **No cycles**: the carriage links to the rail and, through a Neighbours list (global-scope links, hidden in the property editor), to the other profiles and panels. It therefore recomputes after them, for example when the posts change from 40 to 45, and it never writes to them. New profiles and panels made by the workbench mark carriages for recompute, so they are found at once.
- **Shape**: a placeholder box, or the shape of a linked Body (for example an imported STEP) in carriage coordinates, adjusted with BodyPlacement.
- **GUI**: a Carriage command (click the face it runs on; a selected solid becomes the Body) and a task panel with live preview, which shows the position in percent or as a distance.
- **Tests**: `tests/test_stroke.py` covers the rules. `tests/freecad_linear.py` covers:
  - a rail between two posts, including 40 to 45 mm posts;
  - T-junctions on the carriage face, on another face, and with wrap;
  - a through rail on posts, and a mitered ring;
  - an obstacle, a panel in the slot and a linked body;
  - save and reload, undo, and the task panel.

Not done yet:
- **Belt drive**: pulley pitch diameter, clamp allowance and belt length, and a metre-ware block in the cut list priced per metre or per foot.
- **Members added by other means** (copy and paste, Draft arrays, scripts that do not use `make_profile` / `make_panel`) are only found when the carriage next recomputes for another reason.
- **Simplifications**: two carriages on one rail do not block each other. The envelope is always centred on the face, and one end stop length applies to both ends.
- **Units in the task panel**: it shows lengths in mm, like the other simple panels (see international-units-and-formats.md).
- **Reporting**: the frame check and the cut list do not list carriage warnings.
- **GUI testing**: the command, face picking and the task panel inside FreeCAD's GUI were not run. The task panel logic is tested headless.

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
