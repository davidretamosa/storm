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
./desplegar-objetivo.sh --imagen <imagen> [--puerto N]   # la app a probar (o --jar <fichero.jar>)
./cargar-plan.sh plan.jmx      # carga el plan de esa app (p. ej. el que genera 2-processing)
./lanzar-prueba.sh normal storm     # inyecta en la app objetivo el plan cargado con cargar-plan.sh
./lanzar-prueba.sh normal storm --workers 3   # la misma prueba, repartida entre 3 workers
./quitar.sh                    # borra todo el laboratorio del clúster
```

## La app objetivo: cualquier aplicación

La app que se pone a prueba no está fijada: se despliega con `desplegar-objetivo.sh` a partir de
lo que entregue quien la quiera probar, y dentro del clúster se llama siempre `objetivo`.

| Opción | Qué es |
|---|---|
| `--imagen <imagen>` | Imagen de la app, de cualquier lenguaje: de un registro (`registro.empresa.com/app:1.0`) o construida en el equipo |
| `--jar <fichero.jar>` | `.jar` ejecutable: se mete en una imagen de Java genérica (`../objetivo/Dockerfile`) |
| `--puerto N` | Puerto en el que escucha (por defecto 8080) |
| `--salud /ruta` | Ruta que responde 200 cuando la app está lista (opcional; sin ella basta con que el puerto acepte conexiones) |
| `--java N` | Versión de Java para `--jar` (por defecto 21) |
| `--publicar <registro>` | Sube a un registro la imagen construida en el equipo antes de desplegarla; necesario en la nube (ver abajo) |

```bash
# La bankapp, la app de ejemplo del proyecto (imagen publicada por GitHub Actions)
./desplegar-objetivo.sh --imagen ghcr.io/davidretamosa/storm-bankapp --salud /actuator/health/readiness
# Una app en Go en el puerto 80 (probado con traefik/whoami)
./desplegar-objetivo.sh --imagen traefik/whoami:v1.10.3 --puerto 80
```

### App objetivo en un clúster en la nube (`--publicar`)

Docker Desktop y kind ven las imágenes construidas en el equipo; un clúster en la nube no. Si la
app llega como `.jar` (o como imagen construida en el equipo), hay que subir su imagen a un
registro para que el clúster la descargue:

```bash
docker login ghcr.io          # una vez: usuario de GitHub y token personal con write:packages
./desplegar-objetivo.sh --jar app-cliente.jar --puerto 8080 --publicar ghcr.io/<usuario>
```

El script construye la imagen, la sube como `ghcr.io/<usuario>/storm-objetivo:<fecha-hora>` y
despliega esa. Si el clúster no es Docker Desktop ni kind y la imagen solo está en el equipo, el
script se para y pide `--publicar` (si no, el clúster se quedaría esperando una imagen que no
puede descargar). Una app que ya viene en un registro (`--imagen registro.cliente.com/app:1.0`)
no necesita `--publicar`.

Las imágenes nuevas de ghcr.io son **privadas**. O se hacen públicas en GitHub (*Packages → la
imagen → Package settings → Change visibility*), o se le dan al clúster las credenciales en el
Secret `registro-objetivo`, que `desplegar-objetivo.sh` usa solo si existe:

```bash
kubectl -n lab-jmeter create secret docker-registry registro-objetivo \
  --docker-server=ghcr.io --docker-username=<usuario> --docker-password=<token con read:packages>
```

`lanzar-prueba.sh ... storm` le pasa al plan `host=objetivo` y el puerto de la app, así que el
`.jmx` funciona sin cambios con tal de que use `${__P(host)}` y `${__P(port)}`. Volver a ejecutar
`desplegar-objetivo.sh` sustituye la app. La app sale en `localhost:30081` (en kind,
`localhost:40081`) y sus criterios de aprobado están en `criterios/objetivo.properties`.

## Pruebas distribuidas (`--workers N`)

Sin la opción, un único pod de JMeter genera toda la carga. Con `--workers N` la prueba se
reparte, igual que el modo distribuido de JMeter entre varios equipos, pero lo gestiona
Kubernetes:

```
                       ┌──▶ worker 1 ──┐
Job jmeter (master) ───┼──▶ worker 2 ──┼──peticiones──▶ app objetivo
  reparte y evalúa     └──▶ worker 3 ──┘
                            └──métricas──▶ InfluxDB ──▶ Grafana
