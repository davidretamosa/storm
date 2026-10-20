"""Les millores de la capa d'IA. Cadascuna és una opció de `python -m ai` i es pot activar per separat.

Una millora pot fer dues coses, totes dues opcionals:
  - wraps(ctx):    {nom de funció de main: around(original, *args, **kwargs)}, capes sobre la cadena;
  - edit_jmx(ctx, root): canvis sobre l'XML del .jmx ja generat (només elements estàndard de JMeter).

L'ordre d'aquesta llista és l'ordre de les capes: la primera queda més a prop de la funció original.
"""
from ai.enhancements import augment, bodies, canary, groups, traffic

# Les quatre millores del programa 1 (D-4): ordre de construcció T-1 -> T-4
ENHANCEMENTS = {
    "traffic": traffic.Enhancement,
    "groups": groups.Enhancement,
    "bodies": bodies.Enhancement,
    "augment": augment.Enhancement,
}

# Només per provar la xarxa de seguretat (no és cap millora)
CANARY = canary.Enhancement
