"""
ui/charts.py — Γραφήματα.

Plotly αντί για st.line_chart: θέλουμε hover που δείχνει και τα δύο έτη μαζί,
γιατί η ερώτηση δεν είναι «πόσο πούλησα την εβδομάδα 12» αλλά «πόσο πούλησα
σε σχέση με πέρσι την εβδομάδα 12».
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import COLOR

FONT = "Manrope, Inter, system-ui, sans-serif"

_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family=FONT, size=12, color=COLOR["muted"]),
    margin=dict(l=8, r=8, t=8, b=8),
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="#FFFFFF",
        bordercolor=COLOR["grid"],
        font=dict(family=FONT, size=12, color=COLOR["text"]),
    ),
    legend=dict(
        orientation="h",
        yanchor="bottom", y=1.0,
        xanchor="right", x=1,
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
    ),
    xaxis=dict(
        showgrid=False,
        zeroline=False,
        linecolor=COLOR["grid"],
        tickfont=dict(size=11),
    ),
    yaxis=dict(
        gridcolor=COLOR["grid"],
        zeroline=False,
        showline=False,
        tickfont=dict(size=11),
    ),
)

_CONFIG = {"displayModeBar": False, "responsive": True, "staticPlot": False}


def _show(fig: go.Figure, height: int) -> None:
    fig.update_layout(**_LAYOUT, height=height)
    st.plotly_chart(fig, width='stretch', config=_CONFIG)


def year_over_year(
    weeks: list[int],
    now: list,
    then: list,
    *,
    unit: str = "€",
    height: int = 280,
    label_now: str = "Φέτος",
    label_then: str = "Πέρσι",
) -> None:
    """
    Φέτος με γεμάτη γραμμή και σκίαση. Πέρσι με διακεκομμένη γκρι.
    Το πέρσι είναι αναφορά, όχι δεύτερος πρωταγωνιστής — γι' αυτό είναι σβηστό.
    """
    fig = go.Figure()

    suffix = " €" if unit == "€" else ""

    fig.add_trace(go.Scatter(
        x=weeks, y=then,
        name=label_then,
        mode="lines",
        line=dict(color=COLOR["prev"], width=1.6, dash="dot"),
        hovertemplate=f"%{{y:,.0f}}{suffix}<extra>{label_then}</extra>",
        connectgaps=False,
    ))

    fig.add_trace(go.Scatter(
        x=weeks, y=now,
        name=label_now,
        mode="lines",
        line=dict(color=COLOR["ab_red"], width=2.6, shape="spline", smoothing=0.5),
        fill="tozeroy",
        fillcolor="rgba(226,35,26,.06)",
        hovertemplate=f"%{{y:,.0f}}{suffix}<extra>{label_now}</extra>",
        connectgaps=False,
    ))

    fig.update_xaxes(title=None, dtick=4)
    fig.update_yaxes(title=None, tickformat=",.0f")

    _show(fig, height)


def bars(labels: list[str], values: list[float], *, height: int = 260, color: str | None = None) -> None:
    """Απλό ραβδόγραμμα — για ανάλυση ανά μήνα."""
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker=dict(color=color or COLOR["ab_red"], line=dict(width=0)),
        hovertemplate="%{y:,.0f} €<extra>%{x}</extra>",
        width=0.62,
    ))
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=None, tickformat=",.0f")
    _show(fig, height)


def paired_bars(
    labels: list[str],
    now: list[float],
    then: list[float],
    *,
    height: int = 280,
    label_now: str = "Φέτος",
    label_then: str = "Πέρσι",
) -> None:
    """Δύο σειρές δίπλα-δίπλα — μήνας φέτος vs μήνας πέρσι."""
    fig = go.Figure()

    fig.add_trace(go.Bar(
        name=label_then, x=labels, y=then,
        marker=dict(color=COLOR["prev"], opacity=.45, line=dict(width=0)),
        hovertemplate="%{y:,.0f} €<extra>" + label_then + "</extra>",
    ))
    fig.add_trace(go.Bar(
        name=label_now, x=labels, y=now,
        marker=dict(color=COLOR["ab_red"], line=dict(width=0)),
        hovertemplate="%{y:,.0f} €<extra>" + label_now + "</extra>",
    ))

    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=None, tickformat=",.0f")

    _show(fig, height)


def daily_week(dates: list, values: list[float], *, height: int = 220) -> None:
    """Οι μέρες μιας εβδομάδας. Το Σάββατο ξεχωρίζει — είναι η μεγάλη μέρα."""
    from core.metrics import day_name

    labels = [f"{day_name(d, short=True)} {d:%d/%m}" for d in dates]
    colors = [
        COLOR["ink"] if d.weekday() == 5 else COLOR["ab_red"]
        for d in dates
    ]

    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker=dict(color=colors, line=dict(width=0)),
        hovertemplate="%{y:,.0f} €<extra>%{x}</extra>",
        width=0.55,
    ))
    fig.update_xaxes(title=None)
    fig.update_yaxes(title=None, tickformat=",.0f")
    _show(fig, height)
