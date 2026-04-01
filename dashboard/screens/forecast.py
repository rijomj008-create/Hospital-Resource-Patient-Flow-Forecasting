"""
Screen 3 — "What's Coming"
Heroes: national forecast · model transparency · hospital explorer
Detail expander: full 36-hospital capacity alert heatmap
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path
import streamlit as st

from components.ui import (
    page_header, finding, section_heading,
    data_missing_banner, insight_callout,
)
from components.chart_theme import apply_theme

DATA = Path(__file__).parent.parent / "data"


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _load_national_history():
    p = DATA / "hse_tgar_processed.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["report_date"])
    hosp = df[df["is_total"] == 0]
    nat = (
        hosp.groupby("report_date")[["total_trolleys"]]
        .sum()
        .reset_index()
        .rename(columns={"report_date": "date"})
        .sort_values("date")
    )
    nat["rolling_28"] = nat["total_trolleys"].rolling(28, min_periods=7).mean()
    return nat


@st.cache_data(show_spinner=False)
def _load_national_forecast():
    p = DATA / "national_forecast.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["report_date"])
    return df.sort_values("report_date")


@st.cache_data(show_spinner=False)
def _load_metrics():
    p = DATA / "national_overall_metrics.csv"
    if not p.exists():
        return None
    return pd.read_csv(p)


@st.cache_data(show_spinner=False)
def _load_forecast_and_thresholds():
    fc_path  = DATA / "hospital_forecast.csv"
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
        thr["threshold_red"]   = thr["mean_y"] + 2.0 * thr["sd_y"]
    else:
        return fc, None

    return fc, thr


@st.cache_data(show_spinner=False)
def _load_hospital_history():
    p = DATA / "hse_tgar_processed.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["report_date"])
    return df[df["is_total"] == 0]


# ── Chart functions ───────────────────────────────────────────────────────────

def _chart_national_forecast(nat: pd.DataFrame, fc: pd.DataFrame) -> go.Figure:
    history = nat.tail(60).copy()

    forecast_start = fc["report_date"].min()

    fig = go.Figure()

    fig.add_vrect(
        x0=forecast_start,
        x1=fc["report_date"].max(),
        fillcolor="#009CA6",
        opacity=0.08,
        line_width=0,
        layer="below",
    )

    fig.add_trace(go.Scatter(
        x=history["date"],
        y=history["rolling_28"],
        mode="lines",
        name="28-day avg",
        line=dict(color="#003D7C", width=1.5, dash="dash"),
        hovertemplate="%{x|%b %d}<br>28-day avg: <b>%{y:.0f}</b><extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=history["date"],
        y=history["total_trolleys"],
        mode="lines",
        name="Actual trolleys",
        line=dict(color="#009CA6", width=2),
        hovertemplate="%{x|%b %d, %Y}<br>Actual: <b>%{y}</b> trolleys<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=fc["report_date"],
        y=fc["pred_national"].round(0),
        mode="lines",
        name="14-day forecast",
        line=dict(color="#009CA6", width=2, dash="dash"),
        hovertemplate="%{x|%b %d}<br>Forecast: <b>%{y:.0f}</b> trolleys<extra></extra>",
    ))

    fig.add_annotation(
        x=forecast_start,
        yref="paper", y=0.97,
        text="Forecast →",
        showarrow=False,
        font=dict(size=10, color="#009CA6"),
        xanchor="left",
        bgcolor="rgba(255,255,255,0.85)",
        borderpad=3,
    )

    fig.update_layout(
        title=None,
        height=280,
        legend=dict(orientation="h", y=1.08, x=0),
    )
    return apply_theme(fig)


def _render_metrics(metrics: pd.DataFrame):
    row = metrics.iloc[0]

    mae_model    = row.get("mae_model",    "—")
    mape_model   = row.get("mape_model",   "—")
    mae_baseline = row.get("mae_baseline", "—")
    mape_baseline = row.get("mape_baseline", "—")
    test_rows    = int(row.get("test_rows", 90))
    mae_lift_pct = row.get("mae_lift", None)

    def fmt_float(v, decimals=1):
        try:
            return f"{float(v):.{decimals}f}"
        except (TypeError, ValueError):
            return str(v)

    lift_sentence = ""
    if mae_lift_pct is not None:
        try:
            pct = float(mae_lift_pct) / float(mae_baseline) * 100
            lift_sentence = (
                f"<b>{pct:.0f}% reduction in forecast error</b> vs. simply using last week's number."
            )
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    html = f"""
    <div style="display:flex;gap:16px;flex-wrap:wrap;">
      <div style="flex:1;min-width:200px;background:#F5F3EE;border-radius:8px;
                  padding:16px 20px;border-top:3px solid #009CA6;">
        <p style="font-size:11px;font-weight:600;color:#003D7C;margin:0 0 12px;
                  text-transform:uppercase;letter-spacing:.5px;">This Model</p>
        <div style="display:flex;flex-direction:column;gap:8px;">
          <div>
            <p style="font-size:22px;font-weight:700;color:#0D1B2A;margin:0;
                      line-height:1;">{fmt_float(mae_model)} trolleys</p>
            <p style="font-size:11px;color:#6B7280;margin:2px 0 0;">Average daily error</p>
          </div>
          <div>
            <p style="font-size:22px;font-weight:700;color:#0D1B2A;margin:0;
                      line-height:1;">{fmt_float(mape_model)}%</p>
            <p style="font-size:11px;color:#6B7280;margin:2px 0 0;">Error as % of actual</p>
          </div>
          <div>
            <p style="font-size:14px;font-weight:600;color:#0D1B2A;margin:0;">{test_rows} days</p>
            <p style="font-size:11px;color:#6B7280;margin:2px 0 0;">Test period (not used in training)</p>
          </div>
        </div>
      </div>
      <div style="flex:1;min-width:200px;background:#F5F3EE;border-radius:8px;
                  padding:16px 20px;border-top:3px solid #DDD9CF;">
        <p style="font-size:11px;font-weight:600;color:#6B7280;margin:0 0 12px;
                  text-transform:uppercase;letter-spacing:.5px;">Simple Guess (Baseline)</p>
        <div style="display:flex;flex-direction:column;gap:8px;">
          <div>
            <p style="font-size:22px;font-weight:700;color:#6B7280;margin:0;
                      line-height:1;">{fmt_float(mae_baseline)} trolleys</p>
            <p style="font-size:11px;color:#6B7280;margin:2px 0 0;">Average daily error</p>
          </div>
          <div>
            <p style="font-size:22px;font-weight:700;color:#6B7280;margin:0;
                      line-height:1;">{fmt_float(mape_baseline)}%</p>
            <p style="font-size:11px;color:#6B7280;margin:2px 0 0;">Error as % of actual</p>
          </div>
          <div>
            <p style="font-size:14px;font-weight:600;color:#6B7280;margin:0;">{test_rows} days</p>
            <p style="font-size:11px;color:#6B7280;margin:2px 0 0;">Test period</p>
          </div>
        </div>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

    if lift_sentence:
        st.markdown(
            f'<p style="font-size:12px;color:#0D1B2A;margin:12px 0 0;line-height:1.5;">'
            f'{lift_sentence}</p>',
            unsafe_allow_html=True,
        )


