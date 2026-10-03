# 2-processing — Orquestador

Lee los logs de acceso de la aplicación objetivo, modela el tráfico y genera un plan de JMeter (`.jmx`) que lo reproduce.

```
access.log ──► log_parser ──► traffic_model ──► jmx_generator ──► plan .jmx
                                   ▲
.jar ──────► jar_parser ───────────┘   (pendiente)
```

| Carpeta | Qué hace | Estado |
|---|---|---|
| `log_parser/` | Pasa las líneas `ACCESS` del log a un DataFrame ordenado por tiempo. | Hecho |
| `jar_parser/` | Extraer del `.jar` los endpoints declarados. | **Pendiente, vacío** |
| `traffic_model/` | `markov.py`: cadena de Markov de la navegación (cómo empiezan las sesiones, qué petición sigue a cuál y cuándo terminan). `think_time.py`: pausas observadas entre peticiones. `payloads.py`: valores de los `{parámetros}` de ruta y modelo de los cuerpos JSON. `scaling.py`: cuántos usuarios virtuales simular. | Primera versión |
| `jmx_generator/` | Rellena la plantilla `templates/plan.jmx.j2` con el modelo: cada usuario virtual recorre la cadena de Markov (ver abajo). | Primera versión |
| `main.py` | Encadena los pasos. | Hecho |
| `samples/` | Log de ejemplo inventado en el formato de la app del banco (30 sesiones, las 11 peticiones de la API) para probar sin la app. | — |
| `tests/` | Tests de cada módulo. | — |

Partimos del código base generado con Gemini (`codigo_gemini.py`), repartido en estas carpetas y corregido para que se ejecute.

## Cómo se ejecuta

```bash
cd src/2-processing
python -m venv .venv
source .venv/bin/activate        # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt

python main.py samples/access_sample.log          # -> output/generated_scenario.jmx
python main.py ruta/access.log --host bankapp --port 8080 --output output/plan.jmx
pytest
```

El host y el puerto también se pueden cambiar al lanzar JMeter: `jmeter -n -t plan.jmx -Jhost=... -Jport=...`.

## Formato de log que espera

El `access.log` de la app del banco (`1-input/java-app-mock`): **JSON Lines, una petición por línea**:

```json
{"timestamp":"2026-10-01T11:42:35.123Z","requestId":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","sessionId":"sess-9f8e7d6c","userId":12,"method":"POST","endpoint":"/api/accounts/{id}/deposit","path":"/api/accounts/3/deposit","status":200,"durationMs":45,"requestSizeBytes":17,"responseSizeBytes":256,"body":{"amount":200.00}}
```

| Campo | Uso |
|---|---|
| `timestamp` (UTC) | Orden de las peticiones y pausas entre ellas |
| `sessionId` | **Imprescindible**: agrupa las peticiones de una misma visita (cadena de Markov) |
| `method` + `endpoint` | Estado de la cadena. `endpoint` es la ruta con plantilla (`/api/accounts/{id}`) |
| `path` | Ruta concreta (`/api/accounts/3`): de aquí salen los valores de los `{id}` |
| `status`, `durationMs` | Errores y tiempos de respuesta |
| `body` | Cuerpo JSON recibido (`null` si no hay): modelo de los cuerpos que enviará JMeter |

- Obligatorios: `timestamp`, `method` y `endpoint`; las líneas que no son JSON o no los tienen se ignoran.
- `requestId`, `userId` y los tamaños en bytes se leen pero el modelo aún no los usa.
- Los campos que son ids dentro del `body` tienen que acabar en `Id` (`fromAccountId`, `userId`): se toman de los valores vistos en vez de inventarse.

## Cómo simula el `.jmx` el tráfico

Cada iteración de un usuario virtual es **una sesión** que recorre la cadena de Markov aprendida de los logs:

```
Thread Group
├── Flow Control Action "Nueva sesión" + JSR223  -> elige la 1ª petición (model.start)
└── While stormState != END
    ├── JSR223 Timer          -> pausa observada en los logs para esa transición
    ├── Switch ${stormIndex}  -> una petición HTTP por estado de la cadena
    └── JSR223 PostProcessor  -> tras cada petición elige la siguiente (o END) según las probabilidades
```

- El modelo (`states`, `start`, `transitions`, `think_time_ms`) va incrustado como JSON en los scripts Groovy del `.jmx`: el plan es un único fichero autocontenido.
- Las pausas se guardan como 20 cuantiles de lo observado en cada transición y se elige uno al azar (se recortan a 2 min).
- Al elegir cada petición se rellenan sus datos a partir de los logs:
  - **`{parámetros}` de ruta**: uno de los valores vistos en `ruta=` para ese endpoint, según su frecuencia.
  - **Cuerpo JSON** (`Content-Type: application/json`), campo a campo: los números toman un valor entre el mínimo y el máximo observados; los textos, los ids (`id`, `...Id`, `..._id`) y los objetos, uno de los valores vistos. Cada campo aparece con la misma frecuencia que en los logs.
- `--max-steps` (50 por defecto) corta las sesiones con bucles; `--min-probability` descarta transiciones raras y renormaliza.

## Limitaciones conocidas (TODO)

- **No hay correlación entre peticiones**: tras `POST /api/accounts` el siguiente `deposit` usa un id visto en los logs, no el de la cuenta recién creada (habría que extraerlo de la respuesta). Los campos de un cuerpo se generan por separado (p. ej. `fromAccountId` puede coincidir con `toAccountId`), y los valores únicos (emails) se repiten.
- **Los nombres de los campos de los `body` del log de ejemplo son supuestos**: hay que ajustarlos cuando estén los DTOs de `java-app-mock`.
- **No hay perfil horario**: la intensidad es constante durante la prueba.
- **`scaling.py` es una heurística** del código base (sesiones observadas × 1,5), no una predicción.
- **El manifiesto de Kubernetes** que generaba el código base se ha quitado: el despliegue de JMeter es cosa de `3-execution` y hay que acordar con ellos qué les pasamos.
