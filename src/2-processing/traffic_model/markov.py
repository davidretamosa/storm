"""Cadena de Markov de la navegación: qué petición sigue a cuál dentro de una sesión."""
from typing import Dict, List

import pandas as pd

# Estado final: la sesión termina después de la petición actual
END = "END"


def request_key(method: str, endpoint: str) -> str:
    """Identificador de un estado de la cadena, p. ej. 'GET /api/accounts/{id}'."""
    return f"{method} {endpoint}"


def session_steps(df: pd.DataFrame) -> pd.DataFrame:
    """Peticiones con sesión, ordenadas por tiempo, con su estado ('key') y el siguiente ('next_key')."""
    if "session_id" not in df or df["session_id"].isna().all():
        raise ValueError(
            "Los logs no tienen el campo 'sessionId': sin él no se pueden reconstruir "
            "las secuencias de navegación (ver README)."
        )

    steps = df.dropna(subset=["session_id"]).sort_values("timestamp", kind="stable").copy()
    steps["key"] = steps["method"] + " " + steps["endpoint"]
    steps["next_key"] = steps.groupby("session_id")["key"].shift(-1)
    return steps


def _normalize(counts: pd.Series) -> Dict[str, float]:
    return {key: float(n / counts.sum()) for key, n in counts.items() if n > 0}


def build_markov_matrix(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Probabilidad de pasar de cada petición a la siguiente (cada fila suma 1)."""
    # El último paso de cada sesión no tiene transición
    transitions = session_steps(df).dropna(subset=["next_key"])
    if transitions.empty:
        return {}

    return {
        source: _normalize(group["next_key"].value_counts(sort=False))
        for source, group in transitions.groupby("key")
    }


def _prune(distribution: Dict[str, float], min_probability: float) -> Dict[str, float]:
    """Quita lo menos probable y renormaliza; si todo queda por debajo, se queda el más probable."""
    kept = {k: p for k, p in distribution.items() if p >= min_probability}
    if not kept:
        best = max(distribution, key=distribution.get)
        kept = {best: distribution[best]}
    total = sum(kept.values())
    return {k: p / total for k, p in kept.items()}


def build_markov_model(df: pd.DataFrame, min_probability: float = 0.0, max_steps: int = 50) -> dict:
    """Modelo completo de navegación para simular sesiones:

    - start: probabilidad de que una sesión empiece por cada petición.
    - transitions: probabilidad de la siguiente petición, incluido END (fin de sesión).
    - max_steps: límite de peticiones por sesión, por si la cadena tiene bucles.
    """
    steps = session_steps(df)
    first = steps.groupby("session_id")["key"].first()
    with_end = steps.assign(next_key=steps["next_key"].fillna(END))

    transitions = {
        source: _prune(_normalize(group["next_key"].value_counts(sort=False)), min_probability)
        for source, group in with_end.groupby("key")
    }
    states: List[str] = sorted(transitions)
    return {
        "states": states,
        "start": _prune(_normalize(first.value_counts(sort=False)), min_probability),
        "transitions": transitions,
        "max_steps": max_steps,
    }
