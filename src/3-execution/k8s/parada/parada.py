"""Servicio de parada (el botón rojo) + autoparada por métricas.

Recibe POST /parar y detiene la prueba de JMeter que esté en marcha en el namespace.
La parada sube de nivel hasta que la prueba termina:

  0. abortada.txt  deja la nota que lee ejecutar-y-evaluar.sh (veredicto ABORTADA)
  1. shutdown.sh   parada ordenada: las muestras en curso acaban y se genera el informe
  2. stoptest.sh   parada inmediata, si la ordenada no termina a tiempo
  3. borrar el Job último recurso: puede dejar sin generar el informe HTML

AUTOPARADA: un vigilante (hilo en segundo plano) mide la prueba cada pocos segundos y, si
algún criterio activo se incumple de forma sostenida, dispara esa misma escalera con un
motivo que empieza por "auto" (así se distingue en /estado y en el veredicto).
Viene DESACTIVADA por defecto: sin AUTOPARADA=1 el servicio se comporta como antes.

De dónde salen las medidas:
  InfluxDB (base jmeter)  throughput, latencias (media, p95, p99) y % de peticiones fallidas:
                          lo mismo que enseña Grafana (lo escribe el Backend Listener de JMeter)
  resultados.jtl          % de errores del servidor (5xx o sin respuesta), leído del pod de JMeter.
                          Influx no guarda el código HTTP, y sin él no se pueden separar los
                          5xx de los rechazos 4xx, que no cuentan para el veredicto
  API de Kubernetes       reinicios y estado de los pods de la app que se prueba
  Prometheus              solo para criterios propios (CRITERIOS_EXTRA)

Criterios disponibles (se elige cuáles y con qué umbral):
  errores_servidor   % de errores del servidor: 5xx o sin respuesta, como el veredicto  [5 %]
  errores_5xx        % solo de respuestas 5xx                                          [5 %]
  errores_no_http    % de timeouts y errores de conexión (sin código HTTP)             [5 %]
  errores_total      % de peticiones fallidas según JMeter; puede incluir los 4xx      [20 %]
  latencia_p95       latencia percentil 95, en ms                                      [1000]
  latencia_p99       latencia percentil 99, en ms                                      [3000]
  latencia_media     latencia media, en ms                                             [500]
  caida_throughput   rps actuales como % del pico alcanzado; para si baja de ese %     [50 %]
  duracion_max       segundos máximos de prueba                                        [3600]
  reinicios_pods     reinicios de contenedor de la app probada durante la prueba       [0]
  pods_no_listos     pods de la app probada que no están Ready                         [0]
  (los dos últimos solo existen si se define APP_SELECTOR)
  + los que definas tú con CRITERIOS_EXTRA (consulta PromQL o InfluxQL).

Endpoints:
  POST /parar       inicia la parada y responde enseguida (202); la escalera sigue en segundo plano.
                    Motivo opcional: ?motivo=...  o cuerpo JSON {"motivo": "..."}
  GET  /estado      en qué punto va la parada y si hay una prueba en marcha (incluye autoparada)
  GET  /autoparada  configuración actual, últimos valores medidos y criterios disponibles
  POST /autoparada  cambia la configuración en caliente (por ejemplo, justo antes de lanzar):
                    {"activa": true, "gracia": 60, "sostenido": 30,
                     "criterios": {"errores_servidor": 5, "latencia_p95": 800}}
                    "criterios" REEMPLAZA los activos; un umbral null usa el de por defecto.
  GET  /healthz     sonda de Kubernetes

Variables de entorno (todas opcionales):
  NS               namespace de la prueba (en Kubernetes se rellena solo)       [lab-jmeter]
  ESPERA_SHUTDOWN  segundos que se espera tras shutdown.sh antes de subir de nivel [45]
  ESPERA_STOPTEST  segundos que se espera tras stoptest.sh antes de borrar el Job  [20]
  TOKEN            si se define, POST /parar y POST /autoparada exigen "Authorization: Bearer <TOKEN>"
  CORS_ORIGEN      origen(es) de Grafana, separados por comas, si el botón llama desde el navegador

  AUTOPARADA              1 para activar la autoparada                           [0]
  AUTOPARADA_CRITERIOS    "nombre=umbral,nombre=umbral" (umbral opcional)        [errores_servidor,latencia_p95]
  AUTOPARADA_GRACIA       segundos iniciales sin evaluar (arranque / rampa)      [60]
  AUTOPARADA_SOSTENIDO    segundos seguidos incumpliendo antes de parar          [30]
  AUTOPARADA_INTERVALO    cada cuántos segundos se mide                          [5]
  AUTOPARADA_VENTANA      segundos hacia atrás que abarca cada medida            [30]
  MIN_RPS                 por debajo de este tráfico los % de Influx no se evalúan [1]
  MIN_MUESTRAS            mínimo de peticiones en la ventana para evaluar los % del .jtl [30]
  INFLUX_URL / INFLUX_DB  InfluxDB de las métricas de JMeter                     [http://influxdb:8086 / jmeter]
  JTL                     ruta del .jtl dentro del pod de JMeter                 [$RESULTADOS/resultados.jtl]
  JTL_LINEAS              cuántas líneas finales del .jtl se leen en cada medida [10000]
  APP_NS / APP_SELECTOR   dónde están los pods de la app probada (p. ej. app=objetivo)
  PROM_URL                Prometheus, solo para criterios propios                [http://prometheus:9090]
  CRITERIOS_EXTRA         JSON: {"cpu_app": {"query": "...", "fuente": "prometheus", "op": ">",
                                              "umbral": 90, "desc": "CPU de la app", "unidad": "%"}}
                          ("fuente": "prometheus" por defecto, o "influx"; la consulta debe
                          devolver un solo valor)

En local (con tu kubeconfig):  pip install kubernetes  y  python parada.py
"""
import copy
import csv
import hmac
import json
import math
import os
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

