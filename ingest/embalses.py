"""Embalses de la provincia: volumen diario desde el informe público de SAIH Hidrosur.

Uso:  python -m ingest.embalses --data-dir ../lluvia-es-datos
No hay API ni licencia expresa de reutilización: se lee la tabla HTML del informe una vez al día,
se cita la fuente y se avisa de que los datos no están verificados ni tienen valor oficial.
Escribe embalses.json (último dato) y embalses/historico.csv (una fila por embalse y día).
"""
import argparse
import csv
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .common import cargar_config, escribir_json

URL = "https://www.redhidrosurmedioambiente.es/saih/informe/embalses"
UA = "lluvia-es-app (https://github.com/srgreina/lluvia-es-app; uso personal, una consulta al día)"
CAMPOS = ["capacidad_hm3", "volumen_hm3", "pct", "volumen_sem_ant_hm3", "pct_sem_ant",
          "volumen_anio_ant_hm3", "pct_anio_ant", "promedio_8_anios_hm3"]


def _num(txt):
    try:
        return float(txt.strip().replace(",", "."))
    except ValueError:
        return None  # "n/d" u otros


def parsear(html, ids):
    """HTML del informe -> {'fecha': 'AAAA-MM-DD', 'hora': 'HH:MM', 'embalses': {id: {...}}}."""
    sopa = BeautifulSoup(html, "html.parser")
    m = re.search(r"Fecha:\s*(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})", sopa.get_text(" "))
    if not m:
        raise ValueError("No se encuentra la fecha del informe")
    salida = {}
    for fila in sopa.select("tr.embalses-data-row"):
        celdas = [c.get_text(" ", strip=True) for c in fila.find_all("td")]
        mm = re.match(r"(\d+)\s+(.*)", celdas[0]) if celdas else None
        if not mm or mm.group(1) not in ids or len(celdas) < 9:
            continue
        d = {k: _num(v) for k, v in zip(CAMPOS, celdas[1:9])}
        d["nombre"] = re.sub(r"^EMBALSE\s+(DE LA|DEL|DE)?\s*", "", re.sub(r"\s+", " ", mm.group(2))).title()
        salida[mm.group(1)] = d
    return {"fecha": f"{m.group(3)}-{m.group(2)}-{m.group(1)}", "hora": m.group(4), "embalses": salida}


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=3, min=3, max=40),
       retry=retry_if_exception_type(requests.RequestException), reraise=True)
def descargar():
    r = requests.get(URL, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def anexar_historico(ruta, datos):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    existentes = set()
    if ruta.exists():
        with open(ruta, encoding="utf-8", newline="") as f:
            existentes = {(r["fecha"], r["id"]) for r in csv.DictReader(f)}
    nuevo = not ruta.exists()
    with open(ruta, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["fecha", "id", "volumen_hm3", "pct"])
        for eid, e in sorted(datos["embalses"].items()):
            if (datos["fecha"], eid) not in existentes:
                w.writerow([datos["fecha"], eid, e["volumen_hm3"], e["pct"]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    ids = {str(i) for i in cargar_config()["embalses"]}
    datos = parsear(descargar(), ids)
    faltan = ids - set(datos["embalses"])
    if faltan:
        raise SystemExit(f"Embalses no encontrados en el informe: {sorted(faltan)}")
    datos["fuente"] = "SAIH Hidrosur (Junta de Andalucía). Datos de estaciones automáticas, no verificados y sin valor oficial."
    datos["fuente_url"] = URL
    out = Path(args.data_dir)
    escribir_json(out / "embalses.json", datos)
    anexar_historico(out / "embalses" / "historico.csv", datos)
    print(f"Embalses: {len(datos['embalses'])} | dato del {datos['fecha']} {datos['hora']}")


if __name__ == "__main__":
    main()
