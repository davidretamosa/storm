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
./lanzar-prueba.sh normal bankapp   # la misma prueba contra la bankapp (ver ../bankapp)
./simular-clientes.sh 5 8      # 8 clientes simulados usan la bankapp 5 min; recoge sus logs
./generar-plan.sh              # genera el plan con 2-processing (logs recogidos + .jar)
./lanzar-prueba.sh normal storm     # ejecuta el plan generado por 2-processing
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

## Criterios de aprobado

Cada prueba termina con un veredicto, **SUPERADA** o **NO SUPERADA**, según los criterios del
objetivo (`criterios/app.properties` y `criterios/bankapp.properties`):

| Criterio | app | bankapp |
|---|---|---|
| `MAX_ERRORES_PCT`: % máximo de errores de **cada** operación | 1 % | 0,1 % |
| `MAX_P95_MS`: el 95 % de las peticiones debe responder en menos de | 1000 ms | 500 ms |

Al acabar, JMeter muestra una tabla por operación (peticiones, % de errores y tiempo medio)
y marca la que supera el límite. Si la prueba no se supera, el Job queda en estado
`Failed` y `lanzar-prueba.sh` termina con código 1, así que también sirve para
automatizarlo. La evaluación la hace `ejecutar-y-evaluar.sh` dentro del pod de JMeter.

Ejemplo real (escenario `normal` contra la bankapp):

```
[FALLO] Errores: "POST /api/transfers" tiene un 0.30 %, el máximo es 0.1 %
[OK]    Tiempo: el 95 % de las peticiones responde en 56 ms o menos (máximo 500 ms)
VEREDICTO: PRUEBA NO SUPERADA
```

## Resultados de cada prueba

Cada prueba deja sus resultados en el equipo, en `resultados/<escenario>-<objetivo>-<fecha>/`
(esta carpeta no se sube a git):

| Fichero | Qué es |
|---|---|
| `informe/index.html` | Informe HTML de JMeter: gráficas, percentiles y errores de esa prueba |
| `veredicto.txt` | Tabla por operación y resultado de los criterios de aprobado |
| `resultados.jtl` | Todas las peticiones, una por línea (separado por tabuladores) |
| `jmeter.log` | Log de JMeter |

Así se pueden guardar y comparar pruebas (por ejemplo, la bankapp antes y después de un
arreglo). Dentro del clúster también quedan en el disco `jmeter-resultados`.

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
| `almacenamiento.yaml` | Discos persistentes (InfluxDB, Prometheus, resultados) y el pod auxiliar `resultados` |
| `app.yaml` | La app bajo prueba (Deployment + Service `app:8080`) |
| `influxdb.yaml` | InfluxDB 1.8, base de datos `jmeter` |
| `prometheus.yaml` | Prometheus y sus permisos para leer el cAdvisor del kubelet |
| `grafana.yaml` | Grafana con datasources y dashboard ya configurados |
| `jmeter-job.yaml` | Una prueba = un Job que ejecuta `plan.jmx` y termina |
| `generador-job.yaml` | Job que ejecuta el generador de 2-processing sobre el `.jar` y los logs de la bankapp |
| `simulador-job.yaml` | Job con el simulador de clientes (`../simulador/simulador.py`) |
| `backend-listener.xml` | Envío de métricas a InfluxDB que se añade a los planes que no lo traen |
| `ejecutar-y-evaluar.sh` | Dentro del Job: lanza JMeter y comprueba los criterios de aprobado |
| `criterios/` | Criterios de aprobado de cada objetivo (app y bankapp) |
| `escenarios/` | Carga de cada escenario (humo, normal, pico, estres) |
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
- **Datos**: InfluxDB, Prometheus y los resultados de JMeter están en discos persistentes:
  sobreviven a reinicios de pods y de Docker. Solo se borran con `./quitar.sh`, que elimina
  el namespace entero (lo copiado en `resultados/` del equipo se conserva).
