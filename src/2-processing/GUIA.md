# Guía del grupo de processing

Guía para que **todo el grupo entienda el código de `2-processing`** y sepa **qué decisiones tenemos pendientes**.
El `README.md` explica cómo usarlo; esta guía explica **cómo funciona por dentro y qué falta decidir**.

**Índice**

1. [La idea en 1 minuto](#1-la-idea-en-1-minuto)
2. [Mapa: qué recibe cada código y a quién se lo pasa](#2-mapa-qué-recibe-cada-código-y-a-quién-se-lo-pasa)
3. [Recorrido por el código, en orden](#3-recorrido-por-el-código-en-orden)
4. [Opciones y números que pueden liar](#4-opciones-y-números-que-pueden-liar)
5. [Datos de prueba vs datos reales](#5-datos-de-prueba-vs-datos-reales)
6. [⚠️ DECISIONES QUE TENEMOS QUE TOMAR](#6-decisiones-que-tenemos-que-tomar)
7. [Lo que ya está decidido](#7-lo-que-ya-está-decidido)
8. [Glosario](#8-glosario)

---

## 1. La idea en 1 minuto

La empresa quiere probar si su aplicación aguanta mucho tráfico. Para eso no basta con lanzar miles de peticiones iguales: hay que **simular usuarios que se comportan como los de verdad**.

Nuestro código hace eso en 3 pasos:

| Paso | Qué hace | Ejemplo |
|---|---|---|
| **1. Leer** | Lee los logs de la app (y opcionalmente su `.jar`) | "El usuario de la sesión `sess-40a9` miró su perfil, a los 6 s su cuenta y a los 17 s hizo una transferencia de 55,60 €" |
| **2. Aprender** (la "IA") | Saca patrones de miles de líneas de log | "Después de ver una cuenta, el 32 % mira los movimientos y el 18 % transfiere; entre una cosa y otra pasan entre 6 y 18 s" |
| **3. Generar** | Escribe un plan de JMeter (`.jmx`) que simula usuarios con esos patrones | Usuarios virtuales que navegan "tirando un dado" con esas probabilidades |

El `.jmx` se lo pasamos a `3-execution`, que lo lanza contra la app en Kubernetes.

---

## 2. Mapa: qué recibe cada código y a quién se lo pasa

```
                       ┌──────────────────────── main.py (lo coordina todo) ────────────────────────┐
                       │                                                                             │
 access.log ─────────► parse_logs ──► TABLA (DataFrame) ──┬──► build_markov_model ──► model ────────┐ │
 (logs de la app)      log_parser/                         ├──► build_think_times ───► think_times ──┤ │
                                                           ├──► build_path_params ───► path_params ──┤ │
                                                           ├──► build_body_models ───► bodies ───────┼─┼─► generate_jmx ──► plan.jmx ──► JMeter
                                                           ├──► predict_traffic_scale ► profile ─────┘ │   jmx_generator/              (3-execution)
                                                           │                                           │
 app.jar ────────────► parse_jar ──► endpoints ───────────┴──► compare_with_logs ──► solo se imprime  │
 (opcional, --jar)     jar_parser/                                                  (no llega al .jmx) │
                       └─────────────────────────────────────────────────────────────────────────────┘
```

### Quién recibe los **logs**

| Código | Recibe | Devuelve | Lo usa |
|---|---|---|---|
| `log_parser/parser.py` → `parse_logs` | La **ruta del `access.log`** | La **tabla** de peticiones | Todo el `traffic_model` y `compare_with_logs` |

A partir de aquí **nadie vuelve a leer el archivo de log**: todos trabajan con la tabla.

### Quién recibe el **`.jar`**

| Código | Recibe | Devuelve | Lo usa |
|---|---|---|---|
| `jar_parser/parser.py` → `parse_jar` | La **ruta del `.jar`** (opción `--jar`) | La **lista de endpoints** | `compare_with_logs` |
| `jar_parser/parser.py` → `compare_with_logs` | Los endpoints + la tabla | Endpoints nunca usados / desconocidos | `main.py`, para imprimirlos |
| `traffic_model/markov.py` → `build_markov_model(..., endpoints=...)` | Los endpoints | Las "observaciones inventadas" del `.jar` (el prior) | El modelo |
| `traffic_model/payloads.py` → `build_body_models(..., endpoints)` | Los endpoints | Bodies desde el DTO para las peticiones sin bodies en los logs | El modelo |

> `--logs` y `--jar` son opcionales (hace falta al menos uno). Cómo se combinan: `README.md`, sección 5.

### Quién recibe la **tabla** y qué saca

| Código | Columnas de la tabla que usa | Devuelve |
|---|---|---|
| `markov.py` → `build_markov_model` | `session_id`, `timestamp`, `method`, `endpoint` | `model`: `states`, `start`, `transitions`, `max_steps` |
| `think_time.py` → `build_think_times` | `session_id`, `timestamp`, `method`, `endpoint` | `think_times`: pausas entre cada pareja de peticiones |
| `payloads.py` → `build_path_params` | `method`, `endpoint`, `path` | `path_params`: valores vistos de cada `{id}` |
| `payloads.py` → `build_body_models` | `method`, `endpoint`, `body` | `bodies`: cómo es cada campo de cada body |
| `scaling.py` → `predict_traffic_scale` | `session_id` | `profile`: usuarios virtuales, rampa, duración |
| `compare_with_logs` (jar_parser) | `method`, `endpoint` | Cobertura `.jar` vs logs |

Columnas que **nadie usa todavía**: `request_id`, `user_id`, `status`, `duration_ms`, `request_size_bytes`, `response_size_bytes`. Se guardan para el futuro (evaluar resultados, errores…).

### Quién recibe **lo aprendido**

| Código | Recibe | Devuelve |
|---|---|---|
| `jmx_generator/generator.py` → `generate_jmx` | `model`, `think_times`, `profile`, `path_params`, `bodies`, host, puerto, ruta de salida | Escribe el archivo `.jmx` |
| `templates/*.groovy` (dentro de JMeter) | El modelo entero, metido dentro del `.jmx` como JSON | Decide en tiempo real qué hace cada usuario virtual |

---

## 3. Recorrido por el código, en orden

Para cada archivo: **qué hay que entender sí o sí** y **preguntas para comprobar que lo has entendido**.

### 3.1 `samples/access_sample.log` — de qué partimos

- Una línea = una petición, en JSON.
- Lo importante: `sessionId` (quién), `timestamp` (cuándo), `method` + `endpoint` (qué), `path` (con qué ids), `body` (con qué datos).

❓ *¿Qué hizo la sesión de las 3 primeras líneas? ¿Cuánto tardó entre una petición y otra?*

### 3.2 `main.py` — el director

- Lee opciones de la terminal con `argparse` (ver [sección 4](#4-opciones-y-números-que-pueden-liar)).
- Ejecuta: `parse_logs` (si hay `--logs`) y `parse_jar` (si hay `--jar`) → las 5 funciones de `traffic_model` → `generate_jmx`.
- No calcula nada él mismo.

❓ *Si quiero que JMeter ataque a `bankapp:9090`, ¿qué opciones pongo?*

### 3.3 `log_parser/parser.py` — leer el log

- `parse_line`: `json.loads` → comprueba campos obligatorios → traduce nombres con `COLUMNS` (`sessionId` → `session_id`).
- `parse_logs`: lista de filas → `pd.DataFrame(rows, columns=...)` → convierte tipos (`to_datetime`, `to_numeric`) → ordena por hora.
- Las líneas malas **se ignoran sin avisar**.

❓ *¿Qué pasa con una línea que no tiene `endpoint`? ¿Y con una línea vacía?*

### 3.4 `traffic_model/markov.py` — el corazón de la IA

- `get_steps`: añade `key` (`"GET /api/accounts/{id}"`) y `next_key` = lo siguiente que hizo **ese mismo usuario** (`groupby("session_id")` + `shift(-1)`). Sin el `groupby` se mezclarían usuarios.
- `build_markov_model`:
  - `start`: con qué petición empiezan las sesiones (`groupby().first()` + `value_counts(normalize=True)`).
  - `transitions`: los vacíos de `next_key` se rellenan con `END` (`fillna`) → `pd.crosstab` cuenta las parejas → `mix` las pasa a probabilidades (sumando el `.jar` si lo hay).
  - `states`: lista ordenada de todas las peticiones distintas.
- `count_from_logs`: hace el conteo de los logs (inicios y parejas actual → siguiente).
- `mix`: suma a los conteos de los logs las "observaciones inventadas" del `.jar` y lo pasa a probabilidades (ver `README.md`, sección 5).
- `prune`: **opcional**, solo actúa con `--min-probability`.

❓ *¿Por qué hace falta `END`? ¿Qué devuelve `build_markov_model` y qué es cada clave?*

### 3.5 `traffic_model/think_time.py` — las pausas

- Usa `get_steps` y calcula, para cada pareja (actual → siguiente), cuántos ms pasaron entre una y otra.
- No guarda la media: guarda **20 cuantiles** (del mínimo al máximo). JMeter elige uno al azar → pausas cortas y largas como en la realidad.
- Las pausas de más de **2 minutos** se recortan a 2 minutos.

❓ *¿Por qué no usamos simplemente la media de las pausas?*

### 3.6 `traffic_model/payloads.py` — los `{id}` y los bodies

- `build_path_params`: para `/api/accounts/{id}` mira en la columna `path` los valores reales (`/api/accounts/3` → `3`) y guarda su frecuencia.
- `build_body_models`: para cada petición con body, mira **cada campo** en todos sus bodies:
  - número normal (`amount`) → `number`: valor al azar entre el mínimo y el máximo vistos.
  - id (`fromAccountId`, `userId`…), texto u objeto → `choice`: uno de los valores vistos, según su frecuencia.
  - `presence`: en qué proporción de bodies aparece el campo.
- Con `--jar`: las peticiones **sin ningún body en los logs** lo generan desde su DTO (`add_bodies_from_dto`), con un valor por tipo (`default_field_model`). Si hay bodies en los logs, mandan los logs.

❓ *¿Por qué los ids no se generan "entre el mínimo y el máximo" como los importes?*

### 3.7 `traffic_model/scaling.py` — cuántos usuarios

- Usuarios virtuales = **pico de sesiones abiertas a la vez** en el log (`peak_concurrent_sessions`): el plan reproduce el peor momento real. Rampa 60 s, duración 300 s.
- Por qué el pico y no el total de sesiones: el total crece con lo largo que sea el log (con la regla antigua, sesiones × 1,5, un log de una semana daba 315 usuarios en vez de 45); el pico solo depende del momento de más tráfico (3 en los dos casos).
- No hay margen extra (antes ×1,5): reproducir y estresar son cosas distintas. Para estrés, `-Jvusers` al lanzar JMeter.
- Sin logs: 10 usuarios (suposición).
- Es una **regla provisional** (ver [decisión D5](#d5-cuántos-usuarios-virtuales-y-cuánto-tiempo)).

### 3.8 `jmx_generator/` — el plan de JMeter

- `generator.py` → `generate_jmx`:
  1. `build_samplers`: una petición HTTP por cada estado de la cadena, en el mismo orden que `states`.
  2. Junta todo lo aprendido en un JSON.
  3. Mete ese JSON dentro de los scripts Groovy (`_groovy`).
  4. Rellena la plantilla `plan.jmx.j2` con Jinja2 y escribe el archivo.
- `plan.jmx.j2`: XML de JMeter con huecos `{{ ... }}`. No hace falta entender cada línea, solo la estructura:
  ```
  Thread Group (usuarios virtuales)
  ├── "Nueva sesión"  → session_start.groovy elige la 1ª petición (model.start)
  └── While (la sesión no ha terminado)
      ├── Pausa       → la elegida en el paso anterior
      ├── Switch      → hace la petición actual (una por estado)
      └── Después     → next_request.groovy elige la siguiente según las probabilidades, o END
  ```
- `markov_common.groovy`: funciones compartidas: `pick` (tirar el dado con probabilidades), `pickValue`, `buildBody` (genera el body), `goTo` (prepara la siguiente petición: índice del Switch, `{id}` y body).

❓ *¿Dónde se decide, mientras corre JMeter, cuál es la siguiente petición? ¿Por qué el modelo va dentro del `.jmx` y no en un archivo aparte?* (respuesta: para que `3-execution` solo necesite un archivo)

### 3.9 `jar_parser/` — la API desde el `.jar`

- `class_file.py` (bajo nivel, **no hace falta entenderlo a fondo**): lee el formato binario de un `.class` y saca anotaciones, campos y métodos.
- `parser.py`:
  - `read_jar_classes`: abre el `.jar` (es un `.zip`) y lee todas las clases de la app (se salta las librerías de `BOOT-INF/lib/`).
  - `parse_jar`: para cada clase con `@RestController`, junta `@RequestMapping("/api/accounts")` + `@PostMapping("/{id}/deposit")` → `POST /api/accounts/{id}/deposit`. Si un parámetro tiene `@RequestBody`, lee los campos de ese DTO.
  - `compare_with_logs`: endpoints que existen pero nadie usa (`never_used`) y peticiones del log que no existen en el `.jar` (`unknown`).

❓ *Con la demo, ¿qué endpoint sale como "nunca usado" y por qué?*

### 3.10 `tools/demo_server.py` — solo para la demo

- Servidor de prueba que hace de "app del banco": responde a todo y enseña en directo cada petición de JMeter.
- Al parar, compara el % de cada petición recibida con el % del log: **es la prueba de que el modelo reproduce el tráfico real**.
- Cómo hacer la demo: [`DEMO.md`](DEMO.md).

### 3.11 `tests/`

- `pytest` ejecuta todos los `test_*.py`. Tienen que pasar **siempre** antes de subir código.
- Cada test es un ejemplo pequeño de cómo se usa una función: si no entiendes una función, lee su test.

---

## 4. Opciones y números que pueden liar

### Opciones de `main.py` (se cambian al ejecutar)

| Opción | Por defecto | Qué hace | ¿Cuándo tocarla? |
|---|---|---|---|
| `--logs` | — | El log de la app | Si la app tiene logs |
| `--jar` | — | El `.jar` de la app: añade al modelo los endpoints que existen y genera bodies desde los DTOs | Siempre que se tenga el `.jar` |
| `--jar-weight` | `1` | Cuántas "observaciones inventadas" aporta el `.jar` por petición (1 = como una sesión más). Más alto = más uniforme | Si queréis probar más lo que nadie usa |
| `--default-pause` | `1-3` | Pausa (s) al azar en ese rango cuando no hay pausas en los logs. `0-0` = sin pausa | Sin logs, o para una prueba de estrés |
| `--output` | `output/generated_scenario.jmx` | Dónde se guarda el plan | Si queréis varios planes |
| `--host`, `--port` | `localhost`, `8080` | A qué servidor atacará JMeter. Se puede cambiar también al lanzar JMeter: `-Jhost=... -Jport=...` | Cuando se sepa dónde está la app en Kubernetes |

### Opciones al lanzar JMeter (sin regenerar el `.jmx`)

| Opción | Por defecto | Qué hace |
|---|---|---|
| `-Jhost=...`, `-Jport=...` | Los de `main.py` | Servidor al que se envían las peticiones |
| `-Jvusers=...` | El de `scaling.py` (3 con la demo) | Usuarios virtuales |
| `-Jrampup=...` | 60 | Segundos para arrancar a todos los usuarios |
| `-Jduration=...` | 300 | Duración de la prueba en segundos |

Ejemplo (demo corta): `jmeter -n -t output/generated_scenario.jmx -Jvusers=10 -Jduration=60`
| `--min-probability` | `0` | Quita las transiciones con menos probabilidad que este valor y reparte su % entre las demás. **Con 0 no quita nada** | Solo si el plan tiene caminos rarísimos que no interesa probar (p. ej. `0.05` = quitar lo que pase menos del 5 %) |
| `--max-steps` | `50` | Máximo de peticiones por sesión simulada. **No se usa en Python**: viaja dentro del `.jmx` y lo aplica JMeter | Casi nunca. Es una protección por si la cadena tiene bucles (p. ej. retirada → retirada → retirada…) |

### Números escritos dentro del código (se cambian editando el código)

| Valor | Dónde | Qué significa |
|---|---|---|
| `samples=20` | `think_time.py` | Cuántos cuantiles se guardan de las pausas de cada transición |
| `max_ms=120_000` | `think_time.py` | Pausa máxima: 2 minutos. Si alguien tardó más, se cuenta como 2 min |
| `DEFAULT_VUSERS=10` | `scaling.py` | Usuarios virtuales cuando no hay logs |
| `DEFAULT_PAUSE_MS` (1–3 s) | `think_time.py` | Pausa cuando no hay datos (se cambia con `--default-pause`) |
| `ramp_up_seconds=60` | `scaling.py` | JMeter tarda 60 s en arrancar a todos los usuarios virtuales (no todos a la vez) |
| `duration_seconds=300` | `scaling.py` | La prueba dura 5 minutos |
| `MAX_VALUES=50` | `payloads.py` | Para cada `{id}` o campo de texto se guardan como mucho los 50 valores más frecuentes |
| `ID_FIELD` | `payloads.py` | Qué campos se consideran ids: `id`, `...Id`, `..._id` |
| `decimals` (máx. 2) | `payloads.py` | Decimales de los números generados (los mismos que en el log, máximo 2) |
| `{id}` sin valores → `1` | `markov_common.groovy` | Si un `{id}` nunca salió en los logs, JMeter usa `1` |

---

## 5. Datos de prueba vs datos reales

| | Datos de prueba (ahora) | Datos reales (cuando estén) |
|---|---|---|
| Log | `samples/access_sample.log` (**inventado**) | `access.log` de la app de Martina (`1-input`) |
| `.jar` | `samples/demo-bankapp.jar` (**app de prueba**, sus controllers no hacen nada) | `.jar` compilado de `java-app-mock` |
| Dónde está el código Java de prueba | `samples/demo_app/src/` | `src/1-input/java-app-mock/` |

**El código de processing no cambia** al pasar de prueba a real: solo cambia qué archivos se le pasan a `main.py`.

---

## 6. DECISIONES QUE TENEMOS QUE TOMAR

> **Actualización (rama `feature/processing-sencillo`):** ITNow pidió hacerlo **lo más sencillo posible**. D1, D2 y D3 quedan resueltas así (ver sección 7):
> - **D1:** el `.jar` alimenta el modelo (prior + bodies desde el DTO).
> - **D2:** los endpoints que nadie usa salen con probabilidad pequeña gracias al prior del `.jar`.
> - **D3:** si una petición no tiene bodies en los logs, se generan desde el DTO con un valor por tipo.
>
> Se dejan fuera **a propósito, por simplicidad**: reglas REST (lista → detalle…), correlación entre peticiones, leer validaciones de los DTOs (`@NotNull`, `@Email`…), `.war` y JAX-RS, logs de Tomcat/Apache sin `sessionId`, procesar miles de apps por lotes y autenticación. Son las mejoras naturales si ITNow pide más.

> ⚠️ **Lo más importante de esta guía.**

Para cada una: el problema, las opciones y una recomendación. **Hay que decidirlas entre los tres** (y algunas con otros grupos).
Cuando decidáis una, apuntad la decisión aquí y pasadla a la [sección 7](#7-lo-que-ya-está-decidido).

### D1. Papel del `jar_parser`

**Problema.** Ahora el `jar_parser` solo **informa** (imprime qué endpoints existen y cuáles no se usan). Las diapositivas dicen que el orquestador "correlaciona logs y código", así que quizá debería influir en el `.jmx`.

| Opción | Qué implica |
|---|---|
| **a) Solo informar** (como ahora) | Sencillo. Sirve como informe de cobertura: "estos endpoints no se prueban" |
| **b) Que alimente el modelo** | El `.jar` completa lo que no está en los logs (ver D2 y D3). Más trabajo, pero cumple mejor "correlaciona logs y código" |

**Recomendación:** b), empezando por D3, que es lo más útil y sencillo.
**Afecta a:** `main.py`, `payloads.py` y quizá `markov.py`.

### D2. Endpoints que existen pero nadie usa

**Problema.** La cadena de Markov solo conoce lo que la gente ha hecho en los logs. Si nadie ha cerrado nunca una cuenta (`DELETE /api/accounts/{id}` en la demo), el `.jmx` **nunca lo probará**, aunque exista.

| Opción | Ventaja | Inconveniente |
|---|---|---|
| **a) No probarlos** | El tráfico simulado es fiel al real | Hay partes de la app que nunca se prueban |
| **b) Meterlos en la cadena con probabilidad pequeña** (p. ej. 1 %) | Se prueban dentro del tráfico normal | El tráfico ya no es 100 % "real"; hay que decidir **después de qué** petición van |
| **c) Grupo de usuarios aparte** en el `.jmx` que llama a todos los endpoints del `.jar` | Tráfico real intacto + todo se prueba | Más trabajo en `jmx_generator`; hay que generar datos para endpoints sin ejemplos (D3) |

**Recomendación:** c) para una segunda versión; a) mientras tanto.
**Afecta a:** `markov.py` (opción b) o `jmx_generator` (opción c).

### D3. Bodies que no aparecen en los logs

**Problema.** `payloads.py` aprende cómo es un body **mirando los bodies del log**. Si una petición POST no tiene ningún body en el log (nadie la usó, o la app no lo guardó), JMeter la enviaría **vacía** y la app respondería con error.

| Opción | Qué implica |
|---|---|
| **a) Nada** | Esas peticiones fallarán en la prueba |
| **b) Generar el body desde el DTO del `.jar`** | Sabemos sus campos y tipos (`DepositRequest` → `amount: BigDecimal`) → generamos valores por tipo (números entre 1 y 100, textos `"test"`, ids = valores vistos en otros endpoints…) |

**Recomendación:** b). Es la forma más clara de que el `.jar` aporte algo al `.jmx`.
**Hay que decidir también:** qué valores por defecto usar para cada tipo (número, texto, fecha, booleano).

### D4. Correlación entre peticiones

**Problema.** Cada petición se genera por separado. Si un usuario virtual crea una cuenta (`POST /api/accounts`) y después ingresa dinero, el ingreso va a **otra cuenta del log**, no a la que acaba de crear. Lo mismo con `fromAccountId` = `toAccountId`, o emails repetidos al crear usuarios (la app dará error de duplicado).

| Opción | Qué implica |
|---|---|
| **a) Aceptarlo** | Algunas peticiones darán error (400, 404, duplicados) |
| **b) Leer el id de la respuesta** | JMeter guarda el `id` que devuelve el `POST` y lo usa en las siguientes peticiones de esa sesión. **Necesitamos saber qué devuelve la app de Martina** |
| **c) Generar valores únicos** | Emails tipo `user-<número>@mail.com` para que nunca se repitan |

