# Puesta en marcha: STORM de punta a punta

Guía para que cualquier grupo monte **las tres partes juntas en su propio PC** y lance una
prueba de carga completa: compilar la bankapp, sacar su `.jar` y sus logs, generar el plan
`.jmx` con el modelo de IA y ejecutarlo en el laboratorio, con veredicto y gráficas en Grafana.

```
 1-input                       2-processing                     3-execution
 ───────                       ────────────                     ───────────
 bankapp (código) ──▶ imagen ──▶ .jar ──┐
                                        ├──▶ main.py ──▶ plan.jmx ──▶ JMeter ──▶ bankapp
 logs/bankapp.jsonl ────────────────────┘   (modelo de IA)              │
                                                                         └──▶ InfluxDB / Prometheus
                                                                              ──▶ Grafana + veredicto
```

Todo se ejecuta en local, en el Kubernetes de Docker Desktop. Tiempo aproximado la primera vez:
20-30 minutos (casi todo son descargas). Las siguientes veces, 5 minutos.

---

## 0. Requisitos (una sola vez)

| Qué | Para qué | Cómo comprobarlo |
|---|---|---|
| **Docker Desktop** con **Kubernetes activado** (*Settings → Kubernetes → Enable Kubernetes*) | Compilar la bankapp y montar el laboratorio | `kubectl get nodes` muestra `docker-desktop   Ready` |
| **Git for Windows** (incluye **Git Bash**) | Clonar el repositorio y lanzar los scripts `.sh` | `git --version` |
| **Python 3.11 o superior** de [python.org](https://www.python.org/downloads/) (incluye el lanzador `py`) | Generar el plan con el modelo de IA | `py -3 --version` |

No hace falta instalar Java, Maven ni JMeter: todo eso va dentro de Docker.

> **Todos los comandos de esta guía se escriben en Git Bash**, salvo que se diga otra cosa.
> Docker Desktop tiene que estar arrancado (icono de la ballena en verde).

## 1. Clonar el repositorio

```bash
git clone -b develop https://github.com/davidretamosa/storm.git
cd storm
```

A partir de aquí, todas las rutas son relativas a esta carpeta `storm`.

## 2. Compilar la bankapp (1-input)

```bash
src/3-execution/bankapp/construir-imagen.sh
```

Compila el código de `src/1-input/java-app-mock` (rama `origin/develop`) dentro de Docker y crea
la imagen `bankapp`. La primera vez tarda unos minutos porque Maven descarga las dependencias.
Para compilar otra rama: `src/3-execution/bankapp/construir-imagen.sh origin/feature/java-app`.

Al terminar debe salir `Imagen bankapp lista`.

## 3. Sacar el `.jar` de la bankapp

El generador de IA lee el `.jar` para saber qué endpoints y qué cuerpos JSON existen. Lo sacamos
de la imagen que acabamos de construir:

```bash
mkdir -p entrada
docker create --name bankapp-jar bankapp:latest
MSYS_NO_PATHCONV=1 docker cp bankapp-jar:/app/app.jar entrada/bankapp.jar
docker rm bankapp-jar
```

Queda en `entrada/bankapp.jar` (unos 55 MB). La carpeta `entrada/` es solo de trabajo y Git
la ignora.

## 4. Elegir los logs

El generador aprende de los logs **cómo usa la gente la app** (qué hace después de qué, cuánto
tarda entre peticiones, qué importes...). Hay dos opciones:

**A. Los logs de referencia del repositorio (recomendado para empezar).** Ya están en
`src/1-input/java-app-mock/logs/bankapp.jsonl`: 548 peticiones de 107 sesiones escritas por la
bankapp real. No hay que hacer nada.

**B. Logs propios de la bankapp en marcha.** La bankapp escribe cada petición en
`/app/logs/bankapp.jsonl`. Si la habéis usado (con Postman, curl, un front...) después del
paso 5, podéis copiarlos así:

```bash
MSYS_NO_PATHCONV=1 kubectl -n lab-jmeter exec deploy/bankapp -- cat /app/logs/bankapp.jsonl > entrada/bankapp.jsonl
```

Ojo: el fichero se vacía cada vez que se reinicia la bankapp, y también incluye las peticiones
de las pruebas de carga que hayáis lanzado.

## 5. Levantar el laboratorio (3-execution)

```bash
src/3-execution/k8s/desplegar.sh
```

Levanta en Kubernetes la bankapp, InfluxDB, Prometheus y Grafana. La primera vez también
construye la imagen de JMeter (1-2 minutos). Termina con:

```
Laboratorio listo:
  Bankapp:    http://localhost:30081/api/accounts
  Grafana:    http://localhost:30000/d/lab-jmeter-k8s  (admin / admin)
  ...
```

Antes de seguir, comprobad que todos los pods están `1/1 Running` (la bankapp tarda unos
20 segundos en arrancar):

```bash
kubectl -n lab-jmeter get pods
```

## 6. Generar el plan `.jmx` (2-processing)

La primera vez, preparad el entorno de Python:

```bash
cd src/2-processing
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cd ../..
```

> Usad `py -3`, no `python`: el `python` de Git Bash (MSYS2) crea el entorno en `.venv/bin` y
> los comandos de esta guía no lo encontrarían.

Generar el plan con el `.jar` y los logs:

```bash
cd src/2-processing
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe main.py \
  --jar ../../entrada/bankapp.jar \
  --logs ../1-input/java-app-mock/logs/bankapp.jsonl \
  --session \
  --output ../../entrada/plan.jmx
cd ../..
```

- `--session` es obligatorio con la bankapp: cada usuario virtual inicia sesión
  (`POST /api/sessions`) y manda la cabecera `X-Session-Id` en todas las peticiones.
- Si en el paso 4 elegisteis la opción B, cambiad `--logs` por `../../entrada/bankapp.jsonl`.
- No hace falta `--host` ni `--port`: el laboratorio le dice al plan dónde está la bankapp.

Debe terminar con `Plan generado: ../../entrada/plan.jmx`. Las demás opciones del generador
están en [`src/2-processing/README.md`](../2-processing/README.md).

## 7. Cargar el plan y lanzar la prueba

```bash
src/3-execution/k8s/cargar-plan.sh entrada/plan.jmx
src/3-execution/k8s/lanzar-prueba.sh humo storm
```

`humo` es una prueba corta para comprobar que todo funciona: con solo 2 usuarios puede acabar
en pocos segundos y con 20-30 peticiones, y es normal. Si sale bien, lanzad una de verdad:

| Escenario | Usuarios | Duración | Pregunta que responde |
|---|---|---|---|
| `humo`   | 2   | 30 s  | ¿Funciona todo? |
| `normal` | 20  | 3 min | ¿Aguanta el día a día con holgura? |
| `pico`   | 80 de golpe | 2 min | ¿Qué notan los usuarios con 4 veces más tráfico? |
| `estres` | hasta 150 | 5 min | ¿Dónde empieza a sufrir? |
| `rotura` | hasta 400, sin pausas | 10 min | ¿Dónde está el límite de la app? |

```bash
src/3-execution/k8s/lanzar-prueba.sh normal storm
```

Los planes del generador repiten las **pausas reales** de los usuarios entre peticiones, así
que generan poco tráfico: con 20 usuarios, `normal` da alrededor de 1 petición por segundo.
Para apretar de verdad a la app, usad `rotura`, que quita las pausas.

El plan se carga una vez y se puede lanzar con todos los escenarios que queráis. Solo hay que
volver a cargarlo (`cargar-plan.sh`) cuando generéis uno nuevo.

## 8. Ver los resultados

**En la terminal**, al terminar cada prueba, sale una tabla por operación y el veredicto:

```
=== RESULTADO DE LA PRUEBA ===
Operación                               Peticiones Errores servidor  Rechazos 4xx      Media
Iniciar sesión                                  62            0.00%         0.00%       10 ms
POST /api/accounts/{id}/withdraw                 10            0.00%       100.00%       11 ms
GET /api/accounts/{id}                           82            0.00%         0.00%        8 ms
...
TOTAL                                           197            0.00%         8.63%

[OK]    Errores del servidor: ninguna operación pasa del 0.1 % (la peor: 0.00 %)
[OK]    Tiempo: el 95 % de las peticiones responde en 22 ms o menos (máximo 500 ms)

VEREDICTO: PRUEBA SUPERADA
Resultados guardados en k8s/resultados/normal-storm-20261029-123248 (informe: informe/index.html)
```

- **Errores servidor** (5xx o sin respuesta): la app ha fallado. Cuentan para el veredicto.
- **Rechazos 4xx**: la app ha rechazado bien una petición incorrecta (por ejemplo, saldo
  insuficiente). Son informativos y no suspenden la prueba.
- La prueba se **suspende** si alguna operación pasa del 0,1 % de errores del servidor o si el
  95 % de las peticiones no responde en menos de 500 ms.

**En el navegador**:

| Qué | Dónde |
|---|---|
| Gráficas en directo (peticiones/s, tiempos, errores, CPU y memoria) | http://localhost:30000/d/lab-jmeter-k8s (admin / admin) |
| Informe HTML completo de cada prueba | `src/3-execution/k8s/resultados/<prueba>/informe/index.html` |

Las gráficas muestran los últimos 15 minutos; si la prueba fue antes, cambiad el rango de tiempo
arriba a la derecha.

## 9. Apagar

```bash
src/3-execution/k8s/quitar.sh
```

Borra el laboratorio del clúster. Para volver a empezar otro día basta con repetir los pasos 5
y 7; los pasos 1-4 y 6 solo se repiten si cambia el código de la bankapp o queréis otro plan.

---

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `kubectl: command not found` o `connection refused` | Kubernetes no está activado o Docker Desktop no está arrancado. Activadlo en *Settings → Kubernetes* y esperad a que el icono esté en verde. |
| `.venv/Scripts/python.exe: No such file or directory` | El entorno se creó con el `python` de Git Bash. Borrad `src/2-processing/.venv` y repetid el paso 6 con `py -3`. |
| `UnicodeEncodeError` al generar el plan | Falta `PYTHONIOENCODING=utf-8` delante del comando. |
| La prueba da muchos errores 500 o "sin respuesta" justo al empezar | La bankapp aún no había arrancado. Comprobad que está `1/1` con `kubectl -n lab-jmeter get pods` y repetid. |
| Al encender Docker, la bankapp ya tiene carga o Grafana muestra una prueba que no habéis lanzado | Una prueba que quedó a medias (por ejemplo, al apagar el PC) vuelve a arrancar sola. Paradla con `kubectl -n lab-jmeter delete job jmeter` y reiniciad la bankapp con `kubectl -n lab-jmeter rollout restart deploy/bankapp`. |
| Grafana sale vacío | Revisad el rango de tiempo (por defecto, últimos 15 minutos). |
| Muchos "Rechazos 4xx" en retiradas y transferencias | Es normal con el modelo actual: el generador elige importes al azar y muchos superan el saldo. La app responde bien; no es un fallo. |

Más detalle de cada parte: [`k8s/README.md`](k8s/README.md) (laboratorio, escenarios,
criterios), [`bankapp/README.md`](bankapp/README.md) y
[`src/2-processing/README.md`](../2-processing/README.md) (generador).
