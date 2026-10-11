#!/bin/sh
# Lanza una prueba de carga (Job de JMeter) y muestra su salida en directo.
# Uso, desde src/3-execution/k8s:  ./lanzar-prueba.sh [escenario] [app|bankapp]
#   escenario: humo (por defecto), normal, pico o estres (escenarios/*.properties)
#   objetivo:  app (app de prueba, por defecto) o bankapp (con su plan provisional)
set -e
cd "$(dirname "$0")"
NS=lab-jmeter
ESCENARIO="${1:-humo}"
OBJETIVO="${2:-app}"

if [ ! -f "escenarios/$ESCENARIO.properties" ]; then
  echo "No existe el escenario '$ESCENARIO'. Disponibles:"
  ls escenarios | sed 's/\.properties$//; s/^/  /'
  exit 1
fi

case "$OBJETIVO" in
  app)     PLAN=jmeter-plan ;;
  bankapp) PLAN=jmeter-plan-bankapp
           if ! kubectl -n "$NS" get deploy bankapp >/dev/null 2>&1; then
             echo "La bankapp no está desplegada: ../bankapp/construir-imagen.sh y ./desplegar.sh"
             exit 1
           fi ;;
  *)       echo "Objetivo desconocido '$OBJETIVO': usa app o bankapp"; exit 1 ;;
esac

# Un Job no se puede volver a ejecutar: se borra el anterior y se crea otro
kubectl -n "$NS" delete job jmeter --ignore-not-found
sed -e "s/__ESCENARIO__/$ESCENARIO/g" -e "s/__PLAN__/$PLAN/g" -e "s/__HOST__/$OBJETIVO/g" jmeter-job.yaml | kubectl apply -f -

echo "Escenario '$ESCENARIO' contra $OBJETIVO en marcha:"
grep -v '^#' "escenarios/$ESCENARIO.properties" | grep . | sed 's/^/  /'
echo "Dashboard: http://localhost:30000/d/lab-jmeter-k8s"
kubectl -n "$NS" wait --for=condition=ready pod -l job-name=jmeter --timeout=120s >/dev/null 2>&1 || true
kubectl -n "$NS" logs -f job/jmeter

if kubectl -n "$NS" wait --for=condition=complete job/jmeter --timeout=60s >/dev/null 2>&1; then
  echo "Prueba '$ESCENARIO' terminada correctamente."
else
  echo "La prueba ha fallado. Revisa: kubectl -n $NS describe job jmeter"
  exit 1
fi
