"""Frame stiffness command and task panel (GUI)."""

import html
import json
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import cutlist
from . import frame_stiffness as fs
from .feature import ICON_DIR

SUPPORT_TEXT = {"Pinned": "Pinned (standing on feet or the floor)", "Fixed": "Fixed (bolted down stiffly)"}


def open_panel(doc):
    # Recompute before the panel opens its transaction, so Cancel does not undo it.
    cutlist.recompute_if_needed(doc)
    Gui.Control.showDialog(FrameStiffnessPanel(doc))


class FrameStiffness:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(ICON_DIR, "FrameStiffness.svg"),
            "MenuText": "Frame stiffness...",
            "ToolTip": ("Estimate how stiff the frame is sideways and in twist, and its first natural\n"
                        "frequencies, as a range between loose and stiff joints.\n"
                        "Store a baseline to compare design variants."),
        }

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.Control.activeDialog() is False

    def Activated(self):
        open_panel(App.ActiveDocument)


class FrameStiffnessPanel:
    """Settings of the estimate with live results. OK keeps the settings and baseline, Cancel undoes them."""

    def __init__(self, doc):
        self.doc = doc
        self.doc.openTransaction("Frame stiffness")
        self.settings = fs.get_settings(doc, create=True)
        self.result = None
        self._printed = None
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.apply)

        s = self.settings
        form = QtWidgets.QWidget()
        form.setWindowTitle("Frame stiffness")
        layout = QtWidgets.QVBoxLayout(form)
        intro = QtWidgets.QLabel(
            "<b>Estimates.</b> The stiffness of T-slot joints is not known, so every value is a range "
            "between loose joints and stiff joints. Compare designs rather than trusting single numbers.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        box = QtWidgets.QGroupBox("Assumptions")
        grid = QtWidgets.QFormLayout(box)
        self.loose = QtWidgets.QDoubleSpinBox()
        self.loose.setRange(0.01, 100)
        self.loose.setDecimals(2)
        self.loose.setSingleStep(0.1)
        self.loose.setSuffix(" × E·I/L")
        self.loose.setValue(s.LooseJointFactor)
        self.loose.setToolTip(s.getDocumentationOfProperty("LooseJointFactor"))
        self.stiff = QtWidgets.QDoubleSpinBox()
        self.stiff.setRange(0, 1000)
        self.stiff.setDecimals(1)
        self.stiff.setSuffix(" × E·I/L")
        self.stiff.setSpecialValueText("rigid")  # shown at the minimum, 0
        self.stiff.setValue(s.StiffJointFactor)
        self.stiff.setToolTip(s.getDocumentationOfProperty("StiffJointFactor"))
        self.supports = QtWidgets.QComboBox()
        for key in fs.SUPPORTS:
            self.supports.addItem(SUPPORT_TEXT.get(key, key), key)
        self.supports.setCurrentIndex(max(0, self.supports.findData(s.Supports)))
        self.supports.setToolTip(s.getDocumentationOfProperty("Supports"))
        self.top_mass = QtWidgets.QLineEdit(fs.mass_text(s.TopMass.Value))
        self.top_mass.setToolTip(s.getDocumentationOfProperty("TopMass") + "\nFor example 5 kg or 11 lb.")
        self._mass_shown = self.top_mass.text()
        # The spin boxes round what they show (and clamp it to their range);
        # only a value the user changed is written back, so a stored 12.34
        # does not become 12.3 when another setting changes.
        self._factors = {"LooseJointFactor": self.loose, "StiffJointFactor": self.stiff}
        self._factors_shown = {name: w.value() for name, w in self._factors.items()}
        for w in (self.loose, self.stiff):
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self.changed)
        self.supports.currentIndexChanged.connect(self.changed)
        self.top_mass.editingFinished.connect(self._mass_edited)
        grid.addRow("Loose joints", self.loose)
        grid.addRow("Stiff joints", self.stiff)
        grid.addRow("Supports (lowest nodes)", self.supports)
        grid.addRow("Mass on top", self.top_mass)
        layout.addWidget(box)

        self.view = QtWidgets.QLabel()
        self.view.setWordWrap(True)
        self.view.setTextFormat(QtCore.Qt.RichText)
        self.view.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.view)

        buttons = QtWidgets.QHBoxLayout()
        self.set_button = QtWidgets.QPushButton("Set as baseline")
        self.set_button.setToolTip("Store these results in the document, to compare later variants with")
        self.set_button.clicked.connect(self.set_baseline)
        self.clear_button = QtWidgets.QPushButton("Clear baseline")
        self.clear_button.clicked.connect(self.clear_baseline)
        report = QtWidgets.QPushButton("Print report")
        report.setToolTip("Write the results to the report view")
        report.clicked.connect(self.print_report)
        for b in (self.set_button, self.clear_button, report):
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.form = form
        self.run()
        self.print_report()

    # ---- settings ---------------------------------------------------------------------

    def changed(self, *_args):
        self._timer.start()

    def _mass_edited(self):
        if self.top_mass.text() == self._mass_shown:
            return  # focus left without an edit; do not round the stored value
        if fs.parse_mass(self.top_mass.text()) is None:
            self.top_mass.setStyleSheet("color: #c33")
            return
        self.top_mass.setStyleSheet("")
        self._mass_shown = self.top_mass.text()
        self.changed()

    def _write(self):
        s = self.settings
        for name, widget in self._factors.items():
            value = widget.value()
            if value != self._factors_shown[name]:
                setattr(s, name, value)
                self._factors_shown[name] = value
        if s.Supports != self.supports.currentData():
            s.Supports = self.supports.currentData()
        mass = fs.parse_mass(self._mass_shown)
        if mass is not None and abs(s.TopMass.Value - mass) > 1e-12:
            s.TopMass = mass

    def apply(self):
        self._write()
        self.run()

    def flush(self):
        """Apply a change still waiting for the debounce timer, so buttons act on what the panel shows."""
        if self._timer.isActive():
            self._timer.stop()
            self.apply()

    # ---- results ------------------------------------------------------------------------

    def run(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.result = fs.analyse(self.doc)
            error = None
        except ValueError as e:  # nothing to analyse, or numpy/scipy missing
            self.result, error = None, str(e)
        except Exception as e:  # noqa: BLE001 - never leave the panel (and its transaction) half built
            import traceback
            App.Console.PrintError(traceback.format_exc())
            self.result, error = None, f"The analysis failed: {e}"
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._show(error)

    def _show(self, error=None):
        base = fs.baseline(self.doc)
        if self.result is None:
            self.view.setText(f"<span style='color:#c33'>{html.escape(error or '', quote=False)}</span>")
        else:
            self.view.setText(fs.report_html(self.result, base))
        self.set_button.setEnabled(self.result is not None)
        self.clear_button.setEnabled(base is not None)

    def set_baseline(self):
        self.flush()
        if self.result is None:
            return
        fs.set_baseline(self.doc, self.result)
        self._show()
        App.Console.PrintMessage("Profile Builder: frame stiffness baseline stored in the document\n")

    def clear_baseline(self):
        fs.clear_baseline(self.doc)
        self._show()

    def print_report(self):
        self.flush()
        if self.result is None:
            return
        text = fs.report_text(self.result, fs.baseline(self.doc))
        App.Console.PrintMessage(text + "\n")
        self._printed = json.dumps(self.result, sort_keys=True)

    # ---- task panel -----------------------------------------------------------------------

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self.flush()
        self.doc.commitTransaction()
        if self.result is not None and json.dumps(self.result, sort_keys=True) != self._printed:
            self.print_report()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._timer.stop()
        self.doc.abortTransaction()
        Gui.Control.closeDialog()
        return True
