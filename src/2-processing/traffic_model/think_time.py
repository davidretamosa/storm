"""Pausas entre peticiones (think time) observadas en las sesiones."""
import numpy as np

from traffic_model.markov import END, get_steps

# Sin datos no sabemos cuánto espera el usuario: suposición habitual en pruebas de carga,
# una pausa al azar de 1 a 3 s (JMeter elige uno de estos valores). Se cambia con --default-pause.
DEFAULT_PAUSE_MS = [1000, 1500, 2000, 2500, 3000]


def build_think_times(df, samples=20, max_ms=120_000):
    """Milisegundos que pasan entre una petición y la siguiente, para cada transición.

    Devuelve {actual: {siguiente: [ms, ms, ...]}}, p. ej.
    {"GET /api/accounts/{id}": {"POST /api/transfers": [2100, 3400, ..., 18000]}}.

    Se guardan `samples` cuantiles de las pausas observadas en vez de la media:
    al simular se elige uno al azar, así se respeta la forma real (pausas cortas
    frecuentes y alguna larga). Las pausas mayores que `max_ms` se recortan.
    """
    if df is None or df.empty:
        return {}  # sin logs no hay pausas observadas
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


def add_default_pauses(think_times, model, default_pause_ms=DEFAULT_PAUSE_MS):
    """Pone la pausa por defecto en las transiciones del modelo que no tienen pausas de los logs:
    todas si no hay logs, y las que añade el .jar (p. ej. un endpoint que nadie ha usado)."""
    for source, targets in model["transitions"].items():
        for target in targets:
            if target == END:
                continue
            if source not in think_times:
                think_times[source] = {}
            if target not in think_times[source]:
                think_times[source][target] = list(default_pause_ms)
    return think_times
