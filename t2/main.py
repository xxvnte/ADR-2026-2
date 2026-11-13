from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import Any, Callable

import requests

from src import attr_pipeline, config, earthquake, failure_model, key_nodes, loader, map_builder, plots, sql_export, topology
from src.database import DatabaseUnavailableError, ensure_extensions, session

logger = logging.getLogger("main")

LAYER_NAMES = {"fiber": "Fibra óptica", "power_poles": "Postación eléctrica", "road_no_poles": "Camino sin postación", "ferry": "Ferry"}
ROLE_NAMES = {"generate": "Genera", "exchange": "Intercambia", "receive": "Recibe"}
SCENARIO_NAMES = {config.BASE_SCENARIO: "Solo fibra", config.ALL_LAYERS_SCENARIO: "4 capas"}
SCOPE_NAMES = {attr_pipeline.SCOPE_CONTINENTAL: "continental", attr_pipeline.SCOPE_WITH_RAPA_NUI: "con Rapa Nui"}
VARIANT_NAMES = map_builder.VARIANT_LABELS
ANALYZE_NAMES = {
    "Isolated segments": "segmentos aislados",
    "Dead ends": "extremos colgantes",
    "Potential gaps found near dead ends": "posibles brechas cerca de extremos",
    "Intersections detected": "intersecciones sin nodo",
    "Ring geometries": "geometrías en anillo",
}


def configure_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=config.RUN_LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )


def say(message: str = "") -> None:
    print(message, flush=True)


def title(message: str) -> None:
    say()
    say(f"=== {message} ===")


def timed(label: str, action: Callable[[], Any]) -> Any:
    start = time.perf_counter()
    result = action()
    say(f"  ({label}: {time.perf_counter() - start:.1f} s)")
    logger.info("%s finished in %.2f s", label, time.perf_counter() - start)
    return result


def step_load(connection: Any) -> None:
    title("1. Carga de la infraestructura (Respuesta_T5610)")
    ensure_extensions(connection)
    summary = timed("carga", lambda: loader.load_all(connection))
    say(f"  {'Capa':<22}{'Segm. crudos':>13}{'km crudos':>11}{'Segm. limpios':>15}{'km limpios':>12}")
    for row in summary:
        say(f"  {LAYER_NAMES[row['source_layer']]:<22}{row['raw_segments']:>13}{float(row['raw_km']):>11.1f}{row['clean_segments']:>15}{float(row['clean_km']):>12.1f}")


def step_topology(connection: Any) -> None:
    title("2. Topología con pgr_createTopology")
    say(f"  Versión de pgRouting: {topology.pgrouting_version(connection)}")
    analysis = timed("topología", lambda: topology.build_topology(connection))
    summary = topology.topology_summary(connection)
    say(f"  Tolerancia elegida: {config.TOPOLOGY_TOLERANCE_DEG} grados (≈{config.TOPOLOGY_TOLERANCE_DEG * config.METERS_PER_DEGREE_LAT:.0f} m)")
    say(f"  Aristas: {summary['edges']} · vértices: {summary['vertices']} · aristas sin topología: {summary['edges_without_topology']}")
    for scenario, stats in summary["components"].items():
        say(f"  Componentes conexas ({SCENARIO_NAMES[scenario]}): {stats['components']} (la mayor con {stats['largest_component']} vértices)")
    say("  pgr_analyzeGraph: " + ", ".join(f"{ANALYZE_NAMES.get(key, key)} = {value}" for key, value in analysis.items()))
    say("  Comparación de tolerancias (sin Rapa Nui):")
    rows = timed("comparación de tolerancias", lambda: topology.compare_tolerances(connection))
    say(f"  {'Escenario':<12}{'Tolerancia':>12}{'≈ m':>8}{'Método':>16}{'Vértices':>10}{'Componentes':>13}{'Mayor':>8}")
    for row in rows:
        method = "snap" if row["method"] == "snap_only" else "snap + nodos"
        say(f"  {SCENARIO_NAMES[row['scenario']]:<12}{row['tolerance_deg']:>12g}{row['tolerance_m']:>8}{method:>16}{row['vertices']:>10}{row['components']:>13}{row['largest_component']:>8}")


def step_key_nodes(connection: Any) -> None:
    title("3. Nodos clave (genera / intercambia / recibe)")
    result = timed("nodos clave", lambda: key_nodes.build_key_nodes(connection))
    say(f"  Nodos clave: {result['nodes']} (incluye Hanga Roa, solo para sensibilidad)")
    say(f"  Umbral de anclaje: {config.KEY_NODE_ANCHOR_MAX_DISTANCE_M / config.METERS_PER_KM:.0f} km · radio de fusión: {config.KEY_NODE_MERGE_RADIUS_M / config.METERS_PER_KM:.0f} km")
    for row in result["by_role"]:
        say(f"  {ROLE_NAMES[row['role']]:<12} {row['nodes']:>3} nodos, {row['anchored']:>3} anclados")
    table = key_nodes.key_node_table(connection)
    key_nodes.export_key_nodes(table, config.OUTPUT_DIR / "key_nodes.json")
    unanchored = [row for row in table if row["vertex_id"] is None]
    for row in unanchored:
        say(f"  No anclado: {row['name']} (vértice más cercano a {float(row['anchor_distance_m']) / config.METERS_PER_KM:.1f} km)")


