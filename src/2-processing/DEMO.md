# Guía de la demo de processing (presentación a la empresa)

Cómo preparar y hacer la demo del orquestador de IA. Dura **unos 10 minutos** y **no depende de ningún otro grupo**: usa los datos de prueba de `samples/` y un servidor de prueba que hace de "app del banco".

> ⚠️ **Dejadlo claro en la presentación:** el log, el `.jar` y el servidor son **de prueba**. La app real (`1-input`) todavía no está terminada; cuando lo esté, se cambian los archivos de entrada y el código es el mismo.

---

## 1. Preparación (hacerlo antes del día, una sola vez)

### 1.1 Python y el proyecto

```bash
cd src/2-processing
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pytest
```

Los tests tienen que pasar todos.

### 1.2 JMeter

1. Comprobar que tenéis Java 17 o superior: `java -version`.
2. Descargar **Apache JMeter 5.6.3** (*Binaries*, el `.zip`) de https://jmeter.apache.org/download_jmeter.cgi
3. Descomprimirlo en una ruta corta, por ejemplo `C:\jmeter\apache-jmeter-5.6.3`.
4. Comprobar que arranca: doble clic en `C:\jmeter\apache-jmeter-5.6.3\bin\jmeter.bat`.

### 1.3 Ensayo completo

Haced la demo entera (sección 3) al menos una vez el día antes, **en el ordenador que vayáis a usar**.

---

## 2. Checklist el día de la demo

- [ ] `git pull --rebase` en `feature/processing`.
- [ ] Dos terminales abiertas en `src/2-processing` (Git Bash o PowerShell), con letra grande.
- [ ] JMeter abierto (interfaz gráfica), para enseñar el plan.
- [ ] VS Code abierto con `samples/access_sample.log` y `traffic_model/markov.py`.
- [ ] Borrar la carpeta `output/` para generar el plan en directo.
- [ ] Puerto 8080 libre (que no haya otra app usándolo).

---

## 3. Guion de la demo

### Paso 1 — El problema (1 min, sin ordenador)

> *"Para saber si una aplicación aguanta, hay que probarla con tráfico parecido al real. Escribir esas pruebas a mano es lento y no se parecen a cómo se comportan los usuarios de verdad. Nuestro orquestador **aprende de los logs** cómo navegan los usuarios y **genera automáticamente** el plan de JMeter."*

Enseñad el diagrama del `README.md` (logs + `.jar` → modelo → `.jmx`).

### Paso 2 — Los datos de entrada (1 min)

Abrid `samples/access_sample.log` en VS Code y enseñad 3 líneas de la misma sesión:

> *"Cada línea es una petición a la app del banco. Esta sesión mira su perfil, a los 6 segundos su cuenta y a los 17 hace una transferencia. Tenemos 95 peticiones de 30 sesiones; con la app real serán miles."*

Mencionad también el `.jar` de prueba: *"Además leemos el `.jar` compilado de la aplicación para descubrir todos sus endpoints, sin ejecutarla."*

### Paso 3 — Generar el plan (2 min)

En la terminal 1:

```bash
.venv/Scripts/python.exe main.py --logs samples/access_sample.log --jar samples/demo-bankapp.jar
```

Salida esperada y qué decir de cada línea:

```
--- 1. LECTURA ---
Logs: 95 peticiones, 30 sesiones.                   ← "hemos leído el log"
.jar: 12 endpoints.                                 ← "la app tiene 12 endpoints"
  - Nunca usado en los logs (se probará poco, por el .jar): DELETE /api/accounts/{id}
                                                    ← "uno que nadie usa: gracias al .jar también se prueba, un poco"
--- 2. MODELADO DEL TRÁFICO ---
12 estados en la cadena de Markov; 3 usuarios virtuales.
                                                    ← "el modelo: qué hace cada usuario después de cada paso"
6 peticiones con parámetros de ruta; 5 con cuerpo JSON.
                                                    ← "también aprende los ids y los datos que envían"
--- 3. GENERACIÓN DEL ESCENARIO ---
Plan generado: output/generated_scenario.jmx       ← "y genera el plan de JMeter"
```

**Lo importante: logs y `.jar` combinados.** Generad también el plan **solo con el `.jar`** (una app "muerta", sin logs):

```bash
.venv/Scripts/python.exe main.py --jar samples/demo-bankapp.jar
```

> *"Sin logs también funciona: el `.jar` dice qué endpoints y qué bodies existen, y el plan recorre toda la API. Cuando hay logs, mandan los logs; el `.jar` solo completa lo que falta."*

Para el resto de la demo, volved a generar el plan combinado (el comando de arriba con `--logs` y `--jar`).

Si da tiempo, enseñad en `markov.py` la línea de `pd.crosstab` y la función `mix`: *"crosstab cuenta qué petición sigue a cuál en los logs, y mix le suma lo que aporta el .jar y lo convierte en probabilidades: esa es la cadena de Markov"*. Por ejemplo: después de ver una cuenta, el 32 % mira los movimientos, el 25 % ingresa, el 21 % saca dinero, el 18 % transfiere y el 4 % se va.

### Paso 4 — El plan en JMeter (2 min)

