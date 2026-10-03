"""Cuánta carga simular a partir del tráfico observado."""
from typing import Dict

import pandas as pd

DEFAULT_VUSERS = 10


def predict_traffic_scale(
    df: pd.DataFrame,
    growth_factor: float = 1.5,
    ramp_up_seconds: int = 60,
    duration_seconds: int = 300,
) -> Dict[str, int]:
    """Usuarios virtuales = sesiones observadas x factor de crecimiento.

    Heurística provisional del código base: proyecta un +50 % de tráfico.
    """
    if df is None or df.empty or "session_id" not in df:
        # Sin logs no hay datos de cuánta gente la usa: valor por defecto, se cambia con -Jvusers
        vusers = DEFAULT_VUSERS
    else:
        vusers = max(1, int(df["session_id"].nunique() * growth_factor))
    return {
        "vusers": vusers,
        "ramp_up_seconds": ramp_up_seconds,
        "duration_seconds": duration_seconds,
    }
