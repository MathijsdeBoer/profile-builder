"""Task panel for creating a box frame."""

import html
import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import box_frame, cutlist, feature, profiles, skeleton
from .taskpanel import PARAMS, _set

translate = App.Qt.translate


def _length_text(value):
    return App.Units.Quantity(value, App.Units.Length).UserString


def _parse_length(text, shown):
    """Length in mm from text such as '600 mm', '2 ft' or 1' 11" + 5/8".

    A bare number is in the unit the field shows for ``shown`` mm. That is not
    always the unit FreeCAD picks for 1 mm: US customary shows feet, but thou for 1 mm.
    """
    text = text.strip().replace(",", ".")
    try:
        quantity = App.Units.Quantity(text)
    except (ValueError, ArithmeticError):
        # Building US shows 1' 11" + 5/8", which the parser only reads without the plus.
        quantity = App.Units.Quantity(text.replace("+", " "))
    if quantity.Unit == App.Units.Quantity("1 mm").Unit:
        return quantity.Value
    if quantity.Unit == App.Units.Unit():
        _text, factor, _name = App.Units.Quantity(abs(shown) or 1.0, App.Units.Length).getUserPreferred()
        return quantity.Value * factor
    raise ValueError("Enter a length")


def _size_items(key):
    series = profiles.SERIES[key]
    items = []
    seen = set()
    for columns, rows in series.sizes:
        for c, r, side in ((columns, rows, False), (rows, columns, True)):
            size = f"{c}x{r}"
            if size in seen:
                continue
            seen.add(size)
            label = series.designation(c, r)
            if side:
                label = translate("ProfileBuilder", "{size} (on side)").format(size=label)
            items.append((label, size))
    return items


def _combo(items, current):
    box = QtWidgets.QComboBox()
    for text, data in items:
        box.addItem(text, data)
    index = box.findData(current)
    if index >= 0:
        box.setCurrentIndex(index)
    return box


def _size_values(key):
    items = _size_items(key)
    return {data for _text, data in items}


def _saved_size(params, series, columns_key, rows_key):
    columns = params.GetInt(columns_key, 1)
    rows = params.GetInt(rows_key, 1)
    size = f"{columns}x{rows}"
    if size not in _size_values(series):
        return 1, 1
    return columns, rows


