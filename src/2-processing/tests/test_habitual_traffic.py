"""Tráfico habitual (cadena T-1 de la capa de IA). T-1.1: las pausas netas que ya hace build_think_times."""
import hashlib
import json
import re
import socket
from datetime import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import pytest

import bench.jmeter
from bench.tests.support import INPUTS, generate, sha256
from jmx_generator.generator import hourly_curve_script
from log_parser.parser import parse_logs
from traffic_model.habitual import (
    CURVE_PROPERTY, concurrency_curve, error_rates, reference_durations, side_file_path, write_side_file,
)
from traffic_model.payloads import build_path_params
from traffic_model.session import remove_session_requests
from traffic_model.status_filter import successful_rows
from traffic_model.think_time import build_think_times

# src/2-processing, para leer los logs de ejemplo desde cualquier carpeta
ROOT = Path(__file__).resolve().parents[1]
SAMPLE_LOG = ROOT / "samples" / "access_sample.log"
BANKAPP_LOG = ROOT.parent / "1-input" / "java-app-mock" / "logs" / "bankapp.jsonl"
REFERENCE_LOG = ROOT / "bench" / "data" / "bankapp_vall_pic_3h.jsonl"

# testname del TestAction de la curva horaria en el plan (T-1.4)
CURVE_TESTNAME = "STORM-IA: curva horaria"

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


def split_plan(path, drop_curve=False):
    """Separa un .jmx en (resto, modelos): el texto del plan sin los modelos y los modelos.

    En cada script Groovy con el modelo incrustado (parseText('''...''')), el JSON se deshace
    (al revés que jmx_generator/generator.py), se carga con json.loads y en el texto queda __MODEL__.
    Con drop_curve, antes se quitan el TestAction de la curva horaria (T-1.4) y el hashTree que lo sigue.
    """
    root = ET.parse(path).getroot()
    if drop_curve:
        found = [(parent, list(parent).index(child)) for parent in root.iter() for child in parent
                 if child.tag == "TestAction" and child.get("testname") == CURVE_TESTNAME]
        for parent, index in found:
            action, tree = list(parent)[index:index + 2]
            parent.remove(tree)
            parent.remove(action)
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
    habitual_rest, habitual_models = split_plan(habitual, drop_curve=True)

    # (a) sin los modelos (ni la curva horaria del T-1.4), el plan es idéntico
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


# --- T-1.3: <plan>.jmx.ai.json (duraciones, errores y la curva horaria) ---

def durations_table(values, method="GET", endpoint="/a"):
    """Tabla sintética de una sola petición con estas duraciones (ms); un None queda como NaN."""
    df = pd.DataFrame({"method": method, "endpoint": endpoint, "duration_ms": values})
    df["duration_ms"] = pd.to_numeric(df["duration_ms"], errors="coerce")
    return df


def sessions_table(rows):
    """Tabla sintética de peticiones: cada fila es (session_id, second), con second desde ORIGIN."""
    return pd.DataFrame({
        "session_id": [session for session, _ in rows],
        "timestamp": [ORIGIN + pd.Timedelta(seconds=second) for _, second in rows],
        "method": "GET",
        "endpoint": "/a",
    })


def test_reference_durations_by_hand():
    df = durations_table(list(range(1, 21)))
    assert reference_durations(df) == {"GET /a": {"requests": 20, "p50_ms": 10.5, "p95_ms": pytest.approx(19.05)}}


def test_reference_durations_skip_unknown_and_negative():
    # Una duración desconocida no se sabe; una negativa es un error del log: ninguna de las dos cuenta
    result = reference_durations(durations_table([10, None, -5, 30]))["GET /a"]
    assert result["requests"] == 2
    assert result["p50_ms"] == pytest.approx(20.0)


def test_reference_durations_zero_counts_with_three_decimals():
    # Una duración de 0 ms es válida (>= 0); el p50 de [0, 1.234] lleva 3 decimales
    result = reference_durations(durations_table([0, 1.234]))["GET /a"]
    assert result["requests"] == 2
    assert result["p50_ms"] == pytest.approx(0.617)


