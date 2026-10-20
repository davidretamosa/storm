"""Mètriques de la balança (D-4). Sempre el log original contra el trànsit generat.

Totes les funcions reben DataFrames de `parse_logs` (el log original i el trànsit que ha rebut el servidor
eco) i, per als fils actius, el .jtl de JMeter. Distàncies: 0 = idèntic.

- endpoints:  Jensen-Shannon (base 2, entre 0 i 1) entre el repartiment de peticions per endpoint;
- franja:     Jensen-Shannon entre la forma de la corba temporal: el log es parteix en franges d'una hora
              i el trànsit generat en el mateix nombre de franges iguals (la prova dura minuts, no hores);
              si el log no arriba a dues franges, NaN (no hi ha corba per comparar);
- pauses:     segons entre peticions consecutives d'una sessió, amb Wasserstein (s) i KS;
- sessions:   peticions per sessió i durada (s), amb Wasserstein i KS;
- seqüències: Jensen-Shannon entre els parells (petició, següent) incloent-hi l'inici i el final de sessió;
- fils actius: sessions simultànies del log contra fils actius del .jtl (mitjana i pic).

scipy es carrega aquí dins (ai/requirements.txt), no a la resta de la capa.
"""
import numpy as np
import pandas as pd

START, END = "<inici>", "<fi>"


def _scipy():
    from scipy import stats
    from scipy.spatial import distance
    return stats, distance


def requests(df, ignore=()):
    """Les peticions que compten: sense les de `ignore` (p. ex. 'POST /api/sessions', fora del model)."""
    keys = df["method"] + " " + df["endpoint"]
    return df.assign(key=keys)[~keys.isin(list(ignore))].sort_values("timestamp", kind="stable")


def js_distance(a, b):
    """Jensen-Shannon (base 2) entre dos recomptes {clau: n}; les claus que falten valen 0."""
    _, distance = _scipy()
    keys = sorted(set(a) | set(b))
    p = np.array([a.get(k, 0) for k in keys], dtype=float)
    q = np.array([b.get(k, 0) for k in keys], dtype=float)
    if p.sum() == 0 or q.sum() == 0:
        return float("nan")
    return float(distance.jensenshannon(p / p.sum(), q / q.sum(), base=2))


def endpoint_distance(original, generated):
    return js_distance(original["key"].value_counts().to_dict(), generated["key"].value_counts().to_dict())


def time_bins(df, bins):
    """Recompte de peticions en `bins` franges iguals entre la primera i l'última."""
    seconds = (df["timestamp"] - df["timestamp"].min()).dt.total_seconds().to_numpy()
    span = seconds.max() if len(seconds) and seconds.max() > 0 else 1.0
    index = np.minimum((seconds / span * bins).astype(int), bins - 1)
    return dict(zip(*np.unique(index, return_counts=True)))


def hourly_distance(original, generated):
    hours = original["timestamp"].dt.floor("h")
    bins = max(1, int((hours.max() - hours.min()) / pd.Timedelta(hours=1)) + 1)
    if bins < 2:   # un log de menys d'una hora no té corba horària: un 0 aquí no voldria dir res
        return float("nan"), bins
    return js_distance(time_bins(original, bins), time_bins(generated, bins)), bins


def sessions(df):
    """Les peticions agrupades per sessió (les que no en tenen, fora)."""
    return [group for _, group in df.dropna(subset=["session_id"]).groupby("session_id", sort=False)]


def pauses(df):
    values = []
    for group in sessions(df):
        values.extend(group["timestamp"].diff().dt.total_seconds().dropna().tolist())
    return np.array(values)


def session_lengths(df):
    return np.array([len(group) for group in sessions(df)])


def session_durations(df):
    return np.array([(g["timestamp"].max() - g["timestamp"].min()).total_seconds() for g in sessions(df)])


def bigrams(df):
    counts = {}
    for group in sessions(df):
        keys = [START, *group["key"].tolist(), END]
        for pair in zip(keys, keys[1:]):
            counts[pair] = counts.get(pair, 0) + 1
    return counts


def compare_samples(a, b):
    stats, _ = _scipy()
    if len(a) == 0 or len(b) == 0:
        return {"wasserstein": float("nan"), "ks": float("nan"), "median_original": float("nan"),
                "median_generated": float("nan")}
    return {
        "wasserstein": float(stats.wasserstein_distance(a, b)),
        "ks": float(stats.ks_2samp(a, b).statistic),
        "median_original": float(np.median(a)),
        "median_generated": float(np.median(b)),
    }


