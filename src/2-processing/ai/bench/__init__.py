"""Banc de proves de la capa d'IA: la balança per pesar cada millora (amb IA i sense, D-4).

- echo_server.py: el servidor de prova dels companys (tools/demo_server.py, sense modificar-lo) que, a
  més, escriu el trànsit rebut en el format de log del projecte (es torna a llegir amb parse_logs);
- jmeter.py:      llança JMeter en mode -n i en llegeix el .jtl;
- metrics.py:     fidelitat (log original contra trànsit generat) i acceptació (% de 2xx);
- bankapp.py:     la bankapp d'origin/develop, treta amb git archive a l'espai temporal (NOMÉS aquí);
- run.py:         R execucions (aparellades si es comparen dos plans) amb interval de confiança.

Ús: python -m ai.bench --help
"""
