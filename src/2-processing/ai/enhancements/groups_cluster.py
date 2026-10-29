"""Grups de visita (T-2): agrupar les sessions i decidir si de debò n'hi ha més d'un.

    find_groups(df, seed) -> ({sessió: grup}, informe)

1. KMeans sobre les característiques de cada sessió (groups_features.py), escalades, amb la k de 2 a 8 que
   dona més silueta. La llavor (--ai-seed) fixa el resultat.
2. Dos grups que naveguen igual es fusionen: Jensen-Shannon entre els seus parells (inici, petició, següent,
   fi) per sota de SAME_NAVIGATION. Un grup que només es diferencia per la pausa no canvia les seqüències.
   Un grup de menys de MIN_GROUP sessions no es pot validar (no en queden per als trossos de prova): es fusiona
   amb el grup que navega més com ell.
3. Porta de validació: els grups s'han de guanyar el lloc prediint visites que no han vist. Amb 4 de 5 trossos
   es fan els grups i una cadena per grup; amb el 5è es compara el model del pla (triar un grup pel seu pes i
   seguir-ne la cadena) amb una sola cadena. Si de mitjana els grups no prediuen millor, queda un sol grup.

scikit-learn i scipy es carreguen aquí dins (ai/requirements.txt), com fa ai/bench/metrics.py.
"""
from collections import Counter

import numpy as np

from ai.enhancements.groups_features import session_features, session_sequences, session_steps
from traffic_model.markov import END, build_markov_model

MAX_GROUPS = 8
SAME_NAVIGATION = 0.2   # decidit pel Bernat al pla del T-2
FOLDS = 5
MIN_GROUP = 2 * FOLDS   # el mateix mínim de sessions que demana find_groups per validar res
FLOOR = 1e-6            # probabilitat mínima d'una transició mai vista, igual per a tots els models
START = "<inici>"


def cluster(matrix, seed, max_groups=MAX_GROUPS):
    """(etiquetes, k, {k: silueta}): KMeans amb la k de més silueta. Tot 0 si no hi ha prou sessions diferents."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    n = len(matrix)
    distinct = len(np.unique(matrix, axis=0))
    top = min(max_groups, distinct, n - 1)   # la silueta demana 2 <= k <= n - 1
    if top < 2:
        return np.zeros(n, dtype=int), 1, {}

    scaled = StandardScaler().fit_transform(matrix)
    sample = 3000 if n > 3000 else None      # la silueta és quadràtica: a partir d'aquí, una mostra fixa
    best, silhouettes = None, {}
    for k in range(2, top + 1):
        labels = KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(scaled)
        silhouettes[k] = float(silhouette_score(scaled, labels, sample_size=sample, random_state=seed))
        if best is None or silhouettes[k] > silhouettes[best[0]]:
            best = (k, labels)
    return best[1], best[0], silhouettes


def navigation(sequences):
    """Recompte dels parells (petició, següent) d'unes sessions, amb l'inici i el final."""
    counts = Counter()
    for sequence in sequences:
        keys = [START, *sequence, END]
        counts.update(zip(keys, keys[1:]))
    return counts


def js_distance(a, b):
    """Jensen-Shannon (base 2, de 0 a 1) entre dos recomptes."""
    from scipy.spatial import distance

    keys = sorted(set(a) | set(b))
    p = np.array([a.get(k, 0) for k in keys], dtype=float)
    q = np.array([b.get(k, 0) for k in keys], dtype=float)
    return float(distance.jensenshannon(p / p.sum(), q / q.sum(), base=2))


def merge_alike(labels, sequences, threshold=SAME_NAVIGATION, min_size=MIN_GROUP):
    """(etiquetes, fusions): fusiona, d'una en una,
    - la parella de grups que navega més igual, mentre la seva distància sigui menor que `threshold`;
    - després, el grup més petit amb menys de `min_size` sessions, amb el que navega més com ell."""
    labels = np.array(labels)
    merges = []
    while True:
        groups = sorted(set(labels.tolist()))
        if len(groups) < 2:
            return labels, merges
        counts = {g: navigation(s for s, label in zip(sequences, labels) if label == g) for g in groups}
        sizes = {g: int((labels == g).sum()) for g in groups}
        distance = {(a, b): js_distance(counts[a], counts[b]) for i, a in enumerate(groups) for b in groups[i + 1:]}
        js, a, b = min((d, a, b) for (a, b), d in distance.items())
        reason = "navega igual"
        if js >= threshold:
            small = min(groups, key=lambda g: (sizes[g], g))
            if sizes[small] >= min_size:
                return labels, merges
            js, a, b = min((d, *pair) for pair, d in distance.items() if small in pair)
            reason = f"massa petit ({sizes[small]} sessions)"
        keep, gone = (a, b) if sizes[a] >= sizes[b] else (b, a)
        labels[labels == gone] = keep
        merges.append({"groups": [int(keep), int(gone)], "js": round(js, 4), "why": reason})


def group_labels(steps, ids, seed):
    """Agrupament + fusió d'unes sessions: (etiquetes en l'ordre de `ids`, informe)."""
    steps = steps[steps["session_id"].isin(set(ids))]
    matrix, _ = session_features(steps, ids)
    labels, k, silhouettes = cluster(matrix, seed)
    sequences = session_sequences(steps, ids)
    labels, merges = merge_alike(labels, [sequences[i] for i in ids])
    return labels, {"k": k, "silhouettes": silhouettes, "merges": merges}


def log_likelihood(sequence, model):
    """log P(sessió) segons una cadena de build_markov_model (inici, transicions i END)."""
    total = np.log(model["start"].get(sequence[0], 0) + FLOOR)
    for current, following in zip(sequence, [*sequence[1:], END]):
        total += np.log(model["transitions"].get(current, {}).get(following, 0) + FLOOR)
    return total


def split(ids, seed, folds=FOLDS):
    """[(entrenament, prova)] per a cada tros: cada sessió és a la prova d'un sol tros i mai al seu entrenament."""
    order = np.random.default_rng(seed).permutation(len(ids)) % folds
    return [([s for s, f in zip(ids, order) if f != fold], [s for s, f in zip(ids, order) if f == fold])
            for fold in range(folds)]


