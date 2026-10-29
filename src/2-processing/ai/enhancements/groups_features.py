"""Grups de visita (T-2): què fa cada sessió, en números, per poder-les agrupar.

Només fa servir columnes del log (mètode, endpoint, hora, codi de resposta): res de cap app en concret.
Les sessions són les mateixes que veu la cadena de Markov dels companys (get_steps de traffic_model/markov.py).
"""
import numpy as np
import pandas as pd

from traffic_model.markov import get_steps


def session_steps(df):
    """Les peticions de cada sessió en ordre de temps (la taula de get_steps) i els ids de sessió per
    ordre d'aparició."""
    steps = get_steps(df)
    return steps, list(steps["session_id"].unique())


def session_sequences(steps, ids):
    """{sessió: [petició, petició, ...]}, p. ej. {"s1": ["GET /a", "POST /b"]}."""
    sequences = steps.groupby("session_id", sort=False)["key"].agg(list)
    return {session: sequences[session] for session in ids}


def session_features(steps, ids):
    """(matriu sessions × característiques, noms de les columnes), una fila per sessió en l'ordre de `ids`:

    - quantes vegades fa cada petició (`mètode endpoint`);
    - la longitud (nombre de peticions);
    - la pausa mitjana entre peticions, en log(1 + segons) (0 si només en fa una);
    - la part de respostes 4xx;
    - si ha creat algun recurs (alguna resposta 201).
    """
    grouped = steps.groupby("session_id", sort=False)
    counts = pd.crosstab(steps["session_id"], steps["key"]).reindex(ids)

    length = grouped.size().reindex(ids)
    pause = grouped["timestamp"].apply(lambda t: t.diff().dt.total_seconds().mean()).reindex(ids).fillna(0)

    status = pd.to_numeric(steps["status"], errors="coerce") if "status" in steps else pd.Series(np.nan, steps.index)
    errors = status.between(400, 499).groupby(steps["session_id"], sort=False).mean().reindex(ids)
    creates = (status == 201).groupby(steps["session_id"], sort=False).any().reindex(ids)

    matrix = np.column_stack([
        counts.to_numpy(dtype=float),
        length.to_numpy(dtype=float),
        np.log1p(pause.clip(lower=0).to_numpy(dtype=float)),
        errors.to_numpy(dtype=float),
        creates.to_numpy(dtype=float),
    ])
    names = [*counts.columns, "<longitud>", "<pausa_log>", "<taxa_4xx>", "<crea>"]
    return matrix, names
