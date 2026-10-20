"""La bankapp d'origin/develop (src/1-input/java-app-mock), NOMÉS per mesurar l'acceptació.

Es treu amb `git archive` a l'espai temporal (mai a storm/ ni al worktree), es compila un cop amb el
Maven wrapper (la primera vegada baixa dependències) i s'arrenca de nou abans de cada execució: la base
de dades és H2 en memòria, i reiniciar-la la deixa com al principi.
"""
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # src/2-processing
SOURCE = "src/1-input/java-app-mock"


def extract(workdir, ref="origin/develop"):
    """git archive <ref> src/1-input/java-app-mock -> workdir/bankapp; torna el directori i el commit."""
    workdir = Path(workdir)
    target = workdir / "bankapp"
    target.mkdir(parents=True, exist_ok=True)
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout.strip()
    commit = subprocess.run(["git", "rev-parse", ref], cwd=top, capture_output=True, text=True,
                            check=True).stdout.strip()
    tar = workdir / "bankapp.tar"
    # Des de l'arrel del repo: des d'un subdirectori, el camí del git archive és relatiu i no troba res
    subprocess.run(["git", "archive", "--format=tar", "-o", str(tar), ref, SOURCE], cwd=top, check=True)
    subprocess.run(["tar", "-xf", str(tar), "-C", str(target), "--strip-components=3"], check=True)
    return target, commit


def build(directory):
    """./mvnw -DskipTests package; torna el .jar."""
    directory = Path(directory)
    (directory / "mvnw").chmod(0o755)
    subprocess.run(["./mvnw", "-q", "-DskipTests", "package"], cwd=directory, check=True)
    jars = sorted((directory / "target").glob("*.jar"))
    if not jars:
        raise RuntimeError(f"no s'ha generat cap .jar a {directory / 'target'}")
    return jars[0]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Bankapp:
    """Una instància nova de la bankapp: `with Bankapp(jar) as app: ... app.port`."""

    def __init__(self, jar, log, port=None, timeout=120):
        self.jar, self.log, self.port, self.timeout = Path(jar), Path(log), port or free_port(), timeout
        self.process = None

    def __enter__(self):
        self._out = open(self.log, "w", encoding="utf-8")
        self.process = subprocess.Popen(["java", "-jar", str(self.jar), f"--server.port={self.port}"],
                                        cwd=self.log.parent, stdout=self._out, stderr=subprocess.STDOUT)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"la bankapp s'ha aturat en arrencar (vegeu {self.log})")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/actuator/health", timeout=2) as r:
                    if r.status == 200:
                        return self
            except OSError:
                time.sleep(1)
        self.__exit__()
        raise RuntimeError(f"la bankapp no ha arrencat en {self.timeout} s (vegeu {self.log})")

    def __exit__(self, *exc):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self._out.close()
        return False
