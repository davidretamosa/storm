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
| `samples/` | Log de ejemplo inventado (15 sesiones en la Bank App) para probar sin la app. | — |
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

El mismo que el `access.log` de la echo-api de `3-execution`, **más un campo `sesion=`**:

```
2026-10-01T09:01:20.485+02:00 INFO  [aa05b2715945] ACCESS - metodo=GET endpoint=/api/users/{id} ruta=/api/users/1 query=- estado=200 duracionMs=12 bytesEntrada=0 cliente=172.18.0.6 sesion=s05
```

- `endpoint` es la ruta con plantilla (`/api/users/{id}`), no la concreta; así todas las peticiones a usuarios cuentan como el mismo estado.
- **`cuerpo` tiene que ser el último campo** de la línea (puede tener espacios). `-` = sin cuerpo; los recortados por la app (acaban en `...`) se ignoran.
- **`sesion` es imprescindible**: el `[requestId]` cambia en cada petición, y sin un identificador de sesión/usuario no se pueden reconstruir las secuencias de navegación. Hay que acordarlo con quien implemente el `RequestLoggingFilter` de `java-app-mock` (p. ej. leyendo una cabecera `X-Session-Id`).

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
- **Los nombres de los campos del log de ejemplo son supuestos**: los DTOs de `java-app-mock` aún están vacíos.
- **No hay perfil horario**: la intensidad es constante durante la prueba.
- **`scaling.py` es una heurística** del código base (sesiones observadas × 1,5), no una predicción.
- **El manifiesto de Kubernetes** que generaba el código base se ha quitado: el despliegue de JMeter es cosa de `3-execution` y hay que acordar con ellos qué les pasamos.