**Recomendación:** c) es fácil y se puede hacer ya; b) cuando la app de Martina tenga sus respuestas definidas.
**Depende de:** Martina (formato de las respuestas).

### D5. Cuántos usuarios virtuales y cuánto tiempo

> ✅ **Hecho (opción a + b):** usuarios = pico real de sesiones a la vez, y se puede cambiar con `-Jvusers` (p. ej. para estrés). Antes era "sesiones del log × 1,5", que crecía con lo largo del log; el 1,5 se ha quitado porque no tenía justificación.

**Problema (original).** Era una regla fija heredada del código de Gemini: sesiones del log × 1,5, durante 5 minutos. No tenía ninguna base.

| Opción | Qué implica |
|---|---|
| **a) Concurrencia real del log** | Calcular cuántas sesiones había activas **a la vez** en el momento de más tráfico, y simular eso (× un factor de estrés) |
| **b) Que lo elija quien lanza la prueba** | Opciones `--vusers`, `--duration` en `main.py` |
| **c) Varios escenarios** | Generar varios `.jmx`: carga normal, pico (× 2), estrés (× 5) |

**Recomendación:** a) + b): calcularlo del log por defecto, pero poder cambiarlo.
**Hablar con:** `3-execution` (cuánta carga aguanta el laboratorio).

