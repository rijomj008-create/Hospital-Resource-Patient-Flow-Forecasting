"""
Home screen — "Why This Matters"
One hero chart (national trend) + collapsible detail (heatmap + capacity preview).
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path
import streamlit as st

from components.ui import (
    page_header, stat_row_home, finding, section_heading,
    data_missing_banner, insight_callout,
)
from components.chart_theme import apply_theme

DATA = Path(__file__).parent.parent / "data"


@st.cache_data(show_spinner=False)
def _load_national():
    p = DATA / "hse_tgar_processed.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["report_date"])
    hosp = df[df["is_total"] == 0]
    nat = (
        hosp.groupby("report_date")[["total_trolleys", "ed_trolleys", "ward_trolleys"]]
        .sum()
        .reset_index()
        .rename(columns={"report_date": "date"})
        .sort_values("date")
    )
    nat["rolling_28"] = nat["total_trolleys"].rolling(28, min_periods=7).mean()
    return nat


@st.cache_data(show_spinner=False)
def _load_forecast_and_thresholds():
    fc_path = DATA / "hospital_forecast.csv"
    thr_path = DATA / "capacity_thresholds.csv"
    test_path = DATA / "hospital_predictions_test.csv"

    if not fc_path.exists():
        return None, None

    fc = pd.read_csv(fc_path, parse_dates=["report_date"])

    if thr_path.exists():
        thr = pd.read_csv(thr_path)
    elif test_path.exists():
        test = pd.read_csv(test_path)
        thr = (
            test.groupby("hospital")["y_hosp"]
            .agg(mean_y="mean", sd_y="std")
            .reset_index()
        )
        thr["threshold_amber"] = thr["mean_y"] + 1.5 * thr["sd_y"]
        thr["threshold_red"] = thr["mean_y"] + 2.0 * thr["sd_y"]
    else:
        return fc, None

    return fc, thr


# ── Charts ────────────────────────────────────────────────────────────────────

def _chart_national_trend(nat: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=nat["date"], y=nat["total_trolleys"],
        mode="lines",
        name="Daily trolleys",
        line=dict(color="#009CA6", width=1.2),
        hovertemplate="%{x|%b %d, %Y}<br><b>%{y}</b> trolleys<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=nat["date"], y=nat["rolling_28"],
        mode="lines",
        name="28-day average",
        line=dict(color="#003D7C", width=1.8, dash="dash"),
        hovertemplate="%{x|%b %d}<br>28-day avg: <b>%{y:.0f}</b><extra></extra>",
    ))
    peak_idx = nat["total_trolleys"].idxmax()
    peak_row = nat.loc[peak_idx]
    fig.add_annotation(
        x=peak_row["date"], y=peak_row["total_trolleys"],
        text=f"Peak: {int(peak_row['total_trolleys'])}",
        showarrow=True, arrowhead=2,
        arrowcolor="#DC2626", font=dict(color="#DC2626", size=10),
        bgcolor="white", bordercolor="#DC2626", borderwidth=1,
        ax=40, ay=-30,
    )
    fig.update_layout(title=None, height=240)
    return apply_theme(fig)


def _chart_dow_month_heatmap(nat: pd.DataFrame) -> go.Figure:
    nat = nat.copy()
    nat["dow"] = nat["date"].dt.dayofweek
    nat["month"] = nat["date"].dt.month

    pivot = (
        nat.pivot_table(
            values="total_trolleys", index="month", columns="dow", aggfunc="mean"
        )
        .round(0)
    )

    month_labels = ["Jan","Feb","Mar","Apr","May","Jun",
                    "Jul","Aug","Sep","Oct","Nov","Dec"]
    dow_labels = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

    months_present = [m for m in range(1, 13) if m in pivot.index]
    dows_present = [d for d in range(7) if d in pivot.columns]

    z = [[pivot.loc[m, d] if (m in pivot.index and d in pivot.columns) else None
          for d in dows_present] for m in months_present]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=[dow_labels[d] for d in dows_present],
        y=[month_labels[m - 1] for m in months_present],
        colorscale=[[0, "#E6F7F7"], [0.5, "#009CA6"], [1, "#003D7C"]],
        showscale=False,
        hovertemplate="<b>%{y} %{x}</b><br>Avg: %{z:.0f} trolleys<extra></extra>",
        text=[[f"{v:.0f}" if v else "" for v in row] for row in z],
        texttemplate="%{text}",
        textfont=dict(size=9, color="white"),
    ))
    fig.update_layout(title=None, height=240,
                      yaxis=dict(autorange="reversed"))
    return apply_theme(fig)


def _alert_heatmap_preview(fc: pd.DataFrame, thr: pd.DataFrame) -> None:
    if thr is None:
        st.info("Threshold data unavailable — run export script for full alerts.")
        return

    fc = fc.copy()
    fc["report_date"] = pd.to_datetime(fc["report_date"])
    merged = fc.merge(thr[["hospital", "threshold_amber", "threshold_red"]],
                      on="hospital", how="left")

    top_hospitals = (
        merged.groupby("hospital")["pred_hosp"].mean()
        .nlargest(8).index.tolist()
    )
    merged = merged[merged["hospital"].isin(top_hospitals)]

    dates = sorted(merged["report_date"].unique())[:14]
    merged = merged[merged["report_date"].isin(dates)]

    def status(row):
        if pd.isna(row["threshold_red"]):
            return "green"
        if row["pred_hosp"] >= row["threshold_red"]:
            return "red"
        if row["pred_hosp"] >= row["threshold_amber"]:
            return "amber"
        return "green"

    merged["status"] = merged.apply(status, axis=1)

    colours = {
        "green": ("#D1FAE5", "#065F46"),
        "amber": ("#FEF3C7", "#92400E"),
        "red":   ("#FEE2E2", "#991B1B"),
    }

    date_labels = [pd.to_datetime(d).strftime("%b %d").replace(" 0", " ") for d in dates]

    html = """
    <div style="overflow-x:auto;">
    <table style="border-collapse:separate;border-spacing:2px;width:100%;
                  font-family:'DM Sans',sans-serif;">
    <thead>
      <tr>
        <th style="font-size:10px;color:#6B7280;text-align:left;
                   padding:4px 8px;font-weight:500;">Hospital</th>
    """
    for dl in date_labels:
        html += f'<th style="font-size:9px;color:#6B7280;text-align:center;padding:2px 4px;">{dl}</th>'
    html += "</tr></thead><tbody>"

    for hosp in top_hospitals:
        sub = merged[merged["hospital"] == hosp].set_index("report_date")
        short = hosp[:18] + ("…" if len(hosp) > 18 else "")
        html += f'<tr><td style="font-size:10px;color:#0D1B2A;padding:3px 8px;white-space:nowrap;">{short}</td>'
        for d in dates:
            if d in sub.index:
                row = sub.loc[d]
                val = f"{row['pred_hosp']:.0f}"
                s = row["status"]
                bg, fg = colours[s]
                html += (
                    f'<td style="background:{bg};color:{fg};padding:4px 6px;'
                    f'border-radius:3px;font-size:10px;font-weight:600;'
                    f'text-align:center;">{val}</td>'
                )
            else:
                html += '<td style="text-align:center;font-size:9px;color:#ccc;">—</td>'
        html += "</tr>"

    html += """
    </tbody></table>
    <div style="display:flex;gap:16px;margin-top:8px;font-size:10px;color:#6B7280;">
        <span><span style="display:inline-block;width:10px;height:10px;
              background:#D1FAE5;border-radius:2px;margin-right:4px;"></span>Within normal</span>
        <span><span style="display:inline-block;width:10px;height:10px;
              background:#FEF3C7;border-radius:2px;margin-right:4px;"></span>Elevated pressure</span>
        <span><span style="display:inline-block;width:10px;height:10px;
              background:#FEE2E2;border-radius:2px;margin-right:4px;"></span>Critical pressure</span>
    </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ── Main render ───────────────────────────────────────────────────────────────

