"""Ajudes per llegir, tocar i escriure un .jmx (elements estàndard de JMeter 5.6.3).

El banc només les fa servir per fer-ne una còpia instrumentada (run.instrument): el pla de main.py no es
toca mai. Llegir i tornar a escriure l'XML canvia la forma (cometes, etiquetes buides, escapament) però no
el contingut.
"""
import xml.etree.ElementTree as ET


def read(path):
    return ET.parse(path)


def write(tree, path):
    tree.write(path, encoding="UTF-8", xml_declaration=True)


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
