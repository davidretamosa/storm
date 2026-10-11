#!/bin/sh
# Lanza una prueba de carga (Job de JMeter) y muestra su salida en directo.
# Uso, desde src/3-execution/k8s:  ./lanzar-prueba.sh
set -e
cd "$(dirname "$0")"
NS=lab-jmeter

# Un Job no se puede volver a ejecutar: se borra el anterior y se crea otro
kubectl -n "$NS" delete job jmeter --ignore-not-found
kubectl apply -f jmeter-job.yaml

echo "Prueba en marcha. Dashboard: http://localhost:30000/d/lab-jmeter-k8s"
kubectl -n "$NS" wait --for=condition=ready pod -l job-name=jmeter --timeout=120s >/dev/null 2>&1 || true
kubectl -n "$NS" logs -f job/jmeter

if kubectl -n "$NS" wait --for=condition=complete job/jmeter --timeout=60s >/dev/null 2>&1; then
  echo "Prueba terminada correctamente."
else
  echo "La prueba ha fallado. Revisa: kubectl -n $NS describe job jmeter"
  exit 1
fi
