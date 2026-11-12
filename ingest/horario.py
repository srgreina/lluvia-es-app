"""Ingesta horaria: observación convencional de AEMET -> Parquet mensual + latest.json.

Uso:  python -m ingest.horario --data-dir ../lluvia-es-datos
Requiere AEMET_API_KEY y que exista estaciones.json (ejecutar antes ingest.catalogo).
AEMET solo da la ventana reciente (~24 h), así que se ejecuta cada hora con solape y se
deduplica por (estacion, fecha_utc).
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .common import aemet_get, cargar_config, escribir_json, leer_json

COLUMNAS = ["estacion", "fecha_utc", "prec_mm", "origen"]


def a_dataframe(observaciones, ids_validos):
    filas = []
    for o in observaciones:
        if o.get("idema") not in ids_validos or not o.get("fint"):
            continue
        prec = o.get("prec")
        filas.append({
            "estacion": o["idema"],
            "fecha_utc": pd.Timestamp(o["fint"], tz="UTC"),
            "prec_mm": float(prec) if prec not in (None, "") else float("nan"),
            "origen": "tiempo_real",
        })
    return pd.DataFrame(filas, columns=COLUMNAS)


def _ruta_mes(data_dir, anio, mes):
    return Path(data_dir) / "horario" / f"{anio:04d}" / f"{mes:02d}.parquet"


def fusionar(data_dir, df_nuevo):
    """Añade filas a los Parquet mensuales; las nuevas pisan a las antiguas del mismo (estacion, hora)."""
    if df_nuevo.empty:
        return 0
    df_nuevo = df_nuevo.assign(anio=df_nuevo.fecha_utc.dt.year, mes=df_nuevo.fecha_utc.dt.month)
    total = 0
    for (anio, mes), grupo in df_nuevo.groupby(["anio", "mes"]):
        ruta = _ruta_mes(data_dir, anio, mes)
        grupo = grupo[COLUMNAS]
        if ruta.exists():
            actual = pd.read_parquet(ruta)
            grupo = pd.concat([actual, grupo], ignore_index=True)
        grupo = (grupo.drop_duplicates(["estacion", "fecha_utc"], keep="last")
                      .sort_values(["estacion", "fecha_utc"]).reset_index(drop=True))
        ruta.parent.mkdir(parents=True, exist_ok=True)
        grupo.to_parquet(ruta, compression="zstd", index=False)
        total += len(grupo)
    return total


def cargar_reciente(data_dir, horas, ahora):
    desde = ahora - timedelta(hours=horas)
    trozos = []
    for ref in {desde, ahora}:
        ruta = _ruta_mes(data_dir, ref.year, ref.month)
        if ruta.exists():
            trozos.append(pd.read_parquet(ruta))
    if not trozos:
        return pd.DataFrame(columns=COLUMNAS)
    df = pd.concat(trozos, ignore_index=True).drop_duplicates(["estacion", "fecha_utc"], keep="last")
    return df[(df.fecha_utc > desde) & (df.fecha_utc <= ahora)]


def _acumulado(serie, horas, ahora):
    desde = ahora - timedelta(hours=horas)
    sub = serie[serie.fecha_utc > desde]
    validos = sub.prec_mm.dropna()
    return {"mm": round(float(validos.sum()), 1), "horas_con_dato": int(len(validos))}


def construir_latest(df, ahora, horas_ventana):
    """Las ventanas (1/6/24 h) se anclan a la última observación disponible, no a la hora de
    ejecución: AEMET publica con ~1 h de retraso y, si no, la ventana de 1 h saldría vacía."""
    ref = df.fecha_utc.max() if not df.empty else pd.Timestamp(ahora)
    estaciones = {}
    for est, serie in df.sort_values("fecha_utc").groupby("estacion"):
        estaciones[est] = {
            "acumulado": {"1h": _acumulado(serie, 1, ref), "6h": _acumulado(serie, 6, ref),
                          "24h": _acumulado(serie, 24, ref)},
            "serie": [{"t": r.fecha_utc.strftime("%Y-%m-%dT%H:%MZ"),
                       "mm": None if pd.isna(r.prec_mm) else r.prec_mm}
                      for r in serie.itertuples()],
        }
    return {"generado_utc": ahora.strftime("%Y-%m-%dT%H:%MZ"),
            "ultima_obs_utc": ref.strftime("%Y-%m-%dT%H:%MZ"),
            "fuente": "AEMET (citar a AEMET como autora)",
            "ventana_horas": horas_ventana, "estaciones": estaciones}


def acumulado_mes(data_dir, ref):
    """Lluvia del mes en curso (hasta `ref`, UTC) por estación, con su cobertura.
    `desde_utc` es la primera hora recogida: si es posterior al día 1, el mes no está completo."""
    ruta = _ruta_mes(data_dir, ref.year, ref.month)
    if not ruta.exists():
        return {}
    df = pd.read_parquet(ruta)
    df = df[df.fecha_utc <= ref]
    inicio = pd.Timestamp(year=ref.year, month=ref.month, day=1, tz="UTC")
    horas_mes = int((ref - inicio).total_seconds() // 3600)  # cada fila es el fin de una hora
    salida = {}
    for est, serie in df.groupby("estacion"):
        validos = serie.prec_mm.dropna()
        salida[est] = {"mm": round(float(validos.sum()), 1), "horas_con_dato": int(len(validos)),
                       "horas_mes": horas_mes,
                       "desde_utc": serie.fecha_utc.min().strftime("%Y-%m-%dT%H:%MZ")}
    return salida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    cfg = cargar_config()
    data = Path(args.data_dir)
    ids = set(leer_json(data / "estaciones.json"))

    obs = aemet_get("/observacion/convencional/todas")
    df = a_dataframe(obs, ids)
    fusionar(data, df)

    ahora = datetime.now(timezone.utc)
    reciente = cargar_reciente(data, cfg["horas_ventana"], ahora)
    latest = construir_latest(reciente, ahora, cfg["horas_ventana"])
    ref = pd.Timestamp(latest["ultima_obs_utc"])
    latest["mes"] = ref.strftime("%Y-%m")
    for est, m in acumulado_mes(data, ref).items():
        if est in latest["estaciones"]:
            latest["estaciones"][est]["mes"] = m
    escribir_json(data / "latest.json", latest)
    print(f"Observaciones recibidas: {len(obs)} | filas de Málaga: {len(df)} | "
          f"estaciones en latest: {reciente.estacion.nunique()}")


if __name__ == "__main__":
    main()
