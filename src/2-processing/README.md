# 2-processing — Orquestador de IA

Genera un plan de JMeter (`.jmx`) que **simula usuarios** de una aplicación, a partir de **sus logs** (cómo la usa la gente), de **su `.jar`** (qué endpoints y bodies existen) **o de los dos combinados**. Así funciona tanto con apps con tráfico como con apps sin logs.

```
                      PASO 1: leer              PASO 2: aprender (la "IA")          PASO 3: generar
access.log ──► log_parser ──► tabla ─────┐
(opcional)                                ├──► traffic_model ──► modelo ──► jmx_generator ──► plan .jmx
.jar ───────► jar_parser ──► endpoints ───┘    (Markov, pausas,                                 │
(opcional)                                       ids, bodies, usuarios)                  lo ejecuta JMeter
                                                                                         (3-execution)
```

> 📘 **Para entender el código a fondo y ver las decisiones pendientes, leed [`GUIA.md`](GUIA.md).**
>
> 🎤 **Para preparar y hacer la demo a la empresa, leed [`DEMO.md`](DEMO.md).**

Todo se lanza con `main.py`. Esta carpeta **no depende de las demás** (`1-input`, `3-execution`): en `samples/` hay datos de prueba para ejecutarla sola.

---

## 1. Demo (prueba independiente)

```bash
cd src/2-processing
.venv/Scripts/python.exe main.py --logs samples/access_sample.log --jar samples/demo-bankapp.jar
```

Salida:

```
--- 1. LECTURA ---
Logs: 95 peticiones, 30 sesiones.
.jar: 12 endpoints.
  - Nunca usado en los logs (se probará poco, por el .jar): DELETE /api/accounts/{id}
--- 2. MODELADO DEL TRÁFICO ---
12 estados en la cadena de Markov; 3 usuarios virtuales.
6 peticiones con parámetros de ruta; 5 con cuerpo JSON.
--- 3. GENERACIÓN DEL ESCENARIO ---
Plan generado: output/generated_scenario.jmx
```

Las tres formas de usarlo:

```bash
.venv/Scripts/python.exe main.py --logs samples/access_sample.log                                  # solo logs
.venv/Scripts/python.exe main.py --jar samples/demo-bankapp.jar                                    # solo .jar (app sin logs)
.venv/Scripts/python.exe main.py --logs samples/access_sample.log --jar samples/demo-bankapp.jar   # combinado
```

El `.jmx` generado se puede abrir con JMeter (*File → Open*) para ver la estructura del plan.

> ⚠️ **Todo lo que hay en `samples/` son DATOS DE PRUEBA**, no la aplicación real:
> - `access_sample.log`: log **inventado** con el formato de la app del banco.
> - `demo-bankapp.jar` y `demo_app/`: una app **de prueba** que copia la API del banco (sus controllers no hacen nada) para probar el `jar_parser` mientras la app real de `1-input` no tiene controllers.
>
> Cuando la app real esté lista, se cambia por su `access.log` y su `.jar`; el código no cambia.

---

## 2. Instalación (solo la primera vez)

