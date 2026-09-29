"""Clear run, stroke, position and belt length of a carriage on a rail (pure Python, no FreeCAD).

Everything is measured in the rail's local frame (see ``feature.Frame``):
``x`` and ``y`` across the section, ``s`` along the rail axis. The carriage is
an envelope: a rectangle in the section (``envelope``) swept along the axis.
Members whose shape enters that swept envelope block the carriage over an
interval of ``s``; the free runs are what is left of the rail between them
(``free_runs``). The stroke of a run is its length minus the carriage and one
end stop at each end.

The FreeCAD side (``linear.py``) finds the blocking intervals from the shapes
and uses these functions for the rest, so the rules can be tested without
FreeCAD.
"""

import math
from dataclasses import dataclass

POSITION_MODES = ("Percent", "Distance")
TOLERANCE = 1e-6  # mm: intervals that meet within this count as touching

# For each face of the section: the direction across the face (tangent) and the
# outward normal, as (x, y) in the profile's local section. The tangent is
# normal x axis, so (tangent, normal, axis) is right-handed.
FACE_AXES = {
    "Top": ((1, 0), (0, 1)),
    "Bottom": ((-1, 0), (0, -1)),
    "Left": ((0, 1), (-1, 0)),
    "Right": ((0, -1), (1, 0)),
}


def face_point(face, rect):
    """(x, y) of the middle of a face, and the face width, for rect = (x0, x1, y0, y1)."""
    x0, x1, y0, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return {
        "Top": ((cx, y1), x1 - x0),
        "Bottom": ((cx, y0), x1 - x0),
        "Left": ((x0, cy), y1 - y0),
        "Right": ((x1, cy), y1 - y0),
    }[face]


def envelope(face, rect, width, height, wrap):
    """The carriage envelope as (x0, x1, y0, y1) in the rail's section.

    It is ``width`` wide across the face, centred on it, stands ``height`` out
    from the face and reaches ``wrap`` back past the face (around the sides of
    the rail, as a V-wheel plate does).
    """
    (px, py), _w = face_point(face, rect)
    (tx, ty), (nx, ny) = FACE_AXES[face]
    corners = [(px + tx * u + nx * v, py + ty * u + ny * v)
               for u in (-width / 2, width / 2) for v in (-wrap, height)]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return min(xs), max(xs), min(ys), max(ys)


def face_under(face, rect, width):
    """End points (x, y) of the part of the face under a carriage of this width."""
    (px, py), face_width = face_point(face, rect)
    (tx, ty), _n = FACE_AXES[face]
    half = min(width, face_width) / 2
    return [(px - tx * half, py - ty * half), (px + tx * half, py + ty * half)]


def overlaps(a, b, tol=TOLERANCE):
    """True when two rectangles (x0, x1, y0, y1) overlap by more than tol (touching is not)."""
    return a[0] < b[1] - tol and b[0] < a[1] - tol and a[2] < b[3] - tol and b[2] < a[3] - tol


@dataclass(frozen=True)
class Run:
    """A free stretch of the rail: start and end along the axis, and what limits each end.

    ``start_by`` / ``end_by`` name the blocking member, or are None where the
    run ends at the end of the rail.
    """

    start: float
    end: float
    start_by: object = None
    end_by: object = None

    @property
    def length(self):
        return self.end - self.start


def free_runs(lo, hi, blocked, tol=TOLERANCE):
    """The free runs of [lo, hi] outside the blocked intervals [(s0, s1, label)].

    Intervals are clipped to [lo, hi]. An interval that only touches an end of
    the rail (a post the rail butts against) blocks nothing but names what
    limits the run there.
    """
    intervals = sorted(((max(lo, a), min(hi, b), label) for a, b, label in blocked
                        if b >= lo - tol and a <= hi + tol), key=lambda i: (i[0], i[1]))
    runs = []
    cursor, cursor_by = lo, None
    for a, b, label in intervals:
        if a > cursor + tol:
            runs.append(Run(cursor, a, cursor_by, label))
            cursor, cursor_by = b, label
        elif b > cursor + tol:
            cursor, cursor_by = b, label
        elif cursor_by is None and b >= cursor - tol:
            cursor_by = label  # touches the start of the next run
    if hi > cursor + tol:
        runs.append(Run(cursor, hi, cursor_by, None))
    return runs


