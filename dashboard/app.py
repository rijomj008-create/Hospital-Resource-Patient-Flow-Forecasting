"""
Ireland Healthcare Demand Forecasting Dashboard
Streamlit · Plotly · HSE TGAR Data · 2023–2026
"""
import streamlit as st

st.set_page_config(
    page_title="Ireland Healthcare Demand Forecasting",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="auto",
)

# Must be first Streamlit calls after set_page_config
from components.css import inject_css
from components.ui import sidebar_branding, sidebar_footer
from screens.home import render_home
from screens.problem import render_problem
from screens.drivers import render_drivers
from screens.forecast import render_forecast

inject_css()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    sidebar_branding()

    st.markdown(
        '<p style="font-size:10px;letter-spacing:1px;text-transform:uppercase;'
        'color:rgba(255,255,255,0.35);margin-bottom:6px;">Navigation</p>',
        unsafe_allow_html=True,
    )
    screen = st.radio(
        "Navigation",
        options=["Home", "The Problem", "What Drives It", "What's Coming"],
        label_visibility="hidden",
    )

    st.markdown("<hr style='border-color:rgba(255,255,255,0.1);margin:16px 0;'>",
                unsafe_allow_html=True)

    sidebar_footer(last_updated="Mar 2026")

# ── Route ─────────────────────────────────────────────────────────────────────
if screen == "Home":
    render_home()

elif screen == "The Problem":
    render_problem()

elif screen == "What Drives It":
    render_drivers()

elif screen == "What's Coming":
    render_forecast()