def heldout_gain(steps, ids, seed, chain=None, folds=FOLDS):
    """Per a cada tros: quant millor prediuen els grups les visites que no han vist que una sola cadena
    (log-versemblança mitjana per visita; > 0 vol dir que els grups ajuden).

    chain: els arguments de build_markov_model del pla (min_probability, endpoints, jar_weight), perquè les
    cadenes que es validen siguin com les que hi aniran."""
    chain = chain or {}
    sequences = session_sequences(steps, ids)
    gains = []
    for train, test in split(ids, seed, folds):
        labels, _ = group_labels(steps, train, seed)

        one = build_markov_model(steps[steps["session_id"].isin(set(train))], **chain)
        groups = sorted(set(labels.tolist()))
        models, weights = [], []
        for g in groups:
            members = {s for s, label in zip(train, labels) if label == g}
            models.append(build_markov_model(steps[steps["session_id"].isin(members)], **chain))
            weights.append(len(members) / len(train))

        gain = []
        for session in test:
            mixture = np.logaddexp.reduce([np.log(w) + log_likelihood(sequences[session], m)
                                           for w, m in zip(weights, models)])
            gain.append(mixture - log_likelihood(sequences[session], one))
        gains.append(float(np.mean(gain)))
    return gains


def find_groups(df, seed=0, chain=None):
    """({sessió: grup}, informe). Els grups van de 0 (el més gran) a n - 1; tot 0 vol dir un sol grup.

    chain: els arguments de build_markov_model del pla, per a la porta de validació (heldout_gain)."""
    steps, ids = session_steps(df)
    report = {"sessions": len(ids)}
    if len(ids) < 2 * FOLDS:
        report["one_group"] = f"massa poques sessions ({len(ids)}) per validar grups"
        return dict.fromkeys(ids, 0), report

    labels, info = group_labels(steps, ids, seed)
    report.update(info)
    if len(set(labels.tolist())) > 1:
        gains = heldout_gain(steps, ids, seed, chain)
        report["heldout_gain"] = gains
        if np.mean(gains) <= 0:
            report["one_group"] = "els grups no prediuen millor les visites noves que una sola cadena"
            labels = np.zeros(len(ids), dtype=int)
    elif all(merge["why"] == "navega igual" for merge in report["merges"]):
        report["one_group"] = "tots els grups naveguen igual"
    else:
        report["one_group"] = "els grups naveguen igual o són massa petits per validar-los"

    # Grup 0 = el més gran (empat: el que surt abans), perquè el resultat es llegeixi igual cada vegada
    sizes = Counter(labels.tolist())
    order = sorted(sizes, key=lambda g: (-sizes[g], labels.tolist().index(g)))
    rename = {old: new for new, old in enumerate(order)}
    report["sizes"] = [sizes[g] for g in order]
    return {session: rename[label] for session, label in zip(ids, labels.tolist())}, report
