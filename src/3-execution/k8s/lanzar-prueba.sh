#!/bin/sh
# Lanza una prueba de carga (Job de JMeter) y muestra su salida en directo.
# Uso, desde src/3-execution/k8s:  ./lanzar-prueba.sh [escenario] [app|storm]
#   escenario: humo (por defecto), normal, pico o estres (escenarios/*.properties)
#   objetivo:  app     app de prueba con su plan (por defecto)
#              storm   bankapp con el plan entregado por 2-processing (./cargar-plan.sh)
set -e
cd "$(dirname "$0")"
# En Git Bash (Windows) evita que rutas como pod:/resultados se conviertan a rutas de Windows
export MSYS_NO_PATHCONV=1
NS=lab-jmeter
ESCENARIO="${1:-humo}"
OBJETIVO="${2:-app}"

if [ ! -f "escenarios/$ESCENARIO.properties" ]; then
  echo "No existe el escenario '$ESCENARIO'. Disponibles:"
  ls escenarios | sed 's/\.properties$//; s/^/  /'
  exit 1
fi

# Plan (ConfigMap), app a la que apunta JMeter y criterios de aprobado de cada objetivo
case "$OBJETIVO" in
  app)     PLAN=jmeter-plan;         HOST=app;     CRITERIOS=app ;;
  storm)   PLAN=jmeter-plan-storm;   HOST=bankapp; CRITERIOS=bankapp
           if ! kubectl -n "$NS" get configmap jmeter-plan-storm >/dev/null 2>&1; then
             echo "Aún no hay plan cargado: ejecuta ./cargar-plan.sh <fichero.jmx>"
             exit 1
           fi ;;
  *)       echo "Objetivo desconocido '$OBJETIVO': usa app o storm"; exit 1 ;;
esac
if [ "$HOST" = bankapp ] && ! kubectl -n "$NS" get deploy bankapp >/dev/null 2>&1; then
  echo "La bankapp no está desplegada: ../bankapp/construir-imagen.sh y ./desplegar.sh"
  exit 1
fi

# Criterios de aprobado (MAX_ERRORES_PCT y MAX_P95_MS)
. "criterios/$CRITERIOS.properties"

# Cada prueba guarda sus resultados en su propia carpeta
ID="$ESCENARIO-$OBJETIVO-$(date +%Y%m%d-%H%M%S)"

# Un Job no se puede volver a ejecutar: se borra el anterior y se crea otro
kubectl -n "$NS" delete job jmeter --ignore-not-found
sed -e "s/__ESCENARIO__/$ESCENARIO/g" -e "s/__PLAN__/$PLAN/g" -e "s/__HOST__/$HOST/g" -e "s/__ID__/$ID/g"     -e "s/__MAX_ERRORES_PCT__/$MAX_ERRORES_PCT/g" -e "s/__MAX_P95_MS__/$MAX_P95_MS/g" jmeter-job.yaml | kubectl apply -f -

echo "Escenario '$ESCENARIO' contra $OBJETIVO en marcha:"
grep -v '^#' "escenarios/$ESCENARIO.properties" | grep . | sed 's/^/  /'
echo "Dashboard: http://localhost:30000/d/lab-jmeter-k8s"
kubectl -n "$NS" wait --for=condition=ready pod -l job-name=jmeter --timeout=120s >/dev/null 2>&1 || true
kubectl -n "$NS" logs -f job/jmeter

# logs -f termina cuando acaba el pod; se espera a que el Job tenga su estado final
for i in $(seq 1 30); do
  ESTADO=$(kubectl -n "$NS" get job jmeter -o jsonpath='{.status.succeeded}/{.status.failed}')
  [ "$ESTADO" != "/" ] && break
  sleep 1
done

# Copia los resultados del disco del clúster al equipo (desde el pod auxiliar "resultados")
mkdir -p resultados
POD=$(kubectl -n "$NS" get pod -l app=resultados -o jsonpath='{.items[0].metadata.name}')
if kubectl -n "$NS" cp "$POD:/resultados/$ID" "resultados/$ID" >/dev/null 2>&1; then
  echo "Resultados guardados en k8s/resultados/$ID (informe: informe/index.html)"
else
  echo "No se pudieron copiar los resultados (siguen en el disco jmeter-resultados del clúster)"
fi

case "$ESTADO" in
  1/*) echo "Prueba '$ESCENARIO' contra $OBJETIVO: SUPERADA." ;;
  */1) echo "Prueba '$ESCENARIO' contra $OBJETIVO: NO SUPERADA (detalle arriba)."; exit 1 ;;
  *)   echo "No se pudo saber el resultado. Revisa: kubectl -n $NS describe job jmeter"; exit 2 ;;
esac
