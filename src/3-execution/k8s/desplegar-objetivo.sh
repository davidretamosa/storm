#!/bin/sh
# Despliega en el laboratorio la aplicación objetivo, la app que se va a poner a prueba.
# Sirve para cualquier app: basta con su imagen (de cualquier lenguaje) o con su .jar.
#
# Uso, desde src/3-execution/k8s (con el laboratorio ya montado: ./desplegar.sh):
#   ./desplegar-objetivo.sh --imagen <imagen> [--puerto N] [--salud /ruta]
#   ./desplegar-objetivo.sh --jar <fichero.jar> [--puerto N] [--salud /ruta] [--java N]
#   (las dos admiten además --publicar <registro>, ver abajo)
#
#   --imagen  imagen de la app: de un registro (registro.empresa.com/app:1.0) o construida en
#             este equipo (docker images). Cualquier lenguaje.
#   --jar     .jar ejecutable (java -jar): se mete en una imagen de Java (../objetivo/Dockerfile)
#   --puerto  puerto en el que escucha la app (por defecto 8080)
#   --salud   ruta HTTP que responde 200 cuando la app está lista (p. ej. /actuator/health/readiness
#             en Spring Boot). Sin ella, basta con que el puerto acepte conexiones.
#   --java    versión de Java para --jar (por defecto 21)
#   --publicar  registro al que subir la imagen fabricada en este equipo (p. ej. ghcr.io/<usuario>)
#             antes de desplegarla. Hace falta cuando el clúster no puede ver este equipo (la
#             nube): el clúster la descarga del registro. Antes: docker login <registro>.
#             Si el registro es privado, el clúster necesita sus credenciales en el Secret
#             "registro-objetivo" (ver k8s/README.md); si existe, se usa solo.
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

IMAGEN=""; JAR=""; PUERTO=8080; SALUD=""; JAVA=21; PUBLICAR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --publicar) PUBLICAR="${2:?Falta el registro (p. ej. ghcr.io/usuario)}"; PUBLICAR="${PUBLICAR%/}"; shift 2 ;;
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

# Dónde está el clúster: Docker Desktop y kind ven las imágenes de este equipo (kind, copiándoselas);
# cualquier otro (la nube) solo puede descargarlas de un registro
CONTEXTO=$(kubectl config current-context)
KIND_CLUSTER=""; LOCAL=no
case "$CONTEXTO" in
  kind-*)         KIND_CLUSTER=${CONTEXTO#kind-}; LOCAL=si ;;
  docker-desktop) LOCAL=si ;;
esac

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
# ¿Solo existe en este equipo? Con --jar, siempre (se acaba de construir). Con --imagen, si Docker
# la tiene aquí pero su registro no (se le pregunta al registro: docker manifest inspect).
SOLO_LOCAL=no
if [ -n "$JAR" ]; then
  SOLO_LOCAL=si
elif docker image inspect "$IMAGEN" >/dev/null 2>&1 &&
     ! docker manifest inspect --insecure "$IMAGEN" >/dev/null 2>&1; then
  SOLO_LOCAL=si
fi
if [ "$SOLO_LOCAL" = si ]; then
  # Construida en este equipo
  POLITICA=IfNotPresent
  if [ -n "$PUBLICAR" ]; then
    # Se sube a un registro con una etiqueta única (fecha y hora): el clúster la descarga de ahí
    NOMBRE=${IMAGEN##*/}; NOMBRE=${NOMBRE%%:*}
    DESTINO="$PUBLICAR/$NOMBRE:$(date +%Y%m%d-%H%M%S)"
    echo "   publicándola en $DESTINO..."
    docker tag "$IMAGEN" "$DESTINO"
    if ! docker push -q "$DESTINO" >/dev/null; then
      echo "No se ha podido subir la imagen a $PUBLICAR."
      echo "¿Has iniciado sesión? docker login ${PUBLICAR%%/*}   (en ghcr.io: tu usuario de GitHub y un"
      echo "token personal con permiso write:packages)"
      exit 1
    fi
    IMAGEN=$DESTINO
  elif [ "$LOCAL" = no ]; then
    echo "La imagen $IMAGEN solo está en este equipo y el clúster '$CONTEXTO' no puede verlo."
    echo "Súbela a un registro añadiendo: --publicar <registro>   (p. ej. --publicar ghcr.io/<usuario>)"
    exit 1
  elif [ -n "$KIND_CLUSTER" ]; then
    # En kind cada nodo tiene su propio almacén de imágenes: hay que copiársela
    command -v kind >/dev/null || { echo "Falta kind en el PATH (winget install Kubernetes.kind)"; exit 1; }
    echo "   copiándola a los nodos de kind..."
    kind load docker-image "$IMAGEN" --name "$KIND_CLUSTER" >/dev/null
  fi
else
  [ -z "$PUBLICAR" ] || echo "   (--publicar no hace falta: la imagen ya está en un registro)"
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
# Registro privado: si existe el Secret con sus credenciales, el clúster lo usa para descargar
if kubectl -n "$NS" get secret registro-objetivo >/dev/null 2>&1; then
  echo "   usando las credenciales del Secret registro-objetivo para descargar la imagen"
  kubectl -n "$NS" patch deploy objetivo --type merge \
    -p '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"registro-objetivo"}]}}}}' >/dev/null
else
  # Si ya no existe, se quita la referencia que pudiera quedar de un despliegue anterior
  kubectl -n "$NS" patch deploy objetivo --type json \
    -p '[{"op":"remove","path":"/spec/template/spec/imagePullSecrets"}]' >/dev/null 2>&1 || true
fi
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