En JMeter: *File → Open* → `output/generated_scenario.jmx`. Desplegad el árbol:

```
STORM - plan generado
├── Servidor objetivo            ← a qué servidor ataca (configurable)
└── Usuarios virtuales
    ├── Nueva sesión             ← elige cómo empieza cada visita
    └── Mientras la sesión siga
        ├── Pausa observada      ← espera lo que esperan los usuarios reales
        ├── Elegir siguiente     ← "tira el dado" con las probabilidades aprendidas
        └── Petición actual      ← las 11 peticiones de la API
```

> *"No es una lista fija de peticiones: cada usuario virtual decide en cada momento qué hace, con las probabilidades aprendidas. Así cada sesión es distinta, como en la realidad."*

### Paso 5 — Lanzarlo en directo (3 min)

**Terminal 2** — el servidor de prueba (hace de app del banco y se para solo a los 70 s):

```bash
.venv/Scripts/python.exe tools/demo_server.py --logs samples/access_sample.log --jar samples/demo-bankapp.jar --stop-after 70
```

**Terminal 1** — JMeter sin interfaz, 10 usuarios durante 60 segundos (cambiad `C:\jmeter\...` por vuestra ruta):

```bash
C:\jmeter\apache-jmeter-5.6.3\bin\jmeter.bat -n -t output/generated_scenario.jmx -Jvusers=10 -Jrampup=5 -Jduration=60
```

En la terminal 2 se ven las peticiones llegando en directo (los valores cambian en cada ejecución):

```
[   5.1s] #1    POST   /api/users                       {"name": "Laura Martí", "email": "laura.7@mail.com"}
[   5.1s] #2    GET    /api/users/2
[   5.5s] #5    GET    /api/accounts/4
[  13.6s] #11   POST   /api/accounts/4/deposit          {"amount": 289.24}
```

> *"Fijaos: los usuarios esperan entre petición y petición, los ids son de cuentas que existen y los importes son realistas."*

A los 70 s el servidor se para y enseña **el resultado clave**:

```
RESUMEN: 66 peticiones recibidas de JMeter
Petición                                          % en el log   % recibido
GET /api/accounts/{id}                                  29.5%        30.3%
GET /api/accounts/{id}/transactions                     14.7%        13.6%
GET /api/users/{id}                                     21.1%        25.8%
...
```

> *"El tráfico que genera JMeter tiene las mismas proporciones que el tráfico real del log (el `DELETE`, que nadie usa, sale muy poco: lo añade el `.jar`). Con más usuarios y más tiempo, se parecen todavía más."*

### Paso 6 — Siguientes pasos (1 min)

- Conectarlo con la app real de `1-input` y con el laboratorio de Kubernetes de `3-execution`.
- Las decisiones pendientes de `GUIA.md` (sección 6): usar el `.jar` para probar también los endpoints que nadie usa, simular picos de carga, varios escenarios (normal, pico, estrés)…

---

## 4. Si algo falla (plan B)

| Problema | Solución |
|---|---|
| `main.py: error: unrecognized arguments: --jar` | No tenéis la última versión: `git pull --rebase` |
| `ModuleNotFoundError: No module named 'pandas'` | Falta instalar: `.venv/Scripts/python.exe -m pip install -r requirements.txt` |
| El servidor dice que el puerto 8080 está ocupado | Usad otro: `tools/demo_server.py --port 8090` y en JMeter añadid `-Jport=8090` |
| `jmeter.bat` no se encuentra | Revisad la ruta donde descomprimisteis JMeter |
| JMeter no arranca (error de Java) | Necesita Java 17 o superior: `java -version` |
| No da tiempo / falla JMeter en directo | Saltad el paso 5: enseñad el plan en JMeter (paso 4) y contad el resultado con la tabla de esta guía |

---

## 5. Preguntas que os pueden hacer

| Pregunta | Respuesta |
|---|---|
| *¿Dónde está la IA?* | El modelo se **aprende de los datos**: una cadena de Markov de la navegación, más distribuciones de pausas y de datos. No hay reglas escritas a mano. (Ver decisión D8 de `GUIA.md` para mejoras con ML.) |
| *¿Qué pasa con endpoints que nadie usa?* | El `jar_parser` los descubre y se prueban un poco: el `.jar` aporta unas pocas "observaciones inventadas" a la cadena de Markov. |
| *¿Y si la app no tiene logs?* | Se genera el plan solo con el `.jar`: recorre todos los endpoints, con bodies a partir de los DTOs y pausas de 1–3 s. |
| *¿Funciona con logs reales?* | Sí, con el formato JSON acordado con el grupo de input. Solo hay que cambiar el archivo de entrada. |
| *¿Cuánta carga puede generar?* | La que se configure: `-Jvusers=...` y `-Jduration=...`. En Kubernetes se reparte entre varios JMeter (grupo de execution). |
| *¿Por qué Markov y no una lista fija de peticiones?* | Una lista fija repite siempre lo mismo. Con Markov cada sesión es distinta, pero en conjunto respetan las proporciones reales (lo que muestra el resumen del paso 5). |
| *¿Las pausas son reales?* | Sí: se guardan 20 valores de la distribución de pausas de cada transición y JMeter elige uno al azar. |
