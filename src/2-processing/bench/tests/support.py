"""Dades i ajudes comunes dels tests del banc. S'executen des de src/2-processing: `pytest bench/tests`."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # src/2-processing

LOG = "samples/access_sample.log"
JAR = "samples/demo-bankapp.jar"
BANKAPP = "../1-input/java-app-mock/logs/bankapp.jsonl"   # el log de la bankapp

# Les 5 entrades de la prova en negatiu: arguments de main.py, amb camins relatius a src/2-processing
INPUTS = {
    "logs": ["--logs", LOG],
    "jar": ["--jar", JAR],
    "logs+jar": ["--logs", LOG, "--jar", JAR],
    "logs+jar+session": ["--logs", LOG, "--jar", JAR, "--session", "--session-users", "1,2,3"],
    "bankapp+session": ["--logs", BANKAPP, "--session"],
}


def generate(args, output):
    """`python main.py <args> --output <output>` en un subprocés amb PYTHONHASHSEED=0 (markov.py recorre un
    set: sense la llavor fixada abans d'arrencar l'intèrpret, el pla canvia d'una execució a l'altra)."""
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    command = [sys.executable, "main.py", *args, "--output", str(output)]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return Path(output)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