def _alert_heatmap_full(fc: pd.DataFrame, thr: pd.DataFrame):
    if thr is None:
        st.info("Threshold data unavailable — run export script for full alerts.")
        return

    fc = fc.copy()
    fc["report_date"] = pd.to_datetime(fc["report_date"])
    merged = fc.merge(thr[["hospital", "threshold_amber", "threshold_red"]],
                      on="hospital", how="left")

    hosp_order = (
        merged.groupby("hospital")["pred_hosp"]
        .mean()
        .sort_values(ascending=False)
        .index.tolist()
    )

    dates = sorted(merged["report_date"].unique())[:14]
    merged = merged[merged["report_date"].isin(dates)]

    def status(row):
        if pd.isna(row.get("threshold_red")):
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

    date_labels = [
        pd.to_datetime(d).strftime("%b %d").replace(" 0", " ") for d in dates
    ]

    html = """
    <div style="overflow-x:auto;">
    <table style="border-collapse:separate;border-spacing:2px;width:100%;
                  font-family:'DM Sans',sans-serif;">
    <thead>
      <tr>
        <th style="font-size:10px;color:#6B7280;text-align:left;
                   padding:4px 8px;font-weight:500;white-space:nowrap;">Hospital</th>
    """
    for dl in date_labels:
        html += (
            f'<th style="font-size:9px;color:#6B7280;text-align:center;'
            f'padding:2px 4px;white-space:nowrap;">{dl}</th>'
        )
    html += "</tr></thead><tbody>"

    for hosp in hosp_order:
        sub = merged[merged["hospital"] == hosp].set_index("report_date")
        short = hosp[:22] + ("…" if len(hosp) > 22 else "")
        html += (
            f'<tr><td style="font-size:10px;color:#0D1B2A;padding:3px 8px;'
            f'white-space:nowrap;">{short}</td>'
        )
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
    <div style="display:flex;gap:16px;margin-top:10px;font-size:10px;color:#6B7280;">
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


