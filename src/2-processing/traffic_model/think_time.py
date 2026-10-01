"""Pausas entre peticiones (think time) observadas en las sesiones."""
from typing import Dict, List

import numpy as np
import pandas as pd

from traffic_model.markov import session_steps


def build_think_times(
    df: pd.DataFrame,
    samples: int = 20,
    max_ms: int = 120_000,
) -> Dict[str, Dict[str, List[int]]]:
    """Milisegundos que pasan entre una petición y la siguiente, por transición.

    Se guardan `samples` cuantiles de la distribución observada en vez de la media:
    al simular se elige uno al azar, así se respeta la forma real (pausas cortas
    frecuentes y alguna larga). Las pausas mayores que `max_ms` se recortan.
    """
    steps = session_steps(df)
    steps["gap_ms"] = steps.groupby("session_id")["timestamp"].shift(-1) - steps["timestamp"]
    steps = steps.dropna(subset=["next_key", "gap_ms"])

    think_times: Dict[str, Dict[str, List[int]]] = {}
    quantiles = np.linspace(0, 1, samples)
    for (source, target), group in steps.groupby(["key", "next_key"]):
        gaps = group["gap_ms"].dt.total_seconds().to_numpy() * 1000
        values = np.quantile(np.clip(gaps, 0, max_ms), quantiles)
        think_times.setdefault(source, {})[target] = [int(round(v)) for v in values]
    return think_times
