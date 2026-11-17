"""Lectura de los logs de acceso de la aplicación objetivo (app del banco, 1-input/java-app-mock).

Lee dos formatos, línea a línea: el JSON acordado con input (abajo) y OpenTelemetry (log_parser/otel.py).

Formato: JSON Lines, una petición por línea:
{"timestamp":"2026-10-01T11:42:35.123Z","requestId":"a1b2...","sessionId":"sess-9f8e7d6c","userId":12,
 "method":"POST","endpoint":"/api/accounts/{id}/deposit","path":"/api/accounts/3/deposit","status":200,
 "durationMs":45,"requestSizeBytes":17,"responseSizeBytes":256,"body":{"amount":200.00}}
"""
import json

import pandas as pd

from log_parser.otel import parse_otel_record, parse_otlp_export
from log_parser.headers import normalize_headers

# Nombre del campo en el log -> nombre de la columna en nuestra tabla.
# Los campos del log que no estén aquí se ignoran.
COLUMNS = {
    "timestamp": "timestamp",
    "timestampKind": "timestamp_kind",
    "requestId": "request_id",
    "sessionId": "session_id",
    "userId": "user_id",
    "method": "method",
    "endpoint": "endpoint",
    "path": "path",
    "query": "query",
    "headers": "headers",
    "status": "status",
    "durationMs": "duration_ms",
    "requestSizeBytes": "request_size_bytes",
    "responseSizeBytes": "response_size_bytes",
    "body": "body",
}

# Sin estos campos la línea no sirve para modelar el tráfico
REQUIRED = ["timestamp", "method", "endpoint"]


def parse_line(line):
    """Convierte una línea del log en un diccionario con nuestras columnas.

    Devuelve None si la línea no es una petición válida.
    """
    # 1. La línea tiene que ser JSON (si no, p. ej. un mensaje de arranque de la app, se descarta)
    try:
        entry = json.loads(line)
    except ValueError:
        return None

    # 2. Tiene que ser un objeto {...}
    if not isinstance(entry, dict):
        return None

    # 2b. Si es un registro OpenTelemetry (lleva "attributes"), se lee con su propio formato (otel.py)
    if "attributes" in entry:
        return parse_otel_record(entry)

    # 3. Validar la presencia y el tipo de los campos obligatorios
    for field in REQUIRED:
        value = entry.get(field)

        if not isinstance(value, str) or not value.strip():
            return None

    # 4. Construimos la fila con los nombres de nuestras columnas
    row = {}
    for log_field, column in COLUMNS.items():
        row[column] = entry.get(log_field)
    # Normalizar y filtrar las cabeceras HTTP
    row["headers"] = normalize_headers(row["headers"])

    # El formato JSON acordado con la aplicación del banco
    # registra el timestamp al finalizar la petición.
    if row["timestamp_kind"] is None:
        row["timestamp_kind"] = "end"
    # Extraer los parámetros de consulta si aparecen en la ruta
    if isinstance(row["path"], str) and "?" in row["path"]:
        path, query = row["path"].split("?", 1)
        row["path"] = path

        if row["query"] is None:
            row["query"] = query

    # 5. El body solo nos sirve si es un objeto JSON ({"amount": 200.0}); null o texto -> None
    if not isinstance(row["body"], dict):
        row["body"] = None
    # El endpoint no debe incluir parámetros de consulta
    row["endpoint"] = row["endpoint"].split("?", 1)[0]
    return row

def parse_logs(log_file_path):
    """Lee el log entero y lo devuelve como un DataFrame ordenado por tiempo."""

    # 1. Leemos el archivo línea a línea.
    rows = []
    with open(log_file_path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue

            # Exportación OTLP con múltiples spans.
            if isinstance(entry, dict) and "resourceSpans" in entry:
                rows.extend(parse_otlp_export(entry))
            else:
                # Formatos que ya soportaba STORM.
                row = parse_line(line)
                if row is not None:
                    rows.append(row)

    # 2. Convertimos las filas en un DataFrame.
    df = pd.DataFrame(rows, columns=list(COLUMNS.values()))
    if df.empty:
        return df

    # 3. Convertimos los tipos de datos.
    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        format="ISO8601",
        utc=True,
        errors="coerce"
    )

    # Descartar las peticiones con timestamps inválidos
    df = df.dropna(subset=["timestamp"])
    df["status"] = pd.to_numeric(df["status"], errors="coerce")
    df["duration_ms"] = pd.to_numeric(df["duration_ms"], errors="coerce")
    df["request_size_bytes"] = pd.to_numeric(df["request_size_bytes"], errors="coerce")
    df["response_size_bytes"] = pd.to_numeric(df["response_size_bytes"], errors="coerce")

    # 4. Ordenamos las peticiones por tiempo.
    df = df.sort_values("timestamp", kind="stable")
    df = df.reset_index(drop=True)
    return df

