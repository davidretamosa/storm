"""Grupos de visita: tipos de sesión que se parecen (los que solo leen, los que crean cosas...).

Cada sesión del log se describe con una fila de números (qué peticiones hace y cuántas veces,
cuántas hace en total, lo larga que es la pausa entre ellas, qué parte acaba en 4xx y si crea algo).
Después se agrupan las filas con KMeans (scikit-learn), probando de 2 a MAX_GROUPS grupos y
quedándose con el número que da más silueta (lo bien separados que quedan los grupos).

Luego se aplican tres reglas, para no quedarse con grupos que no sirven:
1. dos grupos que navegan igual (sus pares de peticiones seguidas se parecen) se juntan;
2. un grupo de menos de MIN_GROUP sesiones no se puede validar: se junta con el que más se le parece;
3. la puerta de validación: con 4 de cada 5 trozos se hacen los grupos y una cadena por grupo, y con
   el trozo que queda se mira si los grupos predicen las visitas nuevas mejor que una sola cadena.
   Si de media no lo hacen, queda un solo grupo.

La función que usa main.py (con --visit-groups) es find_visit_groups(), y describe() es el texto
que escribe. Si el log no tiene sesiones no se hacen grupos: el plan es el de la cadena.
"""
from collections import Counter
from itertools import combinations

import numpy as np
import pandas as pd

from traffic_model.markov import END, build_markov_model, get_steps

SEED = 0                 # semilla fija: el mismo log da siempre los mismos grupos
MAX_GROUPS = 8           # k de 2 a 8
KMEANS_RUNS = 10         # n_init del KMeans
SILHOUETTE_SAMPLE = 3000 # a partir de aquí, la silueta se calcula sobre una muestra fija
SAME_NAVIGATION = 0.2    # dos grupos navegan igual si la distancia es menor
MIN_GROUP = 10           # con menos sesiones un grupo no se puede validar
FOLDS = 5                # trozos de la puerta de validación
FLOOR = 1e-6             # probabilidad mínima de una transición nunca vista, la misma para todos los modelos
START = "<inicio>"       # inicio de sesión, para contar los pares (inicio, primera petición)

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


def navigation(sequences):
    """Cuántas veces sale cada par de peticiones seguidas, con el inicio y el final de cada sesión.

    sequences: listas de claves ("GET /a", ...). Cada una cuenta los pares de [START, *sesión, END].
    """
    counts = Counter()
    for sequence in sequences:
        keys = [START, *sequence, END]
        counts.update(zip(keys, keys[1:]))
    return counts


def js_distance(a, b):
    """Distancia de Jensen-Shannon (base 2, de 0 a 1) entre dos recuentos.

    Es la raíz cuadrada de la divergencia (la distancia jensenshannon con base 2 que usa el banco):
    0 si se reparten igual, 1 si no tienen nada en común.
    """
    keys = sorted(set(a) | set(b))
    p = np.array([a.get(key, 0) for key in keys], dtype=float)
    q = np.array([b.get(key, 0) for key in keys], dtype=float)
    p, q = p / p.sum(), q / q.sum()
    m = (p + q) / 2

    def kl(x):
        seen = x > 0
        return float(np.sum(x[seen] * np.log2(x[seen] / m[seen])))

    # max(0, ...): el redondeo no puede dar una raíz de un número negativo
    return float(np.sqrt(max((kl(p) + kl(q)) / 2, 0.0)))