class BoxFrameTaskPanel:
    def __init__(self):
        self.doc = App.ActiveDocument or App.newDocument()
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.apply)
        self._lengths = {}  # field: (text it was filled with, exact value in mm)

        self.defaults = self._load_defaults()
        self.doc.openTransaction("Create box frame")
        try:
            (self.skeleton, self.members, self.created_joints,
             self.warnings) = box_frame.make_box(self.doc, **self.defaults)
        except Exception:
            self.doc.abortTransaction()
            raise
        self.rails = self.members[:8]
        self.posts = self.members[8:]
        self._build()
        self.doc.recompute()
        self._update_summary()

    @staticmethod
    def _load_defaults():
        params = App.ParamGet(PARAMS)
        default_series = params.GetString("Series", profiles.DEFAULT_SERIES)
        if default_series not in profiles.SERIES:
            default_series = profiles.DEFAULT_SERIES

        def series(key):
            value = params.GetString(key, default_series)
            return value if value in profiles.SERIES else default_series

        post_series = series("BoxPostSeries")
        rail_series = series("BoxRailSeries")
        post_cols, post_rows = _saved_size(params, post_series, "BoxPostColumns", "BoxPostRows")
        rail_cols, rail_rows = _saved_size(params, rail_series, "BoxRailColumns", "BoxRailRows")
        post_cell, rail_cell = profiles.SERIES[post_series].cell, profiles.SERIES[rail_series].cell
        if skeleton.rails_collide(post_cols * post_cell, post_rows * post_cell, rail_cols * rail_cell):
            # Saved by a version that allowed it: start with rails like the posts instead.
            rail_series, rail_cols, rail_rows = post_series, post_cols, post_rows
        default_weight = params.GetString("Weight", "Standard")
        if default_weight not in profiles.WEIGHTS:
            default_weight = "Standard"
        post_weight = params.GetString("BoxPostWeight", default_weight)
        if post_weight not in profiles.WEIGHTS:
            post_weight = default_weight
        rail_weight = params.GetString("BoxRailWeight", default_weight)
        if rail_weight not in profiles.WEIGHTS:
            rail_weight = default_weight
        slot_style = params.GetString("BoxSlotStyle", params.GetString("SlotStyle", "T-slot"))
        if slot_style not in profiles.SLOT_STYLES:
            slot_style = "T-slot"
        size_mode = params.GetString("BoxSizeMode", "Outside")
        if size_mode not in skeleton.SIZE_MODES:
            size_mode = "Outside"

        return {
            "width": params.GetFloat("BoxWidth", 600.0),
            "depth": params.GetFloat("BoxDepth", 600.0),
            "height": params.GetFloat("BoxHeight", 700.0),
            "size_mode": size_mode,
            "post_series": post_series,
            "post_cols": post_cols,
            "post_rows": post_rows,
            "rail_series": rail_series,
            "rail_cols": rail_cols,
            "rail_rows": rail_rows,
            "post_weight": post_weight,
            "rail_weight": rail_weight,
            "slot_style": slot_style,
        }

    def _build(self):
        form = QtWidgets.QWidget()
        form.setWindowTitle(translate("ProfileBuilder", "Box frame"))
        layout = QtWidgets.QFormLayout(form)

        self.width = self._length_field(self.defaults["width"])
        self.depth = self._length_field(self.defaults["depth"])
        self.height = self._length_field(self.defaults["height"])
        layout.addRow(translate("ProfileBuilder", "Width"), self.width)
        layout.addRow(translate("ProfileBuilder", "Depth"), self.depth)
        layout.addRow(translate("ProfileBuilder", "Height"), self.height)

        mode_items = (
            (translate("ProfileBuilder", "Outside dimensions"), "Outside"),
            (translate("ProfileBuilder", "Inside clear dimensions"), "Inside clear"),
            (translate("ProfileBuilder", "Centre-line dimensions"), "Centre lines"),
        )
        self.size_mode = _combo(mode_items, self.defaults["size_mode"])
        layout.addRow(translate("ProfileBuilder", "Dimension mode"), self.size_mode)

        series_items = [(profiles.series_label(key), key) for key in profiles.SERIES]
        self.post_series = _combo(series_items, self.defaults["post_series"])
        self.post_size = _combo(
            _size_items(self.defaults["post_series"]),
            f"{self.defaults['post_cols']}x{self.defaults['post_rows']}")
        layout.addRow(translate("ProfileBuilder", "Post series"), self.post_series)
        layout.addRow(translate("ProfileBuilder", "Post size"), self.post_size)

        self.rail_series = _combo(series_items, self.defaults["rail_series"])
        self.rail_size = _combo(
            _size_items(self.defaults["rail_series"]),
            f"{self.defaults['rail_cols']}x{self.defaults['rail_rows']}")
        layout.addRow(translate("ProfileBuilder", "Rail series"), self.rail_series)
        layout.addRow(translate("ProfileBuilder", "Rail size"), self.rail_size)

        weight_items = [(weight, weight) for weight in profiles.WEIGHTS]
        self.post_weight = _combo(weight_items, self.defaults["post_weight"])
        self.rail_weight = _combo(weight_items, self.defaults["rail_weight"])
        layout.addRow(translate("ProfileBuilder", "Post weight"), self.post_weight)
        layout.addRow(translate("ProfileBuilder", "Rail weight"), self.rail_weight)

        style_items = [(style, style) for style in profiles.SLOT_STYLES]
        self.slot_style = _combo(style_items, self.defaults["slot_style"])
        layout.addRow(translate("ProfileBuilder", "Slot style"), self.slot_style)

        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        layout.addRow(self.info)
        note = QtWidgets.QLabel(translate(
            "ProfileBuilder",
            "Lengths accept FreeCAD units. Vertical posts run through butt joints; changing the joint rule can alter the frame size."))
        note.setWordWrap(True)
        layout.addRow(note)
        self.form = [form]

        for widget in (self.width, self.depth, self.height):
            widget.textChanged.connect(self.changed)
        for widget in (self.size_mode, self.post_series, self.post_size,
                       self.rail_series, self.rail_size, self.post_weight,
                       self.rail_weight, self.slot_style):
            widget.currentIndexChanged.connect(self.changed)
        self.post_series.currentIndexChanged.connect(self._post_series_changed)
        self.rail_series.currentIndexChanged.connect(self._rail_series_changed)

    def _length_field(self, value):
        widget = QtWidgets.QLineEdit(_length_text(value))
        self._lengths[widget] = (widget.text(), value)
        return widget

    def _length(self, widget):
        """A field's length in mm: the exact value it was filled with until its text is changed.

        The text is rounded, and in some schemas (Building US) the parser cannot read it back.
        """
        text, value = self._lengths[widget]
        if widget.text() == text:
            return value
        return _parse_length(widget.text(), value)

    def _fill_size(self, widget, series, previous):
        widget.blockSignals(True)
        widget.clear()
        for text, data in _size_items(series):
            widget.addItem(text, data)
        index = widget.findData(previous)
        widget.setCurrentIndex(index if index >= 0 else 0)
        widget.blockSignals(False)

    def _post_series_changed(self):
        self._fill_size(self.post_size, self.post_series.currentData(), self.post_size.currentData())
        self.changed()

    def _rail_series_changed(self):
        self._fill_size(self.rail_size, self.rail_series.currentData(), self.rail_size.currentData())
        self.changed()

    def changed(self, *_args):
        self._timer.start()

    def _update_profiles(self, members, series, cols, rows, weight):
        for member in members:
            _set(member, "Series", series)
            _set(member, "Weight", weight)
            _set(member, "Columns", cols)
            _set(member, "Rows", rows)
            _set(member, "SlotStyle", self.slot_style.currentData())

    def apply(self):
        try:
            dimensions = tuple(self._length(widget) for widget in (self.width, self.depth, self.height))
        except (ValueError, ArithmeticError):
            self.info.setText("<span style='color:#c33'>" + html.escape(
                translate("ProfileBuilder", "Enter a valid length for width, depth and height.")) + "</span>")
            return False
        if not all(math.isfinite(value) and value > 0 for value in dimensions):
            self.info.setText("<span style='color:#c33'>" + html.escape(
                translate("ProfileBuilder", "Width, depth and height must be positive.")) + "</span>")
            return False

        post_cols, post_rows = (int(value) for value in self.post_size.currentData().split("x"))
        rail_cols, rail_rows = (int(value) for value in self.rail_size.currentData().split("x"))
        post_series, rail_series = self.post_series.currentData(), self.rail_series.currentData()
        post_weight, rail_weight = self.post_weight.currentData(), self.rail_weight.currentData()
        post_cell = profiles.SERIES[post_series].cell
        rail_cell = profiles.SERIES[rail_series].cell
        if skeleton.rails_collide(post_cols * post_cell, post_rows * post_cell, rail_cols * rail_cell):
            self.info.setText("<span style='color:#c33'>" + html.escape(translate(
                "ProfileBuilder",
                "Rails wider than the posts in both directions collide at the corners. Choose posts at least as wide as the rails in one direction, or narrower rails.")) +
                "</span>")
            return False

        _set(self.skeleton, "Width", dimensions[0])
        _set(self.skeleton, "Depth", dimensions[1])
        _set(self.skeleton, "Height", dimensions[2])
        _set(self.skeleton, "SizeMode", self.size_mode.currentData())
        self._update_profiles(self.posts, post_series, post_cols, post_rows, post_weight)
        self._update_profiles(self.rails, rail_series, rail_cols, rail_rows, rail_weight)
        _set(self.skeleton, "FallbackPostWidth", post_cols * post_cell)
        _set(self.skeleton, "FallbackPostDepth", post_rows * post_cell)
        _set(self.skeleton, "FallbackRailWidth", rail_cols * rail_cell)
        _set(self.skeleton, "FallbackRailHeight", rail_rows * rail_cell)

        self.doc.recompute()
        return self._update_summary()

    def _update_summary(self):
        if not self.skeleton.isValid():
            message = self.skeleton.getStatusString()
            self.info.setText("<span style='color:#c33'>" + html.escape(message) + "</span>")
            return False
        for member in self.members:
            problem = feature.problem(member)
            if problem:
                self.info.setText("<span style='color:#c33'>" + html.escape(
                    f"{member.Label}: {problem}") + "</span>")
                return False

        mode = self.skeleton.SizeMode
        label = {
            "Outside": translate("ProfileBuilder", "Outside size"),
            "Inside clear": translate("ProfileBuilder", "Inside clear size"),
        }.get(mode, translate("ProfileBuilder", "Centre-line size"))
        measured = skeleton.measured_size(self.skeleton)
        requested = (self.skeleton.Width.Value, self.skeleton.Depth.Value, self.skeleton.Height.Value)
        lines = []
        if measured is not None:
            actual_text = " × ".join(_length_text(value) for value in measured)
            lines.append(translate("ProfileBuilder", "{label}: {dimensions}").format(
                label=label, dimensions=actual_text))

        groups = []
        names = {member.Name for member in self.members}
        for key, members in cutlist.collect(self.doc).items():
            count = sum(member.Name in names for member in members)
            if count:
                length = _length_text(key[1])
                groups.append(translate("ProfileBuilder", "{count} × {length} ({product})").format(
                    count=count, length=length, product=key[0]))
        lines.append(translate("ProfileBuilder", "Cut lengths: {groups}").format(
            groups=", ".join(groups)))
        if measured is not None and any(abs(actual - wanted) > 0.01
                                        for actual, wanted in zip(measured, requested)):
            lines.append("<span style='color:#c60'>" + html.escape(translate(
                "ProfileBuilder",
                "Measured size differs from the requested size. Check profile anchors, spins and joint settings.")) +
                "</span>")
        if self.warnings:
            lines.extend("<span style='color:#c60'>" + html.escape(warning) + "</span>"
                         for warning in self.warnings)
        self.info.setText("<br>".join(lines))
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self._timer.stop()
        if not self.apply():
            return False
        self.doc.commitTransaction()
        params = App.ParamGet(PARAMS)
        params.SetFloat("BoxWidth", self.skeleton.Width.Value)
        params.SetFloat("BoxDepth", self.skeleton.Depth.Value)
        params.SetFloat("BoxHeight", self.skeleton.Height.Value)
        params.SetString("BoxSizeMode", self.skeleton.SizeMode)
        params.SetString("BoxPostSeries", self.post_series.currentData())
        params.SetInt("BoxPostColumns", self.posts[0].Columns)
        params.SetInt("BoxPostRows", self.posts[0].Rows)
        params.SetString("BoxRailSeries", self.rails[0].Series)
        params.SetInt("BoxRailColumns", self.rails[0].Columns)
        params.SetInt("BoxRailRows", self.rails[0].Rows)
        params.SetString("BoxPostWeight", self.posts[0].Weight)
        params.SetString("BoxRailWeight", self.rails[0].Weight)
        params.SetString("BoxSlotStyle", self.posts[0].SlotStyle)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.skeleton)
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
