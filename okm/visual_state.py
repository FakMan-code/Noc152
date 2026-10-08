"""NumPy visual-operational state for Noc152.

Collectors (ops) are not wired yet. This module still runs:

- operator: coverage from the expediente; other metrics stay NaN (`?`)
- showcase: same coverage + simulated series so radar/heatmap/sparklines
  can be exercised without Datadog/MCP

Layers: expediente rows → ndarray state → ASCII renderer.
UI (Rich/Textual/Three.js) should consume the matrix, not invent numbers.

Design notes: docs/visual-ops.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from okm.humanize import is_noise_service, product_name
from okm.store import ExpedienteStore

VisualMode = Literal["operator", "showcase"]

METRIC_COLS = (
    "availability",
    "latency",
    "errors",
    "saturation",
    "coverage",
    "criticality",
)

COL_AVAIL, COL_LAT, COL_ERR, COL_SAT, COL_COV, COL_CRIT = range(6)
SPARK_BARS = "▁▂▃▄▅▆▇█"
HEAT_BARS = "░▒▓█"
STATUS_MARK = {"ok": "✓", "alert": "!", "failing": "×", "unknown": "?"}
WINDOW = 16


@dataclass(frozen=True)
class VisualBoard:
    names: tuple[str, ...]
    metrics: np.ndarray  # (N, 6) float64, NaN = no ops data
    series: np.ndarray  # (N, WINDOW) last window (errors or synthetic)
    status: tuple[str, ...]
    mode: VisualMode
    product: str
    source: str


def _coverage_ratio(store: ExpedienteStore, service_id: str) -> float:
    cov = store.coverage_for(service_id)
    observed = sum(int(v.get("observed", 0)) for v in cov.values())
    inferred = sum(int(v.get("inferred", 0)) for v in cov.values())
    gap = sum(int(v.get("gap", 0)) for v in cov.values())
    total = observed + inferred + gap
    if total <= 0:
        return float("nan")
    return observed / total


def build_board(store: ExpedienteStore, *, mode: VisualMode = "operator", seed: int = 152) -> VisualBoard:
    services = [s for s in store.list_services() if not is_noise_service(s.name)]
    services.sort(key=lambda s: s.name.lower())
    n = len(services)
    metrics = np.full((n, len(METRIC_COLS)), np.nan, dtype=np.float64)
    series = np.full((n, WINDOW), np.nan, dtype=np.float64)
    names: list[str] = []
    status: list[str] = []

    for i, svc in enumerate(services):
        names.append(svc.name)
        metrics[i, COL_COV] = _coverage_ratio(store, svc.service_id)
        status.append("unknown")

    if n and mode == "showcase":
        rng = np.random.default_rng(seed)
        t = np.linspace(0.0, 2 * np.pi, WINDOW, dtype=np.float64)
        base = 0.12 + 0.08 * rng.random(n)
        wave = 0.5 + 0.5 * np.sin(t[None, :] + rng.uniform(0, 2 * np.pi, n)[:, None])
        series = np.clip(base[:, None] * wave + 0.02 * rng.normal(size=(n, WINDOW)), 0, 1)
        # One synthetic incident on the first row (demo only).
        series[0, -5:] = np.clip(series[0, -5:] + 0.55, 0, 1)
        metrics[:, COL_AVAIL] = 1.0 - series[:, -1]
        metrics[:, COL_LAT] = 80 + 420 * series[:, -1]
        metrics[:, COL_ERR] = series[:, -1]
        metrics[:, COL_SAT] = 0.25 + 0.5 * series[:, -1]
        metrics[:, COL_CRIT] = np.where(np.arange(n) == 0, 0.9, 0.35)
        err = metrics[:, COL_ERR]
        status = [
            "failing" if e > 0.65 else "alert" if e > 0.35 else "ok" for e in err
        ]

    run = store.latest_run() or {}
    return VisualBoard(
        names=tuple(names),
        metrics=metrics,
        series=series,
        status=tuple(status),
        mode=mode,
        product=product_name(),
        source=str(run.get("source_uri") or store.workspace),
    )


def sparkline(row: np.ndarray) -> str:
    finite = np.isfinite(row)
    if not np.any(finite):
        return "?" * min(len(row), WINDOW)
    lo = float(np.nanmin(row))
    hi = float(np.nanmax(row))
    span = hi - lo if hi > lo else 1.0
    idx = np.floor((row - lo) / span * (len(SPARK_BARS) - 1))
    out: list[str] = []
    for ok, i in zip(finite, idx, strict=False):
        if not ok:
            out.append("?")
            continue
        out.append(SPARK_BARS[int(np.clip(i, 0, len(SPARK_BARS) - 1))])
    return "".join(out)


def heat_bar(row: np.ndarray) -> str:
    finite = np.isfinite(row)
    if not np.any(finite):
        return "?" * min(len(row), WINDOW)
    hi = float(np.nanmax(row)) or 1.0
    norm = np.clip(row / hi, 0, 1)
    out: list[str] = []
    for ok, v in zip(finite, norm, strict=False):
        if not ok:
            out.append("?")
            continue
        out.append(HEAT_BARS[min(int(v * (len(HEAT_BARS) - 1)), len(HEAT_BARS) - 1)])
    return "".join(out)


def _metric_cell(value: float) -> str:
    if not np.isfinite(value):
        return "?"
    return f"{value:.2f}"


def _status_counts(board: VisualBoard) -> str:
    if not board.status:
        return "sin servicios"
    if board.mode == "operator" and all(s == "unknown" for s in board.status):
        n = len(board.names)
        return f"SIN DATOS OPS · {n} servicios · cobertura de expediente sí"
    crit = sum(1 for s in board.status if s == "failing")
    warn = sum(1 for s in board.status if s == "alert")
    ok = sum(1 for s in board.status if s == "ok")
    return f"{crit} critical · {warn} warning · {ok} ok (showcase, no es producción)"


def _radar_ascii(board: VisualBoard) -> str:
    if not board.names:
        return "  (vacío)"
    shown = list(zip(board.names, board.status, strict=False))[:8]
    glyphs = []
    for name, st in shown:
        mark = STATUS_MARK.get(st, "?")
        glyphs.append(f"{mark}{name[:10]}")
    # Two rings: closer = more coverage (or unknown at the rim).
    inner = "  ".join(glyphs[:3]) or "—"
    outer = "  ".join(glyphs[3:]) or "—"
    return f"     {inner}\n  {outer}"


def render_board(board: VisualBoard) -> str:
    title = f"{board.product}  ·  modo {board.mode}"
    status_line = _status_counts(board)
    lines = [
        f"┌ {title} ",
        f"│ PLATFORM STATUS   {status_line}",
        f"│ fuente: {board.source}",
        "├───────────────────────────┬────────────────────────────────┤",
        "│ SERVICE RADAR             │ METRICS (NaN = sin ops)        │",
    ]
    radar = _radar_ascii(board).splitlines()
    while len(radar) < 2:
        radar.append("")
    lines.append(f"│ {radar[0]:<25} │ avail  lat   err   sat   cov   crit │")
    lines.append(f"│ {radar[1]:<25} │ {', '.join(METRIC_COLS)} │")
    lines.append("├───────────────────────────┴────────────────────────────────┤")
    lines.append("│ SIGNAL TIMELINE / HEATMAP")
    if not board.names:
        lines.append("│   ingestá un repo primero")
    for name, row, serie, st in zip(
        board.names, board.metrics, board.series, board.status, strict=False
    ):
        mark = STATUS_MARK.get(st, "?")
        cov = _metric_cell(row[COL_COV])
        lines.append(
            f"│ {mark} {name[:16]:<16} {sparkline(serie)}  "
            f"heat {heat_bar(serie)}  cov={cov}"
        )
    lines.append("├────────────────────────────────────────────────────────────┤")
    lines.append("│ operator = huecos explícitos   showcase = serie simulada   │")
    lines.append("│ animaciones previstas: pulso, onda, desvanecimiento        │")
    lines.append("└────────────────────────────────────────────────────────────┘")
    width = max(len(x) for x in lines)
    lines[0] = lines[0].ljust(width - 1, "─") + "┐"
    return "\n".join(lines)


def board_text(store: ExpedienteStore, *, mode: VisualMode = "operator") -> str:
    return render_board(build_board(store, mode=mode))
