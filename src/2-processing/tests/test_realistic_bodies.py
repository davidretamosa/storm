"""Tests del flag --realistic-bodies (capa de IA, cadena T-3).

Cada subparte de la cadena añade aquí su sección.
"""
import hashlib
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

from jar_parser.parser import parse_jar
from log_parser.parser import COLUMNS, parse_logs
from traffic_model.payloads import build_body_models
from traffic_model.status_filter import successful_rows

ROOT = Path(__file__).resolve().parents[1]   # src/2-processing
LOG = "samples/access_sample.log"
JAR = "samples/demo-bankapp.jar"
WITHDRAW = "POST /api/accounts/{id}/withdraw"


def frame(rows):
    """DataFrame con las columnas de parse_logs; cada fila es un dict con las columnas que hagan falta."""
    return pd.DataFrame(rows, columns=list(COLUMNS.values()))


def row(status, body, method="POST", endpoint="/api/transfers"):
    return {"method": method, "endpoint": endpoint, "path": endpoint, "status": status, "body": body}


# ---------------------------------------------------------------------------
# Sección 1 · 2xx (T-3.1): el modelo de los bodies sale solo de las peticiones 2xx
# ---------------------------------------------------------------------------

# El filtro compartido con el T-1.2: tiene que ser este texto, byte a byte
STATUS_FILTER_TEXT = '''"""Filtro de peticiones por código de respuesta HTTP."""


def successful_rows(df):
    """Filas que la aplicación aceptó (2xx) y filas sin código de respuesta.

    Si el log no tiene la columna `status`, o la tiene vacía, lo devuelve tal cual.
    """
    if df is None or df.empty or "status" not in df.columns or df["status"].isna().all():
        return df
    status = df["status"]
    return df[status.isna() | ((status >= 200) & (status < 300))]
'''


def test_successful_rows_keeps_2xx_and_rows_without_status():
    df = frame([row(s, {"a": 1}) for s in (200, 201, 299, 300, 400, 500, np.nan)])
    kept = successful_rows(df)["status"].tolist()
    assert kept[:3] == [200, 201, 299]
    assert len(kept) == 4 and pd.isna(kept[3])


def test_successful_rows_returns_the_same_object_without_status():
    empty = frame([])
    no_column = pd.DataFrame([{"method": "POST", "endpoint": "/x", "body": {"a": 1}}])
    all_nan = frame([row(np.nan, {"a": 1}), row(np.nan, {"a": 2})])
    assert successful_rows(None) is None
    for df in (empty, no_column, all_nan):
        assert successful_rows(df) is df


def test_status_filter_is_the_shared_file():
    path = ROOT / "traffic_model" / "status_filter.py"
    expected = hashlib.sha256(STATUS_FILTER_TEXT.encode("utf-8")).hexdigest()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_only_2xx_narrows_the_numeric_range():
    # Control positivo: en access_sample.log, 3 de los 9 retiros son 400 y llevan los importes grandes
    bodies = build_body_models(parse_logs(LOG), only_2xx=True)
    assert bodies[WITHDRAW]["amount"]["max"] == 188.05


def test_without_only_2xx_the_range_is_the_team_one():
    # Control negativo: sin el parámetro, el modelo de siempre (todas las filas)
    df = parse_logs(LOG)
    default = build_body_models(df)
    off = build_body_models(df, only_2xx=False)
    assert default[WITHDRAW]["amount"]["max"] == 4917.51
    assert default == off


def test_a_request_with_only_failed_bodies_keeps_its_model():
    df = frame([
        row(201, {"amount": 10}),
        row(400, {"code": "x"}, endpoint="/api/loans"),
        row(400, {"code": "y"}, endpoint="/api/loans"),
    ])
    with_flag = build_body_models(df, only_2xx=True)
    assert with_flag["POST /api/loans"] == build_body_models(df)["POST /api/loans"]


def test_empty_successes_and_failed_bodies_keep_the_full_model():
    # Las 2xx solo llevan {}: el modelo es el de todas las filas, no {}
    df = frame([row(201, {}), row(201, {}), row(400, {"amount": 5000}), row(400, {"amount": 7000})])
    with_flag = build_body_models(df, only_2xx=True)
    assert with_flag == build_body_models(df)
    assert with_flag["POST /api/transfers"] != {}


def test_the_set_of_requests_with_body_does_not_change():
    df = parse_logs(LOG)
    endpoints = parse_jar(JAR)
    on = build_body_models(df, endpoints, only_2xx=True)
    off = build_body_models(df, endpoints, only_2xx=False)
    assert set(on) == set(off)
    # Sin el .jar también: el DTO no puede tapar una petición que se haya perdido por el filtro
    assert set(build_body_models(df, only_2xx=True)) == set(build_body_models(df))


def test_presence_comes_from_the_2xx_bodies():
    df = frame([
        row(201, {"amount": 10, "concept": "luz"}),
        row(201, {"amount": 20}),
        row(400, {"amount": 9000}),
        row(400, {"amount": 9500}),
    ])
    fields = build_body_models(df, only_2xx=True)["POST /api/transfers"]
    assert fields["concept"]["presence"] == 0.5
    assert fields["amount"]["max"] == 20


def test_reference_log_does_not_change():
    # En el log de referencia todas las peticiones son 2xx: por eso el banco no puede enseñar esta subparte
    log = Path(__file__).parents[1] / "bench/data/bankapp_vall_pic_3h.jsonl"
    df = parse_logs(str(log))
    assert build_body_models(df, only_2xx=True) == build_body_models(df)


def markov_script(plan):
    """El script del JSR223PostProcessor «Elegir siguiente petición (Markov)», ya sin escapes XML."""
    tree = ET.parse(plan)
    for node in tree.iter("JSR223PostProcessor"):
        if node.get("testname") == "Elegir siguiente petición (Markov)":
            for prop in node.iter("stringProp"):
                if prop.get("name") == "script":
                    return prop.text
    raise AssertionError("no está el script de Markov en el plan")


def generate(args, output):
    """`python main.py <args> --output <output>` en un subproceso con PYTHONHASHSEED=0 (como bench/tests)."""
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    command = [sys.executable, "main.py", *args, "--output", str(output)]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return output


def test_main_with_the_flag_uses_the_2xx_model(tmp_path):
    off = markov_script(generate(["--logs", LOG], tmp_path / "off.jmx"))
    on = markov_script(generate(["--logs", LOG, "--realistic-bodies"], tmp_path / "on.jmx"))
    # El modelo va en compacto (separators=(",", ":")), como lo escribe generator.py
    assert '"max":4917.51' in off
    assert '"max":188.05' in on
    assert "4917.51" not in on
