"""GUI commands of the Profile Builder workbench."""

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import cutlist, feature, joints, panels, pricing, profiles, slot_alignment
from . import linear, linear_ui  # carriages
from .feature import ICON_DIR

QT_TRANSLATE_NOOP = App.Qt.QT_TRANSLATE_NOOP

translate = App.Qt.translate


def icon(name):
    return os.path.join(ICON_DIR, name)


def size_icon(key, cols, rows):
    path = icon(f"sizes/{key}_{cols}x{rows}.svg")
    return path if os.path.exists(path) else icon("Profile.svg")


def selected_edges():
    """Straight edges in the selection: ([(object, "EdgeN")], number skipped).

    Selected sub-edges are used as is; a whole selected object (e.g. a sketch)
    contributes all of its straight edges. Edges that already carry a profile
    are skipped, so inserting twice does not silently double the cut list.
    """
    doc = App.ActiveDocument
    occupied = set()
    for p in (doc.Objects if doc else []):
        if feature.is_profile(p) and p.PathEdge:
            try:
                occupied.add((p.PathEdge[0].Name, _edge_key(feature.path_edge(p))))
            except ValueError:
                pass  # a broken path edge occupies nothing

    result, skipped = [], 0

    def take(obj, sub, edge):
        nonlocal skipped
        if not isinstance(getattr(edge, "Curve", None), Part.Line):
            return
        if (obj.Name, _edge_key(edge)) in occupied:
            skipped += 1
        else:
            result.append((obj, sub))

    for sel in Gui.Selection.getSelectionEx():
        obj = sel.Object
        if feature.is_profile(obj) or joints.is_joint(obj) or panels.is_panel(obj) or linear.is_carriage(obj):
            continue
        subs = [s for s in sel.SubElementNames if s.startswith("Edge")]
        if subs:
            for sub in subs:
                take(obj, sub, obj.getSubObject(sub))
        elif hasattr(obj, "Shape") and not sel.SubElementNames:
            for i, edge in enumerate(obj.Shape.Edges, start=1):
                take(obj, f"Edge{i}", edge)
    if skipped:
        App.Console.PrintWarning(f"Profile Builder: skipped {skipped} edge(s) that already have a profile\n")
    return result, skipped


def _edge_key(edge):
    """The two end points of an edge, rounded, in either order."""
    return frozenset(tuple(round(c, 6) for c in v.Point) for v in edge.Vertexes)


class CreateProfile:
    def GetResources(self):
        return {
            "Pixmap": icon("CreateProfile.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_Create", "Profile..."),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_Create", "Create an aluminium extrusion profile.\n"
                        "Select straight edges (or a sketch) first to create one profile per edge.")),
        }

    def IsActive(self):
        return Gui.Control.activeDialog() is False

    def Activated(self):
        from .taskpanel import ProfileTaskPanel
        edges, skipped = selected_edges()
        if not edges and skipped:
            return  # every selected edge already has a profile (a warning was printed)
        Gui.Control.showDialog(ProfileTaskPanel(edges=edges))


class CreateBoxFrame:
    def GetResources(self):
        return {
            "Pixmap": icon("BoxFrame.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_BoxFrame", "Box frame..."),
            "ToolTip": QT_TRANSLATE_NOOP("ProfileBuilder_BoxFrame", "Create a cube frame from outside, inside-clear or centre-line dimensions"),
        }

    def IsActive(self):
        return Gui.Control.activeDialog() is False

    def Activated(self):
        from .box_frame_ui import BoxFrameTaskPanel
        Gui.Control.showDialog(BoxFrameTaskPanel())


