"""Lectura de los logs de acceso de la aplicación objetivo."""
import re

import pandas as pd

# Formato de línea (el mismo que usa la echo-api del grupo de 3-execution):
# 2026-09-25T10:15:02.123+02:00 INFO  [a1b2c3d4e5f6] ACCESS - metodo=GET endpoint=/api/accounts/{id} ... sesion=s01
LINE_PATTERN = re.compile(r"^(?P<timestamp>\S+)\s+\w+\s+\[(?P<request_id>[^\]]*)\]\s+ACCESS\s+-\s+(?P<fields>.*)$")
FIELD_PATTERN = re.compile(r"(\w+)=(\S+)")

# Campo del log -> columna del DataFrame
COLUMNS = {
    "sesion": "session_id",
    "metodo": "method",
    "endpoint": "endpoint",
    "estado": "status",
    "duracionMs": "duration_ms",
}


def parse_logs(log_file_path: str) -> pd.DataFrame:
    """Convierte las líneas ACCESS del log en un DataFrame ordenado por tiempo."""
    rows = []
    with open(log_file_path, encoding="utf-8") as f:
        for line in f:
            match = LINE_PATTERN.match(line.strip())
            if not match:
                continue
            fields = dict(FIELD_PATTERN.findall(match["fields"]))
            row = {"timestamp": match["timestamp"], "request_id": match["request_id"]}
            row.update({col: fields.get(key) for key, col in COLUMNS.items()})
            rows.append(row)

    df = pd.DataFrame(rows, columns=["timestamp", "request_id", *COLUMNS.values()])
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601")
    df["status"] = pd.to_numeric(df["status"], errors="coerce")
    df["duration_ms"] = pd.to_numeric(df["duration_ms"], errors="coerce")
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)
