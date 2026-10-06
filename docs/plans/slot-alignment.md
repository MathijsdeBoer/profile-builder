# Aligning slots on adjoining profiles

**Status: Done**  
**Effort: S**  
**Value: Medium**

## Problem

Profiles with different cross-section grids can meet at a butt joint while their slot centre-lines miss each other.
For example, a 4040 section made from 20 mm cells has two slots across a face, while a 2060 post has three on its
wide face. Rotating the post may orient the right face but cannot remove the half-cell offset between those patterns.

## Delivered

- The **Align slots** command treats selected profiles as the ones to change and their unselected, butt-jointed
  neighbours as references.
- It chooses a section spin and local X/Y offsets that match the greatest number of slot centre-lines at applicable
  joints. The user sees the proposed spin, offsets and match count before applying them.
- `SectionOffsetX` and `SectionOffsetY` are created only when a profile needs a non-zero shift and are saved with
  that profile. They shift the section relative to its path; sketch edges stay in place, and joints, frame checks,
  carriage obstacles and profile geometry use the shifted section.
- Applying the result is one undoable document transaction. Equally good solutions use the other adjacent joint
  directions to prefer an inward shift where that can be inferred.

## Scope

The command works on profiles following sketch edges at existing butt joints. It does not move sketches, infer
unjointed contacts, or align miter joints. If several joints cannot all be matched, the report says how many
applicable joints align so the user can cancel or adjust the result.
