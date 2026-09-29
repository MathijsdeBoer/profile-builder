"""Frame solver tests against closed-form results (no FreeCAD needed).

Needs numpy and scipy: uvx --with numpy --with scipy pytest tests -q -p no:cacheprovider
Without them these tests are skipped.
"""

import importlib.util
import math
import os
import sys

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

_spec = importlib.util.spec_from_file_location(
    "frame_model", os.path.join(os.path.dirname(__file__), "..", "freecad", "profile_builder", "frame_model.py"))
fm = importlib.util.module_from_spec(_spec)
sys.modules["frame_model"] = fm  # dataclasses look their module up
_spec.loader.exec_module(fm)

E, G = 69000.0, 26000.0
SEC = fm.Section(E=E, G=G, A=150.0, iy=7000.0, iz=5000.0, J=1500.0, mass_per_length=0.5e-3)
STIFF_AXIAL = fm.Section(E=E, G=G, A=1e7, iy=7000.0, iz=7000.0, J=1e7, mass_per_length=0.5e-3)


def rel(a, b):
    return abs(a - b) / abs(b)


def cantilever(length=500.0, parts=1, direction=(1, 0, 0), y_axis=(0, 1, 0), section=SEC):
    """Clamped at node 0, free at the last node."""
    m = fm.Model()
    d = np.array(direction, dtype=float) / np.linalg.norm(direction)
    nodes = [m.node(d * length * k / parts) for k in range(parts + 1)]
    for a, b in zip(nodes, nodes[1:]):
        m.beam(a, b, section, y_axis)
    m.support(nodes[0], range(6))
    return m, nodes[-1]


def test_cantilever_tip_loads():
    L, P = 500.0, 10.0
    m, tip = cantilever(L)
    u = m.solve({tip: (0, P, 0)}).displacement(tip)
    assert rel(u[1], P * L ** 3 / (3 * E * SEC.iz)) < 1e-9
    assert rel(u[5], P * L ** 2 / (2 * E * SEC.iz)) < 1e-9
    u = m.solve({tip: (0, 0, P)}).displacement(tip)
    assert rel(u[2], P * L ** 3 / (3 * E * SEC.iy)) < 1e-9
    assert rel(-u[4], P * L ** 2 / (2 * E * SEC.iy)) < 1e-9
    u = m.solve({tip: (P, 0, 0)}).displacement(tip)
    assert rel(u[0], P * L / (E * SEC.A)) < 1e-9
    u = m.solve({tip: (0, 0, 0, 1000.0)}).displacement(tip)
    assert rel(u[3], 1000.0 * L / (G * SEC.J)) < 1e-9


def test_skewed_cantilever_in_several_parts():
    """The same beam along an arbitrary direction, cut into parts, bends the same."""
    L, P = 700.0, 25.0
    d = np.array([1.0, 2.0, -0.5])
    d /= np.linalg.norm(d)
    y = np.cross(d, [0.0, 0.0, 1.0])
    y /= np.linalg.norm(y)
    z = np.cross(d, y)
    m, tip = cantilever(L, parts=5, direction=d, y_axis=y)
    u = m.solve({tip: tuple(P * z)}).displacement(tip)
    assert rel(u[:3] @ z, P * L ** 3 / (3 * E * SEC.iy)) < 1e-9
    assert abs(u[:3] @ y) < 1e-9 * abs(u[:3] @ z)


def test_rigid_end_zone_and_offset():
    L, a, P = 600.0, 100.0, 10.0
    # A rigid zone of length a at the clamped end: only L - a bends.
    m = fm.Model()
    n0, n1 = m.node((0, 0, 0)), m.node((L, 0, 0))
    m.beam(n0, n1, SEC, (0, 1, 0), offsets=((a, 0, 0), None))
    m.support(n0, range(6))
    u = m.solve({n1: (0, P, 0)}).displacement(n1)
    assert rel(u[1], P * (L - a) ** 3 / (3 * E * SEC.iz)) < 1e-9
    # A beam axis offset by e from the nodes: a load at the node twists it.
    e = 15.0
    m = fm.Model()
    n0, n1 = m.node((0, 0, 0)), m.node((L, 0, 0))
    m.beam(n0, n1, SEC, (0, 1, 0), offsets=((0, e, 0), (0, e, 0)))
    m.support(n0, range(6))
    u = m.solve({n1: (0, 0, P)}).displacement(n1)
    assert rel(u[2], P * L ** 3 / (3 * E * SEC.iy) + e * e * P * L / (G * SEC.J)) < 1e-9


