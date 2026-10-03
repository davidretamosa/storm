# 2-processing — Orquestador de IA

Aprende **cómo usan los usuarios la aplicación** a partir de sus logs y genera un plan de JMeter (`.jmx`) que **simula ese mismo tráfico**: las mismas secuencias de peticiones, con las mismas pausas y datos parecidos.

```
                      PASO 1: leer              PASO 2: aprender (la "IA")          PASO 3: generar
access.log ──► log_parser ──► tabla ──► traffic_model ──► modelo ──► jmx_generator ──► plan .jmx
                                 │      (Markov, pausas,                                  │
.jar (opcional) ──► jar_parser ──┘       ids, bodies, usuarios)                    lo ejecuta JMeter
                    (endpoints que existen)                                      (3-execution)
```

Todo se lanza con `main.py`. Esta carpeta **no depende de las demás** (`1-input`, `3-execution`): en `samples/` hay datos de prueba para ejecutarla sola.

---

## 1. Demo (prueba independiente)

```bash
cd src/2-processing
.venv/Scripts/python.exe main.py samples/access_sample.log --jar samples/demo-bankapp.jar
```

Salida:

```
--- 1. PARSING ---
95 peticiones, 30 sesiones.
12 endpoints en el .jar.
  - Nunca usado en los logs (no se probará): DELETE /api/accounts/{id}
--- 2. MODELADO DEL TRÁFICO ---
11 estados en la cadena de Markov; 45 usuarios virtuales.
6 peticiones con parámetros de ruta; 5 con cuerpo JSON.
--- 3. GENERACIÓN DEL ESCENARIO ---
Plan generado: output/generated_scenario.jmx
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
└── tests/                   comprueban que cada parte funciona
```

Los `__init__.py` vacíos son normales: le dicen a Python que la carpeta es un paquete (para poder hacer `from traffic_model.markov import ...`).

### `main.py`

Lee las opciones de la terminal y ejecuta los 3 pasos. No calcula nada: solo llama a las funciones de las demás carpetas y enseña un resumen.

| Opción | Por defecto | Para qué |
|---|---|---|
| `log_file` | (obligatoria) | El log a analizar |
| `--jar` | — | `.jar` de la app, para descubrir todos sus endpoints |
| `--output` | `output/generated_scenario.jmx` | Dónde se guarda el plan |
| `--host`, `--port` | `localhost`, `8080` | Contra qué servidor lanzará JMeter las peticiones |
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
| `scaling.py` | `predict_traffic_scale(tabla)` | **Cuántos usuarios virtuales** simular | "sesiones vistas × 1,5" |

`markov.py` por dentro:

| Función | Qué hace |
|---|---|
| `get_steps(tabla)` | Añade a la tabla `key` (`"GET /api/accounts/{id}"`) y `next_key` (lo siguiente que hizo **ese mismo usuario**, con `groupby("session_id")` + `shift(-1)`). La usa también `think_time.py` |
| `build_markov_model(tabla)` | Cuenta las parejas actual → siguiente con `pd.crosstab` y las pasa a probabilidades. Devuelve `{"states", "start", "transitions", "max_steps"}` |
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

## 5. `jar_parser` y su relación con el modelo

**Qué aporta.** Los logs solo muestran **lo que la gente ha usado**; el `.jar` muestra **todo lo que existe**. Con la demo, el `jar_parser` encuentra `DELETE /api/accounts/{id}`, que nadie ha usado en los logs.

**Qué hace ahora mismo: solo informa.** `main.py` enseña qué endpoints del `.jar` no aparecen en los logs (y al revés). **El modelo y el `.jmx` siguen saliendo solo de los logs**, igual que sin `--jar`.

**Pendiente de decidir entre todos** (por eso aún no está hecho):

1. **Endpoints que existen pero nadie usa** (como el `DELETE`). La cadena de Markov solo conoce lo que ha visto en los logs, así que el `.jmx` nunca los probará. Opciones:
   - a) Dejarlo así: simulamos el tráfico **real**, y lo que nadie usa no se prueba.
   - b) Meterlos en la cadena con una probabilidad pequeña (p. ej. 1 %), aunque nadie los haya usado.
   - c) Un grupo de usuarios aparte en el `.jmx` que llama a **todos** los endpoints del `.jar`, para comprobar que funcionan.
2. **Bodies que no salen en los logs.** `payloads.py` aprende cómo es el body de una petición **mirando los bodies del log**. Si en el log no hay ningún body de esa petición (nunca se ha usado, o la app no lo guardó), JMeter la enviaría **sin body** y la app respondería con error. Con el `jar_parser` sabemos sus campos (`DepositRequest` → `amount: BigDecimal`), así que se podría generar un body de prueba (`{"amount": 100.00}`).

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
- **`scaling.py` es una regla fija** (sesiones observadas × 1,5), no una predicción.
- **`jar_parser`**: ver la sección 5 (decisiones pendientes).
- **Kubernetes**: el despliegue de JMeter es cosa de `3-execution`; hay que acordar con ellos cómo les pasamos el `.jmx`.

---

## 8. Cómo trabajamos (git)

- Rama del grupo: **`feature/processing`**. Nunca push a `develop` ni a `main` (se llega con una Pull Request).
- Antes de empezar y antes de cada `push`: `git pull --rebase`.
- Antes de subir: `.venv/Scripts/python.exe -m pytest` tiene que pasar entero.
