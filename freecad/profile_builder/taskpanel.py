"""Task panel for creating and editing profiles, with live preview."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import feature, profiles

PARAMS = "User parameter:BaseApp/Preferences/Mod/ProfileBuilder"
CUSTOM = "Custom"
DIM_LABELS = {"VChamfer": "V chamfer", "BoreDiameter": "Centre bore"}


def _params():
    return App.ParamGet(PARAMS)


def _spin(value, minimum, maximum, suffix=" mm", decimals=2, step=1.0):
    box = QtWidgets.QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setValue(value)
    box.setKeyboardTracking(False)
    return box


def _combo(items, current=None):
    box = QtWidgets.QComboBox()
    for text, data in items:
        box.addItem(text, data)
    if current is not None:
        _select(box, current)
    return box


def _select(box, data):
    i = box.findData(data)
    if i >= 0:
        box.setCurrentIndex(i)


class ProfileTaskPanel:
    """Creates profiles (optionally one per edge) or edits an existing one.

    The objects are created straight away and updated while the dialog is
    open; Cancel rolls everything back through the undo transaction.
    """

    def __init__(self, edit=None, edges=None, series=None, cols=None, rows=None):
        self.doc = edit.Document if edit else (App.ActiveDocument or App.newDocument())
        self.edges = list(edges or [])
        self._updating = False
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.apply)

        self.doc.openTransaction("Edit profile" if edit else "Create profile")
        if edit:
            self.objects = [edit]
        else:
            p = _params()
            series = series or p.GetString("Series", profiles.DEFAULT_SERIES)
            if series not in profiles.SERIES:
                series = profiles.DEFAULT_SERIES
            cols = cols or p.GetInt("Columns", 1)
            rows = rows or p.GetInt("Rows", 1)
            length = p.GetFloat("Length", 1000.0)
            targets = self.edges or [None]
            self.objects = [feature.make_profile(series, cols, rows, length, self.doc, edge=e)
                            for e in targets]
            if not self.edges:
                for obj in self.objects:
                    obj.SlotStyle = p.GetString("SlotStyle", "T-slot")
                    obj.Weight = _saved_weight(p)
                    obj.Anchor = p.GetString("Anchor", "Center")
            else:
                for obj in self.objects:
                    obj.Anchor = p.GetString("EdgeAnchor", "Center")
                    obj.Weight = _saved_weight(p)

        self.edge_mode = bool(self.objects[0].PathEdge)
        self._build()
        self._load(self.objects[0])
        self.doc.recompute()
        self._update_info()

    # ---- UI -----------------------------------------------------------------

    def _build(self):
        obj = self.objects[0]
        main = QtWidgets.QWidget()
        if len(self.objects) > 1:
            title = f"{len(self.objects)} profiles on edges"
        else:
            title = "Profile" + (" on edge" if self.edge_mode else "")
        main.setWindowTitle(title)
        layout = QtWidgets.QFormLayout(main)

        self.series = _combo([(profiles.series_label(k), k) for k in profiles.SERIES])
        layout.addRow("Series", self.series)
        self.weight = _combo([(w, w) for w in profiles.WEIGHTS])
        for i, w in enumerate(profiles.WEIGHTS):
            self.weight.setItemData(i, profiles.WEIGHT_TIPS[w], QtCore.Qt.ToolTipRole)
        layout.addRow("Weight", self.weight)

        self.size = QtWidgets.QComboBox()
        layout.addRow("Size", self.size)
        grid = QtWidgets.QHBoxLayout()
        self.cols = QtWidgets.QSpinBox()
        self.cols.setRange(1, 20)
        self.rows = QtWidgets.QSpinBox()
        self.rows.setRange(1, 20)
        grid.addWidget(QtWidgets.QLabel("Cells X"))
        grid.addWidget(self.cols)
        grid.addWidget(QtWidgets.QLabel("Y"))
        grid.addWidget(self.rows)
        layout.addRow("", grid)

        self.style = _combo([(s, s) for s in profiles.SLOT_STYLES])
        layout.addRow("Slot style", self.style)

        self.preset = _combo([(name, name) for name, _faces in profiles.SLOT_PRESETS] + [(CUSTOM, CUSTOM)])
        layout.addRow("Slots", self.preset)
        faces = QtWidgets.QGridLayout()
        self.closed = {}
        for i, face in enumerate(profiles.FACES):
            box = QtWidgets.QCheckBox(face)
            self.closed[face] = box
            faces.addWidget(box, i // 2, i % 2)
        layout.addRow("Closed faces", faces)

        self.bore = QtWidgets.QCheckBox("Centre bore")
        self.corner = QtWidgets.QCheckBox("Corner chambers")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.bore)
        row.addWidget(self.corner)
        layout.addRow("", row)

        self.length = _spin(obj.Length.Value, 1, 100000, step=10)
        layout.addRow("Length", self.length)
        if self.edge_mode:
            self.length.setEnabled(False)
            self.length.setToolTip("Taken from the path edge")
            self.extend_start = _spin(0, -10000, 10000)
            self.extend_end = _spin(0, -10000, 10000)
            self.spin = _spin(0, -360, 360, suffix=" °", decimals=1, step=90)
            layout.addRow("Extend start", self.extend_start)
            layout.addRow("Extend end", self.extend_end)
            layout.addRow("Spin", self.spin)
        self.anchor = _combo([(a, a) for a in profiles.ANCHORS])
        layout.addRow("Anchor", self.anchor)

        self.miter_start = _spin(0, -79, 79, suffix=" °", decimals=1, step=5)
        self.miter_end = _spin(0, -79, 79, suffix=" °", decimals=1, step=5)
        self.miter_across = _combo([(a, a) for a in profiles.MITER_ACROSS])
        layout.addRow("Miter start", self.miter_start)
        layout.addRow("Miter end", self.miter_end)
        layout.addRow("Miter across", self.miter_across)

        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        layout.addRow(self.info)

        dims = QtWidgets.QWidget()
        dims.setWindowTitle("Section dimensions")
        dlayout = QtWidgets.QFormLayout(dims)
        note = QtWidgets.QLabel("Defaults of the series; override to match a specific manufacturer.")
        note.setWordWrap(True)
        dlayout.addRow(note)
        self.dims = {}
        for name, _attr, tip in feature.DIMENSIONS:
            box = _spin(0, 0, 500, step=0.1)
            box.setToolTip(tip)
            self.dims[name] = box
            dlayout.addRow(DIM_LABELS.get(name) or _split_camel(name), box)
        reset = QtWidgets.QPushButton("Reset to series defaults")
        reset.clicked.connect(self._reset_dims)
        dlayout.addRow(reset)

        self.form = [main, dims]

        self.series.currentIndexChanged.connect(self._series_changed)
        self.weight.currentIndexChanged.connect(self._weight_changed)
        self.size.currentIndexChanged.connect(self._size_changed)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        for box in self.closed.values():
            box.toggled.connect(self._closed_changed)
        for w in (self.cols, self.rows):
            w.valueChanged.connect(self._cells_changed)
        for w in (self.style, self.anchor, self.miter_across):
            w.currentIndexChanged.connect(self.changed)
        for w in (self.bore, self.corner):
            w.toggled.connect(self.changed)
        spins = [self.length, self.miter_start, self.miter_end, *self.dims.values()]
        if self.edge_mode:
            spins += [self.extend_start, self.extend_end, self.spin]
        for w in spins:
            w.valueChanged.connect(self.changed)

    def _load(self, obj):
        self._updating = True
        try:
            _select(self.series, obj.Series)
            _select(self.weight, obj.Weight)
            self._fill_sizes(obj.Series)
            self.cols.setValue(obj.Columns)
            self.rows.setValue(obj.Rows)
            self._sync_size()
            _select(self.style, obj.SlotStyle)
            for face, box in self.closed.items():
                box.setChecked(getattr(obj, f"Closed{face}"))
            self._sync_preset()
            self.bore.setChecked(obj.CenterBore)
            self.corner.setChecked(obj.CornerHoles)
            self.length.setValue(obj.Length.Value)
            _select(self.anchor, obj.Anchor)
            self.miter_start.setValue(obj.MiterStart.Value)
            self.miter_end.setValue(obj.MiterEnd.Value)
            _select(self.miter_across, obj.MiterAcross)
            if self.edge_mode:
                self.extend_start.setValue(obj.ExtendStart.Value)
                self.extend_end.setValue(obj.ExtendEnd.Value)
                self.spin.setValue(obj.Spin.Value)
            for name, box in self.dims.items():
                box.setValue(getattr(obj, name).Value)
        finally:
            self._updating = False

    def _fill_sizes(self, key):
        series = profiles.SERIES[key]
        self.size.blockSignals(True)
        self.size.clear()
        for cols, rows in series.sizes:
            # Qt cannot look up tuples with findData, so sizes are keyed "CxR".
            self.size.addItem(series.designation(cols, rows), f"{cols}x{rows}")
            if cols != rows:
                # Same profile lying on its side, e.g. 4020.
                self.size.addItem(f"{series.designation(cols, rows)} (on side)", f"{rows}x{cols}")
        self.size.addItem(CUSTOM, None)
        self.size.blockSignals(False)

    def _sync_size(self):
        self.size.blockSignals(True)
        i = self.size.findData(f"{self.cols.value()}x{self.rows.value()}")
        self.size.setCurrentIndex(i if i >= 0 else self.size.count() - 1)
        self.size.blockSignals(False)

    def _sync_preset(self):
        closed = [f for f, b in self.closed.items() if b.isChecked()]
        name = profiles.preset_for_closed_faces(closed) or CUSTOM
        self.preset.blockSignals(True)
        _select(self.preset, name)
        self.preset.blockSignals(False)

    # ---- signal handlers ----------------------------------------------------

    def _series_changed(self):
        if self._updating:
            return
        key = self.series.currentData()
        self._fill_sizes(key)
        self._sync_size()
        self._reset_dims()

    def _weight_changed(self):
        if not self._updating:
            self._reset_dims()

    def _reset_dims(self):
        dims = profiles.SERIES[self.series.currentData()].dimensions(self.weight.currentData())
        self._updating = True
        for name, attr, _tip in feature.DIMENSIONS:
            self.dims[name].setValue(dims[attr])
        self.corner.setChecked(dims["corner_hole"] > 0 or dims["chamber_wall"] > 0)
        self._updating = False
        self.changed()

    def _size_changed(self):
        data = self.size.currentData()
        if not data:
            return
        cols, rows = (int(n) for n in data.split("x"))
        self._updating = True
        self.cols.setValue(cols)
        self.rows.setValue(rows)
        self._updating = False
        self.changed()

    def _cells_changed(self):
        if self._updating:
            return
        self._sync_size()
        self.changed()

    def _preset_changed(self):
        name = self.preset.currentData()
        if name == CUSTOM:
            return
        closed = profiles.closed_faces_for_preset(name)
        self._updating = True
        for face, box in self.closed.items():
            box.setChecked(face in closed)
        self._updating = False
        self.changed()

    def _closed_changed(self):
        if self._updating:
            return
        self._sync_preset()
        self.changed()

    def changed(self, *_args):
        if not self._updating:
            self._timer.start()

    # ---- model --------------------------------------------------------------

    def apply(self):
        key = self.series.currentData()
        for obj in self.objects:
            if obj.Series != key:
                obj.Series = key
            if obj.Weight != self.weight.currentData():
                obj.Weight = self.weight.currentData()
            obj.Columns = self.cols.value()
            obj.Rows = self.rows.value()
            obj.SlotStyle = self.style.currentData()
            for face, box in self.closed.items():
                setattr(obj, f"Closed{face}", box.isChecked())
            obj.CenterBore = self.bore.isChecked()
            obj.CornerHoles = self.corner.isChecked()
            obj.Anchor = self.anchor.currentData()
            obj.MiterStart = self.miter_start.value()
            obj.MiterEnd = self.miter_end.value()
            obj.MiterAcross = self.miter_across.currentData()
            if self.edge_mode:
                obj.ExtendStart = self.extend_start.value()
                obj.ExtendEnd = self.extend_end.value()
                obj.Spin = self.spin.value()
            else:
                obj.Length = self.length.value()
            for name, box in self.dims.items():
                setattr(obj, name, box.value())
            if feature.is_auto_label(obj.Label):
                obj.Label = feature.auto_label(obj)
        self.doc.recompute()
        self._update_info()

    def _update_info(self):
        obj = self.objects[0]
        problems = profiles.validate(feature.dimensions(obj), obj.SlotStyle)
        if problems:
            self.info.setText("<span style='color:#c33'>" + "<br>".join(problems) + "</span>")
            return
        series = profiles.SERIES[obj.Series]
        total = sum(o.Mass for o in self.objects)
        text = (f"<b>{obj.Designation}</b><br>"
                f"Section {obj.SectionArea.Value:.1f} mm², {obj.MassPerMeter:.3f} kg/m<br>"
                f"Saw length {obj.OverallLength.Value:.1f} mm")
        if series.tappable(obj.Weight):
            text += f"<br>Centre bore for {series.tap} tapping"
        elif series.tap:
            text += f"<br>Centre bore Ø{obj.BoreDiameter.Value:g} mm, cannot be tapped"
        if len(self.objects) > 1:
            text += f"<br>{len(self.objects)} pieces, {total:.2f} kg total"
        self.info.setText(text)

    # ---- task dialog API ----------------------------------------------------

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self._timer.stop()
        self.apply()
        self.doc.commitTransaction()
        p = _params()
        obj = self.objects[0]
        p.SetString("Series", obj.Series)
        p.SetInt("Columns", obj.Columns)
        p.SetInt("Rows", obj.Rows)
        p.SetString("SlotStyle", obj.SlotStyle)
        p.SetString("Weight", obj.Weight)
        if self.edge_mode:
            p.SetString("EdgeAnchor", obj.Anchor)
        else:
            p.SetFloat("Length", obj.Length.Value)
            p.SetString("Anchor", obj.Anchor)
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
            gdoc.resetEdit()  # closes the dialog through unsetEdit
        else:
            Gui.Control.closeDialog()


def _saved_weight(p):
    weight = p.GetString("Weight", "Standard")
    return weight if weight in profiles.WEIGHTS else "Standard"


def _split_camel(name):
    out = ""
    for i, ch in enumerate(name):
        if ch.isupper() and i and not name[i - 1].isupper():
            out += " "
        out += ch
    return out[0] + out[1:].lower()