def portal(h, span, supports, spring=None, section=STIFF_AXIAL):
    """Columns at x = 0 and x = span, beam at height h in the x-z plane; returns (model, top nodes)."""
    m = fm.Model()
    a, b = m.node((0, 0, 0)), m.node((0, 0, h))
    c, d = m.node((span, 0, h)), m.node((span, 0, 0))
    m.beam(a, b, section, (1, 0, 0))
    m.beam(d, c, section, (1, 0, 0))
    m.beam(b, c, section, (0, 0, 1), springs=(spring, spring))
    for n in (a, d):
        m.support(n, range(6) if supports == "fixed" else (0, 1, 2, 3, 5))  # pinned in the frame's plane
    return m, (b, c)


def sway_stiffness(m, top):
    s = m.solve({top[0]: (0.5, 0, 0), top[1]: (0.5, 0, 0)})
    return 1.0 / np.mean([s.displacement(n)[0] for n in top])


def test_portal_frames():
    h, span = 400.0, 600.0
    ei = E * STIFF_AXIAL.iy
    a, b = ei / h, ei / span
    m, top = portal(h, span, "fixed")
    assert rel(sway_stiffness(m, top), 12 * a * (a + 6 * b) / (h ** 2 * (2 * a + 3 * b))) < 1e-4
    m, top = portal(h, span, "pinned")
    assert rel(sway_stiffness(m, top), 12 * a * b / (h ** 2 * (a + 2 * b))) < 1e-4


def test_portal_with_semi_rigid_joints():
    """Pinned-base portal whose beam is joined to the columns by rotational springs."""
    h, span = 400.0, 600.0
    ei = E * STIFF_AXIAL.iy
    a, b = ei / h, ei / span
    k = 0.5 * b
    m, top = portal(h, span, "pinned", spring=fm.Spring(k, k, k))
    s = 6 * b * k / (6 * b + k)
    assert rel(sway_stiffness(m, top), 6 * a * s / (h ** 2 * (3 * a + s))) < 1e-4
    rigid = portal(h, span, "pinned")
    assert sway_stiffness(m, top) < sway_stiffness(*rigid)


def test_energy_balances_the_work_done():
    m, top = portal(400.0, 600.0, "pinned", spring=fm.Spring(1e6, 1e6, 1e6), section=SEC)
    loads = {top[0]: (3.0, 1.0, -2.0), top[1]: (0.0, 0.5, 0.0)}
    s = m.solve(loads)
    work = 0.5 * sum(np.dot(f, s.displacement(n)[:3]) for n, f in loads.items())
    assert rel(s.energy, work) < 1e-9
    assert all(e >= 0 for e in s.beam_energy)
    assert s.spring_energy[2][0] > 0 and s.spring_energy[2][1] > 0 and s.spring_energy[0] == (0.0, 0.0)


def test_cantilever_frequencies():
    L = 800.0
    m, _tip = cantilever(L, parts=20)
    freqs = m.modes(4).frequencies
    mu = SEC.mass_per_length * fm.TONNE
    weak = math.sqrt(E * SEC.iz / (mu * L ** 4)) / (2 * math.pi)
    strong = math.sqrt(E * SEC.iy / (mu * L ** 4)) / (2 * math.pi)
    assert rel(freqs[0], 1.875104 ** 2 * weak) < 1e-3
    assert rel(freqs[1], 1.875104 ** 2 * strong) < 1e-3
    assert rel(freqs[2], 4.694091 ** 2 * weak) < 1e-3


