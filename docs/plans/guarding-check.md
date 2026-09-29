# Guarding check aid (ISO 13857 distances, floor gap, guard height)

| | |
|---|---|
| Status | Planned |
| Category | Analysis |
| Effort | L (first estimate L) |
| Value | low |
| Proposed from | industrial |

## Problem

For machine guards (under CE marking in Europe, and under similar rules elsewhere), the mesh or gap size of the infill sets the minimum distance to the hazard. The guard height relative to the hazard and the gap under the guard must also meet the standard. Builders check this by hand for each panel, and a later change (a moved panel, a different mesh, a lower fence) silently invalidates the check.

## Proposal

Panels get Infill (Solid / Mesh / Perforated / Slotted) and OpeningSize properties, added through the backward-compatible add_properties pattern. A HazardZone object links to any solid, such as a robot cell envelope. A pure-Python guarding.py holds user-editable distance tables loaded from JSON, so pytest can cover it. ISO 13857 is the reference in Europe and much of the world, but North American builders often work to ANSI B11.19 or the OSHA guard-opening table, which is in inches, so each table names its standard and unit rather than the code assuming ISO.

For each guard panel it reports:
- the distance from panel to hazard (distToShape) against the distance required for its opening;
- the bottom gap from the panel's lowest point to the floor;
- the guard top height against the hazard height (reach over);
- the gaps between panel edge and frame, from Clearance, Margin and the joint Gap.
The results form a 'Guarding check' block in the report, with pass/fail per panel, and failing panels are highlighted.

## Implementation approach

1. guarding.py (pure, pytest): the table structure plus lookups, with values loaded from user-editable JSON in <UserAppData>/ProfileBuilder.
2. panels.Panel.add_properties: add Infill (Solid / Mesh / Perforated / Slotted) and OpeningSize.
3. A HazardZone FeaturePython that links to any solid.
4. Report time:
   - Distance = panel.Shape.distToShape(hazard.Shape)[0].
   - Floor gap = panel BoundBox.ZMin minus a floor Z setting.
   - Guard top = panel BoundBox.ZMax, compared with the hazard height.
   - Edge gaps from Clearance, Margin and joint Gap.
5. Results go in a 'Guarding check' block in cutlist, with the failing panels highlighted.

## Blockers and caveats

- ISO 13857 and ANSI B11.19 values are copyrighted, so the user has to enter them.
- Liability: this must be labelled a design aid.
- Panels are flat polygons with no mesh frames or real slot insertion, so distances are approximate.
- This serves professional machine builders; hobby frames and enclosures rarely need it.

## Risks

- Liability: label it clearly as a design aid, not a risk assessment or a conformity check (CE or any other).
- The standard's tables are copyrighted, so the user enters the values, or only the table structure ships with a few widely published values and a citation.
- Panel geometry is simplified (slot insertion depth, mesh frames), so distances are approximate.
- Of limited relevance to hobby builds such as printer enclosures.

## Prior art

Guarding vendors (item, Bosch Rexroth, Axelent) print ISO 13857 distance tables in their catalogues. No known FreeCAD tool checks them against the model.

## Modules

- new freecad/profile_builder/guarding.py
- `panels.py`
- `cutlist.py`
- `commands.py`
- `tests/test_guarding.py`
