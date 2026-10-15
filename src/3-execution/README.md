# 3-execution: inyección de las pruebas de carga

Esta parte de STORM **recibe el plan de prueba (`.jmx`) que genera el grupo de IA (2-processing),
lo inyecta con JMeter en la aplicación y mide cómo responde**: tiempos de respuesta, errores, CPU
y memoria, en Grafana y en un informe por prueba, con un veredicto de si la aplicación aguanta.

```
1-input                2-processing                3-execution (esta carpeta)
bankapp + logs  ──▶    el modelo de IA genera  ──▶  JMeter inyecta el plan en la bankapp
                       el plan .jmx                 └─▶ InfluxDB / Prometheus ──▶ Grafana + veredicto
```

Todo funciona en el Kubernetes local de Docker Desktop: la bankapp (compilada desde su rama de
Git), JMeter y la monitorización.

## Las carpetas

| Carpeta | Qué es | Cuándo usarla |
|---|---|---|
| [`k8s/`](k8s/README.md) | **Laboratorio en Kubernetes** (el principal): escenarios, criterios de aprobado, resultados guardados por prueba, CPU y memoria por pod | Para las pruebas de verdad y la demo |
| [`lab-jmeter/`](lab-jmeter/README.md) | Laboratorio con Docker Compose: la versión sencilla, con una app de prueba | Para entender el laboratorio o probar algo rápido. `k8s/` reutiliza sus piezas |
| [`bankapp/`](bankapp/README.md) | Compila la bankapp de `1-input` para desplegarla en el laboratorio | Lo usa `k8s/` |
| `docker/` | Vacía (estructura inicial del repositorio) | — |

## Inyectar un plan del grupo de IA

Requisito: Docker Desktop con Kubernetes activado (*Settings → Kubernetes*). En Windows, desde
Git Bash:

```bash
cd src/3-execution
bankapp/construir-imagen.sh              # compila la bankapp (la primera vez o si cambia)
k8s/desplegar.sh                         # levanta el laboratorio en Kubernetes
k8s/cargar-plan.sh plan.jmx              # carga el .jmx entregado por 2-processing
k8s/lanzar-prueba.sh normal storm        # lo inyecta: 20 usuarios durante 3 minutos
```

Al terminar, la prueba muestra una tabla por operación y el veredicto (**SUPERADA** o
**NO SUPERADA**), y guarda un informe HTML en `k8s/resultados/`. Las gráficas en directo
están en http://localhost:30000/d/lab-jmeter-k8s (admin / admin).

El plan no necesita cambios para el laboratorio:
- debe apuntar a la app con `${__P(host,...)}` y `${__P(port,...)}`, como los que genera
  2-processing; el laboratorio le pasa `host=bankapp`;
- la carga se fija con las mismas propiedades que usa 2-processing (`vusers`, `rampup`,
  `duration`), que cambian según el escenario;
- si no envía métricas a InfluxDB, el laboratorio le añade el envío al ejecutarlo
  (`k8s/backend-listener.xml`), así que se ve en Grafana.

## Escenarios

| Escenario | Usuarios | Duración | Pregunta que responde |
|---|---|---|---|
| `humo`   | 2   | 30 s  | ¿Funciona todo? |
| `normal` | 20  | 3 min | ¿Aguanta el día a día con holgura? |
| `pico`   | 80 de golpe | 2 min | ¿Qué notan los usuarios con 4 veces más tráfico? |
| `estres` | hasta 150 | 5 min | ¿Dónde se rompe? |

## Veredicto

Una prueba se suspende por **errores del servidor** (5xx o sin respuesta) o por **lentitud**.
Los **rechazos 4xx** (saldo insuficiente, datos inválidos...) son la app respondiendo bien a un
error del usuario: se muestran aparte como información. Detalle en [`k8s/README.md`](k8s/README.md).

## Observaciones para las otras partes (15 oct 2026)

Detectadas al inyectar el plan del grupo de IA contra la bankapp:
- **2-processing**: los importes se generan al azar entre el mínimo y el máximo vistos en los logs,
  incluidas las peticiones que fallaron (retirada de 99.999 €, ingreso de -10 €). Por eso casi
  todas las retiradas y transferencias se rechazan por saldo insuficiente (rechazos 4xx del ~90 %).
  Convendría aprender solo de las peticiones con éxito o usar los valores observados.
- **2-processing**: en las transferencias elige origen y destino por separado y a veces coinciden.
- **1-input**: la bankapp en ejecución escribe las fechas de sus logs como `1970-01-01`
  (el fichero de logs de Git sí tiene fechas reales).
- **1-input**: los logs no guardan los campos de las altas (`name`, `email`, `userId`...).

## Estado

- [x] Laboratorio en Docker Compose y en Kubernetes
- [x] Monitorización: InfluxDB + Grafana (prueba) y Prometheus (CPU y memoria por pod)
- [x] Escenarios humo, normal, pico y estrés
- [x] Bankapp real desplegada y probada
- [x] Criterios de aprobado y resultados guardados por prueba
- [x] Inyección del plan generado por 2-processing (prueba de punta a punta)
- [ ] JMeter distribuido (varios pods) para cargas muy grandes