NS = os.environ.get("NS", "lab-jmeter")
ETIQUETA_POD = os.environ.get("ETIQUETA_POD", "app=jmeter")    # el pod master (el del Job)
CONTENEDOR = os.environ.get("CONTENEDOR", "jmeter")
JOB = os.environ.get("JOB", "jmeter")
WORKERS = os.environ.get("WORKERS", "jmeter-worker")            # Deployment de los workers
JMETER_BIN = os.environ.get("JMETER_BIN", "/opt/jmeter/bin")
ESPERA_SHUTDOWN = int(os.environ.get("ESPERA_SHUTDOWN", "45"))
ESPERA_STOPTEST = int(os.environ.get("ESPERA_STOPTEST", "20"))
PUERTO = int(os.environ.get("PUERTO", "8080"))
TOKEN = os.environ.get("TOKEN", "")
CORS_ORIGENES = {
    origen.strip() for origen in os.environ.get("CORS_ORIGEN", "").split(",") if origen.strip()
}
MOTIVO_DEFECTO = "botón rojo"

# --- autoparada
INFLUX_URL = os.environ.get("INFLUX_URL", "http://influxdb:8086")
INFLUX_DB = os.environ.get("INFLUX_DB", "jmeter")
PROM_URL = os.environ.get("PROM_URL", "http://prometheus:9090")
JTL = os.environ.get("JTL", "$RESULTADOS/resultados.jtl")      # dentro del pod de JMeter
JTL_LINEAS = int(os.environ.get("JTL_LINEAS", "10000"))
VENTANA = int(os.environ.get("AUTOPARADA_VENTANA", "30"))
INTERVALO = float(os.environ.get("AUTOPARADA_INTERVALO", "5"))
MIN_RPS = float(os.environ.get("MIN_RPS", "1"))
MIN_MUESTRAS = int(os.environ.get("MIN_MUESTRAS", "30"))
APP_NS = os.environ.get("APP_NS", NS)
APP_SELECTOR = os.environ.get("APP_SELECTOR", "")               # p. ej. app=objetivo

try:
    config.load_incluster_config()      # dentro del clúster
except config.ConfigException:
    config.load_kube_config()           # en local
