"""Lectura de los logs de acceso de la aplicación objetivo (app del banco, 1-input/java-app-mock).

Formato: JSON Lines, una petición por línea:
{"timestamp":"2026-10-01T11:42:35.123Z","requestId":"a1b2...","sessionId":"sess-9f8e7d6c","userId":12,
 "method":"POST","endpoint":"/api/accounts/{id}/deposit","path":"/api/accounts/3/deposit","status":200,
 "durationMs":45,"requestSizeBytes":17,"responseSizeBytes":256,"body":{"amount":200.00}}
"""
import json

import pandas as pd

# Nombre del campo en el log -> nombre de la columna en nuestra tabla.
# Los campos del log que no estén aquí se ignoran.
COLUMNS = {
    "timestamp": "timestamp",
    "requestId": "request_id",
    "sessionId": "session_id",
    "userId": "user_id",
    "method": "method",
    "endpoint": "endpoint",
    "path": "path",
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

    # 3. Tiene que tener los campos obligatorios
    for field in REQUIRED:
        if not entry.get(field):
            return None

    # 4. Construimos la fila con los nombres de nuestras columnas
    row = {}
    for log_field, column in COLUMNS.items():
        row[column] = entry.get(log_field)

    # 5. El body solo nos sirve si es un objeto JSON ({"amount": 200.0}); null o texto -> None
    if not isinstance(row["body"], dict):
        row["body"] = None

    return row


def parse_logs(log_file_path):
    """Lee el log entero y lo devuelve como una tabla (DataFrame) ordenada por tiempo."""
    # 1. Leemos el archivo línea a línea y nos quedamos con las válidas
    rows = []
    with open(log_file_path, encoding="utf-8") as f:
        for line in f:
            row = parse_line(line)
            if row is not None:
                rows.append(row)

    # 2. Convertimos la lista de filas en una tabla
    df = pd.DataFrame(rows, columns=list(COLUMNS.values()))
    if df.empty:
        return df

    # 3. Pasamos cada columna a su tipo de dato: fechas y números en vez de texto
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True)
    df["status"] = pd.to_numeric(df["status"], errors="coerce")
    df["duration_ms"] = pd.to_numeric(df["duration_ms"], errors="coerce")
    df["request_size_bytes"] = pd.to_numeric(df["request_size_bytes"], errors="coerce")
    df["response_size_bytes"] = pd.to_numeric(df["response_size_bytes"], errors="coerce")

    # 4. Ordenamos por hora (los logs no siempre vienen en orden) y renumeramos las filas
    df = df.sort_values("timestamp", kind="stable")
    df = df.reset_index(drop=True)
    return df