def step_earthquake(connection: Any) -> None:
    title("4. Terremoto del Maule 2010 (USGS)")
    epicenter = timed("sismo", lambda: earthquake.load_earthquake(connection))
    say(f"  Evento USGS: {epicenter.event_id}")
    say(f"  Magnitud {epicenter.magnitude} · {epicenter.event_time:%Y-%m-%d %H:%M:%S} UTC · profundidad {epicenter.depth_km} km")
    say(f"  Epicentro: lat {epicenter.lat}, lon {epicenter.lon}")


def step_failure(connection: Any) -> None:
    title("5-6. Probabilidad de falla por enlace")
    result = timed("probabilidades", lambda: failure_model.compute_failures(connection))
    validation = result["validation"]
    say(f"  Subtramos evaluados (≤ {config.SEGMENT_STEP_M / config.METERS_PER_KM:.0f} km): {result['subsegments']} · enlaces: {result['edges']}")
    say(f"  Validación: {'OK' if validation['passed'] else 'FALLÓ'} (fuera de [0,1]: {validation['out_of_range']}, NaN: {validation['nan_values']}, correlación p-distancia: {validation['distance_correlation']:.3f})")
    say(f"  {'Variante':<52}{'mín':>8}{'mediana':>9}{'media':>8}{'máx':>8}{'p>0,5':>7}{'p>0,9':>7}")
    for row in failure_model.failure_statistics(connection, (config.FIBER_LAYER,)):
        say(f"  {VARIANT_NAMES[row['variant']]:<52}{row['p_min']:>8.4f}{row['p_median']:>9.4f}{row['p_mean']:>8.4f}{row['p_max']:>8.4f}{row['above_0_5']:>7}{row['above_0_9']:>7}")


def step_export(connection: Any, verify: bool) -> None:
    title("7. Archivo main.sql")
    result = timed("exportación", lambda: sql_export.export_main_sql(connection))
    say(f"  {result['path']}: {result['inserts']} INSERT para {result['edges']} enlaces ({result['bytes'] / config.BYTES_PER_MB:.2f} MB)")
    if verify:
        check = timed("verificación en BD limpia", sql_export.verify_in_clean_database)
        status = "OK" if check["returncode"] == 0 and check["rows"] == result["edges"] else "FALLÓ"
        say(f"  Ejecución en BD limpia: {status} (filas cargadas: {check['rows']})")


def print_operational(report: dict[str, Any]) -> None:
    say(f"  {'Escenario':<26}{'n':>4}{'C(n,2)':>8}{'Pares conectados':>18}{'ATTR':>9}{'SQL':>9}{'¿Coincide?':>12}")
    for row in report["operational"]:
        label = f"{SCENARIO_NAMES[row['scenario']]} ({SCOPE_NAMES[row['scope']]})"
        say(f"  {label:<26}{row['n']:>4}{row['total_pairs']:>8}{row['connected_pairs']:>18}{row['attr']:>9.4f}{row['sql_check']['attr']:>9.4f}{'sí' if row['sql_matches'] else 'NO':>12}")
    base = report["operational"][0]
    say(f"  ¿Todos los nodos clave conectados entre sí? {'sí' if base['all_connected'] else 'no'}")
    say(f"  Componentes con nodos clave: {base['components_with_key_nodes']} · nodos clave aislados: {len(base['isolated_key_nodes'])}")
    for component in base["components"]:
        if component["key_nodes"] > 1:
            say(f"    [{component['key_nodes']} nodos] " + "; ".join(component["members"]))
    say("  Aislados: " + "; ".join(base["isolated_key_nodes"]))


