"""3D beam frame model: the direct stiffness method, with static and modal analysis.

Pure numpy and scipy, no FreeCAD imports, so pytest can load it directly. The
document-level builder that turns profiles and joints into a model is in
``frame_stiffness.py``.

Units are mm, N, kg and s: stiffness in N/mm, moments in N·mm, rotational
springs in N·mm/rad, mass in kg. Masses are converted to tonnes (N·s²/mm)
internally, so that natural frequencies come out in Hz.

Every node has six degrees of freedom (three translations, three rotations,
in world axes). Beams are 12-DOF Euler-Bernoulli elements with a consistent
mass matrix. Each beam end can sit at an offset from its node (a rigid link,
for anchored profiles and for the part of a joint inside the through
profile), and can be connected to the node through a rotational spring instead
of rigidly. A spring end gets three rotational DOFs of its own; it shares the
node's translations, and its position follows the node's rotation.
"""

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import linalg

TONNE = 1e-3  # kg -> t (N·s²/mm)
MECHANISM = 1e-11  # smallest eigenvalue of the Jacobi-scaled stiffness below which the frame can move freely


class MechanismError(ValueError):
    """The frame (or part of it) can move without deforming anything.

    ``nodes`` are the node indices that move most in that free motion, so the
    caller can say which members are involved.
    """

    def __init__(self, message, nodes=()):
        super().__init__(message)
        self.nodes = list(nodes)


@dataclass(frozen=True)
class Section:
    """Beam section and material.

    ``iy`` and ``iz`` are second moments of area (mm⁴) about the beam's local
    y and z axes: ``iz`` resists deflection along local y, ``iy`` along local z.
    ``J`` is the torsion constant (mm⁴), ``A`` the area (mm²), ``E`` and ``G``
    in N/mm² (MPa), ``mass_per_length`` in kg/mm.
    """

    E: float
    G: float
    A: float
    iy: float
    iz: float
    J: float
    mass_per_length: float = 0.0


@dataclass(frozen=True)
class Spring:
    """Rotational spring between a node and a beam end, in the beam's local axes (N·mm/rad).

    ``torsion`` acts about the beam axis, ``y`` and ``z`` about its local y and z axes.
    """

    torsion: float
    y: float
    z: float

    def matrix(self, axes):
        """3x3 stiffness in world axes; ``axes`` has the beam's local x, y, z as rows."""
        return axes.T @ np.diag([self.torsion, self.y, self.z]) @ axes


@dataclass
class Beam:
    i: int
    j: int
    section: Section
    axes: np.ndarray  # rows: local x (along the beam), y, z in world axes
    length: float
    offsets: tuple  # world vectors from node i / node j to the beam's ends
    springs: tuple  # (Spring or None, Spring or None); None is a rigid connection
    tag: object = None


def _skew(v):
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def beam_stiffness(section, length):
    """12x12 local stiffness matrix; DOFs (u, v, w, θx, θy, θz) at end i, then end j."""
    s, L = section, length
    k = np.zeros((12, 12))
    ea, gj = s.E * s.A / L, s.G * s.J / L
    k[0, 0] = k[6, 6] = ea
    k[0, 6] = k[6, 0] = -ea
    k[3, 3] = k[9, 9] = gj
    k[3, 9] = k[9, 3] = -gj
    # Bending in the local x-y plane (v, θz), resisted by iz.
    a, b, c, d = 12 * s.E * s.iz / L ** 3, 6 * s.E * s.iz / L ** 2, 4 * s.E * s.iz / L, 2 * s.E * s.iz / L
    for (r, q), value in {(1, 1): a, (7, 7): a, (1, 7): -a, (1, 5): b, (1, 11): b, (5, 7): -b, (7, 11): -b,
                          (5, 5): c, (11, 11): c, (5, 11): d}.items():
        k[r, q] = k[q, r] = value
    # Bending in the local x-z plane (w, θy), resisted by iy; the signs differ
    # because a positive θy tilts the beam towards -z.
    a, b, c, d = 12 * s.E * s.iy / L ** 3, 6 * s.E * s.iy / L ** 2, 4 * s.E * s.iy / L, 2 * s.E * s.iy / L
    for (r, q), value in {(2, 2): a, (8, 8): a, (2, 8): -a, (2, 4): -b, (2, 10): -b, (4, 8): b, (8, 10): b,
                          (4, 4): c, (10, 10): c, (4, 10): d}.items():
        k[r, q] = k[q, r] = value
    return k


