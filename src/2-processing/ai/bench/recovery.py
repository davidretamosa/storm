"""Grups de visita (T-2) al banc: la recuperació dels perfils del simulador i les sessions senceres.

    python -m ai.bench.recovery --log ai/bench/data/bankapp_vall_pic_3h.jsonl [--seed 0]
    python -m ai.bench.recovery --bench <carpeta d'un `python -m ai.bench`>

1. Recuperació (--log): s'etiqueta cada sessió amb el perfil del simulador de 3-execution que la va fer, per
   la signatura de la seva seqüència, i es mira si els grups que troba --ai-groups hi coincideixen (ARI).
   Les etiquetes són de la bankapp i del seu simulador: viuen NOMÉS aquí, mai a la resta de ai/.
2. Sessions senceres (--bench): sobre el trànsit que el banc ja ha desat a cada execució (rebut.jsonl),
   - session_js: Jensen-Shannon entre el repartiment de sessions senceres (la seqüència completa) del log i
     del trànsit generat (sequence_js de metrics.py només mira parells, que el Markov ja reprodueix);
   - la longitud de les sessions (Wasserstein i KS, com metrics.py);
   i, si hi ha dos plans, la diferència aparellada B - A amb interval de confiança. No toca run.py ni metrics.py.
"""
import argparse
import json
import shlex
from collections import Counter
from pathlib import Path

from ai.bench import metrics
from ai.bench.run import ROOT, plan_options

# Signatura de la sessió (les peticions en ordre, sense iniciar ni tancar sessió) -> perfil del simulador
# (src/3-execution/simulador/simulador.py a 51a9324). nuevo_cliente fa dues sessions: l'alta, amb la sessió
# d'un empleat, i el compte nou, amb la del client; amb sessions soles no es poden ajuntar.
SIGNATURES = {
    ("GET /api/accounts/{id}",): "curioso",
    ("GET /api/users/{id}", "GET /api/accounts/{id}", "GET /api/accounts/{id}/transactions"): "revisor",
    ("GET /api/accounts/{id}", "POST /api/accounts/{id}/deposit", "GET /api/accounts/{id}"): "ahorrador",
    ("GET /api/accounts/{id}", "POST /api/transfers", "GET /api/accounts/{id}/transactions"): "pagador",
    ("GET /api/accounts/{id}", "POST /api/transfers", "GET /api/accounts/{id}/transactions",
     "POST /api/accounts/{id}/withdraw"): "pagador",
    ("POST /api/users",): "nuevo_cliente:alta",
    ("POST /api/accounts", "POST /api/accounts/{id}/deposit", "GET /api/accounts/{id}"): "nuevo_cliente:cuenta",
}
UNKNOWN = "<desconegut>"
ARI_THRESHOLD = 0.85   # contra les 6 etiquetes de sessió (decisió del Bernat al pla del T-2)


def profile(sequence, whole=False):
    """El perfil d'una sessió: 6 etiquetes (l'alta i el compte del nuevo_cliente, separats) o, amb `whole`, els
    5 perfils del simulador."""
    label = SIGNATURES.get(tuple(sequence), UNKNOWN)
    return label.split(":")[0] if whole else label


def recovery(log, seed=0):
    """Els grups de --ai-groups sobre `log` contra els perfils del simulador."""
    from sklearn.metrics import adjusted_rand_score

    from ai.enhancements.groups_cluster import find_groups
    from ai.enhancements.groups_features import session_sequences, session_steps
    from log_parser.parser import parse_logs

    df = parse_logs(log)
    groups, report = find_groups(df, seed)
    steps, ids = session_steps(df)
    sequences = session_sequences(steps, ids)
    found = [groups[s] for s in ids]
    six = [profile(sequences[s]) for s in ids]
    five = [profile(sequences[s], whole=True) for s in ids]

    table = {}
    for group, label in zip(found, six):
        table.setdefault(int(group), Counter())[label] += 1
    return {
        "log": str(log), "seed": seed, "sessions": len(ids), "unknown": six.count(UNKNOWN),
        "groups": len(set(found)), "report": report,
        "ari_6": float(adjusted_rand_score(six, found)),
        "ari_5": float(adjusted_rand_score(five, found)),
        "threshold_6": ARI_THRESHOLD,
        "table": {group: dict(counts.most_common()) for group, counts in sorted(table.items())},
    }


