"""Precipitación diaria (l/m²) por estación, desde la climatología diaria de AEMET.

Uso:  python -m ingest.diario --data-dir ../lluvia-es-datos
Requiere AEMET_API_KEY. Lee estaciones.json y escribe diario.json: {estacion: {'AAAA-MM-DD': mm}}.
Sirve para completar las ventanas de 1 semana y 1 mes mientras el registro horario es corto.
AEMET publica el dato diario con unos días de retraso: se piden los últimos días y se conserva
lo ya descargado. Las estaciones sin serie climatológica diaria se omiten (AEMET responde 404).
"""
import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .common import AemetError, SinDatos, aemet_get, escribir_json, leer_json
from .historico import parsear_pmes

DIAS_DESCARGA = 45
DIAS_CONSERVA = 120
PAUSA_S = 1.5


def registros_a_dias(registros):
    """Registros diarios de AEMET -> {'2026-11-01': 0.0}. 'Ip' = 0.0; sin dato se omite."""
    dias = {}
    for r in registros:
        f = str(r.get("fecha", ""))[:10]
        v = parsear_pmes(r.get("prec"))
        if len(f) == 10 and v is not None:
            dias[f] = v
    return dias


def descargar(est, ini, fin):
    ruta = (f"/valores/climatologicos/diarios/datos/fechaini/{ini:%Y-%m-%d}T00:00:00UTC"
            f"/fechafin/{fin:%Y-%m-%d}T23:59:59UTC/estacion/{est}")
    return registros_a_dias(aemet_get(ruta))


def fusionar(actual, nuevo, hoy):
    """Los datos nuevos pisan a los viejos; se descarta lo anterior a DIAS_CONSERVA días."""
    corte = (hoy - timedelta(days=DIAS_CONSERVA)).isoformat()
    salida = {}
    for est in set(actual) | set(nuevo):
        dias = {**actual.get(est, {}), **nuevo.get(est, {})}
        dias = {d: v for d, v in dias.items() if d >= corte}
        if dias:
            salida[est] = dict(sorted(dias.items()))
    return salida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    data = Path(args.data_dir)
    ids = sorted(leer_json(data / "estaciones.json"))
    ruta = data / "diario.json"
    previo = leer_json(ruta).get("estaciones", {}) if ruta.exists() else {}

    hoy = datetime.now(timezone.utc).date()
    ini, fin = hoy - timedelta(days=DIAS_DESCARGA), hoy
    nuevo, sin_serie, fallos = {}, 0, 0
    for i, est in enumerate(ids):
        if i:
            time.sleep(PAUSA_S)
        try:
            dias = descargar(est, ini, fin)
        except SinDatos:
            sin_serie += 1
            continue
        except AemetError as e:
            fallos += 1
            print(f"  {est}: error {e}", file=sys.stderr)
            continue
        if dias:
            nuevo[est] = dias
    if ids and not nuevo and not previo:
        raise SystemExit("No se obtuvo ningún dato diario")
    escribir_json(ruta, {"actualizado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                         "fuente": "AEMET (citar a AEMET como autora)",
                         "estaciones": fusionar(previo, nuevo, hoy)})
    ultimo = max((max(d) for d in nuevo.values()), default="-")
    print(f"Estaciones con dato diario: {len(nuevo)} | sin serie: {sin_serie} | fallos: {fallos} | "
          f"último día publicado: {ultimo}")


if __name__ == "__main__":
    main()
