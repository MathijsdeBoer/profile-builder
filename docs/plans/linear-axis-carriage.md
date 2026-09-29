# Linear axis on a profile: carriage, usable stroke and belt length

| | |
|---|---|
| Status | Planned |
| Category | Design & modelling |
| Effort | L (first estimate M) |
| Value | low |
| Proposed from | industrial |

## Problem

Fixtures, gantries, pick-and-place units and printer axes run a carriage along a profile. The builder needs the profile length for a required stroke (stroke plus carriage plus end stops), and the belt length for the drive; both are hand calculations. When the frame changes, say posts from 40 to 45 or an end joint swapped, the butting members take up more of the run and the usable stroke drops without any warning.

## Proposal

A Carriage object linked to a profile and one of its faces, with CarriageLength, EndStopLength and Position (mm or percent).
- It computes the clear run between the faces of the members at each end, from JointStartOffset/JointEndOffset and, for a through member with ExtendThrough, its support().
- From the clear run it gives the stroke, and it warns when that is below an optional RequiredStroke.
- It places a placeholder block, or an App::Link to the user's carriage STEP, at Position on the face using member_frame. Position can be driven by expressions for simple motion checks.
- Optional belt drive: pulley pitch diameter and clamp allowance give an open-belt length (2C + πd for equal pulleys). The belt appears in the cut list as metre ware (e.g. 'GT2 6 mm') with a price per metre, or per foot where suppliers sell it that way.

## What exists today

Not implemented. Deriving the stroke from JointStartOffset/JointEndOffset and support() is too simple. Which members block the carriage depends on the face it runs on and on how far the carriage wraps around the profile; V-wheel plates wrap 2-3 faces. A member that butts against a different face of a through rail doesn't block, and T-junction members in the middle of the rail do. There is also no metre-ware or hardware line type for a belt in cutlist or pricing.

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
