"""Plotly utilization charts and popup HTML."""

import numpy as np
import plotly.graph_objects as go

from .settings import CONGESTION_THRESHOLD, FULL_CAPACITY_LINE


def build_util_plot_html(time_index, flow_signed, capacity_mw, title, subtitle):
    """Build a Plotly utilization fragment and return its summary metrics."""
    flow_signed = np.asarray(flow_signed, dtype=float)
    capacity_mw = np.asarray(capacity_mw, dtype=float)
    if capacity_mw.ndim == 0:
        capacity_mw = np.full_like(flow_signed, capacity_mw, dtype=float)
    util = np.divide(
        np.abs(flow_signed),
        capacity_mw,
        out=np.full_like(flow_signed, np.nan, dtype=float),
        where=capacity_mw > 0,
    )

    max_util = float(np.nanmax(util)) if len(util) > 0 else 0.0
    avg_util = float(np.nanmean(util)) if len(util) > 0 else 0.0
    hours_ge_08 = int(np.sum(util >= CONGESTION_THRESHOLD))
    hours_ge_10 = int(np.sum(util >= FULL_CAPACITY_LINE))

    fig = (
        go.Figure()
        # Utilization trace (|flow|/capacity)
        .add_trace(
            go.Scatter(
                x=time_index,
                y=util,
                mode="lines",
                name="Utilization |flow|/capacity (p.u.)",
                line=dict(color="green", width=1),
            )
        )
        # Flow trace (|flow| in MW)
        .add_trace(
            go.Scatter(
                x=time_index,
                y=np.abs(flow_signed),
                mode="lines",
                name="Flow |flow| (MW)",
                yaxis="y2",
                line=dict(color="blue", width=1),
            )
        )
        # 0.8 p.u. capacity threshold trace (in MW)
        .add_trace(
            go.Scatter(
                x=time_index,
                y=CONGESTION_THRESHOLD * capacity_mw,
                mode="lines",
                name="0.8 p.u. capacity threshol",
                yaxis="y2",
                line=dict(dash="dash", color="orange"),
            )
        )
        # 1.0 p.u. full capacity trace (in MW)
        .add_trace(
            go.Scatter(
                x=time_index,
                y=FULL_CAPACITY_LINE * capacity_mw,
                mode="lines",
                name="1.0 p.u. full capacity",
                yaxis="y2",
                line=dict(dash="dot", color="red"),
            )
        )
        .update_layout(
            title=dict(
                text=(
                    f"{title}<br><span style='font-size:12px'>{subtitle}<br>"
                    f"Max={max_util:.3f} p.u. | Avg={avg_util:.3f} p.u. | "
                    f"Hours ≥0.8={hours_ge_08} | Hours ≥1.0={hours_ge_10}</span>"
                ),
                x=0.01,
                xanchor="left",
            ),
            height=410,
            margin=dict(l=55, r=30, t=120, b=45),
            legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0.0),
            xaxis=dict(title="Time"),
            yaxis=dict(title="Utilization (p.u.)", rangemode="tozero"),
            yaxis2=dict(title="Flow (MW)", overlaying="y", side="right"),
        )
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn"), {
        "max_utilization": max_util,
        "avg_utilization": avg_util,
        "hours_ge_0_8": hours_ge_08,
        "hours_ge_1_0": hours_ge_10,
    }


def build_popup_html(info_html: str, plot_html: str):
    """Wrap metadata and a Plotly chart in a popup HTML block."""
    return f"""
    <div style="font-family: Arial, sans-serif; font-size: 13px; line-height: 1.25;">
      <div style="padding:8px 10px; border:1px solid #ddd; border-radius:6px; margin-bottom:10px;">
        {info_html}
      </div>
      {plot_html}
    </div>
    """
