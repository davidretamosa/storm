"""Un log d'un sol tipus de visita que navega a l'atzar: el control negatiu dels grups (T-2, idea de la consultora).

    python -m ai.bench.one_type_log --log ai/bench/data/bankapp_vall_pic_3h.jsonl --seed 0 --out un_tipus.jsonl

S'aprèn UNA sola cadena de Markov del log (build_markov_model i build_think_times dels companys) i se'n
treuen tantes sessions com en té el log, cadascuna a la mateixa hora d'inici i amb el mateix usuari que una
d'original. Totes les visites venen del mateix model, però amb seqüències molt diferents. Si --ai-groups hi
troba grups, el pla s'ha de comportar igual que sense la millora.

- Les línies sense sessió (iniciar-la, tancar-la) es copien tal qual.
- Cada petició nova copia una línia del log amb la mateixa petició (ruta, body, codi, mides), triada a l'atzar;
  només li canvien l'hora, la sessió i l'usuari.
- La llavor fixa el resultat. Les claus es recorren ordenades: no depèn de PYTHONHASHSEED.
"""
import argparse
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from traffic_model.markov import END


def pick(rng, distribution):
    keys = sorted(distribution)
    weights = np.array([distribution[k] for k in keys], dtype=float)
    return keys[rng.choice(len(keys), p=weights / weights.sum())]


def walk(rng, model, think_times):
    """[(petició, pausa en ms abans d'ella)] d'una sessió de la cadena."""
    steps = [(pick(rng, model["start"]), 0)]
    while len(steps) < model["max_steps"]:
        current = steps[-1][0]
        following = pick(rng, model["transitions"].get(current) or {END: 1.0})
        if following == END:
            break
        pauses = think_times.get(current, {}).get(following) or [0]
        steps.append((following, pauses[rng.integers(len(pauses))]))
    return steps


def one_type_log(log, seed=0):
    """Les línies (diccionaris en el format del log) del log d'un sol tipus, en ordre de temps."""
    from log_parser.parser import parse_logs
    from traffic_model.markov import build_markov_model
    from traffic_model.think_time import build_think_times

    df = parse_logs(log)
    model = build_markov_model(df)
    think_times = build_think_times(df)

    lines = [json.loads(line) for line in Path(log).read_text(encoding="utf-8").splitlines() if line.strip()]
    with_session = [line for line in lines if line.get("sessionId")]
    by_request = {}
    for line in with_session:
        by_request.setdefault(f"{line['method']} {line['endpoint']}", []).append(line)
    # Inici i usuari de cada sessió original, en ordre de temps
    first = {}
    for line in sorted(with_session, key=lambda l: l["timestamp"]):
        first.setdefault(line["sessionId"], line)

    rng = np.random.default_rng(seed)
    output = [line for line in lines if not line.get("sessionId")]
    for session, opening in first.items():
        moment = pd.Timestamp(opening["timestamp"])
        for request, pause_ms in walk(rng, model, think_times):
            moment += timedelta(milliseconds=int(pause_ms))
            examples = by_request[request]
            line = dict(examples[rng.integers(len(examples))])
            line.update({"timestamp": moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "sessionId": session,
                         "userId": opening.get("userId"), "requestId": f"{session}-{len(output)}"})
            output.append(line)
    return sorted(output, key=lambda l: pd.Timestamp(l["timestamp"]))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m ai.bench.one_type_log", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", required=True, help="log d'on s'aprèn la cadena")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True, help="on s'escriu el log nou (JSON Lines)")
    opts = parser.parse_args(argv)
    lines = one_type_log(opts.log, opts.seed)
    Path(opts.out).write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines), encoding="utf-8")
    print(f"{opts.out}: {len(lines)} línies, {len({l['sessionId'] for l in lines if l.get('sessionId')})} sessions")


if __name__ == "__main__":
    main()
