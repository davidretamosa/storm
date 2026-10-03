"""Pausas entre peticiones (think time) observadas en las sesiones."""
import numpy as np

from traffic_model.markov import get_steps


def build_think_times(df, samples=20, max_ms=120_000):
    """Milisegundos que pasan entre una petición y la siguiente, para cada transición.

    Devuelve {actual: {siguiente: [ms, ms, ...]}}, p. ej.
    {"GET /api/accounts/{id}": {"POST /api/transfers": [2100, 3400, ..., 18000]}}.

    Se guardan `samples` cuantiles de las pausas observadas en vez de la media:
    al simular se elige uno al azar, así se respeta la forma real (pausas cortas
    frecuentes y alguna larga). Las pausas mayores que `max_ms` se recortan.
    """
    steps = get_steps(df)

    # Hora de la siguiente petición de la misma sesión (igual que next_key, pero con la hora)
    steps["next_timestamp"] = steps.groupby("session_id")["timestamp"].shift(-1)

    # Pausa = hora de la siguiente - hora de esta, en milisegundos, entre 0 y max_ms
    steps["gap_ms"] = (steps["next_timestamp"] - steps["timestamp"]).dt.total_seconds() * 1000
    steps["gap_ms"] = steps["gap_ms"].clip(lower=0, upper=max_ms)

    # La última petición de cada sesión no tiene pausa
    pairs = steps.dropna(subset=["next_key"])

    # Para cada pareja (actual, siguiente): `samples` cuantiles de sus pausas, del mínimo al máximo
    quantiles = np.linspace(0, 1, samples)
    think_times = {}
    for (source, target), group in pairs.groupby(["key", "next_key"]):
        summary = group["gap_ms"].quantile(quantiles)
        if source not in think_times:
            think_times[source] = {}
        think_times[source][target] = [int(round(v)) for v in summary]
    return think_times
