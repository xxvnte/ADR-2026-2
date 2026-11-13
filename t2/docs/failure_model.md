# Modelo probabilístico de falla de enlaces ante el terremoto del Maule (Mw 8,8, 2010)

Este documento describe la cadena de modelos implementada en [src/failure_model.py](../src/failure_model.py).

## 1. Cadena de modelos

```
epicentro USGS ──► distancia R a cada subtramo (≤ 1 km) ──► PGV(R)  [GMPE Kanno et al. 2006]
                                                              │
                                                              ▼
                              RR = 0,0001 · K · PGV^2,25   [HAZUS-MH / O'Rourke & Ayala 1993]
                                                              │
                                                              ▼
         N_enlace = Σ RR_i · L_i  ──►  P_falla = 1 − exp(−N_enlace)   [proceso de Poisson]
```

### 1.1 Movimiento del suelo: Kanno et al. (2006), eventos someros

Se eligió Kanno et al. (2006) por tres razones:

- entrega **PGV** de forma directa, que es la intensidad que exige el modelo de daño de HAZUS (otras GMPE de subducción, como Zhao et al. 2006 o BC Hydro 2016, solo entregan PGA y aceleraciones espectrales);
- su modelo "shallow" (profundidad focal ≤ 30 km) incluye explícitamente los eventos de **interfase de subducción**. El Maule tiene 22,9 km de profundidad según USGS;
- define la distancia como la distancia más cercana al plano de falla, **o la distancia hipocentral cuando no hay modelo de falla** (p. 880). Esto permite un modelo que parte del epicentro, como pide el enunciado.

Ecuaciones (5), (8) y (9) de Kanno et al. (2006), con log = log10:

```
log10 PGV_roca = a·Mw + b·X − log10(X + d·10^(e·Mw)) + c
G              = p·log10(Vs30) + q
log10 PGV      = log10 PGV_roca + G          [PGV en cm/s]
X = sqrt(R_epi² + h²)  (distancia hipocentral, km)
```

| Parámetro | Valor | Fuente |
|---|---|---|
| a | 0,702 | Kanno et al. (2006), Tabla 3, fila PGV (modelo somero) |
| b | −0,000925 | ídem |
| c | −1,93 | ídem |
| d | 0,00217 | ídem |
| e | 0,5 | ídem, p. 881 ("e = 0,5 for all periods") |
| σ (log10) | 0,321 | ídem (no se usa en la media; ver supuestos) |
| p | −0,7057 | Kanno et al. (2006), Tabla 5 (p. 888), coeficientes de sitio (ec. 8) para PGV |
| q | 1,765 | ídem |
| Vs30 | 400 m/s | supuesto (suelo firme, NEHRP C/D); ver §3 |
| Mw | 8,8 | GeoJSON USGS |
| h | 22,9 km | GeoJSON USGS |

**Verificación de los coeficientes.** Se contrastaron con la implementación de OpenQuake (`openquake/hazardlib/gsim/kanno_2006.py`, GEM Foundation). Esa implementación declara usar los coeficientes entregados por el autor, con algo más de precisión que la Tabla 3, y haber sido verificada contra un vector de prueba del autor principal. La prueba `test_kanno_matches_hand_calculation` reproduce la ecuación a mano.

### 1.2 Daño: tasa de reparaciones de HAZUS-MH (O'Rourke & Ayala 1993)

```
RR [reparaciones/km] = 0,0001 · K · PGV^2,25        (PGV en cm/s)
```

| Parámetro | Valor | Fuente |
|---|---|---|
| Coeficiente | 0,0001 | HAZUS-MH, función de vulnerabilidad por propagación de ondas, basada en O'Rourke & Ayala (1993). Ecuación transcrita como Ec. (1) en Porter (2016, p. 6 impresa / p. 15 del PDF) |
| Exponente | 2,25 | ídem |
| K frágil | 1,0 | ídem: asbesto-cemento, hormigón, fierro fundido |
| K dúctil | 0,3 | ídem: acero, fierro dúctil, PVC. Jeon (2013, Tabla 1) clasifica también el polietileno como dúctil |

