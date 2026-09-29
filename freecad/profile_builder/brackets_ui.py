"""GUI commands for brackets: place the user's bracket part at the joints, and calibrate it."""

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import brackets, feature, joints, panels
from .feature import ICON_DIR

HOW_TO = ("Pick the bracket's two faces that touch the profiles (Ctrl+click): first the one that lies on the "
          "profile ending at the joint, then the one on the profile it meets.\n\n"
          "The bracket can be any part in the document, for example a STEP file from your supplier "
          "(File > Import). Select joints or profiles as well to place brackets only there; otherwise every "
          "joint gets them.")


def icon(name):
    return os.path.join(ICON_DIR, name)


def _message(text, title="Brackets"):
    from PySide import QtWidgets
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), title, text)


def _is_ours(obj):
    return feature.is_profile(obj) or joints.is_joint(obj) or panels.is_panel(obj)


def _picks():
    """[(top-level object, subname)] of the picked faces and vertices, in pick order.

    Picks on profiles, joints and panels are not bracket picks and are left out.
    """
    found = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames:
            if not sub.rsplit(".", 1)[-1].startswith(("Face", "Vertex")):
                continue
            obj, _rest = brackets.resolve(sel.Object, sub)
            if not _is_ours(obj):
                found.append((sel.Object, sub))
    return found


def _whole_part():
    """A selected solid part that can serve as the bracket as it is (no faces picked), or None."""
    for obj in Gui.Selection.getSelection():
        if _is_ours(obj) or brackets.is_brackets(obj):
            continue
        try:
            solid = bool(Part.getShape(obj).Solids)
        except Exception:  # noqa: BLE001  (objects without any shape)
            solid = False
        if solid:  # not a sketch or a line object
            return obj
    return None


def _chosen_joints(doc):
    """(joints, all): the selected joints and those of the selected profiles, or else every joint."""
    found = []
    for obj in Gui.Selection.getSelection():
        if joints.is_joint(obj):
            found.append(obj)
        elif feature.is_profile(obj):
            found += [j for j in (obj.StartJoint, obj.EndJoint) if j is not None]
            found += [j for j in doc.Objects if joints.is_joint(j) and obj.Name in j.PassingMembers]
    found = list(dict.fromkeys(found))
    return (found, False) if found else (brackets.all_joints(doc), True)


def _targets():
    """Brackets objects in the selection, also when a face of one of its brackets was picked."""
    found = [o for o in Gui.Selection.getSelection() if brackets.is_brackets(o)]
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames or ("",):
            obj = brackets.resolve(sel.Object, sub)[0] if sub else sel.Object
            if brackets.is_brackets(obj) and obj not in found:
                found.append(obj)
    return found


def task_panel(obj):
    from .simple_panel import PropertyTaskPanel
    return PropertyTaskPanel(obj, brackets.FIELDS, "Brackets", brackets.info)


class CreateBrackets:
    def GetResources(self):
        return {
            "Pixmap": icon("Brackets.svg"),
            "MenuText": "Brackets...",
            "ToolTip": ("Place your bracket part (for example a STEP file from your supplier) in the corners\n"
                        "of the joints. Pick the bracket's two faces that touch the profiles: first the one on\n"
                        "the profile that ends at the joint, then the one on the profile it meets. Select\n"
                        "joints or profiles as well to limit where brackets go."),
        }

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.Control.activeDialog() is False

    def Activated(self):
        doc = App.ActiveDocument
        picks = _picks()
        notes = []
        try:
            if picks:
                part, frame, notes = brackets.calibrate(picks)
            else:
                part, frame = _whole_part(), None
                if part is not None:
                    notes.append(f"no contact faces picked, so {part.Label} is used as modelled: contact corner "
                                 "at its origin, legs along +X and +Y. Use Calibrate bracket to change that.")
        except ValueError as e:
            _message(f"{e}.\n\n{HOW_TO}")
            return
        if part is None:
            _message(HOW_TO)
            return
        chosen, everywhere = _chosen_joints(doc)
        if not chosen:
            _message("There are no joints yet. Join the profiles first (Joints...), then place the brackets.")
            return
        doc.openTransaction("Brackets")
        # Without a choice, joints made later get brackets too.
        obj = brackets.make_brackets(doc, part, chosen, frame, AllJoints=everywhere)
        doc.recompute()
        doc.commitTransaction()
        for note in notes + list(obj.Notes):
            App.Console.PrintWarning(f"Profile Builder: {note}\n")
        App.Console.PrintMessage(f"Profile Builder: {obj.Count} bracket(s) placed at {len(chosen)} joint(s).\n")
        # The brackets show the part in the corners; the original is in the way.
        vobj = getattr(part, "ViewObject", None)
        if vobj is not None:
            vobj.Visibility = False
        Gui.Selection.clearSelection()
        Gui.Control.showDialog(task_panel(obj))


class CalibrateBracket:
    def GetResources(self):
        return {
            "Pixmap": icon("CalibrateBracket.svg"),
            "MenuText": "Calibrate bracket",
            "ToolTip": ("Set how the part of a Brackets object sits in the corners.\n"
                        "Pick the bracket's two faces that touch the profiles, on one of the placed brackets\n"
                        "or on the part itself (select the Brackets object too): first the one on the profile\n"
                        "that ends at the joint, then the one on the profile it meets."),
        }

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.Control.activeDialog() is False and bool(_targets())

    def Activated(self):
        doc = App.ActiveDocument
        targets = _targets()
        if len(targets) != 1:
            _message("Select one Brackets object, and pick its bracket's two contact faces.")
            return
        target = targets[0]
        try:
            part, frame, notes = brackets.calibrate(_picks())
        except ValueError as e:
            _message(f"{e}.\n\n{HOW_TO}")
            return
        doc.openTransaction("Calibrate bracket")
        if part != target.LinkedObject:
            target.LinkedObject = part
        target.SourceFrame = frame
        target.SwapLegs = False  # the pick order decides which leg goes where
        doc.recompute()
        doc.commitTransaction()
        for note in notes + list(target.Notes):
            App.Console.PrintWarning(f"Profile Builder: {note}\n")
        App.Console.PrintMessage(f"Profile Builder: {target.Label} calibrated, {target.Count} bracket(s).\n")


def register():
    """Register the bracket commands; returns their names."""
    Gui.addCommand("ProfileBuilder_Brackets", CreateBrackets())
    Gui.addCommand("ProfileBuilder_CalibrateBracket", CalibrateBracket())
    return ["ProfileBuilder_Brackets", "ProfileBuilder_CalibrateBracket"]