v1 = client.CoreV1Api()
# stream() sustituye temporalmente el método de petición del cliente que se le pasa: se usa
# uno aparte para que no afecte a las consultas que hacen a la vez otros hilos
v1_exec = client.CoreV1Api(client.ApiClient())
batch = client.BatchV1Api()
apps = client.AppsV1Api()

lock = threading.Lock()
parada = {"estado": "inactiva"}         # inactiva | parando | terminada | fallida


def ahora():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(**campos):
    print(json.dumps({"ts": ahora(), **campos}, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- Kubernetes

def pod_en_marcha():
    """Nombre del pod master de JMeter si está corriendo; None si no hay ninguno."""
    for p in v1.list_namespaced_pod(NS, label_selector=ETIQUETA_POD).items:
        if p.status.phase == "Running" and p.metadata.deletion_timestamp is None:
            return p.metadata.name
    return None


def job_activo():
    """True si el Job existe y tiene pods activos (por ejemplo, aún arrancando)."""
    try:
        return (batch.read_namespaced_job(JOB, NS).status.active or 0) > 0
    except ApiException as e:
        if e.status == 404:
            return False
        raise


def termino(pod):
    """True cuando el pod ya no está en marcha (terminó o ya no existe)."""
    try:
        return v1.read_namespaced_pod(pod, NS).status.phase in ("Succeeded", "Failed")
    except ApiException as e:
        if e.status == 404:
            return True
        raise


def esperar_fin(pod, segundos):
    limite = time.time() + segundos
    while time.time() < limite:
        if termino(pod):
            return True
        time.sleep(2)
    return termino(pod)


def intentar(pod, comando):
    """Ejecuta un comando dentro del pod. Si falla (p. ej. el pod acaba de terminar) lo anota
    y sigue: lo que importa es si la prueba termina, y eso lo comprueba esperar_fin()."""
    try:
        return stream(v1_exec.connect_get_namespaced_pod_exec, pod, NS, container=CONTENEDOR,
                      command=comando, stderr=True, stdin=False, stdout=True, tty=False)
    except Exception as e:                      # noqa: BLE001
        log(evento="exec_fallo", comando=comando[0], error=repr(e))


def borrar_job():
    try:
        batch.delete_namespaced_job(JOB, NS, propagation_policy="Background")
    except ApiException as e:
        if e.status != 404:
            raise


def apagar_workers():
    """lanzar-prueba.sh los apaga al terminar, pero si el Job se borró a la fuerza o la prueba
    se lanzó desde otro sitio podrían quedarse encendidos."""
    try:
        apps.patch_namespaced_deployment_scale(WORKERS, NS, {"spec": {"replicas": 0}})
    except ApiException as e:
        if e.status != 404:
            log(evento="workers_fallo", error=repr(e))


# ---------------------------------------------------------------- la parada

def limpiar(motivo):
    """El motivo acaba dentro de un sed (ejecutar-y-evaluar.sh): se quitan /, & y \\ y demás
    símbolos que lo romperían, y se limita su longitud."""
    motivo = re.sub(r"[^\w .,:;()-]", "", motivo or "").strip()[:60]
    return motivo or MOTIVO_DEFECTO


def nivel(n, texto):
    with lock:
        parada.update(nivel=n, detalle=texto)
    log(evento="nivel", nivel=n, detalle=texto)


def escalera(motivo):
    try:
        pod = pod_en_marcha()
        if pod:
            with lock:
                parada["pod"] = pod
            nivel(0, "escribiendo abortada.txt")
            intentar(pod, ["sh", "-c", 'printf "%s\\n" "$0" > "$RESULTADOS/abortada.txt"', motivo])
            nivel(1, "shutdown: parada ordenada")
            intentar(pod, [f"{JMETER_BIN}/shutdown.sh"])
            if not esperar_fin(pod, ESPERA_SHUTDOWN):
                nivel(2, "stoptest: parada inmediata")
                intentar(pod, [f"{JMETER_BIN}/stoptest.sh"])
                if not esperar_fin(pod, ESPERA_STOPTEST):
                    nivel(3, "borrando el Job")
                    borrar_job()
        else:                                   # el pod aún no ha arrancado: no hay nada que parar
            nivel(3, "el pod no está en marcha: borrando el Job")
            borrar_job()
        apagar_workers()
        final("terminada", "la prueba ha terminado")
    except Exception as e:                      # noqa: BLE001
        log(evento="error", error=repr(e))
        final("fallida", repr(e))


def final(estado, detalle):
    with lock:
        parada.update(estado=estado, detalle=detalle, hasta=ahora())
    log(evento="fin", estado=estado, detalle=detalle)


def iniciar(motivo):
    """Arranca la parada. Devuelve (código HTTP, respuesta)."""
    en_marcha = bool(pod_en_marcha() or job_activo())
    with lock:
        if parada["estado"] == "parando":       # idempotente: ya hay una parada en curso
            return 202, dict(parada)
        if not en_marcha:
            return 409, {"estado": "sin_prueba", "detalle": "no hay ninguna prueba en marcha"}
        parada.clear()
        parada.update(estado="parando", nivel=0, motivo=motivo, desde=ahora(), detalle="iniciando")
        respuesta = dict(parada)
    log(evento="parar", motivo=motivo)
    threading.Thread(target=escalera, args=(motivo,), daemon=True).start()
    return 202, respuesta


def estado():
    with lock:
        info = dict(parada)
    prueba_en_marcha = bool(pod_en_marcha() or job_activo())
    info["prueba_en_marcha"] = prueba_en_marcha
    if prueba_en_marcha and info["estado"] != "parando":
        info = {
            "estado": "activa",
            "detalle": "hay una prueba de JMeter en marcha",
            "prueba_en_marcha": True,
        }
    info["autoparada"] = vista_auto()
    return info


# ---------------------------------------------------------------- autoparada: medidas

def pedir_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.load(r)


def consultar_prometheus(consulta_promql):
    """Valor (float) de una consulta PromQL instantánea; None si no hay datos (o es NaN)."""
    url = f"{PROM_URL}/api/v1/query?{urlencode({'query': consulta_promql})}"
    resultado = pedir_json(url)["data"]["result"]
    if not resultado:
        return None
    valor = float(resultado[0]["value"][1])
    return None if math.isnan(valor) else valor


def consultar_influx(consulta_influxql):
    """Filas [[tiempo_ms, valor, ...], ...] de una consulta InfluxQL; [] si no hay datos."""
    url = f"{INFLUX_URL}/query?{urlencode({'db': INFLUX_DB, 'q': consulta_influxql, 'epoch': 'ms'})}"
    resultado = pedir_json(url)["results"][0]
    if "error" in resultado:
        raise RuntimeError(resultado["error"])
    series = resultado.get("series") or []
    return series[0]["values"] if series else []


def influx_escalar(consulta_influxql):
    filas = consultar_influx(consulta_influxql)
    if not filas or filas[0][1] is None:
        return None
    return float(filas[0][1])


def donde(statut="all"):
    """Filtro del Backend Listener de JMeter: la fila agregada de todas las operaciones
    (transaction = all), con o sin errores (statut = all | ok | ko), en la ventana."""
    return ('"transaction" = \'all\' AND "statut" = \'' + statut
            + '\' AND time > now() - ' + str(VENTANA) + "s")


def influx_agregado(funcion, campo, statut="all"):
    return influx_escalar(f'SELECT {funcion}("{campo}") FROM "jmeter" WHERE {donde(statut)}')


def influx_medida(funcion, campo):
    return lambda ctx: influx_agregado(funcion, campo)


def medir_rps(ctx):
    """Peticiones por segundo: el listener escribe un 'count' por intervalo; se suman todos
    menos el primero y se dividen por el tiempo que separa el primero del último."""
    filas = consultar_influx('SELECT "count" FROM "jmeter" WHERE ' + donde())
    if len(filas) < 2:
        return None
    segundos = (filas[-1][0] - filas[0][0]) / 1000
    if segundos <= 0:
        return None
    return sum(f[1] or 0 for f in filas[1:]) / segundos


def medir_errores_total(ctx):
    total = influx_agregado("sum", "count")
    if not total:
        return None
    errores = influx_agregado("sum", "countError", "ko") or 0.0
    return 100.0 * errores / total


# Columnas por defecto del .jtl de JMeter, por si el fichero no trae cabecera
COLUMNAS_JTL = ["timeStamp", "elapsed", "label", "responseCode", "responseMessage", "threadName",
                "dataType", "success", "failureMessage", "bytes", "sentBytes", "grpThreads",
                "allThreads", "URL", "Latency", "IdleTime", "Connect"]


def leer_jtl(pod):
    """Códigos de respuesta de las peticiones de los últimos VENTANA segundos del .jtl que
    escribe JMeter en el pod. Si falla (no existe, no se puede leer) lanza una excepción."""
    orden = f'f="{JTL}"; head -n 1 "$f"; tail -n {JTL_LINEAS} "$f"'
    salida = stream(v1_exec.connect_get_namespaced_pod_exec, pod, NS, container=CONTENEDOR,
                    command=["sh", "-c", orden], stderr=False, stdin=False, stdout=True, tty=False)
    lineas = (salida or "").splitlines()
    if not lineas:
        raise RuntimeError(f"no se pudo leer {JTL} en el pod {pod}")
    sep = "\t" if "\t" in lineas[0] else ","
    cabecera = next(csv.reader([lineas[0]], delimiter=sep))
    if "timeStamp" in cabecera:
        columnas, filas = cabecera, lineas[1:]
    else:                                       # sin cabecera: columnas por defecto
        columnas, filas = COLUMNAS_JTL, lineas
    if "timeStamp" not in columnas or "responseCode" not in columnas:
        raise RuntimeError(f"el .jtl no tiene timeStamp y responseCode: {columnas}")
    i_ts, i_cod = columnas.index("timeStamp"), columnas.index("responseCode")
    desde = (time.time() - VENTANA) * 1000
    codigos = []
    for fila in csv.reader(filas, delimiter=sep):
        try:
            if int(fila[i_ts]) >= desde:
                codigos.append(fila[i_cod])
        except (ValueError, IndexError):
            continue                            # cabecera repetida, última línea a medias...
    return codigos


def pct_jtl(tipo):
    """% de peticiones de la ventana que son: '5xx', 'no_http' (sin código HTTP: timeout,
    conexión rechazada...) o 'servidor' (las dos cosas, la definición del veredicto)."""
    def es_http(codigo):
        return re.fullmatch(r"\d{3}", codigo) is not None

    def medir(ctx):
        if "jtl" not in ctx:                    # una sola lectura por ciclo, compartida
            ctx["jtl"] = medir_seguro("jtl", leer_jtl, ctx["pod"])
        codigos = ctx["jtl"]
        if codigos is None or len(codigos) < MIN_MUESTRAS:
            return None
        if tipo == "5xx":
            malos = sum(1 for c in codigos if c.startswith("5"))
        elif tipo == "no_http":
            malos = sum(1 for c in codigos if not es_http(c))
        else:
            malos = sum(1 for c in codigos if c.startswith("5") or not es_http(c))
        return 100.0 * malos / len(codigos)
    return medir


def pods_app():
    """Pods de la app que se está probando; None si no se ha configurado APP_SELECTOR."""
    if not APP_SELECTOR:
        return None
    return v1.list_namespaced_pod(APP_NS, label_selector=APP_SELECTOR).items


def total_reinicios():
    pods = pods_app()
    if pods is None:
        return None
    return sum(cs.restart_count for p in pods for cs in (p.status.container_statuses or []))


def medir_reinicios(ctx):
    actual = total_reinicios()
    if actual is None or ctx.get("reinicios_base") is None:
        return None
    return max(0, actual - ctx["reinicios_base"])    # solo los ocurridos durante la prueba


def medir_pods_no_listos(ctx):
    pods = pods_app()
    if pods is None:
        return None

    def listo(p):
        return any(c.type == "Ready" and c.status == "True" for c in (p.status.conditions or []))

    return sum(1 for p in pods if not listo(p))


def medir_caida(ctx):
    """rps actuales como % del pico de la prueba. Ojo: una prueba con rampa de bajada
    pensada a propósito también lo disparará; en ese caso no actives este criterio."""
    if ctx.get("rps") is None or ctx["pico_rps"] < MIN_RPS:
        return None
    return 100.0 * ctx["rps"] / ctx["pico_rps"]


def medir_duracion(ctx):
    return time.time() - ctx["inicio"]


def criterio(desc, unidad, op, umbral, medir, trafico=False):
    """op: '>' (para si el valor supera el umbral) o '<' (para si cae por debajo).
    trafico=True: solo se evalúa si hay al menos MIN_RPS (un % con 2 peticiones no significa nada)."""
    return {"desc": desc, "unidad": unidad, "op": op, "umbral": float(umbral),
            "medir": medir, "trafico": trafico}


CATALOGO = {
    "errores_servidor": criterio("% de errores del servidor: 5xx o sin respuesta (como el veredicto)",
                                 "%", ">", 5, pct_jtl("servidor")),
    "errores_5xx": criterio("% de respuestas 5xx", "%", ">", 5, pct_jtl("5xx")),
    "errores_no_http": criterio("% de timeouts y errores de conexión (sin código HTTP)",
                                "%", ">", 5, pct_jtl("no_http")),
    "errores_total": criterio("% de peticiones fallidas según JMeter (puede incluir los 4xx)",
                              "%", ">", 20, medir_errores_total, True),
    "latencia_p95": criterio("latencia p95", "ms", ">", 1000, influx_medida("mean", "pct95.0"), True),
    "latencia_p99": criterio("latencia p99", "ms", ">", 3000, influx_medida("mean", "pct99.0"), True),
    "latencia_media": criterio("latencia media", "ms", ">", 500, influx_medida("mean", "avg"), True),
    "caida_throughput": criterio("rps actuales como % del pico", "%", "<", 50, medir_caida),
    "duracion_max": criterio("duración máxima de la prueba", "s", ">", 3600, medir_duracion),
}
if APP_SELECTOR:
    CATALOGO["reinicios_pods"] = criterio("reinicios de la app probada", "", ">", 0, medir_reinicios)
    CATALOGO["pods_no_listos"] = criterio("pods de la app probada no Ready", "", ">", 0, medir_pods_no_listos)


def medida_extra(c):
    consultar = influx_escalar if c.get("fuente") == "influx" else consultar_prometheus
    return lambda ctx, q=c["query"]: consultar(q)


try:
    for _nombre, _c in json.loads(os.environ.get("CRITERIOS_EXTRA") or "{}").items():
        CATALOGO[_nombre] = criterio(
            _c.get("desc", _nombre), _c.get("unidad", ""), _c.get("op", ">"),
            _c.get("umbral", 0), medida_extra(_c), bool(_c.get("trafico", False)))
except (ValueError, KeyError, AttributeError, TypeError) as _e:
    log(evento="criterios_extra_invalidos", error=repr(_e))


# ---------------------------------------------------------------- autoparada: configuración

def parsear_criterios(texto):
    """'errores_5xx=5,latencia_p95=800,duracion_max' -> {'errores_5xx': 5.0, ...}
    Sin '=umbral' se usa el umbral por defecto del criterio."""
    resultado = {}
    for trozo in (texto or "").split(","):
        if not trozo.strip():
            continue
        nombre, _, valor = trozo.partition("=")
        nombre = nombre.strip()
        if nombre not in CATALOGO:
            log(evento="criterio_desconocido", nombre=nombre, disponibles=sorted(CATALOGO))
            continue
        try:
            resultado[nombre] = float(valor) if valor.strip() else CATALOGO[nombre]["umbral"]
        except ValueError:
            log(evento="umbral_invalido", nombre=nombre, valor=valor)
    return resultado


auto_cfg = {
    "activa": os.environ.get("AUTOPARADA", "0").strip().lower() in ("1", "true", "si", "sí", "on"),
    "gracia": int(os.environ.get("AUTOPARADA_GRACIA", "60")),
    "sostenido": int(os.environ.get("AUTOPARADA_SOSTENIDO", "30")),
    "criterios": parsear_criterios(
        os.environ.get("AUTOPARADA_CRITERIOS", "errores_servidor,latencia_p95")),
}
auto_est = {"valores": {}, "evaluado": None, "disparo": None}


def vista_auto():
    with lock:
        return copy.deepcopy({"config": auto_cfg, **auto_est})


def catalogo_publico():
    return {n: {"desc": c["desc"], "condicion": f'para si {c["op"]} umbral', "unidad": c["unidad"],
                "umbral_defecto": c["umbral"]} for n, c in CATALOGO.items()}


def configurar_auto(datos):
    """Cambia la configuración en caliente. Devuelve (código HTTP, respuesta)."""
    if not isinstance(datos, dict):
        return 400, {"error": "el cuerpo debe ser un objeto JSON"}
    nuevo = {}
    try:
        if "activa" in datos:
            nuevo["activa"] = bool(datos["activa"])
        for campo in ("gracia", "sostenido"):
            if campo in datos:
                nuevo[campo] = max(0, int(datos[campo]))
        if "criterios" in datos:
            if not isinstance(datos["criterios"], dict):
                raise ValueError("criterios debe ser un objeto {nombre: umbral}")
            criterios = {}
            for nombre, umbral in datos["criterios"].items():
                if nombre not in CATALOGO:
                    raise ValueError(f"criterio desconocido: {nombre}")
                criterios[nombre] = CATALOGO[nombre]["umbral"] if umbral is None else float(umbral)
                if criterios[nombre] < 0:
                    raise ValueError(f"umbral negativo en {nombre}")
            nuevo["criterios"] = criterios
    except (ValueError, TypeError) as e:
        return 400, {"error": str(e), "criterios_disponibles": sorted(CATALOGO)}
    with lock:
        auto_cfg.update(nuevo)
    log(evento="autoparada_config", **nuevo)
    return 200, {**vista_auto(), "criterios_disponibles": catalogo_publico()}


# ---------------------------------------------------------------- autoparada: vigilante

_fallando = set()


def medir_seguro(clave, funcion, *args):
    """Si la medida falla (Prometheus caído, etc.) devuelve None: un fallo de monitorización
    NUNCA para la prueba. Solo se anota el fallo la primera vez, para no llenar el log."""
    try:
        valor = funcion(*args)
        _fallando.discard(clave)
        return valor
    except Exception as e:                      # noqa: BLE001
        if clave not in _fallando:
            _fallando.add(clave)
            log(evento="medida_fallo", criterio=clave, error=repr(e))
        return None


def incumple(valor, op, umbral):
    return valor is not None and (valor > umbral if op == ">" else valor < umbral)


def disparar(nombre, valor, umbral):
    c = CATALOGO[nombre]
    # limpiar() quita < > % =, así que el motivo va con palabras
    motivo = limpiar(f"auto {nombre} {valor:.1f} {'mayor' if c['op'] == '>' else 'menor'} que {umbral:g}")
    codigo, _ = iniciar(motivo)
    with lock:
        auto_est["disparo"] = {"criterio": nombre, "valor": round(valor, 2), "umbral": umbral,
                               "cuando": ahora(), "http": codigo}
    log(evento="autoparada", criterio=nombre, valor=valor, umbral=umbral, codigo=codigo)


def vigilante():
    ctx = None              # estado de la prueba en curso; None si no hay ninguna
    seguidos = {}           # criterio -> segundos seguidos incumpliéndose
    while True:
        time.sleep(INTERVALO)
        try:
            pod = pod_en_marcha()
            if not pod:
                ctx = None
                seguidos.clear()
                with lock:
                    auto_est.update(valores={}, evaluado=None)
                continue
            if ctx is None:                     # empieza una prueba nueva
                ctx = {"inicio": time.time(), "pico_rps": 0.0, "rps": None,
                       "reinicios_base": medir_seguro("reinicios_base", total_reinicios)}
                with lock:
                    auto_est.update(valores={}, evaluado=None, disparo=None)
            ctx["pod"] = pod
            ctx.pop("jtl", None)                # la lectura del .jtl se renueva en cada ciclo
            with lock:
                cfg = copy.deepcopy(auto_cfg)
                parando = parada.get("estado") == "parando"
            if not cfg["activa"] or parando or not cfg["criterios"]:
                continue
            if time.time() - ctx["inicio"] < cfg["gracia"]:
                continue                        # arranque y rampa: aún no se evalúa

            ctx["rps"] = medir_seguro("rps", medir_rps, ctx)
            if ctx["rps"] is not None:
                ctx["pico_rps"] = max(ctx["pico_rps"], ctx["rps"])

            valores = {}
            for nombre, umbral in cfg["criterios"].items():
                c = CATALOGO[nombre]
                valor = None
                if not c["trafico"] or (ctx["rps"] or 0) >= MIN_RPS:
                    valor = medir_seguro(nombre, c["medir"], ctx)
                valores[nombre] = None if valor is None else round(valor, 2)
                if incumple(valor, c["op"], umbral):
                    seguidos[nombre] = seguidos.get(nombre, 0) + INTERVALO
                else:
                    seguidos[nombre] = 0
            for nombre in [n for n in seguidos if n not in cfg["criterios"]]:
                del seguidos[nombre]

            with lock:
                auto_est.update(valores=valores, evaluado=ahora())

            for nombre, segundos in seguidos.items():
                if segundos > 0 and segundos >= cfg["sostenido"]:
                    disparar(nombre, valores[nombre], cfg["criterios"][nombre])
                    seguidos.clear()
                    break
        except Exception as e:                  # noqa: BLE001  el vigilante no puede morir
            log(evento="vigilante_error", error=repr(e))


# ---------------------------------------------------------------- HTTP

class Parada(BaseHTTPRequestHandler):

    def cabeceras_cors(self):
        origen = self.headers.get("Origin")
        if origen and origen in CORS_ORIGENES:
            self.send_header("Access-Control-Allow-Origin", origen)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def responder(self, codigo, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.cabeceras_cors()
        self.end_headers()
        self.wfile.write(cuerpo)

    def autorizado(self):
        return not TOKEN or hmac.compare_digest(self.headers.get("Authorization", ""),
                                                f"Bearer {TOKEN}")

    def leer_json(self):
        """Cuerpo JSON como dict ({} si no hay cuerpo); None si no es un objeto JSON válido."""
        largo = int(self.headers.get("Content-Length") or 0)
        if not largo:
            return {}
        try:
            datos = json.loads(self.rfile.read(largo))
        except ValueError:
            return None
        return datos if isinstance(datos, dict) else None

    def do_OPTIONS(self):                       # petición previa (preflight) del navegador
        self.send_response(204)
        self.cabeceras_cors()
        self.end_headers()

    def do_GET(self):
        try:
            ruta = self.path.split("?")[0]
            if ruta == "/healthz":
                return self.responder(200, {"ok": True})
            if ruta == "/estado":
                return self.responder(200, estado())
            if ruta == "/autoparada":
                return self.responder(200, {**vista_auto(), "criterios_disponibles": catalogo_publico()})
            self.responder(404, {"error": "no existe"})
        except Exception as e:                  # noqa: BLE001
            self.responder(500, {"error": repr(e)})

    def do_POST(self):
        try:
            ruta, _, query = self.path.partition("?")
            if ruta not in ("/parar", "/autoparada"):
                return self.responder(404, {"error": "no existe"})
            if not self.autorizado():
                return self.responder(401, {"error": "falta el token"})
            if ruta == "/autoparada":
                codigo, respuesta = configurar_auto(self.leer_json())
                return self.responder(codigo, respuesta)
            motivo = parse_qs(query).get("motivo", [""])[0]
            if not motivo:
                motivo = str((self.leer_json() or {}).get("motivo", ""))
            codigo, respuesta = iniciar(limpiar(motivo))
            self.responder(codigo, respuesta)
        except Exception as e:                  # noqa: BLE001
            log(evento="error", error=repr(e))
            self.responder(500, {"error": repr(e)})

    def log_message(self, formato, *args):
        log(evento="http", peticion=formato % args)


if __name__ == "__main__":
    log(evento="inicio", namespace=NS, puerto=PUERTO,
        autoparada=auto_cfg["activa"], criterios=auto_cfg["criterios"])
    threading.Thread(target=vigilante, daemon=True).start()
    ThreadingHTTPServer(("", PUERTO), Parada).serve_forever()
