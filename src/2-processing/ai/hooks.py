"""Embolcalls sobre les funcions que main.py importa (el punt d'endoll de la capa d'IA).

main.py fa `from traffic_model.markov import build_markov_model` i, dins de main(),
crida `build_markov_model(...)`: el nom es busca al mòdul `main` en el moment de la crida.
Si substituïm `main.build_markov_model` per un embolcall abans de cridar main.main(),
la cadena dels companys fa servir el nostre embolcall sense tocar-ne ni una línia.

    with Installation(capes):      # posa els embolcalls
        main.main()                # la cadena dels companys, tal qual
    instal·lació.check_called()    # cada embolcall actiu s'ha cridat?

En sortir del `with` es restauren sempre les funcions originals.
"""
import functools
import inspect

import main as upstream

# Les funcions que main.main() crida, en l'ordre en què les crida (vegeu ai/tests/test_ai_contract.py)
WRAPPABLE = (
    "parse_logs",
    "parse_jar",
    "compare_with_logs",
    "build_session_config",
    "remove_session_requests",
    "build_markov_model",
    "build_think_times",
    "add_default_pauses",
    "build_path_params",
    "build_body_models",
    "predict_traffic_scale",
    "build_correlation",
    "generate_jmx",
)

# Les que main.main() crida sempre que acaba bé, sigui quina sigui l'entrada
ALWAYS_CALLED = WRAPPABLE[5:]

REVALIDATE = "revalida els embolcalls de la capa d'IA (ai/hooks.py) contra main.py"


class HookError(RuntimeError):
    """La cadena dels companys ja no és com la capa d'IA espera: millor fallar que fer veure que funciona."""


def _layer(inner, around):
    """Una capa: around(original, *args, **kwargs) rep la funció de sota i decideix què en fa."""
    @functools.wraps(inner)
    def wrapper(*args, **kwargs):
        return around(inner, *args, **kwargs)
    return wrapper


class Installation:
    """Instal·la capes sobre main.<funció> i registra cada crida.

    layers: {nom de funció: [around, ...]}; la primera de la llista és la més propera a l'original.
    Quan hi ha alguna instal·lació, totes les funcions de WRAPPABLE porten un registrador (identitat)
    per poder comprovar, en acabar, quines s'han cridat i amb quins arguments.
    """

    def __init__(self, layers=None):
        self.layers = {name: list(arounds) for name, arounds in (layers or {}).items() if arounds}
        unknown = set(self.layers) - set(WRAPPABLE)
        if unknown:
            raise HookError(f"no es pot embolcallar {sorted(unknown)}: no és a WRAPPABLE")
        self.calls = []        # [(nom, BoundArguments)] en l'ordre de crida
        self._originals = {}

    def __enter__(self):
        for name in WRAPPABLE:
            original = getattr(upstream, name, None)
            if original is None or not callable(original):
                raise HookError(f"main.{name} no existeix: {REVALIDATE} i actualitza ai/UPSTREAM.lock")
            if getattr(original, "_storm_ai_hook", False):
                raise HookError(f"main.{name} ja està embolcallada: dues instal·lacions alhora")
            self._originals[name] = original
        try:
            for name, original in self._originals.items():
                setattr(upstream, name, self._recorder(name, original))
        except BaseException:
            self._restore()
            raise
        return self

    def __exit__(self, *exc):
        self._restore()
        return False

    def _restore(self):
        for name, original in self._originals.items():
            setattr(upstream, name, original)

    def _recorder(self, name, original):
        signature = inspect.signature(original)
        function = original
        for around in self.layers.get(name, []):
            function = _layer(function, around)

        @functools.wraps(original)
        def recorder(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            self.calls.append((name, bound))
            return function(*args, **kwargs)

        recorder._storm_ai_hook = True
        return recorder

    def called(self, name):
        return [bound for called_name, bound in self.calls if called_name == name]

    def expected_calls(self):
        """Quines funcions havia de cridar main.main() en aquesta execució, deduït del que ha passat:

        - parse_logs, si hi havia logs (el df que arriba a build_think_times no és None);
        - parse_jar, si hi havia .jar (els endpoints que arriben a build_markov_model no són None);
        - compare_with_logs, si hi havia les dues coses;
        - build_session_config i remove_session_requests, si el pla porta inici de sessió;
        - la resta, sempre.
        """
        expected = set(ALWAYS_CALLED)
        think = self.called("build_think_times")
        markov = self.called("build_markov_model")
        jmx = self.called("generate_jmx")
        has_logs = bool(think) and think[0].arguments["df"] is not None
        has_jar = bool(markov) and markov[0].arguments["endpoints"] is not None
        if has_logs:
            expected.add("parse_logs")
        if has_jar:
            expected.add("parse_jar")
        if has_logs and has_jar:
            expected.add("compare_with_logs")
        if jmx and jmx[0].arguments["session"] is not None:
            expected |= {"build_session_config", "remove_session_requests"}
        return expected

    def check_called(self):
        """Cada embolcall actiu que tocava cridar s'ha cridat almenys una vegada.

        Si no, vol dir que main.py ja no passa per aquella funció i la millora no faria res sense avisar.
        """
        expected = self.expected_calls()
        missing = [name for name in WRAPPABLE
                   if name in self.layers and name in expected and not self.called(name)]
        if missing:
            raise HookError(f"embolcalls actius que main.main() no ha cridat: {missing}. {REVALIDATE}")
