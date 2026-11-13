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

from .common import (AemetError, SinDatos, aemet_get, cargar_config, escribir_json, haversine_km,
                     leer_json)
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


def elegir_sustitutos(estaciones, con_dato, max_km):
    """Para cada estación sin dato diario propio, la más cercana (<= max_km) que sí lo tiene.
    Se recalcula en cada ejecución: si AEMET vuelve a publicar la serie propia, deja de usarse el sustituto."""
    salida = {}
    for est, e in estaciones.items():
        if est in con_dato:
            continue
        mejor = None
        for otra in con_dato:
            o = estaciones.get(otra)
            if not o:
                continue
            km = haversine_km(e["lat"], e["lon"], o["lat"], o["lon"])
            if km <= max_km and (mejor is None or km < mejor[0]):
                mejor = (km, otra, o["nombre"])
        if mejor:
            salida[est] = {"estacion": mejor[1], "nombre": mejor[2], "distancia_km": round(mejor[0], 1)}
    return salida


def evaluar(n_estaciones, n_con_dato, fallos, max_fallos=0.5):
    """Mensaje de error si la descarga no es fiable (None si va bien). Que una estación no tenga serie
    diaria (404) es normal; lo que alarma es que falle la API o no llegue nada."""
    if n_estaciones and n_con_dato == 0:
        return "No se obtuvo ningún dato diario"
    if n_estaciones and fallos / n_estaciones > max_fallos:
        return f"Fallaron {fallos} de {n_estaciones} estaciones al pedir el dato diario"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    data = Path(args.data_dir)
    estaciones = leer_json(data / "estaciones.json")
    ids = sorted(estaciones)
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
    total = fusionar(previo, nuevo, hoy)
    sustitutos = elegir_sustitutos(estaciones, set(total), cargar_config()["umbral_aviso_km"])
    escribir_json(ruta, {"actualizado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                         "fuente": "AEMET (citar a AEMET como autora)",
                         "estaciones": total, "sustitutos": sustitutos})
    ultimo = max((max(d) for d in nuevo.values()), default="-")
    print(f"Estaciones con dato diario: {len(nuevo)} | sin serie: {sin_serie} | fallos: {fallos} | "
          f"último día publicado: {ultimo} | con sustituto: {len(sustitutos)}")
    problema = evaluar(len(ids), len(nuevo), fallos)
    if problema:   # el dato ya descargado se guarda; el flujo de trabajo falla para que llegue el aviso de GitHub
        raise SystemExit(problema)


if __name__ == "__main__":
    main()