def _chart_hospital_explorer(
    hospital: str,
    fc: pd.DataFrame,
    thr: pd.DataFrame,
    hosp_history: pd.DataFrame,
) -> go.Figure:
    fc_h = fc[fc["hospital"] == hospital].copy()
    fc_h["report_date"] = pd.to_datetime(fc_h["report_date"])

    hist_h = (
        hosp_history[hosp_history["hospital"] == hospital]
        .copy()
        .rename(columns={"report_date": "date"})
        .sort_values("date")
    )
    hist_h = hist_h.tail(30)

    amber, red = None, None
    if thr is not None:
        t_row = thr[thr["hospital"] == hospital]
        if not t_row.empty:
            amber = t_row.iloc[0].get("threshold_amber")
            red   = t_row.iloc[0].get("threshold_red")

    fig = go.Figure()

    if amber is not None and not pd.isna(amber):
        all_dates = list(hist_h["date"]) + list(fc_h["report_date"])
        fig.add_trace(go.Scatter(
            x=all_dates,
            y=[amber] * len(all_dates),
            mode="lines",
            name="Elevated threshold",
            line=dict(color="#F59E0B", width=1.5, dash="dash"),
            hoverinfo="skip",
        ))

    if red is not None and not pd.isna(red):
        all_dates = list(hist_h["date"]) + list(fc_h["report_date"])
        fig.add_trace(go.Scatter(
            x=all_dates,
            y=[red] * len(all_dates),
            mode="lines",
            name="Critical threshold",
            line=dict(color="#DC2626", width=1.5, dash="dash"),
            hoverinfo="skip",
        ))

    if not fc_h.empty:
        fig.add_vrect(
            x0=fc_h["report_date"].min(),
            x1=fc_h["report_date"].max(),
            fillcolor="#009CA6",
            opacity=0.08,
            line_width=0,
            layer="below",
        )

    if not hist_h.empty:
        fig.add_trace(go.Scatter(
            x=hist_h["date"],
            y=hist_h["total_trolleys"],
            mode="lines",
            name="Actual",
            line=dict(color="#009CA6", width=2),
            hovertemplate="%{x|%b %d, %Y}<br>Actual: <b>%{y}</b><extra></extra>",
        ))

    if not fc_h.empty:
        fig.add_trace(go.Scatter(
            x=fc_h["report_date"],
            y=fc_h["pred_hosp"].round(0),
            mode="lines",
            name="14-day forecast",
            line=dict(color="#009CA6", width=2, dash="dash"),
            hovertemplate="%{x|%b %d}<br>Forecast: <b>%{y:.0f}</b><extra></extra>",
        ))

    fig.update_layout(
        title=None,
        height=300,
        legend=dict(orientation="h", y=1.08, x=0),
    )
    return apply_theme(fig)


def _hospital_alert_status(hospital: str, fc: pd.DataFrame, thr: pd.DataFrame):
    if thr is None:
        return "green"
    t_row = thr[thr["hospital"] == hospital]
    if t_row.empty:
        return "green"

    amber = t_row.iloc[0].get("threshold_amber")
    red   = t_row.iloc[0].get("threshold_red")

    fc_h = fc[fc["hospital"] == hospital]
    if fc_h.empty:
        return "green"

    avg_pred = fc_h["pred_hosp"].mean()

    if red is not None and not pd.isna(red) and avg_pred >= red:
        return "red"
    if amber is not None and not pd.isna(amber) and avg_pred >= amber:
        return "amber"
    return "green"


