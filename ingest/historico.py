"""Histórico mensual de precipitación (l/m²) por estación, desde la climatología de AEMET.

Uso:  python -m ingest.historico --data-dir ../lluvia-es-datos [--anio-ini 1996 --anio-fin 2025]
Requiere AEMET_API_KEY. Lee estaciones.json del repo de datos y escribe mensual/<estacion>.json.

Si una estación horaria no tiene serie climatológica propia, se usa la estación climatológica
más cercana (se guarda su identificador y la distancia, y la web lo indica).
"""
import argparse
import time
from datetime import date
from pathlib import Path

from .common import (SinDatos, aemet_get, dms_a_decimal, escribir_json,
                     haversine_km, leer_json)

TROZO_ANIOS = 5          # años por llamada (la API limita el rango)
PAUSA_S = 1.5            # cortesía con el límite de peticiones
MIN_MESES = 120          # menos de 10 años de datos: serie insuficiente, se prueba otra estación
CANDIDATAS = 4           # estaciones cercanas a probar si la propia no sirve


def parsear_pmes(valor):
    """p_mes de AEMET -> float. 'Ip' (inapreciable) = 0.0; vacío o 'Acum' -> None."""
    if valor is None:
        return None
    s = str(valor).strip().replace(",", ".")
    if s.lower() == "ip":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def registros_a_serie(registros):
    """Lista de registros AEMET -> {'1996': [12 valores o None]} (ignora el mes 13 = anual)."""
    serie = {}
    for r in registros:
        f = str(r.get("fecha", ""))
        try:
            anio, mes = f.split("-")
            mes = int(mes)
        except ValueError:
            continue
        if not 1 <= mes <= 12:
            continue
        v = parsear_pmes(r.get("p_mes"))
        fila = serie.setdefault(anio, [None] * 12)
        fila[mes - 1] = v
    return serie


def contar_meses(serie):
    return sum(1 for fila in serie.values() for v in fila if v is not None)


def descargar_serie(estacion, anio_ini, anio_fin):
    serie = {}
    a = anio_ini
    while a <= anio_fin:
        b = min(a + TROZO_ANIOS - 1, anio_fin)
        try:
            regs = aemet_get(f"/valores/climatologicos/mensualesanuales/datos/"
                             f"anioini/{a}/aniofin/{b}/estacion/{estacion}")
            serie.update(registros_a_serie(regs))
        except SinDatos:
            pass
        time.sleep(PAUSA_S)
        a = b + 1
    return serie


def inventario():
    inv = aemet_get("/valores/climatologicos/inventarioestaciones/todasestaciones")
    out = {}
    for e in inv:
        try:
            out[e["indicativo"]] = {"id": e["indicativo"], "nombre": e.get("nombre"),
                                    "lat": dms_a_decimal(e["latitud"]),
                                    "lon": dms_a_decimal(e["longitud"])}
        except (KeyError, ValueError):
            continue
    return out


def cercanas(est, inv, n):
    orden = sorted(inv.values(), key=lambda c: haversine_km(est["lat"], est["lon"], c["lat"], c["lon"]))
    return orden[:n]


def serie_para(est, inv, anio_ini, anio_fin):
    """Devuelve (serie, estacion_fuente, distancia_km) probando la propia y luego las cercanas."""
    for c in cercanas(est, inv, CANDIDATAS):
        d = round(haversine_km(est["lat"], est["lon"], c["lat"], c["lon"]), 1)
        serie = descargar_serie(c["id"], anio_ini, anio_fin)
        if contar_meses(serie) >= MIN_MESES:
            return serie, c, d
    return {}, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--anio-ini", type=int, default=1996)
    ap.add_argument("--anio-fin", type=int, default=date.today().year - 1)
    ap.add_argument("--solo", help="Lista de estaciones separadas por comas (pruebas)")
    args = ap.parse_args()
    out = Path(args.data_dir)
    est = leer_json(out / "estaciones.json")
    inv = inventario()
    ids = args.solo.split(",") if args.solo else sorted(est)
    ok = 0
    for eid in ids:
        e = est[eid]
        # la propia estación primero (si está en el inventario), y si no, las cercanas
        base = dict(e)
        if eid in inv:
            base["lat"], base["lon"] = inv[eid]["lat"], inv[eid]["lon"]
        serie, fuente, dist = serie_para(base, inv, args.anio_ini, args.anio_fin)
        if not fuente:
            print(f"{eid}: sin serie climatológica utilizable")
            continue
        escribir_json(out / "mensual" / f"{eid}.json", {
            "estacion": eid,
            "fuente_estacion": fuente["id"],
            "fuente_nombre": fuente["nombre"],
            "distancia_km": dist,
            "propia": fuente["id"] == eid,
            "anio_ini": args.anio_ini,
            "anio_fin": args.anio_fin,
            "anios": dict(sorted(serie.items())),
        })
        ok += 1
        print(f"{eid}: {contar_meses(serie)} meses desde {fuente['id']} ({dist} km)")
    print(f"Series escritas: {ok} de {len(ids)}")


if __name__ == "__main__":
    main()
