# 3-execution — Inyección de tráfico y observabilidad

Laboratorio local (Docker Compose) para lanzar pruebas de carga con **JMeter** contra la aplicación objetivo y ver el resultado en **Grafana**.

```
JMeter ──peticiones──▶ App (Spring Boot) ──▶ logs/access.log
  │                        │ /actuator/prometheus
  ▼                        ▼
InfluxDB               Prometheus
  └──────────┬─────────────┘
             ▼
          Grafana  (http://localhost:3001)
```

## Carpetas

| Carpeta | Contenido |
|---|---|
| `docker/` | `docker-compose.yml` y `.env` (comportamiento simulado y recursos de la app) |
| `jmeter/` | `plan.jmx` (plantilla única y parametrizada), `escenarios/*.properties`, imagen de JMeter |
| `observabilidad/` | Configuración de Prometheus y de Grafana (data sources y dashboard ya provisionados) |
| `k8s/` | Pendiente: despliegue del mismo laboratorio en Kubernetes |

La app que se prueba ahora es `src/1-input/echo-api/`, una API mínima de entrada/salida que sirve mientras la bankapp (`java-app-mock`) está en desarrollo. Para cambiar de app, basta con cambiar la ruta `build:` del servicio `api` en `docker/docker-compose.yml`.

## Uso

Requisito: Docker Desktop en marcha.

```bash
cd src/3-execution/docker
docker compose up -d --build            # arranca app + InfluxDB + Prometheus + Grafana
docker compose run --rm jmeter humo     # prueba de 30 s (también: normal, pico, estres)
docker compose down                     # parar (añadir -v para borrar métricas)
```

- App: http://localhost:8080/api/eco?mensaje=hola
- Grafana: http://localhost:3001 (admin / admin)
- Informe de cada prueba: `docker/resultados/<id>/informe/index.html`

## Escenarios

| Escenario | Carga | Duración | Qué responde |
|---|---|---|---|
| `humo` | 2 pet/s | 30 s | ¿Funciona el laboratorio? |
| `normal` | rampa a 20 pet/s | 6 min | ¿Aguanta el día a día? |
| `pico` | 20 → 150 → 20 pet/s | ~5,5 min | ¿Soporta un pico y se recupera? |
| `estres` | 25 → 50 → 100 → 200 → 400 pet/s | ~11 min | ¿Dónde está el límite? |

Cada escenario es un `.properties` con la forma de la carga (`schedule`, Open Model Thread Group) y el reparto entre operaciones (`peso_*`). **Contrato con el orquestador (`2-processing/jmx_generator`)**: a partir de los logs, generar un `.properties` con estos valores; la estructura del `.jmx` (cabeceras, listener de InfluxDB, sorteo por pesos) se mantiene.

## Dashboard

Estado general (app arriba/abajo, pet/s, % errores, p95) · Tráfico por operación · Tiempos p50/p95/p99 · Errores por código HTTP y por tipo de excepción · CPU, memoria JVM, hilos de Tomcat y GC.

## Requisitos para la app objetivo

Para que cualquier app (p. ej. la bankapp) se vea completa en el dashboard, necesita:

- `spring-boot-starter-actuator` + `micrometer-registry-prometheus` y exponer `health,prometheus` en `management.endpoints.web.exposure.include`.
- `management.metrics.distribution.percentiles-histogram.http.server.requests=true` (para p95/p99).
- Opcional: contador `api.errores{tipo,estado}` en el manejador global de excepciones (ver `echo-api/.../ManejadorErrores.java`).
