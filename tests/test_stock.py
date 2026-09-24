"""Stock bar optimisation tests (no FreeCAD needed)."""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "stock", os.path.join(os.path.dirname(__file__), "..", "freecad", "profile_builder", "stock.py"))
stock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stock)


def pieces(*lengths):
    return [(length, f"p{i}") for i, length in enumerate(lengths)]


def test_everything_fits_in_one_bar():
    plan = stock.plan(pieces(1000, 2000, 1500), 6000, kerf=3)
    assert len(plan.bars) == 1
    assert plan.bars[0].offcut == 6000 - 4500 - 9


def test_kerf_can_force_an_extra_bar():
    assert len(stock.plan(pieces(3000, 3000), 6000, kerf=0).bars) == 1
    # The first cut eats 3 mm, so the second 3000 no longer fits... unless it is the last piece.
    assert len(stock.plan(pieces(3000, 3000), 6000, kerf=3).bars) == 2
    assert len(stock.plan(pieces(3000, 2997), 6000, kerf=3).bars) == 1


def test_best_of_first_and_best_fit():
    # A perfect packing: two full bars.
    plan = stock.plan(pieces(3400, 2600, 2500, 1500, 1000, 1000), 6000)
    assert len(plan.bars) == 2


def test_oversize_and_end_trim():
    plan = stock.plan(pieces(6500, 5990, 100), 6000, end_trim=20)
    assert [p[0] for p in plan.oversize] == [6500, 5990]
    assert len(plan.bars) == 1
    assert plan.bars[0].offcut == 6000 - 20 - 100


def test_waste():
    plan = stock.plan(pieces(3000, 3000), 6000)
    assert plan.waste == 0
    assert stock.plan([], 6000).waste == 0
