#!/bin/sh
# Carga en el laboratorio el plan .jmx entregado por 2-processing (el grupo de IA) para
# inyectarlo contra la bankapp.
# Uso, desde src/3-execution/k8s:  ./cargar-plan.sh <fichero.jmx>
# Después: ./lanzar-prueba.sh <escenario> storm
#
# El plan debe apuntar a la app con ${__P(host,...)} y ${__P(port,...)} (como los que genera
# 2-processing): el laboratorio le pasa host=bankapp. Si no envía métricas a InfluxDB, se le
# añade el Backend Listener al ejecutarlo (ver ejecutar-y-evaluar.sh).
set -e
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1
NS=lab-jmeter
PLAN="${1:?Uso: ./cargar-plan.sh <fichero.jmx>}"

[ -s "$PLAN" ] || { echo "No existe el fichero '$PLAN'"; exit 1; }
grep -q "<jmeterTestPlan" "$PLAN" || { echo "'$PLAN' no parece un plan de JMeter (.jmx)"; exit 1; }
grep -q '__P(host' "$PLAN" || echo "Aviso: el plan no usa \${__P(host,...)}: apuntará a la app que tenga escrita dentro, no a la bankapp del laboratorio."

mkdir -p planes
cp "$PLAN" planes/storm.jmx
kubectl -n "$NS" create configmap jmeter-plan-storm --from-file=plan.jmx=planes/storm.jmx \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
echo "Plan cargado: $PLAN -> k8s/planes/storm.jmx"
echo "Lánzalo con: ./lanzar-prueba.sh <escenario> storm"
