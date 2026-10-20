"""R execucions de JMeter amb un pla (o dos, aparellats) i les seves mètriques amb interval de confiança.

    python -m ai.bench --log samples/access_sample.log --runs 5 --out sortida/ \\
        --plan "--logs samples/access_sample.log" [--vs "--ai-traffic --logs samples/access_sample.log"] \\
        [--acceptance --bankapp-jar bankapp.jar | --acceptance --bankapp-build] [--prop duration=60]

- El pla es genera amb `python -m ai <--plan>` en un subprocés amb PYTHONHASHSEED=0.
- Fidelitat: JMeter contra el servidor eco amb una còpia instrumentada del pla (capçalera X-Storm-Bench =
  fil-iteració, per saber de quina sessió és cada petició); es compara el trànsit rebut amb --log.
- Acceptació: JMeter amb el pla tal qual contra una bankapp acabada d'arrencar a cada execució.
- Amb --vs, les execucions van aparellades i alternades (A B, B A, A B...) i es dona la diferència B - A
  de cada parell amb el seu interval de confiança. L'atzar de JMeter no es pot fixar: per això R >= 5.
"""
import argparse
import hashlib
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from ai import jmx_post
from ai.bench import bankapp, jmeter, metrics
from ai.bench.echo_server import BENCH_HEADER

ROOT = Path(__file__).resolve().parents[2]   # src/2-processing

# Les xifres que es resumeixen amb interval de confiança: (nom, camí dins del resultat)
SCALARS = [
    ("endpoint_js", ("fidelity", "endpoint_js")),
    ("hourly_js", ("fidelity", "hourly_js")),
    ("sequence_js", ("fidelity", "sequence_js")),
    ("pauses_wasserstein_s", ("fidelity", "pauses", "wasserstein")),
    ("pauses_ks", ("fidelity", "pauses", "ks")),
    ("session_length_wasserstein", ("fidelity", "session_length", "wasserstein")),
    ("session_length_ks", ("fidelity", "session_length", "ks")),
    ("session_duration_wasserstein_s", ("fidelity", "session_duration", "wasserstein")),
    ("session_duration_median_generated_s", ("fidelity", "session_duration", "median_generated")),
    ("sessions_generated", ("fidelity", "sessions_generated")),
    ("requests_generated", ("fidelity", "requests_generated")),
    ("concurrent_sessions_generated_mean", ("fidelity", "concurrency_generated", "mean")),
    ("active_threads_mean", ("fidelity", "active_threads", "mean")),
    ("active_threads_peak", ("fidelity", "active_threads", "peak")),
    ("acceptance_pct_2xx", ("acceptance", "total")),
]