def beam_mass(section, length):
    """12x12 consistent local mass matrix in tonnes (and t·mm² for rotations)."""
    s, L = section, length
    m = s.mass_per_length * TONNE * L  # total, t
    out = np.zeros((12, 12))
    out[np.ix_([0, 6], [0, 6])] = m / 6 * np.array([[2, 1], [1, 2]])
    polar = (s.iy + s.iz) / s.A if s.A else 0.0  # radius of gyration squared
    out[np.ix_([3, 9], [3, 9])] = m * polar / 6 * np.array([[2, 1], [1, 2]])
    bend = m / 420 * np.array([[156, 22 * L, 54, -13 * L],
                               [22 * L, 4 * L * L, 13 * L, -3 * L * L],
                               [54, 13 * L, 156, -22 * L],
                               [-13 * L, -3 * L * L, -22 * L, 4 * L * L]])
    out[np.ix_([1, 5, 7, 11], [1, 5, 7, 11])] = bend
    flip = np.diag([1, -1, 1, -1])  # x-z plane: θy has the opposite sign
    out[np.ix_([2, 4, 8, 10], [2, 4, 8, 10])] = flip @ bend @ flip
    return out


@dataclass
class Static:
    """Result of a static solve."""

    model: object  # the Model that was solved
    u: np.ndarray  # all DOFs
    beam_energy: list  # strain energy per beam, N·mm
    spring_energy: list  # [(energy at end i, energy at end j)] per beam, N·mm

    def displacement(self, node):
        """(ux, uy, uz, θx, θy, θz) of a node."""
        return self.u[6 * node:6 * node + 6].copy()

    @property
    def energy(self):
        return sum(self.beam_energy) + sum(a + b for a, b in self.spring_energy)


@dataclass
class Modes:
    """Result of a modal analysis, lowest mode first."""

    frequencies: list  # Hz
    shapes: np.ndarray  # one column per mode, over all DOFs
    participation: list  # per mode: {"X", "Y", "Z", "twist"}: fraction of the (free) mass in that motion


