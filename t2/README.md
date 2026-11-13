# Tarea 2

## Requisitos

- Docker y Docker Compose
- Python ≥ 3.10 (probado con 3.12.4)
- Conexión a internet en la primera ejecución (USGS, PeeringDB, TeleGeography, Natural Earth, Nominatim). Las descargas quedan en caché en `data/raw/`.

## Puesta en marcha

```bash
cp .env.example .env
docker compose up -d
python -m pip install -r requirements.txt
python main.py --all
```

| Variable `.env` | Uso |
|---|---|
| `POSTGRES_HOST`, `POSTGRES_PORT` | host y puerto publicados (5434 por defecto, para no chocar con otras instancias) |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | credenciales que usan el contenedor y Python |
| `DB_CONTAINER` | nombre del contenedor, se usa para ejecutar `psql -f main.sql` en la verificación |

La imagen `pgrouting/pgrouting:17-3.5-3.7.3` trae PostgreSQL 17, PostGIS 3.5.2 y **pgRouting 3.7.3**. Se fijó esa versión porque `pgr_createTopology` quedó deprecada en pgRouting 3.8 y se eliminó en 4.0.

## Uso de `main.py`

| Opción | Qué hace |
|---|---|
| `--all` | todo: carga, topología, comparación de tolerancias, nodos clave, sismo, probabilidades, `main.sql` (con verificación en BD limpia), ATTR antes/después, gráficos y mapa |
| `--load` | solo instancia la BD (capas, topología, nodos clave, sismo, probabilidades) y escribe `main.sql` |
| `--attr` | solo calcula el ATTR en operación y post-sismo, y los gráficos (requiere `--load` previo) |
| `--map` | solo genera `output/map.html` (requiere `--load` previo; reutiliza `output/attr_results.json`) |

Pruebas unitarias (ATTR y modelo de falla):

```bash
python -m pytest
```

## Estructura

```
t2/
├── main.py                  orquestador (argparse)
├── main.sql                 probabilidades de falla por enlace (generado desde la BD)
├── docker-compose.yml, .env.example, requirements.txt, pytest.ini
├── sql/
│   ├── 01_schema.sql        tablas raw_* y load_log
│   ├── 02_normalize.sql     network_edges unificada (LINESTRING, length_m en geografía)
│   ├── 03_topology.sql      pgr_createTopology + pgr_analyzeGraph + network_vertices
│   ├── 04_key_nodes.sql     key_nodes, key_node_roles, key_node_anchors
│   ├── 05_earthquake.sql    tabla earthquake
│   ├── 06_failure.sql       subtramos, edge_failure, edge_failure_variants
│   └── 07_attr_check.sql    ATTR en SQL con pgr_connectedComponents (verificación cruzada)
├── src/
│   ├── config.py            constantes con nombre (sin números mágicos) y lectura de .env
│   ├── database.py          conexión psycopg2
│   ├── loader.py            shapefiles → PostGIS (pyshp)
│   ├── topology.py          topología y comparación de tolerancias
│   ├── key_nodes.py         descarga de fuentes, fusión y anclaje de nodos clave
│   ├── attr.py              ATTR puro (scipy) y Monte Carlo
│   ├── attr_pipeline.py     ATTR antes/después, verificación SQL, CSV/JSON, tabla attr_results
│   ├── earthquake.py        GeoJSON USGS + ShakeMap → tabla earthquake
│   ├── failure_model.py     GMPE de Kanno 2006 + RR de HAZUS + Poisson
│   ├── sql_export.py        genera y verifica main.sql
│   ├── plots.py             gráficos PNG
│   ├── map_builder.py       mapa Leaflet
│   └── map_template.html
├── tests/                   test_attr.py, test_failure_model.py
├── docs/failure_model.md    modelo de falla: ecuaciones, parámetros y citas
├── data/raw/                Respuesta_T5610 (Subtel), GeoJSON del sismo, external/ (fuentes de nodos)
└── output/                  map.html, attr_results.json, CSV y PNG
```

## Datos y procedencia

