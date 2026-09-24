"""Task panel for prices, stock lengths and delivery costs."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import cutlist, feature, panels, pricing


def _spin(value, maximum=1e6, decimals=2, suffix=""):
    box = QtWidgets.QDoubleSpinBox()
    box.setRange(0, maximum)
    box.setDecimals(decimals)
    box.setSuffix(suffix)
    box.setValue(value)
    box.setKeyboardTracking(False)
    return box


def _table(headers):
    table = QtWidgets.QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.setMinimumHeight(140)
    return table


def _set_rows(table, keys, columns):
    """Fill a table: first column read-only key, other columns from dicts."""
    table.blockSignals(True)
    table.setRowCount(len(keys))
    for r, key in enumerate(keys):
        item = QtWidgets.QTableWidgetItem(key)
        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
        table.setItem(r, 0, item)
        for c, mapping in enumerate(columns, start=1):
            table.setItem(r, c, QtWidgets.QTableWidgetItem(str(mapping.get(key, ""))))
    table.blockSignals(False)


def _read_column(table, column):
    out = {}
    for r in range(table.rowCount()):
        key = table.item(r, 0).text()
        text = table.item(r, column).text().strip() if table.item(r, column) else ""
        if text:
            out[key] = text
    return out


class PricingTaskPanel:
    def __init__(self, doc=None):
        self.doc = doc or App.ActiveDocument
        self.doc.openTransaction("Pricing & stock")
        self.settings = pricing.get_settings(self.doc, create=True)
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.apply)

        s = self.settings
        purchase = QtWidgets.QWidget()
        purchase.setWindowTitle("Purchase")
        form = QtWidgets.QFormLayout(purchase)
        self.currency = QtWidgets.QLineEdit(s.Currency)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(pricing.PURCHASE_MODES)
        self.mode.setCurrentText(s.PurchaseMode)
        self.stock_length = _spin(s.StockLength.Value, 100000, 0, " mm")
        self.kerf = _spin(s.Kerf.Value, 50, 2, " mm")
        self.end_trim = _spin(s.EndTrim.Value, 1000, 1, " mm")
        self.cut_cost = _spin(s.CutCost)
        form.addRow("Currency", self.currency)
        form.addRow("Buy as", self.mode)
        form.addRow("Stock bar length", self.stock_length)
        form.addRow("Saw kerf", self.kerf)
        form.addRow("End trim per bar", self.end_trim)
        form.addRow("Cutting cost / piece", self.cut_cost)

        delivery = QtWidgets.QWidget()
        delivery.setWindowTitle("Delivery and tax")
        form = QtWidgets.QFormLayout(delivery)
        self.delivery_flat = _spin(s.DeliveryFlat)
        self.delivery_kg = _spin(s.DeliveryPerKg)
        self.free_above = _spin(s.FreeDeliveryAbove)
        self.tax = _spin(s.TaxPercent, 100, 1, " %")
        form.addRow("Delivery per order", self.delivery_flat)
        form.addRow("Delivery per kg", self.delivery_kg)
        form.addRow("Free delivery above", self.free_above)
        form.addRow("Tax", self.tax)

        prices = QtWidgets.QWidget()
        prices.setWindowTitle("Prices")
        layout = QtWidgets.QVBoxLayout(prices)
        layout.addWidget(QtWidgets.QLabel("Profiles (bar length empty: use the default)"))
        self.profile_table = _table(["Product", "Price / m", "Bar length (mm)"])
        layout.addWidget(self.profile_table)
        layout.addWidget(QtWidgets.QLabel("Sheets"))
        self.sheet_table = _table(["Sheet", "Price / m²"])
        layout.addWidget(self.sheet_table)
        buttons = QtWidgets.QHBoxLayout()
        save = QtWidgets.QPushButton("Save as my defaults")
        save.setToolTip(f"New documents start from these values ({pricing.defaults_path()})")
        save.clicked.connect(self.save_defaults)
        load = QtWidgets.QPushButton("Load my defaults")
        load.clicked.connect(self.load_defaults)
        buttons.addWidget(save)
        buttons.addWidget(load)
        layout.addLayout(buttons)
        self.estimate = QtWidgets.QLabel()
        self.estimate.setWordWrap(True)
        layout.addWidget(self.estimate)
        self._fill_tables()

        self.form = [purchase, delivery, prices]
        for w in (self.stock_length, self.kerf, self.end_trim, self.cut_cost, self.delivery_flat,
                  self.delivery_kg, self.free_above, self.tax):
            w.valueChanged.connect(self.changed)
        self.mode.currentIndexChanged.connect(self.changed)
        self.currency.editingFinished.connect(self.changed)
        self.profile_table.itemChanged.connect(self.changed)
        self.sheet_table.itemChanged.connect(self.changed)
        self._update_estimate()

    def _fill_tables(self):
        s = self.settings
        products = sorted({feature.product_key(o) for o in self.doc.Objects if feature.is_profile(o)})
        extra = sorted(set(s.ProfilePrices) - set(products))
        _set_rows(self.profile_table, products + extra, [s.ProfilePrices, s.StockLengths])
        sheets = sorted({panels.sheet_key(o) for o in self.doc.Objects if panels.is_panel(o)})
        extra = sorted(set(s.SheetPrices) - set(sheets))
        _set_rows(self.sheet_table, sheets + extra, [s.SheetPrices])

    def changed(self, *_args):
        self._timer.start()

    def _collect(self):
        return {
            "Currency": self.currency.text(),
            "PurchaseMode": self.mode.currentText(),
            "StockLength": self.stock_length.value(),
            "Kerf": self.kerf.value(),
            "EndTrim": self.end_trim.value(),
            "CutCost": self.cut_cost.value(),
            "DeliveryFlat": self.delivery_flat.value(),
            "DeliveryPerKg": self.delivery_kg.value(),
            "FreeDeliveryAbove": self.free_above.value(),
            "TaxPercent": self.tax.value(),
            "ProfilePrices": _read_column(self.profile_table, 1),
            "StockLengths": _read_column(self.profile_table, 2),
            "SheetPrices": _read_column(self.sheet_table, 1),
        }

    def apply(self):
        pricing.apply_values(self.settings, self._collect())
        self._update_estimate()

    def _update_estimate(self):
        report = cutlist.build_report(self.doc)
        c = report.currency
        lines = [f"{label}: {c} {value:,.2f}" for label, value in report.summary]
        lines[-1] = f"<b>{lines[-1]}</b>"
        if report.stock:
            lines.insert(0, f"{len(report.stock)} stock bar(s)")
        lines += [f"<span style='color:#b60'>{w}</span>" for w in report.warnings if w.startswith("No price")]
        self.estimate.setText("<br>".join(lines))

    def save_defaults(self):
        pricing.save_defaults(self._collect())
        App.Console.PrintMessage(f"Profile Builder: pricing defaults saved to {pricing.defaults_path()}\n")

    def load_defaults(self):
        data = pricing.load_defaults()
        if not data:
            App.Console.PrintWarning("Profile Builder: no saved pricing defaults yet\n")
            return
        pricing.apply_values(self.settings, data)
        s = self.settings
        for w, value in ((self.stock_length, s.StockLength.Value), (self.kerf, s.Kerf.Value),
                         (self.end_trim, s.EndTrim.Value), (self.cut_cost, s.CutCost),
                         (self.delivery_flat, s.DeliveryFlat), (self.delivery_kg, s.DeliveryPerKg),
                         (self.free_above, s.FreeDeliveryAbove), (self.tax, s.TaxPercent)):
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)
        self.currency.setText(s.Currency)
        self.mode.blockSignals(True)
        self.mode.setCurrentText(s.PurchaseMode)
        self.mode.blockSignals(False)
        self._fill_tables()
        self._update_estimate()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self._timer.stop()
        self.apply()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._timer.stop()
        self.doc.abortTransaction()
        Gui.Control.closeDialog()
        return True
