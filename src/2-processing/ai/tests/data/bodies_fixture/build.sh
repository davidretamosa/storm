#!/bin/sh
# Torna a compilar el .jar del fixture (cal un JDK). Des d'aquesta carpeta: ./build.sh
set -e
cd "$(dirname "$0")"
rm -rf classes
javac --release 17 -d classes $(find src -name '*.java')
rm -f ../bodies_fixture.jar
jar cf ../bodies_fixture.jar -C classes .
rm -rf classes
