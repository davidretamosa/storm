"""Tráfico habitual (cadena T-1 de la capa de IA). T-1.1: las pausas netas que ya hace build_think_times."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

from bench.tests.support import INPUTS, generate, sha256
from log_parser.parser import parse_logs
from traffic_model.payloads import build_path_params
from traffic_model.status_filter import successful_rows
from traffic_model.think_time import build_think_times

# src/2-processing, para leer los logs de ejemplo desde cualquier carpeta
ROOT = Path(__file__).resolve().parents[1]
SAMPLE_LOG = ROOT / "samples" / "access_sample.log"
BANKAPP_LOG = ROOT.parent / "1-input" / "java-app-mock" / "logs" / "bankapp.jsonl"

# Instante de referencia de las tablas sintéticas: "second" cuenta los segundos desde aquí
ORIGIN = pd.Timestamp("2026-01-01T00:00:00Z")


def steps_table(rows):
    """Tabla de peticiones sintética, con las columnas que lee build_think_times.

    Cada fila es un diccionario con "second" (segundos desde ORIGIN) y "endpoint" (p. ej. "/a"),
    obligatorios, y opcionalmente "session", "method", "duration" y "kind"
    (por defecto "s", "GET", None y "end"). Para una fila sin sesión o sin tipo,
    se pasa None de forma explícita.
    """
    defaults = {"session": "s", "method": "GET", "duration": None, "kind": "end"}
    filled = [{**defaults, **row} for row in rows]
    return pd.DataFrame({
        "session_id": [row["session"] for row in filled],
        "timestamp": pd.to_datetime(
            [ORIGIN + pd.Timedelta(seconds=row["second"]) for row in filled], utc=True
        ),
        "method": [row["method"] for row in filled],
        "endpoint": [row["endpoint"] for row in filled],
        "duration_ms": pd.Series([row["duration"] for row in filled], dtype=float),
        "timestamp_kind": [row["kind"] for row in filled],
    })


def pause(df, source="GET /a", target="GET /b"):
    """Pausas (cuantiles) de la transición source -> target, con 2 muestras."""
    return build_think_times(df, samples=2)[source][target]


def test_net_pause_start_then_end():
    # Inicio de /a + su duración = fin de /a; fin de /b - su duración = inicio de /b
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 200, "kind": "start"},
        {"second": 2, "endpoint": "/b", "duration": 300},
    ])
    assert pause(df) == [1500, 1500]


def test_net_pause_end_then_start():
    # Fin de /a e inicio de /b: el hueco ya es la pausa, no se resta nada
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 200},
        {"second": 2, "endpoint": "/b", "duration": 300, "kind": "start"},
    ])
    assert pause(df) == [2000, 2000]


def test_net_pause_uses_the_next_request_of_the_same_session():
    # Las sesiones se cruzan en el tiempo: cada pausa resta la duración de la siguiente de SU sesión
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 100},
        {"second": 1, "endpoint": "/x", "duration": 900, "session": "t"},
        {"second": 2, "endpoint": "/b", "duration": 300},
        {"second": 5, "endpoint": "/y", "duration": 50, "session": "t"},
    ])
    think = build_think_times(df, samples=2)
    assert think["GET /a"]["GET /b"] == [1700, 1700]
    assert think["GET /x"]["GET /y"] == [3950, 3950]


def test_net_pause_negative_duration_does_not_lengthen():
    # Una duración negativa cuenta como 0: no alarga la pausa
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 200},
        {"second": 2, "endpoint": "/b", "duration": -500},
    ])
    assert pause(df) == [2000, 2000]


def test_net_pause_missing_duration_subtracts_nothing():
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 200},
        {"second": 2, "endpoint": "/b"},
    ])
    assert pause(df) == [2000, 2000]


def test_net_pause_is_never_negative():
    # La duración de /b es mayor que el hueco: la pausa se queda en 0
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 200},
        {"second": 2, "endpoint": "/b", "duration": 5000},
    ])
    assert pause(df) == [0, 0]


def test_net_pause_unknown_kind_subtracts_nothing():
    # Sin saber si la hora es de inicio o de fin, no se corrige el hueco
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 200, "kind": None},
        {"second": 2, "endpoint": "/b", "duration": 300, "kind": None},
    ])
    assert pause(df) == [2000, 2000]


def test_net_pause_is_capped_after_subtracting():
    # 300000 - 300 = 299700, que sigue por encima del tope de 120 s
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 200},
        {"second": 300, "endpoint": "/b", "duration": 300},
    ])
    assert pause(df) == [120000, 120000]


def test_net_pause_unsorted_input():
    # Las filas llegan desordenadas: se ordenan por hora antes de calcular el hueco
    df = steps_table([
        {"second": 2, "endpoint": "/b", "duration": 300},
        {"second": 0, "endpoint": "/a", "duration": 200},
    ])
    assert pause(df) == [1700, 1700]


def test_net_pause_ignores_rows_without_session():
    # La petición sin sesión no se mete entre /a y /b
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 200},
        {"second": 1, "endpoint": "/z", "duration": 999, "session": None},
        {"second": 2, "endpoint": "/b", "duration": 300},
    ])
    assert pause(df) == [1700, 1700]


def test_net_pause_without_duration_column():
    # Control negativo: sin la columna de duración no hay corrección
    df = steps_table([
        {"second": 0, "endpoint": "/a"},
        {"second": 2, "endpoint": "/b"},
    ]).drop(columns=["duration_ms"])
    assert pause(df) == [2000, 2000]


@pytest.mark.parametrize("kind, expected", [
    (None, [1700, 1700]),         # sin timestampKind: el formato del banco es de fin
    ("end", [1700, 1700]),
    ("start", [1800, 1800]),
    ("unknown", [2000, 2000]),
])
def test_net_pause_from_a_jsonl_log(tmp_path, kind, expected):
    # Control positivo de punta a punta: del .jsonl a la pausa, pasando por parse_logs
    lines = []
    for timestamp, endpoint, duration in [
        ("2026-10-01T09:00:00.000Z", "/a", 200),
        ("2026-10-01T09:00:02.000Z", "/b", 300),
    ]:
        entry = {
            "timestamp": timestamp,
            "sessionId": "s",
            "method": "GET",
            "endpoint": endpoint,
            "path": endpoint,
            "status": 200,
            "durationMs": duration,
        }
        if kind is not None:
            entry["timestampKind"] = kind
        lines.append(json.dumps(entry))
    log_file = tmp_path / "pausas.jsonl"
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert pause(parse_logs(log_file)) == expected


def test_net_pause_missing_current_duration_subtracts_nothing():
    # La hora de /a es de inicio pero no se sabe su duración: cuenta como 0
    df = steps_table([
        {"second": 0, "endpoint": "/a", "kind": "start"},
        {"second": 2, "endpoint": "/b", "duration": 300, "kind": "start"},
    ])
    assert pause(df) == [2000, 2000]


def test_net_pause_uses_the_next_kind_of_the_same_session():
    # La fila siguiente en el tiempo es de la sesión t (inicio), pero la siguiente
    # de la sesión s es /b (fin): se descuenta la duración de /b
    df = steps_table([
        {"second": 0, "endpoint": "/a", "duration": 100},
        {"second": 1, "endpoint": "/x", "duration": 900, "session": "t", "kind": "start"},
        {"second": 2, "endpoint": "/b", "duration": 300},
        {"second": 5, "endpoint": "/y", "duration": 50, "session": "t", "kind": "start"},
    ])
    think = build_think_times(df, samples=2)
    assert think["GET /a"]["GET /b"] == [1700, 1700]
    assert think["GET /x"]["GET /y"] == [3100, 3100]


def test_net_pause_from_an_otel_log_with_start_time(tmp_path):
    # OTel con startTimeUnixNano: la hora es de inicio, se descuenta la duración de /a
    start = pd.Timestamp("2026-10-01T09:00:00Z").value  # nanosegundos Unix
    lines = []
    for offset_ms, endpoint, duration_ms in [(0, "/a", 200), (2000, "/b", 300)]:
        begin = start + offset_ms * 1_000_000
        lines.append(json.dumps({
            "startTimeUnixNano": str(begin),
            "endTimeUnixNano": str(begin + duration_ms * 1_000_000),
            "attributes": {
                "http.request.method": "GET",
                "http.route": endpoint,
                "session.id": "s",
            },
        }))
    log_file = tmp_path / "pausas_otel.jsonl"
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    df = parse_logs(log_file)
    assert list(df["timestamp_kind"]) == ["start", "start"]
    assert pause(df) == [1800, 1800]


# ---------------------------------------------------------------------------
# T-1.2: los {id} de las rutas, solo de las peticiones 2xx (--habitual-traffic)
# ---------------------------------------------------------------------------

# sha256 de traffic_model/status_filter.py: el T-3.1 crea el mismo archivo, byte a byte
STATUS_FILTER_SHA256 = "e852d5396d13a7c5ab50430499bdb2f99d8c61cff4768842a49e4e6855f04005"


def requests_table(rows):
    """Tabla de peticiones sintética: cada fila es (method, endpoint, path, status).

    La columna `status` es numérica, como la deja parse_logs (un None queda como NaN).
    """
    df = pd.DataFrame(rows, columns=["method", "endpoint", "path", "status"])
    df["status"] = pd.to_numeric(df["status"], errors="coerce")
    return df


def split_plan(path):
    """Separa un .jmx en (resto, modelos): el texto del plan sin los modelos y los modelos.

    En cada script Groovy con el modelo incrustado (parseText('''...''')), el JSON se deshace
    (al revés que jmx_generator/generator.py), se carga con json.loads y en el texto queda __MODEL__.
    """
    root = ET.parse(path).getroot()
    models = []
    for prop in root.iter("stringProp"):
        if prop.get("name") != "script" or not prop.text or "parseText('''" not in prop.text:
            continue
        head, tail = prop.text.split("parseText('''", 1)
        embedded, after = tail.split("''')", 1)
        models.append(json.loads(embedded.replace("\\'\\'\\'", "'''").replace("\\\\", "\\")))
        prop.text = head + "parseText('''__MODEL__''')" + after
    return ET.tostring(root, encoding="unicode"), models


def test_successful_rows_keeps_2xx_and_unknown():
    # Los límites del rango 2xx: 199 y 300-303 tampoco son respuestas buenas
    statuses = [199, 200, 204, 299, 300, 301, 302, 303, 304, 400, 404, 500, None]
    df = requests_table([("GET", "/a", "/a", s) for s in statuses])
    kept = successful_rows(df)["status"].tolist()
    assert kept[:3] == [200, 204, 299]
    assert len(kept) == 4 and pd.isna(kept[3])


def test_successful_rows_without_status_returns_the_log():
    # Control negativo: si no hay códigos de respuesta, no se filtra nada (mismo objeto)
    without_column = pd.DataFrame({"method": ["GET"], "endpoint": ["/a"], "path": ["/a"]})
    assert successful_rows(without_column) is without_column
    empty_column = requests_table([("GET", "/a", "/a", None), ("GET", "/b", "/b", None)])
    assert successful_rows(empty_column) is empty_column
    assert successful_rows(None) is None


def test_successful_rows_does_not_change_its_input():
    df = requests_table([("GET", "/a", "/a", 200), ("GET", "/a", "/a", 500), ("GET", "/a", "/a", None)])
    before = df.copy()
    successful_rows(df)
    pd.testing.assert_frame_equal(df, before)


def test_status_filter_is_the_shared_file():
    content = (ROOT / "traffic_model" / "status_filter.py").read_bytes()
    assert hashlib.sha256(content).hexdigest() == STATUS_FILTER_SHA256


def test_path_params_only_2xx_drops_failed_ids():
    df = requests_table([("GET", "/a/{id}", "/a/1", 200), ("GET", "/a/{id}", "/a/2", 404)])
    assert build_path_params(df, only_2xx=True)["GET /a/{id}"]["id"] == [["1", 1.0]]
    assert build_path_params(df, only_2xx=False)["GET /a/{id}"]["id"] == [["1", 0.5], ["2", 0.5]]


def test_path_params_only_2xx_304_is_a_failure():
    # Para aprender ids, un 304 no cuenta como respuesta buena
    df = requests_table([("GET", "/a/{id}", "/a/1", 200), ("GET", "/a/{id}", "/a/2", 304)])
    assert build_path_params(df, only_2xx=True)["GET /a/{id}"]["id"] == [["1", 1.0]]


def test_path_params_only_2xx_keeps_lines_without_status():
    # Sin código no se sabe si falló: la línea se queda
    df = requests_table([
        ("GET", "/a/{id}", "/a/1", 200),
        ("GET", "/a/{id}", "/a/2", None),
        ("GET", "/a/{id}", "/a/3", 404),
    ])
    assert build_path_params(df, only_2xx=True)["GET /a/{id}"]["id"] == [["1", 0.5], ["2", 0.5]]


def test_path_params_only_2xx_keeps_a_request_without_any_2xx():
    # Si ninguna línea de la petición es 2xx, se queda entera (si no, desaparecería del plan).
    # Hay otras peticiones con 2xx (una con la misma ruta y otro método): la regla es por
    # petición, no sobre el log entero, y cada petición aprende solo de sus líneas
    df = requests_table([
        ("POST", "/b/{id}", "/b/1", 400),
        ("POST", "/b/{id}", "/b/2", 400),
        ("GET", "/b/{id}", "/b/7", 200),
        ("GET", "/c", "/c", 200),
    ])
    params = build_path_params(df, only_2xx=True)
    assert params["POST /b/{id}"]["id"] == [["1", 0.5], ["2", 0.5]]
    assert params["GET /b/{id}"]["id"] == [["7", 1.0]]


def test_path_params_only_2xx_on_the_sample_log():
    # Control positivo: en el log de ejemplo, 3 retiradas con 400 dejan de contar
    df = parse_logs(SAMPLE_LOG)
    request = "POST /api/accounts/{id}/withdraw"
    everything = build_path_params(df, only_2xx=False)[request]["id"]
    assert [value for value, _ in everything] == ["5", "4", "2"]
    assert [p for _, p in everything] == pytest.approx([2 / 3, 2 / 9, 1 / 9])
    accepted = dict(build_path_params(df, only_2xx=True)[request]["id"])
    assert accepted == pytest.approx({"5": 2 / 3, "2": 1 / 6, "4": 1 / 6})


@pytest.mark.parametrize("log_file", [SAMPLE_LOG, BANKAPP_LOG], ids=["sample", "bankapp"])
def test_path_params_default_is_unchanged(log_file):
    df = parse_logs(log_file)
    assert build_path_params(df) == build_path_params(df, only_2xx=False)


@pytest.mark.parametrize("name", ["logs", "logs+jar", "logs+jar+session", "bankapp+session"])
def test_flag_changes_only_path_params(tmp_path, name):
    plain = generate(INPUTS[name], tmp_path / "sin.jmx")
    habitual = generate(INPUTS[name] + ["--habitual-traffic"], tmp_path / "con.jmx")
    plain_rest, plain_models = split_plan(plain)
    habitual_rest, habitual_models = split_plan(habitual)

    # (a) sin los modelos, el plan es idéntico
    assert plain_models and len(plain_models) == len(habitual_models)
    assert plain_rest == habitual_rest
    for before, after in zip(plain_models, habitual_models):
        # (b) los modelos solo difieren en path_params
        assert set(before) == set(after)
        assert {key for key in before if before[key] != after[key]} == {"path_params"}
        # (c) y path_params sí cambia
        assert before["path_params"] != after["path_params"]


def test_flag_without_logs_changes_nothing(tmp_path):
    plain = generate(INPUTS["jar"], tmp_path / "sin.jmx")
    habitual = generate(INPUTS["jar"] + ["--habitual-traffic"], tmp_path / "con.jmx")
    assert sha256(plain) == sha256(habitual)
