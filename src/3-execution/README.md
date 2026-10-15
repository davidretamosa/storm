# 3-execution: ejecución de las pruebas de carga

Esta parte de STORM **ejecuta los planes de prueba (`.jmx`) contra la aplicación y mide cómo
responde**: lanza usuarios simulados con JMeter, recoge tiempos de respuesta, errores, CPU y
memoria, los muestra en Grafana y da un veredicto de si la aplicación aguanta.

```
1-input            2-processing                 3-execution (esta carpeta)
bankapp + logs ──▶ genera el plan .jmx ──▶ JMeter lo ejecuta contra la bankapp
                                            └─▶ InfluxDB / Prometheus ──▶ Grafana + veredicto
```

Las tres partes ya funcionan enlazadas en el Kubernetes local (Docker Desktop): la bankapp
(1-input) y el generador (2-processing) se compilan desde sus ramas de Git y se ejecutan
dentro del clúster junto al laboratorio.

## Las carpetas

| Carpeta | Qué es | Cuándo usarla |
|---|---|---|
| [`k8s/`](k8s/README.md) | **Laboratorio en Kubernetes** (el principal): escenarios, criterios de aprobado, resultados guardados por prueba, CPU y memoria por pod | Para las pruebas de verdad y la demo |
| [`lab-jmeter/`](lab-jmeter/README.md) | Laboratorio con Docker Compose: la versión sencilla, con una app de prueba | Para entender el laboratorio o probar algo rápido. `k8s/` reutiliza sus piezas |
| [`bankapp/`](bankapp/README.md) | Compila la bankapp de `1-input` y su plan de prueba provisional | Lo usa `k8s/` para probar la aplicación real |
| `generador/` | Empaqueta el generador de planes de `2-processing` (`construir-imagen.sh`) | Lo usa `k8s/generar-plan.sh` |
| `simulador/` | Simulador de clientes: usa la bankapp como personas (5 perfiles, pausas de 1 a 10 s) para que genere logs | Lo usa `k8s/simular-clientes.sh` |
| `docker/` | Vacía (estructura inicial del repositorio) | — |

## Prueba de punta a punta (las tres partes)

```bash
cd src/3-execution
bankapp/construir-imagen.sh          # 1-input: compila la bankapp (con su sistema de logs)
generador/construir-imagen.sh        # 2-processing: empaqueta el generador desde su rama
k8s/desplegar.sh                     # levanta el laboratorio con la bankapp
k8s/generar-plan.sh repo             # el modelo aprende de los logs de 1-input (Git) y del .jar
                                     # (alternativa: k8s/simular-clientes.sh y k8s/generar-plan.sh)
k8s/lanzar-prueba.sh normal storm    # 3-execution: ejecuta ese plan contra la bankapp
```

Los planes de 2-processing no envían métricas a InfluxDB: el laboratorio les añade el envío
automáticamente (`k8s/backend-listener.xml`), así que se ven en Grafana sin cambiar nada.

## Empezar en 3 comandos (plan provisional)

Requisito: Docker Desktop con Kubernetes activado (*Settings → Kubernetes*). En Windows, desde
Git Bash:

```bash
cd src/3-execution
bankapp/construir-imagen.sh             # compila la bankapp (solo la primera vez o si cambia)
k8s/desplegar.sh                        # levanta el laboratorio en Kubernetes
k8s/lanzar-prueba.sh normal bankapp     # prueba de 3 minutos con 20 usuarios
```

Al terminar, la prueba muestra una tabla por operación y el veredicto (**SUPERADA** o
**NO SUPERADA**), y guarda un informe HTML en `k8s/resultados/`. Las gráficas en directo
están en http://localhost:30000/d/lab-jmeter-k8s (admin / admin).

## Escenarios

| Escenario | Usuarios | Duración | Pregunta que responde |
|---|---|---|---|
| `humo`   | 2   | 30 s  | ¿Funciona todo? |
| `normal` | 20  | 3 min | ¿Aguanta el día a día con holgura? |
| `pico`   | 80 de golpe | 2 min | ¿Qué notan los usuarios con 4 veces más tráfico? |
| `estres` | hasta 150 | 5 min | ¿Dónde se rompe? |

## Conexión con 2-processing

El plan que genera `2-processing` se ejecuta tal cual: este laboratorio usa sus mismas
propiedades (`vusers`, `rampup`, `duration`, `host`, `port`).

El plan provisional escrito a mano (`bankapp/plan-bankapp.jmx`, objetivo `bankapp`) es anterior
al inicio de sesión de la bankapp: con la versión con sesiones, sus peticiones reciben 400.

El generador se ejecuta dentro del clúster (`k8s/generar-plan.sh`) y su plan se lanza con el
objetivo `storm`. Si antes se ha ejecutado `k8s/simular-clientes.sh`, aprende de los logs de la
bankapp (qué operaciones se hacen, en qué orden, con qué datos); si no, solo del `.jar`, y
rellena los cuerpos con valores de ejemplo que la app rechaza en parte.

Los logs de 1-input en Git (`src/1-input/java-app-mock/logs/bankapp.jsonl`, 548 peticiones y 107
sesiones con fechas reales) son la entrada recomendada: `k8s/generar-plan.sh repo`. Con ellos el
plan reproduce las pausas reales entre clics (mediana ~40 s).

Pendiente en otras partes (detectado al enlazarlas, 15 oct 2026):
- **2-processing**: los importes se generan al azar entre el mínimo y el máximo vistos en los logs,
  incluidas las peticiones que fallaron (retirada de 99.999 €, ingreso de -10 €). Resultado: la
  mayoría de retiradas y transferencias piden más saldo del que hay (prueba `normal`: 100 % y 82 %
  de errores). Convendría aprender solo de las peticiones con éxito o usar los valores observados.
- **2-processing**: en las transferencias elige origen y destino por separado y a veces coinciden.
- **1-input**: la bankapp en ejecución sigue escribiendo las fechas de sus logs como `1970-01-01`
  (afecta a `k8s/simular-clientes.sh`; el fichero de logs de Git sí tiene fechas reales).
- **1-input**: los logs no guardan los campos de las altas (`name`, `email`, `userId`...).

## Estado

- [x] Laboratorio en Docker Compose y en Kubernetes
- [x] Monitorización: InfluxDB + Grafana (prueba) y Prometheus (CPU y memoria por pod)
- [x] Escenarios humo, normal, pico y estrés
- [x] Bankapp real desplegada y probada
- [x] Criterios de aprobado y resultados guardados por prueba
- [x] Ejecutar el plan generado por 2-processing (prueba de punta a punta)
- [x] Simulador de clientes y generación del plan a partir de los logs de la bankapp
- [ ] JMeter distribuido (varios pods) para cargas muy grandes