def test_reference_durations_without_durations():
    # Control negativo: sin la columna, o con la columna vacía, no hay tabla
    without_column = pd.DataFrame({"method": ["GET"], "endpoint": ["/a"]})
    assert reference_durations(without_column) == {}
    assert reference_durations(durations_table([None, None])) == {}
    assert reference_durations(None) == {}


def test_error_rates_by_hand():
    df = requests_table([("GET", "/a", "/a", s) for s in [200] * 7 + [404] * 2 + [503, None]])
    result = error_rates(df)["GET /a"]
    assert result["requests"] == 10
    assert result["4xx"] == pytest.approx(0.2)
    assert result["5xx"] == pytest.approx(0.1)


def test_error_rates_without_status():
    without_column = pd.DataFrame({"method": ["GET"], "endpoint": ["/a"]})
    assert error_rates(without_column) == {}
    assert error_rates(requests_table([("GET", "/a", "/a", None)])) == {}
    assert error_rates(None) == {}


def test_curve_valley_peak_valley():
    # Una sesión todo el rato y dos más en el tercio del medio: valle, pico, valle.
    # Las líneas sin sesión de antes no cuentan: la curva empieza en la primera sesión
    df = sessions_table([(None, -600), ("", -300), ("a", 0), ("a", 1800),
                         ("b", 600), ("b", 1200), ("c", 600), ("c", 1200)])
    curve = concurrency_curve(df)
    assert curve["values"] == pytest.approx([1 / 3, 1.0, 1 / 3], abs=1e-4)
    assert curve["slice_seconds"] == pytest.approx(600)
    assert curve["start"] == ORIGIN.isoformat()


@pytest.mark.parametrize("seconds, slices", [(599, 1), (601, 2), (3601, 7)])
def test_curve_last_slice_is_not_a_residue(seconds, slices):
    # Las franjas se reajustan para cubrir el log justo: la última no es un trozo casi vacío
    curve = concurrency_curve(sessions_table([("a", 0), ("a", seconds)]))
    assert len(curve["values"]) == slices
    assert curve["values"] == pytest.approx([1.0] * slices)
    assert curve["slice_seconds"] == pytest.approx(seconds / slices)


def test_curve_long_log_widens_the_slices():
    # 3 días de log son más de 288 franjas de 10 min: las franjas se ensanchan
    curve = concurrency_curve(sessions_table([("a", 0), ("a", 3 * 24 * 3600)]))
    assert len(curve["values"]) == 288
    assert curve["slice_seconds"] == pytest.approx(3 * 24 * 3600 / 288)


def test_curve_empty_session_does_not_count():
    # La pseudosesión "" (login y logout sin sesión) estaría abierta de la primera línea a la última:
    # si contara, la segunda franja valdría ~0.5
    df = sessions_table([("a", 0), ("a", 600), ("b", 1199), ("b", 1200), ("", 0), ("", 1200)])
    values = concurrency_curve(df)["values"]
    assert len(values) == 2
    assert values[0] == 1.0
    assert values[1] < 0.01


def test_no_sessions_no_curve():
    # El modo sin sesiones: sin sesiones no hay curva
    without_column = pd.DataFrame({"timestamp": [ORIGIN, ORIGIN + pd.Timedelta(seconds=60)]})
    assert concurrency_curve(without_column) is None
    assert concurrency_curve(sessions_table([(None, 0), (None, 60)])) is None
    assert concurrency_curve(sessions_table([("", 0), ("", 60)])) is None
    assert concurrency_curve(None) is None


def test_curve_of_the_reference_log():
    # Control positivo: el log de referencia tiene valle, pico y valle de una hora cada uno
    df, _ = remove_session_requests(parse_logs(REFERENCE_LOG), None, "/api/sessions")
    curve = concurrency_curve(df)
    values = curve["values"]
    assert len(values) == 18
    assert curve["slice_seconds"] == pytest.approx(599.3, abs=0.05)
    assert all(v >= 0.9 for v in values[6:12])
    assert all(v <= 0.36 for v in values[:6] + values[12:])
    assert max(values) == 1.0
    # La hora de la primera sesión (sin las peticiones de sesión)
    assert curve["start"] == "2026-10-28T19:23:58.601296+00:00"


