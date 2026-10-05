# Laboratorio de pruebas de carga (Docker + JMeter)

JMeter envía tráfico a una aplicación Java (`.jar`) y mide cómo responde. Todo corre en Docker y se lanza con un solo comando.

```
[ JMeter ]  ── peticiones HTTP ──▶  [ app (.jar) ]
 plan.jmx + escenario                 puerto 8080
```

Primera validación (escenario `normal`): **7.223 peticiones en 6 min (~20 pet/s), 37 ms de media, 0 % de errores**.

## Ficheros

| Fichero | Qué es |
|---|---|
| `Dockerfile` | Mete el `.jar` de la app en una imagen con Java 21 |
| `docker-compose.yml` | Arranca la app y JMeter juntos |
| `jmeter/plan.jmx` | Plan de pruebas: qué peticiones se envían |
| `jmeter/escenarios/*.properties` | Cuánta carga y en qué proporción: `humo`, `normal`, `pico`, `estres` |
| `jmeter/Dockerfile`, `jmeter/ejecutar.sh` | Imagen de JMeter y script que lanza cada prueba y genera el informe |

`lab-api.jar` y `resultados/` no se suben al repositorio (se generan en cada ordenador).

## Requisito

Docker Desktop abierto y en verde (*Engine running*).

## Puesta en marcha (una sola vez)

La app de prueba es la echo-api (`src/1-input/echo-api`). Hay que compilarla y copiar el `.jar` a esta carpeta. No hace falta tener Java ni Maven instalados:

```powershell
cd src/1-input/echo-api
docker run --rm -v "${PWD}:/src" -w /src maven:3.9-eclipse-temurin-21 mvn -B package -DskipTests
copy target\lab-api.jar ..\..\3-execution\docker\
```

## Uso

Desde esta carpeta (`src/3-execution/docker`):

```powershell
docker compose up -d                    # arranca la app
docker compose run --rm jmeter humo     # lanza una prueba
docker compose down                     # apaga todo
```

- Comprobar la app: http://localhost:8080/actuator/health → `{"status":"UP"}`
- Informe de cada prueba: `resultados/<escenario>-<fecha>/informe/index.html`
- La primera vez, la imagen de JMeter tarda unos minutos en construirse (descarga JMeter).

| Escenario | Carga | Duración |
|---|---|---|
| `humo` | 2 pet/s | 30 s |
| `normal` | rampa a 20 pet/s | 6 min |
| `pico` | 20 → 150 → 20 pet/s | 5,5 min |
| `estres` | escalones de 25 a 400 pet/s | 11 min |

## Cambiar la app que se prueba

Para probar otra app (por ejemplo, la del Grupo 1), basta con copiar su `.jar` en esta carpeta, cambiar el nombre en la línea `COPY` del `Dockerfile` y ejecutar `docker compose up -d --build`. El `plan.jmx` también habrá que adaptarlo a los endpoints de esa app.

## Siguientes pasos

- Añadir InfluxDB y Grafana para ver las pruebas en gráficos en tiempo real.
- Añadir Prometheus para ver la CPU, la memoria y el estado de la app.
- Desplegar el laboratorio en Kubernetes.
