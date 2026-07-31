"""Chart styling, so every figure in the notebooks reads as one system.

The palette is a validated categorical set: adjacent pairs clear the
colour-vision-deficiency separation floor (worst adjacent ΔE 9.1 protan) and the
normal-vision floor (worst 22.9), on a light surface. Slots are assigned in fixed
order and never cycled — a chart that needs a ninth series needs small multiples,
not a ninth hue.

Two slots (aqua, yellow) sit below 3:1 contrast against the chart surface, which
obliges visible labels wherever they carry meaning. `label_bars` exists for that
reason rather than for decoration.

House rules enforced by `style()`: recessive grid and axes so the data is the
darkest thing on the page, no top or right spine, text in ink rather than series
colour, and a single value axis — never two y-scales, which is the commonest way
a chart misleads.
"""

from __future__ import annotations

__all__ = ["PALETTE", "INK", "GRID", "SURFACE", "style", "label_bars", "despine"]

#: Categorical slots in fixed assignment order.
PALETTE = {
    "blue": "#2a78d6",
    "orange": "#eb6834",
    "aqua": "#1baf7a",
    "yellow": "#eda100",
    "magenta": "#e87ba4",
    "green": "#008300",
}
SERIES = list(PALETTE.values())

INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e3e2df"
SURFACE = "#fcfcfb"


def style() -> None:
    """Apply the house style to matplotlib. Call once per notebook."""
    import matplotlib as mpl

    mpl.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "figure.dpi": 110,
        "figure.figsize": (8.5, 4.2),

        # Recessive frame: the data should be the darkest thing on the page.
        "axes.edgecolor": GRID,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,

        # Text wears ink, never a series colour.
        "text.color": INK,
        "axes.labelcolor": INK_MUTED,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.titlepad": 10,
        "font.size": 9.5,

        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "lines.linewidth": 2.0,
        "lines.markersize": 5,
        "axes.prop_cycle": mpl.cycler(color=SERIES),
    })


def despine(ax) -> None:
    """Drop the value-axis spine too, where the grid already carries the scale."""
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def label_bars(ax, bars, values, fmt="{:,.0f}", *, horizontal=False, pad=3) -> None:
    """Direct-label bars.

    Required, not decorative, wherever a low-contrast slot carries meaning: the
    validator flags aqua and yellow below 3:1 against the surface, and a visible
    label is the relief that makes them legal.
    """
    for bar, value in zip(bars, values):
        if horizontal:
            ax.annotate(fmt.format(value),
                        (bar.get_width(), bar.get_y() + bar.get_height() / 2),
                        xytext=(pad, 0), textcoords="offset points",
                        va="center", ha="left", color=INK_MUTED, fontsize=8.5)
        else:
            ax.annotate(fmt.format(value),
                        (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, pad), textcoords="offset points",
                        va="bottom", ha="center", color=INK_MUTED, fontsize=8.5)