def generate_plan(plan_args, output):
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    command = [sys.executable, "-m", "ai", *plan_args, "--output", str(output)]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"no s'ha pogut generar el pla: {result.stderr}")
    return {"command": f"PYTHONHASHSEED=0 python -m ai {shlex.join(plan_args)} --output {output.name}",
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def instrument(plan, output):
    """Còpia del pla amb una capçalera que diu de quina sessió és cada petició (fil-iteració de JMeter).

    Només per al servidor eco: no canvia ni el recorregut ni les pauses. Element estàndard (HeaderManager).
    """
    tree = jmx_post.read(plan)
    root = tree.getroot()
    thread_group = root.find(".//ThreadGroup")
    children = jmx_post.child_tree(root, thread_group)
    manager = ET.Element("HeaderManager", {"guiclass": "HeaderPanel", "testclass": "HeaderManager",
                                            "testname": "STORM-IA banc: sessió"})
    headers = ET.SubElement(manager, "collectionProp", {"name": "HeaderManager.headers"})
    header = ET.SubElement(headers, "elementProp", {"name": "", "elementType": "Header"})
    header.append(jmx_post.string_prop("Header.name", BENCH_HEADER))
    header.append(jmx_post.string_prop("Header.value", "${__threadNum}-${__groovy(vars.getIteration())}"))
    children.insert(0, manager)
    children.insert(1, ET.Element("hashTree"))
    jmx_post.write(tree, output)


def plan_options(plan_args):
    """Del que es passa a main.py, el que el banc necessita saber: --jar, --session i el seu endpoint."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--jar")
    parser.add_argument("--session", action="store_true")
    parser.add_argument("--session-endpoint", default="/api/sessions")
    opts, _ = parser.parse_known_args(plan_args)
    return opts


def fidelity_run(plan, log, options, folder, properties, original_df):
    from log_parser.parser import parse_logs

    folder.mkdir(parents=True, exist_ok=True)
    port = bankapp.free_port()
    received = folder / "rebut.jsonl"
    command = [sys.executable, "-m", "ai.bench.echo_server", "--out", str(received), "--port", str(port),
               "--logs", str(log)]
    if options.jar:
        command += ["--jar", options.jar]
    if options.session:
        command.append("--require-session")
    with open(folder / "servidor.out", "w", encoding="utf-8") as out:
        server = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
        try:
            _wait_for_port(port, server)
            code, output = jmeter.run(plan, folder / "fidelitat.jtl", folder / "jmeter.log",
                                      {"host": "127.0.0.1", "port": port, **properties})
        finally:
            server.send_signal(signal.SIGINT)
            server.wait(timeout=30)
    (folder / "jmeter.out").write_text(output, encoding="utf-8")
    if code != 0:
        raise RuntimeError(f"JMeter ha acabat amb {code} (vegeu {folder / 'jmeter.out'})")
    ignore = [f"POST {options.session_endpoint}"] if options.session else []
    jtl = jmeter.read_jtl(folder / "fidelitat.jtl")
    return metrics.fidelity(original_df, parse_logs(str(received)), jtl, ignore)


def acceptance_run(plan, jar, folder, properties):
    folder.mkdir(parents=True, exist_ok=True)
    with bankapp.Bankapp(jar, folder / "bankapp.out") as app:
        code, output = jmeter.run(plan, folder / "acceptacio.jtl", folder / "jmeter.log",
                                  {"host": "127.0.0.1", "port": app.port, **properties})
    (folder / "jmeter.out").write_text(output, encoding="utf-8")
    if code != 0:
        raise RuntimeError(f"JMeter ha acabat amb {code} (vegeu {folder / 'jmeter.out'})")
    return metrics.acceptance(jmeter.read_jtl(folder / "acceptacio.jtl"))


def _wait_for_port(port, process, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("el servidor eco s'ha aturat en arrencar")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError("el servidor eco no ha arrencat")


def scalar(result, path):
    value = result
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return float("nan")
        value = value[key]
    return value


def summarize(runs, labels):
    summary = {label: {name: metrics.confidence_interval([scalar(r[label], path) for r in runs])
                       for name, path in SCALARS} for label in labels}
    if len(labels) == 2:
        a, b = labels
        summary["paired_difference"] = {
            name: metrics.confidence_interval([scalar(r[b], path) - scalar(r[a], path) for r in runs])
            for name, path in SCALARS}
    return summary


def markdown(report):
    lines = [f"# Banc STORM-IA · {report['started']}", "", f"- log: `{report['log']}`",
             f"- execucions: {report['runs']}", f"- propietats de JMeter: `{report['properties']}`", ""]
    for label, plan in report["plans"].items():
        lines.append(f"- pla **{label}**: `{plan['command']}` · sha256 `{plan['sha256']}`")
    lines += ["", "| mètrica | " + " | ".join(report["summary"]) + " |",
              "|---|" + "---|" * len(report["summary"])]
    for name, _ in SCALARS:
        cells = []
        for block in report["summary"].values():
            ci = block[name]
            cells.append("—" if ci["n"] == 0 else f"{ci['mean']:.4g} [{ci['low']:.4g}, {ci['high']:.4g}]")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "Mitjana [interval de confiança del 95 %]. Distàncies: 0 = idèntic al log."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m ai.bench", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", required=True, help="log original contra el qual es mesura la fidelitat")
    parser.add_argument("--plan", required=True, help="arguments de `python -m ai` per al pla A (entre cometes)")
    parser.add_argument("--vs", help="arguments del pla B, per comparar-lo aparellat amb A")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", help="carpeta de resultats (per defecte, una de temporal)")
    parser.add_argument("--no-fidelity", action="store_true", help="no mesurar la fidelitat")
    parser.add_argument("--acceptance", action="store_true", help="mesurar l'acceptació contra la bankapp")
    parser.add_argument("--bankapp-jar", help=".jar de la bankapp ja compilat")
    parser.add_argument("--bankapp-build", action="store_true",
                        help="treure la bankapp d'origin/develop amb git archive i compilar-la")
    parser.add_argument("--prop", action="append", default=[], help="propietat de JMeter, p. ex. duration=60")
    opts = parser.parse_args(argv)

    out = Path(opts.out or tempfile.mkdtemp(prefix="storm-bench-")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    properties = dict(p.split("=", 1) for p in opts.prop)
    plans_args = {"A": shlex.split(opts.plan)}
    if opts.vs:
        plans_args["B"] = shlex.split(opts.vs)
    labels = list(plans_args)

    report = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "log": opts.log,
              "runs": opts.runs, "properties": properties, "plans": {}, "bankapp": None}
    plans, bench_plans, options = {}, {}, {}
    for label, args in plans_args.items():
        plans[label] = out / f"pla_{label}.jmx"
        report["plans"][label] = generate_plan(args, plans[label])
        bench_plans[label] = out / f"pla_{label}_banc.jmx"
        instrument(plans[label], bench_plans[label])
        options[label] = plan_options(args)

    jar = opts.bankapp_jar
    if opts.acceptance and not jar:
        if not opts.bankapp_build:
            parser.error("--acceptance necessita --bankapp-jar o --bankapp-build")
        directory, commit = bankapp.extract(out)
        jar = bankapp.build(directory)
        report["bankapp"] = {"ref": "origin/develop", "commit": commit}
    if opts.acceptance:
        report["bankapp"] = {**(report["bankapp"] or {}), "jar": str(jar)}

    from log_parser.parser import parse_logs
    original_df = parse_logs(str(ROOT / opts.log) if not Path(opts.log).is_absolute() else opts.log)

    runs = []
    for r in range(opts.runs):
        order = labels if r % 2 == 0 else list(reversed(labels))   # alternat: A B, B A, ...
        results = {}
        for label in order:
            folder = out / f"exec_{r + 1}" / label
            result = {}
            if not opts.no_fidelity:
                result["fidelity"] = fidelity_run(bench_plans[label], ROOT / opts.log, options[label],
                                                  folder / "fidelitat", properties, original_df)
            if opts.acceptance:
                result["acceptance"] = acceptance_run(plans[label], jar, folder / "acceptacio", properties)
            results[label] = result
            print(f"execució {r + 1}/{opts.runs} pla {label}: fet", flush=True)
        runs.append(results)
        (out / "execucions.json").write_text(json.dumps(runs, indent=1, default=str), encoding="utf-8")

    report["summary"] = summarize(runs, labels)
    (out / "resum.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out / "resum.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    print(f"Resultats a {out}")
    return report