```bash
cd src/2-processing
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

- Así no hace falta "activar" el entorno: se llama directamente a su Python (`.venv/Scripts/python.exe`). Funciona igual en Git Bash y en PowerShell.
- En VS Code: `Ctrl+Shift+P` → *Python: Select Interpreter* → el de `.venv`.

Tests:

```bash
.venv/Scripts/python.exe -m pytest
```

---

## 3. Estructura: para qué sirve cada archivo

```
2-processing/
├── main.py                  ← el "director": llama a todo en orden
├── requirements.txt         ← librerías (pandas, numpy, jinja2, pytest)
├── pytest.ini               ← configuración de los tests
│
├── log_parser/              PASO 1: leer los logs
│   └── parser.py
│
├── jar_parser/              PASO 1 (opcional): leer el .jar
│   ├── class_file.py
│   └── parser.py
│
├── traffic_model/           PASO 2: aprender de los logs (la "IA")
│   ├── markov.py
│   ├── think_time.py
│   ├── payloads.py
│   └── scaling.py
│
├── jmx_generator/           PASO 3: generar el plan de JMeter
│   ├── generator.py
│   └── templates/
│       ├── plan.jmx.j2
│       ├── markov_common.groovy
│       ├── session_start.groovy
│       └── next_request.groovy
│
├── samples/                 DATOS DE PRUEBA
│   ├── access_sample.log
│   ├── demo-bankapp.jar
│   └── demo_app/
│
├── tools/                   SOLO PARA LA DEMO
│   └── demo_server.py
│
└── tests/                   comprueban que cada parte funciona
```

Los `__init__.py` vacíos son normales: le dicen a Python que la carpeta es un paquete (para poder hacer `from traffic_model.markov import ...`).

### `main.py`

Lee las opciones de la terminal y ejecuta los 3 pasos. No calcula nada: solo llama a las funciones de las demás carpetas y enseña un resumen.

| Opción | Por defecto | Para qué |
|---|---|---|
| `--logs` | — | El log de la app (cómo la usa la gente) |
| `--jar` | — | El `.jar` de la app (qué endpoints y bodies existen) |
| | | **Hace falta al menos uno de los dos** |
| `--jar-weight` | `1` | Cuánto pesa el `.jar` al mezclarlo con los logs: `1` = como una sesión más (ver sección 5) |
| `--default-pause` | `1-3` | Pausa en segundos (al azar en ese rango) cuando no hay datos en los logs. `0-0` = sin pausa |
| `--output` | `output/generated_scenario.jmx` | Dónde se guarda el plan |
| `--host`, `--port` | `localhost`, `8080` | Contra qué servidor lanzará JMeter las peticiones |

Al lanzar JMeter se pueden cambiar sin regenerar el plan: `-Jhost=... -Jport=...` (servidor) y `-Jvusers=... -Jrampup=... -Jduration=...` (usuarios virtuales, rampa y duración en segundos).
| `--min-probability` | `0` (no quita nada) | Opcional: ignorar los caminos muy poco frecuentes |
| `--max-steps` | `50` | Máximo de peticiones por sesión simulada (por si hay bucles) |

### `log_parser/parser.py` — leer el log

| Función | Recibe | Devuelve |
|---|---|---|
| `parse_logs(ruta)` | La ruta del `access.log` | Una **tabla de pandas** (una fila por petición), ordenada por hora |
| `parse_line(línea)` | Una línea del log | Un diccionario con la fila, o `None` si la línea no vale |

- Traduce los nombres del log (`sessionId`) a los de la tabla (`session_id`) con el diccionario `COLUMNS`.
- Ignora las líneas que no son JSON o que no tienen `timestamp`, `method` y `endpoint`.
- Convierte el `timestamp` en fecha y los números en números.

### `jar_parser/` — descubrir la API desde el `.jar` (opcional)

Lee el `.jar` compilado de la app **sin ejecutarla** (análisis estático del bytecode) y saca **todos los endpoints que existen**, con los campos de sus bodies. Ver la [sección 5](#5-jar_parser-y-su-relación-con-el-modelo).

| Archivo | Función | Recibe | Devuelve |
|---|---|---|---|
| `class_file.py` | `read_class(bytes)` | Los bytes de un `.class` | Nombre de la clase, sus anotaciones, campos y métodos |
| `parser.py` | `parse_jar(ruta)` | La ruta del `.jar` | Lista de endpoints: `{"method", "endpoint", "controller", "handler", "body"}` |
| `parser.py` | `compare_with_logs(endpoints, tabla)` | Los endpoints y la tabla de logs | `never_used` (en el `.jar` pero no en los logs) y `unknown` (en los logs pero no en el `.jar`) |

- `class_file.py` es la parte "de bajo nivel": sabe leer el formato binario de un `.class` de Java.
- `parser.py` busca las clases con `@RestController` y junta su `@RequestMapping("/api/accounts")` con el `@PostMapping("/{id}/deposit")` de cada método → `POST /api/accounts/{id}/deposit`. Si un parámetro lleva `@RequestBody`, lee los campos de esa clase (el DTO).

### `traffic_model/` — aprender de los logs (la "IA")

Cada archivo aprende **una cosa distinta** de la misma tabla:

| Archivo | Función principal | Qué aprende | Ejemplo |
|---|---|---|---|
| `markov.py` | `build_markov_model(tabla)` | **Qué petición sigue a cuál** (cadena de Markov), cómo empiezan las sesiones y cuándo acaban | "después de ver una cuenta: 32 % movimientos, 25 % ingreso, 21 % retirada, 18 % transferencia, 4 % se va" |
| `think_time.py` | `build_think_times(tabla)` | **Cuánto espera el usuario** entre una petición y la siguiente | "entre ver la cuenta y transferir: de 6 a 18 s" |
| `payloads.py` | `build_path_params(tabla)` | **Qué valores tienen los `{id}`** de las rutas | "`/api/accounts/{id}` usa las cuentas 1, 2, 3, 4, 5" |
| `payloads.py` | `build_body_models(tabla)` | **Cómo son los bodies** de cada petición, campo a campo | "`amount` entre 5 y 300; `concept`: alquiler, luz…" |
| `scaling.py` | `predict_traffic_scale(tabla)` | **Cuántos usuarios virtuales** simular | "como mucho hubo 3 sesiones a la vez → 3 usuarios" |

`markov.py` por dentro:

| Función | Qué hace |
|---|---|
| `get_steps(tabla)` | Añade a la tabla `key` (`"GET /api/accounts/{id}"`) y `next_key` (lo siguiente que hizo **ese mismo usuario**, con `groupby("session_id")` + `shift(-1)`). La usa también `think_time.py` |
| `build_markov_model(tabla, endpoints=...)` | Junta logs y `.jar`: `count_from_logs` cuenta las parejas actual → siguiente con `pd.crosstab` y `mix` les suma el prior del `.jar` y las pasa a probabilidades. Devuelve `{"states", "start", "transitions", "max_steps"}` |
| `table_to_dict(tabla)` | Pasa la tabla de probabilidades a diccionario `{actual: {siguiente: probabilidad}}` |
| `prune(...)` | **Opcional**: quita opciones poco probables (solo con `--min-probability`) |

### `jmx_generator/` — generar el plan de JMeter

| Archivo | Qué es |
|---|---|
| `generator.py` | `generate_jmx(...)`: junta todo lo aprendido y rellena la plantilla |
| `templates/plan.jmx.j2` | El **esqueleto** del `.jmx` (XML de JMeter) con huecos `{{ ... }}` que rellena Jinja2 |
| `templates/*.groovy` | Código que se ejecuta **dentro de JMeter** mientras corre la prueba: elige la primera petición de cada sesión, la siguiente según las probabilidades, la pausa, los `{id}` y el body. Ver la [sección 6](#6-cómo-simula-el-jmx-el-tráfico) |

### `samples/` — datos de prueba

| Archivo | Qué es |
|---|---|
| `access_sample.log` | Log **inventado**: 30 sesiones, 95 peticiones, las 11 peticiones de la API, con algunos errores (400, 404) |
| `demo-bankapp.jar` | `.jar` **de prueba** para el `jar_parser`: los 11 endpoints de la API + `DELETE /api/accounts/{id}` (que no sale en los logs, para ver que se detecta) |
| `demo_app/src/` | El código Java de ese `.jar` (controllers y DTOs que **no hacen nada**) |
| `demo_app/build_demo_jar.py` | Vuelve a generar `demo-bankapp.jar` si se cambia el código Java (necesita el JDK; el `.jar` ya está en el repo) |

### `tools/demo_server.py` — servidor de prueba para la demo

Hace de "app del banco" para recibir el tráfico de JMeter: responde a todo, enseña cada petición en directo y, al parar, compara el % de cada petición recibida con el % del log. **No es la app real.** Cómo usarlo: [`DEMO.md`](DEMO.md).

### `tests/`

Un archivo por parte del código. Cada test es un **ejemplo pequeño** de cómo se usa una función, así que si no entendéis una función, mirad su test.

| Archivo | Comprueba |
|---|---|
| `conftest.py` | No es un test: crea un log pequeño de prueba que usan los demás |
| `test_log_parser.py` | `log_parser/parser.py` |
| `test_jar_parser.py` | `jar_parser/` (con `samples/demo-bankapp.jar`) |
| `test_traffic_model.py` | `markov.py`, `think_time.py`, `scaling.py` |
| `test_payloads.py` | `payloads.py` |
| `test_jmx_generator.py` | `generator.py` |

### Orden recomendado para entender el código

1. `samples/access_sample.log` — de qué partimos (mirad 5 líneas).
2. `main.py` — el mapa general.
3. `log_parser/parser.py`
4. `traffic_model/markov.py` — el corazón de la IA.
5. `traffic_model/think_time.py`, `payloads.py`, `scaling.py`
6. `jmx_generator/generator.py` y, por encima, `templates/`.
7. `jar_parser/parser.py` (y `class_file.py` solo si os interesa cómo se lee un `.class`).

---

## 4. Formato del log

El `access.log` de la app del banco (`1-input/java-app-mock`): **JSON Lines, una petición por línea**.

```json
{"timestamp":"2026-10-01T11:42:35.123Z","requestId":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","sessionId":"sess-9f8e7d6c","userId":12,"method":"POST","endpoint":"/api/accounts/{id}/deposit","path":"/api/accounts/3/deposit","status":200,"durationMs":45,"requestSizeBytes":17,"responseSizeBytes":256,"body":{"amount":200.00}}
```

| Campo | Para qué lo usamos |
|---|---|
| `timestamp` (UTC) | Ordenar las peticiones y calcular las pausas |
| `sessionId` | **Imprescindible**: agrupa las peticiones de una misma visita (cadena de Markov) |
| `method` + `endpoint` | Qué petición es. `endpoint` es la ruta con plantilla (`/api/accounts/{id}`) |
| `path` | Ruta concreta (`/api/accounts/3`): de aquí salen los valores de los `{id}` |
| `status`, `durationMs` | Errores y tiempos de respuesta |
| `body` | Body JSON recibido (`null` si no hay): modelo de los bodies que enviará JMeter |
| `requestId`, `userId`, `requestSizeBytes`, `responseSizeBytes` | Se leen, pero el modelo aún no los usa |

- Obligatorios: `timestamp`, `method` y `endpoint`. Las líneas que no son JSON o no los tienen se ignoran.
- Los ids dentro del `body` tienen que acabar en `Id` (`fromAccountId`, `userId`): así se toman de los valores vistos en vez de inventarse.

---

## 5. Cómo se combinan logs y `.jar`

Versión **sencilla** (lo que pidió ITNow): cada fuente aporta lo que sabe.

| | Los logs dicen… | El `.jar` dice… |
|---|---|---|
| Qué peticiones hay | Las que se usan | **Todas** las que existen |
| Qué sigue a cada petición | **Probabilidades reales** | Nada → "cualquiera, por igual" |
| Body | **Valores reales** | **Campos y tipos** del DTO |
| Pausas | **Pausas reales** | Nada → 1–3 s por defecto |

**Probabilidades (el "prior").** El `.jar` aporta unas pocas **observaciones inventadas**, repartidas por igual entre todas las peticiones posibles, que se suman a los conteos de los logs:

```
probabilidad = (veces en los logs + parte inventada) / (total en los logs + jar_weight)
```

- **Solo `.jar`** (app sin logs): solo hay inventadas → todo igual de probable → se recorre toda la API.
- **Muchos logs:** las inventadas no se notan → mandan los logs (el tráfico real).
- **Endpoint que nadie usa** (el `DELETE` de la demo): sale con probabilidad pequeña (≈0,3 % con `jar_weight=1`) → se prueba un poco.
- **Solo logs:** exactamente igual que antes.

**Bodies.** Si la petición tiene bodies en los logs, **mandan los logs**. Si no tiene ninguno, se genera desde su DTO con un valor por tipo: números 1–100, ids `1`, textos `"test"`, booleanos `true`/`false`, fechas fijas.

**Valores por defecto (solo cuando no hay datos).** Son **suposiciones**, no datos de la app, y se pueden cambiar:
- Pausa: al azar entre **1 y 3 s** (habitual en pruebas de carga: el tiempo de mirar una pantalla y hacer clic). Opción `--default-pause`.
- Usuarios virtuales: **10**. Se cambia al lanzar JMeter con `-Jvusers=...`.

Más detalle y lo que se ha dejado fuera a propósito: `GUIA.md`, sección 6.

---

## 6. Cómo simula el `.jmx` el tráfico

Cada iteración de un usuario virtual es **una sesión** que recorre la cadena de Markov aprendida de los logs:

```
Thread Group
├── Flow Control Action "Nueva sesión" + JSR223  -> elige la 1ª petición (model.start)
└── While stormState != END
    ├── JSR223 Timer          -> pausa observada en los logs para esa transición
    ├── Switch ${stormIndex}  -> una petición HTTP por estado de la cadena
    └── JSR223 PostProcessor  -> tras cada petición elige la siguiente (o END) según las probabilidades
```

- El modelo (`states`, `start`, `transitions`, `think_time_ms`, `path_params`, `bodies`) va **dentro** de los scripts Groovy del `.jmx`: el plan es un único archivo que se puede pasar a `3-execution` tal cual.
- Pausas: se guardan 20 cuantiles de lo observado en cada transición y se elige uno al azar (máximo 2 min).
- Al elegir cada petición se rellenan sus datos:
  - **`{id}` de la ruta**: uno de los valores vistos en `path` para ese endpoint, según su frecuencia.
  - **Body JSON** (`Content-Type: application/json`), campo a campo: los números, un valor entre el mínimo y el máximo observados; los textos y los ids, uno de los valores vistos. Cada campo aparece con la misma frecuencia que en los logs.
- `--max-steps` corta las sesiones demasiado largas; `--min-probability` descarta transiciones raras.

---

## 7. Limitaciones conocidas (TODO)

- **No hay correlación entre peticiones**: tras `POST /api/accounts`, el siguiente `deposit` usa un id visto en los logs, no el de la cuenta recién creada (habría que leerlo de la respuesta). Los campos de un body se generan por separado (`fromAccountId` puede coincidir con `toAccountId`) y los valores únicos (emails) se repiten.
- **Los nombres de los campos de los `body` del log de ejemplo son supuestos**: hay que ajustarlos cuando estén los DTOs de `java-app-mock`.
- **No hay perfil horario**: la intensidad es constante durante la prueba.
- **`scaling.py`**: usuarios virtuales = pico real de sesiones a la vez (reproduce el peor momento del log). Para pruebas de estrés se sube al lanzar JMeter con `-Jvusers`.
- **`jar_parser`**: ver la sección 5 (decisiones pendientes).
- **Kubernetes**: el despliegue de JMeter es cosa de `3-execution`; hay que acordar con ellos cómo les pasamos el `.jmx`.

---

## 8. Cómo trabajamos (git)

- Rama del grupo: **`feature/processing`**. Nunca push a `develop` ni a `main` (se llega con una Pull Request).
- Antes de empezar y antes de cada `push`: `git pull --rebase`.
- Antes de subir: `.venv/Scripts/python.exe -m pytest` tiene que pasar entero.
