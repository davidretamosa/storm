#!/bin/sh
# Genera el plan de prueba con el generador de 2-processing a partir de la bankapp desplegada.
# Uso, desde src/3-execution/k8s:  ./generar-plan.sh [logs]
#   logs: fichero .jsonl con el uso de la bankapp del que aprende el generador. Puede ser
#         - una ruta local (p. ej. logs/bankapp-20261015-122818.jsonl)
#         - "repo": el fichero de logs que mantiene 1-input en Git
#           (origin/develop:src/1-input/java-app-mock/logs/bankapp.jsonl)
#   Sin argumento usa los últimos recogidos por ./simular-clientes.sh (o solo el .jar si no hay).
# Antes: ../bankapp/construir-imagen.sh, ../generador/construir-imagen.sh y ./desplegar.sh
# Después: ./lanzar-prueba.sh <escenario> storm
set -e
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1
NS=lab-jmeter

for imagen in bankapp storm-generador; do
  if ! docker image inspect "$imagen:latest" >/dev/null 2>&1; then
    echo "Falta la imagen $imagen. Constrúyela con ../${imagen#storm-}/construir-imagen.sh"
    exit 1
  fi
done

# Logs indicados: se dejan en el disco del clúster, donde los busca el generador
LOGS="${1:-}"
if [ "$LOGS" = repo ]; then
  git fetch -q origin
  LOGS=logs/bankapp-repo.jsonl
  mkdir -p logs
  git show origin/develop:src/1-input/java-app-mock/logs/bankapp.jsonl > "$LOGS"
fi
if [ -n "$LOGS" ]; then
  [ -s "$LOGS" ] || { echo "No existe el fichero de logs '$LOGS'"; exit 1; }
  RESULTADOS=$(kubectl -n "$NS" get pod -l app=resultados -o jsonpath='{.items[0].metadata.name}')
  kubectl -n "$NS" exec "$RESULTADOS" -- mkdir -p /resultados/logs
  kubectl -n "$NS" cp "$LOGS" "$RESULTADOS:/resultados/logs/bankapp.jsonl" >/dev/null
  echo "Logs para el generador: $LOGS ($(wc -l < "$LOGS") peticiones)"
fi

kubectl -n "$NS" delete job generador --ignore-not-found >/dev/null
kubectl apply -f generador-job.yaml >/dev/null
echo "Generando el plan con 2-processing a partir del .jar de la bankapp..."
if ! kubectl -n "$NS" wait --for=condition=complete job/generador --timeout=300s >/dev/null 2>&1; then
  kubectl -n "$NS" logs job/generador --all-containers 2>&1 | tail -20
  echo "El generador ha fallado. Revisa: kubectl -n $NS describe job generador"
  exit 1
fi
kubectl -n "$NS" logs job/generador

# Se copia el plan al equipo (para verlo o abrirlo en JMeter) y se crea su ConfigMap
mkdir -p planes
POD=$(kubectl -n "$NS" get pod -l app=resultados -o jsonpath='{.items[0].metadata.name}')
kubectl -n "$NS" cp "$POD:/resultados/planes/storm.jmx" planes/storm.jmx >/dev/null
kubectl -n "$NS" create configmap jmeter-plan-storm --from-file=plan.jmx=planes/storm.jmx \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
echo
echo "Plan listo: k8s/planes/storm.jmx"
echo "Lánzalo con: ./lanzar-prueba.sh <escenario> storm"
