"""
Global CSS injection. Called once at app startup.
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


def _bg_css() -> str:
    """Return background CSS — uses photo if available, fallback to plain HSE blue."""
    assets = Path(__file__).parent.parent / "assets"
    # Prefer .jpg (smaller) over .png
    bg_path = next(
        (assets / f for f in ["hospital_bg.jpg", "hospital_bg.png", "hospital_bg.webp"]
         if (assets / f).exists()),
        None,
    )
    if bg_path is not None:
        ext = bg_path.suffix.lstrip(".")
        mime = "jpeg" if ext == "jpg" else ext
        with open(bg_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"""
        .stApp {{
            background-image: url("data:image/{mime};base64,{b64}") !important;
            background-size: cover !important;
            background-position: center center !important;
            background-attachment: fixed !important;
        }}
        /* Dark overlay — lets photo show through */
        .stApp::before {{
            content: '';
            position: fixed;
            inset: 0;
            background: rgba(5, 15, 35, 0.30);
            z-index: 0;
            pointer-events: none;
        }}
        """
    return """
    .stApp { background: #003D7C !important; }
    """


def inject_css():
    bg = _bg_css()
    logo_b64 = _b64(_ASSETS / "hse_logo.png")

    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&family=DM+Serif+Display&display=swap');

        {bg}

        /* Main content — semi-transparent so photo shows at edges */
        [data-testid="stMain"] {{
            background: rgba(240, 237, 230, 0.60) !important;
            position: relative;
            z-index: 1;
        }}
        [data-testid="stMainBlockContainer"] {{
            padding-top: 1.8rem;
            padding-bottom: 3rem;
        }}

        /* Sidebar — solid HSE blue (all screen sizes) */
        [data-testid="stSidebar"] {{
            background: #002D5C !important;
            border-right: 1px solid rgba(255,255,255,0.08) !important;
        }}
        [data-testid="stSidebar"] * {{
            color: rgba(255,255,255,0.80) !important;
            font-family: 'DM Sans', sans-serif !important;
        }}
        /* Active radio item */
        [data-testid="stSidebar"] [data-baseweb="radio"] label[data-checked="true"] {{
            border-left: 3px solid #009CA6 !important;
            background: rgba(0,156,166,0.15) !important;
            padding-left: 8px;
            border-radius: 3px;
        }}
        /* Desktop: keep sidebar pinned open, hide the toggle button */
        @media (min-width: 769px) {{
            [data-testid="stSidebar"] {{
                min-width: 244px !important;
                width: 244px !important;
                transform: none !important;
                display: block !important;
                visibility: visible !important;
            }}
            [data-testid="stSidebarCollapseButton"],
            [data-testid="collapsedControl"] {{
                display: none !important;
            }}
        }}

        /* Global font */
        html, body, [class*="css"] {{
            font-family: 'DM Sans', sans-serif;
        }}

        /* ── Page header typography ── */
        .screen-title {{
            font-family: 'DM Serif Display', serif;
            font-size: 1.75rem;
            color: #0D1B2A;
            line-height: 1.2;
            margin-bottom: 4px;
        }}
        .page-tag {{
            display: inline-block;
            font-size: 10px;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            color: #007A8A;
            font-weight: 600;
            background: rgba(0,156,166,0.12);
            border: 1px solid rgba(0,156,166,0.3);
            padding: 3px 10px;
            border-radius: 20px;
            margin-bottom: 8px;
        }}
        .page-subtitle {{
            font-size: 13px;
            color: #4B5563;
            margin-top: 4px;
            max-width: 580px;
            line-height: 1.55;
        }}

        /* ── Cards — white, floating on photo ── */
        .card-wrap {{
            background: rgba(255,255,255,0.97);
            border-radius: 12px;
            border: 1px solid rgba(221,217,207,0.6);
            padding: 18px 20px;
            margin-bottom: 16px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.18), 0 1px 4px rgba(0,0,0,0.10);
        }}
        .metric-card {{
            background: rgba(255,255,255,0.97);
            border-radius: 12px;
            border: 1px solid rgba(221,217,207,0.6);
            padding: 16px 18px;
            height: 100%;
            box-shadow: 0 4px 20px rgba(0,0,0,0.16), 0 1px 3px rgba(0,0,0,0.08);
        }}

        /* ── Card interior typography — dark on white ── */
        .stat-number {{
            font-family: 'DM Serif Display', serif;
            font-size: 2.1rem;
            color: #0D1B2A;
            line-height: 1;
            margin: 0;
        }}
        .section-heading {{
            font-family: 'DM Sans', sans-serif;
            font-weight: 600;
            font-size: 0.92rem;
            color: #0D1B2A;
            margin-bottom: 4px;
        }}
        .finding-label {{
            font-size: 11px;
            color: #007A8A;
            font-style: italic;
            margin-top: 4px;
            margin-bottom: 4px;
            font-family: 'DM Sans', sans-serif;
            padding: 5px 10px;
            background: #F0FAFA;
            border-left: 3px solid #009CA6;
            border-radius: 0 4px 4px 0;
        }}
        .metric-card .stat-label {{
            font-size: 11px;
            color: #6B7280;
            margin-top: 4px;
            line-height: 1.4;
        }}
        .stat-badge {{
            display: inline-block;
            font-size: 9px;
            font-weight: 600;
            letter-spacing: 0.5px;
            padding: 2px 7px;
            border-radius: 4px;
            margin-top: 6px;
            text-transform: uppercase;
        }}

        /* ── Insight callout — appears BEFORE a chart to frame what to look for ── */
        .insight-callout {{
            font-size: 12px;
            color: #1F2937;
            margin-bottom: 10px;
            margin-top: 2px;
            padding: 8px 12px;
            background: #EEF2FF;
            border-left: 3px solid #003D7C;
            border-radius: 0 4px 4px 0;
            line-height: 1.55;
        }}

        /* ── Data-missing banner ── */
        .data-missing {{
            background: #FEF3C7;
            border: 1px solid #F59E0B;
            border-radius: 8px;
            padding: 14px 18px;
            font-size: 13px;
            color: #92400E;
        }}

        /* Plotly containers */
        .stPlotlyChart > div {{
            background: transparent !important;
        }}

        /* Remove default Streamlit chrome */
        #MainMenu, footer, header {{ visibility: hidden; }}

        /* Divider */
        hr {{
            border: none;
            border-top: 1px solid #DDD9CF;
            margin: 16px 0;
        }}

        /* ── Mobile (≤ 768px) ─────────────────────────────────────────────── */
        @media (max-width: 768px) {{

            /* Show the hamburger menu so users can open the sidebar */
            [data-testid="stSidebarCollapseButton"],
            [data-testid="collapsedControl"] {{
                display: flex !important;
            }}

            /* Stack columns vertically instead of side by side */
            [data-testid="stHorizontalBlock"],
            [data-testid="stColumns"] {{
                flex-wrap: wrap !important;
            }}
            [data-testid="column"],
            [data-testid="stColumn"] {{
                min-width: 100% !important;
                width: 100% !important;
                flex: 1 1 100% !important;
            }}

            /* Smaller page title */
            .screen-title {{
                font-size: 1.3rem !important;
            }}
            .page-subtitle {{
                font-size: 12px !important;
                max-width: 100% !important;
            }}

            /* Tighter main content padding */
            [data-testid="stMainBlockContainer"] {{
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
                padding-top: 1rem !important;
            }}

            /* Compact cards */
            .card-wrap {{
                padding: 14px 12px !important;
                margin-bottom: 12px !important;
                border-radius: 8px !important;
            }}
            .metric-card {{
                padding: 12px 12px !important;
                margin-bottom: 10px !important;
            }}

            /* Scale down stat numbers so they fit on one line */
            .stat-number {{
                font-size: 1.75rem !important;
            }}

            /* Slightly smaller callout and finding text */
            .insight-callout {{
                font-size: 11px !important;
            }}
            .finding-label {{
                font-size: 10px !important;
            }}

            /* Section headings don't need to shrink much, but tighten spacing */
            .section-heading {{
                font-size: 0.85rem !important;
                margin-bottom: 6px !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
