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
- `slot_alignment.direct_align_slots()` lines the slots up across the cross product of the two profile axes, or,
  for parallel and nearly parallel profiles (`joints.PARALLEL`), along the target's picked face, by changing the
  target's section offset only. Its spin and sketch edge stay as they are. Joint trims follow the shifted section,
  so the length of a mitered target, or of a profile butting against it, can change.
- It refuses picks whose slots cannot line up by sliding, with a message and without moving anything:
  - a target or reference whose section X or Y is not along the slide direction (within `joints.PARALLEL`, about
    2.6°), such as a profile turned by Spin;
  - a picked face whose slots do not sit side by side along the slide direction (the face points along it);
  - a slide that would push the target into the reference: the overlap of the two profiles' outer boxes
    (`check._envelope`) would grow by more than `check.CLASH_VOLUME`. This covers parallel profiles standing side
    by side and picked on faces that look the same way, and side-by-side profiles skewed past `joints.PARALLEL`.
    Overlap that is already there, at an unjoined corner, does not count.
- `SectionOffsetX` and `SectionOffsetY` are created only when a profile needs a non-zero shift and are saved with
  that profile. They shift the section relative to its path; sketch edges stay in place, and joints, frame checks,
  carriage obstacles, panels, brackets and profile geometry use the shifted section.
- Applying the result is one undoable document transaction.
- The older joint-based solver (`slot_alignment.plan()`, which searched spins and offsets that match as many slots
  as possible at butt joints and preferred an inward shift on ties) has been removed; the command never used it.

## Scope

The command moves only the section offset of the first profile picked. It does not move sketches or rotate
profiles. It does not check that the two slots face each other, only that they can be lined up by sliding.