Se usa **K = 0,3 (dúctil)** en el modelo principal: el cable de fibra óptica tiene cubierta de polietileno y tolera deformaciones mucho mayores que una tubería frágil. La variante frágil (K = 1,0) se informa como cota superior.

### 1.3 Probabilidad de falla del enlace

Las reparaciones a lo largo de un enlace se modelan como un proceso de Poisson. Si el enlace se divide en subtramos i de longitud L_i ≤ 1 km (`ST_Segmentize` sobre `geography`), con PGV evaluado en el punto medio de cada uno:

```
N_enlace = Σ_i RR(PGV_i) · L_i
P_falla  = 1 − exp(−N_enlace) ∈ [0, 1]
```

El enlace falla si tiene al menos una reparación (un solo corte de fibra interrumpe el enlace). Porter (2016) presenta la Ec. (1) como la tasa **mediana** de reparaciones (R̂) y reporta una razón media/mediana de 1,22. Aquí se usa directamente como la media del proceso de Poisson, lo que subestima levemente las reparaciones esperadas; esto se declara como supuesto. Integrar a lo largo del enlace, en vez de evaluar solo su punto medio, evita subestimar el daño en enlaces largos que pasan cerca del epicentro.

## 2. Variantes de sensibilidad

| Variante | Distancia / intensidad | K |
|---|---|---|
| `kanno_hypocentral_ductile` (principal) | Kanno con distancia hipocentral (desde el epicentro USGS) | 0,3 |
| `kanno_rupture_ductile` | Kanno con distancia 3D al plano de ruptura finita (Hayes 2011, `rupture.json` del ShakeMap USGS) | 0,3 |
| `shakemap_ductile` | PGV de la grilla del ShakeMap USGS v4 (atlas), que combina registros y modelo; vecino más cercano, PGV = 0 fuera de la grilla | 0,3 |
| `kanno_hypocentral_brittle` | igual que la principal | 1,0 |

Resultados sobre la red base (solo fibra, 1915 enlaces), tomados de `python main.py --all`:

| Variante | mediana p | media p | enlaces p > 0,5 | enlaces p > 0,9 | ATTR post-sismo |
|---|---|---|---|---|---|
| Principal (hipocentral, dúctil) | 0,0284 | 0,2027 | 335 | 152 | 0,0402 |
| Ruptura finita, dúctil | 0,3646 | 0,4690 | 893 | 629 | 0,0288 |
| ShakeMap, dúctil | 0,0169 | 0,0933 | 45 | 0 | 0,0348 |
| Hipocentral, frágil | 0,0916 | 0,3107 | 530 | 336 | 0,0357 |

## 3. Supuestos

1. **Sitio.** No hay Vs30 por enlace, así que se asume una condición única de Vs30 = 400 m/s (suelo firme). La variante ShakeMap sí usa el Vs30 propio del ShakeMap (columna SVEL).
2. **Mediana sin variabilidad aleatoria.** Se usa la mediana de la GMPE (no se muestrea ε con σ = 0,321). Así, la incertidumbre del Monte Carlo refleja solo la aleatoriedad del daño dado el PGV.
3. **Independencia.** Condicionado al campo de PGV, los enlaces fallan de forma independiente (Bernoulli). Como el PGV ya depende de la distancia, existe correlación espacial en la *probabilidad*, pero no en la *realización*. En la realidad las fallas están correlacionadas (por ejemplo, un puente o una ladera que corta varias fibras a la vez), así que este supuesto tiende a sobreestimar la diversidad de escenarios y probablemente subestima la probabilidad de cortes simultáneos.
4. **Ferry.** Los trayectos en ferry no están sometidos al mecanismo de propagación de ondas en el suelo, así que se fija p = 0 (`FERRY_FAILURE_PROBABILITY`). El tsunami del 27-F no se modela. El ferry solo afecta la sensibilidad con las 4 capas.
5. **Nodos.** Solo fallan los enlaces; los nodos clave (data centers, aterrizajes, ciudades) se suponen operativos.
6. **Nodos que comparten vértice.** En el escenario base, 8 nodos de Santiago anclan al mismo vértice (1244, de grado 1, a entre 1,1 y 11,8 km), y 3 pares más comparten vértice (Concepción, Temuco y Viña del Mar). Esos 31 de los 79 pares conectados (39 %) no pueden fallar, porque representan la red urbana no levantada, así que el ATTR post-sismo tiene un **piso de 31/1326 = 0,0234**. La pérdida relativa medida es, por lo tanto, conservadora (cota inferior).