class QuickProfile:
    """Insert one catalog size immediately, using the last used length and style."""

    def __init__(self, key, cols, rows):
        self.key, self.cols, self.rows = key, cols, rows
        self.series = profiles.SERIES[key]

    def GetResources(self):
        name = self.series.designation(self.cols, self.rows)
        return {
            "Pixmap": size_icon(self.key, self.cols, self.rows),
            "MenuText": name,
            "ToolTip": translate("ProfileBuilder", "Insert a {name} profile ({series}).\n"
                                 "Uses the weight class and slot style you last picked in the Profile dialog.\n"
                                 "With straight edges selected, one profile is placed on each edge.").format(
                                     name=name, series=profiles.series_label(self.key)),
        }

    def IsActive(self):
        return Gui.Control.activeDialog() is False

    def Activated(self):
        from .taskpanel import PARAMS
        p = App.ParamGet(PARAMS)
        doc = App.ActiveDocument or App.newDocument()
        edges, skipped = selected_edges()
        if not edges and skipped:
            return  # every selected edge already has a profile (a warning was printed)
        doc.openTransaction(f"Insert {self.series.designation(self.cols, self.rows)}")
        created = []
        for edge in edges or [None]:
            obj = feature.make_profile(self.key, self.cols, self.rows,
                                       p.GetFloat("Length", 1000.0), doc, edge=edge,
                                       SlotStyle=p.GetString("SlotStyle", "T-slot"))
            weight = p.GetString("Weight", "Standard")
            if weight in profiles.WEIGHTS:
                obj.Weight = weight
            obj.Anchor = p.GetString("EdgeAnchor" if edge else "Anchor", "Center")
            created.append(obj)
        doc.recompute()
        doc.commitTransaction()
        Gui.Selection.clearSelection()
        for obj in created:
            Gui.Selection.addSelection(obj)


class SeriesGroup:
    """Toolbar drop-down with all catalog sizes of one series."""

    def __init__(self, key, commands):
        self.key, self.commands = key, commands

    def GetCommands(self):
        return self.commands

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        label = profiles.series_label(self.key)
        return {"MenuText": label, "DropDownMenu": True,
                "ToolTip": translate("ProfileBuilder", "Insert a {label} profile").format(label=label)}

    def IsActive(self):
        return Gui.Control.activeDialog() is False


class CutList:
    def GetResources(self):
        return {
            "Pixmap": icon("CutList.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_CutList", "Cut list and costs"),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_CutList", "Create or update the 'Cut list' spreadsheet: pieces grouped by size and length,\n"
                        "stock bar plan, sheets and the cost estimate")),
        }

    def IsActive(self):
        # A task dialog's Cancel undoes its open transaction; the transaction opened here would
        # commit it first, so wait until the dialog is closed.
        return (Gui.Control.activeDialog() is False
                and App.ActiveDocument is not None)

    def Activated(self):
        doc = App.ActiveDocument
        cutlist.recompute_if_needed(doc)
        report = cutlist.build_report(doc)
        doc.openTransaction("Cut list")
        sheet = cutlist.write_spreadsheet(doc, report)
        cutlist.apply_marks(doc, report)
        doc.commitTransaction()
        App.Console.PrintMessage(
            f"Profile Builder: total {pricing.format_money(report.total, report.currency)} -> '{sheet.Label}'\n")
        for error in report.errors:
            App.Console.PrintError(f"  Not in the cut list: {error}\n")
        for warning in report.warnings:
            App.Console.PrintMessage(f"  {warning}\n")
        from .check_ui import quick_summary
        issues = quick_summary(doc)
        if issues:
            App.Console.PrintWarning(f"Profile Builder: {issues}\n")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(sheet)