def whole_sessions(df):
    """{seqüència sencera: nombre de sessions} d'una taula de metrics.requests."""
    return Counter(tuple(group["key"]) for group in metrics.sessions(df))


def session_scores(original, generated):
    lengths = metrics.compare_samples(metrics.session_lengths(original), metrics.session_lengths(generated))
    return {"session_js": metrics.js_distance(whole_sessions(original), whole_sessions(generated)),
            "session_length_wasserstein": lengths["wasserstein"], "session_length_ks": lengths["ks"]}


def bench_sessions(folder):
    """session_js i la longitud de cada execució d'un banc ja fet, amb l'interval de confiança."""
    from log_parser.parser import parse_logs

    folder = Path(folder)
    report = json.loads((folder / "resum.json").read_text(encoding="utf-8"))
    log = Path(report["log"]) if Path(report["log"]).is_absolute() else ROOT / report["log"]
    ignore = {}
    for label, plan in report["plans"].items():
        options = plan_options(shlex.split(plan["command"]))
        ignore[label] = [f"POST {options.session_endpoint}"] if options.session else []

    labels = list(report["plans"])
    runs = []
    for run in sorted(folder.glob("exec_*"), key=lambda p: int(p.name.split("_")[1])):
        scores = {}
        for label in labels:
            original = metrics.requests(parse_logs(str(log)), ignore[label])
            received = metrics.requests(parse_logs(str(run / label / "fidelitat" / "rebut.jsonl")), ignore[label])
            scores[label] = session_scores(original, received)
        runs.append(scores)

    names = list(runs[0][labels[0]]) if runs else []
    summary = {label: {n: metrics.confidence_interval([r[label][n] for r in runs]) for n in names}
               for label in labels}
    if len(labels) == 2:
        a, b = labels
        summary["paired_difference"] = {
            n: metrics.confidence_interval([r[b][n] - r[a][n] for r in runs]) for n in names}
    return {"folder": str(folder), "log": str(log), "runs": runs, "summary": summary}


def markdown(result):
    if "ari_6" in result:
        lines = [f"# Recuperació · `{result['log']}` · llavor {result['seed']}", "",
                 f"- sessions: {result['sessions']} (sense perfil conegut: {result['unknown']})",
                 f"- grups trobats: {result['groups']}",
                 f"- **ARI contra les 6 etiquetes de sessió: {result['ari_6']:.3f}** (llindar {result['threshold_6']})",
                 f"- ARI contra els 5 perfils del simulador: {result['ari_5']:.3f} (només s'informa)", "",
                 "| grup | sessions per etiqueta |", "|---|---|"]
        lines += [f"| {g} | {counts} |" for g, counts in result["table"].items()]
        return "\n".join(lines) + "\n"
    blocks = result["summary"]
    lines = [f"# Sessions senceres · `{result['folder']}`", "", "| mètrica | " + " | ".join(blocks) + " |",
             "|---|" + "---|" * len(blocks)]
    for name in next(iter(blocks.values())):
        cells = [f"{b[name]['mean']:.4g} [{b[name]['low']:.4g}, {b[name]['high']:.4g}]" for b in blocks.values()]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "Mitjana [interval de confiança del 95 %]. Distàncies: 0 = idèntic al log."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m ai.bench.recovery", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", help="log on mesurar la recuperació dels perfils")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bench", help="carpeta d'un banc ja fet on mesurar les sessions senceres")
    opts = parser.parse_args(argv)
    if not opts.log and not opts.bench:
        parser.error("cal --log, --bench o els dos")

    results = []
    if opts.log:
        results.append(recovery(str(ROOT / opts.log) if not Path(opts.log).is_absolute() else opts.log, opts.seed))
    if opts.bench:
        result = bench_sessions(opts.bench)
        Path(opts.bench, "sessions.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        Path(opts.bench, "sessions.md").write_text(markdown(result), encoding="utf-8")
        results.append(result)
    for result in results:
        print(markdown(result))
    return results


if __name__ == "__main__":
    main()
