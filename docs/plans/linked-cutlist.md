# Cut list that counts App::Link copies, arrays and assemblies

| | |
|---|---|
| Status | Planned |
| Category | Manufacturing & ordering |
| Effort | L (first estimate M) |
| Value | medium |
| Proposed from | industrial, freecad-ux |

## Problem

cutlist.collect() only loops over doc.Objects and checks feature.is_profile; panels are collected the same way. The freecad-ux lens checked this in FreeCAD 1.1 with one profile, one App::Link to it, a 4-element Link array and a 3-element Draft link array. The report counted 1 piece where the model has 9. An assembly document that links a saved frame twice counted 0. So if you reuse a module through links or arrays, or build the machine in an Assembly that links the frame file, you get a short order and a cost that is too low, with no warning.

## Proposal

Replace collect() with a walk from doc.RootObjects that multiplies quantities as it goes down. It resolves:
- App::Link (LinkedObject, ElementCount, and links into other documents);
- Draft/Link arrays, by element count, without counting the hidden base again;
- App::Part, Assembly and group containers.
Panels are walked the same way, and later fittings and hardware too. The pricing panel's product list uses the same walker, so linked products get price rows. An ExcludeFromCutList bool on Profile and Panel covers reference geometry and stock already on the shelf. Optionally, a 'Where' column (e.g. 'Frame.FCStd x2') or grouping by top-level assembly (base frame, guard left, guard right). Links to missing documents raise a warning. A smoke test covers the Link, array and two-document cases above.

## What exists today

Confirmed missing. Probe in FreeCAD 1.1 with one profile, one App::Link, an App::Link with ElementCount=4 and a Draft ortho link array (Count=3): feature.is_profile() is False for all of them, and build_report counts 1 piece. The Draft link array is a Part::FeaturePython with `Count`, not `ElementCount`. The proposal's 'walk from doc.RootObjects' is wrong for this codebase:
- Profiles referenced by a Panel (Panel.Profiles) have the panel in their InList, so they are not roots (probe: ring profiles not in RootObjects).
- A link's source is not a root either.
A root-down walk would drop exactly the pieces it is meant to count. Headless, Draft did not hide the array base (Visibility stayed True), so rules based on visibility behave differently in freecadcmd and in the GUI.

## Implementation approach

In cutlist.py, replace collect()'s loop with `instances(doc)` that yields (profile, multiplicity, where).

1. Every profile in doc.Objects counts once, unless it is the Base of a Draft array or ExcludeFromCutList is set. Detect arrays by Proxy.Type in ('Array', 'PathArray', 'PointArray', ...) and use their `Count`.
2. Then add link instances:
   - for each App::Link / App::LinkElement / Draft link array whose getLinkedObject(True) resolves to a profile, or to a container (App::Part, DocumentObjectGroup, Assembly::AssemblyObject) that holds profiles, add max(1, ElementCount or Count), minus hidden elements in VisibilityList;
   - recurse through nested links, and through linked containers into other documents (link.LinkedObject.Document), multiplying as it goes;
   - skip LinkElement children when their parent array is counted.
3. Links into documents that are not open: FreeCAD partially loads them with the assembly. Warn when getLinkedObject() is None.

Add `ExcludeFromCutList` (PropertyBool) via Profile.add_properties and Panel.add_properties; it is added on restore under the existing guard. Apply the same walk to panels, and to pricing_ui._fill_tables so linked products get price rows.

Start with an S step: a report warning 'N App::Link / array copies of profiles are not counted', which removes the silent short order right away.

For the smoke test, build the probe scenario plus a second document with an App::Part holding a cube, linked twice from an assembly document.

## Blockers and caveats

No FreeCAD blocker. The hard part is exact counting rules (link source in the same document, array bases, LinkElements, Assembly joints hiding sources) and testing each one, which puts it at L rather than M. A single frame drawn straight from sketches rarely uses links or arrays. Multi-module machines, repeated workstations or guard panels, and frames placed in an Assembly do, and there a short order goes unnoticed until the parts arrive.

## Risks

- Double counting: an original that is also a link target, hidden array bases, or hidden source objects in assembly documents. The rules must be exact.
- Links into documents that are not open need loading.
- The rule for what 'the order' is must be clear: the active document plus everything it links to.
- A Where column changes the report rows, the CSV and the spreadsheet columns.

## Prior art

The FreeCAD 1.1 Assembly workbench BOM (Assembly::BomObject) walks links and sub-assemblies but knows nothing about lengths or saw cuts. item Engineeringtool and Bosch Rexroth MTpro produce one order list for a whole multi-module machine.

## Modules

- `cutlist.py`
- `pricing_ui.py`
- `feature.py (ExcludeFromCutList)`
- `panels.py`
- `commands.py`
- `tests/freecad_smoke.py`