class ExportCutList:
    def GetResources(self):
        return {
            "Pixmap": icon("ExportCutList.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_ExportCutList", "Export cut list (CSV)..."),
            "ToolTip": QT_TRANSLATE_NOOP("ProfileBuilder_ExportCutList", "Write the cut list of all profiles to a CSV file"),
        }

    def IsActive(self):
        # A task dialog's Cancel undoes its open transaction; the transaction opened here would
        # commit it first, so wait until the dialog is closed.
        return (Gui.Control.activeDialog() is False
                and App.ActiveDocument is not None)

    def Activated(self):
        from PySide import QtCore, QtWidgets
        doc = App.ActiveDocument
        start = os.path.splitext(doc.FileName)[0] + "_cutlist.csv" if doc.FileName else "cutlist.csv"
        comma = "CSV, comma separated, decimal point: 1234.5 (*.csv)"
        semicolon = "CSV, semicolon separated, decimal comma: 1234,5 (*.csv)"
        # Many regions write numbers with a decimal comma, and their spreadsheet
        # programs expect semicolons. Offer the variant that matches this
        # computer's number format first.
        decimal_comma = QtCore.QLocale().decimalPoint() == ","
        filters = [semicolon, comma] if decimal_comma else [comma, semicolon]
        path, chosen = QtWidgets.QFileDialog.getSaveFileName(
            Gui.getMainWindow(), "Export cut list", start, ";;".join(filters))
        if path:
            cutlist.recompute_if_needed(doc)
            report = cutlist.build_report(doc)
            # Keep the marks on the model (and an existing Cut list sheet) the
            # same as in the file, so labels and printout agree.
            doc.openTransaction("Export cut list")
            cutlist.apply_marks(doc, report)
            sheet = doc.getObject("CutList")
            if sheet is not None and sheet.TypeId == "Spreadsheet::Sheet":
                cutlist.write_spreadsheet(doc, report)
            doc.commitTransaction()
            if chosen == semicolon:
                cutlist.write_csv(report, path, delimiter=";", decimal=",")
            else:
                cutlist.write_csv(report, path)
            App.Console.PrintMessage(f"Profile Builder: cut list written to {path}\n")


JOINT_STYLES = (
    ("Butt joints, vertical profiles run through", "Butt", "Vertical"),
    ("Butt joints, longest profile runs through", "Butt", "Longest"),
    ("Butt joints, horizontal profiles run through", "Butt", "Horizontal"),
    ("Butt joints, profiles along X run through", "Butt", "Along X"),
    ("Butt joints, profiles along Y run through", "Butt", "Along Y"),
    ("Miter corners where two profiles meet", "Miter", "Longest"),
)


class CreateJoints:
    def GetResources(self):
        return {
            "Pixmap": icon("Joint.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_Joints", "Joints..."),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_Joints", "Create joints where profiles on sketch edges meet, so they butt or miter\n"
                        "instead of overlapping. Uses the selected profiles, or all of them.")),
        }

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.Control.activeDialog() is False

    def Activated(self):
        from PySide import QtWidgets
        doc = App.ActiveDocument
        selected = [o for o in Gui.Selection.getSelection() if feature.is_profile(o)]
        targets = selected or [o for o in doc.Objects if feature.is_profile(o)]
        if not any(o.PathEdge for o in targets):
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), translate("ProfileBuilder", "Joints"),
                translate("ProfileBuilder", "Joints connect profiles that follow sketch edges.\n"
                "Select a sketch and insert profiles on its edges first."))
            return
        labels = [label for label, _t, _r in JOINT_STYLES]
        choice, ok = QtWidgets.QInputDialog.getItem(
            Gui.getMainWindow(), translate("ProfileBuilder", "Joints"), translate("ProfileBuilder", "How should the profiles meet?"), labels, 0, False)
        if not ok:
            return
        _label, joint_type, rule = JOINT_STYLES[labels.index(choice)]
        doc.openTransaction("Create joints")
        warnings = []
        created = joints.create_joints(doc, targets, joint_type, rule, warnings=warnings)
        doc.recompute()
        doc.commitTransaction()
        for warning in warnings:
            App.Console.PrintWarning(f"Profile Builder: {warning}\n")
        App.Console.PrintMessage(f"Profile Builder: {len(created)} joint(s) created. Select joints to "
                                 "change their type or which profile runs through.\n")


