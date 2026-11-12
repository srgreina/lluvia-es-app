"""Utilidades compartidas: cliente AEMET OpenData, coordenadas y distancias."""
import json
import math
import os
import re
import unicodedata
from pathlib import Path

import requests
import yaml
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

BASE = "https://opendata.aemet.es/opendata/api"
RAIZ = Path(__file__).resolve().parent.parent


class AemetError(Exception):
    """Error reintentable (429, estado != 200, respuesta vacía)."""


class SinDatos(Exception):
    """AEMET responde 404: no hay datos para esos criterios (no se reintenta)."""


def cargar_config():
    with open(RAIZ / "config.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalizar(texto):
    """Mayúsculas y sin tildes, para comparar nombres de provincia."""
    t = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").upper().strip()


def _decodificar(contenido):
    for enc in ("utf-8", "latin-1"):
        try:
            return json.loads(contenido.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise AemetError("Respuesta de datos no es JSON válido")


@retry(stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=2, min=2, max=60),
       retry=retry_if_exception_type((requests.RequestException, AemetError)),
       reraise=True)
def aemet_get(ruta):
    """Llamada en dos pasos de AEMET: la API devuelve una URL con los datos."""
    clave = os.environ.get("AEMET_API_KEY")
    if not clave:
        raise SystemExit("Falta la variable de entorno AEMET_API_KEY")
    r = requests.get(BASE + ruta, headers={"api_key": clave, "accept": "application/json"},
                     timeout=30)
    if r.status_code == 429:
        raise AemetError("429 rate limit")
    if r.status_code == 404:
        raise SinDatos(ruta)
    r.raise_for_status()
    meta = r.json()
    if meta.get("estado") == 404:
        raise SinDatos(meta.get("descripcion") or ruta)
    if meta.get("estado") != 200 or not meta.get("datos"):
        raise AemetError(f"estado={meta.get('estado')} descripcion={meta.get('descripcion')}")
    d = requests.get(meta["datos"], timeout=60)
    if d.status_code == 429:
        raise AemetError("429 rate limit en datos")
    d.raise_for_status()
    return _decodificar(d.content)


def dms_a_decimal(valor):
    """'364825N' / '043520W' (DDMMSS + hemisferio) -> grados decimales."""
    s = str(valor).strip().upper()
    m = re.fullmatch(r"(\d+)([NSEW])", s)
    if not m:
        raise ValueError(f"Coordenada DMS no válida: {valor!r}")
    digitos, hemisferio = m.groups()
    seg = int(digitos[-2:])
    minutos = int(digitos[-4:-2])
    grados = int(digitos[:-4] or 0)
    dec = grados + minutos / 60 + seg / 3600
    return -dec if hemisferio in "SW" else dec


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def escribir_json(ruta, objeto):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def leer_json(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)
