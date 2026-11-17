"""Tráfico habitual (cadena T-1 de la capa de IA). T-1.1: las pausas netas que ya hace build_think_times."""
import json

import pandas as pd
import pytest

from log_parser.parser import parse_logs
from traffic_model.think_time import build_think_times

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