class AlignSlots:
    def GetResources(self):
        return {
            "Pixmap": icon("AlignSlots.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_AlignSlots", "Align slots"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "ProfileBuilder_AlignSlots",
                "Ctrl-select the inside of one slot on each of two profiles, then activate. "
                "The profile picked first slides along its section so its slot lines up with the second. "
                "Sketch edges, spin and length stay fixed."),
        }

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.Control.activeDialog() is False

    def Activated(self):
        from PySide import QtWidgets

        doc = App.ActiveDocument
        title = translate("ProfileBuilder", "Align slots")
        picked_slots = []
        invalid_picks = []
        
        for selection in Gui.Selection.getSelectionEx():
            obj = selection.Object
            if not feature.is_profile(obj):
                continue
            for subelement in selection.SubElementNames:
                try:
                    picked_slots.append(slot_alignment.picked_slot(obj, subelement))
                except ValueError as error:
                    invalid_picks.append(str(error))
        
        if invalid_picks:
            QtWidgets.QMessageBox.warning(
                Gui.getMainWindow(), title, "\n".join(dict.fromkeys(invalid_picks)))
            return

        if len(picked_slots) < 2:
            text = translate("ProfileBuilder", "Ctrl-select exactly two slot floors (the inside of one slot on each profile), "
                           "then activate Align Slots. The profile picked first slides so its slot "
                           "lines up with the second.")
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), title, text)
            return

        if len(picked_slots) > 2:
            text = translate("ProfileBuilder", "Select exactly two slot-floor faces. "
                           "You have selected {0}.").format(len(picked_slots))
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), title, text)
            return

        # Check that slots are on different profiles
        slot1, slot2 = picked_slots
        if slot1.profile.Name == slot2.profile.Name:
            text = translate("ProfileBuilder", "The two slots must be on different profiles.")
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), title, text)
            return

        # The first slot picked is the one that moves; the second is the reference.
        try:
            alignments = slot_alignment.direct_align_slots(slot1, slot2)
        except ValueError as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), title, str(error))
            return

        changes = [alignment for alignment in alignments if alignment.changed]
        if not changes:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), title,
                translate("ProfileBuilder", "The two slots already line up."))
            return

        try:
            changed = slot_alignment.apply(doc, changes)
        except Exception as error:
            QtWidgets.QMessageBox.critical(
                Gui.getMainWindow(), title,
                translate("ProfileBuilder", "Aligning the slots failed: {error}").format(error=error))
            return
        App.Console.PrintMessage(
            translate("ProfileBuilder", "Profile Builder: moved {profile} to line up its slot.\n")
            .format(profile=changed[0].profile.Label))

class RunThrough:
    def GetResources(self):
        return {
            "Pixmap": icon("RunThrough.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_RunThrough", "Run through"),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_RunThrough", "Make the selected profiles run through all their butt joints;\n"
                        "the profiles they meet are trimmed against them instead.")),
        }

    def IsActive(self):
        return any(feature.is_profile(o) and (o.StartJoint or o.EndJoint)
                   for o in Gui.Selection.getSelection())

    def Activated(self):
        doc = App.ActiveDocument
        chosen = [o for o in Gui.Selection.getSelection() if feature.is_profile(o)]
        doc.openTransaction("Run through")
        joints.set_runs_through(chosen)
        doc.recompute()
        doc.commitTransaction()


class SwapJoint:
    def GetResources(self):
        return {
            "Pixmap": icon("SwapJoint.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_SwapJoint", "Swap joint"),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_SwapJoint", "Let the other profile run through the selected butt joint(s).\n"
                        "Select the joint (orange dot or tree item), or a profile to swap both its ends.")),
        }

    def IsActive(self):
        return bool(self._joints())

    def _joints(self):
        found = []
        for o in Gui.Selection.getSelection():
            if joints.is_joint(o):
                found.append(o)
            elif feature.is_profile(o):
                found += [j for j in (o.StartJoint, o.EndJoint) if j is not None]
        return [j for j in dict.fromkeys(found) if j.Type == "Butt"]

    def Activated(self):
        doc = App.ActiveDocument
        doc.openTransaction("Swap joint")
        for joint in self._joints():
            joints.swap(joint)
        doc.recompute()
        doc.commitTransaction()


