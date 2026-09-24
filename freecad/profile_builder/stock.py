"""Cutting pieces from stock bars (1D cutting stock), pure Python.

Uses first-fit and best-fit decreasing and keeps whichever needs fewer bars
(then: the larger single offcut, which is the more useful leftover). For the
handful of pieces in a typical frame this is optimal or within one bar.
"""

from dataclasses import dataclass, field


@dataclass
class Bar:
    length: float
    usable: float
    pieces: list = field(default_factory=list)  # [(length, label)]
    remaining: float = 0.0

    @property
    def used(self):
        return sum(length for length, _label in self.pieces)

    @property
    def offcut(self):
        return max(0.0, self.remaining)


@dataclass
class Plan:
    stock_length: float
    kerf: float
    end_trim: float
    bars: list
    oversize: list  # pieces longer than a stock bar: [(length, label)]

    @property
    def bought_length(self):
        return self.stock_length * len(self.bars)

    @property
    def piece_length(self):
        return sum(b.used for b in self.bars)

    @property
    def waste(self):
        """Fraction of the bought material that is not in a piece (kerf, trim and offcuts)."""
        return 1 - self.piece_length / self.bought_length if self.bars else 0.0


def _pack(pieces, usable, kerf, stock_length, best_fit):
    bars = []
    for length, label in pieces:
        fits = [b for b in bars if length <= b.remaining + 1e-9]
        if fits:
            bar = min(fits, key=lambda b: b.remaining) if best_fit else fits[0]
        else:
            bar = Bar(stock_length, usable, remaining=usable)
            bars.append(bar)
        bar.pieces.append((length, label))
        # The saw cut after a piece eats the kerf, unless nothing is left anyway.
        bar.remaining -= length + kerf
    return bars


def plan(pieces, stock_length, kerf=0.0, end_trim=0.0):
    """Assign pieces [(length, label)] to bars of ``stock_length``.

    ``kerf`` is the material lost per saw cut; ``end_trim`` is cut off each bar
    once to square its end.
    """
    if stock_length <= 0:
        raise ValueError("Stock length must be positive")
    usable = stock_length - end_trim
    ordered = sorted(pieces, key=lambda p: -p[0])
    oversize = [p for p in ordered if p[0] > usable + 1e-9]
    fitting = [p for p in ordered if p[0] <= usable + 1e-9]
    options = [_pack(fitting, usable, kerf, stock_length, best_fit) for best_fit in (False, True)]
    bars = min(options, key=lambda bs: (len(bs), -max((b.offcut for b in bs), default=0)))
    return Plan(stock_length, kerf, end_trim, bars, oversize)
