# Tarea 2

## Requisitos

- **Docker Desktop** (con Docker Compose v2), abierto antes de ejecutar.
- **Python ≥ 3.10**.
- Conexión a internet solo la primera vez, para descargar la imagen `pgrouting/pgrouting:17-3.5-3.7.3`. Los datos externos (USGS, PeeringDB, TeleGeography, Natural Earth, Nominatim) ya vienen en caché en `data/raw/`, así que el resultado es reproducible sin volver a descargarlos.

## Instalación y ejecución (un solo comando)

```bash
pip install -r requirements.txt
python main.py
```

`python main.py` sin opciones ejecuta todo el flujo:

1. Si la base de datos no responde, levanta el contenedor por sí mismo (`docker compose up -d --wait`). No hace falta crear la BD, copiar `.env` ni ajustar rutas o credenciales.
2. Carga las 4 capas de Subtel en PostGIS y normaliza las geometrías.
3. Construye la topología con `pgr_createTopology` (tolerancia 1e-4°) e inicializa `network_edges.failure_probability` en 0. Marca como sintéticas las capas que no son fibra.
4. Identifica y ancla los 53 nodos clave (genera / intercambia / recibe).
5. Carga el sismo desde el GeoJSON de USGS en la tabla `earthquake`.
6. Calcula la probabilidad de falla de cada enlace y actualiza `network_edges.failure_probability`.
7. Genera `main.sql` y lo carga en una BD vacía para comprobar que funciona (4497 filas).
8. Calcula el ATTR antes y después del sismo (Monte Carlo, N = 2000, semilla fija).
9. Genera el mapa, lo sirve en **http://127.0.0.1:8000/map.html** y abre el navegador. Si el puerto 8000 está ocupado, usa el siguiente libre y lo indica en pantalla. El servidor queda activo hasta presionar Ctrl+C.

Tarda alrededor de un minuto, más la descarga de la imagen Docker la primera vez.

### Valores esperados

| Resultado | Valor |
|---|---|
| ATTR en operación (solo fibra, 52 nodos clave) | **0,0596** (79 de 1326 pares conectados) |
| ATTR después del sismo (modelo principal) | **0,0402** (σ = 0,0042; IC 95 % [0,0400; 0,0404]) |
| Diferencia | −0,0194 (−32,5 %) |
| Sensibilidad: ruptura finita / ShakeMap / frágil | 0,0288 / 0,0348 / 0,0357 |
| Sensibilidad: red de 4 capas | 0,1214 → 0,0562 |

### Dónde quedan los resultados