class CreatePanel:
    def GetResources(self):
        return {
            "Pixmap": icon("Panel.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_Panel", "Panel..."),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_Panel", "Create a sheet panel in the opening between the selected profiles\n"
                        "(at least three, in one plane), e.g. an enclosure side.")),
        }

    def IsActive(self):
        return (Gui.Control.activeDialog() is False
                and len([o for o in Gui.Selection.getSelection() if feature.is_profile(o)]) >= 3)

    def Activated(self):
        doc = App.ActiveDocument
        members = [o for o in Gui.Selection.getSelection() if feature.is_profile(o)]
        # A sketch selected with the profiles holds the cutouts, but not the sketch the profiles
        # follow (a box selection often catches it), which would cut away the whole sheet.
        paths = {m.PathEdge[0].Name for m in members if m.PathEdge}
        sketches = [o for o in Gui.Selection.getSelection()
                    if o.TypeId == "Sketcher::SketchObject" and o.Name not in paths]
        doc.openTransaction("Create panel")
        panel = panels.make_panel(doc, members, cutouts=sketches[0] if sketches else None)
        doc.recompute()
        doc.commitTransaction()
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(panel, 0)


def _refresh_marks(doc, title, renumber=False):
    """Build the report and store its marks, in one undoable step; returns the report.

    With ``renumber``, the marks given so far are forgotten first, in the same
    step, so one undo brings back the old marks on the model and in the store.
    """
    cutlist.recompute_if_needed(doc)
    doc.openTransaction(title)
    if renumber:
        cutlist.renumber_marks(doc)
    report = cutlist.build_report(doc)
    cutlist.apply_marks(doc, report)
    sheet = doc.getObject("CutList")
    if sheet is not None and sheet.TypeId == "Spreadsheet::Sheet":
        cutlist.write_spreadsheet(doc, report)
    doc.commitTransaction()
    return report


class ShowMarks:
    def GetResources(self):
        return {
            "Pixmap": icon("PieceMarks.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_ShowMarks", "Show piece marks"),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_ShowMarks", "Show or hide the piece marks (A1, A2, ...) in the 3D view, on the selected profiles\n"
                        "or on all of them. Showing them brings the marks up to date first.")),
        }

    def IsActive(self):
        # A task dialog's Cancel undoes its open transaction; the transaction opened here would
        # commit it first, so wait until the dialog is closed.
        return (Gui.Control.activeDialog() is False
                and App.ActiveDocument is not None and any(feature.is_profile(o) for o in App.ActiveDocument.Objects))

    def Activated(self):
        doc = App.ActiveDocument
        chosen = [o for o in Gui.Selection.getSelection() if feature.is_profile(o)]
        members = chosen or [o for o in doc.Objects if feature.is_profile(o)]
        show = not all(getattr(p.ViewObject, "ShowMark", False) for p in members)
        if show:
            _refresh_marks(doc, "Show piece marks")
        for p in members:
            p.ViewObject.ShowMark = show


class RenumberMarks:
    def GetResources(self):
        return {
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_RenumberMarks", "Renumber piece marks"),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_RenumberMarks", "Number all pieces again from A1, and sheets from P-1, closing the gaps that edits leave.\n"
                        "Marks otherwise stay put; after renumbering, labels printed earlier no longer match.")),
        }

    def IsActive(self):
        # A task dialog's Cancel undoes its open transaction; the transaction opened here would
        # commit it first, so wait until the dialog is closed.
        return (Gui.Control.activeDialog() is False
                and App.ActiveDocument is not None)

    def Activated(self):
        doc = App.ActiveDocument
        _refresh_marks(doc, translate("ProfileBuilder", "Renumber piece marks"), renumber=True)
        App.Console.PrintMessage("Profile Builder: piece marks renumbered\n")


