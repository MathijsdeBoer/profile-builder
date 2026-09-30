"""The Check frame command: a task panel listing the frame check's findings."""

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import check
from .feature import ICON_DIR

translate = App.Qt.translate
QT_TRANSLATE_NOOP = App.Qt.QT_TRANSLATE_NOOP

FIX_TEXT = {"delete": QT_TRANSLATE_NOOP("ProfileBuilder", "Delete the extra profiles"),
            "join": QT_TRANSLATE_NOOP("ProfileBuilder", "Join these ends")}
SEVERITY_TEXT = {"Error": QT_TRANSLATE_NOOP("ProfileBuilder", "Errors"),
                 "Warning": QT_TRANSLATE_NOOP("ProfileBuilder", "Warnings"),
                 "Info": QT_TRANSLATE_NOOP("ProfileBuilder", "Notes")}


class CheckPanel:
    """Findings grouped by severity; clicking one selects its objects, Fix repairs the obvious ones."""

    def __init__(self, doc):
        self.doc = doc
        self.findings = []
        form = QtWidgets.QWidget()
        form.setWindowTitle(translate("ProfileBuilder", "Check frame"))
        layout = QtWidgets.QVBoxLayout(form)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setWordWrap(True)
        self.tree.itemSelectionChanged.connect(self.selected)
        layout.addWidget(self.tree)
        buttons = QtWidgets.QHBoxLayout()
        self.fix_button = QtWidgets.QPushButton(translate("ProfileBuilder", "Fix"))
        self.fix_button.setEnabled(False)
        self.fix_button.clicked.connect(self.fix)
        again = QtWidgets.QPushButton(translate("ProfileBuilder", "Check again"))
        again.clicked.connect(self.refresh)
        buttons.addWidget(self.fix_button)
        buttons.addWidget(again)
        layout.addLayout(buttons)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.form = form
        self.refresh()

    def refresh(self):
        self.doc.recompute()
        self.findings = check.run(self.doc)
        self.tree.clear()
        counts = {}
        for severity in check.SEVERITIES:
            items = [f for f in self.findings if f.severity == severity]
            counts[severity] = len(items)
            if not items:
                continue
            title = translate("ProfileBuilder", SEVERITY_TEXT[severity])
            group = QtWidgets.QTreeWidgetItem([f"{title} ({len(items)})"])
            self.tree.addTopLevelItem(group)
            for finding in items:
                item = QtWidgets.QTreeWidgetItem([finding.text])
                item.setData(0, QtCore.Qt.UserRole, self.findings.index(finding))
                item.setToolTip(0, finding.text)
                group.addChild(item)
            group.setExpanded(severity != "Info")
        problems = counts.get("Error", 0) + counts.get("Warning", 0)
        self.summary.setText(translate("ProfileBuilder", "No problems found.") if not problems else
                             translate("ProfileBuilder", "{errors} error(s) and {warnings} warning(s). "
                                       "Click one to select its objects.").format(
                                           errors=counts.get("Error", 0), warnings=counts.get("Warning", 0)))
        self.fix_button.setEnabled(False)

    def current(self):
        items = self.tree.selectedItems()
        index = items[0].data(0, QtCore.Qt.UserRole) if items else None
        return self.findings[index] if index is not None else None

    def selected(self):
        finding = self.current()
        self.fix_button.setEnabled(bool(finding and finding.fix))
        if finding and finding.fix:
            self.fix_button.setText(translate("ProfileBuilder", FIX_TEXT[finding.fix[0]]))
        Gui.Selection.clearSelection()
        if finding is None:
            return
        for name in finding.objects:
            obj = self.doc.getObject(name)
            if obj is not None:
                Gui.Selection.addSelection(obj)
        if finding.objects:
            Gui.SendMsgToActiveView("ViewSelection")

    def fix(self):
        finding = self.current()
        if not finding or not finding.fix:
            return
        self.doc.openTransaction(translate("ProfileBuilder", "Fix frame check finding"))
        try:
            message = check.apply_fix(self.doc, finding)
            self.doc.recompute()
            self.doc.commitTransaction()
        except Exception as exc:  # noqa: BLE001
            self.doc.abortTransaction()
            message = str(exc)
        if finding.fix[0] == "join" and finding.fix[2] > 0.01:
            message += translate("ProfileBuilder", ". The real fix is to snap the sketch vertex: "
                                 "the gap stays in the profile's length.")
        self.note.setText(message)
        self.refresh()

    def accept(self):
        Gui.Selection.clearSelection()
        Gui.Control.closeDialog()
        return True

    reject = accept

    def getStandardButtons(self):
        return int(QtWidgets.QDialogButtonBox.Close)


class CheckFrame:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(ICON_DIR, "CheckFrame.svg"),
            "MenuText": QT_TRANSLATE_NOOP("ProfileBuilder_CheckFrame", "Check frame..."),
            "ToolTip": QT_TRANSLATE_NOOP("ProfileBuilder_CheckFrame",
                                         "List what would otherwise pass silently: broken objects, profiles "
                                         "that overlap,\nends that nearly meet but have no joint, duplicate "
                                         "profiles, panel fit problems and more"),
        }

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.Control.activeDialog() is False

    def Activated(self):
        Gui.Control.showDialog(CheckPanel(App.ActiveDocument))


def quick_summary(doc):
    """A one-line console note after the cut list, or "" when the quick checks find nothing."""
    found = [f for f in check.run(doc, check.QUICK) if f.severity != "Error"]  # errors are in the cut list
    if not found:
        return ""
    return translate("ProfileBuilder", "{count} frame issue(s), e.g. {first}; see Check frame").format(
        count=len(found), first=found[0].text)


def register():
    Gui.addCommand("ProfileBuilder_CheckFrame", CheckFrame())
