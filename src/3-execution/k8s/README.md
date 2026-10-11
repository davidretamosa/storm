# Laboratorio de carga en Kubernetes

El mismo laboratorio que `../lab-jmeter` (Docker Compose), pero desplegado en Kubernetes:
JMeter lanza tráfico contra la app, InfluxDB guarda los resultados, Prometheus mide CPU y
memoria y Grafana lo enseña todo.

```
Job jmeter ──peticiones HTTP──▶ app
     └──métricas de la prueba──▶ InfluxDB ──┐
cAdvisor del kubelet ──▶ Prometheus ────────┴──▶ Grafana
```

## Requisitos

- Docker Desktop con Kubernetes activado (*Settings → Kubernetes → Enable Kubernetes*).
- Una terminal con `sh` (en Windows, Git Bash).

## Uso

Desde esta carpeta (`src/3-execution/k8s`):

```bash
./desplegar.sh                 # construye las imágenes y levanta app, InfluxDB, Prometheus y Grafana
./lanzar-prueba.sh normal      # lanza una prueba con el escenario indicado (por defecto, humo)
./quitar.sh                    # borra todo el laboratorio del clúster
```

## Escenarios

Cada escenario es un fichero de `escenarios/` que solo fija la carga; el plan (`plan.jmx`) es
siempre el mismo.

| Escenario | Usuarios | Subida | Duración | Pregunta que responde |
|---|---|---|---|---|
| `humo`   | 2   | 5 s   | 30 s  | ¿Funciona todo? |
| `normal` | 20  | 30 s  | 3 min | ¿Aguanta el día a día con holgura? |
| `pico`   | 80  | 10 s  | 2 min | ¿Qué notan los usuarios con 4 veces más tráfico de golpe? |
| `estres` | 150 | 4 min | 5 min | ¿En qué punto se dispara el tiempo de respuesta o aparecen errores? |

Las propiedades (`vusers`, `rampup`, `duration`, `host`, `port`) son las mismas que usa el
plan que genera `2-processing`, así que estos escenarios también valdrán para él. Para
crear uno nuevo basta con copiar un fichero, cambiar los números y volver a ejecutar
`./desplegar.sh`.

En Grafana todas las pruebas comparten el dashboard; se distinguen por la hora. El nombre
del escenario queda guardado en InfluxDB (etiqueta `application`).

| Servicio   | URL                                        |
|------------|--------------------------------------------|
| App        | http://localhost:30080/hello               |
| Grafana    | http://localhost:30000/d/lab-jmeter-k8s (admin / admin) |
| Prometheus | http://localhost:30090                     |

## Qué hay en cada fichero

| Fichero | Qué es |
|---|---|
| `00-namespace.yaml` | Espacio `lab-jmeter`: todo el laboratorio vive aquí |
| `app.yaml` | La app bajo prueba (Deployment + Service `app:8080`) |
| `influxdb.yaml` | InfluxDB 1.8, base de datos `jmeter` |
| `prometheus.yaml` | Prometheus y sus permisos para leer el cAdvisor del kubelet |
| `grafana.yaml` | Grafana con datasources y dashboard ya configurados |
| `jmeter-job.yaml` | Una prueba = un Job que ejecuta `plan.jmx` y termina |
| `grafana/lab-jmeter-k8s.json` | Dashboard: el de `lab-jmeter` con CPU y memoria por pod |

No se duplica nada de `../lab-jmeter`: `desplegar.sh` construye las imágenes desde
`lab-jmeter/app` y `lab-jmeter/jmeter`, y mete en ConfigMaps su `plan.jmx` y la
configuración de Grafana.

## Notas

- **Imágenes locales**: Kubernetes de Docker Desktop usa las imágenes que construye
  Docker en el propio equipo (`imagePullPolicy: Never`). En un clúster real habría que
  subirlas a un registro (Docker Hub, GitHub Container Registry...).
- **Cambiar el plan**: edita `../lab-jmeter/jmeter/plan.jmx` y vuelve a ejecutar
  `./desplegar.sh`; la siguiente prueba ya usa el plan nuevo.
- **CPU y memoria**: no hace falta desplegar cAdvisor, el kubelet ya lo incluye. En Docker
  Desktop da los datos por pod, no por contenedor; como cada pod tiene un solo
  contenedor, es lo mismo.
- **Vigilancia de la app** (`readinessProbe` en `app.yaml`): tiene margen amplio a propósito.
  Con un margen de 1 s, bajo carga Kubernetes sacaba la app del tráfico por tardar en
  responder y provocaba errores "Connection refused" y esperas de hasta 25 s que no eran
  culpa de la app.
- **Datos**: InfluxDB y Prometheus guardan los datos en el propio pod; se pierden al
  borrarlo o con `./quitar.sh`.
