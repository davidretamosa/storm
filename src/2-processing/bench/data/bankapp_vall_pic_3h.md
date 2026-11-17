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

## Problemes coneguts (mesurats el 2026-11-17)

El log **no s'edita ni es filtra**: aquí només es documenta. Cada xifra s'ha tornat a mesurar el 2026-11-17
sobre aquest fitxer i el codi de `f4a299f` (comandes des de `src/2-processing`). Les de reproducció surten
de la línia de base de sota (els 10 `.jtl` d'acceptació, `<sortida>/exec_*/*/acceptacio/acceptacio.jtl`).

1. **Les altes surten amb `body {}`.** 241 `POST /api/users` i 241 `POST /api/accounts`, totes 201 i totes
   amb `body {}`.
   - La bankapp sí que va rebre el cos: `requestSizeBytes` de 56 a 76 a les d'usuari i de 36 a les de compte.
   - El filtre de log de la bankapp només deixa passar `amount`, `concept`, `accountId`, `receptorID`,
     `fromAccountId` i `toAccountId` (`RequestLoggingFilter.java:38-45` a `origin/develop`). Per això es
     perden `name`, `email`, `iban` i `userId`.
   - En reproduir-les, fallen: **378 de 378 `POST /api/users` i 351 de 351 `POST /api/accounts` donen 400**.
   - És feina del T-3.

   ```
   python -c "import json,collections as c;r=[json.loads(l) for l in open('bench/data/bankapp_vall_pic_3h.jsonl')];[print(k,len(s),c.Counter(x['status'] for x in s),c.Counter(json.dumps(x['body']) for x in s),min(x['requestSizeBytes'] for x in s),max(x['requestSizeBytes'] for x in s)) for k in ('/api/users','/api/accounts') for s in [[x for x in r if x['method']=='POST' and x['endpoint']==k]]]"
   git show origin/develop:src/1-input/java-app-mock/src/main/java/com/pae/bankapp/logging/RequestLoggingFilter.java | sed -n 38,45p
   ```
2. **Els 400 de les transferències no són al log.** Les 540 `POST /api/transfers` són 200, i cap té
   origen = destí.
   - En reproduir-les, **264 de 822 donen 400 (32,1 %)**.
   - Motiu: el model de bodies tria cada camp per separat (`field_model`, `traffic_model/payloads.py:170-189`
     a `f4a299f`; la línia 173 que se citava és de la branca vella). Amb les freqüències del log,
     P(origen = destí) = Σ p_origen · p_destí = 0,333. La bankapp rebutja origen = destí.
   - La correlació de la Maria (`markov_common.groovy:198-210`) canviaria `fromAccountId` pel compte creat a
     la mateixa visita, però contra la bankapp les altes de compte fallen (punt 1) i no se'n crea cap.
   - És feina del T-3.

   ```
   python -c "import json,collections as c;r=[json.loads(l) for l in open('bench/data/bankapp_vall_pic_3h.jsonl')];t=[x for x in r if x['method']=='POST' and x['endpoint']=='/api/transfers'];print(len(t),c.Counter(x['status'] for x in t),sum(x['body']['fromAccountId']==x['body']['toAccountId'] for x in t))"
   python -c "from log_parser.parser import parse_logs;from traffic_model.payloads import build_body_models;b=build_body_models(parse_logs('bench/data/bankapp_vall_pic_3h.jsonl'),None)['POST /api/transfers'];f=dict(b['fromAccountId']['values']);t=dict(b['toAccountId']['values']);print(round(sum(f[k]*t.get(k,0) for k in f),3))"
   ```
3. **3 línies desordenades:** 456 (0,031 ms), 5460 (0,613 ms) i 6662 (0,003 ms), totes per menys d'1 ms.
   `parse_logs` ja les ordena (`log_parser/parser.py:135`).

   ```
   python -c "import json;from datetime import datetime as d;t=[d.fromisoformat(json.loads(l)['timestamp']) for l in open('bench/data/bankapp_vall_pic_3h.jsonl')];[print(i+1,(t[i-1]-t[i]).total_seconds()*1000,'ms') for i in range(1,len(t)) if t[i]<t[i-1]]"
   ```
4. **`meta.json` dona malament el final de la còpia B** (22:24:03; de fet, 21:24:15 UTC; vegeu l'annex).
   - No és al repo, i el banc no el llegeix.
   - El `meta.json` ja no és a la màquina i no s'ha pogut tornar a obrir. Sí que es pot veure al log: les
     peticions per minut passen de 124 (21:23) a 51 (21:24) i es queden a la vall fins al final. Això
     concorda amb 21:24:15 i no amb 22:24:03.

   ```
   python -c "import json,collections as c;n=c.Counter(json.loads(l)['timestamp'][11:19] for l in open('bench/data/bankapp_vall_pic_3h.jsonl'));print([(m,sum(v for k,v in n.items() if k.startswith(m))) for m in ('21:22','21:23','21:24','21:25')])"
   ```
5. **Els ids ≥ 100 són les altes del simulador** i no existeixen en una bankapp nova.
   - `data.sql` (`origin/develop`) crea usuaris i comptes 1–3, i els autoincrements comencen a 100.
   - Als camins del log (sense els de sessió) hi ha 482 ids ≥ 100, de 5.899.
   - En reproduir-ho surten 404: 86 a `GET /api/accounts/{id}` (1,9 %) i 86 a
     `POST /api/accounts/{id}/deposit` (9,0 %). Al model de rutes, la probabilitat d'un id ≥ 100 és de
     l'1,6 % i del 10,1 %.

   ```
   python -c "import json,re,collections as c;n=c.Counter(('>=100' if int(m)>=100 else m) for l in open('bench/data/bankapp_vall_pic_3h.jsonl') for x in [json.loads(l)] if not x['endpoint'].startswith('/api/sessions') for m in re.findall(r'/(\d+)(?=/|$)',x['path']));print(n)"
   git show origin/develop:src/1-input/java-app-mock/src/main/resources/data.sql
   ```

## Línia de base sobre `f4a299f`

> ⚠️ **Mesurada a la nit, amb càrrega**: mentre corria, a la mateixa màquina corrien el control negatiu del
> banc (un altre banc sencer) i, durant una estona, el verificador amb els tests del banc (JMeter curt). La
> central la farà tornar a passar amb el Mac quiet. Les xifres de temps (pauses i durades) són les que més hi
> poden haver patit.

- **Data:** 2026-11-17, de 02:35:39 a 04:19:50 UTC.
- **Codi:** la cadena a `f4a299f` (`feature/processing-ia2`); el banc a `bc3f2c7`. El commit següent,
  `89b145c`, només canvia el nom del `HeaderManager` del banc i com es resol `--bankapp-jar`, i no canvia les
  peticions.
- **Bankapp:** `origin/develop` a `517ea3ab0b0eaafd46fe7cc5d0154722ad6309fd`, compilada amb `--bankapp-build`.
- **Entorn:** Python 3.15.1, numpy 2.5.5, pandas 3.1.1, scipy 1.18.1, jinja2 3.1.6; JMeter 5.6.3; Java 21.0.2.
- **Pla (A = B):** sha256 `1b72f6373e5dab930d518dc44e286129f7c13274ec1861016c3edfd58af2ee60`.
- **Comanda**, des de `src/2-processing`:

  ```
  python -m bench --log bench/data/bankapp_vall_pic_3h.jsonl \
    --plan "--logs bench/data/bankapp_vall_pic_3h.jsonl --session --session-users 1,2,3" \
    --vs   "--logs bench/data/bankapp_vall_pic_3h.jsonl --session --session-users 1,2,3" \
    --runs 5 --acceptance --bankapp-build --out <carpeta fora del repo>
  ```

Mitjana [interval de confiança del 95 %] de 5 execucions aparellades. Distàncies: 0 = idèntic al log.

| mètrica | A | B | diferència B − A |
|---|---|---|---|
| endpoint_js | 0.03177 [0.01988, 0.04367] | 0.02834 [0.01854, 0.03813] | -0.003434 [-0.01531, 0.008445] |
| hourly_js | 0.149 [0.1288, 0.1692] | 0.1548 [0.1408, 0.1688] | 0.005798 [-0.02723, 0.03882] |
| sequence_js | 0.05441 [0.04316, 0.06566] | 0.05012 [0.04005, 0.06019] | -0.004294 [-0.0185, 0.009908] |
| pauses_wasserstein_s | 0.1691 [0.06652, 0.2718] | 0.1704 [0.07527, 0.2656] | 0.001307 [-0.1828, 0.1854] |
| pauses_ks | 0.05415 [0.04485, 0.06346] | 0.05177 [0.04081, 0.06274] | -0.002379 [-0.0187, 0.01394] |
| session_length_wasserstein | 0.4732 [0.4228, 0.5235] | 0.5002 [0.4411, 0.5593] | 0.02705 [-0.04126, 0.09536] |
| session_length_ks | 0.2338 [0.1988, 0.2687] | 0.2487 [0.2228, 0.2747] | 0.01494 [-0.03365, 0.06354] |
| session_duration_wasserstein_s | 1.007 [0.7191, 1.296] | 1.033 [0.7936, 1.272] | 0.02519 [-0.4735, 0.5238] |
| session_duration_median_generated_s | 2.839 [2.6, 3.078] | 2.731 [2.429, 3.033] | -0.1078 [-0.5815, 0.3659] |
| sessions_generated | 423.2 [392.3, 454.1] | 434.4 [420.6, 448.2] | 11.2 [-28.76, 51.16] |
| requests_generated | 994 [937.3, 1051] | 1009 [975.6, 1042] | 14.6 [-74.01, 103.2] |
| concurrent_sessions_generated_mean | 6.361 [6.359, 6.364] | 6.366 [6.34, 6.391] | 0.004183 [-0.02033, 0.0287] |
| active_threads_mean | 6.698 [6.679, 6.718] | 6.732 [6.686, 6.778] | 0.03338 [-0.02468, 0.09145] |
| active_threads_peak | 7 [7, 7] | 7 [7, 7] | 0 [0, 0] |
| acceptance_pct_2xx | 91.87 [90.72, 93.02] | 91.9 [90.86, 92.94] | 0.02654 [-0.6697, 0.7228] |

**Control positiu:** A i B són el mateix pla, i l'interval de la diferència inclou el 0 a totes les mètriques.

**Control negatiu del banc** (Addenda 1 de l'encàrrec): el mateix A, i B = A + `--max-steps 2` (sha256
`f046e7b2e1f9b3831b579cd4c7ad2142ab0c5bdc1b7bce39094619181bdbdc65`); 5 execucions, només fidelitat, de 02:36:01
a 03:27:39 UTC, a la vegada que la línia de base. B − A queda fora de l'interval a la llargada i la durada de
les sessions, i a les pauses no:

| mètrica | diferència B − A |
|---|---|
| session_length_wasserstein | 0.2253 [0.164, 0.2865] |
| session_length_ks | 0.3928 [0.3712, 0.4144] |
| session_duration_wasserstein_s | 1.283 [0.9737, 1.592] |
| session_duration_median_generated_s | -1.192 [-1.445, -0.9398] |
| pauses_wasserstein_s | -0.0006241 [-0.09518, 0.09394] |

(`--default-pause 0-0`, que deia l'encàrrec al principi, no canvia el pla amb aquest log: totes les
transicions ja tenen pauses apreses, `traffic_model/think_time.py:84-95`, i els dos `.jmx` surten idèntics.)

**Dues mesures amb JMeter real**, que s'apunten i no s'arreglen:
- **`X-Storm-Bench` arriba al servidor eco** amb el `request_headers.groovy` de la Maria al pla: 14.301 de
  14.301 línies dels 10 `rebut.jsonl` de la línia de base porten `sessionId` = `<fil>-<iteració>`, diferent
  de l'`X-Session-Id` de l'app.
- **Durada real de cada corrida** amb `duration` 300 (del «Starting standalone test» al «Tidying up» del
  `jmeter.out`): de 302,7 a 309,8 s a les 20 corrides de la línia de base, i de 302,5 a 309,0 s a les 10 del
  control negatiu. El `Thread.sleep` de la pausa (`next_request.groovy:40`) allarga la prova entre 3 i 10 s
  per sobre de `duration`.

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
