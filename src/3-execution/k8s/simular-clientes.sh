#!/bin/sh
# Simula clientes usando la bankapp y recoge los logs que genera (logs/bankapp.jsonl),
# para que el generador de 2-processing aprenda de ellos.
# Uso, desde src/3-execution/k8s:  ./simular-clientes.sh [minutos] [clientes]
#   por defecto: 5 minutos y 8 clientes a la vez
# Después: ./generar-plan.sh (usará estos logs además del .jar)
set -e
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1
NS=lab-jmeter
MINUTOS="${1:-5}"
CLIENTES="${2:-8}"

if ! kubectl -n "$NS" get deploy bankapp >/dev/null 2>&1; then
  echo "La bankapp no está desplegada: ../bankapp/construir-imagen.sh y ./desplegar.sh"
  exit 1
fi

# Bankapp recién arrancada: su base de datos vuelve al estado inicial y el fichero de
# logs empieza vacío, así solo contiene la simulación
echo "Reiniciando la bankapp para empezar con logs vacíos..."
kubectl -n "$NS" rollout restart deploy/bankapp >/dev/null
kubectl -n "$NS" rollout status deploy/bankapp --timeout=240s >/dev/null

kubectl -n "$NS" create configmap simulador --from-file=../simulador/simulador.py \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n "$NS" delete job simulador --ignore-not-found >/dev/null
sed -e "s/__CLIENTES__/$CLIENTES/" -e "s/__MINUTOS__/$MINUTOS/" simulador-job.yaml | kubectl apply -f - >/dev/null
kubectl -n "$NS" wait --for=condition=ready pod -l job-name=simulador --timeout=180s >/dev/null 2>&1 || true
kubectl -n "$NS" logs -f job/simulador

# Recoge los logs de la bankapp: copia en el equipo y en el disco del clúster (para el generador)
BANKAPP=$(kubectl -n "$NS" get pod -l app=bankapp -o jsonpath='{.items[0].metadata.name}')
RESULTADOS=$(kubectl -n "$NS" get pod -l app=resultados -o jsonpath='{.items[0].metadata.name}')
mkdir -p logs
FICHERO="logs/bankapp-$(date +%Y%m%d-%H%M%S).jsonl"
kubectl -n "$NS" cp "$BANKAPP:/app/logs/bankapp.jsonl" "$FICHERO" >/dev/null
kubectl -n "$NS" exec "$RESULTADOS" -- mkdir -p /resultados/logs
kubectl -n "$NS" cp "$FICHERO" "$RESULTADOS:/resultados/logs/bankapp.jsonl" >/dev/null

echo
echo "Logs recogidos: k8s/$FICHERO ($(wc -l < "$FICHERO") peticiones)"
echo "Genera el plan con ellos: ./generar-plan.sh"