### D6. Perfil horario (picos de carga)

**Problema.** La diapositiva 3 habla de "picos de carga" e "intensidades horarias". Ahora la carga es **constante** durante toda la prueba.

| Opción | Qué implica |
|---|---|
| **a) Constante** (como ahora) | Sencillo |
| **b) Reproducir la curva del log** | Calcular peticiones por minuto/hora del log y hacer que JMeter suba y baje usuarios igual (en JMeter: *Ultimate Thread Group* o *Throughput Shaping Timer*, que son plugins) |

**Recomendación:** b) en una segunda versión. Hay que confirmar con `3-execution` si pueden instalar plugins de JMeter.

### D7. Peticiones con error en los logs

**Problema.** Los logs incluyen peticiones que fallaron (400 sin saldo, 404 cuenta inexistente). Ahora **se incluyen en el modelo**: el `.jmx` también reproducirá esos errores.

| Opción | Qué implica |
|---|---|
| **a) Incluirlas** (como ahora) | Más realista: los usuarios reales también se equivocan |
| **b) Quitarlas** | El `.jmx` solo hace peticiones "correctas"; los errores en la prueba indicarían fallos de la app |

**Recomendación:** a), pero dejarlo explicado en la presentación. Afecta a `parser.py` (filtrar por `status`).

