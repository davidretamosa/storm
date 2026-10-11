#!/bin/sh
# Despliega el laboratorio en Kubernetes (Docker Desktop).
# Uso, desde src/3-execution/k8s:  ./desplegar.sh
# Se puede repetir: aplica solo los cambios (p. ej. un plan.jmx nuevo).
set -e
cd "$(dirname "$0")"
LAB=../lab-jmeter
NS=lab-jmeter

echo "1/4 Construyendo las imágenes locales (lab-app y lab-jmeter)..."
docker build -q -t lab-app "$LAB/app" >/dev/null
docker build -q -t lab-jmeter "$LAB/jmeter" >/dev/null

echo "2/4 Creando el namespace y los ConfigMaps (plan.jmx y Grafana)..."
kubectl apply -f 00-namespace.yaml
configmap() {  # configmap <nombre> <--from-file ...>: crea o actualiza
  nombre=$1; shift
  kubectl -n "$NS" create configmap "$nombre" "$@" --dry-run=client -o yaml | kubectl apply -f -
}
configmap jmeter-plan --from-file=plan.jmx="$LAB/jmeter/plan.jmx"
configmap grafana-datasources --from-file="$LAB/grafana/provisioning/datasources/datasources.yml"
configmap grafana-dashboards \
  --from-file="$LAB/grafana/provisioning/dashboards/dashboards.yml" \
  --from-file=grafana/lab-jmeter-k8s.json

echo "3/4 Desplegando app, InfluxDB, Prometheus y Grafana..."
kubectl apply -f app.yaml -f influxdb.yaml -f prometheus.yaml -f grafana.yaml

echo "4/4 Esperando a que todo esté listo..."
for d in app influxdb prometheus grafana; do
  kubectl -n "$NS" rollout status deploy/"$d" --timeout=180s
done

echo
echo "Laboratorio listo:"
echo "  App:        http://localhost:30080/hello"
echo "  Grafana:    http://localhost:30000/d/lab-jmeter-k8s  (admin / admin)"
echo "  Prometheus: http://localhost:30090"
echo "Lanzar una prueba: ./lanzar-prueba.sh"
