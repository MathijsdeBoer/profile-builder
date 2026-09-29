# Feature plans

These plans come from a brainstorm on 2026-09-28, run as a Claude Code workflow (see `AI_DISCLOSURE.md`).
Six AI agents proposed ideas from different angles: a 3D-printer builder, an industrial machine builder,
purchasing and the workshop, FreeCAD UX, competitors and vendor tools (including FrameForge), and
engineering analysis. A seventh merged them, and three more checked each one against the code as of
commit `ead3f7d` and FreeCAD 1.1: whether it already exists, the effort, the value and the blockers. The
effort below is the checked figure. On 2026-09-29 the plans were rewritten for the audience the
workbench is meant for (hobbyists and professionals, metric and imperial regions, suppliers worldwide),
because the first version had been written around one hobbyist and one supplier, and their value was
re-rated for that audience.

Effort: S = under a day, M = 1-3 days, L = about a week, XL = more.

## Suggested order

Already done: the bug fixes and quick wins from the review (section properties, section cache, panel materials and thermal fit, piece marks), the first international fixes, and first stages of
the frame stiffness estimate, the linear axis carriage and bracket placement.

1. [Addon Manager readiness: licence, metadata, CI and translations](addon-manager-readiness.md) (M, high value)
2. [International use: units, imperial profiles and translations](international-units-and-formats.md) (L, high value)
3. [Frame check: one list of clashes, unjoined ends and other silent order errors](frame-check.md) (L, high value)
4. [Box frame generator sized by outside, inside or centre-line dimensions](box-frame-generator.md) (L, high value)
5. [Connection method per joint, with derived machining: end taps, access holes, counterbores](joint-connection-machining.md) (L, high value)
6. [Hardware BOM from joints and panels, with pack sizes and T-nut preload warnings](hardware-bom.md) (L, high value)

## Design & modelling

| Feature | Status | Effort | Value |
|---|---|---|---|
| [Box frame generator sized by outside, inside or centre-line dimensions](box-frame-generator.md) | Planned | L | high |
| [Enclosure doors: sheet doors and framed guard doors with hinge gaps and a swing check](enclosure-doors.md) | Planned | XL | medium |
| [Linear axis on a profile: carriage, usable stroke and belt length](linear-axis-carriage.md) | Partly done | L | low |

## Joints & assembly

