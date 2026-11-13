from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src import config
from src.database import fetch_all
from src.failure_model import kanno_pgv_cm_s, hypocentral_distance_km, load_shakemap_grid

SERIES_PRIMARY = "#2a78d6"
SERIES_SECONDARY = "#eb6834"
NEUTRAL = "#9a9890"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
FIGURE_SIZE = (8.0, 4.5)
DPI = 150
LINE_WIDTH = 2.0
MARKER_SIZE = 9
HISTOGRAM_BINS = 40
DISTANCE_CURVE_MAX_KM = 2000.0
DISTANCE_CURVE_POINTS = 400
ALPHA_POINTS = 0.35
TITLE_FONT_SIZE = 12
GRID_LINE_WIDTH = 0.8
BAND_ALPHA = 0.15
BAR_EDGE_WIDTH = 1
BAR_HEIGHT = 0.55
LABEL_HIGH = 0.92
LABEL_LOW = 0.80
TOP_BAR_EDGE = -0.5
OFFSET_FINAL_MEAN = (-150, 18)
OFFSET_RIGHT = (6, 0)
OFFSET_LEFT = (-110, 0)
OFFSET_BASELINE = (-6, -14)
OFFSET_BAR_VALUE = (4, -4)

VARIANT_LABELS = {
    config.VARIANT_PRIMARY: "Kanno + dist. hipocentral (K=0,3)",
    config.VARIANT_RUPTURE: "Kanno + dist. a la ruptura (K=0,3)",
    config.VARIANT_SHAKEMAP: "ShakeMap USGS (K=0,3)",
    config.VARIANT_BRITTLE: "Kanno + dist. hipocentral (K=1,0)",
}


def _style(axis: Any, title: str, x_label: str, y_label: str) -> None:
    axis.set_facecolor(SURFACE)
    axis.set_title(title, color=TEXT_PRIMARY, fontsize=TITLE_FONT_SIZE, loc="left")
    axis.set_xlabel(x_label, color=TEXT_SECONDARY)
    axis.set_ylabel(y_label, color=TEXT_SECONDARY)
    axis.grid(True, color=GRID, linewidth=GRID_LINE_WIDTH)
    axis.set_axisbelow(True)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(GRID)
    axis.tick_params(colors=TEXT_SECONDARY)


def _save(figure: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.patch.set_facecolor(SURFACE)
    figure.tight_layout()
    figure.savefig(path, dpi=DPI)
    plt.close(figure)
    return path


def convergence_plot(running_mean: list[float], samples: list[float]) -> Path:
    values = np.asarray(running_mean)
    draws = np.asarray(samples)
    runs = np.arange(1, values.shape[0] + 1)
    deviation = np.array([draws[:n].std(ddof=1) if n > 1 else 0.0 for n in runs])
    half_width = config.CONFIDENCE_Z * deviation / np.sqrt(runs)
    figure, axis = plt.subplots(figsize=FIGURE_SIZE)
    axis.fill_between(runs, values - half_width, values + half_width, color=SERIES_PRIMARY, alpha=BAND_ALPHA, linewidth=0)
    axis.plot(runs, values, color=SERIES_PRIMARY, linewidth=LINE_WIDTH)
    axis.annotate(f"media final = {values[-1]:.4f}", (runs[-1], values[-1]), textcoords="offset points", xytext=OFFSET_FINAL_MEAN, color=TEXT_PRIMARY)
    _style(axis, "Convergencia Monte Carlo del ATTR post-sismo (IC 95 %)", "Número de realizaciones N", "ATTR acumulado")
    return _save(figure, config.OUTPUT_DIR / "attr_convergence.png")


def attr_histogram(samples: list[float], before: float) -> Path:
    figure, axis = plt.subplots(figsize=FIGURE_SIZE)
    axis.hist(samples, bins=HISTOGRAM_BINS, color=SERIES_PRIMARY, edgecolor=SURFACE, linewidth=BAR_EDGE_WIDTH)
    mean = float(np.mean(samples))
    axis.axvline(mean, color=TEXT_PRIMARY, linewidth=LINE_WIDTH, linestyle="--")
    axis.axvline(before, color=NEUTRAL, linewidth=LINE_WIDTH)
    axis.annotate(f"media post-sismo {mean:.4f}", (mean, axis.get_ylim()[1] * LABEL_HIGH), xytext=OFFSET_RIGHT, textcoords="offset points", color=TEXT_PRIMARY)
    axis.annotate(f"en operación {before:.4f}", (before, axis.get_ylim()[1] * LABEL_LOW), xytext=OFFSET_LEFT, textcoords="offset points", color=TEXT_SECONDARY)
    _style(axis, "Distribución de ATTR(k) en las realizaciones Monte Carlo", "ATTR(k)", "Frecuencia")
    return _save(figure, config.OUTPUT_DIR / "attr_histogram.png")


def _fiber_failures(connection: Any) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT f.distance_km, f.failure_probability, e.length_m FROM edge_failure f JOIN network_edges e USING (edge_id) "
        "WHERE e.source_layer = %s",
        (config.FIBER_LAYER,),
    )


