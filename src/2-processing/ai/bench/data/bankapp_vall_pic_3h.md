# bankapp_vall_pic_3h.jsonl

Log de referència del benchmark de la capa d'IA (encàrrec T-BASE). L'ha escrit la bankapp real, amb trànsit
del simulador sense modificar.

| | |
|---|---|
| Fitxer | `bankapp_vall_pic_3h.jsonl`, 12.811 línies, SHA-256 `76b7ecd7949d5ba8423644be27d4d7ed2009084f0b4284be62091198899c3a2c` |
| Bankapp | `src/1-input/java-app-mock` a develop `f0bcad352d540494e387181e3863282ae6dff40b`, compilada amb el Maven wrapper (Java 21.0.2) |
| Simulador | `src/3-execution/simulador/simulador.py` a `51a9324834a8ef17b52704237bed0f9c560e712d`, sense cap canvi (SHA-256 `c17042f0…9a47e`, igual que el del commit) |
| Inici | 2026-10-28 19:23:47 UTC (bankapp a punt i simulador A engegat) |
| Final | 2026-10-28 22:24:03 UTC (els dos simuladors acabats) |
| Primera / última petició | 19:23:56.59 UTC / 22:23:48.94 UTC |

## Càrrega: vall, pic, vall

Dues còpies del simulador contra la mateixa bankapp:

| Còpia | Des de | `CLIENTES` | `MINUTOS` | Peticions |
|---|---|---|---|---|
| A | minut 0 (19:23:47) | 3 | 180 | 7.704 |
| B | minut 60 (20:23:47) | 6 | 60 | 5.107 |

Primera hora 3 clients, segona hora 9, tercera hora 3: unes 425 peticions cada 10 minuts a les valls i unes 1.280
al pic. Les dues còpies sumen exactament les línies del log.

## Comanda

La bankapp s'engega amb `java -jar bankapp-0.0.1-SNAPSHOT.jar --server.port=<port lliure>` des d'una carpeta buida
(escriu `logs/bankapp.jsonl` allà). Sense cap petició de salut: s'espera la línia `Started` de la sortida, perquè
el log només tingui trànsit del simulador. Cada còpia del simulador:

```
BANKAPP=http://127.0.0.1:<port> CLIENTES=<n> MINUTOS=<m> python -I simulador.py
```

Tot plegat ho va llançar un script del taller amb `caffeinate -dims`, amb el Mac endollat. Un batec cada 5 s
comprova que el Mac no s'ha adormit: el forat més gran entre batecs va ser de 5,1 s, i `pmset -g log` no mostra
cap adormiment durant l'execució. (Un primer intent amb el Mac amb bateria es va adormir i es va descartar.)

## Comprovacions

- `parse_logs` el llegeix sencer: 12.811 de 12.811 línies.
- `hourly_js` és numèric (4 franges horàries); contra el mateix trànsit repartit pla dona 0,17.
- Codis: 200, 201 i 204; cap error.
- Les línies no estan del tot en ordre de temps: 3 línies tenen una hora anterior a la de la línia d'abans, i hi ha
  3 hores repetides. `parse_logs` les ordena; qui llegeixi el fitxer pel seu compte ho ha de fer igual.
- Sense dades personals: les altes d'usuari surten amb `body` `{}`, i els únics textos són els conceptes fixos del
  simulador (`Nómina`, `Cena`…). Cap correu, nom ni identificador real.

## Annex: el llançador, tal com va córrer

Per poder tornar a fer el log des del repo (`python -I llancador.py`, amb `JAR` i `SIM` apuntant al jar de `f0bcad3` i al simulador de `51a9324`). Un error seu, que no toca el log: a `meta.json` anota el final de cada simulador quan acaba **A**, perquè els espera en ordre; per això hi diu que B va acabar a les 22:24:03. De fet B va acabar a les 21:24:15 UTC (hora de l'últim canvi del seu `sim_B.out`).

```python
"""Log de referència del T-BASE: bankapp de develop (f0bcad3) + simulador de 51a9324 sense modificar.

Vall-pic-vall en 3 h (acordat amb el Bernat el 2026-10-27):
  - còpia A: CLIENTES=3, MINUTOS=180, des del minut 0;
  - còpia B: CLIENTES=6, MINUTOS=60, des del minut 60.
No es fa cap petició de salut: s'espera la línia "Started" de la bankapp, perquè el log només tingui
trànsit del simulador.

Primer intent (12:01 UTC) invàlid: el Mac es va adormir i time.sleep no compta el temps adormit. Ara
l'espera va pel rellotge de paret, i un batec cada 5 s (heartbeat.txt) deixa veure qualsevol adormiment.
"""
import threading
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

S = Path(__file__).resolve().parent
JAR = S / "ref/bankapp/target/bankapp-0.0.1-SNAPSHOT.jar"
SIM = S / "simulador.py"
RUN = S / "run3h_b"
COPIES = [("A", 0, 3, 180), ("B", 60, 6, 60)]   # (nom, minut d'inici, CLIENTES, MINUTOS)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def note(meta, key, value):
    meta[key] = value
    (RUN / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{now()} {key} = {value}", flush=True)


def heartbeat(stop):
    """Una línia cada 5 s amb l'hora de paret; un forat gran vol dir que el Mac s'ha adormit."""
    with open(RUN / "heartbeat.txt", "w", encoding="utf-8") as beats:
        while not stop.is_set():
            beats.write(f"{time.time():.1f}\n")
            beats.flush()
            stop.wait(5)


def main():
    RUN.mkdir()
    meta = {}
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(stop,), daemon=True).start()
    port = free_port()
    out = open(RUN / "app.out", "w", encoding="utf-8")
    app = subprocess.Popen(["java", "-jar", str(JAR), f"--server.port={port}"], cwd=RUN, stdout=out,
                           stderr=subprocess.STDOUT)
    deadline = time.time() + 180
    while "Started " not in (RUN / "app.out").read_text(encoding="utf-8", errors="replace"):
        if app.poll() is not None or time.time() > deadline:
            sys.exit("la bankapp no ha arrencat (vegeu app.out)")
        time.sleep(1)
    note(meta, "bankapp_port", port)
    note(meta, "bankapp_started", now())

    t0 = time.time()
    running = []
    for name, start_min, clients, minutes in COPIES:
        while time.time() < t0 + start_min * 60:   # pel rellotge de paret, no per un sol time.sleep llarg
            time.sleep(1)
        env = {**os.environ, "BANKAPP": f"http://127.0.0.1:{port}", "CLIENTES": str(clients),
               "MINUTOS": str(minutes)}
        log = open(RUN / f"sim_{name}.out", "w", encoding="utf-8")
        running.append((name, subprocess.Popen([sys.executable, "-I", str(SIM)], env=env, stdout=log,
                                               stderr=subprocess.STDOUT)))
        note(meta, f"sim_{name}", {"start": now(), "CLIENTES": clients, "MINUTOS": minutes})

    for name, process in running:
        process.wait()
        note(meta, f"sim_{name}_end", {"end": now(), "returncode": process.returncode})

    app.terminate()
    app.wait(timeout=60)
    note(meta, "bankapp_stopped", now())
    stop.set()
    beats = [float(x) for x in (RUN / "heartbeat.txt").read_text().split()]
    note(meta, "heartbeat_max_gap_s", round(max(b - a for a, b in zip(beats, beats[1:])), 1))


if __name__ == "__main__":
    main()
```
