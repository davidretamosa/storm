#!/bin/sh
# Despliega el laboratorio en el clúster de Kubernetes activo (kubectl config current-context):
# el de Docker Desktop (un nodo) o uno de kind con varios nodos (ver kind/cluster.yaml).
# Uso, desde src/3-execution/k8s:  ./desplegar.sh
# Se puede repetir: aplica solo los cambios (p. ej. un plan.jmx nuevo).
set -e
cd "$(dirname "$0")"
LAB=../lab-jmeter
NS=lab-jmeter

# En kind cada nodo es un contenedor con su propio almacén de imágenes: las que se construyen
# aquí hay que copiárselas (kind load). Docker Desktop, en cambio, usa directamente las de Docker.
CONTEXTO=$(kubectl config current-context)
case "$CONTEXTO" in
  kind-*) KIND_CLUSTER=${CONTEXTO#kind-}; PUERTO=4 ;;   # puertos 400xx (kind/cluster.yaml)
  *)      KIND_CLUSTER="";                PUERTO=3 ;;   # puertos 300xx (NodePort)
esac
echo "Clúster: $CONTEXTO ($(kubectl get nodes --no-headers | wc -l | tr -d ' ') nodos)"
cargar_en_kind() {  # cargar_en_kind <imagen>...: copia las imágenes a los nodos de kind
  [ -n "$KIND_CLUSTER" ] || return 0
  command -v kind >/dev/null || { echo "Falta kind en el PATH (winget install Kubernetes.kind)"; exit 1; }
  echo "   copiando a los nodos de kind: $*"
  kind load docker-image "$@" --name "$KIND_CLUSTER" >/dev/null
}

echo "1/4 Construyendo las imágenes locales (lab-app y lab-jmeter)..."
docker build -q -t lab-app "$LAB/app" >/dev/null
# La imagen de JMeter no cambia y construirla implica descargar JMeter (~90 MB):
# solo se construye si falta. Para forzarlo: docker rmi lab-jmeter
if ! docker image inspect lab-jmeter:latest >/dev/null 2>&1; then
  echo "   (descargando JMeter, solo la primera vez: unos minutos)"
  docker build -q -t lab-jmeter "$LAB/jmeter" >/dev/null
fi
cargar_en_kind lab-app:latest lab-jmeter:latest

echo "2/4 Creando el namespace y los ConfigMaps (plan.jmx y Grafana)..."
kubectl apply -f 00-namespace.yaml
configmap() {  # configmap <nombre> <--from-file ...>: crea o actualiza
  nombre=$1; shift
  kubectl -n "$NS" create configmap "$nombre" "$@" --dry-run=client -o yaml | kubectl apply -f -
}
configmap jmeter-plan --from-file=plan.jmx="$LAB/jmeter/plan.jmx"
configmap jmeter-escenarios --from-file=escenarios/
configmap jmeter-scripts --from-file=ejecutar-y-evaluar.sh --from-file=backend-listener.xml
configmap grafana-datasources --from-file="$LAB/grafana/provisioning/datasources/datasources.yml"
configmap grafana-dashboards \
  --from-file="$LAB/grafana/provisioning/dashboards/dashboards.yml" \
  --from-file=grafana/lab-jmeter-k8s.json

echo "3/4 Desplegando discos, app, InfluxDB, Prometheus y Grafana..."
kubectl apply -f almacenamiento.yaml
kubectl apply -f app.yaml -f influxdb.yaml -f prometheus.yaml -f grafana.yaml
# Workers de JMeter para pruebas distribuidas: se crean a 0 y lanzar-prueba.sh --workers N los arranca
kubectl apply -f jmeter-workers.yaml
DESPLIEGUES="resultados app influxdb prometheus grafana"
# La bankapp solo se despliega si ya se ha construido su imagen
if docker image inspect bankapp:latest >/dev/null 2>&1; then
  cargar_en_kind bankapp:latest
  kubectl apply -f bankapp.yaml
  # Reinicia el pod para que use la imagen recién construida (la etiqueta :latest no cambia)
  kubectl -n "$NS" rollout restart deploy/bankapp >/dev/null
  DESPLIEGUES="$DESPLIEGUES bankapp"
else
  echo "   (bankapp no desplegada: construye antes su imagen con ../bankapp/construir-imagen.sh)"
fi

echo "4/4 Esperando a que todo esté listo..."
for d in $DESPLIEGUES; do
  kubectl -n "$NS" rollout status deploy/"$d" --timeout=180s
done

echo
echo "Laboratorio listo:"
echo "  App:        http://localhost:${PUERTO}0080/hello"
echo "  Bankapp:    http://localhost:${PUERTO}0081/api/accounts  (si está desplegada)"
echo "  Grafana:    http://localhost:${PUERTO}0000/d/lab-jmeter-k8s  (admin / admin)"
echo "  Prometheus: http://localhost:${PUERTO}0090"
echo "Lanzar una prueba: ./lanzar-prueba.sh <escenario> [app|storm] [--workers N]"
