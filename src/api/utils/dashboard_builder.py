"""
Build the Badi Oerlikon occupancy dashboard as a dark-mode webapp.

Charts (all Plotly, server-rendered):
    1. Occupancy timeline — range selector buttons (1D / 3D / 1W / 1M)
    2. Best time to visit — 15-min resolution, opening-hours aware
    3. Weekly heatmap    — 15-min resolution, closed slots greyed out
    4. Today & tomorrow  — historical forecast with ±1σ band
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import plotly.graph_objects as go

logger = logging.getLogger("dashboard_builder")

# ── Constants ──────────────────────────────────────────────────────────────

_TZ = ZoneInfo("Europe/Zurich")

_DOW = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]

# Official opening hours (open_hour, close_hour)
_HOURS: dict[int, tuple[int, int]] = {
    0: (6, 20),  # Montag
    1: (6, 20),  # Dienstag
    2: (6, 22),  # Mittwoch  (Kinderspielnachmittag 14–16)
    3: (6, 20),  # Donnerstag
    4: (6, 22),  # Freitag
    5: (6, 22),  # Samstag
    6: (6, 22),  # Sonntag
}

_OPEN = 6   # earliest opening across all days
_CLOSE = 22  # latest closing across all days

# Best-time recommendation: ≤ 30 min before earliest close (20:00) → 19:30
# (assumes a 30-minute swimming slot; start must allow full slot before close)
_BEST_H, _BEST_M = 19, 30

# ── Dark-mode colour palette (GitHub dark) ─────────────────────────────────

_BG     = "#0d1117"
_CARD   = "#161b22"
_BORDER = "#30363d"
_TEXT   = "#e6edf3"
_MUTED  = "#7d8590"
_ACCENT = "#58a6ff"
_GOOD   = "#3fb950"
_WARN   = "#d29922"
_BAD    = "#f85149"
_GRID   = "#21262d"


# ── Helpers ────────────────────────────────────────────────────────────────

def _slot(h: int, m: int) -> str:
    """'HH:MM' label for a 15-min slot."""
    return f"{h:02d}:{m:02d}"


def _all_slots() -> list[tuple[int, int]]:
    """Every 15-min slot from 06:00 … 22:00 (close mark for padding)."""
    slots = [(h, m) for h in range(_OPEN, _CLOSE) for m in (0, 15, 30, 45)]
    slots.append((_CLOSE, 0))  # include closing-time mark as visual padding
    return slots


def _is_open(dow: int, h: int, m: int) -> bool:
    oh, ch = _HOURS[dow]
    return oh <= h + m / 60 < ch


def _before_cutoff(h: int, m: int) -> bool:
    """True when the slot is ≤ 19:15 (45 min before earliest close)."""
    return (h, m) <= (_BEST_H, _BEST_M)


def _bin15(dt: datetime) -> tuple[int, int]:
    """Round a datetime to its 15-min bin → (hour, minute)."""
    return dt.hour, (dt.minute // 15) * 15


def _hex_rgb(c: str) -> str:
    """'#rrggbb' → 'r,g,b' for use in rgba()."""
    h = c.lstrip("#")
    return ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def _base(**kw) -> dict:
    """Common dark layout dict for every chart."""
    d = dict(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="Inter,system-ui,-apple-system,sans-serif",
            color=_TEXT, size=12,
        ),
        margin=dict(l=50, r=20, t=40, b=40),
        xaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID),
        yaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID),
    )
    d.update(kw)
    return d


# ── Data fetching ──────────────────────────────────────────────────────────

def _fetch_readings(lookback_days: int) -> list[dict]:
    """Read CSV blobs for the last N days from Azure Blob Storage."""
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        logger.error("azure-storage-blob not installed")
        return []

    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn:
        aws = os.getenv("AzureWebJobsStorage", "")
        if aws and aws != "UseDevelopmentStorage=true":
            conn = aws
    if not conn:
        return []

    container = os.getenv("BLOB_CONTAINER_NAME", "occupancy-data")
    svc = BlobServiceClient.from_connection_string(conn)
    cc = svc.get_container_client(container)

    rows: list[dict] = []
    today = datetime.now(timezone.utc).date()

    for offset in range(lookback_days + 1):
        day = today - timedelta(days=offset)
        prefix = day.strftime("%Y-%m-%d/")
        try:
            for blob in cc.list_blobs(name_starts_with=prefix):
                try:
                    data = (cc.get_blob_client(blob.name)
                            .download_blob().readall().decode())
                    for r in csv.DictReader(io.StringIO(data)):
                        ts = r.get("timestamp", "")
                        occ = r.get("occupancy", "")
                        if ts and occ:
                            rows.append({
                                "timestamp": ts,
                                "occupancy": int(float(occ)),
                            })
                except Exception:
                    pass
        except Exception:
            pass

    rows.sort(key=lambda r: r["timestamp"])
    return rows


def _parse(rows: list[dict]) -> list[tuple[datetime, int]]:
    """Raw dicts → (local_datetime, occupancy) in Europe/Zurich."""
    out: list[tuple[datetime, int]] = []
    for r in rows:
        s = r["timestamp"]
        try:
            fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in s else "%Y-%m-%dT%H:%M:%S"
            dt = datetime.strptime(s, fmt)
            dt = (dt.replace(tzinfo=timezone.utc)
                  .astimezone(_TZ)
                  .replace(tzinfo=None))
            out.append((dt, r["occupancy"]))
        except ValueError:
            continue
    return out


# ── Chart 1 — Timeline ────────────────────────────────────────────────────

def _chart_timeline(data: list[tuple[datetime, int]]) -> go.Figure:
    """Line chart of raw occupancy (5-min buckets) with opening-hour shapes."""

    # 5-min bucketing
    buckets: dict[datetime, list[int]] = defaultdict(list)
    for dt, occ in data:
        b = dt.replace(second=0, microsecond=0,
                       minute=(dt.minute // 5) * 5)
        buckets[b].append(occ)

    ts = sorted(buckets)
    vals = [round(sum(buckets[t]) / len(buckets[t]), 1) for t in ts]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ts, y=vals, mode="lines",
        line=dict(color=_ACCENT, width=1.5),
        fill="tozeroy",
        fillcolor=f"rgba({_hex_rgb(_ACCENT)},0.08)",
        hovertemplate=(
            "<b>%{x|%a %d %b %H:%M}</b><br>"
            "%{y} people<extra></extra>"
        ),
    ))

    # Subtle green bands for each day's opening hours
    shapes = []
    if ts:
        d0, d1 = ts[0].date(), ts[-1].date()
        cur = d0
        while cur <= d1:
            oh, ch = _HOURS[cur.weekday()]
            shapes.append(dict(
                type="rect",
                x0=datetime(cur.year, cur.month, cur.day, oh).isoformat(),
                x1=datetime(cur.year, cur.month, cur.day, ch).isoformat(),
                y0=0, y1=1, yref="paper",
                fillcolor=f"rgba({_hex_rgb(_GOOD)},0.04)",
                line_width=0, layer="below",
            ))
            cur += timedelta(days=1)

    # Default x-range: last 7 days
    now = datetime.now(_TZ).replace(tzinfo=None)
    fig.update_layout(**_base(
        height=380,
        shapes=shapes,
        showlegend=False,
        xaxis=dict(
            type="date", gridcolor=_GRID,
            range=[
                (now - timedelta(days=7)).isoformat(),
                (now + timedelta(minutes=30)).isoformat(),
            ],
        ),
        yaxis=dict(title="People", gridcolor=_GRID),
    ))
    return fig


# ── Chart 2 — Best time to visit ──────────────────────────────────────────

def _chart_best_time(data: list[tuple[datetime, int]]) -> go.Figure:
    """Bar chart — average occupancy per 15-min slot across all days."""

    by_slot: dict[tuple[int, int], list[int]] = defaultdict(list)
    for dt, occ in data:
        hm = _bin15(dt)
        if _OPEN <= hm[0] < _CLOSE:
            by_slot[hm].append(occ)

    slots = _all_slots()
    labels = [_slot(h, m) for h, m in slots]
    avgs = []
    for s in slots:
        v = by_slot.get(s, [])
        avgs.append(round(sum(v) / len(v), 1) if v else 0)

    # Colour bars green → yellow → red by relative occupancy
    positive = [a for a in avgs if a > 0]
    if positive:
        mn, mx = min(positive), max(positive)
        rng = mx - mn or 1
        colors = []
        for a in avgs:
            if a <= 0:
                colors.append(_GRID)
                continue
            t = (a - mn) / rng
            if t < 0.35:
                colors.append(_GOOD)
            elif t < 0.65:
                colors.append(_WARN)
            else:
                colors.append(_BAD)
    else:
        colors = [_ACCENT] * len(slots)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=avgs, marker_color=colors,
        hovertemplate="<b>%{x}</b><br>Avg: %{y} people<extra></extra>",
    ))

    # ── Best-time marker — best 30-min swim window ──
    # Only the *start* of the pair must be ≤ cutoff (last entry time).
    slot_ok = [
        a > 0 and _is_open(0, *s)
        for s, a in zip(slots, avgs)
    ]
    best_start: int | None = None
    best_combined: float = float("inf")
    for i in range(len(slots) - 1):
        if not (slot_ok[i] and slot_ok[i + 1]):
            continue
        if not _before_cutoff(*slots[i]):
            continue
        combined = avgs[i] + avgs[i + 1]
        if combined < best_combined:
            best_combined = combined
            best_start = i

    if best_start is not None:
        end_idx = best_start + 2
        end_label = (
            labels[end_idx] if end_idx < len(labels)
            else _slot(_CLOSE, 0)
        )
        fig.add_annotation(
            x=labels[best_start], y=avgs[best_start],
            text=f"✓ Best: {labels[best_start]}–{end_label}",
            showarrow=True, arrowhead=2, ay=-55,
            arrowcolor=_GOOD,
            font=dict(color=_GOOD, size=12),
            bgcolor=f"rgba({_hex_rgb(_GOOD)},0.15)",
            bordercolor=_GOOD, borderwidth=1, borderpad=4,
        )

    # ── Closing-time marker at 20:00 ──
    fig.add_vline(
        x="20:00", line_dash="dash", line_color=_WARN, line_width=1,
    )
    fig.add_annotation(
        x="20:00", y=1.02, yref="paper",
        text="Closes 20:00 (Mon/Tue/Thu)",
        showarrow=False, font=dict(color=_WARN, size=9),
    )

    # Hourly ticks for readability
    hticks = [_slot(h, 0) for h in range(_OPEN, _CLOSE + 1)]
    fig.update_layout(**_base(
        height=340,
        showlegend=False,
        xaxis=dict(
            gridcolor=_GRID,
            tickmode="array", tickvals=hticks, ticktext=hticks,
        ),
        yaxis=dict(title="Avg People", gridcolor=_GRID),
    ))
    return fig


# ── Chart 3 — Heatmap ─────────────────────────────────────────────────────

def _chart_heatmap(data: list[tuple[datetime, int]]) -> go.Figure:
    """Day-of-week × 15-min heatmap.  Cells outside opening hours are null."""

    grid: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for dt, occ in data:
        h, m = _bin15(dt)
        if _OPEN <= h < _CLOSE:
            grid[(dt.weekday(), h, m)].append(occ)

    slots = _all_slots()
    labels = [_slot(h, m) for h, m in slots]

    z: list[list[float | None]] = []
    for dow in range(7):
        row: list[float | None] = []
        for h, m in slots:
            if not _is_open(dow, h, m):
                row.append(None)
            else:
                v = grid.get((dow, h, m), [])
                row.append(round(sum(v) / len(v), 1) if v else None)
        z.append(row)

    fig = go.Figure(data=go.Heatmap(
        z=z, x=labels, y=_DOW,
        colorscale=[
            [0.0, _GOOD],
            [0.5, _WARN],
            [1.0, _BAD],
        ],
        hovertemplate=(
            "<b>%{y} %{x}</b><br>"
            "Avg: %{z:.0f} people<extra></extra>"
        ),
        colorbar=dict(
            title=dict(text="People", font=dict(color=_TEXT)),
            tickfont=dict(color=_TEXT),
        ),
        xgap=1, ygap=2,
    ))

    hticks = [_slot(h, 0) for h in range(_OPEN, _CLOSE + 1)]
    fig.update_layout(**_base(
        height=340,
        xaxis=dict(
            gridcolor=_GRID,
            tickmode="array", tickvals=hticks, ticktext=hticks,
        ),
        yaxis=dict(autorange="reversed", gridcolor=_GRID),
    ))
    return fig


# ── Chart 4 — Prediction ──────────────────────────────────────────────────

def _chart_prediction(data: list[tuple[datetime, int]]) -> go.Figure:
    """Forecast for today & tomorrow using per-slot historical averages."""

    now = datetime.now(_TZ)
    t_dow = now.weekday()
    tm_dow = (t_dow + 1) % 7

    grid: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for dt, occ in data:
        h, m = _bin15(dt)
        grid[(dt.weekday(), h, m)].append(occ)

    fig = go.Figure()

    for dow, label, color, dash in [
        (t_dow, f"Today ({_DOW[t_dow]})", _ACCENT, "solid"),
        (tm_dow, f"Tomorrow ({_DOW[tm_dow]})", _WARN, "dash"),
    ]:
        oh, ch = _HOURS[dow]
        xs, means, hi, lo = [], [], [], []

        for h, m in _all_slots():
            if not _is_open(dow, h, m):
                continue
            v = grid.get((dow, h, m), [])
            if not v:
                continue
            avg = sum(v) / len(v)
            std = (math.sqrt(sum((x - avg) ** 2 for x in v) / len(v))
                   if len(v) > 1 else 0)
            xs.append(_slot(h, m))
            means.append(round(avg, 1))
            hi.append(round(avg + std, 1))
            lo.append(round(max(avg - std, 0), 1))

        if not xs:
            continue

        # ±1σ confidence band
        fig.add_trace(go.Scatter(
            x=xs + xs[::-1],
            y=hi + lo[::-1],
            fill="toself",
            fillcolor=f"rgba({_hex_rgb(color)},0.12)",
            line=dict(width=0),
            showlegend=False, hoverinfo="skip",
        ))
        # Mean line
        fig.add_trace(go.Scatter(
            x=xs, y=means,
            mode="lines+markers", name=label,
            line=dict(color=color, width=2, dash=dash),
            marker=dict(size=3),
            hovertemplate=(
                f"<b>{label} %{{x}}</b><br>"
                f"%{{y}} people<extra></extra>"
            ),
        ))

        # Opening / closing annotations
        fig.add_annotation(
            x=_slot(oh, 0), y=1, yref="paper", yshift=12,
            text=f"Opens {oh}:00", showarrow=False,
            font=dict(color=_GOOD, size=9),
        )
        fig.add_annotation(
            x=_slot(ch - 1, 45), y=1, yref="paper", yshift=12,
            text=f"Closes {ch}:00", showarrow=False,
            font=dict(color=_BAD, size=9),
        )

    # "Now" marker
    now_slot = _slot(*_bin15(now.replace(tzinfo=None)))
    fig.add_vline(
        x=now_slot, line_dash="dot", line_color=_MUTED, line_width=1.5,
    )
    fig.add_annotation(
        x=now_slot, y=1, yref="paper", yshift=12,
        text="Now", showarrow=False,
        font=dict(color=_MUTED, size=11),
    )

    hticks = [_slot(h, 0) for h in range(_OPEN, _CLOSE + 1)]
    fig.update_layout(**_base(
        height=360,
        xaxis=dict(
            gridcolor=_GRID,
            tickmode="array", tickvals=hticks, ticktext=hticks,
        ),
        yaxis=dict(title="People", gridcolor=_GRID),
        legend=dict(
            yanchor="top", y=0.99, xanchor="left", x=0.01,
            bgcolor="rgba(0,0,0,0)",
        ),
    ))
    return fig


# ── HTML assembly ──────────────────────────────────────────────────────────

_PLOTLY_CFG: dict = {"responsive": True, "displaylogo": False}


def _assemble_page(
    fig_tl: go.Figure,
    fig_bt: go.Figure,
    fig_hm: go.Figure,
    fig_pr: go.Figure,
    n_readings: int,
    lookback_days: int,
    raw_data: list[tuple[datetime, int]] | None = None,
) -> str:
    """Combine all charts into one dark-mode HTML page."""

    now = datetime.now(_TZ)
    now_str = now.strftime("%H:%M %Z, %a %d %b %Y")
    dow = now.weekday()
    oh, ch = _HOURS[dow]
    is_open = oh <= now.hour < ch

    status_cls = "open" if is_open else "closed"
    status_icon = "\U0001f7e2" if is_open else "\U0001f534"  # 🟢 / 🔴
    if is_open:
        status_text = f"Open now · closes at {ch}:00"
    else:
        # Find next opening
        next_dow = (dow + 1) % 7
        next_oh, _ = _HOURS[next_dow]
        status_text = f"Closed · opens {_DOW[next_dow]} at {next_oh:02d}:00"

    # Render chart divs with known IDs
    tl_html = fig_tl.to_html(
        full_html=False, include_plotlyjs=False,
        div_id="chart-timeline", config=_PLOTLY_CFG)
    bt_html = fig_bt.to_html(
        full_html=False, include_plotlyjs=False,
        div_id="chart-besttime", config=_PLOTLY_CFG)
    hm_html = fig_hm.to_html(
        full_html=False, include_plotlyjs=False,
        div_id="chart-heatmap", config=_PLOTLY_CFG)
    pr_html = fig_pr.to_html(
        full_html=False, include_plotlyjs=False,
        div_id="chart-prediction", config=_PLOTLY_CFG)

    # Pre-compute range endpoints for JS buttons (Zurich local, naive)
    now_naive = now.replace(tzinfo=None)
    r1  = (now_naive - timedelta(days=1)).isoformat()
    r3  = (now_naive - timedelta(days=3)).isoformat()
    r7  = (now_naive - timedelta(days=7)).isoformat()
    r30 = (now_naive - timedelta(days=30)).isoformat()
    r_now = now_naive.isoformat()

    good_rgb = _hex_rgb(_GOOD)
    warn_rgb = _hex_rgb(_WARN)
    bad_rgb  = _hex_rgb(_BAD)
    accent_rgb = _hex_rgb(_ACCENT)

    # Raw data as JSON for client-side resolution switching
    raw_json = (
        json.dumps([[dt.strftime("%Y-%m-%dT%H:%M:%S"), occ]
                    for dt, occ in raw_data])
        if raw_data else "[]"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Badi Oerlikon – Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}

  body {{
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    margin: 0; padding: 0;
    background: {_BG}; color: {_TEXT};
    line-height: 1.5;
  }}

  .container {{ max-width: 1200px; margin: 0 auto; padding: 16px 20px; }}

  /* ── Header ── */
  header {{
    border-bottom: 1px solid {_BORDER};
    padding-bottom: 14px; margin-bottom: 18px;
  }}
  .header-row {{
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 10px;
  }}
  h1 {{
    margin: 0; font-size: 1.4em; font-weight: 600;
    background: linear-gradient(135deg, {_ACCENT}, {_GOOD});
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
  }}
  .subtitle {{ color: {_MUTED}; font-size: 0.82em; margin-top: 2px; }}
  .badge {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 14px; border-radius: 20px;
    font-size: 0.82em; font-weight: 500;
  }}
  .badge.open  {{ background: rgba({good_rgb},0.12); color: {_GOOD}; }}
  .badge.closed {{ background: rgba({bad_rgb},0.12); color: {_BAD}; }}

  /* ── Info cards ── */
  .info-row {{
    display: grid; grid-template-columns: auto 1fr; gap: 14px;
    margin-bottom: 18px;
  }}
  @media (max-width: 700px) {{ .info-row {{ grid-template-columns: 1fr; }} }}

  .info-card {{
    background: {_CARD}; border: 1px solid {_BORDER};
    border-radius: 10px; padding: 14px 16px;
  }}
  .info-card h3 {{
    margin: 0 0 6px; font-size: 0.75em; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.06em; color: {_MUTED};
  }}
  .hours-tbl {{ width: 100%; border-collapse: collapse; font-size: 0.82em; }}
  .hours-tbl td {{ padding: 1px 8px 1px 0; white-space: nowrap; }}
  .hours-tbl td:first-child {{ font-weight: 500; color: {_ACCENT}; width: 28px; }}
  .hours-tbl .note td {{ color: {_MUTED}; font-size: 0.88em; font-style: italic; }}

  /* ── Chart cards ── */
  .card {{
    background: {_CARD}; border: 1px solid {_BORDER};
    border-radius: 10px; padding: 14px 16px;
    margin-bottom: 14px; overflow: hidden;
  }}
  .card-head {{
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 6px; margin-bottom: 6px;
  }}
  .card-head h2 {{ margin: 0; font-size: 0.95em; font-weight: 600; }}
  .card-head .desc {{ color: {_MUTED}; font-size: 0.78em; }}

  /* ── Range buttons ── */
  .range-btns {{ display: flex; gap: 4px; }}
  .rbtn {{
    background: transparent; color: {_MUTED};
    border: 1px solid {_BORDER}; padding: 3px 12px;
    border-radius: 6px; cursor: pointer;
    font-size: 0.78em; font-family: inherit; font-weight: 500;
    transition: all .15s;
  }}
  .rbtn:hover {{ color: {_TEXT}; border-color: {_MUTED}; }}
  .rbtn.active {{
    background: rgba({accent_rgb},0.15);
    color: {_ACCENT}; border-color: {_ACCENT};
  }}

  /* ── Grid ── */
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}

  /* ── Footer ── */
  footer {{
    text-align: center; color: {_MUTED}; font-size: 0.72em;
    padding: 16px 0; border-top: 1px solid {_BORDER}; margin-top: 16px;
  }}
  footer a {{ color: {_ACCENT}; text-decoration: none; }}
  footer a:hover {{ text-decoration: underline; }}

  /* Plotly tweaks */
  .js-plotly-plot .plotly .modebar {{ opacity: 0.4; }}
  .js-plotly-plot .plotly .modebar:hover {{ opacity: 1; }}
</style>
</head>

<body>
<div class="container">

  <!-- Header -->
  <header>
    <div class="header-row">
      <div>
        <h1>\U0001f3ca Badi Oerlikon</h1>
        <div class="subtitle">
          {n_readings:,} readings &middot; {lookback_days}-day window &middot; {now_str}
        </div>
      </div>
      <span class="badge {status_cls}">{status_icon} {status_text}</span>
    </div>
  </header>

  <!-- Info row -->
  <div class="info-row">
    <div class="info-card">
      <h3>&Ouml;ffnungszeiten</h3>
      <table class="hours-tbl">
        <tr><td>Mo</td><td>06 – 20 Uhr</td></tr>
        <tr><td>Di</td><td>06 – 20 Uhr</td></tr>
        <tr><td>Mi</td><td>06 – 22 Uhr</td></tr>
        <tr class="note"><td></td><td>Kinderspielnachmittag 14 – 16 Uhr</td></tr>
        <tr><td>Do</td><td>06 – 20 Uhr</td></tr>
        <tr><td>Fr</td><td>06 – 22 Uhr</td></tr>
        <tr><td>Sa</td><td>06 – 22 Uhr</td></tr>
        <tr><td>So</td><td>06 – 22 Uhr</td></tr>
      </table>
      <div style="margin-top:6px;font-size:0.76em;color:{_MUTED}">
        Letzter Einlass 30 Min. vor Schluss &middot;
        Wasser verlassen bis Badschluss
      </div>
    </div>

    <div class="info-card" style="display:flex;flex-direction:column;justify-content:center">
      <h3>Legende</h3>
      <div style="font-size:0.85em;display:grid;grid-template-columns:auto 1fr;gap:3px 10px">
        <span style="color:{_GOOD}">\u25a0</span><span>Low occupancy — great time</span>
        <span style="color:{_WARN}">\u25a0</span><span>Moderate — expect some people</span>
        <span style="color:{_BAD}">\u25a0</span><span>Busy — peak hours</span>
        <span style="color:{_MUTED}">\u25a0</span><span>Pool closed</span>
      </div>
    </div>
  </div>

  <!-- Chart 1: Timeline -->
  <div class="card">
    <div class="card-head">
      <div>
        <h2>Occupancy Timeline</h2>
        <span class="desc"><span id="res-label">5-min resolution</span> &middot; shaded = opening hours</span>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <div class="range-btns">
          <button class="rbtn" onclick="setRange(1)" data-d="1">1D</button>
          <button class="rbtn" onclick="setRange(3)" data-d="3">3D</button>
          <button class="rbtn active" onclick="setRange(7)" data-d="7">1W</button>
          <button class="rbtn" onclick="setRange(30)" data-d="30">1M</button>
        </div>
        <div class="range-btns">
          <button class="rbtn res-btn" onclick="setResolution(0)">Raw</button>
          <button class="rbtn res-btn" onclick="setResolution(1)">1m</button>
          <button class="rbtn res-btn active" onclick="setResolution(5)">5m</button>
          <button class="rbtn res-btn" onclick="setResolution(15)">15m</button>
        </div>
      </div>
    </div>
    {tl_html}
  </div>

  <!-- Charts 2 & 3 side by side -->
  <div class="grid-2">
    <div class="card">
      <div class="card-head">
        <div>
          <h2>Best Time to Visit</h2>
          <span class="desc">15-min avg &middot; dashed = Mon/Tue/Thu close</span>
        </div>
      </div>
      {bt_html}
    </div>

    <div class="card">
      <div class="card-head">
        <div>
          <h2>Weekly Pattern</h2>
          <span class="desc">15-min heatmap &middot; empty = pool closed</span>
        </div>
      </div>
      {hm_html}
    </div>
  </div>

  <!-- Chart 4: Prediction -->
  <div class="card">
    <div class="card-head">
      <div>
        <h2>Forecast — Today &amp; Tomorrow</h2>
        <span class="desc">Historical averages &plusmn; 1&sigma;</span>
      </div>
    </div>
    {pr_html}
  </div>

  <footer>
    Data: CrowdMonitor WebSocket &middot; Badi Oerlikon (SSD-7) &middot;
    <a href="/api/occupancy?days=7">JSON API</a> &middot;
    <a href="/api/health_check">Health</a>
  </footer>

</div><!-- /container -->

<script>
var _ranges = {{
  1:  ["{r1}",  "{r_now}"],
  3:  ["{r3}",  "{r_now}"],
  7:  ["{r7}",  "{r_now}"],
  30: ["{r30}", "{r_now}"]
}};
function setRange(d) {{
  Plotly.relayout("chart-timeline", {{"xaxis.range": _ranges[d]}});
  document.querySelectorAll(".rbtn:not(.res-btn)").forEach(function(b){{b.classList.remove("active")}});
  event.currentTarget.classList.add("active");
}}
var _rawData = {raw_json};
function _parseLocal(s) {{
  var p = s.split(/[-T:]/);  
  return new Date(+p[0], p[1]-1, +p[2], +p[3]||0, +p[4]||0, +(p[5]||0)).getTime();
}}
function _fmtLocal(ms) {{
  var d = new Date(ms);
  function pad(n) {{ return n < 10 ? '0'+n : ''+n; }}
  return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+
         pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());
}}
function setResolution(resMin) {{
  if (resMin === 0) {{
    Plotly.restyle("chart-timeline", {{
      x: [_rawData.map(function(d){{return d[0]}})],
      y: [_rawData.map(function(d){{return d[1]}})]       
    }}, [0]);
  }} else {{
    var resMs = resMin * 60000;
    var buckets = {{}};
    _rawData.forEach(function(d) {{
      var t = _parseLocal(d[0]);
      var key = Math.floor(t / resMs) * resMs;
      if (!buckets[key]) buckets[key] = [];
      buckets[key].push(d[1]);
    }});
    var keys = Object.keys(buckets).map(Number).sort(function(a,b){{return a-b}});
    Plotly.restyle("chart-timeline", {{
      x: [keys.map(_fmtLocal)],
      y: [keys.map(function(k) {{
        var a = buckets[k];
        return Math.round(a.reduce(function(s,v){{return s+v}},0)/a.length*10)/10;
      }})]
    }}, [0]);
  }}
  var lbl = resMin === 0 ? 'Raw resolution' : resMin + '-min resolution';
  document.getElementById('res-label').textContent = lbl;
  document.querySelectorAll('.res-btn').forEach(function(b){{b.classList.remove('active')}});
  if (event && event.currentTarget) event.currentTarget.classList.add('active');
}}
</script>

</body>
</html>"""


def _empty_page(msg: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Badi Oerlikon</title>
<style>
  body {{
    font-family: Inter,system-ui,sans-serif;
    background: {_BG}; color: {_MUTED};
    display: flex; justify-content: center; align-items: center;
    min-height: 80vh; margin: 0;
  }}
</style></head>
<body><h2>{msg}</h2></body></html>"""


# ── Public entry point ─────────────────────────────────────────────────────

def build_dashboard_html(lookback_days: int = 30) -> str:
    """Fetch data, build charts, return complete HTML page."""
    readings = _fetch_readings(lookback_days)
    if not readings:
        return _empty_page("No occupancy data found yet — check back later.")

    parsed = _parse(readings)
    if not parsed:
        return _empty_page("Could not parse any readings.")

    return _assemble_page(
        _chart_timeline(parsed),
        _chart_best_time(parsed),
        _chart_heatmap(parsed),
        _chart_prediction(parsed),
        len(parsed),
        lookback_days,
        raw_data=parsed,
    )
