"""GUI commands for brackets: place the user's bracket part at the joints, and calibrate it."""

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import brackets, feature, joints, panels
from .feature import ICON_DIR

QT_TRANSLATE_NOOP = App.Qt.QT_TRANSLATE_NOOP

HOW_TO = ("Pick the bracket's two faces that touch the profiles (Ctrl+click): first the one that lies on the "
          "profile ending at the joint, then the one on the profile it meets.\n\n"
          "The bracket can be any part in the document, for example a STEP file from your supplier "
          "(File > Import). Select joints or profiles as well to place brackets only there; otherwise every "
          "joint gets them.")

HOW_TO_PLATE = ("Pick the plate's two faces: first the flat face that lies on the profiles, then the face at the "
                "end of its stem (the part that lies on the profile that ends at the joint).\n\n"
                "The plate can be any part in the document, for example a STEP file from your supplier "
                "(File > Import). Select joints or profiles as well to place plates only there; otherwise "
                "every T-junction gets them.")


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
    """A selected solid part that can serve as the bracket as it is (no faces picked), or None.

    Not a profile, joint, panel or Brackets object, nor a group, App::Part or
    link holding one: the brackets would show the frame in every corner.
    """
    for obj in Gui.Selection.getSelection():
        if brackets.holds_frame(obj):
            continue
        try:
            solid = bool(Part.getShape(obj).Solids)
        except Exception:  # noqa: BLE001  (objects without any shape)
            solid = False
        if solid:  # not a sketch or a line object
            return obj
    return None


def _chosen_joints(doc, style="Corner"):
    """(joints, all): the selected joints and those of the selected profiles, or else every joint.

    End plates only go at T-junctions, so for them the other selected joints are left out: given
    explicitly, they would be taken from an all-joints Brackets object that places brackets there.
    """
    found = []
    for obj in Gui.Selection.getSelection():
        if joints.is_joint(obj):
            found.append(obj)
        elif feature.is_profile(obj):
            found += [j for j in (obj.StartJoint, obj.EndJoint) if j is not None]
            found += [j for j in doc.Objects if joints.is_joint(j) and obj.Name in j.PassingMembers]
    if not found:
        return brackets.all_joints(doc), True
    found = list(dict.fromkeys(found))
    if style == "End plate":
        found = [j for j in found if joints.passing_of(j)]
    return found, False


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
    from PySide import QtCore, QtWidgets

    from .simple_panel import PropertyTaskPanel

    class BracketsPanel(PropertyTaskPanel):
        """The property fields, plus a checklist of the corners: untick one to leave it without brackets."""

        def __init__(self):
            super().__init__(obj, brackets.fields(obj), "Brackets", brackets.info)
            brackets.fill_corners(obj)  # a document saved before the corner list existed
            self.corners = QtWidgets.QListWidget()
            self.corners.setToolTip(obj.getDocumentationOfProperty("SkippedCorners"))
            self.form.layout().insertRow(self.form.layout().rowCount() - 1,
                                         App.Qt.translate("ProfileBuilder", "Corners"), self.corners)
            self._fill()
            self.corners.itemChanged.connect(self.changed)

        def _fill(self):
            skipped = set(obj.SkippedCorners)
            self.corners.blockSignals(True)
            try:
                self.corners.clear()
                for key, label in zip(obj.Corners, obj.CornerLabels):
                    item = QtWidgets.QListWidgetItem(label)
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                    item.setCheckState(QtCore.Qt.Unchecked if key in skipped else QtCore.Qt.Checked)
                    item.setData(QtCore.Qt.UserRole, key)
                    self.corners.addItem(item)
            finally:
                self.corners.blockSignals(False)

        def apply(self):
            current = set(obj.Corners)
            skipped = [k for k in obj.SkippedCorners if k not in current]  # corners that are not listed now stay as set
            for i in range(self.corners.count()):
                item = self.corners.item(i)
                if item.checkState() == QtCore.Qt.Unchecked:
                    skipped.append(item.data(QtCore.Qt.UserRole))
            if sorted(skipped) != sorted(obj.SkippedCorners):
                obj.SkippedCorners = skipped
            super().apply()

        def _reload(self):
            super()._reload()
            self._fill()

    return BracketsPanel()


