#!/bin/sh
# Despliega en el laboratorio la aplicación objetivo, la app que se va a poner a prueba.
# Sirve para cualquier app: basta con su imagen (de cualquier lenguaje) o con su .jar.
#
# Uso, desde src/3-execution/k8s (con el laboratorio ya montado: ./desplegar.sh):
#   ./desplegar-objetivo.sh --imagen <imagen> [--puerto N] [--salud /ruta]
#   ./desplegar-objetivo.sh --jar <fichero.jar> [--puerto N] [--salud /ruta] [--java N]
#
#   --imagen  imagen de la app: de un registro (registro.empresa.com/app:1.0) o construida en
#             este equipo (docker images). Cualquier lenguaje.
#   --jar     .jar ejecutable (java -jar): se mete en una imagen de Java (../objetivo/Dockerfile)
#   --puerto  puerto en el que escucha la app (por defecto 8080)
#   --salud   ruta HTTP que responde 200 cuando la app está lista (p. ej. /actuator/health/readiness
#             en Spring Boot). Sin ella, basta con que el puerto acepte conexiones.
#   --java    versión de Java para --jar (por defecto 21)
#
# Ejemplo, la bankapp del proyecto:
#   ./desplegar-objetivo.sh --imagen ghcr.io/davidretamosa/storm-bankapp --salud /actuator/health/readiness
#
# Dentro del clúster la app se llama siempre "objetivo" (objetivo.yaml) y se prueba con
# ./lanzar-prueba.sh <escenario> storm. Volver a ejecutarlo sustituye la app anterior.
set -e
cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1   # Git Bash: no convertir rutas como /actuator/... a rutas de Windows
NS=lab-jmeter

IMAGEN=""; JAR=""; PUERTO=8080; SALUD=""; JAVA=21
while [ $# -gt 0 ]; do
  case "$1" in
    --imagen) IMAGEN="${2:?Falta la imagen}"; shift 2 ;;
    --jar)    JAR="${2:?Falta el fichero .jar}"; shift 2 ;;
    --puerto) PUERTO="${2:?Falta el puerto}"; shift 2 ;;
    --salud)  SALUD="${2:?Falta la ruta}"; shift 2 ;;
    --java)   JAVA="${2:?Falta la versión de Java}"; shift 2 ;;
    *) echo "Opción desconocida: $1 (ver el principio de este script)"; exit 1 ;;
  esac
done
if [ -z "$IMAGEN$JAR" ] || { [ -n "$IMAGEN" ] && [ -n "$JAR" ]; }; then
  echo "Indica la app con --imagen <imagen> o con --jar <fichero.jar> (solo una de las dos)."
  exit 1
fi
case "$PUERTO" in ''|*[!0-9]*) echo "--puerto necesita un número"; exit 1 ;; esac
case "$SALUD" in ''|/*) ;; *) SALUD="/$SALUD" ;; esac
kubectl get namespace "$NS" >/dev/null 2>&1 || { echo "Antes monta el laboratorio: ./desplegar.sh"; exit 1; }

# En kind cada nodo tiene su propio almacén de imágenes: las de este equipo hay que copiárselas
CONTEXTO=$(kubectl config current-context)
KIND_CLUSTER=""; case "$CONTEXTO" in kind-*) KIND_CLUSTER=${CONTEXTO#kind-} ;; esac

# 1. La imagen
if [ -n "$JAR" ]; then
  [ -s "$JAR" ] || { echo "No existe el fichero '$JAR'"; exit 1; }
  IMAGEN=storm-objetivo:latest
  echo "1/3 Construyendo una imagen de Java $JAVA con $(basename "$JAR")..."
  # Carpeta temporal con ruta relativa (en Git Bash, Docker no entiende rutas como /tmp/...)
  TMP=$(mktemp -d ../objetivo/.construir-XXXXXX); trap 'rm -rf "$TMP"' EXIT
  cp "$JAR" "$TMP/app.jar"
  docker build -q --build-arg JAVA="$JAVA" -t "$IMAGEN" -f ../objetivo/Dockerfile "$TMP" >/dev/null
else
  echo "1/3 Imagen: $IMAGEN"
fi
if docker image inspect "$IMAGEN" >/dev/null 2>&1; then
  # Está en este equipo (construida aquí): el clúster no la descarga de ningún sitio
  POLITICA=IfNotPresent
  if [ -n "$KIND_CLUSTER" ]; then
    command -v kind >/dev/null || { echo "Falta kind en el PATH (winget install Kubernetes.kind)"; exit 1; }
    echo "   copiándola a los nodos de kind..."
    kind load docker-image "$IMAGEN" --name "$KIND_CLUSTER" >/dev/null
  fi
else
  # Viene de un registro: sin etiqueta o con :latest su contenido cambia, así que se descarga siempre
  case "${IMAGEN##*/}" in *:*) ;; *) IMAGEN="$IMAGEN:latest" ;; esac
  case "$IMAGEN" in *:latest) POLITICA=Always ;; *) POLITICA=IfNotPresent ;; esac
fi

# 2. La comprobación de "lista": ruta HTTP si se ha dado, si no basta con que el puerto responda
if [ -n "$SALUD" ]; then
  SONDA="httpGet: { path: \"$SALUD\", port: $PUERTO }"
else
  SONDA="tcpSocket: { port: $PUERTO }"
fi

# La bankapp de antes de objetivo.yaml ocupa el mismo puerto (30081): se quita si sigue ahí
if kubectl -n "$NS" get deploy bankapp >/dev/null 2>&1; then
  echo "   quitando el despliegue antiguo 'bankapp' (ahora la app se llama 'objetivo')"
  kubectl -n "$NS" delete deploy/bankapp svc/bankapp --ignore-not-found >/dev/null
fi

if [ -n "$SALUD" ]; then LISTA="responda $SALUD"; else LISTA="acepte conexiones"; fi
echo "2/3 Desplegando la app (puerto $PUERTO, lista cuando $LISTA)..."
sed -e "s|__IMAGEN__|$IMAGEN|" -e "s|__POLITICA__|$POLITICA|" -e "s|__PUERTO__|$PUERTO|g" \
    -e "s|__SONDA__|$SONDA|" objetivo.yaml | kubectl apply -f - >/dev/null
# Si ya existía con la misma imagen y etiqueta, se reinicia para que use la versión actual
kubectl -n "$NS" rollout restart deploy/objetivo >/dev/null

echo "3/3 Esperando a que la app esté lista..."
if ! kubectl -n "$NS" rollout status deploy/objetivo --timeout=300s >/dev/null; then
  echo "La app no ha llegado a estar lista. Revisa:"
  echo "  kubectl -n $NS describe pod -l app=objetivo   (eventos: ¿se descarga la imagen?)"
  echo "  kubectl -n $NS logs deploy/objetivo           (¿arranca? ¿en qué puerto escucha?)"
  exit 1
fi
case "$KIND_CLUSTER" in '') URL=http://localhost:30081 ;; *) URL=http://localhost:40081 ;; esac
echo "App objetivo lista: $IMAGEN, puerto $PUERTO (desde el equipo: $URL)"
echo "Siguiente: ./cargar-plan.sh <plan.jmx> y ./lanzar-prueba.sh <escenario> storm"