## 4. Limitaciones

- **Ruptura extendida.** El Maule rompió unos 500 km (plano de Hayes 2011 entre ≈ 33,4° S y 38,0° S). La distancia al epicentro subestima la intensidad en los extremos de la ruptura (Valparaíso, Arauco). La variante con distancia a la ruptura corrige esto y aumenta la pérdida de ATTR del 32,5 % al 51,7 %.
- **Extrapolación de la GMPE.** Kanno et al. (2006) se calibró con registros de Japón que no incluyen eventos de Mw 8,8, así que aplicarla al Maule es una extrapolación. El gráfico `output/pgv_vs_distance.png` muestra que, en los subtramos de fibra a menos de 150 km del epicentro, Kanno da 53–145 cm/s mientras que el ShakeMap da 16–54 cm/s. Además, Kanno decae más lento que el ShakeMap a más de 500 km.
- **Extrapolación de HAZUS.** La relación de O'Rourke & Ayala se ajustó con PGV de hasta unos 50 cm/s y para tuberías enterradas. Aplicarla a fibra **aérea** sobre postación (la mayoría de los tendidos según Yafún, §4.3) es una aproximación: no existe en la literatura revisada una curva de fragilidad específica para cable aéreo de fibra en función del PGV.
- **Datos de 2017–2018 contra sismo de 2010.** La red es la levantada por Yafún (2018), no la de 2010. El ejercicio es un escenario: "¿qué pasaría si el 27-F ocurriera sobre la red actual?".

## 5. Referencias

- Kanno, T., Narita, A., Morikawa, N., Fujiwara, H., & Fukushima, Y. (2006). A new attenuation relation for strong ground motion in Japan based on recorded data. *Bulletin of the Seismological Society of America*, 96(3), 879–897. https://doi.org/10.1785/0120050138
- O'Rourke, M. J., & Ayala, G. (1993). Pipeline damage due to wave propagation. *Journal of Geotechnical Engineering*, 119(9), 1490–1498. https://doi.org/10.1061/(ASCE)0733-9410(1993)119:9(1490)
- FEMA. *Hazus Earthquake Model Technical Manual* (Hazus-MH), capítulo de sistemas de agua potable, vulnerabilidad de tuberías. https://www.fema.gov/flood-maps/products-tools/hazus (el PDF bloquea la descarga automatizada; la ecuación se verificó en Porter 2016).
- Porter, K. A. (2016). *Damage and Restoration of Water Supply Systems in an Earthquake Sequence* (SESM 16-02). University of Colorado Boulder. Ec. (1). https://www.colorado.edu/ceae/sites/default/files/attached-files/porter_27_jul_2016_cu_water_model.pdf
- Jeon, S.-S. (2013). Seismic behavior of buried pipelines constructed by design criteria and construction specifications of both Korea and the US. *Natural Hazards and Earth System Sciences*, 13(9), 2271–2278. https://doi.org/10.5194/nhess-13-2271-2013
- GEM Foundation. OpenQuake Engine, `openquake/hazardlib/gsim/kanno_2006.py`. https://github.com/gem/oq-engine
- U.S. Geological Survey. M 8.8 – 2010 Maule, Chile Earthquake, evento `official20100227063411530_30`, productos origin, ShakeMap (atlas, v1) y finite-fault (Hayes 2011). https://earthquake.usgs.gov/earthquakes/eventpage/official20100227063411530_30
- Boettcher, N., Prieto, Y., Restrepo, J. C., & Pezoa, J. E. (2018). Resilient Multiculture Network Design in the Presence of Exploit-Triggered Correlated Failures. *IEEE Latin America Transactions*, 16(9), 2336–2344. https://doi.org/10.1109/TLA.2018.8789553
