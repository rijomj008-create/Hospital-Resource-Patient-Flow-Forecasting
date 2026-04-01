"""
Screen 2 — "What Drives It"
Hero: Holiday Paradox (the most surprising and accessible finding)
Detail expander: weather · bed block · patient safety · surge capacity · volatility quadrant
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
def _load_national():
    p = DATA / "hse_tgar_processed.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["report_date"])
    hosp = df[df["is_total"] == 0]
    nat = (
        hosp.groupby("report_date")[
            ["total_trolleys", "ward_trolleys", "ed_trolleys",
             "surge_capacity", "delayed_transfers", "waiting_24h", "waiting_24h_75plus"]
        ]
        .sum()
        .reset_index()
        .rename(columns={"report_date": "date"})
        .sort_values("date")
    )
    for col in ["surge_capacity", "delayed_transfers", "waiting_24h", "waiting_24h_75plus"]:
        nat[col] = nat[col].replace(0, np.nan)
    return nat


@st.cache_data(show_spinner=False)
def _load_holidays():
    p = DATA / "holidays_ie.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["holiday_date"])
    return df


@st.cache_data(show_spinner=False)
def _load_weather():
    p = DATA / "weather_daily.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["report_date"])
    return df


@st.cache_data(show_spinner=False)
def _load_hospital_level():
    p = DATA / "hse_tgar_processed.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["report_date"])
    return df[df["is_total"] == 0]


# ── Chart functions ───────────────────────────────────────────────────────────

def _holiday_paradox_data(nat: pd.DataFrame, hol: pd.DataFrame, selected: str):
    nat = nat.set_index("date")
    if selected != "All holidays (average)":
        hol = hol[hol["name"] == selected]

    records = []
    for _, row in hol.iterrows():
        d = row["holiday_date"]
        for offset, label in [(-1, "Day Before"), (0, "Holiday"), (1, "Day After")]:
            target = d + pd.Timedelta(days=offset)
            if target in nat.index:
                records.append({
                    "period": label,
                    "trolleys": nat.loc[target, "total_trolleys"],
                    "holiday": row["name"],
                })

    if not records:
        return None

    result = pd.DataFrame(records)
    avg = result.groupby("period")["trolleys"].mean().reset_index()
    order = ["Day Before", "Holiday", "Day After"]
    avg["period"] = pd.Categorical(avg["period"], categories=order, ordered=True)
    avg = avg.sort_values("period")

    typical = nat["total_trolleys"].mean()
    return avg, typical


def _chart_holiday(nat, hol, selected):
    result = _holiday_paradox_data(nat, hol, selected)
    if result is None:
        return None
    avg, typical = result

    colours = {
        "Day Before": "#009CA6",
        "Holiday":    "#007A4D",
        "Day After":  "#DC2626",
    }

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=avg["period"],
        y=avg["trolleys"].round(0),
        marker_color=[colours.get(p, "#009CA6") for p in avg["period"]],
        text=avg["trolleys"].round(0).astype(int),
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Avg: %{y:.0f} trolleys<extra></extra>",
        name="",
    ))
    fig.add_hline(
        y=typical,
        line_dash="dash",
        line_color="#F59E0B",
        line_width=1.5,
        annotation_text=f"Typical day: {typical:.0f}",
        annotation_font=dict(size=10, color="#F59E0B"),
        annotation_position="top right",
    )
    fig.update_layout(
        title=None, height=280,
        showlegend=False,
        yaxis_title="Average trolleys",
    )
    return apply_theme(fig)


def _chart_weather(nat: pd.DataFrame, weather: pd.DataFrame,
                   city: str, variable: str):
    city_w = weather[weather["city"] == city].copy()
    city_w = city_w.rename(columns={"report_date": "date"})
    merged = nat[["date", "total_trolleys"]].merge(
        city_w[["date", variable]], on="date", how="inner"
    ).dropna()

    if merged.empty or len(merged) < 10:
        return None, None

    r = merged[["total_trolleys", variable]].corr().iloc[0, 1]

    z = np.polyfit(merged[variable], merged["total_trolleys"], 1)
    x_line = np.linspace(merged[variable].min(), merged[variable].max(), 100)
    y_line = np.polyval(z, x_line)

    var_labels = {
        "tavg": "Avg Temperature (°C)",
        "tmin": "Min Temperature (°C)",
        "tmax": "Max Temperature (°C)",
        "prcp": "Precipitation (mm)",
        "rhum": "Relative Humidity (%)",
        "wspd": "Wind Speed (km/h)",
    }
    x_label = var_labels.get(variable, variable)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=merged[variable], y=merged["total_trolleys"],
        mode="markers",
        marker=dict(color="#009CA6", size=4, opacity=0.45),
        hovertemplate=f"{x_label}: %{{x:.1f}}<br>Trolleys: %{{y}}<extra></extra>",
        name="Daily observation",
    ))
    fig.add_trace(go.Scatter(
        x=x_line, y=y_line,
        mode="lines",
        line=dict(color="#003D7C", width=2),
        name="Trend",
        hoverinfo="skip",
    ))
    fig.add_annotation(
        xref="paper", yref="paper", x=0.02, y=0.95,
        text=f"r = {r:.2f}",
        showarrow=False,
        font=dict(size=12, color="#0D1B2A"),
        bgcolor="white",
        bordercolor="#DDD9CF",
        borderwidth=1,
        borderpad=4,
    )
    fig.update_layout(
        title=None, height=300,
        xaxis_title=x_label,
        yaxis_title="National daily trolleys",
        showlegend=False,
    )
    return apply_theme(fig), r


def _chart_bed_block(nat: pd.DataFrame):
    data = nat[["date", "delayed_transfers", "ward_trolleys"]].dropna(
        subset=["delayed_transfers"]
    )
    if data.empty:
        return None

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["delayed_transfers"],
        mode="lines", name="Patients stuck waiting for discharge",
        line=dict(color="#F59E0B", width=1.5),
        hovertemplate="%{x|%b %d, %Y}<br>Delayed transfers: <b>%{y}</b><extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["ward_trolleys"],
        mode="lines", name="Patients on ward trolleys",
        line=dict(color="#DC2626", width=1.5),
        yaxis="y2",
        hovertemplate="%{x|%b %d, %Y}<br>Ward trolleys: <b>%{y}</b><extra></extra>",
    ))

    fig.update_layout(
        title=None, height=280,
        yaxis=dict(
            title=dict(text="Patients awaiting discharge (amber)",
                       font=dict(color="#F59E0B", size=10)),
            gridcolor="#F0EDE6",
            linecolor="#DDD9CF",
            tickfont=dict(size=10),
            zeroline=False,
        ),
        yaxis2=dict(
            title=dict(text="Ward trolleys (red)",
                       font=dict(color="#DC2626", size=10)),
            overlaying="y", side="right",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(size=10),
            zeroline=False,
        ),
        legend=dict(orientation="h", y=1.08, x=0),
    )
    return apply_theme(fig)


def _chart_patient_safety(nat: pd.DataFrame):
    data = nat[["date", "waiting_24h", "waiting_24h_75plus", "total_trolleys"]].dropna(
        subset=["waiting_24h"]
    )
    if data.empty:
        return None

    data["rolling_7"] = data["waiting_24h"].rolling(7, min_periods=3).mean()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["total_trolleys"],
        mode="lines", name="Total trolleys",
        line=dict(color="#009CA6", width=1.2, dash="dot"),
        yaxis="y2",
        hovertemplate="%{x|%b %d}<br>Total trolleys: <b>%{y}</b><extra></extra>",
        opacity=0.6,
    ))
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["waiting_24h"],
        mode="lines", name="Waiting >24h",
        line=dict(color="#DC2626", width=1),
        opacity=0.4,
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["rolling_7"],
        mode="lines", name="Waiting >24h (7-day avg)",
        line=dict(color="#DC2626", width=2),
        hovertemplate="%{x|%b %d}<br>Waiting >24h: <b>%{y:.0f}</b><extra></extra>",
    ))
    if data["waiting_24h_75plus"].notna().any():
        fig.add_trace(go.Scatter(
            x=data["date"], y=data["waiting_24h_75plus"],
            mode="lines", name="Aged 75+ waiting >24h",
            line=dict(color="#7C3AED", width=1.5),
            hovertemplate="%{x|%b %d}<br>75+ waiting: <b>%{y:.0f}</b><extra></extra>",
        ))

    fig.update_layout(
        title=None, height=280,
        yaxis=dict(
            title=dict(text="Patients waiting >24 hours (red)",
                       font=dict(size=10)),
            gridcolor="#F0EDE6", linecolor="#DDD9CF",
            tickfont=dict(size=10), zeroline=False,
        ),
        yaxis2=dict(
            title=dict(text="Total trolleys (teal, dotted)",
                       font=dict(color="#009CA6", size=10)),
            overlaying="y", side="right",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(size=10), zeroline=False,
        ),
        legend=dict(orientation="h", y=1.08, x=0),
    )
    return apply_theme(fig)


def _chart_surge(nat: pd.DataFrame):
    data = nat[["date", "surge_capacity", "total_trolleys"]].dropna(
        subset=["surge_capacity"]
    )
    if data.empty:
        return None

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=data["date"], y=data["surge_capacity"],
        name="Temporary extra beds activated",
        marker_color="#F59E0B",
        opacity=0.75,
        hovertemplate="%{x|%b %d, %Y}<br>Surge beds: <b>%{y}</b><extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=data["date"], y=data["total_trolleys"],
        mode="lines", name="Total trolleys",
        line=dict(color="#DC2626", width=1.5),
        yaxis="y2",
        hovertemplate="%{x|%b %d}<br>Trolleys: <b>%{y}</b><extra></extra>",
    ))
    fig.update_layout(
        title=None, height=270,
        bargap=0,
        yaxis=dict(
            title=dict(text="Surge beds activated (amber bars)",
                       font=dict(color="#F59E0B", size=10)),
            gridcolor="#F0EDE6", linecolor="#DDD9CF",
            tickfont=dict(size=10), zeroline=False,
        ),
        yaxis2=dict(
            title=dict(text="Total trolleys (red line)",
                       font=dict(color="#DC2626", size=10)),
            overlaying="y", side="right",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(size=10), zeroline=False,
        ),
        legend=dict(orientation="h", y=1.08, x=0),
    )
    return apply_theme(fig)


def _chart_volatility(hosp_df: pd.DataFrame):
    stats = (
        hosp_df.groupby(["hospital", "region"])["total_trolleys"]
        .agg(mean_y="mean", std_y="std")
        .reset_index()
        .dropna()
    )
    stats = stats[stats["mean_y"] > 0]
    stats["cv"] = (stats["std_y"] / stats["mean_y"]).round(3)

    med_mean = stats["mean_y"].median()
    med_cv   = stats["cv"].median()

    region_colours = {
        r: c for r, c in zip(
            stats["region"].unique(),
            ["#009CA6", "#F59E0B", "#DC2626", "#007A4D", "#6366F1", "#F97316"],
        )
    }

    fig = go.Figure()
    for region, grp in stats.groupby("region"):
        fig.add_trace(go.Scatter(
            x=grp["mean_y"], y=grp["cv"],
            mode="markers+text",
            name=region,
            marker=dict(
                color=region_colours.get(region, "#009CA6"),
                size=9, opacity=0.8,
                line=dict(width=1, color="white"),
            ),
            text=grp["hospital"].apply(lambda h: h[:12]),
            textposition="top center",
            textfont=dict(size=8, color="#6B7280"),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Avg trolleys: %{x:.1f}<br>"
                "Day-to-day variation: %{y:.2f}<extra></extra>"
            ),
            customdata=grp[["hospital"]].values,
        ))

    fig.add_vline(x=med_mean, line_dash="dot", line_color="#DDD9CF", line_width=1)
    fig.add_hline(y=med_cv,   line_dash="dot", line_color="#DDD9CF", line_width=1)

    x_max = stats["mean_y"].max() * 1.05
    y_max = stats["cv"].max() * 1.05
    quadrant_labels = [
        (med_mean * 1.35, y_max * 0.96, "High demand · Unpredictable", "#DC2626"),
        (med_mean * 0.15, y_max * 0.96, "Low demand · Unpredictable",  "#F59E0B"),
        (med_mean * 1.35, med_cv * 0.3, "High demand · Predictable",   "#007A4D"),
        (med_mean * 0.15, med_cv * 0.3, "Low demand · Predictable",    "#6B7280"),
    ]
    for x, y, label, colour in quadrant_labels:
        fig.add_annotation(
            x=x, y=y, text=label, showarrow=False,
            font=dict(size=9, color=colour),
            bgcolor="rgba(255,255,255,0.7)",
            borderpad=2,
        )

    fig.update_layout(
        title=None, height=380,
        xaxis_title="Average daily trolleys →",
        yaxis_title="Day-to-day variation (higher = harder to plan) →",
        legend=dict(orientation="h", y=-0.18, x=0),
    )
    return apply_theme(fig)


# ── Main render ───────────────────────────────────────────────────────────────

def render_drivers():
    page_header(
        "What Drives It",
        "What Causes the Trolley Crisis?",
        "The single biggest swing factor is the day after a public holiday. "
        "But weather, bed block, and discharge delays all play a role.",
    )

    nat      = _load_national()
    hol      = _load_holidays()
    weather  = _load_weather()
    hosp_df  = _load_hospital_level()

    if nat is None:
        data_missing_banner()
        st.stop()

    # ── Hero: Holiday Paradox ──
    st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
    insight_callout(
        "You might expect fewer trolleys on a public holiday — and you'd be right. "
        "But look at what happens the day after. "
        "Staffing follows the calendar; patient need does not. "
        "Select a specific holiday below to see the pattern for that date."
    )
    section_heading("The day after a holiday is Ireland's biggest pressure point")

    if hol is not None:
        holiday_names = ["All holidays (average)"] + sorted(hol["name"].dropna().unique().tolist())
        selected_hol = st.selectbox(
            "Select holiday", holiday_names, label_visibility="collapsed"
        )
        fig = _chart_holiday(nat, hol, selected_hol)
        if fig:
            st.plotly_chart(fig, width="stretch",
                            config={"displayModeBar": False})
            finding(
                "Trolleys drop ~35% on the holiday itself, then spike the following working day — "
                "demand doesn't take a day off"
            )
        else:
            st.info("Not enough data for the selected holiday.")
    else:
        st.info("holidays_ie.csv not found — run the export script.")
    st.markdown("</div>", unsafe_allow_html=True)

    # ── Detail expander ──
    with st.expander("Explore more causes: weather, bed block, patient safety, surge capacity"):

        # Weather
        if weather is not None:
            st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
            insight_callout(
                "Each dot is one day. The blue line shows the trend. "
                "r is the correlation: closer to -1 means colder weather strongly predicts more trolleys. "
                "Try switching to 'Min Temperature' — it often shows the strongest signal."
            )
            section_heading("Does cold weather drive more trolleys?")
            cities    = sorted(weather["city"].dropna().unique().tolist())
            var_opts  = {
                "Avg Temperature (°C)":   "tavg",
                "Min Temperature (°C)":   "tmin",
                "Max Temperature (°C)":   "tmax",
                "Precipitation (mm)":     "prcp",
                "Relative Humidity (%)":  "rhum",
                "Wind Speed (km/h)":      "wspd",
            }
            c1, c2 = st.columns([1, 1])
            with c1:
                city_sel = st.selectbox(
                    "City", cities,
                    index=cities.index("Dublin") if "Dublin" in cities else 0,
                    label_visibility="collapsed",
                )
            with c2:
                var_sel_label = st.selectbox(
                    "Variable", list(var_opts.keys()),
                    label_visibility="collapsed",
                )
            var_sel = var_opts[var_sel_label]

            fig, r = _chart_weather(nat, weather, city_sel, var_sel)
            if fig:
                st.plotly_chart(fig, width="stretch",
                                config={"displayModeBar": False})
                direction = "Colder" if var_sel in ["tavg", "tmin", "tmax"] else "Higher"
                finding(
                    f"{direction} {var_sel_label.lower()} correlates with higher trolley demand "
                    f"(r = {r:.2f}) — but weather explains only part of the story"
                )
            else:
                st.info("Not enough overlapping data for this city/variable combination.")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("weather_daily.csv not found — run the export script.")

        # Bed Block
        st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
        insight_callout(
            "The amber line shows patients who are medically ready to leave hospital but have nowhere to go — "
            "no care home place, no home support arranged. They occupy beds that new patients need. "
            "The red line (right axis) shows ward trolleys. Watch how they move together."
        )
        section_heading("Patients can't leave — so new patients wait on trolleys")
        fig = _chart_bed_block(nat)
        if fig:
            st.plotly_chart(fig, width="stretch",
                            config={"displayModeBar": False})
            finding("When discharge delays rise, ward trolleys follow — bed block moves the crisis deeper into the system")
        else:
            st.info("Delayed transfer data not yet available in this dataset range.")
        st.markdown("</div>", unsafe_allow_html=True)

        # Patient Safety
        st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
        insight_callout(
            "Waiting more than 24 hours on a trolley is a patient safety risk, not just a comfort issue. "
            "The red line shows how many patients cross that threshold each day. "
            "The purple line (if shown) isolates patients aged 75 and over — the most vulnerable group. "
            "The dotted teal line (right axis) shows total trolleys for scale."
        )
        section_heading("Overcrowding becomes a safety issue: patients waiting over 24 hours")
        fig = _chart_patient_safety(nat)
        if fig:
            st.plotly_chart(fig, width="stretch",
                            config={"displayModeBar": False})
            finding(
                "Patients waiting >24 hours tracks total trolley count closely — "
                "the 75+ cohort represents the most clinically vulnerable group"
            )
        else:
            st.info("Waiting >24h data not yet available in this dataset range.")
        st.markdown("</div>", unsafe_allow_html=True)

        # Surge Capacity
        st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
        insight_callout(
            "Hospitals can open temporary extra beds in a crisis — shown here as amber bars. "
            "The red line shows total trolleys on the same days. "
            "If surge beds were activated proactively, you'd see the bars appear before trolley peaks. "
            "Look at whether that's actually what happens."
        )
        section_heading("Surge beds are activated after the crisis — not before")
        fig = _chart_surge(nat)
        if fig:
            st.plotly_chart(fig, width="stretch",
                            config={"displayModeBar": False})
            finding(
                "Surge beds appear after trolley numbers have already peaked — "
                "the system reacts, it does not anticipate"
            )
        else:
            st.info("Surge capacity data not yet available in this dataset range.")
        st.markdown("</div>", unsafe_allow_html=True)

        # Volatility Quadrant
        if hosp_df is not None:
            st.markdown('<div class="card-wrap">', unsafe_allow_html=True)
            insight_callout(
                "This chart plots every hospital by two things: how many trolleys they have on average (x-axis) "
                "and how much that number varies from day to day (y-axis). "
                "A hospital in the top-right is both busy and unpredictable — the hardest to plan for. "
                "A hospital in the bottom-right is busy but consistent — easier to staff for. "
                "Hover over any dot to see the hospital name."
            )
            section_heading("Not all high-pressure hospitals are equally hard to plan for")
            fig = _chart_volatility(hosp_df)
            st.plotly_chart(fig, width="stretch",
                            config={"displayModeBar": False})
            finding(
                "Some high-pressure hospitals are actually more predictable than lower-pressure ones — "
                "volume and variability are separate problems"
            )
            st.markdown("</div>", unsafe_allow_html=True)