def test_the_sample_log_figures():
    # Las cifras del log de ejemplo (tabla del punto 3 del encargo)
    df = parse_logs(SAMPLE_LOG)
    withdraw = error_rates(df)["POST /api/accounts/{id}/withdraw"]
    assert withdraw["requests"] == 9
    assert withdraw["4xx"] == pytest.approx(0.3333)
    curve = concurrency_curve(df)
    assert curve["slice_seconds"] == pytest.approx(561.6, abs=0.05)
    assert curve["values"] == pytest.approx([0.5008, 0.386, 1.0, 0.854])


def test_side_file_path():
    assert side_file_path("output/plan.jmx") == Path("output/plan.jmx.ai.json")


def test_side_file_with_the_flag(tmp_path):
    plan = generate(INPUTS["bankapp+session"] + ["--habitual-traffic"], tmp_path / "plan.jmx")
    content = json.loads(side_file_path(plan).read_text(encoding="utf-8"))
    assert list(content) == ["flag", "curve_property", "curve", "reference_durations", "error_rates"]
    assert content["flag"] == "--habitual-traffic"
    assert content["curve_property"] == "-Jcurva_horaria=1"
    assert len(content["curve"]["values"]) == 51
    assert content["curve"]["slice_seconds"] == pytest.approx(590.5, abs=0.05)
    assert content["curve"]["values"][0] == 1.0
    assert content["error_rates"]["POST /api/transfers"] == {
        "requests": 29, "4xx": pytest.approx(0.0345), "5xx": 0.0}
    assert content["reference_durations"]["GET /api/accounts/{id}"] == {
        "requests": 187, "p50_ms": pytest.approx(59.0), "p95_ms": pytest.approx(115.7)}
    # Duraciones y errores salen del log entero leído, también de las peticiones de sesión
    assert "POST /api/sessions" in content["reference_durations"]
    assert "POST /api/sessions" in content["error_rates"]


def test_curve_comes_from_the_log_without_session_requests(tmp_path):
    # El DELETE de sesión de "b" lleva su sessionId y la alargaría hasta el final: sin él, "b" dura 1 s
    line = ('{{"timestamp":"2026-01-01T00:{minute}:00Z","sessionId":"{session}","userId":1,"method":"{method}",'
            '"endpoint":"{endpoint}","path":"{path}","status":200,"durationMs":5}}')
    rows = [("00", "a", "GET", "/api/x", "/api/x"), ("00", "b", "GET", "/api/x", "/api/x"),
            ("10", "a", "GET", "/api/x", "/api/x"), ("20", "a", "GET", "/api/x", "/api/x"),
            ("20", "b", "DELETE", "/api/sessions/{id}", "/api/sessions/b")]
    log = tmp_path / "log.jsonl"
    log.write_text("\n".join(
        line.format(minute=m, session=s, method=me, endpoint=e, path=pa) for m, s, me, e, pa in rows) + "\n",
        encoding="utf-8")
    plan = generate(["--logs", str(log), "--session", "--habitual-traffic"], tmp_path / "plan.jmx")
    content = json.loads(side_file_path(plan).read_text(encoding="utf-8"))
    assert content["curve"]["values"] == pytest.approx([1.0, 0.9983])
    # las duraciones sí salen del log entero, con el DELETE de sesión
    assert "DELETE /api/sessions/{id}" in content["reference_durations"]


def test_side_file_without_logs(tmp_path):
    plan = generate(INPUTS["jar"] + ["--habitual-traffic"], tmp_path / "plan.jmx")
    content = json.loads(side_file_path(plan).read_text(encoding="utf-8"))
    assert content["curve"] is None
    assert content["curve_property"] is None
    assert content["reference_durations"] == {}
    assert content["error_rates"] == {}


