"""Which cut pieces are identical, and piece marks. Pure Python (no FreeCAD).

A piece is described by its closed faces and its two end cuts, each an
(angle, axis) pair. Angles follow the Profile convention: positive means the
+axis side of the section is the long side. Two pieces are the same when one
can be turned into the other, for example a frame side that was drawn in the
opposite direction, which flips the sign of both miters.
"""

import string

# Physical turns of a piece: how the closed faces map, whether the ends swap,
# and how an end cut (angle, axis) changes.
TURNS = (
    # 180 degrees about the length axis: the +X and +Y sides go to -X and -Y.
    ({"Top": "Bottom", "Bottom": "Top", "Left": "Right", "Right": "Left"}, False,
     lambda a, ax: (-a, ax)),
    # End over end about local Y: the ends swap and +X becomes -X.
    ({"Left": "Right", "Right": "Left"}, True, lambda a, ax: (-a if ax == "X" else a, ax)),
    # End over end about local X: the ends swap and +Y becomes -Y.
    ({"Top": "Bottom", "Bottom": "Top"}, True, lambda a, ax: (-a if ax == "Y" else a, ax)),
)
# A quarter turn about the length axis, only for square sections: +X goes to +Y.
QUARTER_TURN = ({"Right": "Top", "Top": "Left", "Left": "Bottom", "Bottom": "Right"}, False,
                lambda a, ax: (a, "Y") if ax == "X" else ((-a, "X") if ax == "Y" else (a, ax)))


def upright(closed, cuts, cols, rows):
    """Describe a piece in the orientation with Rows >= Columns.

    A 2x1 section is a 1x2 section lying on its side ("2040 (on side)"). A
    quarter turn about the length axis stands it up, so both orientations get
    the same description: the same closed faces, and the miters across the
    same faces. Returns (closed, cuts).
    """
    if cols <= rows:
        return frozenset(closed), tuple(cuts)
    mapping, _swap, turn = QUARTER_TURN
    return (frozenset(mapping.get(f, f) for f in closed), tuple(turn(a, ax) for a, ax in cuts))


def cut(angle, axis):
    """One end cut, rounded to 0.1 degree; a square cut has no axis."""
    angle = round(angle, 1) + 0.0  # + 0.0 turns -0.0 into 0.0
    return (0.0, "") if angle == 0 else (angle, axis)


def canonical_cuts(closed, cuts, square):
    """The end cuts of a piece in a form that is equal for identical pieces.

    ``closed`` holds the closed face names, ``cuts`` is ((start angle, axis),
    (end angle, axis)) and ``square`` says whether the section is square (then
    quarter turns are allowed too). Only turns that leave the closed faces
    where they are count, because the product name records those faces.
    """
    turns = TURNS + ((QUARTER_TURN,) if square else ())
    start = (frozenset(closed), tuple(cut(a, ax) for a, ax in cuts))
    seen, todo = {start}, [start]
    while todo:
        faces, ends = todo.pop()
        for mapping, swap, turn in turns:
            turned = tuple(cut(*turn(a, ax)) for a, ax in ends)
            state = (frozenset(mapping.get(f, f) for f in faces), turned[::-1] if swap else turned)
            if state not in seen:
                seen.add(state)
                todo.append(state)
    same = [ends for faces, ends in seen if faces == start[0]]
    # Prefer positive angles: "45, 45" reads better than "-45, -45".
    return max(same, key=lambda e: (e[0][0], e[1][0], e[0][1], e[1][1]))


def letters(index):
    """Spreadsheet-style letters: 0 -> A, 25 -> Z, 26 -> AA."""
    text = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        text = string.ascii_uppercase[rest] + text
    return text


def assign_marks(groups, state, prefix=None):
    """Stable marks for groups of identical pieces: {key: mark}.

    ``groups`` is [(product, key)] in the order new marks are handed out (the
    report passes the longest piece of a product first). ``state`` holds the
    marks given so far, {"letters": {product: letter}, "marks": {key: mark}},
    and is updated in place; the caller stores it with the document. A group
    keeps its mark while its key exists. A new group gets the next number of
    its product's letter, and a new product the next letter. Marks of groups
    that no longer exist are retired, not reused, so a printed label never
    comes to mean another piece. With ``prefix`` (e.g. "P-") every mark uses
    that prefix instead of a product letter.
    """
    products = state.setdefault("letters", {})
    marks = state.setdefault("marks", {})
    result = {}
    for product, key in groups:
        if key in marks:
            result[key] = marks[key]
            continue
        start = prefix or products.get(product)
        if start is None:
            start = products[product] = letters(len(products))
        used = [int(m[len(start):]) for m in marks.values() if m.startswith(start) and m[len(start):].isdigit()]
        marks[key] = result[key] = f"{start}{max(used, default=0) + 1}"
    return result


def mark_order(mark):
    """Sort key for marks: A1, A2, A10, B1, AA1, P-1."""
    head = mark.rstrip("0123456789")
    tail = mark[len(head):]
    return (len(head), head, int(tail) if tail else 0)
