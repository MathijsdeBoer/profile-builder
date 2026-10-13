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
    brackets: int = 0  # Brackets objects, selected or picked on one of their brackets
    slots: int = 0  # slot floors picked on profiles
    part_faces: int = 0  # faces picked on objects outside the frame, such as a bracket part
    parts: int = 0  # the objects those faces are on
    other: int = 0
    total: int = 0


# Whether a face is a slot floor, by (document, profile, face, shape hash), for the faces picked last
# time. Faces are added to a selection one at a time, so each one is classified only once.
_slot_floors = {}
# (key, summary) of the selection the watchers asked about last; they all ask on every change.
_last = [None, None]


def _target(root, sub):
    """(object, element name) of one pick, given as the top-level object and its full subname.

    A pick on a bracket placed by a Brackets object gives that object, as Calibrate bracket takes it;
    otherwise the object is the one the element belongs to, as ``brackets.resolve`` finds it (a link to
    a profile or joint gives the profile or joint).
    """
    if not sub:
        return root, ""
    obj, rest = brackets.resolve(root, sub)
    if not brackets.is_brackets(obj):
        linked = obj.getLinkedObject(True)
        if linked is not None and (feature.is_profile(linked) or joints.is_joint(linked)):
            obj = linked
    return obj, rest.rsplit(".", 1)[-1]


def _resolved(selection):
    """([(object, element names, shape hash or None)], number of entries), grouped by object."""
    groups = {}
    total = 0
    for root, names in selection:
        total += 1
        for name in names or ("",):
            obj, element = _target(root, name)
            groups.setdefault((obj.Document.Name, obj.Name), (obj, []))[1].append(element)
    return [(obj, tuple(elements), obj.Shape.hashCode() if feature.is_profile(obj) else None)
            for obj, elements in groups.values()], total


def _summary(groups, total):
    profiles = joint_count = bracket_count = slots = part_faces = parts = other = 0
    used = {}
    for obj, elements, stamp in groups:
        if feature.is_profile(obj):
            picked_whole = False
            for name in elements:
                if not name.startswith("Face"):
                    picked_whole = True
                elif slots > 2 or (slots and (profiles or picked_whole)):
                    continue  # no group depends on what the remaining faces are any more
                else:
                    key = (obj.Document.Name, obj.Name, name, stamp)
                    if key not in _slot_floors:
                        try:
                            slot_alignment.picked_slot(obj, name)
                        except ValueError:
                            _slot_floors[key] = False
                        else:
                            _slot_floors[key] = True
                    used[key] = _slot_floors[key]
                    if used[key]:
                        slots += 1
                    else:
                        picked_whole = True  # a click on the profile's own face means the profile
            profiles += picked_whole
        elif joints.is_joint(obj):
            joint_count += 1
        elif brackets.is_brackets(obj):
            bracket_count += 1
        else:
            faces = sum(name.startswith("Face") for name in elements)
            if faces and not brackets.holds_frame(obj):
                part_faces += faces
                parts += 1
            if faces < len(elements):
                other += 1
    _slot_floors.clear()
    _slot_floors.update(used)
    return Selection(profiles=profiles, joints=joint_count, brackets=bracket_count, slots=slots,
                     part_faces=part_faces, parts=parts, other=other, total=total)


def summarize(selection):
    """Count what is selected, from (top-level object, full subnames) pairs.

    The pairs are as an unresolved selection gives them (``getSelectionEx("", 0)``): a face of a
    profile in a group is (group, ("Profile.Face3",)), a face of a placed bracket (Brackets, ("0.Face1",)).
    """
    return _summary(*_resolved(selection))


def _picks():
    import FreeCADGui as Gui
    return [(s.Object, tuple(s.SubElementNames)) for s in Gui.Selection.getSelectionEx("", 0)]


def current_selection():
    """The summary of the current selection, made once per selection and shared by all the watchers."""
    groups, total = _resolved(_picks())
    key = (total, tuple((obj.Document.Name, obj.Name, elements, stamp) for obj, elements, stamp in groups))
    if _last[0] != key:
        _last[:] = [key, _summary(groups, total)]
    return _last[1]


def _bracket_part(sel):
    # Brackets and End plates take the two contact faces of one part (and optionally joints).
    return sel.part_faces == 2 and sel.parts == 1 and not (sel.slots or sel.brackets)


def _frame_selected(sel):
    return (sel.profiles or sel.joints) and not sel.slots and not _bracket_part(sel)


def _create(sel):
    return not (sel.profiles or sel.joints or sel.brackets or sel.slots or _bracket_part(sel))


def _report(sel):
    doc = App.ActiveDocument
    return not sel.total and any(feature.is_profile(o) for o in doc.Objects)


def _align(sel):
    # The command refuses anything but two slot floors, so only offer it for exactly that.
    return sel.slots == 2 and not (sel.profiles or sel.joints or sel.brackets or sel.part_faces or sel.other)


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
                       ["ProfileBuilder_Panel", "ProfileBuilder_Carriage", "ProfileBuilder_Brackets",
                        "ProfileBuilder_EndPlates"],
                       _frame_selected),
        ContextWatcher(translate("ProfileBuilder", "Bracket part"),
                       ["ProfileBuilder_Brackets", "ProfileBuilder_EndPlates"], _bracket_part),
        ContextWatcher(translate("ProfileBuilder", "Brackets"),
                       ["ProfileBuilder_CalibrateBracket"], _brackets),
        ContextWatcher(translate("ProfileBuilder", "Report and check"),
                       ["ProfileBuilder_CutList", "ProfileBuilder_ExportCutList", "ProfileBuilder_CheckFrame",
                        "ProfileBuilder_FrameStiffness", "ProfileBuilder_ExportPanels", "ProfileBuilder_Pricing"],
                       _report),
    ]
