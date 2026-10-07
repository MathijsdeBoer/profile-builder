"""Selection-aware command groups for the Tasks tab.

FreeCAD asks every task watcher whether to show itself each time the selection changes, and hides them
while a task dialog is open. A watcher only lists commands that are registered elsewhere, so this module
only decides which ones fit what is selected.
"""

from dataclasses import dataclass

import FreeCAD as App

from . import brackets, feature, joints, slot_alignment

translate = App.Qt.translate


@dataclass(frozen=True)
class Selection:
    profiles: int = 0  # profiles selected as a whole or by a face that is not a slot floor
    joints: int = 0
    brackets: int = 0
    slots: int = 0  # slot floors picked on profiles
    other: int = 0
    total: int = 0


def summarize(selection):
    """Count what is selected, from (object, sub-element names) pairs."""
    profiles = joint_count = bracket_count = slots = other = 0
    entries = list(selection)
    for obj, names in entries:
        if feature.is_profile(obj):
            picked_whole = False
            for name in (names or ("",)):
                if name.startswith("Face"):
                    try:
                        slot_alignment.picked_slot(obj, name)
                    except ValueError:
                        picked_whole = True  # a click on the profile's own face means the profile
                    else:
                        slots += 1
                else:
                    picked_whole = True
            profiles += picked_whole
        elif joints.is_joint(obj):
            joint_count += 1
        elif brackets.is_brackets(obj):
            bracket_count += 1
        else:
            other += 1
    return Selection(profiles, joint_count, bracket_count, slots, other, len(entries))


def current_selection():
    import FreeCADGui as Gui
    return summarize((s.Object, tuple(s.SubElementNames)) for s in Gui.Selection.getSelectionEx())


def _frame_selected(sel):
    return (sel.profiles or sel.joints) and not sel.slots


def _create(sel):
    return not sel.profiles and not sel.joints and not sel.brackets and not sel.slots


def _report(sel):
    doc = App.ActiveDocument
    return not sel.total and any(feature.is_profile(o) for o in doc.Objects)


def _align(sel):
    # The command refuses anything but two slot floors, so only offer it for exactly that.
    return sel.slots == 2 and not (sel.profiles or sel.joints or sel.brackets or sel.other)


def _brackets(sel):
    return bool(sel.brackets)


class ContextWatcher:
    def __init__(self, title, commands, wanted):
        self.title = title
        self.commands = list(commands)
        self._wanted = wanted

    def shouldShow(self):
        if App.ActiveDocument is None:
            return False
        return bool(self._wanted(current_selection()))


def watchers():
    return [
        ContextWatcher(translate("ProfileBuilder", "Create"),
                       ["ProfileBuilder_Create", "ProfileBuilder_BoxFrame"], _create),
        ContextWatcher(translate("ProfileBuilder", "Line up slots"),
                       ["ProfileBuilder_AlignSlots"], _align),
        ContextWatcher(translate("ProfileBuilder", "Join and trim"),
                       ["ProfileBuilder_Joints", "ProfileBuilder_RunThrough", "ProfileBuilder_SwapJoint"],
                       _frame_selected),
        ContextWatcher(translate("ProfileBuilder", "Add to the frame"),
                       ["ProfileBuilder_Panel", "ProfileBuilder_Carriage", "ProfileBuilder_Brackets"],
                       _frame_selected),
        ContextWatcher(translate("ProfileBuilder", "Brackets"),
                       ["ProfileBuilder_CalibrateBracket"], _brackets),
        ContextWatcher(translate("ProfileBuilder", "Report and check"),
                       ["ProfileBuilder_CutList", "ProfileBuilder_ExportCutList", "ProfileBuilder_CheckFrame",
                        "ProfileBuilder_FrameStiffness", "ProfileBuilder_ExportPanels", "ProfileBuilder_Pricing"],
                       _report),
    ]
