"""ai/UPSTREAM.lock: l'empremta (SHA-256) dels fitxers dels companys sobre els quals s'han validat els embolcalls.

Si algun canvia, desapareix o n'apareix un de nou als directoris de codi, la capa s'ha de revalidar:
    python -m ai.upstream            # comprova (surt amb error si no quadra)
    python -m ai.upstream --write    # torna a escriure el lock, NOMÉS després de revalidar
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # src/2-processing
LOCK = Path(__file__).resolve().parent / "UPSTREAM.lock"
MESSAGE = "revalida els embolcalls i actualitza el lock"

# On un fitxer de codi nou dels companys podria canviar la cadena
CODE_DIRS = ["log_parser", "jar_parser", "traffic_model", "jmx_generator", "tools"]
CODE_SUFFIXES = {".py", ".groovy", ".j2"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_lock(lock=LOCK):
    """{camí relatiu: sha256}; les línies que comencen per # són comentaris."""
    entries = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, path = line.split(maxsplit=1)
            entries[path] = digest
    return entries


def code_files(root=ROOT):
    found = {"main.py"} if (root / "main.py").exists() else set()
    for directory in CODE_DIRS:
        for path in (root / directory).rglob("*"):
            if path.suffix in CODE_SUFFIXES and "__pycache__" not in path.parts:
                found.add(path.relative_to(root).as_posix())
    return found


def problems(root=ROOT, lock=LOCK):
    """Llista de diferències entre el lock i el que hi ha ara (buida = tot quadra)."""
    entries = read_lock(lock)
    found = []
    for path, digest in sorted(entries.items()):
        file = root / path
        if not file.exists():
            found.append(f"ha desaparegut: {path}")
        elif sha256(file) != digest:
            found.append(f"ha canviat: {path}")
    for path in sorted(code_files(root) - set(entries)):
        found.append(f"fitxer de codi nou: {path}")
    return found


def write_lock(paths, root=ROOT, lock=LOCK, base="?"):
    lines = [f"# Fitxers dels companys (src/2-processing) a {base}. Es regenera amb: python -m ai.upstream --write",
             "# NOMÉS després de revalidar els embolcalls (ai/tests/test_ai_contract.py i test_ai_identity.py)."]
    lines += [f"{sha256(root / path)}  {path}" for path in sorted(paths)]
    lock.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv):
    if "--write" in argv:
        base = argv[argv.index("--base") + 1] if "--base" in argv else "?"
        paths = set(read_lock()) | code_files() if LOCK.exists() else code_files()
        write_lock(sorted(p for p in paths if (ROOT / p).exists()), base=base)
        print(f"Escrit {LOCK}")
        return 0
    found = problems()
    for problem in found:
        print(problem)
    if found:
        print(MESSAGE)
        return 1
    print("UPSTREAM.lock quadra")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
