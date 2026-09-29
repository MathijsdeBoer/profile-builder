# Profile section from a sketch or vendor DXF

| | |
|---|---|
| Status | Planned |
| Category | Catalog |
| Effort | L (first estimate M) |
| Value | high |
| Proposed from | competitors |

## Problem

Vendors publish DXF or STEP sections for every profile (item, Bosch Rexroth, 80/20, Misumi, Motedis), but the catalog only approximates dimensions and has no inch series. Anyone using a vendor-specific shape (item 40x40 light, an 80/20 1010 or 1515 inch profile, an L profile, 2020 door or corner profiles) has to wait for catalog work. The same route covers radius profiles such as LR 40x40 or R40: instead of adding catalog entries, use the vendor's own drawing.

## Proposal

Add a SectionSource property to Profile: a link to a sketch or a DXF-imported shape. When it is set, execute builds the face from its closed wires (FaceMakerBullseye for holes), centres it on its bounding box, and bakes in the anchor offset as today, then extrudes and miters as usual.
- member_frame() uses the section's bounding box instead of Columns x CellSize, so joints and panel outlines keep working.
- Designation and product_key come from a SectionName property, typically the vendor's own part number (80/20 '1515', Misumi 'HFS5-2020'), whose format differs per vendor.
- Mass comes from the real area, which is more accurate than the simplified model.
A 'Profile from section...' command imports a DXF and creates the profile, one per selected edge.

## What exists today

FrameForge already builds custom profiles from sketches, so for anyone comparing the two workbenches this is parity. Confirmed that member_frame, describe, panels._check_slot and ProfileTaskPanel all assume Columns × CellSize catalog geometry.

## Implementation approach

A sketch-only version is M; the DXF import command makes it L.
1. feature.py:
   - Add SectionSource (App::PropertyLink) and a required SectionName through add_properties.
   - execute branch: take the linked shape's closed wires in its local coordinates (clear the sketch Placement), build the face with Part.makeFace(wires, 'Part::FaceMakerBullseye'), centre it on its BoundBox, translate by geometry.anchor_offset before extrusion as today, then use geometry.make_solid unchanged.
   - Skip apply_series_defaults and profiles.validate.
   - member_frame(): take the rect from the source BoundBox, which is cheap and needs no face build.
   - describe() and product_key use SectionName, so prices stay stable.
2. Joints: add SectionSource to SECTION_PROPS. The proposal misses a second step: also add the section source to joint.Sources in create_joints, and when SectionSource is set later. Editing the section sketch recomputes the profile but never touches its joints, so neighbours would keep stale trims.
3. panels._check_slot: refuse In-slot panels for custom sections (On face only).
4. ViewProviderProfile.setEdit: open the generic PropertyTaskPanel for custom-section profiles, because ProfileTaskPanel is catalog-driven.
5. commands.py: 'Profile from section…' creates one profile per selected edge. Later add DXF import via Import.readDXF or importDXF, with a step to choose the outer closed wire and handle units.
6. Smoke test: a 20 × 20 sketch with a bore on the cube edges gives the same trims as a catalog 2020. Editing the sketch to 30 × 30 must update the neighbours' trims.

## Blockers and caveats

- Joints and panels treat the section as its bounding rectangle. That is correct for the outer faces of L profiles and wrong on the curved side of radius profiles, so it needs documenting.
- Vendor DXFs contain dimensions, title blocks and splines, so the importer needs wire filtering and a way to choose the right wire. North American vendors such as 80/20 draw in inches and many DXFs carry no unit header, so the import step must let the user confirm the unit.

## Risks

- Joints treat the section as its bounding rectangle. That is right for rectangular families but wrong for L or radius shapes; document this.
- The in-slot panel check relies on catalog slot maths, so allow only On-face panels (or user-given slot positions) for custom sections.
- SECTION_PROPS must include SectionSource, so neighbouring joints recompute.
- product_key built from SectionName must stay stable, or saved prices are orphaned.

## Prior art

FrameForge Create Custom Profiles (any sketch as the section). item, Bosch Rexroth, 80/20, Misumi and Motedis provide downloadable CAD data per profile.

## Modules

- `feature.py (execute, member_frame, describe, product_key)`
- `geometry.py`
- `panels.py (_check_slot)`
- `taskpanel.py`
- `commands.py`
- `tests/freecad_smoke.py`
