"""GUI commands of the Profile Builder workbench."""

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import cutlist, feature, joints, panels, profiles
from .feature import ICON_DIR


def icon(name):
    return os.path.join(ICON_DIR, name)


def size_icon(key, cols, rows):
    path = icon(f"sizes/{key}_{cols}x{rows}.svg")
    return path if os.path.exists(path) else icon("Profile.svg")


def selected_edges():
    """Straight edges in the selection as (object, "EdgeN") tuples.

    Selected sub-edges are used as is; a whole selected object (e.g. a sketch)
    contributes all of its straight edges.
    """
    result = []
    for sel in Gui.Selection.getSelectionEx():
        obj = sel.Object
        if feature.is_profile(obj):
            continue
        subs = [s for s in sel.SubElementNames if s.startswith("Edge")]
        if subs:
            for sub in subs:
                edge = obj.getSubObject(sub)
                if isinstance(getattr(edge, "Curve", None), Part.Line):
                    result.append((obj, sub))
        elif hasattr(obj, "Shape") and not sel.SubElementNames:
            for i, edge in enumerate(obj.Shape.Edges, start=1):
                if isinstance(edge.Curve, Part.Line):
                    result.append((obj, f"Edge{i}"))
    return result


class CreateProfile:
    def GetResources(self):
        return {
            "Pixmap": icon("CreateProfile.svg"),
            "MenuText": "Profile...",
            "ToolTip": ("Create an aluminium extrusion profile.\n"
                        "Select straight edges (or a sketch) first to create one profile per edge."),
        }

    def IsActive(self):
        return Gui.Control.activeDialog() is False

    def Activated(self):
        from .taskpanel import ProfileTaskPanel
        Gui.Control.showDialog(ProfileTaskPanel(edges=selected_edges()))


class QuickProfile:
    """Insert one catalog size immediately, using the last used length and style."""

    def __init__(self, key, cols, rows):
        self.key, self.cols, self.rows = key, cols, rows
        self.series = profiles.SERIES[key]

    def GetResources(self):
        name = self.series.designation(self.cols, self.rows)
        return {
            "Pixmap": size_icon(self.key, self.cols, self.rows),
            "MenuText": f"{name}",
            "ToolTip": (f"Insert a {name} profile ({profiles.series_label(self.key)}).\n"
                        "Uses the weight class and slot style you last picked in the Profile dialog.\n"
                        "With straight edges selected, one profile is placed on each edge."),
        }

    def IsActive(self):
        return Gui.Control.activeDialog() is False

    def Activated(self):
        from .taskpanel import PARAMS
        p = App.ParamGet(PARAMS)
        doc = App.ActiveDocument or App.newDocument()
        edges = selected_edges()
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
        return {"MenuText": label, "ToolTip": f"Insert a {label} profile", "DropDownMenu": True}

    def IsActive(self):
        return Gui.Control.activeDialog() is False


class CutList:
    def GetResources(self):
        return {
            "Pixmap": icon("CutList.svg"),
            "MenuText": "Cut list and costs",
            "ToolTip": ("Create or update the 'Cut list' spreadsheet: pieces grouped by size and length,\n"
                        "stock bar plan, sheets and the cost estimate"),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        report = cutlist.build_report(doc)
        doc.openTransaction("Cut list")
        sheet = cutlist.write_spreadsheet(doc, report)
        doc.commitTransaction()
        App.Console.PrintMessage(
            f"Profile Builder: total {report.currency} {report.total:,.2f} -> '{sheet.Label}'\n")
        for warning in report.warnings:
            App.Console.PrintMessage(f"  {warning}\n")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(sheet)


class ExportCutList:
    def GetResources(self):
        return {
            "Pixmap": icon("ExportCutList.svg"),
            "MenuText": "Export cut list (CSV)...",
            "ToolTip": "Write the cut list of all profiles to a CSV file",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from PySide import QtWidgets
        doc = App.ActiveDocument
        start = os.path.splitext(doc.FileName)[0] + "_cutlist.csv" if doc.FileName else "cutlist.csv"
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            Gui.getMainWindow(), "Export cut list", start, "CSV files (*.csv)")
        if path:
            cutlist.write_csv(cutlist.build_report(doc), path)
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
            "MenuText": "Joints...",
            "ToolTip": ("Create joints where profiles on sketch edges meet, so they butt or miter\n"
                        "instead of overlapping. Uses the selected profiles, or all of them."),
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
                Gui.getMainWindow(), "Joints",
                "Joints connect profiles that follow sketch edges.\n"
                "Select a sketch and insert profiles on its edges first.")
            return
        labels = [label for label, _t, _r in JOINT_STYLES]
        choice, ok = QtWidgets.QInputDialog.getItem(
            Gui.getMainWindow(), "Joints", "How should the profiles meet?", labels, 0, False)
        if not ok:
            return
        _label, joint_type, rule = JOINT_STYLES[labels.index(choice)]
        doc.openTransaction("Create joints")
        created = joints.create_joints(doc, targets, joint_type, rule)
        doc.recompute()
        doc.commitTransaction()
        App.Console.PrintMessage(f"Profile Builder: {len(created)} joint(s) created. Select joints to "
                                 "change their type or which profile runs through.\n")


class RunThrough:
    def GetResources(self):
        return {
            "Pixmap": icon("RunThrough.svg"),
            "MenuText": "Run through",
            "ToolTip": ("Make the selected profiles run through all their butt joints;\n"
                        "the profiles they meet are trimmed against them instead."),
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
            "MenuText": "Swap joint",
            "ToolTip": ("Let the other profile run through the selected butt joint(s).\n"
                        "Select the joint (orange dot or tree item), or a profile to swap both its ends."),
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
            "MenuText": "Panel...",
            "ToolTip": ("Create a sheet panel in the opening between the selected profiles\n"
                        "(at least three, in one plane), e.g. an enclosure side."),
        }

    def IsActive(self):
        return (Gui.Control.activeDialog() is False
                and len([o for o in Gui.Selection.getSelection() if feature.is_profile(o)]) >= 3)

    def Activated(self):
        doc = App.ActiveDocument
        members = [o for o in Gui.Selection.getSelection() if feature.is_profile(o)]
        doc.openTransaction("Create panel")
        panel = panels.make_panel(doc, members)
        doc.recompute()
        doc.commitTransaction()
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(panel, 0)


class Pricing:
    def GetResources(self):
        return {
            "Pixmap": icon("Pricing.svg"),
            "MenuText": "Pricing and stock...",
            "ToolTip": "Prices per metre and m², stock bar lengths, cutting, delivery and tax",
        }

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.Control.activeDialog() is False

    def Activated(self):
        from .pricing_ui import PricingTaskPanel
        Gui.Control.showDialog(PricingTaskPanel(App.ActiveDocument))


def register():
    """Register all commands; returns [(series key, group command, size commands)]."""
    Gui.addCommand("ProfileBuilder_Create", CreateProfile())
    Gui.addCommand("ProfileBuilder_CutList", CutList())
    Gui.addCommand("ProfileBuilder_ExportCutList", ExportCutList())
    Gui.addCommand("ProfileBuilder_Joints", CreateJoints())
    Gui.addCommand("ProfileBuilder_RunThrough", RunThrough())
    Gui.addCommand("ProfileBuilder_SwapJoint", SwapJoint())
    Gui.addCommand("ProfileBuilder_Panel", CreatePanel())
    Gui.addCommand("ProfileBuilder_Pricing", Pricing())
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
