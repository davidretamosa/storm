"""Grupos de visita: tipos de sesión que se parecen (los que solo leen, los que crean cosas...).

Cada sesión del log se describe con una fila de números (qué peticiones hace y cuántas veces,
cuántas hace en total, lo larga que es la pausa entre ellas, qué parte acaba en 4xx y si crea algo).
Después se agrupan las filas con KMeans (scikit-learn), probando de 2 a MAX_GROUPS grupos y
quedándose con el número que da más silueta (lo bien separados que quedan los grupos).

La función que usa main.py (con --visit-groups) es find_visit_groups(), y describe() es el texto
que escribe. Si el log no tiene sesiones no se hacen grupos: el plan es el de la cadena.
"""
import numpy as np
import pandas as pd

from traffic_model.markov import get_steps

SEED = 0                 # semilla fija: el mismo log da siempre los mismos grupos
MAX_GROUPS = 8           # k de 2 a 8
KMEANS_RUNS = 10         # n_init del KMeans
SILHOUETTE_SAMPLE = 3000 # a partir de aquí, la silueta se calcula sobre una muestra fija

# Columnas de la tabla que no son peticiones (entre <> para que no choquen con "GET /a")
LENGTH = "<longitud>"
PAUSE = "<pausa_log>"
RATE_4XX = "<taxa_4xx>"
CREATES = "<crea>"


def has_sessions(df):
    """True si el log tiene al menos una petición con sessionId (sin lanzar nada si no)."""
    return (
        df is not None
        and not df.empty
        and "session_id" in df.columns
        and bool(df["session_id"].notna().any())
    )


def session_table(df):
    """Una fila de números por sesión. Solo se llama si has_sessions(df).

    Devuelve (ids, sequences, matrix, names):
    - ids: los session_id, por orden de aparición;
    - sequences: {sesión: ["GET /a", "POST /b", ...]}, en orden de tiempo;
    - matrix: numpy float, una fila por sesión (en el orden de ids) y una columna por nombre de names;
    - names: una columna por petición (cuántas veces la hace, en orden alfabético) y después
      <longitud>, <pausa_log>, <taxa_4xx> y <crea>.
    """
    # Las peticiones sin sessionId quedan fuera (get_steps solo quita los nulos: "" es una sesión)
    steps = get_steps(df)
    ids = list(steps["session_id"].unique())
    by_session = steps.groupby("session_id", sort=False)

    sequences = {session: list(keys) for session, keys in by_session["key"]}

    # Cuántas veces hace cada petición cada sesión
    counts = pd.crosstab(steps["session_id"], steps["key"]).reindex(ids).sort_index(axis=1)

    # Número de peticiones
    length = by_session.size().reindex(ids)

    # Pausa media entre peticiones seguidas, en bruto (aquí no se resta la duración: solo sirve
    # para separar visitas lentas de rápidas). Negativas a 0; con una sola petición, 0.
    gaps = by_session["timestamp"].diff().dt.total_seconds().clip(lower=0)
    pause = np.log1p(gaps.groupby(steps["session_id"], sort=False).mean().reindex(ids).fillna(0))

    # Respuestas: parte en 4xx y si alguna crea algo (201). Un status nulo no es 4xx.
    if "status" in steps.columns:
        status = pd.to_numeric(steps["status"], errors="coerce")
    else:
        status = pd.Series(np.nan, index=steps.index)
    is_4xx = status.between(400, 499).astype(float)
    is_201 = (status == 201).astype(float)
    rate_4xx = is_4xx.groupby(steps["session_id"], sort=False).mean().reindex(ids).fillna(0)
    creates = is_201.groupby(steps["session_id"], sort=False).max().reindex(ids).fillna(0)

    table = counts.copy()
    table[LENGTH] = length
    table[PAUSE] = pause
    table[RATE_4XX] = rate_4xx
    table[CREATES] = creates
    table = table.fillna(0)

    names = list(table.columns)
    matrix = table.to_numpy(dtype=float)
    return ids, sequences, matrix, names


def cluster_sessions(matrix, seed=SEED, max_groups=MAX_GROUPS):
    """Agrupa las filas con KMeans y elige el número de grupos k por silueta.

    Prueba k de 2 a top = min(max_groups, filas diferentes, filas - 1) (la silueta pide 2 <= k <= n - 1)
    y se queda con la k de más silueta; si empatan, la más pequeña.
    Devuelve (labels, k, silhouettes), con silhouettes = {k: silueta}. Si no se puede agrupar
    (top < 2), todo es un grupo: (ceros, 1, {}).
    """
    # Dentro de la función: con --visit-groups apagado, main.py no carga scikit-learn
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    n = len(matrix)
    top = min(max_groups, len(np.unique(matrix, axis=0)), n - 1)
    if top < 2:
        return np.zeros(n, dtype=int), 1, {}

    # Cada columna con media 0 y desviación 1, para que ninguna pese más solo por su escala
    scaled = StandardScaler().fit_transform(matrix)
    sample = SILHOUETTE_SAMPLE if n > SILHOUETTE_SAMPLE else None

    labels_by_k = {}
    silhouettes = {}
    for k in range(2, top + 1):
        labels = KMeans(n_clusters=k, n_init=KMEANS_RUNS, random_state=seed).fit_predict(scaled)
        labels_by_k[k] = labels
        silhouettes[k] = float(silhouette_score(scaled, labels, sample_size=sample, random_state=seed))

    # La de más silueta; si empatan, la k más pequeña
    best = max(silhouettes, key=lambda k: (silhouettes[k], -k))
    return labels_by_k[best], best, silhouettes


def find_visit_groups(df, chain=None):
    """Los grupos de visita del log: (groups, report).

    - groups: {session_id: grupo}, con los grupos numerados de 0 (el más grande) en adelante;
      si dos tienen el mismo tamaño, va antes el que aparece antes en el log.
    - report: {"sessions", "k", "silhouettes", "sizes"} y, con un solo grupo o ninguno,
      "one_group" (el motivo).

    `chain` (los argumentos de build_markov_model del plan) aún no se usa: lo usará la puerta de
    validación (T-2.2). No escribe nada; el texto lo hace describe().
    """
    if not has_sessions(df):
        return {}, {"sessions": 0, "one_group": "el log no tiene sesiones"}

    ids, _, matrix, _ = session_table(df)
    labels, k, silhouettes = cluster_sessions(matrix)

    # Renumerar: 0 el grupo más grande; si empatan, el que sale antes en ids
    labels = list(labels)
    first_seen = {}
    for position, label in enumerate(labels):
        first_seen.setdefault(label, position)
    sizes_by_label = {label: labels.count(label) for label in first_seen}
    order = sorted(first_seen, key=lambda label: (-sizes_by_label[label], first_seen[label]))
    number = {label: n for n, label in enumerate(order)}

    groups = {session: number[label] for session, label in zip(ids, labels)}
    report = {
        "sessions": len(ids),
        "k": k,
        "silhouettes": silhouettes,
        "sizes": [sizes_by_label[label] for label in order],
    }
    if k == 1:
        report["one_group"] = "todas las sesiones son iguales"
    return groups, report


def describe(report):
    """El texto que escribe main.py después de "Grupos de visita: "."""
    if report["sessions"] == 0:
        return "ninguno (el log no tiene sesiones); el plan es el de la cadena"
    if "one_group" in report:
        return f"1 ({report['one_group']}); el plan es el de la cadena"
    sizes = ", ".join(str(size) for size in report["sizes"])
    return f"{len(report['sizes'])} ({sizes} sesiones)"
