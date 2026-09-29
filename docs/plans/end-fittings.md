# End fittings: levelling feet, castors, floor brackets and end caps with height compensation

| | |
|---|---|
| Status | Planned |
| Category | Joints & assembly |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | industrial |

## Problem

A workstation or guard is designed to an envelope, such as a worktop at 900 mm or a guard top at 2000 mm. Feet add 60-120 mm and castors more, so posts cut to the sketch come out too long unless each one is trimmed by hand. The cut list also leaves out the feet, castors and end caps, and the end tapping each post needs for a foot (M8 or M10 on metric profiles, 1/4-20 or 5/16-18 on inch profiles). Forgetting to order that tapping with cut-to-size pieces is a common mistake with any supplier: the pieces arrive untapped.

## Proposal

A new fittings.py, modelled on joints.py. A Fitting sits at a path-edge vertex: its Sources link to the path object, and profiles link to it through new StartFitting/EndFitting properties, so there is no cycle. Fitting types come from a user-editable table: foot M8 D60 with nominal height and adjustment range, castor, floor bracket, end-cap thickness.

Profile.execute asks fittings.adjustment() for an offset, the same way it asks joints.adjustment(). At a free end, the post is trimmed so the foot base lands on the sketch vertex, which is the floor. The fitting checks its thread against Series.tap and Series.tappable(weight), a check that today only appears as task-panel text.

The fitting draws a simple disc-and-stud placeholder, or an App::Link to the user's STEP file for that type, oriented with member_frame. The cut list gets a Hardware block (qty x price per piece) and 'M8 tapped, start' in the machining column. Fitting positions also give the support polygon for the mass and tipping check.

## What exists today

Partial workaround: ExtendStart/ExtendEnd already let a user trim a post by a foot height by hand (negative extend). Series.tap and tappable() exist but only appear as task-panel text (taskpanel._update_info). There are no fittings, no machining column and no hardware rows.

## Implementation approach

Effort M holds only if fittings are profile properties; separate Fitting objects with STEP App::Links would be L.

Revised value medium, down from high: on cube frames (printer frames, enclosures, many machine bases) the post bottom is a joint vertex, where the proposal itself says to stack rather than trim. Height compensation therefore helps mainly free-ended legs: tables, stands, and workstations whose lowest rails sit above the floor. The tapping check and the counts are useful on every frame, and they overlap with hardware-bom.

Implementation (drop the linked Fitting object):
- Add to Profile.add_properties:
  - StartFitting/EndFitting (App::PropertyString with a fitting type name, '' for none);
  - StartFittingHeight/EndFittingHeight, copied from the fitting table when the type is set (the same pattern as apply_series_defaults copying dimensions onto the object, so later table edits don't silently change documents);
  - FittingMode (Trim / Stack).
- New fittings.py (pure Python): a table from resources defaults plus <UserAppData>/ProfileBuilder/fittings.json, as {name: {thread, height, adjust, kind}}.
- Profile.execute: at an end with no joint and mode Trim, extend[i] -= height. At joint ends, never trim, and report the overall height instead.
- Validation: thread != series.tap or not series.tappable(weight) raises a ValueError (the object shows the error) or fills a read-only Notes property.
- Placeholders: a separate 'Fittings' display object that links to the profiles, drawing a cylinder compound at each fitted end from Placement/Length. Profiles never link to it, so there is no cycle.
- cutlist:
  - the collect() key includes the fitting names, so tapped pieces group separately;
  - PIECE_HEADER gains 'Machining' ('M8 tapped, start'), which means extending write_spreadsheet's cols 'ABCDEFGHI' to 10 columns;
  - fitting counts feed the hardware block.

## Blockers and caveats

- Heights and threads are vendor data; ship examples in both metric and inch sizes. Threads are compared as names ('M8', '1/4-20'), as Series.tap already stores them.
- The trim-or-stack ambiguity at cube corners is inherent and must be an explicit per-profile mode.
- The cut-list column change alters CSV and spreadsheet layout, and the smoke test reads cell A2.

## Risks

- On a cube frame, a post's bottom end is usually also a joint vertex, with the bottom rails butting against it. Trimming only the post would misalign it with the rails. So at an end that also has a joint, the fitting should stack on the flush end and report the overall height instead of trimming, or the whole base sketch should be raised. This needs a clear explanation.
- The fitting properties must not trigger dimension resets on restore; follow the _restoring pattern.

## Prior art

Vendor catalogues (item, Bosch Rexroth, 80/20, Misumi) list foot heights and the threads they need. FrameForge has no end fittings.

## Modules

- new freecad/profile_builder/fittings.py
- `feature.py (StartFitting/EndFitting, execute)`
- `cutlist.py`
- `pricing.py`
- `pricing_ui.py`
- `commands.py`
- `init_gui.py`
