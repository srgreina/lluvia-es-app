"""Pruebas sin red: coordenadas, asignación municipio->estación y fusión/latest de la ingesta.
Ejecutar:  python -m tests.test_core
"""
import tempfile
from datetime import datetime, timezone

import pandas as pd

from ingest import catalogo, diario, embalses, historico, horario
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
        lt = horario.construir_latest(rec, ahora, 24, (1, 6, 24, 48, 168, 720))
        a = lt["estaciones"]["A"]["acumulado"]
        assert a["24h"]["horas_con_dato"] == 5 and a["24h"]["mm"] == 4.0  # 0.5+2.0+3x0.5, 11:00 sin dato
        assert a["1h"]["mm"] == 0.5
        assert set(a) == {"1h", "6h", "24h", "48h", "7d", "30d"} and a["30d"]["mm"] == 4.0
        assert horario.clave_ventana(168) == "7d" and horario.clave_ventana(720) == "30d" and horario.clave_ventana(48) == "48h"
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


def test_diario():
    regs = [{"fecha": "2026-11-08", "prec": "5,0"}, {"fecha": "2026-11-09", "prec": "Ip"},
            {"fecha": "2026-11-10", "prec": ""}, {"fecha": "2026-11-11", "prec": "1.0"}]
    assert diario.registros_a_dias(regs) == {"2026-11-08": 5.0, "2026-11-09": 0.0, "2026-11-11": 1.0}
    hoy = datetime(2026, 11, 13, tzinfo=timezone.utc).date()
    f = diario.fusionar({"A": {"2026-11-08": 1.0, "2026-05-01": 9.0}}, {"A": {"2026-11-08": 5.0}}, hoy)
    assert f == {"A": {"2026-11-08": 5.0}}  # lo nuevo pisa a lo viejo y se purga lo antiguo
    # acumular: sin doble cómputo cuando el día completo ya viene en el dato diario
    ref = pd.Timestamp("2026-11-12T15:00", tz="UTC")
    horas = pd.date_range("2026-11-11T01:00", "2026-11-12T15:00", freq="h", tz="UTC")
    serie = pd.DataFrame({"estacion": "A", "fecha_utc": horas, "prec_mm": 0.5, "origen": "x"})
    solo_h = horario.acumular(serie, ref - pd.Timedelta(hours=168), ref)
    assert solo_h["horas_con_dato"] == len(horas) and solo_h["mm"] == round(0.5 * len(horas), 1)
    dias = {"2026-11-05": 7.0,   # día que empieza antes de la ventana: no entra
            "2026-11-08": 5.0, "2026-11-09": 2.0, "2026-11-11": 10.0}  # el 11 ya está en las horas
    r = horario.acumular(serie, ref - pd.Timedelta(hours=168), ref, dias)
    horas_12 = 15   # 12 de noviembre, de 01:00 a 15:00
    assert r["horas_con_dato"] == 24 * 3 + horas_12
    assert r["mm"] == round(5.0 + 2.0 + 10.0 + 0.5 * horas_12, 1)
    assert r["desde"] == pd.Timestamp("2026-11-08", tz="UTC")
    # el día 11 de noviembre cerrado a las 00:00 del 12 pertenece al día 11
    assert horario._dia_de(pd.Timestamp("2026-11-12T00:00", tz="UTC")) == "2026-11-11"
    lt = horario.construir_latest(serie, ref + pd.Timedelta(minutes=30), 24, (1, 24, 168), {"A": dias})
    assert lt["estaciones"]["A"]["acumulado"]["24h"]["mm"] == 12.0   # <48 h: solo horario
    assert lt["estaciones"]["A"]["acumulado"]["7d"]["mm"] == r["mm"]
    with tempfile.TemporaryDirectory() as d:
        horario.fusionar(d, serie.assign(origen="tiempo_real"))
        m = horario.acumulado_mes(d, ref, {"A": {"2026-11-01": 3.0, "2026-11-02": 4.0, "2026-11-11": 10.0}})["A"]
        assert m["desde_utc"] == "2026-11-01T00:00Z" and m["horas_con_dato"] == 48 + 24 + 15
        assert m["mm"] == round(3.0 + 4.0 + 10.0 + 0.5 * 15, 1)


def test_aviso_diario():
    assert diario.evaluar(40, 25, 0) is None
    assert diario.evaluar(40, 10, 5) is None            # muchas estaciones sin serie (404) es normal
    assert diario.evaluar(40, 0, 0) is not None          # no llegó nada
    assert diario.evaluar(40, 10, 25) is not None        # la API falló en más de la mitad


def test_frontend_cobertura():
    """Una ventana de 48 h o más con menos del 90 % de horas con dato no puede mostrarse como cifra."""
    import re
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which("node"):
        return
    html = (Path(__file__).resolve().parent.parent / "docs" / "index.html").read_text(encoding="utf-8")
    fn = html[html.index("function accRaw"):html.index("/* ---------- escala de color")]
    wins = re.search(r"const WINDOWS = \{.*?\n\};", html, re.S).group(0)
    wins = re.sub(r"th: \[[^\]]*\]", "", wins)
    prog = wins + "\nconst S = {win: '30d', latest: {estaciones: {A: {acumulado: {" \
        "'30d': {mm: 0, horas_con_dato: 36}, '7d': {mm: 3, horas_con_dato: 160}, '24h': {mm: 1, horas_con_dato: 24}," \
        " '48h': {mm: 2, horas_con_dato: 36}}}}}};\n" + fn + \
        "\nconsole.log(JSON.stringify([acc('A','30d'), acc('A','7d') && acc('A','7d').mm, acc('A','24h').mm, acc('A','48h')," \
        " accRaw('A','30d').horas_con_dato]));"
    out = subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[null,3,1,null,36]", out


def test_sustitutos():
    est = {"P": {"lat": 36.7075, "lon": -4.4272, "nombre": "PUERTO"},
           "C": {"lat": 36.7178, "lon": -4.4817, "nombre": "CENTRO"},
           "L": {"lat": 37.17, "lon": -4.15, "nombre": "LEJOS"}}
    s = diario.elegir_sustitutos(est, {"C"}, 15)
    assert s == {"P": {"estacion": "C", "nombre": "CENTRO", "distancia_km": s["P"]["distancia_km"]}} and 4 < s["P"]["distancia_km"] < 6
    assert "L" not in s                                  # fuera de radio: sin sustituto
    assert diario.elegir_sustitutos(est, {"C", "P"}, 15).get("P") is None   # si publica la propia, no hay sustituto
    ef, usados = horario.dias_efectivos({"C": {"2026-11-01": 1.0}}, s)
    assert ef["P"] == {"2026-11-01": 1.0} and usados["P"]["estacion"] == "C"
    ef, usados = horario.dias_efectivos({"C": {"x": 1}, "P": {"x": 2}}, s)
    assert ef["P"] == {"x": 2} and usados == {}


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