def probability_histogram(connection: Any) -> Path:
    rows = _fiber_failures(connection)
    figure, axis = plt.subplots(figsize=FIGURE_SIZE)
    axis.hist([row["failure_probability"] for row in rows], bins=HISTOGRAM_BINS, color=SERIES_PRIMARY, edgecolor=SURFACE, linewidth=BAR_EDGE_WIDTH)
    _style(axis, "Probabilidad de falla de los enlaces de fibra (modelo principal)", "Probabilidad de falla", "Número de enlaces")
    return _save(figure, config.OUTPUT_DIR / "failure_histogram.png")


def probability_vs_distance(connection: Any) -> Path:
    rows = _fiber_failures(connection)
    figure, axis = plt.subplots(figsize=FIGURE_SIZE)
    axis.scatter(
        [row["distance_km"] for row in rows],
        [row["failure_probability"] for row in rows],
        s=MARKER_SIZE,
        color=SERIES_PRIMARY,
        alpha=ALPHA_POINTS,
        linewidths=0,
    )
    _style(axis, "Probabilidad de falla vs. distancia mínima al epicentro (fibra)", "Distancia al epicentro (km)", "Probabilidad de falla")
    return _save(figure, config.OUTPUT_DIR / "failure_vs_distance.png")


def pgv_vs_distance(connection: Any, magnitude: float, depth_km: float) -> Path:
    rows = fetch_all(
        connection,
        "SELECT s.mid_lon, s.mid_lat, s.epicentral_distance_m FROM edge_subsegments s JOIN network_edges e USING (edge_id) "
        "WHERE e.source_layer = %s",
        (config.FIBER_LAYER,),
    )
    lon = np.array([row["mid_lon"] for row in rows])
    lat = np.array([row["mid_lat"] for row in rows])
    epicentral = np.array([row["epicentral_distance_m"] for row in rows]) / config.METERS_PER_KM
    observed = load_shakemap_grid().sample(lon, lat)
    inside = observed > 0
    curve_distance = np.linspace(0.0, DISTANCE_CURVE_MAX_KM, DISTANCE_CURVE_POINTS)
    curve = kanno_pgv_cm_s(magnitude, hypocentral_distance_km(curve_distance, depth_km))
    figure, axis = plt.subplots(figsize=FIGURE_SIZE)
    axis.scatter(epicentral[inside], observed[inside], s=MARKER_SIZE, color=SERIES_SECONDARY, alpha=ALPHA_POINTS, linewidths=0, label="ShakeMap USGS en tramos de fibra")
    axis.plot(curve_distance, curve, color=SERIES_PRIMARY, linewidth=LINE_WIDTH, label="Kanno et al. (2006), Vs30 = 400 m/s")
    axis.set_yscale("log")
    axis.legend(frameon=False, labelcolor=TEXT_PRIMARY)
    _style(axis, "PGV vs. distancia al epicentro: modelo y ShakeMap", "Distancia al epicentro (km)", "PGV (cm/s, escala log)")
    return _save(figure, config.OUTPUT_DIR / "pgv_vs_distance.png")


def attr_by_variant(report: dict[str, Any]) -> Path:
    rows = [row for row in report["post_earthquake"] if row["scenario"] == config.BASE_SCENARIO]
    labels = [VARIANT_LABELS[row["variant"]] for row in rows]
    after = [row["attr_after"] for row in rows]
    before = rows[0]["attr_before"]
    figure, axis = plt.subplots(figsize=FIGURE_SIZE)
    positions = np.arange(len(rows))
    axis.barh(positions, after, color=SERIES_PRIMARY, height=BAR_HEIGHT)
    axis.axvline(before, color=NEUTRAL, linewidth=LINE_WIDTH, linestyle="--")
    axis.annotate(f"en operación {before:.4f}", (before, TOP_BAR_EDGE), xytext=OFFSET_BASELINE, textcoords="offset points", ha="right", color=TEXT_SECONDARY)
    for position, value in zip(positions, after):
        axis.annotate(f"{value:.4f}", (value, position), xytext=OFFSET_BAR_VALUE, textcoords="offset points", color=TEXT_PRIMARY)
    axis.set_yticks(positions, labels)
    axis.invert_yaxis()
    _style(axis, "ATTR post-sismo por variante del modelo de falla (solo fibra)", "ATTR", "")
    return _save(figure, config.OUTPUT_DIR / "attr_by_variant.png")


def build_all_plots(connection: Any, report: dict[str, Any], magnitude: float, depth_km: float) -> list[Path]:
    paths = [probability_histogram(connection), probability_vs_distance(connection), pgv_vs_distance(connection, magnitude, depth_km)]
    if report.get("primary_samples"):
        before = next(row["attr_before"] for row in report["post_earthquake"] if row["variant"] == config.VARIANT_PRIMARY)
        paths.append(convergence_plot(report["primary_running_mean"], report["primary_samples"]))
        paths.append(attr_histogram(report["primary_samples"], before))
        paths.append(attr_by_variant(report))
    return paths