def print_post(report: dict[str, Any]) -> None:
    say(f"  {'Escenario / variante':<62}{'Antes':>8}{'Después':>9}{'σ':>8}{'Pérdida':>9}")
    for row in report["post_earthquake"]:
        label = f"{SCENARIO_NAMES[row['scenario']]} · {VARIANT_NAMES[row['variant']]}"
        say(f"  {label:<62}{row['attr_before']:>8.4f}{row['attr_after']:>9.4f}{row['std']:>8.4f}{row['relative_loss'] * config.PERCENT:>8.1f}%")
    primary = next(row for row in report["post_earthquake"] if row["variant"] == config.VARIANT_PRIMARY)
    say(f"  Modelo principal: N = {primary['runs']}, semilla = {primary['seed']}, IC 95 % = [{primary['ci95'][0]:.4f}, {primary['ci95'][1]:.4f}], P5/P50/P95 = {primary['percentiles']['5']:.4f}/{primary['percentiles']['50']:.4f}/{primary['percentiles']['95']:.4f}")
    deterministic = report["deterministic"]
    say(f"  Escenario determinista (cortar p ≥ {deterministic['threshold']}): {deterministic['removed_edges']} enlaces cortados, ATTR = {deterministic['attr_after']:.4f}")
    say("  Nodos clave más afectados (socios perdidos esperados):")
    for row in report["node_impact"][: config.TOP_AFFECTED_COUNT]:
        say(f"    {row['name'][:60]:<60} {row['baseline_partners']:>3} → {row['expected_partners_after']:>6.2f} (P pérdida = {row['partner_loss_probability']:.3f})")
    say("  Pares críticos (menor probabilidad de seguir conectados):")
    for row in report["critical_pairs"][: config.TOP_AFFECTED_COUNT]:
        say(f"    {row['node_a'][:40]} ↔ {row['node_b'][:40]}: {row['connection_probability']:.3f}")


def step_attr(connection: Any) -> dict[str, Any]:
    title("3 y 8. ATTR antes y después del terremoto")
    report = timed("ATTR + Monte Carlo", lambda: attr_pipeline.run_attr(connection))
    say("  ATTR en operación (ec. 8 con un único escenario sin fallas):")
    print_operational(report)
    say("  ATTR tras el sismo 8,8 (Monte Carlo, estimador de la ec. 9):")
    print_post(report)
    epicenter = earthquake.read_epicenter(connection)
    paths = plots.build_all_plots(connection, report, epicenter.magnitude, epicenter.depth_km)
    say("  Gráficos: " + ", ".join(path.name for path in paths))
    say(f"  Resultados: {attr_pipeline.ATTR_JSON_PATH}")
    return report


def load_saved_report() -> dict[str, Any] | None:
    if not attr_pipeline.ATTR_JSON_PATH.exists():
        return None
    return json.loads(attr_pipeline.ATTR_JSON_PATH.read_text(encoding="utf-8"))


def step_map(connection: Any, report: dict[str, Any] | None) -> None:
    title("9. Mapa Leaflet")
    active = report or load_saved_report() or attr_pipeline.run_attr(connection)
    result = timed("mapa", lambda: map_builder.build_map(connection, active, earthquake.read_epicenter(connection)))
    say(f"  Mapa generado: {result['path']} ({result['bytes'] / config.BYTES_PER_MB:.2f} MB). Ábralo en el navegador.")


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resiliencia de la infraestructura de Internet chilena ante el terremoto 8,8 (ATTR antes y después).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="ejecuta todo: carga, topología, nodos, sismo, probabilidades, main.sql, ATTR y mapa")
    group.add_argument("--load", action="store_true", help="solo carga la BD (capas, topología, nodos clave, sismo, probabilidades y main.sql)")
    group.add_argument("--attr", action="store_true", help="solo calcula el ATTR antes y después (requiere BD cargada)")
    group.add_argument("--map", action="store_true", help="solo genera el mapa Leaflet (requiere BD cargada)")
    return parser.parse_args(argv)


def run(arguments: argparse.Namespace) -> None:
    with session() as connection:
        if arguments.all or arguments.load:
            step_load(connection)
            step_topology(connection)
            step_key_nodes(connection)
            step_earthquake(connection)
            step_failure(connection)
            step_export(connection, verify=arguments.all)
        report = step_attr(connection) if (arguments.all or arguments.attr) else None
        if arguments.all or arguments.map:
            step_map(connection, report)
    say()
    say("Listo.")


def main(argv: list[str] | None = None) -> int:
    configure_output()
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        run(arguments)
    except DatabaseUnavailableError as error:
        logger.exception("database unavailable")
        say(f"Error: no se pudo conectar a la base de datos. ¿Ejecutó 'docker compose up -d' y existe el archivo .env? Detalle: {error}")
        return 1
    except loader.ShapefileMissingError as error:
        logger.exception("shapefile missing")
        say(f"Error: no se encontró el shapefile {error}. Descomprima Respuesta_T5610 en data/raw/.")
        return 1
    except requests.RequestException as error:
        logger.exception("download failed")
        say(f"Error: falló una descarga de datos externos (USGS, PeeringDB, TeleGeography o Natural Earth). Revise su conexión. Detalle: {error}")
        return 1
    except earthquake.EarthquakeValidationError as error:
        logger.exception("earthquake validation failed")
        say(f"Error: el sismo descargado no pasó la validación: {error}")
        return 1
    except Exception as error:
        logger.exception("unexpected failure")
        say(f"Error inesperado: {error}. Si la BD está vacía, ejecute primero 'python main.py --load'. Revise output/run.log.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