@pytest.mark.parametrize("name", list(INPUTS))
def test_no_side_file_without_the_flag(tmp_path, name):
    # Control negativo: sin el flag no se escribe ningún .ai.json
    folder = tmp_path / "sin"
    generate(INPUTS[name], folder / "plan.jmx")
    assert list(folder.rglob("*.ai.json")) == []
    assert (folder / "plan.jmx").exists()


def test_write_side_file_writes_utf8_json(tmp_path):
    # Sin curva: curve y curve_property a null; el JSON termina en salto de línea
    path = write_side_file(tmp_path / "p.jmx", None, None)
    text = path.read_text(encoding="utf-8")
    assert path == tmp_path / "p.jmx.ai.json"
    assert text.endswith("}\n")
    assert json.loads(text)["curve_property"] is None


# --- T-1.4: la curva horaria en el plan, apagada salvo -Jcurva_horaria=1 ---

CURVE_VALUES = re.compile(r"double\[\] curve = \[(.*?)\] as double\[\]")


def curve_values_of(script):
    """Los valores de la curva incrustados en el script del temporizador."""
    return [float(v) for v in CURVE_VALUES.search(script).group(1).split(",")]


def thread_group_children(path):
    """Los hijos del hashTree que sigue al Thread Group del plan, en orden."""
    root = ET.parse(path).getroot()
    for parent in root.iter("hashTree"):
        children = list(parent)
        for index, child in enumerate(children):
            if child.tag == "ThreadGroup":
                return list(children[index + 1])
    raise AssertionError("el plan no tiene Thread Group")


def test_hourly_curve_script_carries_the_values():
    script = hourly_curve_script([1.0, 0.25, 0.0, 0.5])
    assert "double[] curve = [1.0, 0.25, 0.0, 0.5] as double[]" in script
    assert "Math.floor" in script
    assert "ctx.getThread().stop()" in script
    assert "__CURVE_VALUES__" not in script


def test_the_script_reads_the_property_of_the_side_file(tmp_path):
    # El nombre de la propiedad es el mismo en el plan y en el .ai.json: si cambia en uno solo, cae
    script = hourly_curve_script([1.0])
    assert f'props.getProperty("{CURVE_PROPERTY}", "0").trim() != "1"' in script
    plan = generate(INPUTS["bankapp+session"] + ["--habitual-traffic"], tmp_path / "plan.jmx")
    content = json.loads(side_file_path(plan).read_text(encoding="utf-8"))
    assert content["curve_property"] == f"-J{CURVE_PROPERTY}=1"


def test_the_curve_goes_right_before_the_new_session(tmp_path):
    plan = generate(INPUTS["bankapp+session"] + ["--habitual-traffic"], tmp_path / "plan.jmx")
    children = thread_group_children(plan)
    actions = [(i, c) for i, c in enumerate(children) if c.tag == "TestAction"]
    curve = [(i, c) for i, c in actions if c.get("testname") == CURVE_TESTNAME]
    assert len(curve) == 1
    index = curve[0][0]
    # El TestAction siguiente es "Nueva sesión": la espera va antes de elegir la primera petición
    following = [c for i, c in actions if i > index]
    assert following[0].get("testname") == "Nueva sesión"
    timers = list(children[index + 1].iter("JSR223Timer"))
    assert children[index + 1].tag == "hashTree" and len(timers) == 1
    script = next(p.text for p in timers[0] if p.get("name") == "script")
    content = json.loads(side_file_path(plan).read_text(encoding="utf-8"))
    assert len(content["curve"]["values"]) == 51
    assert curve_values_of(script) == content["curve"]["values"]


