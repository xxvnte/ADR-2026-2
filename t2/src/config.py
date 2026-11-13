from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
EXTERNAL_DIR = RAW_DIR / "external"
SHAPEFILE_DIR = RAW_DIR / "Respuesta_T5610"
SQL_DIR = PROJECT_ROOT / "sql"
OUTPUT_DIR = PROJECT_ROOT / "output"
MAIN_SQL_PATH = PROJECT_ROOT / "main.sql"
MAP_PATH = OUTPUT_DIR / "map.html"
RUN_LOG_PATH = OUTPUT_DIR / "run.log"

SRID_WGS84 = 4326
METERS_PER_KM = 1000.0
BYTES_PER_MB = 1_000_000
PERCENT = 100.0
MAGNITUDE_TOLERANCE = 1e-9
DISPLAY_DECIMALS_KM = 2
DISPLAY_DECIMALS_PROBABILITY = 4
DISPLAY_DECIMALS_INTENSITY = 1
DISPLAY_DECIMALS_IMPACT = 3
SHAPEFILE_ENCODING = "latin1"
INSERT_BATCH_SIZE = 500


@dataclass(frozen=True)
class LayerSpec:
    shapefile: str
    raw_table: str
    source_layer: str


LAYERS: tuple[LayerSpec, ...] = (
    LayerSpec("fibra_optica_detectada", "raw_fiber", "fiber"),
    LayerSpec("postacion_electrica_detectada", "raw_poles_path", "power_poles"),
    LayerSpec("camino_sin_postacion_detectado", "raw_roads_no_poles", "road_no_poles"),
    LayerSpec("trayecto_en_ferry", "raw_ferry", "ferry"),
)

FIBER_LAYER = "fiber"
FERRY_LAYER = "ferry"
BASE_SCENARIO = "fiber_only"
ALL_LAYERS_SCENARIO = "all_layers"
SCENARIO_LAYERS: dict[str, tuple[str, ...]] = {
    BASE_SCENARIO: (FIBER_LAYER,),
    ALL_LAYERS_SCENARIO: tuple(layer.source_layer for layer in LAYERS),
}

RAPA_NUI_MAX_LONGITUDE = -100.0

TOPOLOGY_TOLERANCE_DEG = 1e-4
TOLERANCE_CANDIDATES_DEG: tuple[float, ...] = (0.0, 1e-5, 1e-4, 1e-3)
METERS_PER_DEGREE_LAT = 111_320.0

KEY_NODE_MERGE_RADIUS_M = 1_000.0
KEY_NODE_ANCHOR_MAX_DISTANCE_M = 15_000.0
DATA_CENTER_MIN_NETWORKS = 10
CHILE_COUNTRY_CODE = "CL"
CHILE_NAME = "Chile"
CHILE_LANDING_SUFFIX = "-chile"

RECEIVER_CITIES: tuple[str, ...] = (
    "Arica", "Iquique", "Antofagasta", "Copiapó", "La Serena", "Valparaíso",
    "Santiago", "Rancagua", "Talca", "Chillán", "Concepción", "Temuco",
    "Valdivia", "Puerto Montt", "Coihaique", "Punta Arenas",
    "Viña del Mar", "Talcahuano", "Coquimbo", "Osorno", "San Bernardo",
)
RAPA_NUI_CITY = "Hanga Roa"

ROLE_GENERATE = "generate"
ROLE_EXCHANGE = "exchange"
ROLE_RECEIVE = "receive"

SOURCE_TELEGEOGRAPHY = "TeleGeography Submarine Cable Map API v3"
SOURCE_PEERINGDB = "PeeringDB API"
SOURCE_NATURAL_EARTH = "Natural Earth 10m populated places (simple)"

LANDING_POINTS_URL = "https://www.submarinecablemap.com/api/v3/landing-point/landing-point-geo.json"
LANDING_POINT_DETAIL_URL = "https://www.submarinecablemap.com/api/v3/landing-point/{landing_id}.json"
PEERINGDB_IX_URL = "https://www.peeringdb.com/api/ix?country=CL"
PEERINGDB_FAC_URL = "https://www.peeringdb.com/api/fac?country=CL"
PEERINGDB_IXFAC_URL = "https://www.peeringdb.com/api/ixfac?ix_id={ix_id}"
NATURAL_EARTH_PLACES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_10m_populated_places_simple.geojson"
)
HTTP_TIMEOUT_S = 120
HTTP_USER_AGENT = "resilience-coursework/1.0"

USGS_EVENT_ID = "official20100227063411530_30"
USGS_EVENT_URL = f"https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&eventid={USGS_EVENT_ID}"
USGS_EVENT_PAGE = f"https://earthquake.usgs.gov/earthquakes/eventpage/{USGS_EVENT_ID}"
EARTHQUAKE_GEOJSON_PATH = RAW_DIR / "earthquake_maule_2010.geojson"
SHAKEMAP_GRID_PATH = EXTERNAL_DIR / "shakemap_grid.xml"
RUPTURE_PATH = EXTERNAL_DIR / "shakemap_rupture.json"
EXPECTED_MAGNITUDE = 8.8
CHILE_BBOX = (-76.0, -56.0, -66.0, -17.0)
DEPTH_RANGE_KM = (10.0, 60.0)
DISTANCE_RINGS_KM: tuple[int, ...] = (100, 200, 300, 500)

KANNO_A = 0.702
KANNO_B = -0.000925
KANNO_C = -1.93
KANNO_D = 0.00217
KANNO_E = 0.5
KANNO_SIGMA_LOG10 = 0.321
KANNO_SITE_P = -0.7057
KANNO_SITE_Q = 1.765
KANNO_SHALLOW_MAX_DEPTH_KM = 30.0
SITE_VS30_MPS = 400.0

HAZUS_RR_COEFFICIENT = 0.0001
HAZUS_RR_EXPONENT = 2.25
HAZUS_K_DUCTILE = 0.3
HAZUS_K_BRITTLE = 1.0

SEGMENT_STEP_M = 1_000.0
EARTH_RADIUS_KM = 6_371.0088
FERRY_FAILURE_PROBABILITY = 0.0

VARIANT_PRIMARY = "kanno_hypocentral_ductile"
VARIANT_RUPTURE = "kanno_rupture_ductile"
VARIANT_SHAKEMAP = "shakemap_ductile"
VARIANT_BRITTLE = "kanno_hypocentral_brittle"
FAILURE_VARIANTS: tuple[str, ...] = (VARIANT_PRIMARY, VARIANT_RUPTURE, VARIANT_SHAKEMAP, VARIANT_BRITTLE)

MONTE_CARLO_RUNS = 2_000
MONTE_CARLO_SEED = 20100227
DETERMINISTIC_THRESHOLD = 0.5
PROBABILITY_BINS: tuple[float, ...] = (0.1, 0.5, 0.9)
PERCENTILES: tuple[int, ...] = (5, 50, 95)
CONFIDENCE_Z = 1.96
TOP_AFFECTED_COUNT = 10

MAP_SIMPLIFY_TOLERANCE_DEG = 0.0005
MAP_CENTER = (-36.5, -71.5)
MAP_ZOOM = 5
LEAFLET_VERSION = "1.9.4"


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    container: str


def database_settings() -> DatabaseSettings:
    return DatabaseSettings(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5434")),
        dbname=os.getenv("POSTGRES_DB", "resilience"),
        user=os.getenv("POSTGRES_USER", "resilience"),
        password=os.getenv("POSTGRES_PASSWORD", "resilience"),
        container=os.getenv("DB_CONTAINER", "t2-pgrouting"),
    )