| Feature | Status | Effort | Value |
|---|---|---|---|
| [Connection method per joint, with derived machining: end taps, access holes, counterbores](joint-connection-machining.md) | Planned | L | high |
| [Angled butt joints for diagonal braces](angled-butt-joints.md) | Planned | M | medium |
| [End fittings: levelling feet, castors, floor brackets and end caps with height compensation](end-fittings.md) | Planned | M | medium |
| [Place the user's vendor STEP brackets at every joint](step-bracket-placement.md) | Partly done | L | medium |

## Manufacturing & ordering

| Feature | Status | Effort | Value |
|---|---|---|---|
| [Cheapest-buy stock planner: mixed bar lengths, packs, per-product mode, offcut inventory](cheapest-stock-planner.md) | Planned | L | high |
| [Hardware BOM from joints and panels, with pack sizes and T-nut preload warnings](hardware-bom.md) | Planned | L | high |
| [Panel fabrication: slot-aligned mounting holes, rounded corners, cutouts, DXF/SVG export](panel-fabrication.md) | Planned | L | high |
| [Accessories from the model: end caps, slot covers, panel seals and tagged STEP parts](accessories-from-model.md) | Planned | M | medium |
| [Supplier order export with article numbers, part-number templates and cut-length rules](order-export.md) | Partly done | M | medium |
| [Order snapshots and change orders ('what changed since I ordered?')](order-revisions.md) | Planned | M | medium |
| [Stable piece marks in the cut list, stock plan and 3D view](piece-marks.md) | Partly done | M | medium |
| [Named supplier price books and side-by-side quote comparison](supplier-price-books.md) | Planned | M | medium |
| [Cut list that counts App::Link copies, arrays and assemblies](linked-cutlist.md) | Planned | L | medium |
| [Printable workshop pack: bar diagrams, saw set-up order, piece sketches, squaring diagonals](workshop-pack.md) | Planned | L | medium |
| [Miter plane in the piece key, and a workshop-readable miter description](miter-plane-key.md) | Done | S | medium |

## FreeCAD integration & UX

| Feature | Status | Effort | Value |
|---|---|---|---|
| [Addon Manager readiness: licence, metadata, CI and translations](addon-manager-readiness.md) | Planned | M | high |
| [International use: units, imperial profiles and translations](international-units-and-formats.md) | Partly done | L | high |
| [Joints task panel with live preview, auto-join on insert and a Preferences page](joints-task-panel-preferences.md) | Planned | M | medium |
| [Live cut list dock with select-from-row and colour-by-group](live-cutlist-dock.md) | Planned | M | medium |
| [Reference integrity: renames, deleted joints and deleted edges](reference-integrity.md) | Done | M | high |
| [Section cache and change-only writes for fast recompute of large frames](section-cache.md) | Done | S | medium |

## Analysis

| Feature | Status | Effort | Value |
|---|---|---|---|
| [Frame check: one list of clashes, unjoined ends and other silent order errors](frame-check.md) | Partly done | L | high |
| [Mass, centre of gravity, tipping and foot loads](mass-cog-tipping.md) | Planned | M | medium |
| [Deflection and stress check per member, shown as a range between support bounds](member-load-check.md) | Planned | M | medium |
| [Racking and bracing audit for frames](racking-audit.md) | Planned | M | medium |
| [Guarding check aid (ISO 13857 distances, floor gap, guard height)](guarding-check.md) | Planned | L | low |
| [Profile sizing advisor: the cheapest profile and orientation that passes a load check](sizing-advisor.md) | Planned | L | low |
| [Frame stiffness and natural-frequency model with joint-stiffness bounds and variant comparison](frame-stiffness-model.md) | Partly done | XL | low |
| [Panel fit budget: thermal expansion and cut tolerance for sheets in slots and on faces](panel-thermal-fit.md) | Done | S | medium |
| [Section properties from the modelled section (Ix, Iy, W, principal axes, centroid offset)](section-properties.md) | Done | S | medium |

## Catalog

| Feature | Status | Effort | Value |
|---|---|---|---|
| [Profile section from a sketch or vendor DXF](section-from-sketch-dxf.md) | Planned | L | high |

## Bugs found during the review

The checks also turned up bugs in the existing code. All are fixed and covered by tests:

- The cut list silently left out profiles with errors, so an order could come up short.
- Mirror-identical mitered pieces got separate rows, because the miter signs follow the drawing direction.
- A swapped joint stored its choice by label, so renaming profiles lost it and pieces could overlap.
- Deleting a miter joint left the profiles mitered.
- A profile whose sketch line was deleted failed with a cryptic error.
- Inserting a size twice on the same sketch silently doubled the profiles.
- Ends that nearly meet (e.g. 0.2 mm apart) silently got no joint and overlapped.
- The stock plan lost which piece was which.
- The CSV came out garbled in Excel with a decimal comma.
- A panel's density did not follow its material.
- The spreadsheet writer silently dropped columns beyond the ninth.

A second, adversarial review of those fixes found 21 more defects (all fixed, each with a test):

- Undo or Cancel could switch joints to Manual and change lengths.
- A joint whose hand-picked profile was deleted or copied silently picked another profile later.
- A profile whose sketch line was deleted stayed in the cut list at its old length.
- One deleted line made the Joints command fail for the whole document.
- The decimal-comma CSV rounded totals to 6 digits.
- The Panel dialog wrote the old material's density back.
- Material names could match the wrong material (e.g. "glass-clear PETG"). Unknown materials got
  acrylic's expansion, which caused false thermal warnings.
- The thermal check ignored the room that a shallow insert depth leaves.
- A 1x2 and a 2x1 profile ("on side") were grouped inconsistently.
- Quick insert did nothing while the Cut list spreadsheet was selected.
- The CSV export's marks differed from the ones on the model.
- A user's own description starting with "Mark " was overwritten.
- No near-miss warning appeared when the other end already had a joint.
- Swap failed right after a rename.
- Older documents showed zero section properties and could keep stale miters.
