# Section cache and change-only writes for fast recompute of large frames

| | |
|---|---|
| Status | Done |
| Category | FreeCAD integration & UX |
| Effort | S (first estimate S) |
| Value | medium |
| Proposed from | freecad-ux |

## Status

`geometry.make_section` caches sections (LRU, 64 entries) and returns copies. The Profile dialog writes only changed values.

## Problem

Benchmark in freecadcmd 1.1 with 120 profiles (ten 400 mm cubes): a full recompute takes 1.6 s for 2020 and 3.6 s for 4040 Light. make_section() alone costs 6.7 ms and 20.7 ms per profile, against about 1 ms for the extrusion, so rebuilding identical sections accounts for roughly 50-70% of the time. The task panel recomputes on every debounced change, so editing 100+ profiles on edges freezes the GUI for seconds per keystroke. ProfileTaskPanel.apply() also writes every property on every object on each tick, changed or not, which retriggers onChanged and joint touches.

## Proposal

Memoise geometry.make_section() with a small LRU cache. The key is the rounded dimension tuple plus cols, rows, style, closed faces, bore, corner holes and anchor, and the cache returns face.copy(). A frame typically has only 1-3 distinct sections, so almost every profile hits the cache. In ProfileTaskPanel.apply(), write only the values that changed, as simple_panel already does. Optionally set a coarser default Deviation/AngularDeflection on ViewProviderProfile, because the arcs in chambers and bores make heavy meshes. Add a smoke check that cached and uncached faces have identical Area, plus a timing line in the test output.

## What exists today

There is no cache. A benchmark in FreeCAD 1.1.3 confirms the proposal's numbers:
- make_section takes 7.2 ms (2020) and 20.8 ms (4040 Light), against about 0.9-1.5 ms for the extrusion and 0.3-0.5 ms for face.copy();
- 120 profiles in cubes recompute in 1.55 s and 3.53 s.
simple_panel.PropertyTaskPanel.apply already writes only changed values. ProfileTaskPanel.apply writes every property of every object on each tick, and a same-value write still marks a FeaturePython touched (verified). So every tick recomputes all edited profiles, and via SECTION_PROPS and touch_joints_of, their joints and neighbours.

## Implementation approach

Effort S confirmed. Small frames of 12-30 profiles, such as printer frames, enclosures and workbenches, recompute in under 0.5 s anyway. The gain is real for the multi-edge create panel and for large frames such as machine guarding, conveyors and multi-station workstations, which often use heavier 40 and 45 series sections.

Implementation:
- In geometry.make_section, add a module-level LRU (OrderedDict, about 64 entries) keyed by (tuple(sorted(d.items())), cols, rows, style, frozenset(closed), bool(center_bore), corner_holes, anchor). Keying on the whole dimension dict means fields added later are included automatically, which removes the stale-key risk.
- Insert the face only after validate() passes and the face is built and translated, so errors are never cached.
- Always return face.copy(), never the cached object. make_solid's miter branch already copies, and extrude does not modify the face.
- Add geometry.clear_cache() for tests.
- In taskpanel.ProfileTaskPanel.apply, compare each value with the current property before setattr, as simple_panel does (current.Value if hasattr), including the Label update.
- Only change ViewProviderProfile Deviation after measuring in the GUI.
- freecad_smoke: cached and uncached Area/Volume are equal for a customised dimension dict, and a hit counter increases for a 12-profile cube. Print one timing line.

## Blockers and caveats

None. The only rule: cached faces are shared state and must never be handed out or modified in place.

## Risks

- The cache key must include every input that affects the shape, including dimension fields added later, or a customised profile gets a stale section.
- Shapes must be copied, because make_section translates its face in place.
- The GUI tessellation cost was not measured (headless run only).

## Modules

- `geometry.py`
- `taskpanel.py`
- `feature.py`
- `tests/freecad_smoke.py`
