"""Cuánta carga simular: cuántos usuarios virtuales, cuánto tarda en arrancarlos y cuánto dura."""
import math

import pandas as pd

# Sin logs no hay datos de cuánta gente usa la app: valor pequeño por defecto
# (no tumbar el laboratorio y que haya varios usuarios a la vez). Se cambia con -Jvusers.
DEFAULT_VUSERS = 10


def peak_concurrent_sessions(df):
    """Máximo de sesiones abiertas A LA VEZ en el log (el momento de más tráfico).

    Cada sesión está abierta desde su primera petición hasta la última. Se recorre el tiempo
    sumando 1 cuando empieza una sesión y restando 1 cuando acaba; el máximo es el pico.
    """
    sessions = df.dropna(subset=["session_id"]).groupby("session_id")["timestamp"].agg(["min", "max"])

    starts = pd.DataFrame({"time": sessions["min"], "change": 1})
    ends = pd.DataFrame({"time": sessions["max"], "change": -1})

    # Por orden de tiempo; si coinciden, primero los inicios (una sesión de una sola petición cuenta)
    events = pd.concat([starts, ends]).sort_values(["time", "change"], ascending=[True, False])
    return int(events["change"].cumsum().max())


def predict_traffic_scale(df, growth_factor=1.5, ramp_up_seconds=60, duration_seconds=300):
    """Usuarios virtuales = pico de sesiones a la vez en el log x growth_factor (+50 % de margen).

    Se usa el pico y no el total de sesiones: el total crece con lo largo que sea el log
    (un log de un día daría miles de usuarios), el pico solo depende del momento de más tráfico.
    Todo se puede cambiar al lanzar JMeter: -Jvusers= -Jrampup= -Jduration=
    """
    if df is None or df.empty or "session_id" not in df or df["session_id"].isna().all():
        vusers = DEFAULT_VUSERS
    else:
        vusers = max(1, math.ceil(peak_concurrent_sessions(df) * growth_factor))
    return {
        "vusers": vusers,
        "ramp_up_seconds": ramp_up_seconds,
        "duration_seconds": duration_seconds,
    }
