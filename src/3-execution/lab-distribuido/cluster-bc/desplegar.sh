#!/bin/sh
# Despliega el clúster 1 del lab distribuido (k3s con 2 nodos): JMeter master e InfluxDB y
# Grafana en el nodo con label rol=controller (pcb) y los workers de JMeter en el de
# rol=worker (pcc). La app (bankapp) y Prometheus NO van aquí: están en PC A (../pc-a).
# Uso, en pcb desde lab-distribuido/cluster-bc:  ./desplegar.sh
# Se puede repetir: aplica solo los cambios.
#
# Imágenes: versiones fijas e imagePullPolicy IfNotPresent, para que la demo funcione sin
# internet si las imágenes ya están en los nodos (ver README). Las de storm (JMeter) vienen
# de ghcr.io/davidretamosa con la etiqueta ETIQUETA (sha-xxxxxxx = un commit concreto).
set -e
cd "$(dirname "$0")"
NS=lab-jmeter
REGISTRO=ghcr.io/davidretamosa
ETIQUETA="${ETIQUETA:-latest}"
[ "$ETIQUETA" = latest ] && echo "Aviso: ETIQUETA=latest. Para la demo fija una versión: ETIQUETA=sha-xxxxxxx ./desplegar.sh"

# Cada componente va a un nodo concreto (nodeSelector rol=...): sin las labels, los pods no arrancan
for rol in controller worker; do
  if [ -z "$(kubectl get nodes -l rol=$rol -o name)" ]; then
    echo "Ningún nodo tiene la label rol=$rol: kubectl label node <nodo> rol=$rol"
    exit 1
  fi
done
echo "Clúster: $(kubectl config current-context)"
kubectl get nodes -L rol --no-headers | awk '{print "   " $1 "  rol=" $NF}'

echo "1/3 Creando el namespace y los ConfigMaps (escenarios, scripts y Grafana)..."
kubectl apply -f 00-namespace.yaml
configmap() {  # configmap <nombre> <--from-file ...>: crea o actualiza
  nombre=$1; shift
  kubectl -n "$NS" create configmap "$nombre" "$@" --dry-run=client -o yaml | kubectl apply -f -
}
configmap jmeter-escenarios --from-file=escenarios/
configmap jmeter-scripts --from-file=ejecutar-y-evaluar.sh --from-file=backend-listener.xml
configmap grafana-datasources --from-file=grafana/datasources.yml
configmap grafana-dashboards --from-file=grafana/dashboards.yml --from-file=grafana/lab-jmeter-k8s.json

echo "2/3 Desplegando discos, InfluxDB, Grafana y workers de JMeter (imágenes storm: $ETIQUETA)..."
kubectl apply -f almacenamiento.yaml -f influxdb.yaml -f grafana.yaml
# Workers de JMeter: se crean a 0 y lanzar-prueba.sh --workers N los arranca.
# El Job de cada prueba (master) usa la misma imagen que ellos.
sed "s|__IMAGEN_JMETER__|$REGISTRO/storm-lab-jmeter:$ETIQUETA|" jmeter-workers.yaml | kubectl apply -f -

echo "3/3 Esperando a que todo esté listo..."
for d in resultados influxdb grafana; do
  kubectl -n "$NS" rollout status deploy/"$d" --timeout=300s
done

IP_CONTROLLER=$(kubectl get nodes -l rol=controller -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
echo
echo "Clúster 1 listo:"
echo "  Grafana: http://$IP_CONTROLLER:30000/d/lab-jmeter-k8s  (admin / admin)"
echo "Siguiente: ./cargar-plan.sh <plan.jmx> y ./lanzar-prueba.sh <escenario> externo --workers 1"