# ── Main render ───────────────────────────────────────────────────────────────

def render_forecast():
    page_header(
        "What's Coming",
        "14-Day Hospital Demand Forecast",
        "An XGBoost model trained on 3 years of daily HSE data. "
        "Select any hospital below to see its specific forecast and alert status.",
    )

    nat    = _load_national_history()
    fc_nat = _load_national_forecast()
    metrics = _load_metrics()
    fc_hosp, thr = _load_forecast_and_thresholds()
    hosp_hist = _load_hospital_history()

    # ── Hero 1: National forecast ──
    st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
    insight_callout(
        "The solid teal line shows the last 60 days of actual trolley counts. "
        "The dashed line shows the model's forecast for the next 14 days. "
        "The shaded region marks the forecast window."
    )
    section_heading("National forecast — next 14 days")

    if nat is not None and fc_nat is not None:
        fig = _chart_national_forecast(nat, fc_nat)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        finding(
            "The model captures day-of-week and seasonal patterns — "
            "Mondays and winter peaks are anticipated, not just reacted to"
        )
    else:
        data_missing_banner()
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Hero 2: Model transparency ──
    st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
    insight_callout(
        "How accurate is the forecast? The left card shows this model's error on 90 days of data it never saw. "
        "The right card shows what a naive approach (using last week's number) would have gotten. "
        "Smaller numbers are better."
    )
    section_heading("How accurate is the forecast?")

    if metrics is not None and not metrics.empty:
        _render_metrics(metrics)
    else:
        st.info("national_overall_metrics.csv not found — run the export script.")
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Hero 3: Hospital explorer ──
    st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
    insight_callout(
        "Select a hospital to see its last 30 days of actuals alongside the 14-day forecast. "
        "The dashed threshold lines are calibrated to that hospital's own history — "
        "they are not national averages."
    )
    section_heading("Check any hospital")

    if fc_hosp is not None and hosp_hist is not None:
        hospitals = sorted(fc_hosp["hospital"].dropna().unique().tolist())
        selected = st.selectbox(
            "Select a hospital",
            hospitals,
            label_visibility="collapsed",
        )

        alert = _hospital_alert_status(selected, fc_hosp, thr)
        if alert == "red":
            st.markdown(
                f'<div style="background:#FEE2E2;border:1px solid #DC2626;border-radius:6px;'
                f'padding:10px 14px;margin-bottom:10px;font-size:12px;color:#991B1B;">'
                f'<strong>HIGH PRESSURE</strong> · {selected} is forecast above its critical threshold '
                f'for this 14-day window.</div>',
                unsafe_allow_html=True,
            )
        elif alert == "amber":
            st.markdown(
                f'<div style="background:#FEF3C7;border:1px solid #F59E0B;border-radius:6px;'
                f'padding:10px 14px;margin-bottom:10px;font-size:12px;color:#92400E;">'
                f'<strong>ELEVATED PRESSURE</strong> · {selected} is forecast above its elevated threshold '
                f'for this 14-day window.</div>',
                unsafe_allow_html=True,
            )

        fig = _chart_hospital_explorer(selected, fc_hosp, thr, hosp_hist)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        finding(
            "Threshold lines reflect each hospital's own historical distribution — "
            "alerts are calibrated per site, not nationally"
        )
    else:
        data_missing_banner()
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Detail expander: full heatmap ──
    with st.expander("See all 36 hospitals — 14-day capacity alert heatmap"):
        st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
        insight_callout(
            "All 36 tracked hospitals, ordered by average forecast pressure (highest first). "
            "Green = within normal range. Amber = elevated. Red = critical. "
            "Each hospital's thresholds are based on its own history — "
            "a red at Letterkenny is just as serious as a red at UH Limerick."
        )
        section_heading("14-day capacity alert · All 36 hospitals")

        if fc_hosp is not None:
            _alert_heatmap_full(fc_hosp, thr)
            finding(
                "Capacity pressures are not uniform — the same national average "
                "can hide critical strain at individual hospitals"
            )
        else:
            data_missing_banner()
        st.markdown("</div>", unsafe_allow_html=True)