### D8. Qué es "la IA" y cómo la presentamos

**Problema.** La diapositiva habla de "Orquestador de IA". Lo que tenemos es un **modelo estadístico** (cadena de Markov + distribuciones de pausas y datos). Es un modelo aprendido de los datos, pero no es *machine learning* "clásico" ni un LLM.

| Opción | Qué implica |
|---|---|
| **a) Presentarlo así** | "Modelo probabilístico aprendido de los logs": honesto y explicable |
| **b) Añadir una parte con LLM** | P. ej. que un LLM genere bodies realistas o explique los resultados. Más trabajo y más "IA" |
| **c) Añadir ML** | P. ej. agrupar usuarios por comportamiento (clustering) para tener varios tipos de usuario |

**Recomendación:** a) para la primera versión; c) es una mejora natural (tipos de usuario: "el que solo consulta", "el que transfiere"…).

### D9. Qué le entregamos a `3-execution`

**Problema.** Hay que acordar con ellos el formato de entrega.

- ¿Les basta el `.jmx` (que ya lleva todo dentro)?
- ¿Cómo le pasan el host y el puerto de la app en Kubernetes? (`-Jhost=... -Jport=...`)
- ¿Necesitan algo más (número de pods de JMeter, duración…)?

**Hablar con:** Víctor Gargallo (`3-execution`).

