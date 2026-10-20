import sys
from pathlib import Path

# Perquè `import main` trobi el main.py dels companys encara que no s'arrenqui des de src/2-processing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.cli import run  # noqa: E402

run()
