# Joints task panel with live preview, auto-join on insert and a Preferences page

| | |
|---|---|
| Status | Planned |
| Category | FreeCAD integration & UX |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | freecad-ux |

## Problem

Joints... is a modal QInputDialog with six text choices. The user picks a style blind, sees the result afterwards, and undoes to try another. The modal dialog is also why GUI tests have to monkeypatch it (CLAUDE.md). Each insert on sketch edges needs a separate Joints step that is easy to forget, and the pieces then overlap. Defaults are hidden 'last used' values, and panels always start as 3 mm acrylic at 1.19 g/cm³, which is wrong for Dibond or polycarbonate enclosures, and for 1/8 in (3.175 mm) sheet where sheet is sold in inch sizes.

## Proposal

Replace the dialog with a task panel that follows the repo pattern: open a transaction, apply live on a debounce, and implement Cancel as abortTransaction(). It has style and rule combos, a gap field and the ExtendThrough option, and shows the resulting cut groups ('8 x 380, 4 x 420') before OK. An 'Auto-join on insert' option makes QuickProfile and ProfileTaskPanel.accept call create_joints on new edge profiles with the default style. A Preferences page (Gui.addPreferencePage), under the existing Mod/ProfileBuilder parameter group, sets:
- default series, weight, slot style and joint style;
- auto-join and profile colour;
- panel material, thickness and density;
- joint marker size and visibility.

## What exists today

Partly exists:
- Double-clicking a joint already opens a live-preview PropertyTaskPanel (JOINT_FIELDS: Type, ThroughRule, Through, ExtendThrough, Gap) with transaction and Cancel. What is missing is the batch creation step, which is a modal QInputDialog.getItem over JOINT_STYLES in commands.CreateJoints.
- 'Last used' defaults are already stored under PARAMS ('Mod/ProfileBuilder') by ProfileTaskPanel.accept, but there is no preference page to see or edit them.
- Panels always start as Acrylic, 3 mm, 1.19 g/cm³ (panels.add_properties).

## Implementation approach

New joints_panel.py:
- __init__ opens a transaction, calls joints.create_joints(doc, targets, 'Butt', rule) once and keeps the returned joints.
- Changing the style combo only sets Type/ThroughRule/Gap/ExtendThrough on those joints. Miter goes only on joints with len(ends_of)==2 and no passing_of, mirroring create_joints' simple_corner rule. The joints are never recreated, so names and the undo stack don't churn.
- On a debounced QTimer: recompute, then show the cut groups from cutlist.collect(doc) ('8 x 380, 4 x 420') and any invalid profiles.
- Cancel calls abortTransaction().

Auto-join:
- after make_profile in QuickProfile.Activated and ProfileTaskPanel.accept, call create_joints on new + existing profiles;
- give create_joints a `free_ends_of` parameter so only the new profiles' free ends are clustered, but all profiles are used for T-junction detection. This avoids joining old ends the user left free on purpose.

New preferences.py: a class with form/loadSettings/saveSettings registered with Gui.addPreferencePage(PageClass, 'Profile Builder'). Register it at module level in init_gui, not in Workbench.Initialize, so it exists before the workbench is activated. It reads and writes the same PARAMS keys (Series, Weight, SlotStyle, joint style, AutoJoin, panel Material/Thickness/Density, joint PointSize). make_panel and ViewProviderJoint read those keys. The page needs no unit setting of its own: lengths are stored in mm, and showing them in inches is a job for FreeCAD's unit schema (Gui::QuantitySpinBox), for all task panels at once.

GUI test scripts no longer need to monkeypatch QInputDialog.

## Blockers and caveats

None. Auto-join must not join ends the user left free on purpose, which needs the small create_joints refactor above. Registering the preference page must not import GUI modules into the App-only layer.

## Risks

- A live preview that creates joints must reuse the joints it created rather than recreate them on each change; otherwise the undo history and object names churn.
- Auto-join on insert must leave existing joints alone, which create_joints already does.

## Prior art

The live-preview task panels already in this repo: taskpanel.py, simple_panel.py and pricing_ui.py.

## Modules

- `commands.py`
- new freecad/profile_builder/joints_panel.py
- new freecad/profile_builder/preferences.py
- `taskpanel.py`
- `panels.py`
- `init_gui.py`
