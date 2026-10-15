"""Lectura de un archivo .class de Java (bytecode) sin ejecutarlo.

Un .class es binario y tiene siempre la misma estructura (especificación de la JVM, capítulo 4):

    cabecera | constant pool | nombre de la clase | campos | métodos | atributos

- El "constant pool" es una lista con todos los textos y números de la clase. El resto del
  archivo no repite los textos: guarda su posición en esa lista (p. ej. "el nombre está en la 14").
- Las anotaciones (@RestController, @GetMapping("/{id}")...) se guardan como "atributos"
  de la clase, de cada método y de cada parámetro.

Este módulo solo extrae lo que necesita el jar_parser: nombre de la clase, anotaciones,
campos (con su tipo) y métodos (con sus parámetros y anotaciones).
"""
import struct

# Tipos básicos de Java en los descriptores: "J" = long, "Z" = boolean...
PRIMITIVES = {
    "B": "byte", "C": "char", "D": "double", "F": "float",
    "I": "int", "J": "long", "S": "short", "Z": "boolean", "V": "void",
}
ACC_STATIC = 0x0008


class Reader:
    """Lee números de un bloque de bytes, avanzando la posición (formato big-endian)."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def u1(self):
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u2(self):
        value = struct.unpack_from(">H", self.data, self.pos)[0]
        self.pos += 2
        return value

    def u4(self):
        value = struct.unpack_from(">I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def bytes(self, length):
        value = self.data[self.pos:self.pos + length]
        self.pos += length
        return value


def read_constant_pool(reader):
    """Lista con los textos (Utf8), enteros (Integer) y clases (Class) de la clase.

    El resto de tipos de entrada se saltan (no los necesitamos), pero hay que leerlos
    para saber dónde empieza la siguiente.
    """
    count = reader.u2()
    pool = [None] * count  # la posición 0 no se usa
    i = 1
    while i < count:
        tag = reader.u1()
        if tag == 1:                      # Utf8: un texto
            length = reader.u2()
            pool[i] = reader.bytes(length).decode("utf-8", errors="replace")
        elif tag == 3:                    # Integer
            pool[i] = struct.unpack(">i", reader.bytes(4))[0]
        elif tag == 4:                    # Float
            reader.bytes(4)
        elif tag in (5, 6):               # Long, Double: ocupan dos posiciones
            reader.bytes(8)
            i += 1
        elif tag == 7:                    # Class: posición del texto con su nombre
            pool[i] = ("class", reader.u2())
        elif tag in (8, 16, 19, 20):      # String, MethodType, Module, Package
            reader.u2()
        elif tag in (9, 10, 11, 12, 17, 18):  # referencias a campos/métodos, NameAndType, Dynamic...
            reader.bytes(4)
        elif tag == 15:                   # MethodHandle
            reader.bytes(3)
        else:
            raise ValueError(f"Tipo de constante desconocido: {tag}")
        i += 1
    return pool


def descriptor_to_type(descriptor):
    """'Ljava/math/BigDecimal;' -> 'java.math.BigDecimal' ; 'J' -> 'long' ; '[I' -> 'int[]'."""
    if descriptor.startswith("["):
        return descriptor_to_type(descriptor[1:]) + "[]"
    if descriptor.startswith("L"):
        return descriptor[1:-1].replace("/", ".")
    return PRIMITIVES[descriptor]


def method_parameter_types(descriptor):
    """'(Ljava/lang/Long;Lcom/pae/Dto;)V' -> ['java.lang.Long', 'com.pae.Dto']."""
    params = descriptor[1:descriptor.index(")")]
    types = []
    i = 0
    while i < len(params):
        start = i
        while params[i] == "[":  # arrays: "[" delante del tipo
            i += 1
        if params[i] == "L":     # clase: hasta el ";"
            i = params.index(";", i)
        i += 1
        types.append(descriptor_to_type(params[start:i]))
    return types


def read_element_value(reader, pool):
    """Valor de un elemento de una anotación, p. ej. el "/{id}" de @GetMapping("/{id}")."""
    tag = chr(reader.u1())
    if tag == "s":                        # texto
        return pool[reader.u2()]
    if tag in "BCISZ":                    # entero / booleano
        return pool[reader.u2()]
    if tag in "DFJ":                      # double / float / long (no los necesitamos)
        reader.u2()
        return None
    if tag == "e":                        # enum, p. ej. RequestMethod.GET -> "GET"
        reader.u2()                       # tipo del enum
        return pool[reader.u2()]
    if tag == "c":                        # una clase, p. ej. String.class
        return descriptor_to_type(pool[reader.u2()])
    if tag == "@":                        # una anotación dentro de otra
        return read_annotation(reader, pool)
    if tag == "[":                        # una lista de valores
        return [read_element_value(reader, pool) for _ in range(reader.u2())]
    raise ValueError(f"Tipo de valor de anotación desconocido: {tag}")


def read_annotation(reader, pool):
    """{"type": "org.springframework...GetMapping", "values": {"value": ["/{id}"]}}"""
    annotation_type = descriptor_to_type(pool[reader.u2()])
    values = {}
    for _ in range(reader.u2()):
        name = pool[reader.u2()]
        values[name] = read_element_value(reader, pool)
    return {"type": annotation_type, "values": values}


def read_attributes(reader, pool):
    """Lee los atributos de una clase, campo o método y devuelve solo las anotaciones:

    {"annotations": [...], "param_annotations": [[...], [...], ...]}
    """
    result = {"annotations": [], "param_annotations": []}
    for _ in range(reader.u2()):
        name = pool[reader.u2()]
        length = reader.u4()
        if name == "RuntimeVisibleAnnotations":
            result["annotations"] = [read_annotation(reader, pool) for _ in range(reader.u2())]
        elif name == "RuntimeVisibleParameterAnnotations":
            for _ in range(reader.u1()):  # un grupo de anotaciones por parámetro
                result["param_annotations"].append(
                    [read_annotation(reader, pool) for _ in range(reader.u2())]
                )
        else:
            reader.bytes(length)  # el código del método y demás: no lo necesitamos
    return result


def read_class(data):
    """Lee los bytes de un .class y devuelve:

    {
      "name": "com.pae.bankapp.controller.AccountController",
      "annotations": [{"type": ..., "values": {...}}, ...],
      "fields":  [{"name": "amount", "type": "java.math.BigDecimal", "static": False}, ...],
      "methods": [{"name": "deposit", "params": ["java.lang.Long", "com.pae...DepositRequest"],
                   "annotations": [...], "param_annotations": [[...], [...]]}, ...],
    }
    """
    reader = Reader(data)
    if reader.u4() != 0xCAFEBABE:  # todos los .class empiezan por estos 4 bytes
        raise ValueError("No es un archivo .class")
    reader.u2()  # versión menor
    reader.u2()  # versión mayor
    pool = read_constant_pool(reader)

    reader.u2()  # modificadores de la clase (public, final...)
    this_class = pool[reader.u2()]
    name = pool[this_class[1]].replace("/", ".")
    reader.u2()  # superclase
    for _ in range(reader.u2()):  # interfaces
        reader.u2()

    fields = []
    for _ in range(reader.u2()):
        access = reader.u2()
        field_name = pool[reader.u2()]
        field_type = descriptor_to_type(pool[reader.u2()])
        read_attributes(reader, pool)
        fields.append({"name": field_name, "type": field_type, "static": bool(access & ACC_STATIC)})

    methods = []
    for _ in range(reader.u2()):
        reader.u2()  # modificadores
        method_name = pool[reader.u2()]
        descriptor = pool[reader.u2()]
        attributes = read_attributes(reader, pool)
        methods.append({
            "name": method_name,
            "params": method_parameter_types(descriptor),
            "annotations": attributes["annotations"],
            "param_annotations": attributes["param_annotations"],
        })

    class_annotations = read_attributes(reader, pool)["annotations"]
    return {"name": name, "annotations": class_annotations, "fields": fields, "methods": methods}