| Dato | Fuente | Licencia | Archivo |
|---|---|---|---|
| Infraestructura (4 capas) | Subtel, respuesta SAIP T5610 (oficio N°7479/G, 29-05-2023), base del estudio Yafún (2018) | información pública (Ley 20.285) | `data/raw/Respuesta_T5610/` |
| Sismo Maule 2010 | USGS FDSN, evento `official20100227063411530_30` | dominio público | `data/raw/earthquake_maule_2010.geojson` |
| ShakeMap y ruptura finita | USGS ShakeMap (atlas v1), Hayes (2011) | dominio público | `data/raw/external/shakemap_*` (la grilla de 13 MB no se versiona; se descarga sola) |
| Aterrizajes de cables submarinos | TeleGeography Submarine Cable Map API v3 | CC BY-SA 4.0 | `data/raw/external/landing_*.json` |
| IXP y data centers | PeeringDB API | AUP de PeeringDB | `data/raw/external/peeringdb_*.json` |
| Ciudades | Natural Earth 10m populated places | dominio público | `data/raw/external/natural_earth_places.geojson` |
| Hanga Roa (sensibilidad) | OpenStreetMap Nominatim | ODbL | `data/raw/external/hanga_roa_nominatim.json` |

Las URL y fechas exactas de descarga se registran automáticamente en `data/raw/external/sources_manifest.json`.

## Decisiones metodológicas

- **Red base = solo fibra óptica.** Según en Yafún (Sección 4.2–4.3, Cuadro 4.1), la postación eléctrica y los caminos sin postación se documentaron como rutas candidatas para tender fibra, no como enlaces de datos, y el ferry es un trayecto náutico. Las 4 capas se cargan igual, se dibujan en el mapa y se usan como análisis de sensibilidad (con el ferry como enlace marítimo de p = 0).
- **Rapa Nui.** Sus enlaces se conservan en la BD (`is_rapa_nui`). El ATTR base es continental, y la sensibilidad agrega Hanga Roa como nodo que recibe (queda aislado y el ATTR baja de 0,0596 a 0,0573).
- **Snapping.** `pgr_createTopology` con tolerancia 1e-4° (aprox. 11 m, del orden del error GPS del levantamiento en terreno). Entre 0 y 1e-3° las componentes de fibra solo varían de 174 a 165, así que la desconexión es real y no un artefacto. No se aplica `pgr_nodeNetwork` en el cálculo: que dos tendidos se crucen no implica una fusión de fibras. Su efecto (122 componentes) se informa como sensibilidad.
- **Nodos clave.** Generan: aterrizajes de cables internacionales y data centers con ≥ 10 redes en PeeringDB. Intercambian: sedes de IXP/PIT y aterrizajes de cables domésticos. Reciben: las 16 capitales regionales más las ciudades de más de 150 mil habitantes. Los sitios a menos de 1 km entre sí se fusionan en un nodo con varios roles (`key_node_roles`). Cada nodo se ancla al vértice de la red más cercano, medido en geografía, si está a 15 km o menos (radio metropolitano: en Yafún se cita a Subtel sobre anillos urbanos de fibra en Santiago, Valparaíso, Temuco y Concepción que el levantamiento rural no captura). Los nodos no anclados cuentan como aislados en el ATTR.
- **ATTR.** ATTR(k) = Σ_{i<j} Z_ij^k / C(n,2) (Boettcher et al. 2018). En operación hay un único escenario. Tras el sismo, ATTR = Σ_k (α_k/α)·ATTR(k) = E[ATTR(k)], que se estima por Monte Carlo (Bernoulli independientes por enlace, semilla fija).
- **Modelo de falla.** Kanno et al. (2006) para PGV más la tasa de reparaciones de HAZUS-MH (O'Rourke & Ayala 1993), con K = 0,3 (dúctil), integrada en subtramos de 1 km y con P = 1 − exp(−Σ RR·L). Detalle completo en [docs/failure_model.md](docs/failure_model.md).

## Referencias

- Yafún (2018). *Estudio y Recomendaciones sobre la Resiliencia de la Infraestructura de la Internet Chilena*. NIC Chile Research Labs – CORFO 15BPE-47225.
- Boettcher, N., Prieto, Y., Restrepo, J. C., & Pezoa, J. E. (2018). Resilient Multiculture Network Design in the Presence of Exploit-Triggered Correlated Failures. *IEEE Latin America Transactions*, 16(9), 2336–2344. https://doi.org/10.1109/TLA.2018.8789553
- Kanno, T. et al. (2006). *BSSA* 96(3), 879–897. https://doi.org/10.1785/0120050138
- O'Rourke, M. J., & Ayala, G. (1993). *J. Geotech. Eng.* 119(9), 1490–1498. https://doi.org/10.1061/(ASCE)0733-9410(1993)119:9(1490)
- Porter, K. A. (2016). SESM 16-02, University of Colorado Boulder.
- USGS. Evento `official20100227063411530_30`. https://earthquake.usgs.gov/earthquakes/eventpage/official20100227063411530_30
