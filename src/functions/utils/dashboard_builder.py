"""
Build the occupancy dashboard as a self-contained Plotly HTML page.

All charts are generated in Python — no hand-written HTML/JS.
The dashboard answers: "When is the best time to go to Badi Oerlikon?"
"""

from __future__ import annotations

import csv
import io
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger("dashboard_builder")

# Day-of-week names (Monday=0)
_DOW_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_dashboard_html(lookback_days: int = 30) -> str:
    """
    Fetch historical data and return a complete HTML page with Plotly charts.

    Charts:
        1. Recent 7-day occupancy timeline
        2. Average occupancy by hour of day ("best hour to go")
        3. Heatmap: day-of-week × hour ("best day + hour combo")
        4. Prediction for today & tomorrow (hourly forecast)
    """
    readings = _fetch_readings(lookback_days)

    if not readings:
        return _empty_page("No occupancy data found yet. "
                           "Check back once the collectors have been running.")

    # Parse into (datetime, int) tuples
    parsed = _parse_readings(readings)

    # Build individual figures
    fig_timeline = _chart_recent_timeline(parsed, days=7)
    fig_best_hour = _chart_best_hour(parsed)
    fig_heatmap = _chart_heatmap(parsed)
    fig_prediction = _chart_prediction(parsed)

    # Assemble full page
    return _assemble_page(fig_timeline, fig_best_hour, fig_heatmap,
                          fig_prediction, len(parsed), lookback_days)


# ---------------------------------------------------------------------------
# Data fetching (reuses same blob-reading logic as get_occupancy)
# ---------------------------------------------------------------------------

def _fetch_readings(lookback_days: int) -> list[dict]:
    """Read raw CSV blobs for the last N days."""
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        logger.error("azure-storage-blob not installed")
        return []

    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        aws = os.getenv("AzureWebJobsStorage", "")
        if aws and aws != "UseDevelopmentStorage=true":
            conn_str = aws
    if not conn_str:
        logger.warning("No storage connection string — returning empty data")
        return []

    container_name = os.getenv("BLOB_CONTAINER_NAME", "occupancy-data")
    blob_service = BlobServiceClient.from_connection_string(conn_str)
    container_client = blob_service.get_container_client(container_name)

    all_readings: list[dict] = []
    today = datetime.now(timezone.utc).date()

    for offset in range(lookback_days + 1):
        day = today - timedelta(days=offset)
        prefix = day.strftime("%Y-%m-%d/")
        try:
            for blob in container_client.list_blobs(name_starts_with=prefix):
                try:
                    blob_client = container_client.get_blob_client(blob.name)
                    content = (blob_client
                               .download_blob()
                               .readall()
                               .decode("utf-8"))
                    reader = csv.DictReader(io.StringIO(content))
                    for row in reader:
                        ts = row.get("timestamp", "")
                        occ = row.get("occupancy", "")
                        if ts and occ:
                            all_readings.append({
                                "timestamp": ts,
                                "occupancy": int(float(occ)),
                            })
                except Exception as e:
                    logger.debug(f"Skip blob {blob.name}: {e}")
        except Exception as e:
            logger.debug(f"Skip prefix {prefix}: {e}")

    all_readings.sort(key=lambda r: r["timestamp"])
    return all_readings


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_readings(readings: list[dict]) -> list[tuple[datetime, int]]:
    """Convert raw dicts to (datetime, occupancy) tuples."""
    result = []
    for r in readings:
        ts_str = r["timestamp"]
        try:
            if "." in ts_str:
                dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S.%f")
            else:
                dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
            result.append((dt, r["occupancy"]))
        except ValueError:
            continue
    return result


# ---------------------------------------------------------------------------
# Chart 1: Recent 7-day timeline
# ---------------------------------------------------------------------------

