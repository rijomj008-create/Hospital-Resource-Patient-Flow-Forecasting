"""
Reusable UI components: stat cards, page headers, finding labels, sidebar.
"""
import base64
from pathlib import Path
import streamlit as st

_ASSETS = Path(__file__).parent.parent / "assets"


def _b64(path: Path) -> str | None:
    if path.exists():
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None


# ── Sidebar ──────────────────────────────────────────────────────────────────

def sidebar_branding():
    logo_b64 = _b64(_ASSETS / "hse_logo.png")

    if logo_b64:
        logo_html = (
            f'<img src="data:image/png;base64,{logo_b64}" '
            f'style="height:36px;width:auto;flex-shrink:0;" alt="HSE">'
        )
    else:
        # Fallback: styled text box matching HSE wordmark style
        logo_html = (
            '<div style="background:#fff;border-radius:5px;padding:4px 8px;'
            'font-weight:700;color:#003D7C;font-size:13px;'
            'letter-spacing:-0.3px;flex-shrink:0;">HSE</div>'
        )

    st.sidebar.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:10px;padding:4px 0 18px;
             border-bottom:1px solid rgba(255,255,255,0.12);margin-bottom:16px;">
            {logo_html}
            <div>
                <div style="color:rgba(255,255,255,0.9);font-size:12px;font-weight:500;
                     line-height:1.2;">Health Service Executive</div>
                <div style="color:rgba(255,255,255,0.4);font-size:10px;margin-top:1px;">
                     Ireland · Seirbhís Sláinte</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar_footer(last_updated: str = "Mar 2026"):
    st.sidebar.markdown(
        f"""
        <div style="font-size:10px;color:rgba(255,255,255,0.3);line-height:1.7;
             border-top:1px solid rgba(255,255,255,0.1);padding-top:14px;margin-top:20px;">
            <strong style="color:rgba(255,255,255,0.5);">Data source</strong><br>
            HSE TGAR Report (public)<br>
            Last updated: {last_updated}<br><br>
            ⚠ Exploratory analysis<br>
            Not for clinical use
        </div>
        <div style="font-size:10px;line-height:1.8;
             border-top:1px solid rgba(255,255,255,0.1);padding-top:14px;margin-top:16px;">
            <strong style="color:rgba(255,255,255,0.5);letter-spacing:0.5px;">Built by</strong><br>
            <span style="color:rgba(255,255,255,0.75);font-weight:500;">Rijo Mathew John</span><br>
            <a href="mailto:rijomj008@gmail.com"
               style="color:rgba(0,200,210,0.8);text-decoration:none;">
                rijomj008@gmail.com
            </a><br>
            <a href="https://www.linkedin.com/in/rijo-mathew-john"
               target="_blank"
               style="color:rgba(0,200,210,0.8);text-decoration:none;">
                linkedin.com/in/rijo-mathew-john
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Page structure ────────────────────────────────────────────────────────────

def page_header(tag: str, title: str, subtitle: str):
    st.markdown(
        f"""
        <div style="margin-bottom:24px;">
            <span class="page-tag">{tag}</span>
            <p class="screen-title">{title}</p>
            <p class="page-subtitle">{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_heading(text: str):
    st.markdown(f'<p class="section-heading">{text}</p>', unsafe_allow_html=True)


def finding(text: str):
    """Key insight label rendered below every chart."""
    st.markdown(f'<p class="finding-label">↑ {text}</p>', unsafe_allow_html=True)


def insight_callout(text: str):
    """Context or question rendered BEFORE a chart to frame what the reader should look for."""
    st.markdown(f'<p class="insight-callout">{text}</p>', unsafe_allow_html=True)


def card_open():
    st.markdown('<div class="card-wrap">', unsafe_allow_html=True)


def card_close():
    st.markdown("</div>", unsafe_allow_html=True)


# ── Stat cards ────────────────────────────────────────────────────────────────

def stat_card(value: str, label: str, badge: str,
              stripe: str, badge_bg: str, badge_fg: str):
    return f"""
    <div class="metric-card" style="border-top:3px solid {stripe};">
        <p class="stat-number">{value}</p>
        <p class="stat-label">{label}</p>
        <span class="stat-badge" style="background:{badge_bg};color:{badge_fg};">
            {badge}
        </span>
    </div>
    """


def stat_row_home():
    """Three headline stat cards for the Home screen."""
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            stat_card("488", "Peak trolley count · Single day",
                      "Jan 13 2026 · Record high",
                      "#DC2626", "#FEE2E2", "#991B1B"),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            stat_card("273", "Daily average across Ireland",
                      "3-year rolling mean",
                      "#F59E0B", "#FEF3C7", "#92400E"),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            stat_card("36", "Hospitals tracked · 4 HSE regions",
                      "National coverage · 2023–2026",
                      "#009CA6", "#E6F7F7", "#0B7A76"),
            unsafe_allow_html=True,
        )


# ── Data-missing banner ───────────────────────────────────────────────────────

def data_missing_banner():
    st.markdown(
        """
        <div class="data-missing">
            <strong>Historical data not found.</strong>
            Run the export script first:<br>
            <code style="font-size:12px;">
            cd dashboard &nbsp;&nbsp;→&nbsp;&nbsp;
            python data_prep/export_from_sql.py
            </code>
        </div>
        """,
        unsafe_allow_html=True,
    )
