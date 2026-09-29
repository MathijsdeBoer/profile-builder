"""GUI for carriages: the Carriage command and its task panel."""

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from . import feature, joints, linear, panels
from .feature import ICON_DIR
from .simple_panel import PropertyTaskPanel

FIELDS = ("Face", "CarriageLength", "EnvelopeWidth", "EnvelopeHeight", "Wrap", "EndStopLength",
          "RequiredStroke", "Run", "PositionMode", "PositionPercent", "Position",
          "BeltItem", "BeltPitch", "PulleyTeeth", "PulleyDiameter", "PulleyCentres", "ClampAllowance")
INTEGER_KINDS = ("App::PropertyInteger", "App::PropertyIntegerConstraint")
INTEGER_MAX = {"Run": 99, "PulleyTeeth": 1000}


class CarriageTaskPanel(PropertyTaskPanel):
    """Edits a carriage with live preview; shows the position in percent or as a distance."""

    def __init__(self, obj):
        super().__init__(obj, FIELDS, "Carriage", linear.carriage_info)
        percent = self.widgets["PositionPercent"]
        percent.blockSignals(True)
        try:
            percent.setRange(0, 100)
            percent.setDecimals(1)
            percent.setSuffix(" %")
            percent.setValue(obj.PositionPercent)
        finally:
            percent.blockSignals(False)
        self._shown["PositionPercent"] = self._read(percent)
        layout = self.form.layout()
        for name in ("PositionPercent", "Position"):
            label = layout.labelForField(self.widgets[name])
            if label is not None:
                label.setText("Position")
        self.widgets["PositionMode"].currentIndexChanged.connect(self._show_mode)
        self._show_mode()

    def _widget(self, name):
        if self.obj.getTypeIdOfProperty(name) in INTEGER_KINDS:
            w = QtWidgets.QSpinBox()
            w.setRange(0, INTEGER_MAX.get(name, 999999))
            w.setValue(getattr(self.obj, name))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self.changed)
            return w
        return super()._widget(name)

    def apply(self):
        super().apply()
        self._show_mode()

    def _show_mode(self, *_args):
        percent = self.widgets["PositionMode"].currentText() == "Percent"
        layout = self.form.layout()
        for name, visible in (("PositionPercent", percent), ("Position", not percent)):
            widget = self.widgets[name]
            widget.setVisible(visible)
            label = layout.labelForField(widget)
            if label is not None:
                label.setVisible(visible)


class CreateCarriage:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(ICON_DIR, "Carriage.svg"),
            "MenuText": "Carriage...",
            "ToolTip": ("Add a carriage that runs along the selected profile, and get its clear run and stroke.\n"
                        "Click the face it runs on to choose that side. Also select a solid (for example an\n"
                        "imported STEP carriage) to show it instead of the placeholder box."),
        }

    def IsActive(self):
        return (Gui.Control.activeDialog() is False
                and any(feature.is_profile(o) for o in Gui.Selection.getSelection()))

    def Activated(self):
        doc = App.ActiveDocument
        rail, face, body = None, "Top", None
        for sel in Gui.Selection.getSelectionEx():
            obj = sel.Object
            if feature.is_profile(obj):
                if rail is None:
                    rail = obj
                    picked = [p for p, sub in zip(sel.PickedPoints, sel.SubElementNames) if sub.startswith("Face")]
                    if picked:
                        try:
                            face = linear.face_at(rail, picked[0]) or face
                        except ValueError:
                            pass  # a broken path edge: the carriage reports it after creation
            elif (body is None and not (joints.is_joint(obj) or panels.is_panel(obj) or linear.is_carriage(obj))
                  and hasattr(obj, "Shape") and obj.Shape.Solids):
                body = obj
        if rail is None:
            return
        doc.openTransaction("Create carriage")
        carriage = linear.make_carriage(doc, rail, face, body=body)
        doc.recompute()
        doc.commitTransaction()
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(carriage, 0)
