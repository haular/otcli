class DotDict(dict):
    """
    Una clase de diccionario que permite el acceso a sus claves
    mediante notación de punto (ej: mi_dict.mi_clave).

    Hereda de 'dict', por lo que mantiene todos los métodos
    originales de un diccionario (.keys(), .items(), etc.).
    """

    def __init__(self, *args, **kwargs):
        """
        Constructor. Procesa los datos iniciales para convertir
        diccionarios anidados en DotDicts también.
        """
        super().__init__(*args, **kwargs)
        for key, value in self.items():
            if isinstance(value, dict):
                self[key] = DotDict(value)

    def __getattr__(self, name):
        """
        Se ejecuta cuando se intenta acceder a un atributo que no existe
        (ej: mi_dict.clave_inexistente). Lo usamos para buscar en las claves.
        """
        try:
            # Intenta devolver el valor de la clave del diccionario
            return self[name]
        except KeyError:
            # Si la clave no existe, lanza un AttributeError,
            # que es el comportamiento esperado para atributos.
            raise AttributeError(f"El objeto 'DotDict' no tiene el atributo o clave '{name}'")

    def __setattr__(self, name, value):
        """
        Se ejecuta cuando se asigna un valor a un atributo (ej: mi_dict.clave = 'valor').
        Lo usamos para establecer el valor en el diccionario.
        """
        # Si el valor que se asigna es un diccionario, lo convertimos a DotDict
        if isinstance(value, dict):
            value = DotDict(value)
        # Asigna el valor a la clave correspondiente en el diccionario
        self[name] = value

    def __delattr__(self, name):
        """
        Se ejecuta cuando se elimina un atributo (ej: del mi_dict.clave).
        """
        try:
            del self[name]
        except KeyError:
            raise AttributeError(f"El objeto 'DotDict' no tiene el atributo o clave '{name}'")

    def update(self, *args, **kwargs):
        """
        Sobrescribe el método update() para asegurar que los diccionarios
        anidados que se añadan también se conviertan en DotDict.
        """
        # El método dict.update() puede recibir argumentos posicionales (un dict)
        # y/o argumentos de palabra clave (key=value).
        # Los procesamos para tener un solo diccionario con el que trabajar.
        datos_para_actualizar = dict(*args, **kwargs)

        for key, value in datos_para_actualizar.items():
            # Si un valor es un diccionario, lo convertimos a DotDict
            # antes de pasarlo al update original. La recursión
            # se maneja automáticamente en el __init__ de DotDict.
            if isinstance(value, dict):
                self[key] = DotDict(value)
            else:
                self[key] = value

    def to_dict(self):
        """
        Convierte recursivamente el DotDict y todos los DotDicts anidados
        de nuevo a diccionarios estándar de Python.
        """
        result = {}
        for key, value in self.items():
            if isinstance(value, DotDict):
                result[key] = value.to_dict()
            else:
                result[key] = value
        return result
