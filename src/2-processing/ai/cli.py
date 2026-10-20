"""`python -m ai [--ai-traffic] [--ai-groups] [--ai-bodies] [--ai-augment] [--ai-seed N] <arguments de main.py>`

Llegeix només les opcions --ai-*; la resta va tal qual a main.main() dels companys.

- Cap millora activa: es crida main.main() sense instal·lar res (identitat per construcció).
- Alguna millora activa: es comprova ai/UPSTREAM.lock, s'instal·len les capes, es crida main.main(),
  es comprova que les capes s'han cridat (si no, s'esborra el .jmx i falla) i el .jmx passa pel
  post-procés (ai/jmx_post.py).
- --ai-noop: totes les capes en mode identitat, sense post-procés (ha de donar el mateix .jmx).
- --ai-canary: un canvi petit i conegut (ai/enhancements/canary.py).
"""
import argparse
import sys
from pathlib import Path

import main as upstream
from ai import jmx_post
from ai import upstream as lock
from ai.enhancements import CANARY, ENHANCEMENTS
from ai.enhancements.base import Context
from ai.hooks import WRAPPABLE, HookError, Installation


def build_parser():
    # allow_abbrev=False: "--ai" o "--ai-t" no es poden confondre amb res; add_help=False: -h és de main.py
    parser = argparse.ArgumentParser(prog="python -m ai", allow_abbrev=False, add_help=False)
    for name, enhancement in ENHANCEMENTS.items():
        parser.add_argument(enhancement.flag, dest=name, action="store_true",
                            help=f"activa la millora '{name}' ({enhancement.phase})")
    parser.add_argument("--ai-seed", type=int, default=0, help="llavor de les millores (per defecte 0)")
    parser.add_argument("--ai-noop", action="store_true", help="instal·la totes les capes en mode identitat")
    parser.add_argument("--ai-canary", action="store_true", help="canvi petit i conegut per provar la xarxa")
    return parser


def call_upstream(argv):
    """main.main() dels companys amb `argv` com a línia d'ordres (com fa tests/test_main.py)."""
    saved = sys.argv
    sys.argv = ["main.py", *argv]
    try:
        upstream.main()
    finally:
        sys.argv = saved


def plan_layers(opts):
    """(capes per funció, editors del .jmx) segons les opcions."""
    ctx = Context(seed=opts.ai_seed)
    active = [enhancement(ctx) for name, enhancement in ENHANCEMENTS.items() if getattr(opts, name)]
    if opts.ai_canary:
        active.append(CANARY(ctx))

    layers = {name: [] for name in WRAPPABLE}
    if opts.ai_noop:
        for name in WRAPPABLE:
            layers[name].append(_identity)
    for enhancement in active:
        for name, around in enhancement.wraps().items():
            layers[name].append(around)

    editors = [enhancement.edit_jmx for enhancement in active]
    if active:  # el post-procés només s'aplica si hi ha alguna millora activa
        layers["generate_jmx"].append(jmx_post.wrap_generate_jmx(editors))
    return layers, bool(active)


def _identity(original, *args, **kwargs):
    return original(*args, **kwargs)


def run(argv=None):
    opts, rest = build_parser().parse_known_args(argv)
    layers, any_active = plan_layers(opts)
    if not any_active and not opts.ai_noop:
        call_upstream(rest)
        return None

    # Amb capes actives, el codi dels companys ha de ser aquell sobre el qual s'han validat (ai/UPSTREAM.lock)
    drift = lock.problems()
    if drift:
        raise HookError(f"{drift}: {lock.MESSAGE}")

    installation = Installation(layers)
    with installation:
        call_upstream(rest)
    try:
        installation.check_called()
    except HookError:
        # Un pla generat amb una capa saltada no es pot fer passar per bo: s'esborra
        for bound in installation.called("generate_jmx"):
            Path(bound.arguments["output_path"]).unlink(missing_ok=True)
        raise
    return installation
