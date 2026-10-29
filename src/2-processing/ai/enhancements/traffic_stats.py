"""Trànsit habitual (T-1): el que es treu de `status` i `duration_ms`, columnes que la cadena dels companys no llegeix.

Funcions sobre el DataFrame de `parse_logs`. No canvien mai el que reben: tornen una còpia o una dada nova.

- net_pauses:          el log amb les pauses sense el temps de resposta del servidor (per a build_think_times);
- successful:          les peticions que van anar bé (per a build_path_params);
- error_rates:         la taxa de 4xx i de 5xx de cada petició (dada per al laboratori);
- reference_durations: el p50 i el p95 de duration_ms de cada petició (dada per al laboratori, IA-09).
"""
import pandas as pd


def has_column(df, column):
    """El log té aquesta columna amb algun valor (els logs sense status o sense duració la porten buida)."""
    return df is not None and not df.empty and column in df.columns and df[column].notna().any()


def request_keys(df):
    """'GET' + ' ' + '/api/accounts/{id}', com la clau dels companys (traffic_model/markov.py)."""
    return df["method"] + " " + df["endpoint"]


def net_pauses(df):
    """Còpia del log on cada pausa d'una sessió ja no porta el temps de resposta de la petició d'abans.

    El log apunta quan arriba cada petició. Entre una i la següent hi ha el temps que triga el servidor
    (duration_ms) i el que l'usuari s'hi pensa. JMeter ja espera la resposta abans de fer la pausa: si la
    pausa també el portés, comptaria dues vegades. Pausa neta = pausa - duració de l'anterior, com a mínim 0.

    No es calculen les pauses aquí: es mouen les hores de cada sessió perquè build_think_times (dels
    companys) les calculi com sempre, amb els seus quantils i el seu topall. Sense duration_ms, el log tal qual.
    """
    if not has_column(df, "duration_ms") or not has_column(df, "session_id"):
        return df

    steps = df.dropna(subset=["session_id"]).sort_values("timestamp", kind="stable")
    sessions = steps.groupby("session_id")

    gap = sessions["timestamp"].diff()                                    # NaT a la primera de cada sessió
    previous_ms = sessions["duration_ms"].shift(1).fillna(0)              # duració de la petició d'abans
    net = (gap - pd.to_timedelta(previous_ms, unit="ms")).clip(lower=pd.Timedelta(0)).fillna(pd.Timedelta(0))

    # Hora nova = hora de la primera petició de la sessió + suma de les pauses netes fins aquí
    start = sessions["timestamp"].transform("min")
    shifted = start + net.groupby(steps["session_id"]).cumsum()

    result = df.copy()
    result.loc[steps.index, "timestamp"] = shifted
    return result


def successful(df):
    """Les peticions que van anar bé (2xx), per aprendre'n els valors dels {id} de la ruta.

    Així el pla no torna a fer servir un id que va donar 404. No es filtra:
    - si el log no té status (no se sap què va fallar);
    - una petició sense status a la línia (no se sap si va fallar);
    - una petició (mètode + endpoint) que no té cap 2xx: si no, sortiria del pla i JMeter faria servir 1.
    """
    if not has_column(df, "status"):
        return df
    ok = df["status"].between(200, 299) | df["status"].isna()
    any_ok = ok.groupby(request_keys(df)).transform("any")
    return df[ok | ~any_ok]


def error_rates(df):
    """{"POST /api/transfers": {"requests": 540, "4xx": 0.02, "5xx": 0.0}, ...}, de les línies amb status."""
    if not has_column(df, "status"):
        return {}
    known = df.dropna(subset=["status"])
    result = {}
    for key, group in known.groupby(request_keys(known)):
        result[key] = {
            "requests": int(len(group)),
            "4xx": round(float(group["status"].between(400, 499).mean()), 4),
            "5xx": round(float(group["status"].between(500, 599).mean()), 4),
        }
    return result


def reference_durations(df):
    """{"GET /api/accounts/{id}": {"requests": 3122, "p50_ms": 2.0, "p95_ms": 7.0}, ...}: quant triga l'app avui."""
    if not has_column(df, "duration_ms"):
        return {}
    known = df.dropna(subset=["duration_ms"])
    result = {}
    for key, group in known.groupby(request_keys(known)):
        result[key] = {
            "requests": int(len(group)),
            "p50_ms": round(float(group["duration_ms"].quantile(0.5)), 3),
            "p95_ms": round(float(group["duration_ms"].quantile(0.95)), 3),
        }
    return result