| Archivo | Contenido |
|---|---|
| `main.sql` | infraestructura y probabilidad de falla de los 4497 enlaces (tabla `edge_failure_probability`, con geometría y la marca `is_synthetic`) |
| `output/map.html` | mapa Leaflet (también en http://127.0.0.1:8000/map.html mientras corre `main.py`) |
| `output/attr_results.json` | ATTR antes y después, variantes, convergencia, nodos y enlaces más afectados |
| `output/key_nodes_table.csv` | los 53 nodos clave con rol, coordenadas, región, vértice de anclaje, fuente y justificación |
| `output/critical_links.csv` | enlaces críticos (ΔATTR y riesgo = p × ΔATTR) |
| `output/backbone_nodes.csv` | nodos troncales de la fibra (bifurcaciones de tránsito) |
| `output/key_node_impact.csv`, `output/critical_pairs.csv` | nodos clave y pares más afectados |
| `output/*.png` | gráficos (convergencia, histogramas, PGV vs distancia, variantes) |
| `output/run.log` | registro interno |

## Opciones de `main.py`

| Comando | Qué hace |
|---|---|
| `python main.py` | todo el flujo (equivale a `--all`) |
| `python main.py --load` | solo carga la BD: capas, topología, nodos clave, sismo, probabilidades y `main.sql` |
| `python main.py --attr` | solo calcula el ATTR antes y después (requiere la BD cargada) |
| `python main.py --map` | solo genera y levanta el mapa, sin recalcular (requiere la BD cargada) |
| `--no-browser` | no levanta el servidor del mapa ni abre el navegador (útil en pruebas) |
| `--port N` | puerto del servidor del mapa (por defecto 8000; si está ocupado se usa el siguiente libre) |

## Configuración (opcional)

`src/config.py` trae por defecto los mismos valores de `.env.example`, así que **no hace falta crear `.env`**. Solo si quiere cambiar el puerto o las credenciales, copie `.env.example` a `.env` y edítelo. `docker-compose.yml` usa esos mismos valores por defecto.

| Variable | Por defecto | Uso |
|---|---|---|
| `POSTGRES_HOST`, `POSTGRES_PORT` | `localhost`, `5434` | host y puerto publicados (5434 para no chocar con otras instancias de PostgreSQL) |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `resilience` | credenciales del contenedor |
| `DB_CONTAINER` | `t2-pgrouting` | contenedor donde se ejecuta `psql -f main.sql` para la verificación |

La imagen `pgrouting/pgrouting:17-3.5-3.7.3` trae PostgreSQL 17, PostGIS 3.5.2 y **pgRouting 3.7.3**. Se fijó esa versión porque `pgr_createTopology` quedó deprecada en pgRouting 3.8 y se eliminó en 4.0.

## Librerías

| Librería | Para qué se usa |
|---|---|
| `psycopg2-binary` | conexión a PostgreSQL/PostGIS desde Python |
| `pyshp` | lectura de los shapefiles de Subtel (la imagen de pgRouting no trae `shp2pgsql` ni `ogr2ogr`) |
| `numpy` | vectores de probabilidades y simulación Monte Carlo |
| `scipy` | componentes conexas del grafo (`scipy.sparse.csgraph`) para el ATTR |
| `networkx` | caminos más cortos y puntos de articulación para los nodos troncales |
| `matplotlib` | gráficos PNG de `output/` |
| `requests` | descarga de fuentes externas cuando no están en caché |
| `python-dotenv` | lectura opcional de `.env` |

Las dependencias de desarrollo están en `requirements-dev.txt`: `pytest` (pruebas unitarias) y `playwright` (revisión del mapa en un navegador sin ventana). No son necesarias para ejecutar `main.py`.

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Estructura

```
t2/
├── main.py                  orquestador (un solo comando)
├── main.sql                 infraestructura y probabilidades de falla por enlace (generado desde la BD)
├── docker-compose.yml, .env.example, requirements.txt, requirements-dev.txt, pytest.ini
├── sql/
│   ├── 01_schema.sql        tablas raw_* y load_log
│   ├── 02_normalize.sql     network_edges unificada (LINESTRING, length_m en geografía, is_synthetic)
│   ├── 03_topology.sql      failure_probability = 0, pgr_createTopology, pgr_analyzeGraph, network_vertices
│   ├── 04_key_nodes.sql     key_nodes, key_node_roles, key_node_anchors
│   ├── 05_earthquake.sql    tabla earthquake
│   ├── 06_failure.sql       subtramos, edge_failure, edge_failure_variants
│   └── 07_attr_check.sql    ATTR en SQL con pgr_connectedComponents (verificación cruzada)
├── src/
│   ├── config.py            parámetros con nombre y valores por defecto
│   ├── database.py          conexión psycopg2
│   ├── loader.py            shapefiles → PostGIS
│   ├── topology.py          topología y comparación de tolerancias
│   ├── key_nodes.py         fuentes, fusión y anclaje de nodos clave
│   ├── attr.py              ATTR y Monte Carlo
│   ├── attr_pipeline.py     ATTR antes/después, verificación SQL, CSV/JSON y tabla attr_results
│   ├── analysis.py          tabla de nodos con región, nodos troncales, enlaces críticos y convergencia
│   ├── earthquake.py        GeoJSON de USGS y ShakeMap → tabla earthquake
│   ├── failure_model.py     GMPE de Kanno 2006, RR de HAZUS y Poisson; actualiza network_edges
│   ├── sql_export.py        genera main.sql y lo carga en una BD vacía
│   ├── plots.py             gráficos
│   ├── map_builder.py       mapa Leaflet
│   └── map_template.html
├── tests/                   test_attr.py, test_failure_model.py, test_analysis.py
├── docs/failure_model.md    modelo de falla: ecuaciones, parámetros y fuentes
├── data/raw/                Respuesta_T5610 (Subtel), GeoJSON del sismo y external/ (caché de fuentes)
└── output/                  resultados (se regeneran con main.py)
```

## Datos y procedencia

| Dato | Fuente | Licencia | Archivo |
|---|---|---|---|
| Infraestructura (4 capas) | Subtel, respuesta SAIP T5610 (oficio N°7479/G, 29-05-2023), base del estudio Yafún (2018) | información pública (Ley 20.285) | `data/raw/Respuesta_T5610/` |
| Sismo Maule 2010 | USGS FDSN, evento `official20100227063411530_30` | dominio público | `data/raw/earthquake_maule_2010.geojson` |
| ShakeMap y ruptura finita | USGS ShakeMap (atlas v1) y Hayes (2011) | dominio público | `data/raw/external/shakemap_*` |
| Aterrizajes de cables submarinos | TeleGeography Submarine Cable Map API v3 | CC BY-SA 4.0 | `data/raw/external/landing_*.json` |
| IXP y data centers | PeeringDB API | AUP de PeeringDB | `data/raw/external/peeringdb_*.json` |
| Ciudades y regiones | Natural Earth 10m populated places | dominio público | `data/raw/external/natural_earth_places.geojson` |
| Hanga Roa (sensibilidad) | OpenStreetMap Nominatim | ODbL | `data/raw/external/hanga_roa_nominatim.json` |

Las URL y fechas de descarga están en `data/raw/external/sources_manifest.json`. Toda esta caché se versiona a propósito: PeeringDB y TeleGeography cambian con el tiempo, y sin la caché el número de nodos clave (y por lo tanto el ATTR) podría no coincidir con el informe.

## Decisiones metodológicas

- **Red base = solo fibra óptica (datos reales del SAIP).** Según Yafún (§4.2–4.3, Cuadro 4.1), la postación eléctrica y los caminos sin postación son rutas candidatas para tender fibra, y el ferry es un trayecto náutico. Esas capas se marcan como **sintéticas** (`is_synthetic = true`), se dibujan con línea punteada en el mapa y solo se usan en la sensibilidad de 4 capas (con el ferry en p = 0).
- **Limitación de los datos.** El archivo SAIP trae 10.313 km de fibra detectada, frente a los 26.534 km documentados en el estudio (Cuadro 4.1, sumando todas las capas). No hay topología lógica ni puntos de interconexión, así que el ATTR medido es una cota inferior de la conectividad real.
- **Rapa Nui.** Sus enlaces se conservan (`is_rapa_nui`). El ATTR base es continental, y la sensibilidad agrega Hanga Roa (queda aislado: 0,0596 → 0,0573).
- **Snapping.** Tolerancia 1e-4° (≈ 11 m, del orden del error de digitalización del levantamiento). Entre 0 y 1e-3° las componentes de fibra solo varían de 174 a 165, así que la desconexión es real. No se aplica `pgr_nodeNetwork`, porque que dos tendidos se crucen no implica un empalme.
- **Nodos clave.** Generan: aterrizajes de cables internacionales y data centers con ≥ 10 redes en PeeringDB. Intercambian: sedes de IXP/PIT y aterrizajes de cables domésticos. Reciben: capitales regionales y ciudades de más de 150 mil habitantes. Se anclan al vértice más cercano (≤ 15 km); los no anclados cuentan como aislados. Los **nodos troncales** (bifurcaciones de la fibra por donde pasan más pares de nodos clave) se reportan aparte y no entran al ATTR, porque son de tránsito.
- **ATTR.** ATTR(k) = C(n,2)⁻¹ Σ Z_ij^k y ATTR = Σ_k (α_k/α)·ATTR(k) (Boettcher et al. 2018, ec. 8–9). Tras el sismo se estima por Monte Carlo (N = 2000; error estándar ≈ 0,0001).
- **Modelo de falla.** Kanno et al. (2006) para el PGV, la tasa de reparaciones de HAZUS-MH (O'Rourke & Ayala 1993) con K = 0,3 y P = 1 − exp(−Σ RR·L) sobre subtramos de 1 km. Detalle en [docs/failure_model.md](docs/failure_model.md).

## Referencias

- NIC Chile Research Labs (2018). *Estudio y Recomendaciones sobre la Resiliencia de la Infraestructura de la Internet Chilena*. CORFO 15BPE-47225.
- Boettcher, N., Prieto, Y., Restrepo, S. y Pezoa, J. (2018). Resilient Multiculture Network Design in the Presence of Exploit-Triggered Correlated Failures. *IEEE Latin America Transactions*, 16(9), 2336–2344. https://doi.org/10.1109/TLA.2018.8789553
- Kanno, T., Narita, A., Morikawa, N., Fujiwara, H. y Fukushima, Y. (2006). A New Attenuation Relation for Strong Ground Motion in Japan Based on Recorded Data. *BSSA*, 96(3), 879–897. https://doi.org/10.1785/0120050138
- O'Rourke, M. y Ayala, G. (1993). Pipeline Damage Due to Wave Propagation. *Journal of Geotechnical Engineering*, 119(9), 1490–1498. https://doi.org/10.1061/(ASCE)0733-9410(1993)119:9(1490)
- Porter, K. A. (2016). *Damage and Restoration of Water Supply Systems in an Earthquake Sequence* (SESM 16-02). University of Colorado Boulder.
- USGS. Evento `official20100227063411530_30`. https://earthquake.usgs.gov/earthquakes/eventpage/official20100227063411530_30
