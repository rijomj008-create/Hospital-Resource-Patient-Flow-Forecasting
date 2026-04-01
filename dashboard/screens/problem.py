"""
Screen 1 — "The Problem"
Heroes: national trend · hospital trajectories
Detail expander: ED vs Ward split · regional · month×day heatmap
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
import streamlit as st

from components.ui import (
    page_header, finding, section_heading,
    data_missing_banner, insight_callout,
)
from components.chart_theme import apply_theme

DATA = Path(__file__).parent.parent / "data"

MONTH_LABELS = ["Jan","Feb","Mar","Apr","May","Jun",
                "Jul","Aug","Sep","Oct","Nov","Dec"]
DOW_LABELS   = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _load_raw():
    p = DATA / "hse_tgar_processed.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["report_date"])
    return df


@st.cache_data(show_spinner=False)
def _load_population():
    p = DATA / "population_region.csv"
    if not p.exists():
        return None
    return pd.read_csv(p)


def _national(df: pd.DataFrame) -> pd.DataFrame:
    hosp = df[df["is_total"] == 0]
    nat = (
        hosp.groupby("report_date")[
            ["total_trolleys", "ed_trolleys", "ward_trolleys",
             "surge_capacity", "delayed_transfers", "waiting_24h"]
        ]
        .sum()
        .reset_index()
        .rename(columns={"report_date": "date"})
        .sort_values("date")
    )
    nat["rolling_28"] = nat["total_trolleys"].rolling(28, min_periods=7).mean()
    nat["year"] = nat["date"].dt.year
    return nat


def _regional(df: pd.DataFrame) -> pd.DataFrame:
    hosp = df[df["is_total"] == 0]
    reg = (
        hosp.groupby(["report_date", "region"])["total_trolleys"]
        .sum()
        .reset_index()
        .rename(columns={"report_date": "date"})
    )
    reg["year"] = reg["date"].dt.year
    return reg


def _hospital_yearly(df: pd.DataFrame) -> pd.DataFrame:
    hosp = df[df["is_total"] == 0].copy()
    hosp["year"] = hosp["report_date"].dt.year
    hdf = (
        hosp.groupby(["hospital", "region", "year"])["total_trolleys"]
        .mean()
        .reset_index()
    )
    return hdf


# ── Charts ────────────────────────────────────────────────────────────────────

def _chart_trend(nat: pd.DataFrame, year_filter: str) -> go.Figure:
    data = nat if year_filter == "All" else nat[nat["year"] == int(year_filter)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["total_trolleys"],
        mode="lines", name="Daily trolleys",
        line=dict(color="#009CA6", width=1.3),
        hovertemplate="%{x|%b %d, %Y}<br><b>%{y}</b> trolleys<extra></extra>",
    ))
    if year_filter == "All":
        fig.add_trace(go.Scatter(
            x=data["date"], y=data["rolling_28"],
            mode="lines", name="28-day average",
            line=dict(color="#003D7C", width=2, dash="dash"),
            hovertemplate="%{x|%b %d}<br>28d avg: <b>%{y:.0f}</b><extra></extra>",
        ))
        peak_idx = data["total_trolleys"].idxmax()
        peak_row = data.loc[peak_idx]
        fig.add_annotation(
            x=peak_row["date"], y=peak_row["total_trolleys"],
            text=f"Peak: {int(peak_row['total_trolleys'])} trolleys",
            showarrow=True, arrowhead=2, arrowcolor="#DC2626",
            font=dict(color="#DC2626", size=10),
            bgcolor="white", bordercolor="#DC2626", borderwidth=1,
            ax=50, ay=-35,
        )
    fig.update_layout(title=None, height=260)
    return apply_theme(fig)


def _chart_ed_ward(nat: pd.DataFrame, year_filter: str) -> go.Figure:
    data = nat if year_filter == "All" else nat[nat["year"] == int(year_filter)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["ed_trolleys"],
        mode="lines", name="ED trolleys",
        stackgroup="one",
        line=dict(color="#009CA6", width=0),
        fillcolor="rgba(0,156,166,0.55)",
        hovertemplate="%{x|%b %d}<br>ED: <b>%{y}</b><extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["ward_trolleys"],
        mode="lines", name="Ward trolleys",
        stackgroup="one",
        line=dict(color="#F59E0B", width=0),
        fillcolor="rgba(245,158,11,0.55)",
        hovertemplate="%{x|%b %d}<br>Ward: <b>%{y}</b><extra></extra>",
    ))
    fig.update_layout(title=None, height=230)
    return apply_theme(fig)


def _chart_regional(reg: pd.DataFrame, pop: pd.DataFrame | None,
                    mode: str) -> go.Figure:
    avg = reg.groupby("region")["total_trolleys"].mean().reset_index()
    avg.columns = ["region", "avg_trolleys"]
    avg = avg.sort_values("avg_trolleys", ascending=True)

    if mode == "Per Capita" and pop is not None:
        avg = avg.merge(pop, on="region", how="left")
        avg["value"] = (avg["avg_trolleys"] / avg["population"] * 100_000).round(1)
        x_label = "Avg daily trolleys per 100k population"
    else:
        avg["value"] = avg["avg_trolleys"].round(1)
        x_label = "Average daily trolleys"

    fig = go.Figure(go.Bar(
        x=avg["value"], y=avg["region"],
        orientation="h",
        marker_color="#009CA6",
        text=avg["value"].apply(lambda v: f"{v:.1f}"),
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>%{x:.1f}<extra></extra>",
    ))
    fig.update_layout(
        title=None, height=260,
        xaxis_title=x_label,
        yaxis_title=None,
    )
    return apply_theme(fig)


def _chart_trajectories(hdf: pd.DataFrame) -> go.Figure:
    years = sorted(hdf["year"].unique())

    if len(years) < 2:
        avg = hdf.groupby("hospital")["total_trolleys"].mean().nlargest(20).reset_index()
        fig = go.Figure(go.Bar(
            x=avg["total_trolleys"], y=avg["hospital"],
            orientation="h", marker_color="#009CA6",
        ))
        fig.update_layout(title=None, height=360)
        return apply_theme(fig)

    first_year, last_year = years[0], years[-1]
    pivot = hdf.pivot_table(values="total_trolleys",
                            index="hospital", columns="year").reset_index()
    pivot = pivot.dropna(subset=[first_year, last_year])
    pivot["slope"] = pivot[last_year] - pivot[first_year]
    pivot["category"] = pivot["slope"].apply(
        lambda s: "Deteriorating" if s > 2 else ("Improving" if s < -2 else "Stable")
    )

    top20 = pivot.nlargest(20, last_year)

    colour_map = {
        "Deteriorating": "#DC2626",
        "Stable":        "#6B7280",
        "Improving":     "#007A4D",
    }

    fig = go.Figure()
    for cat, colour in colour_map.items():
        sub = top20[top20["category"] == cat]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub[last_year], y=sub["hospital"],
            orientation="h",
            name=cat,
            marker_color=colour,
            hovertemplate=(
                "<b>%{y}</b><br>"
                f"{last_year} avg: %{{x:.1f}}<extra></extra>"
            ),
            text=sub["slope"].apply(
                lambda s: f"+{s:.1f}" if s > 0 else f"{s:.1f}"
            ),
            textposition="outside",
        ))

    fig.update_layout(
        title=None, height=380,
        barmode="overlay",
        yaxis=dict(categoryorder="total ascending"),
        legend=dict(orientation="h", y=1.05),
    )
    return apply_theme(fig)


def _chart_dow_month(nat: pd.DataFrame) -> go.Figure:
    nat = nat.copy()
    nat["dow"]   = nat["date"].dt.dayofweek
    nat["month"] = nat["date"].dt.month

    pivot = nat.pivot_table(
        values="total_trolleys", index="month", columns="dow", aggfunc="mean"
    ).round(0)

    months_p = [m for m in range(1, 13) if m in pivot.index]
    dows_p   = [d for d in range(7)      if d in pivot.columns]

    z = [[pivot.loc[m, d] if (m in pivot.index and d in pivot.columns) else None
          for d in dows_p] for m in months_p]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=[DOW_LABELS[d] for d in dows_p],
        y=[MONTH_LABELS[m - 1] for m in months_p],
        colorscale=[[0, "#E6F7F7"], [0.5, "#009CA6"], [1, "#003D7C"]],
        showscale=True,
        colorbar=dict(thickness=10, len=0.8,
                      tickfont=dict(size=9, color="#6B7280")),
        text=[[f"{v:.0f}" if v else "" for v in row] for row in z],
        texttemplate="%{text}",
        textfont=dict(size=9, color="white"),
        hovertemplate="<b>%{y} — %{x}</b><br>Avg: %{z:.0f} trolleys<extra></extra>",
    ))
    fig.update_layout(
        title=None, height=300,
        yaxis=dict(autorange="reversed"),
    )
    return apply_theme(fig)


# ── Main render ───────────────────────────────────────────────────────────────

def render_problem():
    page_header(
        "The Problem",
        "What Is the Trolley Crisis?",
        "Ireland averages 273 patients on trolleys every day. "
        "The number has grown each year. Some hospitals are getting significantly worse.",
    )

    df = _load_raw()
    pop = _load_population()

    if df is None:
        data_missing_banner()
        st.stop()

    nat = _national(df)
    reg = _regional(df)
    hdf = _hospital_yearly(df)

    years = ["All"] + sorted(nat["year"].unique().astype(str).tolist())

    # ── Hero 1: National trend ──
    st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
    insight_callout(
        "Each spike is a winter surge. The dashed line (28-day average) shows the underlying trend — "
        "it rises each year and never fully returns to where it started. "
        "Use the filter to zoom into a single year."
    )
    section_heading("The crisis has gotten worse every winter")
    year_filter = st.radio(
        "Year", years, horizontal=True, label_visibility="collapsed"
    )
    st.plotly_chart(
        _chart_trend(nat, year_filter),
        width="stretch",
        config={"displayModeBar": False},
    )
    finding("Ireland averages 273 trolleys per day — a figure that has worsened each winter since 2023")
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Hero 2: Hospital trajectories ──
    st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
    insight_callout(
        "Red bars show hospitals where the average trolley count has risen year-on-year. "
        "Green bars show hospitals that have improved. "
        "The number next to each bar shows the change since the first year of data."
    )
    section_heading("Some hospitals are getting worse — others are holding steady")
    st.plotly_chart(
        _chart_trajectories(hdf),
        width="stretch",
        config={"displayModeBar": False},
    )
    finding("6 hospitals are deteriorating year-on-year — UH Limerick and Galway UH show the steepest increases")
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Detail expander ──
    with st.expander("Dig deeper: type of trolley, regional breakdown, and time patterns"):

        # ED vs Ward
        st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
        insight_callout(
            "Trolleys in the Emergency Department (teal) show people waiting to be admitted. "
            "Trolleys in wards (amber) show people who have been admitted but have no bed — "
            "known as bed block. A growing amber share means the problem is spreading deeper into the hospital."
        )
        section_heading("ED trolleys vs ward trolleys — where are patients waiting?")
        st.plotly_chart(
            _chart_ed_ward(nat, year_filter),
            width="stretch",
            config={"displayModeBar": False},
        )
        finding("A rising ward trolley share signals bed block — the crisis is shifting deeper into the system")
        st.markdown("</div>", unsafe_allow_html=True)

        # Regional
        st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
        insight_callout(
            "Toggle 'Per 100k population' to account for the size of each region. "
            "A region with a large population naturally has more trolleys in total — "
            "the per-capita view shows which regions are most under-resourced relative to their population."
        )
        section_heading("Which HSE region carries the most pressure?")
        mode = st.toggle("Per 100k population", value=False)
        mode_label = "Per Capita" if mode else "Absolute"
        st.plotly_chart(
            _chart_regional(reg, pop, mode_label),
            width="stretch",
            config={"displayModeBar": False},
        )
        if mode:
            finding("Adjusted for population, some regions are more severely under-resourced than raw totals suggest")
        else:
            finding("HSE West & North West and South regions carry the heaviest absolute trolley burden")
        st.markdown("</div>", unsafe_allow_html=True)

        # Day × Month heatmap
        st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
        insight_callout(
            "Darker blue = more trolleys on average. "
            "Each cell is the average for that combination of month and day of week across all years of data. "
            "The top-left corner (January Mondays) is consistently the darkest."
        )
        section_heading("When is pressure highest? Month and day of week")
        st.plotly_chart(
            _chart_dow_month(nat),
            width="stretch",
            config={"displayModeBar": False},
        )
        finding("Monday mornings in January and February are Ireland's highest-pressure moments — every year")
        st.markdown("</div>", unsafe_allow_html=True)
