# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas>=2.0",
#   "plotly>=5.18",
#   "kaleido==0.2.1",
# ]
# ///
"""
plot_monitor.py — Visualise Slurm job monitor CSV output.

Usage
-----
    uv run plot_monitor.py <csv>
    uv run plot_monitor.py <csv> --title "My job" --cpus 8 --png

Output
------
    <jobid>_monitor.html   always produced  (interactive Plotly)
    <jobid>_monitor.png    with --png flag  (static 2x, requires kaleido)

Notes on values
---------------
    rss_kb  — KB → converted to MB for display
    cpu_pct — converted to cores in the plot (cpu_pct / 100)
              first sample is always dropped (cold-start artefact)
              pass --cpus N to draw an allocated-cores reference line
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ── palette ──────────────────────────────────────────────────────────────────

C = {
    "bg":      "#0d1117",
    "panel":   "#161b22",
    "border":  "rgba(255,255,255,0.07)",
    "grid":    "rgba(255,255,255,0.05)",
    "text":    "#e6edf3",
    "subtext": "#6e7681",
    "memory":  "#58a6ff",   # blue
    "cpu":     "#f0883e",   # orange
    "peak":    "#f85149",   # red
}

# ordered panel definitions: (df_column, display_title, y_axis_label, colour_key)
PANEL_META = [
    ("rss_mb",    "Memory (RSS)",    "MB",    "memory"),
    ("cpu_cores", "CPU Utilisation", "cores", "cpu"),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def hex_to_rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ── data loading ─────────────────────────────────────────────────────────────

def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    missing = {"timestamp", "rss_kb"} - set(df.columns)
    if missing:
        sys.exit(f"ERROR: CSV missing required columns: {missing}")

    df = df.sort_values("timestamp").reset_index(drop=True)
    df["elapsed_s"] = df["timestamp"] - df["timestamp"].iloc[0]

    # memory unit conversion
    df["rss_mb"] = df["rss_kb"] / 1024

    # optional column — fill with NaN if absent (older CSV without cpu_pct)
    if "cpu_pct" not in df.columns:
        df["cpu_pct"] = float("nan")

    # drop first sample for delta metrics (prev=0 artefact)
    df.loc[0, "cpu_pct"] = float("nan")

    # cpu: percentage → cores (more human-readable)
    df["cpu_cores"] = df["cpu_pct"] / 100.0

    return df


def active_panels(df: pd.DataFrame) -> list[tuple]:
    """Return panels that have at least one non-zero, non-NaN value."""
    return [
        m for m in PANEL_META
        if not df[m[0]].isna().all() and df[m[0]].abs().sum() > 0
    ]


# ── figure ────────────────────────────────────────────────────────────────────

def add_peak_annotation(
    fig: go.Figure, df: pd.DataFrame,
    col: str, y_label: str, row: int, colour: str,
) -> None:
    valid = df[col].dropna()
    if valid.empty:
        return
    idx    = valid.idxmax()
    peak_x = df.loc[idx, "elapsed_s"]
    peak_y = valid.loc[idx]
    xref   = f"x{row}" if row > 1 else "x"
    yref   = f"y{row}" if row > 1 else "y"
    fig.add_annotation(
        x=peak_x, y=peak_y,
        xref=xref, yref=yref,
        text=f"<b>{peak_y:.1f}</b> {y_label}",
        showarrow=True,
        arrowhead=2, arrowsize=0.9, arrowwidth=1.2,
        arrowcolor=C["peak"],
        font=dict(size=10, color=C["peak"], family="monospace"),
        bgcolor=C["bg"],
        bordercolor=C["peak"],
        borderwidth=1,
        borderpad=4,
        ax=52, ay=-34,
    )


def build_figure(df: pd.DataFrame, job_id: str, custom_title: str | None,
                 cpus: int | None = None) -> go.Figure:
    panels   = active_panels(df)
    n        = len(panels)
    duration = int(df["elapsed_s"].iloc[-1])
    n_samp   = len(df)
    interval = round(duration / max(n_samp - 1, 1))

    title_text = custom_title or f"Job {job_id} — runtime profile"
    subtitle   = (
        f"duration {duration} s &nbsp;·&nbsp; "
        f"{n_samp} samples &nbsp;·&nbsp; "
        f"~{interval} s interval"
    )

    fig = make_subplots(
        rows=n, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[1.0] * n,
    )

    x = df["elapsed_s"]

    for i, (col, title, y_label, ck) in enumerate(panels, start=1):
        colour = C[ck]
        y      = df[col]

        # filled area trace
        fig.add_trace(
            go.Scatter(
                x=x, y=y,
                mode="lines",
                name=title,
                line=dict(color=colour, width=2, shape="spline", smoothing=0.5),
                fill="tozeroy",
                fillcolor=hex_to_rgba(colour, 0.12),
                hovertemplate=(
                    f"<b>{title}</b><br>"
                    "Elapsed: %{x} s<br>"
                    f"Value: %{{y:.2f}} {y_label}"
                    "<extra></extra>"
                ),
            ),
            row=i, col=1,
        )

        # panel label (top-left of each subplot)
        xref = f"x{i} domain" if i > 1 else "x domain"
        yref = f"y{i} domain" if i > 1 else "y domain"
        fig.add_annotation(
            x=0, y=1.0, xref=xref, yref=yref,
            text=f"<b>{title}</b>",
            showarrow=False,
            font=dict(size=12, color=C["text"]),
            xanchor="left", yanchor="bottom",
            xshift=4, yshift=5,
        )

        # peak annotation — memory only; CPU reads naturally from the axis
        if col == "rss_mb":
            add_peak_annotation(fig, df, col, y_label, i, colour)

        # y-axis: integer ticks for cores panel; reference line if --cpus given
        if col == "cpu_cores":
            peak_cores = int(df["cpu_cores"].dropna().max()) + 1
            tick_max   = max(peak_cores, cpus + 1) if cpus else peak_cores
            fig.update_yaxes(
                row=i, col=1,
                title_text=y_label,
                title_font=dict(size=10, color=C["subtext"]),
                title_standoff=6,
                range=[0, tick_max],
                tickmode="linear", tick0=0, dtick=1,
                gridcolor=C["grid"],
                tickfont=dict(size=10, color=C["subtext"]),
                showline=False, zeroline=False,
            )
            if cpus:
                fig.add_hline(
                    y=cpus, row=i, col=1,
                    line=dict(color=C["cpu"], width=1.2, dash="dot"),
                    annotation_text=f"allocated ({cpus})",
                    annotation_font=dict(size=10, color=C["subtext"]),
                    annotation_position="top right",
                )
        else:
            fig.update_yaxes(
                row=i, col=1,
                title_text=y_label,
                title_font=dict(size=10, color=C["subtext"]),
                title_standoff=6,
                rangemode="tozero",
                gridcolor=C["grid"],
                tickfont=dict(size=10, color=C["subtext"]),
                showline=False, zeroline=False,
            )
        if i < n:
            fig.update_xaxes(row=i, col=1, showticklabels=False)

    fig.update_xaxes(
        row=n, col=1,
        title_text="Elapsed time (s)",
        title_font=dict(size=11, color=C["subtext"]),
        gridcolor=C["grid"],
        tickfont=dict(size=10, color=C["subtext"]),
        showline=False, zeroline=False,
    )

    fig.update_layout(
        height=210 * n + 90,
        width=960,
        title=dict(
            text=(
                f"{title_text}"
                f"<br><sup><span style='color:{C['subtext']}'>{subtitle}</span></sup>"
            ),
            font=dict(size=16, color=C["text"]),
            x=0.02, xanchor="left",
            y=0.97, yanchor="top",
        ),
        paper_bgcolor=C["bg"],
        plot_bgcolor=C["panel"],
        font=dict(family="'SF Mono', 'Fira Mono', monospace", color=C["text"]),
        legend=dict(
            orientation="h",
            x=1, xanchor="right",
            y=1.01, yanchor="bottom",
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        ),
        margin=dict(l=70, r=30, t=95, b=50),
        hovermode="x unified",
    )

    # subtle outer border
    fig.add_shape(
        type="rect", xref="paper", yref="paper",
        x0=0, y0=0, x1=1, y1=1,
        line=dict(color=C["border"], width=1),
        layer="above",
    )

    return fig


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Plot a Slurm job monitor CSV as a multi-panel timeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("csv",     type=Path,        help="Path to <jobid>_monitor.csv")
    ap.add_argument("--title", default=None,     help="Custom plot title")
    ap.add_argument("--cpus",  type=int, default=None,
                               help="Allocated core count — draws a reference line on the CPU panel")
    ap.add_argument("--out",   default=None,     help="Output path (default: <csv stem>.html)")
    ap.add_argument("--png",   action="store_true", help="Also export PNG (requires kaleido)")
    args = ap.parse_args()

    if not args.csv.exists():
        sys.exit(f"ERROR: File not found: {args.csv}")

    job_id = args.csv.stem.split("_")[0]
    df     = load(args.csv)

    # summary to stdout
    print(f"\n  job      : {job_id}")
    print(f"  samples  : {len(df)}")
    print(f"  duration : {int(df['elapsed_s'].iloc[-1])} s")
    print(f"  peak RSS : {df['rss_mb'].max():.1f} MB")
    cpu_valid = df["cpu_cores"].dropna()
    if not cpu_valid.empty:
        peak_cores = cpu_valid.max()
        alloc_note = f" / {args.cpus} allocated" if args.cpus else ""
        print(f"  peak CPU : {peak_cores:.1f} cores{alloc_note}")
    print()

    fig = build_figure(df, job_id, args.title, cpus=args.cpus)

    html_out = Path(args.out) if args.out else args.csv.with_suffix(".html")
    fig.write_html(
        html_out,
        include_plotlyjs="cdn",
        config={"displayModeBar": True, "scrollZoom": True},
    )
    print(f"  ✓  HTML  →  {html_out}")

    if args.png:
        png_out = html_out.with_suffix(".png")
        fig.write_image(png_out, scale=2)
        print(f"  ✓  PNG   →  {png_out}\n")


if __name__ == "__main__":
    main()
