# lluvia-es-app

Ingesta, workflows y web de la app de lluvia en España. Fase actual: **provincia de Málaga**, ampliable cambiando `config.yml`.

Los datos se guardan en el repo [`lluvia-es-datos`](https://github.com/srgreina/lluvia-es-datos).

## Web (escritorio y móvil)
`docs/index.html`: página única (Leaflet + Chart.js) que lee los JSON del repo de datos. Mapa con la lluvia de cada estación en 1 h / 6 h / 24 h, buscador de municipios, botón de ubicación, gráfico horario y ranking. Se publica con GitHub Pages (rama `main`, carpeta `/docs`): https://srgreina.github.io/lluvia-es-app/

Es instalable como app (PWA) y se abre sin conexión con los últimos datos guardados. Las estaciones cercanas se agrupan en el mapa y el círculo muestra la lluvia máxima del grupo.

Para probarla contra otros datos: `?data=/ruta/a/datos/` en la URL. Se puede enlazar un municipio (`#m29067`) o una estación (`#e6172Y`).

Las ventanas de 1/6/24 h se anclan a la **última observación disponible** (AEMET publica con ~1 h de retraso) y la web indica cuántas horas con dato hay detrás de cada cifra.

## Fuente y licencia
Datos © AEMET (AEMET OpenData). Uso y reproducción permitidos citando a AEMET como autora.

## Estructura
- `config.yml`: provincia, umbral de aviso (km) y ventana de horas.
- `ingest/catalogo.py`: estaciones, municipios y asignación municipio → estación más cercana (con distancia).
- `ingest/horario.py`: observación horaria → `horario/AAAA/MM.parquet` + `latest.json`.
- `.github/workflows/`: `catalogo.yml` (manual) y `horario.yml` (cada hora, minuto 7).
- `tests/test_core.py`: pruebas sin red (`python -m tests.test_core`).

## Secrets necesarios (Settings → Secrets and variables → Actions)
1. `AEMET_API_KEY`: clave de AEMET OpenData.
2. `DATOS_TOKEN`: token fine-grained con permiso *Contents: Read and write* solo sobre `lluvia-es-datos`.

## Puesta en marcha
1. Crear los dos secrets.
2. Lanzar a mano el workflow **Catálogo** (genera `estaciones.json`, `municipios.json`, `municipio_estacion.json`).
3. Lanzar a mano **Ingesta horaria** y comprobar `latest.json`; a partir de ahí corre solo.

## Asignación de municipios
Cada municipio usa la **estación más cercana** con observación horaria (puede estar en otra provincia) y se guarda la distancia. Si supera `umbral_aviso_km`, el dato se marca como orientativo.

## Pendiente de verificar con clave real
Los nombres de campo de `/maestro/municipios` y del inventario de estaciones están escritos de forma defensiva, pero no se han probado contra la API. Si el workflow de catálogo falla, el primer sitio a revisar es `ingest/catalogo.py`.
