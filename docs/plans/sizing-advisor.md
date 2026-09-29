# Profile sizing advisor: the cheapest profile and orientation that passes a load check

| | |
|---|---|
| Status | Planned |
| Category | Analysis |
| Effort | L (first estimate M) |
| Value | low |
| Proposed from | engineering, competitors, printer-builder |

## Problem

The real decision is cost against stiffness: for this span, at the prices of the supplier actually used, is 2040 on edge or 3030 Light cheaper? Today that means trial and error with the Series combo and re-running the report.

## Proposal

From a Load, or from a member plus a target deflection, list the catalog variants that meet the limit. Candidates are series x size x weight class x orientation (Spin 0/90 for non-square profiles), filtered by default to the slot system already used in the document so nuts and brackets stay compatible. Each row shows:
- the deflection range, e.g. '2040: 0.42 mm, 2080: 0.07 mm, 4040 Light: 0.09 mm';
- kg/m and price/m, from pricing.lookup on ProfilePrices, falling back to kg/m when there is no price.
The list is sorted by cost per piece, including the effect on the stock-bar plan in 'Stock bars' mode. An Apply button sets Series/Weight/Columns/Rows/Spin on the member, or on all members with the same product key, in one transaction.

Section properties for the catalog variants come from a generated table, so the advisor doesn't build hundreds of faces interactively: tools/make_section_table.py (next to make_icons.py) writes resources/sections.json, and a test checks that it is current.

## What exists today

None of its prerequisites exist in the repo: no loads.py, no beams.py, no section-properties, no member-load-check. Only SectionArea, MassPerMeter and Mass are computed. Vendor datasheet Ix/Iy values are not in the catalog, and this feature depends on Ix/Iy, even if they are computed from the model.

## Implementation approach

Revised effort L, up from M: the advisor is about M on top of a Load object and a beam check, which are each M to L and not built.

Revised value low: most builders pick a size by convention or by the slot system they already stock (20 and 30 series for small machines, 40 and 45 series for workstations and guarding), and the approximate sections make close rankings unreliable.

Implementation, if pursued:
- tools/make_section_table.py (next to make_icons.py) computes Ix and Iy from the modelled face (Part.Face.MatrixOfInertia is about the centroid) for every SERIES x sizes x weight x style. It writes resources/sections.json with a hash of the catalog dimensions.
- A pytest test compares that hash with profiles.SERIES, so a stale table is caught without FreeCAD.
- New pure-Python advisor.py:
  - deflection = k F L^3 / (E I) for simple-support and cantilever cases;
  - filter candidates by the target, restricted to the slot systems already in the document;
  - sort by price/m from pricing.lookup(ProfilePrices, key), falling back to kg/m and saying so.
- Build candidate product keys without a document object, by replicating feature.describe in pure Python.
- Apply in one transaction, setting Series/Weight/Columns/Rows/Spin. Warn that apply_series_defaults resets customised dimensions and that joints.touch_joints_of changes neighbouring cut lengths.

## Blockers and caveats

- Depends on the unbuilt Loads and beam-check features.
- The sections are approximate (README 'Accuracy'), so computed Ix/Iy can differ noticeably from vendor values, and near-tie rankings are not trustworthy.
- Most candidates will have no price in the document's ProfilePrices, so the ranking degrades to mass.
- The catalog has only metric series, so users of inch systems (80/20 10 and 15 series) get no candidates in their own slot system until inch series exist.

## Risks

- Depends on section-properties and member-load-check.
- Changing Series intentionally resets dimensions, so customised members must be excluded or warned about.
- Section changes trigger joints.touch_joints_of and move neighbouring trims, so the advisor must say that other cut-list pieces change too.
- When most candidates have no price, the ranking is mass-based, and the list should say so.

## Prior art

Vendor selectors (item Engineeringtool and Machining Tool, Misumi) filter by load but use only their own catalog and list prices, not the prices the builder pays or the stock plan. Nothing in FreeCAD does this.

## Modules

- `loads.py`
- `beams.py`
- `pricing.py`
- `stock.py`
- `profiles.py`
- new tools/make_section_table.py
- new freecad/profile_builder/resources/sections.json
- `commands.py`
- `tests/test_profiles.py`