class CreateBrackets:
    style = "Corner"
    how_to = HOW_TO

    def GetResources(self):
        return {
            "Pixmap": icon("Brackets.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_Brackets", "Brackets..."),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_Brackets", "Place your bracket part (for example a STEP file from your supplier) in the corners\n"
                        "of the joints. Pick the bracket's two faces that touch the profiles: first the one on\n"
                        "the profile that ends at the joint, then the one on the profile it meets. Select\n"
                        "joints or profiles as well to limit where brackets go.")),
        }

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.Control.activeDialog() is False

    def Activated(self):
        doc = App.ActiveDocument
        picks = _picks()
        notes = []
        try:
            if picks:
                part, frame, notes = brackets.calibrate(picks, self.style)
            else:
                part, frame = _whole_part(), None
                if part is not None:
                    notes.append(f"no contact faces picked, so {part.Label} is used as modelled: "
                                 + ("its contact face in the XY plane facing -Z, the stem along +X, the bar's "
                                    "outer end at the origin" if self.style == "End plate" else
                                    "contact corner at its origin, legs along +X and +Y")
                                 + ". Use Calibrate bracket to change that.")
        except ValueError as e:
            _message(f"{e}.\n\n{self.how_to}")
            return
        if part is None:
            _message(self.how_to)
            return
        chosen, everywhere = _chosen_joints(doc, self.style)
        if not chosen and not everywhere:
            _message("None of the selected joints and profiles is at a T-junction, where one profile ends on the "
                     f"side of another that runs through, so there is nowhere to put end plates.\n\n{self.how_to}")
            return
        if not chosen:
            _message("There are no joints yet. Join the profiles first (Joints...), then place the brackets.")
            return
        doc.openTransaction("End plates" if self.style == "End plate" else "Brackets")
        # Without a choice, joints made later get brackets too.
        obj = brackets.make_brackets(doc, part, chosen, frame, AllJoints=everywhere, SkipClaimed=everywhere,
                                     Style=self.style)
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


class CreateEndPlates(CreateBrackets):
    style = "End plate"
    how_to = HOW_TO_PLATE

    def GetResources(self):
        return {
            "Pixmap": icon("Brackets.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_EndPlates", "End plates..."),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_EndPlates", "Place your plate part (for example a T plate from your supplier) across the profiles at\n"
                                          "T-junctions, where one profile ends on the side of another. Pick the plate's two\n"
                                          "faces: first the one that lies on the profiles, then the one at the end of its stem.\n"
                                          "Select joints or profiles as well to limit where plates go.")),
        }


class CalibrateBracket:
    def GetResources(self):
        return {
            "Pixmap": icon("CalibrateBracket.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_CalibrateBracket", "Calibrate bracket"),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_CalibrateBracket", "Set how the part of a Brackets object sits in the corners.\n"
                        "Pick the bracket's two faces that touch the profiles, on one of the placed brackets\n"
                        "or on the part itself (select the Brackets object too): first the one on the profile\n"
                        "that ends at the joint, then the one on the profile it meets.")),
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
            part, frame, notes = brackets.calibrate(_picks(), target.Style)
        except ValueError as e:
            _message(f"{e}.\n\n{HOW_TO_PLATE if target.Style == 'End plate' else HOW_TO}")
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
    Gui.addCommand("ProfileBuilder_EndPlates", CreateEndPlates())
    Gui.addCommand("ProfileBuilder_CalibrateBracket", CalibrateBracket())
    return ["ProfileBuilder_Brackets", "ProfileBuilder_EndPlates", "ProfileBuilder_CalibrateBracket"]
