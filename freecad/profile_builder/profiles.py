r"""Catalog of standard aluminium T-slot / V-slot extrusion series.

This module is pure Python (no FreeCAD imports) so it can be unit tested
without FreeCAD. All dimensions are in millimetres and describe a single
square "cell" of the series; multi-cell profiles (2040, 4080, ...) are built
by tiling cells.

The values are typical B-type dimensions. Manufacturers (Misumi, Item, Bosch
Rexroth, OpenBuilds, ...) differ by a few tenths of a millimetre, so every value
is copied onto the FreeCAD feature where it can be overridden.

Slot geometry, measured from the outer face (v) and across the slot (u)::

        |<-- slot_opening -->|
    ____|                    |____   v = 0      (outer face)
        |____            ____|       v = lip
     ____|                  |____    head_width, from v = lip ...
    |                            |   ... to v = lip + head_straight
     \                          /
      \________________________/     v = slot_depth, bottom_width
"""

from dataclasses import dataclass, fields

SLOT_STYLES = ("T-slot", "V-slot")
ANCHORS = ("Center", "Bottom left", "Bottom center")
MITER_ACROSS = ("X", "Y")
FACES = ("Top", "Bottom", "Left", "Right")

# Density of 6063-T5/T6 aluminium in g/cm^3.
ALUMINIUM_DENSITY = 2.70

# Presets for which faces carry no slot, as (label, closed faces).
SLOT_PRESETS = (
    ("All sides open", ()),
    ("3 open (1 side closed)", ("Top",)),
    ("2 open, adjacent", ("Top", "Right")),
    ("2 open, opposite", ("Top", "Bottom")),
    ("1 open (3 sides closed)", ("Top", "Right", "Bottom")),
    ("All sides closed", FACES),
)


@dataclass(frozen=True)
class Series:
    key: str
    label: str
    cell: float
    slot_opening: float
    lip: float
    head_width: float
    head_straight: float
    slot_depth: float
    bottom_width: float
    center_bore: float
    corner_radius: float
    v_chamfer: float
    corner_hole: float = 0.0
    tap: str = ""
    sizes: tuple = ((1, 1), (1, 2), (1, 3), (1, 4), (2, 2), (2, 4))

    def designation(self, cols, rows):
        return designation(self.cell, cols, rows)

    def dimensions(self):
        """The geometric dimensions as a dict (everything but metadata)."""
        skip = {"key", "label", "tap", "sizes"}
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in skip}


SERIES = {
    s.key: s
    for s in (
        Series(
            key="15-3", label="15 series, slot 3", cell=15.0,
            slot_opening=3.3, lip=1.1, head_width=6.0, head_straight=1.0,
            slot_depth=4.4, bottom_width=3.6, center_bore=2.5,
            corner_radius=0.5, v_chamfer=0.6, tap="M3",
            sizes=((1, 1), (1, 2), (1, 3), (2, 2)),
        ),
        Series(
            key="20-6", label="20 series, slot 6", cell=20.0,
            slot_opening=6.2, lip=1.8, head_width=11.0, head_straight=1.5,
            slot_depth=6.1, bottom_width=5.8, center_bore=4.2,
            corner_radius=1.0, v_chamfer=1.5, tap="M5",
        ),
        Series(
            key="30-8", label="30 series, slot 8", cell=30.0,
            slot_opening=8.2, lip=2.2, head_width=16.5, head_straight=2.5,
            slot_depth=9.0, bottom_width=8.0, center_bore=6.8,
            corner_radius=1.5, v_chamfer=1.8, tap="M8",
            sizes=((1, 1), (1, 2), (1, 3), (2, 2), (2, 4)),
        ),
        Series(
            key="40-8", label="40 series, slot 8", cell=40.0,
            slot_opening=8.2, lip=4.3, head_width=20.0, head_straight=3.0,
            slot_depth=12.3, bottom_width=10.0, center_bore=6.8,
            corner_radius=2.0, v_chamfer=2.5, corner_hole=6.5, tap="M8",
        ),
        Series(
            key="40-10", label="40 series, slot 10", cell=40.0,
            slot_opening=10.2, lip=4.3, head_width=22.0, head_straight=3.0,
            slot_depth=12.5, bottom_width=11.0, center_bore=8.5,
            corner_radius=2.0, v_chamfer=2.5, corner_hole=5.5, tap="M10",
        ),
        Series(
            key="45-10", label="45 series, slot 10", cell=45.0,
            slot_opening=10.2, lip=4.5, head_width=22.0, head_straight=3.5,
            slot_depth=13.5, bottom_width=12.0, center_bore=8.5,
            corner_radius=2.0, v_chamfer=2.5, corner_hole=7.0, tap="M10",
            sizes=((1, 1), (1, 2), (1, 3), (2, 2), (2, 4)),
        ),
    )
}

DEFAULT_SERIES = "20-6"


def _fmt(value):
    return str(int(round(value))) if abs(value - round(value)) < 1e-9 else f"{value:g}"


def designation(cell, cols, rows):
    """Trade name of a profile, e.g. 2040 for a 1x2 profile of the 20 series."""
    a, b = sorted((cell * cols, cell * rows))
    return f"{_fmt(a)}{_fmt(b)}"


def closed_faces_for_preset(label):
    for name, closed in SLOT_PRESETS:
        if name == label:
            return closed
    raise KeyError(label)


def preset_for_closed_faces(closed):
    closed = set(closed)
    for name, faces in SLOT_PRESETS:
        if set(faces) == closed:
            return name
    return None


def validate(d, style="T-slot"):
    """Check a dimension dict for impossible geometry.

    Returns a list of human readable problems (empty when the dimensions are
    usable).
    """
    problems = []

    def need(cond, msg):
        if not cond:
            problems.append(msg)

    positive = ("cell", "slot_opening", "lip", "head_width", "slot_depth", "bottom_width")
    for name in positive:
        need(d[name] > 0, f"{name} must be positive")
    if problems:
        return problems

    cell = d["cell"]
    need(d["slot_opening"] < d["head_width"], "slot opening must be narrower than the slot head")
    need(d["head_width"] < cell, "slot head must be narrower than the cell")
    need(d["bottom_width"] <= d["head_width"], "slot bottom must not be wider than the slot head")
    need(d["slot_depth"] < cell / 2, "slot depth must be less than half the cell size")
    need(d["head_straight"] >= 0, "head straight height must not be negative")
    need(
        d["lip"] + d["head_straight"] < d["slot_depth"],
        "lip + head straight height must be less than the slot depth",
    )
    core = cell - 2 * d["slot_depth"]
    need(d["center_bore"] >= 0, "center bore must not be negative")
    need(d["center_bore"] < core, "center bore does not fit in the core")
    need(d["bottom_width"] < core, "slot bottom must be narrower than the core")
    rim = (cell - d["head_width"]) / 2
    need(0 <= d["corner_radius"] < rim, "corner radius must be smaller than the corner wall")
    if d.get("corner_hole", 0) > 0:
        need(d["corner_hole"] < 0.9 * rim, "corner hole does not fit in the corner")
    if style == "V-slot":
        need(0 < d["v_chamfer"] < d["lip"], "V chamfer must be between 0 and the lip thickness")
    return problems
