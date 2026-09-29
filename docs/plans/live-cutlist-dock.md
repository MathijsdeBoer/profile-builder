# Live cut list dock with select-from-row and colour-by-group

| | |
|---|---|
| Status | Planned |
| Category | FreeCAD integration & UX |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | freecad-ux |

## Problem

The Cut list spreadsheet is a snapshot that goes stale after any edit, and nothing links a row back to the 3D model. When the list says '9 x 380' but you expected 8, there is no way to find the odd one. It is also hard to check whether a frame you expect to be symmetric really is.

## Proposal

A dockable panel (QDockWidget) shows the report grouped by product, then by length and miters. It refreshes after each document recompute through a debounced document observer. Clicking a group selects and zooms to its profiles; double-clicking opens the multi-selection in the property editor. The piece marks (from the piece-marks feature) and the pricing estimate line appear there too. A 'Colour by' toggle (Product / Cut group / Joint role / Errors) temporarily recolours the profiles and restores their colours when switched off.

## What exists today

The Cut list spreadsheet is a snapshot with no link back to the model. collect() keeps only one representative object per group, so it has to return every member. There is no piece-marks feature, so the proposed Mark column has nothing to show yet.

## Implementation approach

1. New cutlist_dock.py: a QDockWidget holding a QTreeWidget (product -> group rows with qty, length, saw length, miters and cost, plus the estimate line), built from build_report and from a collect() variant that returns all objects per key. Show lengths through FreeCAD's unit schema (Quantity.UserString) and costs through pricing.format_money, so users on an imperial schema see inches and everyone sees their own currency and number format.
2. Refresh: App.addDocumentObserver with slotRecomputedDocument and slotActivateDocument restarts a 300 ms single-shot QTimer. Remove the observer when the dock or the document closes.
3. Click: Gui.Selection.clearSelection(), then addSelection() for every object in the group, then Gui.SendMsgToActiveView('ViewSelection'). Double-click keeps that multi-selection for the property editor.
4. commands.py: a toggle command, registered in init_gui.
5. GUI test: a freecad.exe script driven by QTimer that logs the row count and the selection size.
Put Colour by in phase 2:
- Setting ViewObject.ShapeColor marks the document as modified.
- The colours are written to GuiDocument.xml if the user saves.
- They land on the undo stack while a task-panel transaction is open.
So either restore the colours in slotStartSaveDocument and never recolour during a transaction, or draw a temporary Coin overlay instead.

## Blockers and caveats

Recolouring without touching the document is what raises the effort. Without Colour by, this is S-M.

## Risks

- Recolouring must not end up in saved files or on the undo stack.
- Refreshing on every recompute must be debounced for large frames.
- The Mark column depends on the piece-marks feature.

## Prior art

The Woodworking addon has colour-based cut-list reports (not verified). FreeCAD's own spreadsheet has no link back to the selection.

## Modules

- new freecad/profile_builder/cutlist_dock.py
- `cutlist.py`
- `feature.py`
- `commands.py`
- `init_gui.py`
