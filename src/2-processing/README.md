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
| `traffic_model/` | `markov.py`: probabilidad de pasar de una petición a la siguiente dentro de una sesión. `scaling.py`: cuántos usuarios virtuales simular. | Primera versión |
| `jmx_generator/` | Rellena la plantilla `templates/plan.jmx.j2` con el modelo. | Primera versión |
| `main.py` | Encadena los pasos. | Hecho |
| `samples/` | Log de ejemplo inventado (15 sesiones en la Bank App) para probar sin la app. | — |
| `tests/` | Tests de cada módulo. | — |

Partimos del código base generado con Gemini (`codigo_gemini.py`), repartido en estas carpetas y corregido para que se ejecute.

## Cómo se ejecuta

```bash
cd src/2-processing
python3 -m venv .venv && source .venv/bin/activate
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
- **`sesion` es imprescindible**: el `[requestId]` cambia en cada petición, y sin un identificador de sesión/usuario no se pueden reconstruir las secuencias de navegación. Hay que acordarlo con quien implemente el `RequestLoggingFilter` de `java-app-mock` (p. ej. leyendo una cabecera `X-Session-Id`).

## Limitaciones conocidas (TODO)

- **El `.jmx` aún no es probabilístico**: tiene una petición por cada transición con probabilidad ≥ 10 %, en secuencia. Falta que JMeter elija la siguiente petición según la cadena de Markov (p. ej. con Throughput Controllers).
- **Los POST van sin cuerpo** y los parámetros de ruta (`{id}`) valen siempre `1`.
- **`scaling.py` es una heurística** del código base (sesiones observadas × 1,5), no una predicción.
- **El manifiesto de Kubernetes** que generaba el código base se ha quitado: el despliegue de JMeter es cosa de `3-execution` y hay que acordar con ellos qué les pasamos.
- No se ha probado todavía el `.jmx` en un JMeter real.
