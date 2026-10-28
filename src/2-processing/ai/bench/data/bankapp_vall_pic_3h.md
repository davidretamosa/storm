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
- Sense dades personals: les altes d'usuari surten amb `body` `{}`, i els únics textos són els conceptes fixos del
  simulador (`Nómina`, `Cena`…). Cap correu, nom ni identificador real.
