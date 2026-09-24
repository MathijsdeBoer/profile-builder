"""Generic task panel that edits a few properties of one object with live preview."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets


def _label(name):
    out = ""
    for i, ch in enumerate(name):
        if ch.isupper() and i and not name[i - 1].isupper():
            out += " "
        out += ch
    return out[0] + out[1:].lower()


class PropertyTaskPanel:
    """Shows ``fields`` of ``obj``; changes apply immediately, Cancel undoes them."""

    def __init__(self, obj, fields, title, info=None):
        self.obj = obj
        self.doc = obj.Document
        self.info_func = info
        self.doc.openTransaction(f"Edit {obj.Label}")
        self.widgets = {}
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.apply)

        form = QtWidgets.QWidget()
        form.setWindowTitle(title)
        layout = QtWidgets.QFormLayout(form)
        for name in fields:
            widget = self._widget(name)
            layout.addRow(_label(name), widget)
            widget.setToolTip(obj.getDocumentationOfProperty(name))
            self.widgets[name] = widget
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        layout.addRow(self.info)
        self.form = form
        self._update_info()

    def _widget(self, name):
        kind = self.obj.getTypeIdOfProperty(name)
        value = getattr(self.obj, name)
        if kind == "App::PropertyEnumeration":
            w = QtWidgets.QComboBox()
            w.addItems(self.obj.getEnumerationsOfProperty(name))
            w.setCurrentText(value)
            w.currentIndexChanged.connect(self.changed)
        elif kind == "App::PropertyBool":
            w = QtWidgets.QCheckBox()
            w.setChecked(value)
            w.toggled.connect(self.changed)
        elif kind == "App::PropertyString":
            w = QtWidgets.QLineEdit(value)
            w.editingFinished.connect(self.changed)
        else:
            w = QtWidgets.QDoubleSpinBox()
            unit = {"App::PropertyLength": " mm", "App::PropertyDistance": " mm",
                    "App::PropertyAngle": " °"}.get(kind, "")
            w.setRange(0 if kind == "App::PropertyLength" else -1e6, 1e6)
            w.setDecimals(3 if kind == "App::PropertyFloat" else 2)
            w.setSuffix(unit)
            w.setValue(value.Value if hasattr(value, "Value") else value)
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self.changed)
        return w

    def changed(self, *_args):
        self._timer.start()

    def apply(self):
        for name, w in self.widgets.items():
            if isinstance(w, QtWidgets.QComboBox):
                value = w.currentText()
            elif isinstance(w, QtWidgets.QCheckBox):
                value = w.isChecked()
            elif isinstance(w, QtWidgets.QLineEdit):
                value = w.text()
            else:
                value = w.value()
            current = getattr(self.obj, name)
            if (current.Value if hasattr(current, "Value") else current) != value:
                setattr(self.obj, name, value)
        self.doc.recompute()
        self._update_info()

    def _update_info(self):
        if not self.obj.isValid():
            self.info.setText("<span style='color:#c33'>%s</span>" % _error_text(self.obj))
        elif self.info_func:
            self.info.setText(self.info_func(self.obj))

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self._timer.stop()
        self.apply()
        self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self._timer.stop()
        self.doc.abortTransaction()
        self.doc.recompute()
        self._close()
        return True

    def _close(self):
        gdoc = Gui.getDocument(self.doc.Name)
        if gdoc.getInEdit():
            gdoc.resetEdit()
        else:
            Gui.Control.closeDialog()


def _error_text(obj):
    try:
        return obj.getStatusString()
    except Exception:
        return "This object has an error; see the report view"
