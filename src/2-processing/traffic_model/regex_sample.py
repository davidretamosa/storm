"""Genera un texto que cumple una expresión regular (para los @Pattern de los DTO).

Se apoya en el analizador de expresiones regulares de Python: lee la expresión como un árbol
(literales, clases de caracteres, repeticiones...) y construye un texto que encaja.
Si la expresión usa algo que Python no entiende (p. ej. \\p{Alpha} de Java) devuelve None.
"""
import re

try:
    from re import _parser as sre_parse          # Python 3.11 o más
    from re import _constants as sre_constants
except ImportError:                              # Python 3.10 o menos
    import sre_parse
    import sre_constants

OPS = sre_constants


def _in_set(items, rep):
    """Un carácter de una clase [..]: el primero que sirva."""
    if items and items[0][0] == OPS.NEGATE:
        banned = set()
        for op, value in items[1:]:
            if op == OPS.LITERAL:
                banned.add(chr(value))
            elif op == OPS.RANGE:
                banned.update(chr(c) for c in range(value[0], value[1] + 1))
        for candidate in "a1Z_-x":
            if candidate not in banned:
                return candidate
        return "a"
    for op, value in items:
        if op == OPS.LITERAL:
            return chr(value)
        if op == OPS.RANGE:
            return chr(value[0])
        if op == OPS.CATEGORY:
            return _category(value)
    return "a"


def _category(value):
    name = str(value)
    if "NOT_DIGIT" in name or "NOT_SPACE" in name:
        return "a"
    if "NOT_WORD" in name:
        return "-"
    if "DIGIT" in name:
        return "1"
    if "SPACE" in name:
        return " "
    return "a"


def _build(tree, rep, groups):
    out = []
    for op, value in tree:
        if op == OPS.LITERAL:
            out.append(chr(value))
        elif op == OPS.NOT_LITERAL:
            out.append("a" if chr(value) != "a" else "b")
        elif op == OPS.ANY:
            out.append("a")
        elif op == OPS.IN:
            out.append(_in_set(value, rep))
        elif op == OPS.CATEGORY:
            out.append(_category(value))
        elif op == OPS.BRANCH:
            out.append(_build(value[1][0], rep, groups))
        elif op == OPS.SUBPATTERN:
            text = _build(value[-1], rep, groups)
            if value[0]:
                groups[value[0]] = text
            out.append(text)
        elif op in (OPS.MAX_REPEAT, OPS.MIN_REPEAT):
            low, high, sub = value
            high = rep if high == OPS.MAXREPEAT else high
            count = max(low, min(high, rep))
            out.append("".join(_build(sub, rep, groups) for _ in range(count)))
        elif op == OPS.GROUPREF:
            out.append(groups.get(value, ""))
        # AT (^, $, \b) y ASSERT (mirar adelante/atrás) no escriben nada
    return "".join(out)


def sample(pattern, min_len=0, max_len=None):
    """Un texto que cumple `pattern` y, si se puede, mide entre min_len y max_len. None si no hay forma."""
    try:
        tree = sre_parse.parse(pattern)
        compiled = re.compile(pattern)
    except (re.error, ValueError, RecursionError, OverflowError):
        return None
    fallback = None
    for rep in sorted({1, 2, 3, 5, 10, 20, max(1, min_len)}):
        try:
            text = _build(tree, rep, {})
        except (KeyError, IndexError, TypeError, ValueError):
            return None
        if not compiled.fullmatch(text):
            continue
        fallback = fallback if fallback is not None else text
        if len(text) >= min_len and (max_len is None or len(text) <= max_len):
            return text
    return fallback