def concurrent_sessions(df):
    """Sessions obertes alhora (de la primera a l'última petició): mitjana ponderada pel temps i pic."""
    events = []
    for group in sessions(df):
        events.append((group["timestamp"].min(), 1))
        events.append((group["timestamp"].max(), -1))
    if not events:
        return {"mean": float("nan"), "peak": 0}
    events.sort(key=lambda e: (e[0], -e[1]))
    level, peak, area = 0, 0, 0.0
    previous = events[0][0]
    for time, change in events:
        area += level * (time - previous).total_seconds()
        level += change
        peak = max(peak, level)
        previous = time
    total = (events[-1][0] - events[0][0]).total_seconds()
    return {"mean": area / total if total > 0 else float(peak), "peak": peak}


def active_threads(jtl, step_seconds=10):
    """Fils actius al .jtl (columna allThreads): mitjana, pic i la línia de temps per trams de `step_seconds`."""
    if jtl is None or jtl.empty:
        return {"mean": float("nan"), "peak": 0, "timeline": [], "requests_timeline": []}
    seconds = (jtl["timeStamp"] - jtl["timeStamp"].min()) / 1000.0
    step = (seconds // step_seconds).astype(int)
    timeline = jtl.groupby(step)["allThreads"].max()
    requests_per_step = jtl.groupby(step).size()
    return {
        "mean": float(jtl["allThreads"].mean()),
        "peak": int(jtl["allThreads"].max()),
        "last_request_s": float(seconds.max()),
        "timeline": [[int(i) * step_seconds, int(v)] for i, v in timeline.items()],
        "requests_timeline": [[int(i) * step_seconds, int(v)] for i, v in requests_per_step.items()],
    }


def fidelity(original_df, generated_df, jtl=None, ignore=()):
    """Totes les mètriques de fidelitat d'una execució."""
    original = requests(original_df, ignore)
    generated = requests(generated_df, ignore)
    hourly, bins = hourly_distance(original, generated)
    return {
        "requests_original": int(len(original)),
        "requests_generated": int(len(generated)),
        "endpoint_js": endpoint_distance(original, generated),
        "hourly_js": hourly,
        "hourly_bins": bins,
        "pauses": compare_samples(pauses(original), pauses(generated)),
        "session_length": compare_samples(session_lengths(original), session_lengths(generated)),
        "session_duration": compare_samples(session_durations(original), session_durations(generated)),
        "sessions_original": len(sessions(original)),
        "sessions_generated": len(sessions(generated)),
        "sequence_js": js_distance(bigrams(original), bigrams(generated)),
        "concurrency_original": concurrent_sessions(original),
        "concurrency_generated": concurrent_sessions(generated),
        "active_threads": active_threads(jtl),
    }


def acceptance(jtl):
    """Percentatge de 2xx per sampler i en total (el que la app real accepta)."""
    if jtl is None or jtl.empty:
        return {"total": float("nan"), "samples": 0, "by_sampler": {}}
    ok = jtl["responseCode"].str.startswith("2")
    by_sampler = {}
    for label, group in jtl.assign(ok=ok).groupby("label"):
        by_sampler[label] = {"samples": int(len(group)), "pct_2xx": float(group["ok"].mean() * 100),
                             "codes": group["responseCode"].value_counts().to_dict()}
    return {"total": float(ok.mean() * 100), "samples": int(len(jtl)), "by_sampler": by_sampler}


def confidence_interval(values, level=0.95):
    """Mitjana i interval de confiança (t de Student) d'una llista de valors."""
    stats, _ = _scipy()
    values = np.array([v for v in values if v == v], dtype=float)  # fora els NaN
    if len(values) == 0:
        return {"n": 0, "mean": float("nan"), "low": float("nan"), "high": float("nan")}
    mean = float(values.mean())
    if len(values) < 2:
        return {"n": 1, "mean": mean, "low": float("nan"), "high": float("nan")}
    half = float(stats.t.ppf((1 + level) / 2, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values)))
    return {"n": int(len(values)), "mean": mean, "low": mean - half, "high": mean + half}
