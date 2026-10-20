"""Dades i ajudes comunes dels tests de la capa d'IA. S'executen des de src/2-processing: `pytest ai/tests`."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # src/2-processing

LOG = "samples/access_sample.log"
JAR = "samples/demo-bankapp.jar"
MARTINA = "samples/martina_bankapp.jsonl"

# Les 5 entrades de la prova d'identitat (encàrrec T-ARQ, punt 3)
INPUTS = {
    "logs": ["--logs", LOG],
    "jar": ["--jar", JAR],
    "logs+jar": ["--logs", LOG, "--jar", JAR],
    "logs+jar+session": ["--logs", LOG, "--jar", JAR, "--session", "--session-users", "1,2,3"],
    "martina+session": ["--logs", MARTINA, "--session"],
}


def generate(entry, args, output):
    """Genera un .jmx en un subprocés amb PYTHONHASHSEED=0 (markov.py recorre un set: sense llavor
    fixada abans d'arrencar l'intèrpret, el pla canvia d'una execució a l'altra)."""
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    command = [sys.executable, *entry, *args, "--output", str(output)]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return Path(output)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


MAIN = ["main.py"]
AI = ["-m", "ai"]