def merge_alike(labels, sequences, threshold=SAME_NAVIGATION, min_size=MIN_GROUP):
    """Las reglas 1 y 2: junta grupos, de uno en uno, hasta que no se aplica ninguna.

    labels: {sesión: grupo}; sequences: {sesión: [claves]}. Devuelve (labels, merges).
    1. "navegan igual": el par de grupos (i, j), i < j, con menos distancia de navegación, si es menor
       que `threshold` (si empatan, el par más pequeño);
    2. "demasiado pequeño": si no, el grupo más pequeño (si empatan, el de número más bajo), si tiene
       menos de `min_size` sesiones, con el grupo del que está más cerca (si empatan, el de número más bajo).
    En cada fusión el grupo grande se queda el número (si empatan, el número más bajo) y el pequeño pasa a él.
    """
    labels = dict(labels)
    merges = []
    while True:
        groups = sorted(set(labels.values()))
        if len(groups) < 2:
            return labels, merges

        members = {group: [session for session, label in labels.items() if label == group] for group in groups}
        sizes = {group: len(members[group]) for group in groups}
        counts = {group: navigation(sequences[session] for session in members[group]) for group in groups}
        # Redondeadas a 12 decimales: dos distancias iguales (p. ej. 1 sin nada en común) pueden salir
        # 1.0 y 0.9999999999999999 según el orden de las sumas, y el empate tiene que contar como empate
        distance = {(i, j): round(js_distance(counts[i], counts[j]), 12) for i, j in combinations(groups, 2)}

        # Regla 1: el par que navega más igual
        js, i, j = min((d, i, j) for (i, j), d in distance.items())
        if js < threshold:
            why = "navegan igual"
        else:
            # Regla 2: el grupo más pequeño, si no llega al mínimo, con el más cercano
            small = min(groups, key=lambda group: (sizes[group], group))
            if sizes[small] >= min_size:
                return labels, merges
            js, other = min((distance[tuple(sorted((small, group)))], group) for group in groups if group != small)
            i, j = small, other
            why = f"demasiado pequeño ({sizes[small]} sesiones)"

        # El grande se queda el número; si tienen el mismo tamaño, el número más bajo
        if sizes[i] > sizes[j] or (sizes[i] == sizes[j] and i < j):
            keep, gone = i, j
        else:
            keep, gone = j, i
        for session in members[gone]:
            labels[session] = keep
        merges.append({"groups": [int(keep), int(gone)], "js": round(js, 4), "why": why})


def group_labels(df, ids, seed=SEED):
    """El agrupamiento (KMeans) y las reglas 1 y 2, solo con las sesiones de `ids`.

    Las columnas de la tabla salen solo de esas sesiones: nada de las demás.
    Devuelve ({sesión: grupo}, {"k", "silhouettes", "merges"}).
    """
    sub = df[df["session_id"].isin(set(ids))]
    names_ids, sequences, matrix, _ = session_table(sub)
    found, k, silhouettes = cluster_sessions(matrix, seed=seed)
    labels = {session: int(label) for session, label in zip(names_ids, found)}
    labels, merges = merge_alike(labels, sequences)
    return labels, {"k": k, "silhouettes": silhouettes, "merges": merges}


def log_likelihood(sequence, model):
    """log P(sesión) según una cadena de build_markov_model: el inicio y cada paso, hasta END.

    Siempre con .get y + FLOOR: una sesión de prueba puede pasar por un estado que el modelo no tiene.
    """
    total = np.log(model["start"].get(sequence[0], 0.0) + FLOOR)
    for current, following in zip(sequence, [*sequence[1:], END]):
        total += np.log(model["transitions"].get(current, {}).get(following, 0.0) + FLOOR)
    return float(total)


def split(ids, seed=SEED, folds=FOLDS):
    """[(entrenamiento, prueba), ...], uno por trozo: cada sesión está en la prueba de un solo trozo
    y nunca en su entrenamiento."""
    order = np.random.default_rng(seed).permutation(len(ids)) % folds
    return [
        ([session for session, f in zip(ids, order) if f != fold],
         [session for session, f in zip(ids, order) if f == fold])
        for fold in range(folds)
    ]


