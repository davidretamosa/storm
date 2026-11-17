"""Servicio de parada (el botón rojo).

Recibe POST /parar y detiene la prueba de JMeter que esté en marcha en el namespace.
La parada sube de nivel hasta que la prueba termina:

  0. abortada.txt  deja la nota que lee ejecutar-y-evaluar.sh (veredicto ABORTADA)
  1. shutdown.sh   parada ordenada: las muestras en curso acaban y se genera el informe
  2. stoptest.sh   parada inmediata, si la ordenada no termina a tiempo
  3. borrar el Job último recurso: puede dejar sin generar el informe HTML

Endpoints:
  POST /parar    inicia la parada y responde enseguida (202); la escalera sigue en segundo plano.
                 Motivo opcional: ?motivo=...  o cuerpo JSON {"motivo": "..."}
  GET  /estado   en qué punto va la parada y si hay una prueba en marcha
  GET  /healthz  sonda de Kubernetes

Variables de entorno (todas opcionales):
  NS               namespace de la prueba (en Kubernetes se rellena solo)       [lab-jmeter]
  ESPERA_SHUTDOWN  segundos que se espera tras shutdown.sh antes de subir de nivel [45]
  ESPERA_STOPTEST  segundos que se espera tras stoptest.sh antes de borrar el Job  [20]
  TOKEN            si se define, POST /parar exige "Authorization: Bearer <TOKEN>"
  CORS_ORIGEN      origen de Grafana, si el botón llama desde el navegador

En local (con tu kubeconfig):  pip install kubernetes  y  python parada.py
"""
import hmac
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

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
CORS_ORIGEN = os.environ.get("CORS_ORIGEN", "")
MOTIVO_DEFECTO = "botón rojo"

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
    info["prueba_en_marcha"] = pod_en_marcha() is not None
    return info


# ---------------------------------------------------------------- HTTP

class Parada(BaseHTTPRequestHandler):

    def cabeceras_cors(self):
        if CORS_ORIGEN:
            self.send_header("Access-Control-Allow-Origin", CORS_ORIGEN)
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
            self.responder(404, {"error": "no existe"})
        except Exception as e:                  # noqa: BLE001
            self.responder(500, {"error": repr(e)})

    def do_POST(self):
        try:
            ruta, _, query = self.path.partition("?")
            if ruta != "/parar":
                return self.responder(404, {"error": "no existe"})
            if TOKEN and not hmac.compare_digest(self.headers.get("Authorization", ""),
                                                 f"Bearer {TOKEN}"):
                return self.responder(401, {"error": "falta el token"})
            motivo = parse_qs(query).get("motivo", [""])[0]
            largo = int(self.headers.get("Content-Length") or 0)
            if largo and not motivo:
                try:
                    motivo = str(json.loads(self.rfile.read(largo)).get("motivo", ""))
                except (ValueError, AttributeError):
                    pass
            codigo, respuesta = iniciar(limpiar(motivo))
            self.responder(codigo, respuesta)
        except Exception as e:                  # noqa: BLE001
            log(evento="error", error=repr(e))
            self.responder(500, {"error": repr(e)})

    def log_message(self, formato, *args):
        log(evento="http", peticion=formato % args)


if __name__ == "__main__":
    log(evento="inicio", namespace=NS, puerto=PUERTO)
    ThreadingHTTPServer(("", PUERTO), Parada).serve_forever()