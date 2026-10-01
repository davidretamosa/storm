"""Cuánta carga simular a partir del tráfico observado."""
from typing import Dict

import pandas as pd


def predict_traffic_scale(
    df: pd.DataFrame,
    growth_factor: float = 1.5,
    ramp_up_seconds: int = 60,
    duration_seconds: int = 300,
) -> Dict[str, int]:
    """Usuarios virtuales = sesiones observadas x factor de crecimiento.

    Heurística provisional del código base: proyecta un +50 % de tráfico.
    """
    unique_sessions = df["session_id"].nunique() if "session_id" in df else 0
    return {
        "vusers": max(1, int(unique_sessions * growth_factor)),
        "ramp_up_seconds": ramp_up_seconds,
        "duration_seconds": duration_seconds,
    }
