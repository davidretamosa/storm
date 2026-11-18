#!/bin/sh
# Vuelve a compilar el .jar de prueba (hace falta un JDK). Desde esta carpeta: sh build.sh
# Compila en una carpeta temporal nueva y no borra nada: jar cf sobrescribe ../bodies_fixture.jar.
set -e
cd "$(dirname "$0")"
classes="$(mktemp -d "${TMPDIR:-/tmp}/bodies_fixture.XXXXXX")"
javac --release 17 -d "$classes" $(find src -name '*.java' | sort)
jar cf ../bodies_fixture.jar -C "$classes" .
echo "Hecho: ../bodies_fixture.jar (clases compiladas en $classes)"
