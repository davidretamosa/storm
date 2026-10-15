# 3-execution: ejecución de las pruebas de carga

Esta parte de STORM **ejecuta los planes de prueba (`.jmx`) contra la aplicación y mide cómo
responde**: lanza usuarios simulados con JMeter, recoge tiempos de respuesta, errores, CPU y
memoria, los muestra en Grafana y da un veredicto de si la aplicación aguanta.

```
1-input            2-processing                 3-execution (esta carpeta)
bankapp + logs ──▶ genera el plan .jmx ──▶ JMeter lo ejecuta contra la bankapp
                                            └─▶ InfluxDB / Prometheus ──▶ Grafana + veredicto
```

## Las carpetas

| Carpeta | Qué es | Cuándo usarla |
|---|---|---|
| [`k8s/`](k8s/README.md) | **Laboratorio en Kubernetes** (el principal): escenarios, criterios de aprobado, resultados guardados por prueba, CPU y memoria por pod | Para las pruebas de verdad y la demo |
| [`lab-jmeter/`](lab-jmeter/README.md) | Laboratorio con Docker Compose: la versión sencilla, con una app de prueba | Para entender el laboratorio o probar algo rápido. `k8s/` reutiliza sus piezas |
| [`bankapp/`](bankapp/README.md) | Compila la bankapp de `1-input` y su plan de prueba provisional | Lo usa `k8s/` para probar la aplicación real |
| `docker/` | Vacía (estructura inicial del repositorio) | — |

## Empezar en 3 comandos

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
propiedades (`vusers`, `rampup`, `duration`, `host`, `port`). Mientras no esté integrado, la
bankapp se prueba con un plan provisional escrito a mano (`bankapp/plan-bankapp.jmx`).

Pendiente de acordar con 2-processing:
- dónde deja el `.jmx` generado (propuesta: `bankapp/plan-bankapp.jmx`);
- el envío de métricas a InfluxDB (Backend Listener), que su plantilla aún no incluye.

## Estado

- [x] Laboratorio en Docker Compose y en Kubernetes
- [x] Monitorización: InfluxDB + Grafana (prueba) y Prometheus (CPU y memoria por pod)
- [x] Escenarios humo, normal, pico y estrés
- [x] Bankapp real desplegada y probada
- [x] Criterios de aprobado y resultados guardados por prueba
- [ ] Ejecutar el plan generado por 2-processing (prueba de punta a punta)
- [ ] JMeter distribuido (varios pods) para cargas muy grandes
