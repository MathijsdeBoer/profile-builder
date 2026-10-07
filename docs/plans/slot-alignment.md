# Aligning slots on adjoining profiles

**Status: Done**  
**Effort: S**  
**Value: Medium**

## Problem

Profiles with different cross-section grids can meet at a butt joint while their slot centre-lines miss each other.
For example, a 4040 section made from 20 mm cells has two slots across a face, while a 2060 post has three on its
wide face. Rotating the post may orient the right face but cannot remove the half-cell offset between those patterns.

## Delivered

- The **Align slots** command takes exactly two Ctrl-selected slot floors, one per profile. The first profile is
  moved, the second is the reference, and the change applies at once without a dialog. No joint is required.
- The slots are lined up across the cross product of the two profile axes (across the face normal for parallel
  profiles) by changing the target's section offset only; its spin, sketch edge and length stay as they are. A
  target turned so that direction is not along its section X or Y is refused with a message.
- slot_alignment.plan() still offers the joint-based search (spin and offsets matching as many slots as possible at
  butt joints) as an API, but the command no longer uses it.
- `SectionOffsetX` and `SectionOffsetY` are created only when a profile needs a non-zero shift and are saved with
  that profile. They shift the section relative to its path; sketch edges stay in place, and joints, frame checks,
  carriage obstacles and profile geometry use the shifted section.
- Applying the result is one undoable document transaction. Equally good solutions use the other adjacent joint
  directions to prefer an inward shift where that can be inferred.

## Scope

The command moves only the section offset of the first profile picked. It does not move sketches, rotate profiles
or check that the slots face each other.
