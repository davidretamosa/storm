"""Trànsit habitual (T-1, --ai-traffic): el dia normal de l'app, a partir de status, duration_ms i les hores.

Capes sobre la cadena dels companys (cap fitxer seu tocat):
- parse_logs:            identitat; es queda el log sencer per a les dades del laboratori;
- build_think_times:     les pauses, sense el temps de resposta de la petició d'abans (traffic_stats.net_pauses);
- build_path_params:     els {id} de la ruta, només de les peticions que van anar bé (traffic_stats.successful);
- predict_traffic_scale: el resultat de l'original, intacte (vusers no canvia); amb el mateix log, la corba;
- generate_jmx:          després de generar el pla, <output>.ai.json al costat (durades i errors per endpoint).

Al .jmx: el temporitzador de la corba horària, APAGAT per defecte (-Jcurva_horaria=1 l'encén).
No es talla cap sessió: la de l'app mana (Addenda 1 de l'encàrrec T-1).
"""
import inspect
import json
from pathlib import Path

from ai.enhancements import traffic_curve, traffic_stats
from ai.enhancements.base import Enhancement as Base


def side_file(output_path):
    """output/plan.jmx -> output/plan.jmx.ai.json"""
    return Path(f"{output_path}.ai.json")


def _change_argument(name, change):
    """Capa que crida l'original amb l'argument `name` passat per `change` (la resta, tal qual)."""
    def around(original, *args, **kwargs):
        bound = inspect.signature(original).bind(*args, **kwargs)
        bound.arguments[name] = change(bound.arguments[name])
        return original(*bound.args, **bound.kwargs)
    return around


def _argument(original, args, kwargs, name):
    return inspect.signature(original).bind(*args, **kwargs).arguments[name]


class Enhancement(Base):
    name = "traffic"
    flag = "--ai-traffic"
    phase = "T-1"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.log = None     # el log sencer, tal com surt de parse_logs
        self.curve = None   # traffic_curve.concurrency_curve, si el log té sessions
        self.side_path = None

    def wraps(self):
        return {
            "parse_logs": self._keep_log,
            "build_think_times": _change_argument("df", traffic_stats.net_pauses),
            "build_path_params": _change_argument("df", traffic_stats.successful),
            "predict_traffic_scale": self._scale_and_curve,
            "generate_jmx": self._write_side_file,
        }

    def _keep_log(self, original, *args, **kwargs):
        self.log = original(*args, **kwargs)
        return self.log

    def _scale_and_curve(self, original, *args, **kwargs):
        profile = original(*args, **kwargs)
        self.curve = traffic_curve.concurrency_curve(_argument(original, args, kwargs, "df"))
        self.ctx.shared["traffic"] = {"curve": self.curve}
        return profile

    def _write_side_file(self, original, *args, **kwargs):
        result = original(*args, **kwargs)
        data = {
            "enhancement": f"{self.flag} ({self.phase})",
            "curve_property": f"-J{traffic_curve.PROPERTY}=1",
            "curve": self.curve,
            "reference_durations": traffic_stats.reference_durations(self.log),
            "error_rates": traffic_stats.error_rates(self.log),
        }
        self.side_path = side_file(_argument(original, args, kwargs, "output_path"))
        self.side_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return result

    def edit_jmx(self, root):
        if self.curve is None:
            return
        try:
            traffic_curve.add_timer(root, self.curve)
        except ValueError:
            # el .ai.json diria que la corba s'encén amb -Jcurva_horaria=1, i el pla no la porta
            if self.side_path is not None:
                self.side_path.unlink(missing_ok=True)
            raise