def heldout_gain(df, ids, chain, seed=SEED, folds=FOLDS):
    """La puerta de validación (regla 3): cuánto mejor predicen los grupos las visitas que no han visto
    que una sola cadena, por trozo (log-verosimilitud media por visita; > 0 quiere decir que ayudan).

    Los grupos y las cadenas se hacen solo con el entrenamiento de cada trozo. chain son los argumentos
    de build_markov_model del plan (min_probability, endpoints, jar_weight), para que las cadenas que
    se validan sean como las que irán al plan.
    """
    _, sequences, _, _ = session_table(df[df["session_id"].isin(set(ids))])
    gains = []
    for train, test in split(ids, seed, folds):
        labels, _ = group_labels(df, train, seed)
        one = build_markov_model(df[df["session_id"].isin(set(train))], **chain)

        models, weights = [], []
        for group in sorted(set(labels.values())):
            members = {session for session, label in labels.items() if label == group}
            models.append(build_markov_model(df[df["session_id"].isin(members)], **chain))
            weights.append(len(members) / len(train))

        # Mezcla: se elige un grupo por su peso y se sigue su cadena
        gain = []
        for session in test:
            mixture = np.logaddexp.reduce([np.log(weight) + log_likelihood(sequences[session], model)
                                           for weight, model in zip(weights, models)])
            gain.append(mixture - log_likelihood(sequences[session], one))
        gains.append(float(np.mean(gain)))
    return gains


def find_visit_groups(df, chain=None):
    """Los grupos de visita del log, después de las tres reglas: (groups, report).

    - groups: {session_id: grupo}, con los grupos numerados de 0 (el más grande) en adelante;
      si dos tienen el mismo tamaño, va antes el que aparece antes en el log.
    - report: {"sessions", "sizes"}; si se ha agrupado, también "k", "silhouettes" y "merges"
      (las fusiones de las reglas 1 y 2); si ha pasado por la puerta, "heldout_gain" (la ganancia de
      cada trozo); y, con un solo grupo o ninguno, "one_group" (el motivo).

    `chain` son los argumentos de build_markov_model del plan, para la puerta de validación.
    No escribe nada; el texto lo hace describe().
    """
    if not has_sessions(df):
        return {}, {"sessions": 0, "one_group": "el log no tiene sesiones"}

    # Las sesiones por orden de aparición (como en session_table)
    ids = list(get_steps(df)["session_id"].unique())
    report = {"sessions": len(ids)}

    if len(ids) < 2 * FOLDS:
        labels = dict.fromkeys(ids, 0)
        report["one_group"] = f"demasiado pocas sesiones ({len(ids)}) para validar grupos"
    else:
        labels, info = group_labels(df, ids)
        report.update(info)
        if len(set(labels.values())) > 1:
            report["heldout_gain"] = heldout_gain(df, ids, chain or {})
            if np.mean(report["heldout_gain"]) <= 0:
                labels = dict.fromkeys(ids, 0)
                report["one_group"] = "los grupos no predicen mejor las visitas nuevas que un solo modelo"
        elif info["k"] == 1:
            report["one_group"] = "todas las sesiones son iguales"
        elif all(merge["why"] == "navegan igual" for merge in info["merges"]):
            report["one_group"] = "los grupos navegan igual"
        else:
            report["one_group"] = "los grupos navegan igual o son demasiado pequeños"

    # Renumerar: 0 el grupo más grande; si empatan, el que sale antes en ids
    found = [labels[session] for session in ids]
    first_seen = {}
    for position, label in enumerate(found):
        first_seen.setdefault(label, position)
    sizes_by_label = {label: found.count(label) for label in first_seen}
    order = sorted(first_seen, key=lambda label: (-sizes_by_label[label], first_seen[label]))
    number = {label: n for n, label in enumerate(order)}

    groups = {session: number[label] for session, label in zip(ids, found)}
    report["sizes"] = [sizes_by_label[label] for label in order]
    return groups, report


def describe(report):
    """El texto que escribe main.py después de "Grupos de visita: "."""
    if report["sessions"] == 0:
        return "ninguno (el log no tiene sesiones); el plan es el de la cadena"
    if "one_group" in report:
        return f"1 ({report['one_group']}); el plan es el de la cadena"
    sizes = ", ".join(str(size) for size in report["sizes"])
    return f"{len(report['sizes'])} ({sizes} sesiones)"
