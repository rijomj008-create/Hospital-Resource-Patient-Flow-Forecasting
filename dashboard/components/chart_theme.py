"""
Shared Plotly theme. Apply to every figure with apply_theme(fig).
"""

CHART_THEME = dict(
    paper_bgcolor="#FFFFFF",
    plot_bgcolor="#FFFFFF",
    title=dict(text=""),
    font=dict(family="DM Sans, sans-serif", size=11, color="#6B7280"),
    margin=dict(l=40, r=20, t=28, b=40),
    xaxis=dict(
        gridcolor="#F0EDE6",
        linecolor="#DDD9CF",
        tickfont=dict(size=10),
        zeroline=False,
    ),
    yaxis=dict(
        gridcolor="#F0EDE6",
        linecolor="#DDD9CF",
        tickfont=dict(size=10),
        zeroline=False,
    ),
    colorway=["#009CA6", "#F59E0B", "#DC2626", "#007A4D", "#6366F1", "#F97316"],
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=10),
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
    hoverlabel=dict(
        bgcolor="#0D1B2A",
        font=dict(color="#fff", size=11, family="DM Sans"),
    ),
)


def apply_theme(fig):
    """Apply the dashboard theme to any Plotly figure."""
    fig.update_layout(**CHART_THEME)
    return fig