class ExportPanels:
    def GetResources(self):
        return {
            "Pixmap": icon("ExportPanels.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_ExportPanels", "Export panels (DXF/SVG)..."),
            "ToolTip": (QT_TRANSLATE_NOOP("ProfileBuilder_ExportPanels", "Write a DXF and an SVG file for each different sheet, for laser cutting or CNC routing.\n"
                        "The unit (mm or inch) follows FreeCAD's unit system and is in each file name.")),
        }

    def IsActive(self):
        # A task dialog's Cancel undoes its open transaction; the transaction opened here would
        # commit it first, so wait until the dialog is closed.
        return (Gui.Control.activeDialog() is False
                and App.ActiveDocument is not None and any(panels.is_panel(o) for o in App.ActiveDocument.Objects))

    def Activated(self):
        from PySide import QtWidgets
        doc = App.ActiveDocument
        start = os.path.dirname(doc.FileName) if doc.FileName else ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(Gui.getMainWindow(), "Export panels to folder", start)
        if not folder:
            return
        report = _refresh_marks(doc, "Export panels")
        written = panels.export_panels(doc, folder, report.marks)
        App.Console.PrintMessage(f"Profile Builder: {len(written) // 2} sheet(s) written to {folder}\n")
        for error in report.errors:
            if "(panel)" in error:
                App.Console.PrintError(f"  Not exported: {error}\n")


class Pricing:
    def GetResources(self):
        return {
            "Pixmap": icon("Pricing.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_Pricing", "Pricing and stock..."),
            "ToolTip": QT_TRANSLATE_NOOP("ProfileBuilder_Pricing", "Prices per metre and m², stock bar lengths, cutting, delivery and tax"),
        }

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.Control.activeDialog() is False

    def Activated(self):
        from .pricing_ui import PricingTaskPanel
        Gui.Control.showDialog(PricingTaskPanel(App.ActiveDocument))


def register():
    """Register all commands; returns [(series key, group command, size commands)]."""
    Gui.addCommand("ProfileBuilder_Create", CreateProfile())
    Gui.addCommand("ProfileBuilder_BoxFrame", CreateBoxFrame())
    Gui.addCommand("ProfileBuilder_CutList", CutList())
    Gui.addCommand("ProfileBuilder_ExportCutList", ExportCutList())
    Gui.addCommand("ProfileBuilder_Joints", CreateJoints())
    Gui.addCommand("ProfileBuilder_AlignSlots", AlignSlots())
    Gui.addCommand("ProfileBuilder_RunThrough", RunThrough())
    Gui.addCommand("ProfileBuilder_SwapJoint", SwapJoint())
    Gui.addCommand("ProfileBuilder_Panel", CreatePanel())
    Gui.addCommand("ProfileBuilder_Pricing", Pricing())
    Gui.addCommand("ProfileBuilder_ShowMarks", ShowMarks())
    Gui.addCommand("ProfileBuilder_RenumberMarks", RenumberMarks())
    Gui.addCommand("ProfileBuilder_ExportPanels", ExportPanels())
    from .frame_ui import FrameStiffness
    Gui.addCommand("ProfileBuilder_FrameStiffness", FrameStiffness())
    Gui.addCommand("ProfileBuilder_Carriage", linear_ui.CreateCarriage())
    from . import brackets_ui, check_ui
    brackets_ui.register()
    check_ui.register()
    groups = []
    for key, series in profiles.SERIES.items():
        names = []
        for cols, rows in series.sizes:
            name = f"ProfileBuilder_Insert_{key.replace('-', '_')}_{cols}x{rows}"
            Gui.addCommand(name, QuickProfile(key, cols, rows))
            names.append(name)
        group = f"ProfileBuilder_Series_{key.replace('-', '_')}"
        Gui.addCommand(group, SeriesGroup(key, names))
        groups.append((key, group, names))
    return groups
