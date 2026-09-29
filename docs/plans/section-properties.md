# Section properties from the modelled section (Ix, Iy, W, principal axes, centroid offset)

| | |
|---|---|
| Status | Done |
| Category | Analysis |
| Effort | S (first estimate S) |
| Value | medium |
| Proposed from | engineering, printer-builder, competitors |

## Status

Ix, Iy, Wx and Wy of the modelled section are read-only Info properties and show in the Profile dialog. Supplier comparison values are not added.

## Problem

Choosing between 2020, 2040 standing or flat, 3030 Light or 4040 Ultralight is a stiffness question, but the workbench only reports area and kg/m. Users look up I values on supplier pages, and those may not match the variant they modelled (closed faces, weight class, custom dimensions). Nothing tells them that a 2040 lying flat is 3.5x more flexible than one standing on edge. It gives most of what curated datasheet values would, without curating any data, because the section face already exists.

## Proposal

execute() already builds the section as one Part.Face. Read face.MatrixOfInertia (about the centroid, checked), PrincipalProperties and CenterOfMass, and store these as read-only Info properties:
- Ix and Iy in cm⁴ about the local axes (with Spin taken into account);
- principal moments and angle;
- section moduli Wx/Wy from the vertex farthest from the centroid;
- radius of gyration and centroid offset from the profile axis.
Measured on the current catalog: 20-6 1x1 gives 0.74 cm⁴, 2040 gives 5.09 / 1.46 cm⁴, 40-8 1x1 gives 11.05 cm⁴, and closing the Top face of a 2020 raises Ix by 27% and moves the centroid 1.5 mm off the axis.

The task panel shows the values rounded to 2 significant figures and labelled 'modelled'. For horizontal members it adds one plain line, e.g. 'lying flat: 3.5x less stiff under gravity', using the orientation from member_frame.

Optionally, users can type their supplier's Ix/Iy/kg/m per product key into the existing per-document product maps. The report then shows 'modelled 0.74, supplier 0.70 (-5%)', which calibrates the numbers and flags series dimensions that don't match the supplier. This also exposes a catalog oddity: Heavy is identical to Standard for 20-5, 20-6 and 30-8 (same area and I), because Standard has no corner holes there.

## What exists today

Before this was built, only SectionArea, MassPerMeter and Mass existed. The numbers are verified in FreeCAD 1.1 on geometry.make_section faces:
- 20-6 1x1: Ix = Iy = 0.741 cm⁴.
- 2040: 5.092 and 1.458 cm⁴, a ratio of 3.49, so '3.5x' is right.
- 40-8 1x1: 11.055 cm⁴.
- 2020 with ClosedTop: Ix = 0.943 cm⁴ (+27%), centroid y = 1.52 mm.
- A12 is 0 for symmetric sections. PrincipalProperties['Moments'] returns (polar, I1, I2) for a planar face.
Heavy equals Standard for 15-3, 20-5, 20-6, 30-6 and 30-8, with identical areas, because apply_weight('Heavy') only zeroes corner holes and chambers these Standard sections don't have. The 40/45 series differ, e.g. 40-8 is 746 vs 879 mm².

## Implementation approach

feature.Profile.add_properties: add read-only (mode=1) Info properties under a 'Section' group: Ix, Iy (PropertyFloat, cm⁴), Wx, Wy (cm³), IPrincipal1/2 and PrincipalAngle, and CentroidOffset (PropertyDistance or a vector).

In execute, the section `face` already exists:
- m = face.MatrixOfInertia, which is about the centre of mass. Ix = m.A11/1e4 and Iy = m.A22/1e4.
- Take the principal values and axes from face.PrincipalProperties.
- W = I / c, with c from face.BoundBox relative to face.CenterOfMass.
- The centroid offset is CenterOfMass minus the anchor pivot (geometry.anchor_offset), because the anchor is baked into the face.
Spin doesn't change section values; it only matters for world orientation.

taskpanel._update_info: show 2-significant-figure values tagged 'modelled'. For a horizontal member, use feature.member_frame(obj) to project gravity (world Z) onto the local axes, I_g = Ix*gy² + Iy*gx². Compare it with max(Ix, Iy) to print 'lying flat: 3.5x less stiff'.

Inch suppliers such as 80/20 list I in in⁴ and W in in³ (1 in⁴ = 41.62 cm⁴). The Info properties are plain floats in cm⁴, so the dialog should also show in⁴ when FreeCAD's unit schema is imperial, and supplier values should be entered with their unit.

Optional supplier values: an 'Ix'/'Iy' column in pricing_ui keyed by product_key, and a deviation note in the report.

Old documents: add_properties runs under _restoring, and the values stay 0 until the next recompute. The task panel should compute them on the fly or say 'recompute to update'.

Smoke test: 2040 Ix/Iy ratio 3.4-3.6.

Separately, fix or document the Heavy = Standard duplication (README or WEIGHT_TIPS), because the catalog currently offers a class that changes nothing for five series.

## Blockers and caveats

None. Modelled sections run heavy on 40/45, so show 2 significant figures and 'modelled' provenance. The optional supplier-value columns make it M.

## Risks

- Modelled sections run heavy on the 40/45 sizes (README), so I reads a few percent (20 series) to about 20% (40-8) optimistic. Show 2 significant figures and 'modelled' provenance, never 4 decimals.
- A12 in MatrixOfInertia follows the inertia-tensor sign convention, so take the principal axes from PrincipalProperties.
- New properties must go through add_properties under the _restoring guard.
- Custom dimensions can make the numbers look authoritative when they are not.

## Prior art

Vendor datasheets (item, Bosch Rexroth, Misumi, 80/20, Motedis) list Ix/Iy per profile. FreeCAD exposes MatrixOfInertia on faces, but no workbench presents it for extrusions, and FrameForge does not compute section properties.

## Modules

- `feature.py (Info properties via add_properties, execute)`
- `taskpanel.py`
- `cutlist.py`
- `pricing.py / pricing_ui.py (optional supplier values)`
- `README.md (Accuracy)`
- `tests/freecad_smoke.py`
