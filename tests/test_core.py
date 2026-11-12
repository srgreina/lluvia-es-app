"""Pruebas sin red: coordenadas, asignación municipio->estación y fusión/latest de la ingesta.
Ejecutar:  python -m tests.test_core
"""
import tempfile
from datetime import datetime, timezone

import pandas as pd

from ingest import catalogo, horario
from ingest.common import dms_a_decimal, haversine_km


def test_dms():
    assert abs(dms_a_decimal("364825N") - 36.80694) < 1e-4
    assert abs(dms_a_decimal("043520W") - (-4.58889)) < 1e-4


def test_haversine():
    assert abs(haversine_km(36.72, -4.42, 36.72, -4.42)) < 1e-9
    assert 1.0 < haversine_km(36.72, -4.42, 36.73, -4.42) < 1.2


def test_asignacion():
    muns = [{"ine": "29067", "nombre": "Málaga", "lat": 36.72, "lon": -4.42},
            {"ine": "29901", "nombre": "Pueblo", "lat": 36.90, "lon": -4.90}]
    est = {"A": {"id": "A", "nombre": "MALAGA AEROPUERTO", "lat": 36.67, "lon": -4.49},
           "B": {"id": "B", "nombre": "OTRA", "lat": 37.40, "lon": -5.90}}
    a = catalogo.asignar(muns, est, 15)
    assert a["29067"]["estacion"] == "A" and a["29067"]["propia"] is True
    assert a["29901"]["orientativo"] is True and a["29901"]["propia"] is False


def test_fusion_y_latest():
    ahora = datetime(2026, 11, 12, 15, 30, tzinfo=timezone.utc)
    obs = [{"idema": "A", "fint": f"2026-11-12T{h:02d}:00:00", "prec": 0.5} for h in range(10, 16)]
    obs += [{"idema": "A", "fint": "2026-11-12T12:00:00", "prec": 2.0},   # duplicado: gana el último
            {"idema": "X", "fint": "2026-11-12T12:00:00", "prec": 9.0},   # fuera de catálogo
            {"idema": "A", "fint": "2026-11-12T11:00:00", "prec": None}]  # sin dato -> NaN
    df = horario.a_dataframe(obs, {"A"})
    with tempfile.TemporaryDirectory() as d:
        horario.fusionar(d, df)
        horario.fusionar(d, df)  # idempotente
        rec = horario.cargar_reciente(d, 24, ahora)
        assert len(rec) == 6 and set(rec.estacion) == {"A"}
        lt = horario.construir_latest(rec, ahora, 24)
        a = lt["estaciones"]["A"]["acumulado"]
        assert a["24h"]["horas_con_dato"] == 5 and a["24h"]["mm"] == 4.0  # 0.5+2.0+3x0.5, 11:00 sin dato
        assert a["1h"]["mm"] == 0.5


if __name__ == "__main__":
    for nombre, fn in list(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK", nombre)
