# Printable workshop pack: bar diagrams, saw set-up order, piece sketches, squaring diagonals

| | |
|---|---|
| Status | Planned |
| Category | Manufacturing & ordering |
| Effort | L (first estimate M) |
| Value | medium |
| Proposed from | printer-builder, purchasing-workshop, freecad-ux, competitors |

## Problem

At the saw and on the bench, a spreadsheet or CSV is a poor tool, and it is hard to print. There is no printable sheet that shows which piece goes where, the bars drawn to scale with their offcuts, a cutting order, or the angles and saw lengths of mitered pieces. Nothing gives target diagonals for squaring the frame during assembly.

## Proposal

A 'Build sheet' command generates a self-contained SVG/HTML page (A4 or US Letter, chosen from the system locale, printable to PDF from a browser) from the report. It is pure Python string building, so it can be tested without FreeCAD. It contains:
1. one to-scale diagram per bar, with piece marks, kerf, end trim and a hatched offcut;
2. a saw set-up list grouped by (miter setting, stop length) and ordered to minimise angle and stop-block changes ('Square, stop 380: cut 8x A from bars 1-3; 45° opposed, stop 420: 4x C');
3. for each unique piece, a side-view sketch with miter directions, start/end and machining positions;
4. an isometric line view with the marks and the outside dimensions;
5. target diagonals for each rectangular face, for squaring ('top frame, outside corners: 593.9 mm');
6. tick boxes, and an optional sticker sheet of mark labels.
A later option builds a TechDraw page instead: an isometric DrawViewPart, a DrawViewSpreadsheet of the cut list, one DrawViewBalloon per mark (placed with projectPoint at each profile's midpoint), small dimensioned side views for mitered groups, and title-block fields with mass, bar count and cost.

## What exists today

Partly covered in text form. The Stock plan block already lists each bar's pieces and offcut ('380 + 380 + 420', offcut) in the spreadsheet and CSV. stock.plan keeps (length, label) per piece, but build_report flattens it into a string and drops the labels. There are no piece marks, no machining data (both are unbuilt proposals) and no drawing or print output.

## Implementation approach

Revised effort L, up from M, for all six parts. M covers bar diagrams, the saw set-up list, diagonals for rectangular panels or a skeleton, and a mark table. The TechDraw variant is a separate L.

Which parts matter depends on how the profiles are bought. The saw-centric parts (bar diagrams, stop-block order, kerf) only matter in 'Stock bars' mode, for workshops and makers who cut full bars themselves. Buyers who order cut-to-size (from item, Misumi, 80/20, Motedis, a marketplace seller or a local shop) mainly use the marks, the assembly isometric and the diagonals.

Implementation:
- Keep report.stock unchanged (the smoke test asserts len(report.stock) == 2) and add report.plans = [(product, stock.Plan)], so the bars keep their (length, label) pieces.
- Marks: deterministic letters per cutlist.collect group key (the key is already sorted), computed in the report.
- If marks are also written to profiles, add a Mark property with the Prop_NoRecompute status. Any property write, even of the same value, marks a FeaturePython object as touched; this was verified in FreeCAD 1.1.
- New pure-Python buildsheet.py, tested with pytest:
  - bar_svg(plan, scale);
  - setup_order(pieces), grouping by (miter start, miter end, MiterAcross, saw length) and ordered to minimise angle changes;
  - diagonal(w, h);
  - HTML page assembly with print CSS.
- Stop lengths and diagonals follow FreeCAD's unit schema, so a shop that measures in inches reads inches at the saw instead of converting from mm.
- A thin FreeCAD-side collector turns member_frame plus Placement/Length into 3D segments for the isometric view; the projection itself is pure Python.
- Diagonals come from rectangular Panel outlines (panel_outline corners) and from the box skeleton if that lands. General 4-cycle detection in the joint graph is a later step.
- New 'Build sheet...' command in commands.py writes an HTML file next to the document. It does not use Qt printing, so it also runs headless.

## Blockers and caveats

- 'Which piece goes where' needs piece marks, which are not built.
- Hole and tapping positions need the unbuilt machining feature, so leave them out.
- Squaring diagonals for arbitrary frames need rectangle detection; there is no face list to take them from except panels or a generator skeleton.
- The TechDraw API differs between 0.21 and 1.1, and hidden-line views of detailed sections are slow.

## Risks

- Report.stock holds preformatted strings, and the smoke test checks len(report.stock). Refactor it to structured bars without breaking the spreadsheet/CSV output.
- This builds on piece marks, and on the machining feature for hole positions.
- Don't depend on Qt printing, so it also works headless.
- The TechDraw variant is about L on its own. Hidden-line removal on 100+ detailed sections is slow and cluttered, balloons overlap on dense frames, and the TechDraw Python API differs between 0.21 and 1.1.

## Prior art

OptiCut and CutList Optimizer print bar layout diagrams. FrameForge creates balloons on TechDraw views and exports all TechDraw pages as PDF. item Engineeringtool generates dimensioned isometric drawings.

## Modules

- new freecad/profile_builder/buildsheet.py
- `cutlist.py (structured stock bars and marks in Report)`
- `stock.py`
- `commands.py`
- `init_gui.py`
- `optional new drawing.py (TechDraw, GUI only)`
- `tests`
