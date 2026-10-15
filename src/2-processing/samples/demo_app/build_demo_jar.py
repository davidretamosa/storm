"""SOLO PARA PRUEBAS: compila la app de prueba (demo_app/src) y genera samples/demo-bankapp.jar.

El .jar ya está en el repo; este script solo hace falta si se cambia el código Java de demo_app.
Necesita el JDK (javac) e internet la primera vez (descarga las anotaciones de Spring de Maven Central).

Uso (desde src/2-processing):
    python samples/demo_app/build_demo_jar.py
"""
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
SOURCES = HERE / "src"
LIBS = HERE / ".libs"  # ignorada por git
OUTPUT = HERE.parent / "demo-bankapp.jar"

# Solo se necesitan para compilar las anotaciones (@RestController, @GetMapping...)
SPRING_VERSION = "6.2.0"
SPRING_JARS = ["spring-web", "spring-context", "spring-core"]
MAVEN_URL = "https://repo1.maven.org/maven2/org/springframework/{name}/{version}/{name}-{version}.jar"


def download_spring():
    LIBS.mkdir(exist_ok=True)
    jars = []
    for name in SPRING_JARS:
        jar = LIBS / f"{name}-{SPRING_VERSION}.jar"
        if not jar.exists():
            print(f"Descargando {jar.name}...")
            urllib.request.urlretrieve(MAVEN_URL.format(name=name, version=SPRING_VERSION), jar)
        jars.append(jar)
    return jars


def main():
    jars = download_spring()
    java_files = sorted(str(p) for p in SOURCES.rglob("*.java"))

    with tempfile.TemporaryDirectory() as build:
        classpath = ";".join(str(j) for j in jars)  # ';' en Windows
        subprocess.run(["javac", "--release", "17", "-cp", classpath, "-d", build, *java_files], check=True)

        # Misma estructura que el .jar de Spring Boot: las clases van en BOOT-INF/classes/
        with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as jar:
            jar.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nCreated-By: STORM demo_app\n")
            for class_file in sorted(Path(build).rglob("*.class")):
                jar.write(class_file, "BOOT-INF/classes/" + class_file.relative_to(build).as_posix())

    print(f"Generado {OUTPUT}")


if __name__ == "__main__":
    main()