```

1. `lanzar-prueba.sh` pide N réplicas del Deployment `jmeter-worker` (`kubectl scale`) y espera
   a que estén listas. Cada worker es un `jmeter-server` con la misma imagen que el master.
2. Saca sus IPs del Service `jmeter-worker` y se las pasa al Job, que hace de master (`-R`).
3. Los workers generan la carga y envían las métricas a InfluxDB; el master recoge los
   resultados y los evalúa con los mismos criterios de siempre.
4. Al terminar, los workers vuelven a 0 réplicas (no ocupan memoria entre pruebas).

Los **usuarios del escenario son el total** y se reparten entre los workers redondeando hacia
arriba (`normal`, 20 usuarios con 3 workers = 7 en cada uno), así que un escenario genera la
misma carga con 1 o con N workers. Nunca se usan más workers que usuarios.

Detalles que ya resuelven los ficheros (son los mismos que hacían falta con varios equipos):
las propiedades de la prueba se envían a los workers con `-G` (con `-J` solo las vería el
master), los puertos RMI son fijos (1099 y 50000 en los workers, 60000 en el master), RMI va
sin SSL y cada pod se anuncia con su IP (`java.rmi.server.hostname`).

## Varios nodos con kind

El Kubernetes de Docker Desktop tiene un solo nodo. Para ver el laboratorio como en un clúster
real (o en la nube), [kind](https://kind.sigs.k8s.io/) crea un clúster en el que cada nodo es un
contenedor de Docker: `kind/cluster.yaml` define 1 nodo de control y 3 de trabajo. Los mismos
ficheros sirven sin cambios; Kubernetes reparte los pods entre los nodos y pone cada worker de
JMeter en un nodo distinto.

```bash
winget install Kubernetes.kind                 # una sola vez (abrir una terminal nueva después)
kind create cluster --config kind/cluster.yaml # crea el clúster "storm" y lo deja activo
./desplegar.sh                                 # detecta kind y copia las imágenes a los nodos
./cargar-plan.sh <plan.jmx>
./lanzar-prueba.sh normal storm --workers 3
kubectl -n lab-jmeter get pods -o wide         # columna NODE: en qué nodo está cada pod
```

En kind los servicios salen por los puertos **400xx** (Grafana `localhost:40000`, app objetivo
`localhost:40081`, Prometheus `localhost:40090`) para no chocar con los 300xx de Docker Desktop.

Para cambiar de clúster: `kubectl config use-context docker-desktop` o `kind-storm`. Todos los
scripts usan el clúster activo. Para borrarlo: `kind delete cluster --name storm`.

Ten en cuenta:
- Los 4 nodos comparten la memoria y la CPU del mismo equipo, así que los tiempos son algo
  peores que en Docker Desktop: sirve para demostrar el reparto, no para medir rendimiento.
- Con los dos clústeres encendidos la memoria de Docker se queda justa: conviene parar uno
  (en Docker Desktop, `kubectl -n lab-jmeter scale deploy --all --replicas=0`).
- En kind cada nodo tiene su propio almacén de imágenes; por eso `desplegar.sh` hace
  `kind load docker-image`. En un clúster en la nube se subirían a un registro.

## Imágenes publicadas en GitHub (registro)

Por defecto, las imágenes propias del laboratorio (app de prueba y JMeter) se construyen en cada
equipo. Un clúster en la nube no puede usarlas: necesita descargarlas de un **registro**. Para
eso, GitHub Actions (`.github/workflows/imagenes.yml`) las construye y las publica en GitHub
Container Registry cada vez que cambia su código en `develop`, junto con la bankapp de ejemplo:

| Imagen | Qué es |
|---|---|
| `ghcr.io/davidretamosa/storm-lab-app` | La app de prueba del laboratorio |
| `ghcr.io/davidretamosa/storm-lab-jmeter` | JMeter (master y workers) |
| `ghcr.io/davidretamosa/storm-bankapp` | La bankapp, la app de ejemplo (`src/1-input/java-app-mock`) |

Etiquetas: `latest` (lo último de `develop`), el nombre de la rama y el commit (`sha-xxxxxxx`).

Para desplegar con ellas, sin construir nada en el equipo:

```bash
REGISTRO=ghcr.io/davidretamosa ./desplegar.sh
REGISTRO=ghcr.io/davidretamosa ETIQUETA=sha-1a2b3c4 ./desplegar.sh   # una versión concreta
./desplegar-objetivo.sh --imagen ghcr.io/davidretamosa/storm-bankapp --salud /actuator/health/readiness
```

`desplegar.sh` cambia las imágenes de los `.yaml` por las del registro y Kubernetes las
descarga; `lanzar-prueba.sh` usa para el master la misma imagen que los workers, así que no
necesita la opción. Para volver a las locales, `./desplegar.sh` sin `REGISTRO`. La app objetivo
va aparte, con `desplegar-objetivo.sh --imagen`, venga del registro que venga.

Como el repositorio es público, las imágenes también lo son: se descargan sin contraseña.

## Escenarios

Cada escenario es un fichero de `escenarios/` que solo fija la carga; el plan (`plan.jmx`) es
siempre el mismo.

| Escenario | Usuarios | Subida | Duración | Pregunta que responde |
|---|---|---|---|---|
| `humo`   | 2   | 5 s   | 30 s  | ¿Funciona todo? |
| `normal` | 20  | 30 s  | 3 min | ¿Aguanta el día a día con holgura? |
| `pico`   | 80  | 10 s  | 2 min | ¿Qué notan los usuarios con 4 veces más tráfico de golpe? |
| `estres` | 150 | 4 min | 5 min | ¿En qué punto se dispara el tiempo de respuesta o aparecen errores? |
| `rotura` | 400, sin pausas | 10 min | 10 min | ¿Dónde está el límite de la app y qué se rompe primero? |

Los planes de `2-processing` repiten las pausas reales de los usuarios entre peticiones, así
que muchos usuarios generan poco tráfico. `factor_pausa` las escala: 1 = pausas reales (por
defecto), 0 = sin pausas. `rotura` usa 0 para llegar al límite de la app con un solo JMeter.

Las propiedades (`vusers`, `rampup`, `duration`, `host`, `port`) son las mismas que usa el
plan que genera `2-processing`, así que estos escenarios también valdrán para él. Para
crear uno nuevo basta con copiar un fichero, cambiar los números y volver a ejecutar
`./desplegar.sh`.

## Criterios de aprobado

Cada prueba termina con un veredicto, **SUPERADA** o **NO SUPERADA**, según los criterios del
objetivo (`criterios/app.properties` para la app de prueba y `criterios/objetivo.properties`
para la app objetivo). Los de la app objetivo son los de la bankapp; ajústalos a lo que se exija
a la app que se prueba:

| Criterio | app de prueba | app objetivo |
|---|---|---|
| `MAX_ERRORES_PCT`: % máximo de **errores del servidor** de cada operación | 1 % | 0,1 % |
| `MAX_P95_MS`: el 95 % de las peticiones debe responder en menos de | 1000 ms | 500 ms |

Se distinguen dos tipos de respuesta fallida:

| Tipo | Ejemplos | ¿Cuenta para el veredicto? |
|---|---|---|
| **Error del servidor**: 5xx o sin respuesta | deadlock (500), app caída, timeout | **Sí**: es un fallo de la app |
| **Rechazo (4xx)** | saldo insuficiente, datos inválidos, cuenta inexistente | **No**: la app responde bien a un error del usuario; se muestra como información |

Al acabar, JMeter muestra una tabla por operación (peticiones, errores del servidor, rechazos y
tiempo medio) y marca la que supera el límite. Si la prueba no se supera, el Job queda en estado
`Failed` y `lanzar-prueba.sh` termina con código 1, así que también sirve para automatizarlo.
La evaluación la hace `ejecutar-y-evaluar.sh` dentro del pod de JMeter.

## Resultados de cada prueba

Cada prueba deja sus resultados en el equipo, en `resultados/<escenario>-<objetivo>-<fecha>/`
(con `--workers N`: `<escenario>-<objetivo>-Nworkers-<fecha>/`; esta carpeta no se sube a git):

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
| App objetivo | http://localhost:30081                   |
| Grafana    | http://localhost:30000/d/lab-jmeter-k8s (admin / admin) |
| Prometheus | http://localhost:30090                     |

## Qué hay en cada fichero

| Fichero | Qué es |
|---|---|
| `00-namespace.yaml` | Espacio `lab-jmeter`: todo el laboratorio vive aquí |
| `almacenamiento.yaml` | Discos persistentes (InfluxDB, Prometheus, resultados) y el pod auxiliar `resultados` |
| `app.yaml` | La app de prueba del laboratorio (Deployment + Service `app:8080`) |
| `objetivo.yaml` | Plantilla de la app objetivo; la rellena `desplegar-objetivo.sh` (imagen, puerto, salud) |
| `desplegar-objetivo.sh` | Despliega como app objetivo cualquier app, a partir de su imagen o de su `.jar` |
| `influxdb.yaml` | InfluxDB 1.8, base de datos `jmeter` |
| `prometheus.yaml` | Prometheus y sus permisos para leer el cAdvisor del kubelet |
| `grafana.yaml` | Grafana con datasources y dashboard ya configurados |
| `jmeter-job.yaml` | Una prueba = un Job que ejecuta `plan.jmx` y termina (con `--workers`, hace de master) |
| `jmeter-workers.yaml` | Workers de JMeter para las pruebas distribuidas (Deployment a 0 réplicas + Service) |
| `kind/cluster.yaml` | Clúster de 4 nodos con kind para probar el reparto entre máquinas |
| `backend-listener.xml` | Envío de métricas a InfluxDB que se añade a los planes que no lo traen |
| `ejecutar-y-evaluar.sh` | Dentro del Job: lanza JMeter y comprueba los criterios de aprobado |
| `criterios/` | Criterios de aprobado de cada objetivo (`app` y `objetivo`, que usa el objetivo `storm`) |
| `escenarios/` | Carga de cada escenario (humo, normal, pico, estres, rotura) |
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
