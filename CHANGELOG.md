# Changelog

Most of this workbench was written by an AI model; see [AI_DISCLOSURE.md](AI_DISCLOSURE.md).

## Unreleased

Added:
- Box frame generator for closed cubes, sized by outside, inside-clear or centre-line dimensions, with
  separate post and rail profiles and a live cut-length summary. The requested size is kept on each side,
  also with different sections on different sides, and Check frame warns when the frame no longer
  measures that size. Rails wider than the posts in both directions are refused, because they would
  collide at the corners. Sizes are read in the unit the field shows, and fields you do not touch keep
  their exact value in every unit schema.
- Linear-carriage warnings, such as insufficient stroke, in the cut-list Notes block.
- Align slots: pick one slot floor on each of two profiles, and the first profile slides along its section
  (a saved section offset) until its slot lines up with the second, with or without a joint and without a
  confirmation dialog. Its sketch edge and spin stay as they are; joint trims follow the shifted section,
  so the length of a mitered or butting profile can change. Parallel and nearly parallel profiles are
  lined up across the picked face. Picks whose slots cannot line up by sliding are refused: a profile
  whose faces are not square to the slide direction, a face that points along it, and a slide that would
  push the first profile into the second.
- End plates: a Brackets style and an **End plates...** command for flat T plates on the outer faces of
  T-junctions, with their own calibration from two faces of the plate (picked in the wrong order, they are
  refused). A cross gets no plates and a 3D T one plate per butting profile, both with a note. SlotOffset
  and SwapLegs do not apply to end plates.
- Bracket control per joint and corner: a checklist of corners in the task panel (`SkippedCorners`),
  `ExcludedJoints`, and `SkipClaimed`, so an all-joints Brackets object leaves out the joints another
  Brackets object was given. Claims depend on the joints only: End plates claim only T-junctions, and a
  Joints list filled by AllJoints claims nothing until you edit it (deleting a joint is no edit).
  Brackets objects from older documents get their corner checklist when the task panel opens.
- The Tasks tab shows the commands that fit the current selection: create, joints and parts, Align slots,
  Brackets and End plates for two faces of a bracket part, Calibrate bracket for a placed bracket, and the
  report and checks.
- The "Profile Builder tools" toolbar is split into three: Joints and Alignment, Component Tools, and
  Output and Analysis.
- Panels accept profiles whose centre lines are not in one plane (different section sizes, or a section
  offset from Align slots), as long as one plane reaches every profile. In slot also needs that plane to
  pass through one of each profile's slots. PlaneOffset is measured from the middle of the part all
  sections share, so the order of the profiles does not matter. An On face sheet lies on the outermost
  face of all the profiles, and a missed slot suggests a PlaneOffset that suits every profile. Profiles
  that are nearly, but not exactly, in one plane are handled the same way, so their order does not
  matter either. An On face sheet more than 0.5 mm off a profile's face gives a fit warning for that
  profile (also in Check frame), and no holes are drilled along it.

Fixed:
- Deleting a profile refreshes its joints, including a manual through-profile choice.
- A profile whose path object, or one of whose joint sources, has an error is listed in the cut list's
  error block, instead of keeping its old length.
- Undo and redo of a profile edit update the butting profiles and the box-frame skeleton, also when the
  edit was recomputed after its transaction had been committed.

## 0.2.0 (2026-09-30)

Added:
- I-type series (Misumi-style slots) and weight classes: Light, Ultralight and Heavy.
- Section properties (Ix, Iy, Wx, Wy) from the modelled section.
- Stable piece marks (A1, A2, ... for profiles, P-1, ... for sheets) in the cut list, the stock plan, the
  tree and the 3D view, with a Renumber command.
- Currency and number formats taken from the system region; a CSV variant with decimal commas.
- Linear axis carriage: clear run, usable stroke and belt length (as metre ware in the cut list).
- Frame stiffness estimate: sideways and twist stiffness and natural frequencies, as a range between
  loose and stiff joints, with a baseline to compare variants.
- Bracket placement: your own bracket part in the corners of the joints, counted in the cut list.
- Panel fit checks: thermal expansion with a cut tolerance, a cold check that the sheet stays in its
  slots, and screw-hole play for sheets on the face. Materials set density and expansion.
- Panel fabrication: mounting holes on the slot centre lines, rounded corners, cutouts from a sketch, and
  DXF and SVG export per sheet.
- Check frame: one list of broken objects, overlaps, ends without a joint, duplicate profiles, panel fit
  problems, long pieces and more, with one-click fixes for duplicates and unjoined ends.
- Licence files, package metadata for the Addon Manager, automated tests on GitHub, and the groundwork for
  translations.

Fixed:
- The cut list silently left out profiles and panels with errors; they are now listed at the top and the
  total is marked incomplete.
- Mirror-image mitered pieces, and 1x2 versus 2x1 profiles, got separate cut-list rows.
- A hand-picked through profile was lost when profiles were renamed, deleted or copied.
- Undo and Cancel could switch joints to Manual and change lengths.
- Deleting a miter joint left the profiles mitered; a deleted sketch line gave a cryptic error.
- Frames turned 45° chose their through profiles by creation order.
- Ends that nearly meet silently got no joint; they are now reported.
- The CSV export came out garbled in spreadsheet programs that use a decimal comma.
- On FreeCAD 1.0, amounts lost their cents, and moments showed as energy ("J").

## 0.1.0 (2026-09-24)

First version: parametric B-type T-slot and V-slot profiles in several series (multi-cell sizes such as
2040 and 4080) with closed faces and anchors; profiles on sketch edges; butt joints with run-through
control, miter joints and T-junctions; sheet panels; prices per metre and m², cutting, delivery and tax;
stock bar planning; and the cut list as a spreadsheet and CSV.
