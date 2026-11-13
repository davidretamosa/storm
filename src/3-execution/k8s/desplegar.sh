#!/bin/sh
# Despliega el laboratorio en el clúster de Kubernetes activo (kubectl config current-context):
# el de Docker Desktop (un nodo) o uno de kind con varios nodos (ver kind/cluster.yaml).
# Uso, desde src/3-execution/k8s:  ./desplegar.sh
# Se puede repetir: aplica solo los cambios (p. ej. un plan.jmx nuevo).
#
# Imágenes propias (bankapp, lab-app, lab-jmeter):
#   por defecto   se construyen en este equipo (la bankapp, con ../bankapp/construir-imagen.sh)
#   REGISTRO=ghcr.io/davidretamosa ./desplegar.sh
#                 no se construye nada: el clúster las descarga del registro, donde las publica
#                 GitHub Actions (.github/workflows/imagenes.yml). Es lo que hace falta en un
#                 clúster en la nube. ETIQUETA elige la versión (por defecto latest = develop).
set -e
cd "$(dirname "$0")"
LAB=../lab-jmeter
NS=lab-jmeter
REGISTRO="${REGISTRO%/}"
ETIQUETA="${ETIQUETA:-latest}"

# kubectl apply de un fichero; con REGISTRO, cambia antes las imágenes locales por las del
# registro y deja que Kubernetes las descargue (imagePullPolicy Always: latest cambia de contenido)
aplicar() {
  if [ -n "$REGISTRO" ]; then
    sed -e "s|image: bankapp:latest|image: $REGISTRO/storm-bankapp:$ETIQUETA|" \
        -e "s|image: lab-app:latest|image: $REGISTRO/storm-lab-app:$ETIQUETA|" \
        -e "s|image: lab-jmeter:latest|image: $REGISTRO/storm-lab-jmeter:$ETIQUETA|" \
        -e "s|imagePullPolicy: Never|imagePullPolicy: Always|" "$1" | kubectl apply -f -
  else
    kubectl apply -f "$1"
  fi
}

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

if [ -n "$REGISTRO" ]; then
  echo "1/4 Imágenes del registro $REGISTRO (etiqueta $ETIQUETA): no se construye nada."
else
  echo "1/4 Construyendo las imágenes locales (lab-app y lab-jmeter)..."
  docker build -q -t lab-app "$LAB/app" >/dev/null
  # La imagen de JMeter no cambia y construirla implica descargar JMeter (~90 MB):
  # solo se construye si falta. Para forzarlo: docker rmi lab-jmeter
  if ! docker image inspect lab-jmeter:latest >/dev/null 2>&1; then
    echo "   (descargando JMeter, solo la primera vez: unos minutos)"
    docker build -q -t lab-jmeter "$LAB/jmeter" >/dev/null
  fi
  cargar_en_kind lab-app:latest lab-jmeter:latest
fi

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
aplicar app.yaml
kubectl apply -f influxdb.yaml -f prometheus.yaml -f grafana.yaml
# Workers de JMeter para pruebas distribuidas: se crean a 0 y lanzar-prueba.sh --workers N los
# arranca. El Job de cada prueba (master) usa la misma imagen que ellos.
aplicar jmeter-workers.yaml
DESPLIEGUES="resultados app influxdb prometheus grafana"
# La bankapp se despliega si está en el registro o si ya se ha construido su imagen
if [ -n "$REGISTRO" ] || docker image inspect bankapp:latest >/dev/null 2>&1; then
  [ -n "$REGISTRO" ] || cargar_en_kind bankapp:latest
  aplicar bankapp.yaml
  # Reinicia el pod para que use la imagen recién construida o publicada (la etiqueta no cambia)
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
