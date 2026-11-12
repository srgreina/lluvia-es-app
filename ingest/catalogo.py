"""Catálogo: estaciones, municipios de la provincia y asignación municipio -> estación más cercana.

Uso:  python -m ingest.catalogo --data-dir ../lluvia-es-datos
Requiere AEMET_API_KEY.

Criterio: cada municipio usa la estación más cercana (distancia haversine al centroide del
municipio) entre TODAS las estaciones con observación horaria (incluye las de provincias
vecinas). Si hay una estación dentro de la provincia a menos de ~1 km del centroide se marca
igualmente como "más cercana"; el campo `propia` indica si el municipio tiene estación en su
propio nombre (ubicación contiene el nombre del municipio).
"""
import argparse
from pathlib import Path

from .common import (aemet_get, cargar_config, dms_a_decimal, escribir_json,
                     haversine_km, normalizar)


def _coord(m, dec_key, dms_key, convertir):
    v = m.get(dec_key)
    if v not in (None, ""):
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            pass
    return convertir(m[dms_key])


def estaciones_observacion():
    """Estaciones presentes en la observación convencional (lat/lon en decimal)."""
    datos = aemet_get("/observacion/convencional/todas")
    est = {}
    for o in datos:
        idema = o.get("idema")
        if idema and o.get("lat") is not None and o.get("lon") is not None:
            est[idema] = {"id": idema, "nombre": o.get("ubi"), "lat": float(o["lat"]),
                          "lon": float(o["lon"]), "alt": o.get("alt")}
    return est


def inventario_provincia(nombre_provincia):
    inv = aemet_get("/valores/climatologicos/inventarioestaciones/todasestaciones")
    objetivo = normalizar(nombre_provincia)
    return {e["indicativo"]: e for e in inv if normalizar(e.get("provincia")) == objetivo}


def municipios_provincia(codigo_ine):
    mun = aemet_get("/maestro/municipios")
    salida = []
    for m in mun:
        mid = str(m.get("id", "")).replace("id", "")
        if not mid.startswith(str(codigo_ine)):
            continue
        salida.append({
            "ine": mid[:5],
            "nombre": m.get("nombre"),
            "lat": _coord(m, "latitud_dec", "latitud", dms_a_decimal),
            "lon": _coord(m, "longitud_dec", "longitud", dms_a_decimal),
        })
    return sorted(salida, key=lambda x: x["ine"])


def asignar(municipios, estaciones, umbral_km):
    asig = {}
    for m in municipios:
        mejor, dist = None, None
        for e in estaciones.values():
            d = haversine_km(m["lat"], m["lon"], e["lat"], e["lon"])
            if dist is None or d < dist:
                mejor, dist = e, d
        if mejor is None:
            continue
        asig[m["ine"]] = {
            "estacion": mejor["id"],
            "estacion_nombre": mejor["nombre"],
            "distancia_km": round(dist, 1),
            "propia": normalizar(m["nombre"]) in normalizar(mejor["nombre"]),
            "orientativo": dist > umbral_km,
        }
    return asig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    cfg = cargar_config()
    out = Path(args.data_dir)

    obs = estaciones_observacion()
    inv = inventario_provincia(cfg["provincia_nombre"])
    muns = municipios_provincia(cfg["provincia_ine"])
    asig = asignar(muns, obs, cfg["umbral_aviso_km"])

    necesarias = {a["estacion"] for a in asig.values()} | (set(inv) & set(obs))
    estaciones = {}
    for eid in sorted(necesarias):
        e = dict(obs[eid])
        i = inv.get(eid)
        if i:
            e["provincia"] = i.get("provincia")
            e["nombre"] = i.get("nombre") or e["nombre"]
        estaciones[eid] = e

    escribir_json(out / "estaciones.json", estaciones)
    escribir_json(out / "municipios.json", muns)
    escribir_json(out / "municipio_estacion.json", asig)
    sin_propia = sum(1 for a in asig.values() if not a["propia"])
    print(f"Estaciones: {len(estaciones)} | municipios: {len(muns)} | "
          f"sin estación propia: {sin_propia} | orientativos: "
          f"{sum(1 for a in asig.values() if a['orientativo'])}")


if __name__ == "__main__":
    main()
