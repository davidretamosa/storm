"""Tráfico habitual (capa de IA, --habitual-traffic): cómo es el día normal de la aplicación según el log.

Se escribe en un fichero al lado del plan, <plan>.jmx.ai.json, para las personas y el laboratorio:
- reference_durations(df): p50 y p95 de la duración de cada petición (ms);
- error_rates(df): proporción de respuestas 4xx y 5xx de cada petición;
- concurrency_curve(df): la curva horaria, cuántas sesiones había abiertas en cada franja del log,
  en proporción a la franja más llena (1 = la más llena, que en el plan serán los vusers).

El plan .jmx no cambia: la curva se calcula aquí y se pondrá en el plan aparte, apagada salvo que
se lance JMeter con -Jcurva_horaria=1.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

CURVE_PROPERTY = "curva_horaria"   # propiedad de JMeter que enciende la curva: -Jcurva_horaria=1
SLICE_SECONDS = 600                # franjas de unos 10 minutos del log
MAX_SLICES = 288                   # 2 días de log; si es más largo, las franjas se ensanchan
MIN_SESSION_SECONDS = 1            # una sesión de una sola petición cuenta como si durara 1 s


def _request_keys(df):
    """La clave de cada petición, "GET /api/accounts/{id}", como en traffic_model/markov.py."""
    return df["method"] + " " + df["endpoint"]


def reference_durations(df):
    """{"GET /api/accounts/{id}": {"requests": 187, "p50_ms": 59.0, "p95_ms": 115.7}, ...}

    Solo cuentan las líneas con duration_ms conocido y >= 0 (una duración negativa es un error del log).
    Cuantiles de pandas (interpolación lineal), redondeados a 3 decimales. {} si no hay ninguna duración válida.
    """
    if df is None or df.empty or "duration_ms" not in df.columns:
        return {}
    durations = pd.to_numeric(df["duration_ms"], errors="coerce")
    valid = durations.notna() & (durations >= 0)
    if not valid.any():
        return {}
    table = pd.DataFrame({"key": _request_keys(df)[valid], "duration": durations[valid]})
    result = {}
    for key, group in table.groupby("key"):
        values = group["duration"]
        result[key] = {
            "requests": int(len(values)),
            "p50_ms": round(float(values.quantile(0.5)), 3),
            "p95_ms": round(float(values.quantile(0.95)), 3),
        }
    return result


def error_rates(df):
    """{"POST /api/transfers": {"requests": 29, "4xx": 0.0345, "5xx": 0.0}, ...}

    Solo cuentan las líneas con status conocido. Proporciones redondeadas a 4 decimales.
    {} si no hay ningún status.
    """
    if df is None or df.empty or "status" not in df.columns:
        return {}
    status = pd.to_numeric(df["status"], errors="coerce")
    known = status.notna()
    if not known.any():
        return {}
    table = pd.DataFrame({"key": _request_keys(df)[known], "status": status[known]})
    result = {}
    for key, group in table.groupby("key"):
        codes = group["status"]
        result[key] = {
            "requests": int(len(codes)),
            "4xx": round(float(((codes >= 400) & (codes <= 499)).mean()), 4),
            "5xx": round(float(((codes >= 500) & (codes <= 599)).mean()), 4),
        }
    return result


def concurrency_curve(df, slice_seconds=SLICE_SECONDS, max_slices=MAX_SLICES):
    """{"start": hora de la primera franja, "slice_seconds": s, "values": [0.3244, ..., 1.0, ...]} o None.

    - Sesión = de la primera petición a la última de cada session_id (como peak_concurrent_sessions);
      dura como mínimo MIN_SESSION_SECONDS.
    - Las filas sin sesión no cuentan, ni la pseudosesión "" (los login y logout de la bankapp): sería
      una sesión abierta de la primera línea a la última.
    - Franjas iguales que cubren el log justo (de unos slice_seconds, como mucho max_slices), para que
      la última no sea un residuo casi vacío.
    - values[j] = sesiones abiertas de media en la franja j / las de la franja más llena.
    None si no hay ninguna sesión: sin sesiones no hay curva.
    """
    if df is None or df.empty or "session_id" not in df.columns or "timestamp" not in df.columns:
        return None
    ids = df["session_id"]
    with_session = ids.notna() & (ids.astype("object") != "") & df["timestamp"].notna()
    if not with_session.any():
        return None
    sessions = df[with_session].groupby("session_id")["timestamp"].agg(["min", "max"])

    first = sessions["min"].min()
    starts = (sessions["min"] - first).dt.total_seconds().to_numpy()
    ends = (sessions["max"] - first).dt.total_seconds().to_numpy()
    ends = np.maximum(ends, starts + MIN_SESSION_SECONDS)

    # Franjas iguales: el log entero (span) dividido en count trozos
    span = float(ends.max())
    count = min(max_slices, max(1, math.ceil(span / slice_seconds)))
    width = span / count
    edges = np.arange(count + 1) * width

    # Segundos que cada sesión está abierta dentro de cada franja (sesiones x franjas)
    overlap = np.minimum(ends[:, None], edges[None, 1:]) - np.maximum(starts[:, None], edges[None, :-1])
    open_sessions = np.clip(overlap, 0, None).sum(axis=0) / width
    values = open_sessions / open_sessions.max()
    return {
        "start": pd.Timestamp(first).isoformat(),
        "slice_seconds": float(width),
        "values": [round(float(v), 4) for v in values],
    }


def side_file_path(output_path):
    """output/plan.jmx -> output/plan.jmx.ai.json"""
    return Path(f"{output_path}.ai.json")


def write_side_file(output_path, df, curve):
    """Escribe <plan>.jmx.ai.json con la curva, las duraciones y los errores; devuelve su ruta."""
    content = {
        "flag": "--habitual-traffic",
        # sin curva no se dice cómo se enciende una curva que no está
        "curve_property": f"-J{CURVE_PROPERTY}=1" if curve is not None else None,
        "curve": curve,
        "reference_durations": reference_durations(df),
        "error_rates": error_rates(df),
    }
    path = side_file_path(output_path)
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