def test_simply_supported_frequency():
    L = 1000.0
    m = fm.Model()
    nodes = [m.node((L * k / 20, 0, 0)) for k in range(21)]
    for a, b in zip(nodes, nodes[1:]):
        m.beam(a, b, SEC, (0, 1, 0))
    m.support(nodes[0], (0, 1, 2, 3))
    m.support(nodes[-1], (1, 2))
    mu = SEC.mass_per_length * fm.TONNE
    expected = math.pi / 2 * math.sqrt(E * SEC.iz / (mu * L ** 4))
    assert rel(m.modes(1).frequencies[0], expected) < 1e-3


def test_tip_mass_on_a_massless_beam():
    """Only the tip mass counts; the massless rotations are condensed out."""
    L, kg = 500.0, 2.0
    light = fm.Section(E=E, G=G, A=150.0, iy=7000.0, iz=5000.0, J=1500.0, mass_per_length=0.0)
    m, tip = cantilever(L, parts=3, direction=(0, 0, 1), y_axis=(1, 0, 0), section=light)
    m.add_mass(tip, kg)
    modes = m.modes(2)
    expected = math.sqrt(3 * E * light.iz / L ** 3 / (kg * fm.TONNE)) / (2 * math.pi)
    assert rel(modes.frequencies[0], expected) < 1e-9
    # Weak axis: local z is bent by iz; local y is world X, so it sways along X.
    assert modes.participation[0]["X"] > 0.99 and modes.participation[1]["Y"] > 0.99


def test_twist_mode_is_recognised():
    """A thin post carrying a cross with masses on its arms twists first."""
    thin = fm.Section(E=E, G=G, A=150.0, iy=7000.0, iz=7000.0, J=20.0, mass_per_length=0.0)
    arm = fm.Section(E=E, G=G, A=500.0, iy=1e6, iz=1e6, J=1e6, mass_per_length=0.0)
    m = fm.Model()
    base, top = m.node((0, 0, 0)), m.node((0, 0, 500))
    m.beam(base, top, thin, (1, 0, 0))
    m.support(base, range(6))
    for x, y in ((200, 0), (-200, 0), (0, 200), (0, -200)):
        end = m.node((x, y, 500))
        m.beam(top, end, arm, (0, 0, 1))
        m.add_mass(end, 1.0)
    modes = m.modes(1)
    assert modes.participation[0]["twist"] > 0.99
    expected = math.sqrt(G * thin.J / 500 / (4 * 200 ** 2 * fm.TONNE)) / (2 * math.pi)
    assert rel(modes.frequencies[0], expected) < 1e-3


def test_mechanisms_are_reported():
    m = fm.Model()
    a, b = m.node((0, 0, 0)), m.node((500, 0, 0))
    m.beam(a, b, SEC, (0, 1, 0))
    m.support(a)
    m.support(b)  # pinned at both ends: nothing stops it spinning about its own axis
    with pytest.raises(fm.MechanismError) as err:
        m.solve({b: (0, 1, 0)})
    assert sorted(err.value.nodes) == [a, b]
    with pytest.raises(fm.MechanismError):
        m.modes(1)
    # A beam hanging on nothing.
    c, d = m.node((0, 0, 100)), m.node((500, 0, 100))
    m.support(a, range(6))
    m.beam(c, d, SEC, (0, 1, 0))
    with pytest.raises(fm.MechanismError) as err:
        m.solve({b: (0, 1, 0)})
    assert set(err.value.nodes) <= {c, d} and err.value.nodes


def test_spring_matrix_follows_the_beam_axes():
    axes = np.array([[0, 0, 1.0], [1.0, 0, 0], [0, 1.0, 0]])  # a vertical beam
    k = fm.Spring(1.0, 2.0, 3.0).matrix(axes)
    assert np.allclose(k, np.diag([2.0, 3.0, 1.0]))


def test_local_matrices_are_symmetric():
    k = fm.beam_stiffness(SEC, 400.0)
    mass = fm.beam_mass(SEC, 400.0)
    assert np.allclose(k, k.T) and np.allclose(mass, mass.T)
    assert abs(mass[np.ix_([0, 6], [0, 6])].sum() - SEC.mass_per_length * fm.TONNE * 400) < 1e-12
    assert np.all(np.linalg.eigvalsh(mass) > 0)
