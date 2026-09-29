# Panel fit budget: thermal expansion and cut tolerance for sheets in slots and on faces

| | |
|---|---|
| Status | Done |
| Category | Analysis |
| Effort | S (first estimate S) |
| Value | medium |
| Proposed from | engineering |

## Status

Panels have a materials table (density and expansion follow the material, including trade names such as Plexiglas, Perspex, Lexan, Makrolon and Dibond), assembly/min/max temperatures, and a thermal fit check shown in the Panel dialog and the report notes.

## Problem

Heated 3D printer enclosures (50-60 °C for ABS/ASA), machine enclosures around motors or other heat sources, and frames in unheated halls or outdoors all see large temperature swings. Their sheets are often acrylic or polycarbonate, which expands about 3x more than aluminium. Sheets in slots then bind and bow, and screwed on-face sheets crack at the holes. The panel check only tests thickness against the slot opening.

## Proposal

Add a small pure-Python materials table with density and expansion coefficient: acrylic ~70-75e-6/K, PC ~65-70e-6/K, ACM ~24e-6/K, glass ~9e-6/K, aluminium 23e-6/K. Choosing a known Material fills Density and a new Alpha on the panel, keeping values the user has customised. The Engineering settings get the assembly temperature and the min/max operating temperatures. Panel info and the report notes then give the differential growth and the clearance needed.

Example: a 500 mm acrylic sheet in a chamber going from 20 to 60 °C grows about 1.0 mm more than the frame, 0.49 mm per side. That uses up the whole default 0.5 mm Clearance before any sheet cut tolerance, so the check says 'set Clearance ≥ 0.8 mm'.

At minimum temperature it checks that the sheet still overlaps the slot by a safe margin (InsertDepth minus shrinkage). For on-face panels it gives the hole oversize needed at the screw farthest from a fixed centre. An editable sheet cut tolerance (e.g. ±0.3 mm laser, ±1 mm saw) is part of the budget.

## What exists today

Partly exists. Panel has free-text Material (the pricing key, default 'Acrylic') and Density (1.19) that are independent of each other. Switching to Dibond, PC or glass leaves the density at 1.19 and makes panel mass and per-kg delivery wrong. _check_slot tests only thickness against SlotOpening - 0.2. Panel has no onChanged and no restore guard. No screw holes are modelled, so the on-face hole-oversize figure can only be a general number derived from the sheet size.

## Implementation approach

New pure-Python materials.py with MATERIALS = {name: (density g/cm³, alpha 1/K, typical cut tolerance mm)} for Acrylic, PC, PETG, ACM/Dibond, Glass, Aluminium and MDF. Test it with pytest (tests/test_materials.py).

panels.Panel:
- add_properties gets 'Alpha' (PropertyFloat, 1e-6/K) and 'CutTolerance'.
- Add onChanged(obj, prop) that returns early on `'Restore' in obj.State`. When Material changes to a known name, it updates Density and Alpha only if they still equal the previous material's table values, which keeps values the user customised. Store the previous name in a hidden PropertyString, because the proxy has no state (dumps returns None).

Thermal budget, from the panel's own properties or from the 'Engineering' group of pricing.FIELDS (AssemblyTemp, MaxTemp):
- Hot growth per side = (alpha_sheet - 23e-6) * dT * max(Width, Height) / 2 + CutTolerance/2. For 500 mm acrylic heated from 20 to 60 °C that is about 0.49 mm plus tolerance.
- panel_info and the report notes print 'set Clearance >= X mm' when Clearance is below the growth.
- The cold-shrink overlap check is cheap, but it practically never fires: slot overlap is about 4 mm against at most 0.4 mm shrink.

simple_panel: an editable QComboBox for Material with the table names as suggestions. It must stay a free string, because Material is the SheetPrices key.

## Blockers and caveats

None. The expansion coefficients depend on the grade, and the panels run cooler than the chamber air, so the numbers are worst-case and should be rounded to 0.1 mm. Most of the value comes from the materials table fixing density and mass. The thermal check itself is a modest rule of thumb. The temperatures are plain °C floats, so users who work in °F convert by hand.

## Risks

- Expansion coefficients vary by grade, and chamber temperature is not uniform (panels run cooler than the air). State the values as typical and round to 0.1 mm.
- Alpha must be added through add_properties without changing Density on restore.
- Auto-filling Density from Material must never overwrite a value the user set.

## Prior art

Enclosure build guides and the sheet makers' fabrication guides give rules of thumb. No CAD addon applies them to the actual sheet sizes.

## Modules

- new freecad/profile_builder/materials.py
- `panels.py`
- `simple_panel.py`
- `cutlist.py`
- `tests/test_materials.py`
