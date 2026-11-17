"""Banc de proves: la balança per pesar cada millora (A sense la millora, B amb, sobre el mateix log).

- echo_server.py: el servidor de prova de l'equip (tools/demo_server.py, sense modificar-lo) que, a més,
  escriu el trànsit rebut en el format de log del projecte (es torna a llegir amb parse_logs);
- jmeter.py:      llança JMeter en mode -n i en llegeix el .jtl;
- jmx.py:         les ajudes per llegir i escriure el .jmx (per instrumentar-ne una còpia);
- metrics.py:     fidelitat (log original contra trànsit generat) i acceptació (% de 2xx);
- bankapp.py:     la bankapp d'origin/develop, treta amb git archive a l'espai temporal;
- run.py:         R execucions (aparellades si es comparen dos plans) amb interval de confiança.

Els plans es fan amb main.py. Les mètriques necessiten scipy, que no és al requirements.txt de l'equip:
s'instal·la a part a l'entorn virtual (pip install scipy).

Ús, des de src/2-processing: python -m bench --help
"""
