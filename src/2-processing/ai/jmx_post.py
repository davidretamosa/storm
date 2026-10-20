"""Post-procés del .jmx: les millores hi poden afegir o canviar elements estàndard de JMeter 5.6.3.

Només s'aplica si hi ha alguna millora activa (amb tot desactivat, el .jmx no es torna a escriure i
és byte a byte el dels companys). Llegir i tornar a escriure l'XML canvia la forma (cometes, etiquetes
buides, escapament) però no el contingut: un cop canonicalitzat (C14N) surt idèntic.
"""
import inspect
import xml.etree.ElementTree as ET
from pathlib import Path


def read(path):
    return ET.parse(path)


def write(tree, path):
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def canonical(path_or_text):
    """Forma canònica (C14N 2.0) d'un .jmx, per comparar contingut sense mirar la forma."""
    text = Path(path_or_text).read_text(encoding="utf-8") if isinstance(path_or_text, Path) else path_or_text
    if text.startswith("<?xml"):
        text = text[text.index("?>") + 2:]
    return ET.canonicalize(xml_data=text)


def post_process(path, editors):
    """Aplica cada editor(root) sobre el .jmx de `path` i el torna a escriure."""
    tree = read(path)
    for edit in editors:
        edit(tree.getroot())
    write(tree, path)


def wrap_generate_jmx(editors):
    """Capa per a main.generate_jmx: genera el pla com sempre i després hi passa els editors."""
    def around(original, *args, **kwargs):
        result = original(*args, **kwargs)
        post_process(_output_path(original, args, kwargs), editors)
        return result
    return around


def _output_path(original, args, kwargs):
    bound = inspect.signature(original).bind(*args, **kwargs)
    return bound.arguments["output_path"]


# --- Ajudes per als editors ---------------------------------------------------------------------

def child_tree(root, element):
    """El <hashTree> que va just després d'un element (on viuen els seus fills, en format .jmx)."""
    parent = parent_of(root, element)
    siblings = list(parent)
    index = siblings.index(element)
    following = siblings[index + 1] if index + 1 < len(siblings) else None
    if following is None or following.tag != "hashTree":
        raise ValueError(f"{element.tag} no té el seu <hashTree> al darrere")
    return following


def parent_of(root, element):
    for parent in root.iter():
        for child in parent:
            if child is element:
                return parent
    raise ValueError(f"{element.tag} no és dins del pla")


def string_prop(name, value):
    prop = ET.Element("stringProp", {"name": name})
    prop.text = value
    return prop
