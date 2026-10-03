"""Lectura de los logs de acceso de la aplicación objetivo (app del banco, 1-input/java-app-mock).

Formato: JSON Lines, una petición por línea:
{"timestamp":"2026-10-01T11:42:35.123Z","requestId":"a1b2...","sessionId":"sess-9f8e7d6c","userId":12,
 "method":"POST","endpoint":"/api/accounts/{id}/deposit","path":"/api/accounts/3/deposit","status":200,
 "durationMs":45,"requestSizeBytes":17,"responseSizeBytes":256,"body":{"amount":200.00}}
"""
import json

import pandas as pd

# Campo del log -> columna del DataFrame
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
    "body": "body",
}
# Sin estos campos la línea no sirve para modelar el tráfico
REQUIRED = ("timestamp", "method", "endpoint")


def _parse_line(line: str):
    """Diccionario de la línea, o None si no es un log de petición válido."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or any(not entry.get(field) for field in REQUIRED):
        return None
    row = {column: entry.get(field) for field, column in COLUMNS.items()}
    # El cuerpo solo se usa si es un objeto JSON ({"amount": 200.0}); null o texto -> None
    if not isinstance(row["body"], dict):
        row["body"] = None
    return row


def parse_logs(log_file_path: str) -> pd.DataFrame:
    """Convierte el log (una petición JSON por línea) en un DataFrame ordenado por tiempo.

    Las líneas vacías, las que no son JSON y las que no tienen timestamp/method/endpoint se ignoran.
    """
    with open(log_file_path, encoding="utf-8") as f:
        rows = [row for row in map(_parse_line, f) if row is not None]

    df = pd.DataFrame(rows, columns=list(COLUMNS.values()))
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True)
    df["status"] = pd.to_numeric(df["status"], errors="coerce")
    df["duration_ms"] = pd.to_numeric(df["duration_ms"], errors="coerce")
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)
