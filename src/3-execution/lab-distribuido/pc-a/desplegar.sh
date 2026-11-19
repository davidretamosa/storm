#!/bin/sh
# PC A del lab distribuido (Windows, Kubernetes de Docker Desktop): despliega la app que se
# pone a prueba (la bankapp) y Prometheus. JMeter, InfluxDB y Grafana están en el clúster 1
# (pcb y pcc, ../cluster-bc) y llegan aquí por la red del lab:
#   bankapp     http://192.168.10.1:30081   (JMeter la ataca)
#   Prometheus  http://192.168.10.1:30090   (datasource de Grafana)
# Hay que abrir esos dos puertos en el firewall de Windows (ver README).
#
# Uso, en PC A (Git Bash) desde lab-distribuido/pc-a:
#   ./desplegar.sh [--imagen <imagen>] [--puerto N] [--salud /ruta]
#   sin opciones  la bankapp: ghcr.io/davidretamosa/storm-bankapp:<ETIQUETA>, puerto 8080,
#                 lista cuando /actuator/health/readiness responde 200
#   --imagen      otra app (cualquier lenguaje); --puerto y --salud, los suyos
# Versión de la bankapp: ETIQUETA=sha-xxxxxxx ./desplegar.sh (por defecto latest).
# Para la demo sin internet: versión fija e imágenes ya descargadas (imagePullPolicy IfNotPresent).
#
# Dentro de Kubernetes la app se llama "objetivo" (objetivo.yaml) en el namespace lab-jmeter:
# el dashboard de Grafana busca la CPU y la memoria de los pods objetivo-* de ese namespace.
set -e
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1   # Git Bash: no convertir rutas como /actuator/... a rutas de Windows
NS=lab-jmeter
ETIQUETA="${ETIQUETA:-latest}"

IMAGEN=""; PUERTO=8080; SALUD=/actuator/health/readiness
while [ $# -gt 0 ]; do
  case "$1" in
    --imagen) IMAGEN="${2:?Falta la imagen}"; SALUD=""; shift 2 ;;
    --puerto) PUERTO="${2:?Falta el puerto}"; shift 2 ;;
    --salud)  SALUD="${2:?Falta la ruta}"; shift 2 ;;
    *) echo "Opción desconocida: $1 (ver el principio de este script)"; exit 1 ;;
  esac
done
[ -n "$IMAGEN" ] || IMAGEN=ghcr.io/davidretamosa/storm-bankapp:$ETIQUETA
case "$PUERTO" in ''|*[!0-9]*) echo "--puerto necesita un número"; exit 1 ;; esac
case "$SALUD" in ''|/*) ;; *) SALUD="/$SALUD" ;; esac
case "${IMAGEN##*/}" in *:*) ;; *) IMAGEN="$IMAGEN:latest" ;; esac
case "$IMAGEN" in *:latest) echo "Aviso: $IMAGEN. Para la demo fija una versión (ETIQUETA=sha-xxxxxxx)." ;; esac

# Debe ser el Kubernetes de Docker Desktop de PC A, no el clúster 1
CONTEXTO=$(kubectl config current-context)
[ "$CONTEXTO" = docker-desktop ] || echo "Aviso: el contexto de kubectl es '$CONTEXTO', no docker-desktop."

echo "1/3 Namespace, disco y Prometheus (NodePort 30090)..."
kubectl apply -f 00-namespace.yaml -f almacenamiento.yaml -f prometheus.yaml >/dev/null

# La comprobación de "lista": ruta HTTP si se ha dado, si no basta con que el puerto responda
if [ -n "$SALUD" ]; then
  SONDA="httpGet: { path: \"$SALUD\", port: $PUERTO }"; LISTA="responda $SALUD"
else
  SONDA="tcpSocket: { port: $PUERTO }"; LISTA="acepte conexiones"
fi
echo "2/3 App: $IMAGEN (puerto $PUERTO, NodePort 30081, lista cuando $LISTA)..."
sed -e "s|__IMAGEN__|$IMAGEN|" -e "s|__POLITICA__|IfNotPresent|" -e "s|__PUERTO__|$PUERTO|g" \
    -e "s|__SONDA__|$SONDA|" objetivo.yaml | kubectl apply -f - >/dev/null
# Si ya existía con la misma imagen y etiqueta, se reinicia para empezar cada vez desde cero
kubectl -n "$NS" rollout restart deploy/objetivo >/dev/null

echo "3/3 Esperando a que la app y Prometheus estén listos..."
kubectl -n "$NS" rollout status deploy/prometheus --timeout=180s >/dev/null
if ! kubectl -n "$NS" rollout status deploy/objetivo --timeout=300s >/dev/null; then
  echo "La app no ha llegado a estar lista. Revisa:"
  echo "  kubectl -n $NS describe pod -l app=objetivo   (eventos: ¿está la imagen?)"
  echo "  kubectl -n $NS logs deploy/objetivo           (¿arranca? ¿en qué puerto escucha?)"
  exit 1
fi
echo
echo "PC A listo:"
echo "  App:        http://192.168.10.1:30081  ($IMAGEN)"
echo "  Prometheus: http://192.168.10.1:30090"