def test_no_curve_without_sessions(tmp_path):
    # Control negativo: un log sin sessionId (el modo sin sesiones) no tiene curva, ni en el plan ni en el .ai.json
    line = ('{{"timestamp":"2026-01-01T00:{minute}:00Z","userId":1,"method":"GET",'
            '"endpoint":"/api/x","path":"/api/x","status":200,"durationMs":5}}')
    log = tmp_path / "log.jsonl"
    log.write_text("\n".join(line.format(minute=m) for m in ("00", "10", "20")) + "\n", encoding="utf-8")
    plan = generate(["--logs", str(log), "--habitual-traffic"], tmp_path / "plan.jmx")
    assert CURVE_TESTNAME not in plan.read_text(encoding="utf-8")
    content = json.loads(side_file_path(plan).read_text(encoding="utf-8"))
    assert content["curve"] is None


# JMeter real: un plan mínimo de 4 hilos y 24 s, con el temporizador de la curva y una muestra de 200 ms
MINIMAL_PLAN = """<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.3">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="Curva horaria"/>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="Hilos">
        <stringProp name="ThreadGroup.on_sample_error">continue</stringProp>
        <elementProp name="ThreadGroup.main_controller" elementType="LoopController" guiclass="LoopControlPanel" testclass="LoopController">
          <boolProp name="LoopController.continue_forever">false</boolProp>
          <intProp name="LoopController.loops">-1</intProp>
        </elementProp>
        <stringProp name="ThreadGroup.num_threads">4</stringProp>
        <stringProp name="ThreadGroup.ramp_time">0</stringProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
        <stringProp name="ThreadGroup.duration">24</stringProp>
        <stringProp name="ThreadGroup.delay">0</stringProp>
      </ThreadGroup>
      <hashTree>
        <TestAction guiclass="TestActionGui" testclass="TestAction" testname="Curva">
          <intProp name="ActionProcessor.action">1</intProp>
          <intProp name="ActionProcessor.target">0</intProp>
          <stringProp name="ActionProcessor.duration">0</stringProp>
        </TestAction>
        <hashTree>
          <JSR223Timer guiclass="TestBeanGUI" testclass="JSR223Timer" testname="Esperar la franja">
            <stringProp name="scriptLanguage">groovy</stringProp>
            <stringProp name="parameters"></stringProp>
            <stringProp name="filename"></stringProp>
            <stringProp name="cacheKey">true</stringProp>
            <stringProp name="script">{script}</stringProp>
          </JSR223Timer>
          <hashTree/>
        </hashTree>
        <JSR223Sampler guiclass="TestBeanGUI" testclass="JSR223Sampler" testname="marca">
          <stringProp name="scriptLanguage">groovy</stringProp>
          <stringProp name="parameters"></stringProp>
          <stringProp name="filename"></stringProp>
          <stringProp name="cacheKey">true</stringProp>
          <stringProp name="script">Thread.sleep(200)</stringProp>
        </JSR223Sampler>
        <hashTree/>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>
"""

needs_jmeter = pytest.mark.skipif(not bench.jmeter.jmeter_binary().exists(), reason="sin JMeter")


def assert_clean_log(log):
    # Si el Groovy no compila, el temporizador falla pero los hilos siguen: solo el jmeter.log lo dice
    text = Path(log).read_text(encoding="utf-8", errors="replace")
    errors = [line for line in text.splitlines() if " ERROR " in line or "ScriptException" in line]
    assert errors == []


def run_minimal_plan(tmp_path, values, properties=None):
    """Lanza el plan mínimo con esta curva; devuelve (JTL, camino del jmeter.log)."""
    plan = tmp_path / "curva.jmx"
    plan.write_text(MINIMAL_PLAN.replace("{script}", escape(hourly_curve_script(values))), encoding="utf-8")
    jtl, log = tmp_path / "curva.jtl", tmp_path / "jmeter.log"
    code, output = bench.jmeter.run(plan, jtl, log, properties)
    assert code == 0, output
    assert_clean_log(log)
    return bench.jmeter.read_jtl(jtl), log


def thread_number(name):
    """El hilo k (0, 1, ...) es el que tiene threadName acabado en -{k+1}."""
    return int(str(name).rsplit("-", 1)[1]) - 1


