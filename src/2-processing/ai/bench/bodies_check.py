"""Les xifres del T-3 (bodies realistes) sobre la carpeta d'un `python -m ai.bench --vs ...` ja fet.

    python -m ai.bench.bodies_check <carpeta del banc> [--log ai/bench/data/bankapp_vall_pic_3h.jsonl]

NOMÉS per a la bankapp (per això viu a ai/bench/): coneix les seves transferències i els seus correus.
No torna a llançar res: llegeix el que el banc ha deixat a la carpeta.

- acceptació amb body: % de 2xx a la bankapp dels samplers que envien ${stormBody} (del .jmx);
- origen = destí: transferències del trànsit rebut pel servidor eco amb fromAccountId == toAccountId;
- correus repetits: altes d'usuari del trànsit rebut amb un email que ja havia sortit;
- imports: KS i Wasserstein contra els imports de les peticions 2xx del log, per endpoint;
- errors al jmeter.log: línies ERROR (totes, i les de Groovy/JSR223).
Per a cada mesura, A i B amb interval de confiança i la diferència B - A aparellada (com el banc).
"""
import argparse
import json
from pathlib import Path

from ai import jmx_post
from ai.bench import jmeter, metrics

ROOT = Path(__file__).resolve().parents[2]   # src/2-processing
LOG = "ai/bench/data/bankapp_vall_pic_3h.jsonl"
TRANSFERS = "POST /api/transfers"
USERS = "POST /api/users"
AMOUNT = "amount"


def body_samplers(plan):
    """Els noms dels samplers que envien ${stormBody}."""
    root = jmx_post.read(plan).getroot()
    labels = set()
    for sampler in root.iter("HTTPSamplerProxy"):
        values = [prop.text for prop in sampler.iter("stringProp") if prop.get("name") == "Argument.value"]
        if "${stormBody}" in values:
            labels.add(sampler.get("testname"))
    return labels


def acceptance_with_body(jtl, labels):
    rows = jtl[jtl["label"].isin(labels)] if not jtl.empty else jtl
    if rows.empty:
        return float("nan"), 0
    return float(rows["responseCode"].str.startswith("2").mean() * 100), int(len(rows))


def bodies_of(df, request):
    keys = df["method"] + " " + df["endpoint"]
    return [body for body in df[keys == request]["body"] if isinstance(body, dict)]


def same_account(received):
    bodies = bodies_of(received, TRANSFERS)
    same = sum(1 for b in bodies if "fromAccountId" in b and b.get("fromAccountId") == b.get("toAccountId"))
    return same, len(bodies)


def repeated_emails(received):
    emails = [b["email"] for b in bodies_of(received, USERS) if b.get("email")]
    return len(emails) - len(set(emails)), len(emails)


def amounts(df, request):
    return [b[AMOUNT] for b in bodies_of(df, request) if isinstance(b.get(AMOUNT), (int, float))]


def amount_distances(original, received):
    good = original[original["status"].between(200, 299)]
    result = {}
    for request in sorted(set(good["method"] + " " + good["endpoint"])):
        reference = amounts(good, request)
        if reference:
            result[request] = metrics.compare_samples(reference, amounts(received, request))
    return result


def jmeter_errors(log):
    if not log.exists():
        return float("nan"), float("nan")
    lines = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if " ERROR " in line]
    groovy = [line for line in lines if any(word in line for word in ("JSR223", "groovy", "Groovy", "STORM-IA"))]
    return len(lines), len(groovy)


def check_run(folder, labels, original):
    from log_parser.parser import parse_logs

    result = {}
    received_file = folder / "fidelitat" / "rebut.jsonl"
    if received_file.exists():
        received = parse_logs(str(received_file))
        result["same_account"], result["transfers"] = same_account(received)
        result["repeated_emails"], result["emails"] = repeated_emails(received)
        result["amounts"] = amount_distances(original, received)
        result["errors_fidelity"], result["groovy_errors_fidelity"] = jmeter_errors(folder / "fidelitat" / "jmeter.log")
    jtl_file = folder / "acceptacio" / "acceptacio.jtl"
    if jtl_file.exists():
        jtl = jmeter.read_jtl(jtl_file)
        result["acceptance_body"], result["body_samples"] = acceptance_with_body(jtl, labels)
        result["acceptance_by_sampler"] = metrics.acceptance(jtl)["by_sampler"]
        result["errors_acceptance"], result["groovy_errors_acceptance"] = jmeter_errors(
            folder / "acceptacio" / "jmeter.log")
    return result


def scalars(result):
    """Les xifres d'una execució que es resumeixen amb interval de confiança."""
    values = {name: result.get(name, float("nan")) for name in
              ("acceptance_body", "same_account", "repeated_emails", "groovy_errors_fidelity",
               "groovy_errors_acceptance")}
    for request, distance in result.get("amounts", {}).items():
        values[f"amount_ks {request}"] = distance["ks"]
        values[f"amount_wasserstein {request}"] = distance["wasserstein"]
    return values


def summarize(runs, labels):
    names = sorted({name for run in runs for label in labels for name in scalars(run[label])})
    summary = {label: {name: metrics.confidence_interval([scalars(run[label]).get(name, float("nan")) for run in runs])
                       for name in names} for label in labels}
    if len(labels) == 2:
        a, b = labels
        summary["paired_difference"] = {
            name: metrics.confidence_interval([scalars(run[b]).get(name, float("nan"))
                                               - scalars(run[a]).get(name, float("nan")) for run in runs])
            for name in names}
    return summary


def markdown(summary):
    blocks = list(summary)
    lines = ["| mètrica | " + " | ".join(blocks) + " |", "|---|" + "---|" * len(blocks)]
    for name in summary[blocks[0]]:
        cells = []
        for block in blocks:
            ci = summary[block][name]
            cells.append("—" if ci["n"] == 0 else f"{ci['mean']:.4g} [{ci['low']:.4g}, {ci['high']:.4g}]")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    from log_parser.parser import parse_logs

    parser = argparse.ArgumentParser(prog="python -m ai.bench.bodies_check", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", help="carpeta de sortida del banc (--out)")
    parser.add_argument("--log", default=LOG, help="log original (els imports es comparen amb les seves 2xx)")
    opts = parser.parse_args(argv)

    folder = Path(opts.folder)
    labels = sorted(path.stem.split("_")[1] for path in folder.glob("pla_?.jmx"))
    samplers = set().union(*(body_samplers(folder / f"pla_{label}.jmx") for label in labels))
    log = Path(opts.log) if Path(opts.log).is_absolute() else ROOT / opts.log
    original = parse_logs(str(log))

    runs = []
    for run_folder in sorted(folder.glob("exec_*"), key=lambda p: int(p.name.split("_")[1])):
        runs.append({label: check_run(run_folder / label, samplers, original) for label in labels})

    report = {"folder": str(folder), "log": str(log), "body_samplers": sorted(samplers), "runs": runs,
              "summary": summarize(runs, labels)}
    (folder / "bodies_check.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    text = markdown(report["summary"])
    (folder / "bodies_check.md").write_text(text, encoding="utf-8")
    print(text)
    return report


if __name__ == "__main__":
    main()
