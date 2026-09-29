"""Prices, stock lengths and delivery costs, stored per document.

The settings live in a single "Pricing & stock" object in the document, so a
project keeps the prices of the supplier it was quoted with. They can also be
saved as the user's defaults, which new documents start from.
"""

import json
import os

import FreeCAD as App

SETTINGS_NAME = "ProfileBuilderPricing"
PURCHASE_MODES = ("Cut to size", "Stock bars")

# (property, kind, group, tooltip, default)
FIELDS = (
    # The default comes from the system locale, see default_currency().
    ("Currency", "App::PropertyString", "Purchase",
     "Currency symbol used in reports (by default the one of your system's region)", None),
    ("PurchaseMode", "App::PropertyEnumeration", "Purchase",
     "Cut to size: pay per metre of pieces plus a cutting cost per piece. "
     "Stock bars: buy whole bars and cut them yourself.", list(PURCHASE_MODES)),
    ("StockLength", "App::PropertyLength", "Purchase",
     "Default bar length for stock bars. Suppliers differ (for example 6 m, 3 m, 145 in or 242 in), "
     "so check yours; per-product lengths go in StockLengths", 6000.0),
    ("Kerf", "App::PropertyLength", "Purchase", "Material lost per saw cut", 3.0),
    ("EndTrim", "App::PropertyLength", "Purchase", "Cut off each stock bar once to square its end", 0.0),
    ("CutCost", "App::PropertyFloat", "Purchase", "Cutting cost per piece (cut to size only)", 0.0),
    ("DeliveryFlat", "App::PropertyFloat", "Delivery", "Fixed delivery cost per order", 0.0),
    ("DeliveryPerKg", "App::PropertyFloat", "Delivery", "Delivery cost per kg", 0.0),
    ("FreeDeliveryAbove", "App::PropertyFloat", "Delivery",
     "Order value above which delivery is free (0: never free)", 0.0),
    ("TaxPercent", "App::PropertyFloat", "Delivery",
     "Tax added to the total (VAT, GST or sales tax), in percent; 0 when prices already include it", 0.0),
    ("ProfilePrices", "App::PropertyMap", "Prices", "Price per metre, by product", None),
    ("StockLengths", "App::PropertyMap", "Prices", "Bar length in mm by product, if not the default", None),
    ("SheetPrices", "App::PropertyMap", "Prices", "Price per square metre, by sheet material", None),
)


def default_currency():
    """The currency symbol of the system's region ("$", "€", "£", "kr", ...), or "" when unknown."""
    try:
        from PySide import QtCore
        fmt = getattr(QtCore.QLocale, "CurrencySymbolFormat", QtCore.QLocale)
        return QtCore.QLocale.system().currencySymbol(fmt.CurrencySymbol)
    except Exception:  # noqa: BLE001
        return ""


def format_money(value, currency):
    """An amount formatted the way the system's region writes money.

    For example "$1,234.56" (US), "€ 1.234,56" (Netherlands) or "1 234,56 kr"
    (Sweden). Falls back to "currency 1234.56" without Qt.
    """
    try:
        from PySide import QtCore
        return QtCore.QLocale.system().toCurrencyString(float(value), currency)
    except Exception:  # noqa: BLE001
        return f"{currency} {value:.2f}".strip()


def defaults_path():
    return os.path.join(App.getUserAppDataDir(), "ProfileBuilder", "pricing.json")


def parse_number(text):
    """Float from user text ('12,50' is fine); None when empty or invalid."""
    try:
        return float(str(text).strip().replace(",", "."))
    except ValueError:
        return None


class Settings:
    Type = "ProfileBuilder::Pricing"

    def __init__(self, obj):
        obj.Proxy = self
        self.add_properties(obj)

    def add_properties(self, obj):
        for name, kind, group, tip, default in FIELDS:
            if name in obj.PropertiesList:
                continue
            obj.addProperty(kind, name, group, tip)
            if name == "Currency":
                default = default_currency()
            if default is not None:
                setattr(obj, name, default)

    def onDocumentRestored(self, obj):
        self.add_properties(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads


class ViewProviderSettings:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from .feature import ICON_DIR
        return os.path.join(ICON_DIR, "Pricing.svg")

    def doubleClicked(self, vobj):
        import FreeCADGui as Gui
        from .pricing_ui import PricingTaskPanel
        if not Gui.Control.activeDialog():
            Gui.Control.showDialog(PricingTaskPanel(vobj.Object.Document))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps
    __setstate__ = loads


def get_settings(doc, create=False):
    obj = doc.getObject(SETTINGS_NAME)
    if obj is None and create:
        obj = doc.addObject("App::FeaturePython", SETTINGS_NAME)
        Settings(obj)
        obj.Label = "Pricing & stock"
        if App.GuiUp:
            ViewProviderSettings(obj.ViewObject)
        apply_values(obj, load_defaults())
    return obj


def values(settings):
    """Settings as a plain dict (what gets saved as defaults)."""
    out = {}
    for name, _kind, _group, _tip, _default in FIELDS:
        value = getattr(settings, name)
        out[name] = value.Value if hasattr(value, "Value") else (dict(value) if isinstance(value, dict) else value)
    return out


def apply_values(settings, data):
    for name, _kind, _group, _tip, _default in FIELDS:
        if name in data:
            setattr(settings, name, data[name])


def load_defaults():
    try:
        with open(defaults_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_defaults(data):
    path = defaults_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def lookup(mapping, key):
    return parse_number(mapping.get(key, "")) if mapping else None


def settings_values(doc):
    """Effective settings for a document: its settings object, else the saved defaults."""
    obj = get_settings(doc)
    if obj is not None:
        return values(obj)
    data = {name: (default[0] if isinstance(default, list) else default)
            for name, _kind, _group, _tip, default in FIELDS}
    data["Currency"] = default_currency()
    data.update({k: v for k, v in load_defaults().items() if k in data})
    for name in ("ProfilePrices", "StockLengths", "SheetPrices"):
        data[name] = dict(data.get(name) or {})
    return data
