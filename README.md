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
- `ingest/historico.py`: climatología mensual de AEMET (1996 hasta el año en curso) -> `mensual/<estacion>.json`.
- `ingest/embalses.py`: volumen diario de los embalses de la provincia (SAIH Hidrosur) -> `embalses.json` y `embalses/historico.csv`.
- `.github/workflows/`: `horario.yml` (cada hora, minuto 7), `catalogo.yml` (día 2 de cada mes y manual), `historico.yml` (día 3 de cada mes y manual) y `embalses.yml` (cada día, 08:41 UTC).
- `tests/test_core.py`: pruebas sin red (`python -m tests.test_core`).

## Secrets necesarios (Settings → Secrets and variables → Actions)
1. `AEMET_API_KEY`: clave de AEMET OpenData.
2. `DATOS_TOKEN`: token fine-grained con permiso *Contents: Read and write* solo sobre `lluvia-es-datos`.

## Puesta en marcha
1. Crear los dos secrets.
2. Lanzar a mano el workflow **Catálogo** (genera `estaciones.json`, `municipios.json`, `municipio_estacion.json`).
3. Lanzar a mano **Ingesta horaria** y comprobar `latest.json`; a partir de ahí corre solo.

## Embalses y su licencia
No hay API ni licencia expresa de reutilización de SAIH Hidrosur. Se lee la tabla HTML del [informe público](https://www.redhidrosurmedioambiente.es/saih/informe/embalses) una vez al día, con un `User-Agent` que identifica el proyecto, y la web cita la fuente y avisa de que los datos son automáticos, no verificados y sin valor oficial. Los embalses se eligen en `config.yml` (`embalses`, identificadores de Hidrosur).

## Lluvia frente a lo normal
La media de cada mes sale de la serie de `mensual/` (años completos anteriores al año en curso). El mes en curso solo se compara con el mes entero cuando el registro horario lo cubre desde el día 1.

## Asignación de municipios
Cada municipio usa la **estación más cercana** con observación horaria (puede estar en otra provincia) y se guarda la distancia. Si supera `umbral_aviso_km`, el dato se marca como orientativo.

## Si algo falla
- **Ingesta sin ejecutarse:** el cron de GitHub puede retrasarse o no dispararse; el workflow se puede lanzar a mano.
- **Errores 403 al publicar:** caducidad o permisos del `DATOS_TOKEN` (debe tener *Contents: Read and write* sobre `lluvia-es-datos`).
- **Histórico:** AEMET limita cada consulta a 36 meses; el código pide tramos de 3 años.