---

## 7. Lo que ya está decidido

| Tema | Decisión |
|---|---|
| Formato del log | JSON Lines, una petición por línea, con los campos de la [sección 4 del README](README.md#4-formato-del-log) (acordado con Martina) |
| Nombres de ids en los bodies | camelCase acabado en `Id` (`fromAccountId`, `userId`) |
| Librería de datos | **pandas** (lo piden las diapositivas) |
| Rama de trabajo | Una sola para el grupo: `feature/processing` |
| Demo | Independiente de las demás carpetas, con los datos de `samples/` |
| `jar_parser` | Lee el bytecode desde Python (sin `javap`) |
| Combinar logs y `.jar` | Prior uniforme del `.jar` (`--jar-weight 1`) + bodies desde el DTO si no hay en los logs (D1, D2, D3) |
| Sin logs | Pausa al azar de 1–3 s (`--default-pause`) y 10 usuarios virtuales (`-Jvusers`): **suposiciones**, no datos |
| `--min-probability` | Por defecto `0`: no se quita nada del modelo |

---

## 8. Glosario

| Palabra | Significado |
|---|---|
| **Sesión** | Una visita de un usuario: todas las peticiones con el mismo `sessionId` |
| **Endpoint** | Una ruta de la API con plantilla: `/api/accounts/{id}` |
| **Estado** | Una petición tipo `"GET /api/accounts/{id}"` (método + endpoint). Cada estado es un "sitio" donde puede estar el usuario |
| **Transición** | Pasar de una petición a la siguiente dentro de una sesión |
| **Cadena de Markov** | La tabla de probabilidades "si estás aquí, ¿adónde vas después?" |
| **`END`** | Estado especial: la sesión termina |
| **Think time** | Pausa del usuario entre una petición y la siguiente |
| **Cuantil** | Valor que deja por debajo un % de los datos (el cuantil 0,5 es la mediana) |
| **DataFrame** | Tabla de pandas (filas y columnas) |
| **DTO** | Clase Java que solo transporta datos; sus campos son los campos del JSON del body |
| **Bytecode / `.class`** | El código Java compilado. Un `.jar` es un `.zip` lleno de `.class` |
| **Anotación** | Las etiquetas `@...` de Java (`@GetMapping("/{id}")`): de ahí sacamos los endpoints |
| **`.jmx`** | Archivo XML con un plan de pruebas de JMeter |
| **Usuario virtual (vuser)** | Un "usuario simulado" de JMeter. Cada uno es un hilo que hace sesiones una detrás de otra |
| **Groovy** | El lenguaje de los scripts que se ejecutan dentro de JMeter |
| **Jinja2** | Librería de Python para rellenar plantillas de texto (`{{ variable }}`) |
