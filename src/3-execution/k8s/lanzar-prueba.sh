#!/bin/sh
# Lanza una prueba de carga (Job de JMeter) y muestra su salida en directo.
# Uso, desde src/3-execution/k8s:  ./lanzar-prueba.sh [escenario] [app|storm] [--workers N]
#   escenario: humo (por defecto), normal, pico o estres (escenarios/*.properties)
#   objetivo:  app     app de prueba con su plan (por defecto)
#              storm   bankapp con el plan entregado por 2-processing (./cargar-plan.sh)
#   --workers N  prueba distribuida: Kubernetes arranca N workers de JMeter (jmeter-workers.yaml),
#                la carga se reparte entre ellos y al terminar se vuelven a apagar.
#                Sin la opción, un solo pod de JMeter genera toda la carga (como siempre).
set -e
cd "$(dirname "$0")"
# En Git Bash (Windows) evita que rutas como pod:/resultados se conviertan a rutas de Windows
export MSYS_NO_PATHCONV=1
NS=lab-jmeter

# Argumentos: escenario y objetivo por posición; --workers N en cualquier sitio
NUM_WORKERS=0
POSICIONALES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --workers)   NUM_WORKERS="${2:?Uso: --workers N}"; shift 2 ;;
    --workers=*) NUM_WORKERS="${1#--workers=}"; shift ;;
    *)           POSICIONALES="$POSICIONALES $1"; shift ;;
  esac
done
set -- $POSICIONALES
ESCENARIO="${1:-humo}"
OBJETIVO="${2:-app}"
case "$NUM_WORKERS" in
  ''|*[!0-9]*) echo "--workers necesita un número (0 = sin workers)"; exit 1 ;;
esac

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

# Prueba distribuida: se piden N workers a Kubernetes y se espera a que estén listos
WORKERS=""
if [ "$NUM_WORKERS" -gt 0 ]; then
  if ! kubectl -n "$NS" get deploy jmeter-worker >/dev/null 2>&1; then
    echo "Los workers no están desplegados: ./desplegar.sh (o kubectl apply -f jmeter-workers.yaml)"
    exit 1
  fi
  # No tiene sentido tener más workers que usuarios (cada worker lleva al menos uno)
  VUSERS=$(sed -n 's/^vusers=//p' "escenarios/$ESCENARIO.properties" | tr -d '\r ')
  if [ -n "$VUSERS" ] && [ "$NUM_WORKERS" -gt "$VUSERS" ]; then
    echo "El escenario '$ESCENARIO' tiene $VUSERS usuarios: se usan $VUSERS workers en lugar de $NUM_WORKERS."
    NUM_WORKERS=$VUSERS
  fi
  ID="$ESCENARIO-$OBJETIVO-${NUM_WORKERS}workers-$(date +%Y%m%d-%H%M%S)"
  echo "Arrancando $NUM_WORKERS workers de JMeter..."
  kubectl -n "$NS" scale deploy jmeter-worker --replicas="$NUM_WORKERS" >/dev/null
  kubectl -n "$NS" rollout status deploy jmeter-worker --timeout=180s >/dev/null
  # IPs de los workers listos, según el Service jmeter-worker (no incluye los que se están apagando)
  for i in $(seq 1 30); do
    WORKERS=$(kubectl -n "$NS" get endpointslices -l kubernetes.io/service-name=jmeter-worker \
      -o jsonpath='{range .items[*].endpoints[?(@.conditions.ready==true)]}{.addresses[0]}{"\n"}{end}' | sort -u | paste -sd, -)
    [ "$(echo "$WORKERS" | tr ',' '\n' | grep -c .)" -eq "$NUM_WORKERS" ] && break
    sleep 2
  done
  echo "Workers listos: $WORKERS"
fi

# El master usa la misma imagen que los workers: la local (lab-jmeter) o la del registro si el
# laboratorio se desplegó con REGISTRO=... ./desplegar.sh
IMAGEN=$(kubectl -n "$NS" get deploy jmeter-worker -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)
POLITICA=$(kubectl -n "$NS" get deploy jmeter-worker -o jsonpath='{.spec.template.spec.containers[0].imagePullPolicy}' 2>/dev/null || true)

# Un Job no se puede volver a ejecutar: se borra el anterior y se crea otro
kubectl -n "$NS" delete job jmeter --ignore-not-found
sed -e "s/__ESCENARIO__/$ESCENARIO/g" -e "s/__PLAN__/$PLAN/g" -e "s/__HOST__/$HOST/g" -e "s/__ID__/$ID/g" \
    -e "s/__WORKERS__/$WORKERS/g" \
    -e "s|image: lab-jmeter:latest|image: ${IMAGEN:-lab-jmeter:latest}|" \
    -e "s|imagePullPolicy: Never|imagePullPolicy: ${POLITICA:-Never}|" \
    -e "s/__MAX_ERRORES_PCT__/$MAX_ERRORES_PCT/g" -e "s/__MAX_P95_MS__/$MAX_P95_MS/g" jmeter-job.yaml | kubectl apply -f -

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

# Los workers solo hacen falta durante la prueba: se vuelven a 0 para liberar memoria
if [ "$NUM_WORKERS" -gt 0 ]; then
  kubectl -n "$NS" scale deploy jmeter-worker --replicas=0 >/dev/null
  echo "Workers apagados."
fi

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
