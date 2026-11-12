"""Pruebas sin red: coordenadas, asignación municipio->estación y fusión/latest de la ingesta.
Ejecutar:  python -m tests.test_core
"""
import tempfile
from datetime import datetime, timezone

import pandas as pd

from ingest import catalogo, embalses, historico, horario
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
        assert lt["ultima_obs_utc"] == "2026-11-12T15:00Z"  # ventanas ancladas a la última observación
        m = horario.acumulado_mes(d, pd.Timestamp(lt["ultima_obs_utc"]))["A"]
        assert m["mm"] == 4.0 and m["horas_con_dato"] == 5 and m["desde_utc"] == "2026-11-12T10:00Z"
        assert m["horas_mes"] == 11 * 24 + 15  # del 1 de noviembre 00:00 a las 15:00 del día 12


def test_historico():
    assert historico.parsear_pmes("12,5") == 12.5 and historico.parsear_pmes("Ip") == 0.0
    assert historico.parsear_pmes("") is None and historico.parsear_pmes(None) is None
    regs = [{"fecha": "1996-1", "p_mes": "10.0"}, {"fecha": "1996-2", "p_mes": "Ip"},
            {"fecha": "1996-13", "p_mes": "999"}, {"fecha": "1997-12", "p_mes": "3.5"}]
    s = historico.registros_a_serie(regs)
    assert s["1996"][0] == 10.0 and s["1996"][1] == 0.0 and s["1996"][2] is None
    assert s["1997"][11] == 3.5 and historico.contar_meses(s) == 3


def test_embalses():
    html = """<html><body><table><tbody>
    <tr class="embalses-data-row"><td>16 EMBALSE DE LA CONCEPCIÓN</td><td>57.54</td><td>26.87</td><td>46.7</td><td>26.35</td><td>45.8</td><td>34.01</td><td>59.1</td><td>31.8</td></tr>
    <tr class="embalses-subtotal"><td>Total sistema Costa del Sol Occ.</td><td>57.54</td><td>26.87</td><td>46.7</td><td>26.35</td><td>45.8</td><td>34.01</td><td>59.1</td><td>31.8</td></tr>
    <tr class="embalses-data-row"><td>29 EMBALSE DEL  GUADALTEBA</td><td>153.30</td><td>143.26</td><td>93.5</td><td>142.99</td><td>93.3</td><td>77.61</td><td>50.6</td><td>n/d</td></tr>
    <tr class="embalses-data-row"><td>31 EMBALSE CONDE DE GUADALHORCE</td><td>66.49</td><td>38.42</td><td>57.8</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td></tr>
    <tr class="embalses-data-row"><td>51 EMBALSE DE RULES</td><td>105.36</td><td>90.94</td><td>86.3</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td></tr>
    </tbody></table><p>Fecha: 12/11/2026 08:00</p></body></html>"""
    d = embalses.parsear(html, {"16", "29", "31", "37"})
    assert d["fecha"] == "2026-11-12" and d["hora"] == "08:00" and set(d["embalses"]) == {"16", "29", "31"}
    assert d["embalses"]["16"]["nombre"] == "La Concepción" and d["embalses"]["16"]["pct"] == 46.7
    assert d["embalses"]["29"]["nombre"] == "Guadalteba" and d["embalses"]["29"]["promedio_8_anios_hm3"] is None
    with tempfile.TemporaryDirectory() as tmp:
        ruta = tmp + "/h.csv"
        embalses.anexar_historico(ruta, d)
        embalses.anexar_historico(ruta, d)  # idempotente por (fecha, id)
        assert len(open(ruta, encoding="utf-8").read().strip().splitlines()) == 4

    assert d["embalses"]["31"]["nombre"] == "Conde de Guadalhorce"


if __name__ == "__main__":
    for nombre, fn in list(globals().items()):
        if nombre.startswith("test_"):
            fn()
            print("OK", nombre)