def _chart_recent_timeline(
    parsed: list[tuple[datetime, int]], days: int = 7,
) -> go.Figure:
    """Line chart of raw occupancy over the last N days."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    recent = [(dt, occ) for dt, occ in parsed if dt >= cutoff]

    if not recent:
        recent = parsed[-2000:]  # fallback: last 2000 readings

    # Downsample to 5-min buckets for smoother rendering
    buckets: dict[str, list[int]] = defaultdict(list)
    for dt, occ in recent:
        bucket = dt.replace(second=0, microsecond=0)
        bucket = bucket.replace(minute=(bucket.minute // 5) * 5)
        buckets[bucket.isoformat()].append(occ)

    timestamps = sorted(buckets.keys())
    avgs = [round(sum(buckets[t]) / len(buckets[t]), 1) for t in timestamps]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=avgs,
        mode="lines",
        line=dict(color="#1f77b4", width=1.5),
        name="Occupancy",
        hovertemplate="<b>%{x|%a %d %b %H:%M}</b><br>Occupancy: %{y}<extra></extra>",
    ))
    fig.update_layout(
        title=f"Occupancy — Last {days} Days",
        xaxis_title="Time",
        yaxis_title="People",
        template="plotly_white",
        height=350,
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 2: Average occupancy by hour of day
# ---------------------------------------------------------------------------

def _chart_best_hour(parsed: list[tuple[datetime, int]]) -> go.Figure:
    """Bar chart — average occupancy per hour, highlighting the best hours."""
    hourly: dict[int, list[int]] = defaultdict(list)
    for dt, occ in parsed:
        hourly[dt.hour].append(occ)

    hours = sorted(hourly.keys())
    avgs = [round(sum(hourly[h]) / len(hourly[h]), 1) for h in hours]

    # Color the bars: green for lowest quartile, blue for middle, red for top
    if avgs:
        sorted_avgs = sorted(avgs)
        q25 = sorted_avgs[len(sorted_avgs) // 4]
        q75 = sorted_avgs[3 * len(sorted_avgs) // 4]
        colors = []
        for v in avgs:
            if v <= q25:
                colors.append("#2ca02c")  # green — best
            elif v >= q75:
                colors.append("#d62728")  # red — busiest
            else:
                colors.append("#1f77b4")  # blue — average
    else:
        colors = ["#1f77b4"] * len(hours)

    labels = [f"{h:02d}:00" for h in hours]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=avgs,
        marker_color=colors,
        hovertemplate="<b>%{x}</b><br>Avg occupancy: %{y}<extra></extra>",
    ))

    # Mark the best hour
    if avgs:
        best_idx = avgs.index(min(avgs))
        fig.add_annotation(
            x=labels[best_idx], y=avgs[best_idx],
            text=f"Best: {labels[best_idx]}",
            showarrow=True, arrowhead=2, arrowcolor="#2ca02c",
            font=dict(color="#2ca02c", size=12),
        )

    fig.update_layout(
        title="Average Occupancy by Hour of Day",
        xaxis_title="Hour",
        yaxis_title="Avg People",
        template="plotly_white",
        height=320,
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 3: Heatmap — day of week × hour
# ---------------------------------------------------------------------------

def _chart_heatmap(parsed: list[tuple[datetime, int]]) -> go.Figure:
    """Heatmap showing avg occupancy for each (day-of-week, hour) cell."""
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for dt, occ in parsed:
        grid[(dt.weekday(), dt.hour)].append(occ)

    # Build matrix: rows = days (Mon..Sun), cols = hours (0..23)
    hours_present = sorted({h for _, h in grid.keys()})
    z = []
    for dow in range(7):
        row = []
        for h in hours_present:
            values = grid.get((dow, h), [])
            row.append(round(sum(values) / len(values), 1) if values else None)
        z.append(row)

    fig = go.Figure(data=go.Heatmap(
        z=z,
        x=[f"{h:02d}:00" for h in hours_present],
        y=_DOW_NAMES,
        colorscale=[
            [0.0, "#2ca02c"],   # green  — low (good)
            [0.5, "#ffdd57"],   # yellow — medium
            [1.0, "#d62728"],   # red    — high (busy)
        ],
        hovertemplate=(
            "<b>%{y} %{x}</b><br>"
            "Avg occupancy: %{z:.0f}<extra></extra>"
        ),
        colorbar=dict(title="People"),
    ))
    fig.update_layout(
        title="When to Go? Occupancy Heatmap (green = fewest people)",
        template="plotly_white",
        height=320,
        margin=dict(l=90, r=20, t=50, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 4: Prediction for today & tomorrow
# ---------------------------------------------------------------------------

def _chart_prediction(parsed: list[tuple[datetime, int]]) -> go.Figure:
    """
    Hourly forecast for today & tomorrow based on historical averages
    for the same day-of-week.

    Shows mean ± 1 std-dev band.
    """
    import math

    now = datetime.now(timezone.utc)
    today_dow = now.weekday()
    tomorrow_dow = (today_dow + 1) % 7

    # Gather historical data by (day_of_week, hour)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for dt, occ in parsed:
        grid[(dt.weekday(), dt.hour)].append(occ)

    fig = go.Figure()

    for dow, label, color, dash in [
        (today_dow, f"Today ({_DOW_NAMES[today_dow]})", "#1f77b4", "solid"),
        (tomorrow_dow, f"Tomorrow ({_DOW_NAMES[tomorrow_dow]})", "#ff7f0e", "dash"),
    ]:
        hours, means, upper, lower = [], [], [], []
        for h in range(24):
            values = grid.get((dow, h), [])
            if not values:
                continue
            avg = sum(values) / len(values)
            std = math.sqrt(sum((v - avg) ** 2 for v in values) / len(values))
            hours.append(f"{h:02d}:00")
            means.append(round(avg, 1))
            upper.append(round(avg + std, 1))
            lower.append(round(avg - std, 1))

        if not hours:
            continue

        # Confidence band
        fig.add_trace(go.Scatter(
            x=hours + hours[::-1],
            y=upper + lower[::-1],
            fill="toself",
            fillcolor=f"rgba({','.join(_hex_to_rgb(color))},0.15)",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        ))
        # Mean line
        fig.add_trace(go.Scatter(
            x=hours, y=means,
            mode="lines+markers",
            name=label,
            line=dict(color=color, width=2, dash=dash),
            marker=dict(size=4),
            hovertemplate=f"<b>{label} %{{x}}</b><br>Predicted: %{{y}} people<extra></extra>",
        ))

    # Vertical "now" line — use a shape since x-axis is categorical
    now_hour = now.hour
    fig.add_shape(
        type="line",
        x0=f"{now_hour:02d}:00", x1=f"{now_hour:02d}:00",
        y0=0, y1=1, yref="paper",
        line=dict(color="gray", dash="dot", width=1.5),
    )
    fig.add_annotation(
        x=f"{now_hour:02d}:00", y=1, yref="paper",
        text="Now", showarrow=False,
        font=dict(color="gray", size=11),
        yshift=10,
    )

    fig.update_layout(
        title="Predicted Occupancy — Today & Tomorrow",
        xaxis_title="Hour",
        yaxis_title="Predicted People",
        template="plotly_white",
        height=350,
        margin=dict(l=50, r=20, t=50, b=40),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )
    return fig


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

def _assemble_page(
    fig_timeline: go.Figure,
    fig_best_hour: go.Figure,
    fig_heatmap: go.Figure,
    fig_prediction: go.Figure,
    total_readings: int,
    lookback_days: int,
) -> str:
    """Combine all Plotly figures into one self-contained HTML page."""
    # Each figure as a <div> with embedded JS (full_html=False avoids
    # duplicate plotly.js includes)
    include_js = True  # only include plotly.js once
    divs = []
    for fig in [fig_timeline, fig_best_hour, fig_heatmap, fig_prediction]:
        divs.append(fig.to_html(
            full_html=False,
            include_plotlyjs="cdn" if include_js else False,
        ))
        include_js = False

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Badi Oerlikon – Occupancy Dashboard</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 20px;
    background: #f8f9fa; color: #333;
  }}
  h1 {{ margin: 0 0 4px; font-size: 1.6em; }}
  .subtitle {{ color: #666; margin-bottom: 16px; font-size: 0.9em; }}
  .chart-container {{ background: #fff; border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 12px;
    margin-bottom: 16px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  footer {{ text-align: center; color: #999; font-size: 0.8em;
    margin-top: 20px; }}
</style>
</head>
<body>
<h1>🏊 Badi Oerlikon — When Should I Go?</h1>
<p class="subtitle">
  Based on {total_readings:,} readings over the last {lookback_days} days ·
  Updated {now_str}
</p>

<div class="chart-container">{divs[0]}</div>

<div class="grid">
  <div class="chart-container">{divs[1]}</div>
  <div class="chart-container">{divs[2]}</div>
</div>

<div class="chart-container">{divs[3]}</div>

<footer>
  Data source: CrowdMonitor WebSocket API · Badi Oerlikon (SSD-7) ·
  <a href="/api/occupancy?days=7">Raw JSON API</a>
</footer>
</body>
</html>"""


def _empty_page(message: str) -> str:
    """Return a minimal HTML page when there's no data."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Badi Oerlikon Dashboard</title>
<style>
  body {{ font-family: sans-serif; display: flex; justify-content: center;
    align-items: center; min-height: 80vh; color: #666; }}
</style>
</head>
<body><h2>{message}</h2></body>
</html>"""


def _hex_to_rgb(hex_color: str) -> list[str]:
    """Convert '#rrggbb' to ['r', 'g', 'b'] strings."""
    h = hex_color.lstrip("#")
    return [str(int(h[i:i + 2], 16)) for i in (0, 2, 4)]
