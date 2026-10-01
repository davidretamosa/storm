"""Cadena de Markov de la navegación: qué petición sigue a cuál dentro de una sesión."""
from typing import Dict

import pandas as pd


def request_key(method: str, endpoint: str) -> str:
    """Identificador de un estado de la cadena, p. ej. 'GET /api/accounts/{id}'."""
    return f"{method} {endpoint}"


def build_markov_matrix(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Probabilidad de pasar de cada petición a la siguiente (cada fila suma 1)."""
    if "session_id" not in df or df["session_id"].isna().all():
        raise ValueError(
            "Los logs no tienen el campo 'sesion=': sin él no se pueden reconstruir "
            "las secuencias de navegación (ver README)."
        )

    steps = df.dropna(subset=["session_id"]).sort_values("timestamp", kind="stable")
    keys = steps["method"] + " " + steps["endpoint"]
    next_keys = keys.groupby(steps["session_id"]).shift(-1)

    # El último paso de cada sesión no tiene transición
    transitions = pd.DataFrame({"source": keys, "target": next_keys}).dropna()
    if transitions.empty:
        return {}

    counts = transitions.groupby(["source", "target"]).size().unstack(fill_value=0)
    probabilities = counts.div(counts.sum(axis=1), axis=0)
    return {
        source: {target: float(p) for target, p in row.items() if p > 0}
        for source, row in probabilities.iterrows()
    }
