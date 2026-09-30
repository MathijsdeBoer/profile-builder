# Changelog

Most of this workbench was written by an AI model; see [AI_DISCLOSURE.md](AI_DISCLOSURE.md).

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