@dataclass
class Model:
    nodes: list = field(default_factory=list)
    beams: list = field(default_factory=list)
    masses: dict = field(default_factory=dict)  # node -> kg
    fixed: dict = field(default_factory=dict)  # node -> set of DOFs 0..5
    _prepared: tuple = field(default=None, repr=False)  # (K, M, hinges, free, Cholesky of K) once checked

    def node(self, xyz):
        self._prepared = None
        self.nodes.append(np.array(xyz, dtype=float))
        return len(self.nodes) - 1

    def beam(self, i, j, section, y_axis, offsets=(None, None), springs=(None, None), tag=None):
        """Add a beam from node i to node j and return its index.

        ``y_axis`` gives the direction of the local y axis (it is made square
        to the beam). ``offsets`` are world vectors from each node to the beam
        end (rigid links), ``springs`` a Spring or None (rigid) per end.
        """
        if i == j:
            raise ValueError("a beam needs two different nodes")
        self._prepared = None
        e = tuple(np.zeros(3) if o is None else np.array(o, dtype=float) for o in offsets)
        a, b = self.nodes[i] + e[0], self.nodes[j] + e[1]
        length = float(np.linalg.norm(b - a))
        if length < 1e-9:
            raise ValueError("a beam needs a length")
        ex = (b - a) / length
        y = np.array(y_axis, dtype=float)
        y = y - ex * y.dot(ex)
        if np.linalg.norm(y) < 1e-9:
            raise ValueError("the local y axis of a beam must not be parallel to it")
        ey = y / np.linalg.norm(y)
        ez = np.cross(ex, ey)
        self.beams.append(Beam(i, j, section, np.array([ex, ey, ez]), length, e, tuple(springs), tag))
        return len(self.beams) - 1

    def add_mass(self, node, kg):
        self._prepared = None
        self.masses[node] = self.masses.get(node, 0.0) + kg

    def support(self, node, dofs=(0, 1, 2)):
        """Hold DOFs of a node: (0, 1, 2) pins it, range(6) clamps it."""
        self._prepared = None
        self.fixed.setdefault(node, set()).update(dofs)

    # ---- assembly ----------------------------------------------------------------

    def _hinges(self):
        """{(beam, end): first of its three rotational DOFs}, and the total DOF count."""
        n = 6 * len(self.nodes)
        hinges = {}
        for b, beam in enumerate(self.beams):
            for end in (0, 1):
                if beam.springs[end] is not None:
                    hinges[(b, end)] = n
                    n += 3
        return hinges, n

    def _end_map(self, b, end, hinges):
        """(global DOFs, 6 x n matrix) giving a beam end's DOFs in world axes."""
        beam = self.beams[b]
        node = beam.i if end == 0 else beam.j
        dofs = list(range(6 * node, 6 * node + 6))
        spring = (b, end) in hinges
        if spring:
            dofs += list(range(hinges[(b, end)], hinges[(b, end)] + 3))
        m = np.zeros((6, len(dofs)))
        m[0:3, 0:3] = np.eye(3)
        m[0:3, 3:6] = -_skew(beam.offsets[end])  # u_end = u_node + θ_node × e
        if spring:
            m[3:6, 6:9] = np.eye(3)
        else:
            m[3:6, 3:6] = np.eye(3)
        return dofs, m

    def _beam_map(self, b, hinges):
        di, mi = self._end_map(b, 0, hinges)
        dj, mj = self._end_map(b, 1, hinges)
        m = np.zeros((12, len(di) + len(dj)))
        m[0:6, :len(di)] = mi
        m[6:12, len(di):] = mj
        return di + dj, m

    def assemble(self):
        """(K, M, hinges) over all DOFs, before supports."""
        hinges, n = self._hinges()
        K = np.zeros((n, n))
        M = np.zeros((n, n))
        for b, beam in enumerate(self.beams):
            dofs, m = self._beam_map(b, hinges)
            rot = np.kron(np.eye(4), beam.axes)  # world -> local
            t = rot @ m
            ix = np.ix_(dofs, dofs)
            K[ix] += t.T @ beam_stiffness(beam.section, beam.length) @ t
            M[ix] += t.T @ beam_mass(beam.section, beam.length) @ t
            for end in (0, 1):
                spring = beam.springs[end]
                if spring is None:
                    continue
                node = beam.i if end == 0 else beam.j
                k = spring.matrix(beam.axes)
                own = list(range(6 * node + 3, 6 * node + 6)) + list(range(hinges[(b, end)], hinges[(b, end)] + 3))
                K[np.ix_(own, own)] += np.block([[k, -k], [-k, k]])
        for node, kg in self.masses.items():
            for d in range(3):
                M[6 * node + d, 6 * node + d] += kg * TONNE
        return K, M, hinges

    def free_dofs(self, n):
        fixed = {6 * node + d for node, dofs in self.fixed.items() for d in dofs}
        return np.array([d for d in range(n) if d not in fixed], dtype=int)

    def _node_of(self, dof, hinges):
        if dof < 6 * len(self.nodes):
            return dof // 6
        for (b, end), start in hinges.items():
            if start <= dof < start + 3:
                beam = self.beams[b]
                return beam.i if end == 0 else beam.j
        return None

    def _check_mechanism(self, K, free, hinges):
        """Raise MechanismError when the supported frame can still move freely."""
        kff = K[np.ix_(free, free)]
        d = np.sqrt(np.clip(np.diag(kff), 0.0, None))
        loose = np.where(d <= 0.0)[0]
        if len(loose):
            nodes = sorted({self._node_of(free[i], hinges) for i in loose} - {None})
            raise MechanismError("some nodes are not held by any member or support", nodes)
        scaled = kff / np.outer(d, d)
        w, v = linalg.eigh(scaled, subset_by_index=[0, 0])
        if w[0] < MECHANISM:
            motion = np.abs(v[:, 0] / d)
            per_node = {}
            for i, amount in enumerate(motion):
                node = self._node_of(free[i], hinges)
                per_node[node] = max(per_node.get(node, 0.0), amount)
            top = max(per_node.values())
            nodes = sorted(n for n, a in per_node.items() if n is not None and a > 0.1 * top)
            raise MechanismError("the frame can move without deforming (a mechanism)", nodes)

    def _prepare(self):
        """(K, M, hinges, free DOFs), assembled once and checked for mechanisms."""
        if self._prepared is None:
            K, M, hinges = self.assemble()
            free = self.free_dofs(K.shape[0])
            self._check_mechanism(K, free, hinges)
            try:
                factor = linalg.cho_factor(K[np.ix_(free, free)])
            except linalg.LinAlgError as e:  # nearly singular, just above the mechanism threshold
                raise MechanismError("the frame is nearly a mechanism") from e
            self._prepared = (K, M, hinges, free, factor)
        return self._prepared[:4]

    # ---- analyses -------------------------------------------------------------------

    def solve(self, loads):
        """Static solve for ``loads`` = {node: (Fx, Fy, Fz, Mx, My, Mz)} in N and N·mm."""
        K, _M, hinges, free = self._prepare()
        n = K.shape[0]
        f = np.zeros(n)
        for node, values in loads.items():
            f[6 * node:6 * node + len(values)] += values
        u = np.zeros(n)
        u[free] = linalg.cho_solve(self._prepared[4], f[free])

        beam_energy, spring_energy = [], []
        for b, beam in enumerate(self.beams):
            dofs, m = self._beam_map(b, hinges)
            t = np.kron(np.eye(4), beam.axes) @ m
            local = t @ u[dofs]
            beam_energy.append(0.5 * local @ beam_stiffness(beam.section, beam.length) @ local)
            ends = []
            for end in (0, 1):
                spring = beam.springs[end]
                if spring is None:
                    ends.append(0.0)
                    continue
                node = beam.i if end == 0 else beam.j
                h = hinges[(b, end)]
                turn = u[h:h + 3] - u[6 * node + 3:6 * node + 6]
                ends.append(0.5 * turn @ spring.matrix(beam.axes) @ turn)
            spring_energy.append(tuple(ends))
        return Static(self, u, beam_energy, spring_energy)

    def modes(self, count=3):
        """The lowest ``count`` natural frequencies and mode shapes."""
        K, M, hinges, free = self._prepare()
        n = K.shape[0]
        kff, mff = K[np.ix_(free, free)], M[np.ix_(free, free)]
        # DOFs without mass (a node held only by springs) are condensed out.
        diag = np.diag(mff)
        massless = diag <= 1e-12 * max(diag.max(), 1e-30)
        heavy = ~massless
        if not heavy.any():
            raise ValueError("the frame has no mass")
        if massless.any():
            k00 = kff[np.ix_(massless, massless)]
            k0m = kff[np.ix_(massless, heavy)]
            recover = -linalg.solve(k00, k0m, assume_a="pos")
            kc = kff[np.ix_(heavy, heavy)] + k0m.T @ recover
        else:
            recover = None
            kc = kff
        mc = mff[np.ix_(heavy, heavy)]
        count = min(count, int(heavy.sum()))
        w, v = linalg.eigh(kc, mc, subset_by_index=[0, count - 1])
        shapes = np.zeros((n, count))
        heavy_dofs, massless_dofs = free[heavy], free[massless]
        shapes[heavy_dofs, :] = v
        if recover is not None:
            shapes[massless_dofs, :] = recover @ v

        rigid = self._rigid_motions(n, hinges, M, free)
        participation = []
        for k in range(count):
            phi = v[:, k]
            shares = {}
            for name, r in rigid.items():
                rh = r[heavy_dofs]
                total = rh @ mc @ rh
                shares[name] = float((phi @ mc @ rh) ** 2 / total) if total > 0 else 0.0
            participation.append(shares)
        frequencies = [math.sqrt(max(x, 0.0)) / (2 * math.pi) for x in w]
        return Modes(frequencies, shapes, participation)

    def _rigid_motions(self, n, hinges, M, free):
        """Unit rigid-body motions over all DOFs: translations X, Y, Z and a twist about the vertical axis.

        The twist axis passes through the centre of the free mass.
        """
        def vector(translation=None, spin=False, centre=(0.0, 0.0)):
            r = np.zeros(n)
            for node, p in enumerate(self.nodes):
                if translation is not None:
                    r[6 * node + translation] = 1.0
                if spin:
                    r[6 * node] = -(p[1] - centre[1])
                    r[6 * node + 1] = p[0] - centre[0]
                    r[6 * node + 5] = 1.0
            if spin:
                for start in hinges.values():
                    r[start + 2] = 1.0
            return r

        rx, ry, rz = vector(0), vector(1), vector(2)
        spin = vector(spin=True)
        mf = M[np.ix_(free, free)]

        def dot(a, b):
            return a[free] @ mf @ b[free]

        mx, my = dot(rx, rx), dot(ry, ry)
        cx = dot(ry, spin) / my if my > 0 else 0.0
        cy = -dot(rx, spin) / mx if mx > 0 else 0.0
        return {"X": rx, "Y": ry, "Z": rz, "twist": vector(spin=True, centre=(cx, cy))}
