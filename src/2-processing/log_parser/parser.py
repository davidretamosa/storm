"""Lectura de los logs de acceso de la aplicación objetivo."""
import re

import pandas as pd

# Formato de línea (el mismo que usa la echo-api del grupo de 3-execution):
# 2026-09-25T10:15:02.123+02:00 INFO  [a1b2c3d4e5f6] ACCESS - metodo=POST endpoint=/api/accounts/{id}/deposit
#   ruta=/api/accounts/3/deposit ... ua="Apache-HttpClient/4.5.14" sesion=s01 cuerpo={"amount": 50.0}
LINE_PATTERN = re.compile(r"^(?P<timestamp>\S+)\s+\w+\s+\[(?P<request_id>[^\]]*)\]\s+ACCESS\s+-\s+(?P<fields>.*)$")
# Valores sin espacios o entre comillas (ua="Mozilla/5.0 (Windows NT ...)")
FIELD_PATTERN = re.compile(r'(\w+)=("[^"]*"|\S+)')
# El cuerpo va siempre al final de la línea y puede tener espacios
BODY_PATTERN = re.compile(r"\s+cuerpo=(?P<body>.*)$")

# Campo del log -> columna del DataFrame
COLUMNS = {
    "sesion": "session_id",
    "metodo": "method",
    "endpoint": "endpoint",
    "ruta": "path",
    "estado": "status",
    "duracionMs": "duration_ms",
}


def _body(raw):
    """'-' (sin cuerpo) y los cuerpos recortados por la app ('...') no sirven como ejemplo."""
    if raw is None or raw == "-" or raw.endswith("..."):
        return None
    return raw


def parse_logs(log_file_path: str) -> pd.DataFrame:
    """Convierte las líneas ACCESS del log en un DataFrame ordenado por tiempo."""
    rows = []
    with open(log_file_path, encoding="utf-8") as f:
        for line in f:
            match = LINE_PATTERN.match(line.strip())
            if not match:
                continue
            fields_text = match["fields"]
            body = BODY_PATTERN.search(fields_text)
            if body:
                fields_text = fields_text[:body.start()]
            fields = dict(FIELD_PATTERN.findall(fields_text))
            row = {"timestamp": match["timestamp"], "request_id": match["request_id"]}
            row.update({col: fields.get(key) for key, col in COLUMNS.items()})
            row["body"] = _body(body["body"].strip() if body else None)
            rows.append(row)

    df = pd.DataFrame(rows, columns=["timestamp", "request_id", *COLUMNS.values(), "body"])
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601")
    df["status"] = pd.to_numeric(df["status"], errors="coerce")
    df["duration_ms"] = pd.to_numeric(df["duration_ms"], errors="coerce")
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)