TEST_START = re.compile(r"^(\S+ \S+) INFO o\.a\.j\.e\.StandardJMeterEngine: Running the test!", re.M)


def jmeter_start_ms(log):
    """Hora de inicio de la prueba (ms desde 1970): la línea «Running the test!» del jmeter.log.

    Es el reloj del temporizador (getTestStartTime). La primera muestra llega más tarde: entre 0,5 y 2,5 s
    según la carga de la máquina, y por eso no sirve de origen.
    """
    stamp = TEST_START.search(Path(log).read_text(encoding="utf-8", errors="replace")).group(1)
    return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S,%f").timestamp() * 1000


def working_threads_by_window(df, log, windows=4):
    """Hilos con alguna muestra en cada ventana: la j va de j·6 + 2 a j·6 + 4 s desde el inicio de la prueba.

    El origen es el reloj del temporizador (jmeter_start_ms); la ventana de 2 s está en medio de cada franja de 6 s.
    """
    t0 = jmeter_start_ms(log)
    seconds = (df["timeStamp"] - t0) / 1000.0
    return [{thread_number(n) for n in df.loc[(seconds >= j * 6 + 2) & (seconds <= j * 6 + 4), "threadName"]}
            for j in range(windows)]


@needs_jmeter
def test_real_jmeter_curve_is_off_by_default(tmp_path):
    df, log = run_minimal_plan(tmp_path, [1, 0.25, 0, 0.5])
    assert working_threads_by_window(df, log) == [{0, 1, 2, 3}] * 4


@needs_jmeter
def test_real_jmeter_follows_the_curve(tmp_path):
    df, log = run_minimal_plan(tmp_path, [1, 0.25, 0, 0.5], {CURVE_PROPERTY: "1"})
    assert working_threads_by_window(df, log) == [{0, 1, 2, 3}, {0}, set(), {0, 1}]


@needs_jmeter
def test_real_jmeter_border_thread(tmp_path):
    # 0,4 × 4 hilos = 1,6: el hilo 0 siempre, el 1 con probabilidad 0,6 (la parte decimal), el 2 y el 3 nunca
    df, _ = run_minimal_plan(tmp_path, [0.4] * 8, {CURVE_PROPERTY: "1"})
    counts = df["threadName"].map(thread_number).value_counts()
    assert counts.get(2, 0) == 0 and counts.get(3, 0) == 0
    assert counts.get(0, 0) > 0
    assert 0 < counts.get(1, 0) < 0.75 * counts[0]


def free_closed_port():
    """Un puerto libre en 127.0.0.1 en el que no escucha nadie."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@needs_jmeter
def test_real_jmeter_accepts_the_plan(tmp_path):
    # El plan de main.py --habitual-traffic, con la curva encendida, contra un puerto cerrado
    line = ('{{"timestamp":"2026-01-01T00:00:0{second}Z","sessionId":"{session}","userId":1,"method":"GET",'
            '"endpoint":"/api/x","path":"/api/x","status":200,"durationMs":5}}')
    rows = [(s, n + i) for n, s in enumerate("abc") for i in range(3)]   # 3 sesiones, pausas de 1 s
    log = tmp_path / "log.jsonl"
    log.write_text("\n".join(line.format(session=s, second=t) for s, t in rows) + "\n", encoding="utf-8")
    plan = generate(["--logs", str(log), "--habitual-traffic"], tmp_path / "plan.jmx")
    assert CURVE_TESTNAME in plan.read_text(encoding="utf-8")
    jtl, jlog = tmp_path / "plan.jtl", tmp_path / "jmeter.log"
    properties = {CURVE_PROPERTY: "1", "duration": "10", "vusers": "2", "rampup": "0",
                  "host": "127.0.0.1", "port": str(free_closed_port())}
    code, output = bench.jmeter.run(plan, jtl, jlog, properties)
    assert code == 0, output
    assert_clean_log(jlog)
    assert len(bench.jmeter.read_jtl(jtl)) >= 1