def render_home():
    page_header(
        "Ireland · 2023–2026 · 36 Hospitals",
        "Ireland's Trolley Crisis, Decoded",
        "Every day, hundreds of patients in Irish hospitals wait on trolleys "
        "because there are no beds. This dashboard shows how bad it is, "
        "what causes it, and what the next 14 days look like.",
    )

    stat_row_home()
    st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)

    nat = _load_national()

    if nat is None:
        data_missing_banner()
        st.stop()

    # ── Hero: national trend ──
    st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
    insight_callout(
        "The number of patients on trolleys has risen every winter since 2023. "
        "January 13, 2026 set the record: 488 patients waited on trolleys in a single day. "
        "The dashed line shows the 28-day rolling average — look at how it climbs each year."
    )
    section_heading("National trolley count · 2023–2026")
    st.plotly_chart(
        _chart_national_trend(nat),
        width="stretch",
        config={"displayModeBar": False},
    )
    finding("Winter 2025–26 is the worst period on record in this dataset")
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Collapsible detail ──
    with st.expander("See more: when pressure peaks and which hospitals are most at risk"):
        c_left, c_right = st.columns([1, 1])

        with c_left:
            st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
            insight_callout(
                "Darker cells = more trolleys on average. "
                "Look at the top-left corner: January Mondays are consistently Ireland's worst moment."
            )
            section_heading("When is pressure highest? Month × day of week")
            st.plotly_chart(
                _chart_dow_month_heatmap(nat),
                width="stretch",
                config={"displayModeBar": False},
            )
            finding("Monday mornings in January are Ireland's highest-pressure moment")
            st.markdown("</div>", unsafe_allow_html=True)

        with c_right:
            st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
            insight_callout(
                "Green = within normal range. Amber = elevated. Red = critical. "
                "Thresholds are set per hospital — a red alert at a small hospital "
                "is just as serious as one at a large one."
            )
            section_heading("14-day forecast: top 8 hospitals by pressure")
            fc, thr = _load_forecast_and_thresholds()
            if fc is not None:
                _alert_heatmap_preview(fc, thr)
            else:
                data_missing_banner()
            st.markdown("</div>", unsafe_allow_html=True)
