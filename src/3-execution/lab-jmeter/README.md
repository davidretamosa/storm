# Laboratorio de carga con Docker Compose

La versión más sencilla del laboratorio: todo corre en el propio ordenador con Docker Compose.
JMeter lanza peticiones contra una app de prueba, InfluxDB guarda los resultados, Prometheus y
cAdvisor miden la CPU y la memoria, y Grafana lo enseña todo.

```
JMeter ──peticiones HTTP──▶ app
  └──métricas de la prueba──▶ InfluxDB ──┐
cAdvisor ──▶ Prometheus ─────────────────┴──▶ Grafana
```

Es también la **base del laboratorio de Kubernetes** (`../k8s`): reutiliza de aquí la app,
la imagen de JMeter, el `plan.jmx` y la configuración de Grafana.

## Requisitos

Docker Desktop abierto y en marcha.

## Uso

Desde esta carpeta (`src/3-execution/lab-jmeter`):

```bash
docker compose up -d --build          # levanta app, InfluxDB, Prometheus, cAdvisor y Grafana
docker compose run --rm jmeter        # lanza la prueba (20 usuarios, 100 vueltas cada uno)
docker compose stop                   # lo apaga sin borrar nada (docker compose start para volver)
```

| Servicio   | URL |
|------------|-----|
| App        | http://localhost:8080/hello |
| Grafana    | http://localhost:3000/d/lab-jmeter/lab-jmeter (admin / admin) |
| Prometheus | http://localhost:9090 |
| cAdvisor   | http://localhost:8081 |

Los resultados de la última prueba quedan en `resultados/resultados.jtl` (se sobrescriben en
cada prueba).

### Cambiar la carga

El `plan.jmx` acepta las mismas propiedades que el laboratorio de Kubernetes. Por ejemplo,
80 usuarios durante 2 minutos:

```bash
docker compose run --rm jmeter -n -t /test/plan.jmx -l /resultados/resultados.jtl -f -Jvusers=80 -Jrampup=10 -Jduration=120 -Jloops=-1
```

| Propiedad | Qué es | Por defecto |
|---|---|---|
| `vusers` | usuarios simultáneos | 20 |
| `rampup` | segundos para llegar a todos los usuarios | 30 |
| `duration` | duración máxima en segundos | 86400 (sin límite práctico) |
| `loops` | vueltas por usuario (`-1` = sin límite, hasta `duration`) | 100 |
| `host`, `port` | app objetivo | `app`, `8080` |

## Qué hay en cada carpeta

| Carpeta / fichero | Qué es |
|---|---|
| `app/` | App de prueba: `App.java` con dos endpoints (`/hello` responde al momento, `/slow` tarda 300 ms) y su `app.jar` |
| `jmeter/` | Imagen de JMeter 5.6.3 y el plan de prueba `plan.jmx` |
| `prometheus/` | Configuración de Prometheus (lee cAdvisor) |
| `grafana/provisioning/` | Datasources y dashboard "Lab JMeter", cargados al arrancar Grafana |
| `docker-compose.yml` | Todos los servicios; JMeter solo arranca con `docker compose run` |

## Limitaciones conocidas

- **CPU y memoria de Docker entero, no de cada contenedor**: con Docker Desktop, cAdvisor
  v0.49.1 no distingue contenedores. El laboratorio de Kubernetes sí da los datos por pod.
- **Puerto 8081 (cAdvisor)**: si otro programa lo usa, cAdvisor no arranca. Se puede cambiar solo
  en tu equipo con un `docker-compose.override.yml` junto al `docker-compose.yml` (no lo subas a git):
  `services: { cadvisor: { ports: !override ["8088:8080"] } }`.
- **Sin veredicto ni histórico de pruebas**: para criterios de aprobado, escenarios y resultados
  guardados por prueba, usa el laboratorio de Kubernetes (`../k8s`).
- **Contraseñas por defecto** (Grafana admin/admin, InfluxDB sin contraseña): solo para uso local.
