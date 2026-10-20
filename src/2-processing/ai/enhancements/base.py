"""Forma comuna de les millores."""
import sys


class Context:
    """El que totes les millores comparteixen en una execució."""

    def __init__(self, seed=0):
        self.seed = seed


class Enhancement:
    name = ""
    flag = ""
    phase = ""  # el taller que la construirà

    def __init__(self, ctx):
        self.ctx = ctx

    def wraps(self):
        return {}

    def edit_jmx(self, root):
        pass


class Placeholder(Enhancement):
    """Millora que encara no fa res: existeix l'opció, el contingut el posa el seu taller."""

    def __init__(self, ctx):
        super().__init__(ctx)
        print(f"[ai] {self.flag}: encara no fa res (és feina del {self.phase})", file=sys.stderr)