def pick_run(runs, index=0):
    """The run the carriage is on: 0 for the longest (the first of equals), n for the n-th from the start.

    Returns (run, message): run is None when there are no runs; message is set
    when ``index`` asks for a run that does not exist and the longest is used.
    """
    if not runs:
        return None, None
    if 1 <= index <= len(runs):
        return runs[index - 1], None
    longest = max(range(len(runs)), key=lambda i: (round(runs[i].length, 6), -i))
    message = None
    if index:
        message = f"there is no run {index}, only {len(runs)}; using the longest"
    return runs[longest], message


def stroke(run_length, carriage_length, end_stop):
    """Usable stroke: the run minus the carriage and an end stop at each end (negative: it does not fit)."""
    return run_length - carriage_length - 2 * end_stop


def travel(mode, position, percent, usable):
    """Travel from the start of the stroke, from a distance or from a percentage of the stroke."""
    if mode == "Percent":
        return max(0.0, usable) * min(100.0, max(0.0, percent)) / 100
    return position


def centre(run, carriage_length, end_stop, moved):
    """Position of the carriage centre along the axis.

    ``moved`` is the travel from the start of the stroke. A carriage that does
    not fit in its run is shown in the middle of the run.
    """
    if stroke(run.length, carriage_length, end_stop) < 0:
        return (run.start + run.end) / 2
    return run.start + end_stop + carriage_length / 2 + moved


def problems(run, carriage_length, end_stop, required, mode, moved, fmt=None, names=None):
    """Messages for what is wrong with a carriage on its run (empty when all is well).

    ``fmt`` formats a length (default "12.5 mm"); ``names`` gives the text for
    what limits a run end, with None meaning the end of the rail.
    """
    fmt = fmt or (lambda v: f"{v:g} mm")
    names = names or (lambda by, end: str(by) if by is not None else f"the {end} of the rail")
    usable = stroke(run.length, carriage_length, end_stop)
    limits = f"between {names(run.start_by, 'start')} and {names(run.end_by, 'end')}"
    found = []
    if usable < 0:
        found.append(f"the carriage and its end stops ({fmt(carriage_length + 2 * end_stop)}) do not fit in "
                     f"the clear run of {fmt(run.length)} {limits}")
    elif required > 0 and usable < required - TOLERANCE:
        found.append(f"the stroke of {fmt(usable)} is {fmt(required - usable)} short of the required "
                     f"{fmt(required)}; the clear run of {fmt(run.length)} is {limits}")
    if mode == "Distance" and usable >= 0 and not -TOLERANCE <= moved <= usable + TOLERANCE:
        limit = names(run.start_by, "start") if moved < 0 else names(run.end_by, "end")
        found.append(f"Position {fmt(moved)} is outside the stroke (0 to {fmt(usable)}): "
                     f"the carriage would run into {limit}")
    return found


def pitch_diameter(teeth, pitch):
    """Pitch diameter of a toothed pulley: teeth x pitch / pi (0 when either is unknown)."""
    return teeth * pitch / math.pi if teeth > 0 and pitch > 0 else 0.0


def belt_length(centres, pulley_diameter, allowance=0.0, pitch=0.0):
    """Length of an open belt over two equal pulleys, with both ends clamped to the carriage.

    The belt goes round both pulleys: 2 x centre distance + pi x pitch
    diameter. ``allowance`` is what the clamps add (the ends held in them)
    or take away (a gap between the clamps). With a tooth ``pitch`` the length
    is rounded up to whole teeth.
    """
    length = 2 * centres + math.pi * pulley_diameter + allowance
    if pitch > 0:
        length = math.ceil(length / pitch - 1e-9) * pitch
    return length
