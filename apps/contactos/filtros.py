"""Filtrado de contactos por campos personalizados (compartido entre la lista y las campañas)."""
from .models import CampoPersonalizado

# Operadores válidos por tipo de campo. (clave, etiqueta)
OPERADORES = {
    CampoPersonalizado.Tipo.TEXTO: [('contiene', 'contiene'), ('eq', 'es igual a')],
    CampoPersonalizado.Tipo.LISTA: [('eq', 'es')],
    CampoPersonalizado.Tipo.BOOLEANO: [('eq', 'es')],
    CampoPersonalizado.Tipo.NUMERO: [('eq', 'igual a'), ('gte', 'mayor o igual a'), ('lte', 'menor o igual a')],
    CampoPersonalizado.Tipo.FECHA: [('eq', 'en fecha'), ('gte', 'desde'), ('lte', 'hasta')],
}


def aplicar_filtro_campo(qs, campo, operador, valor):
    """Filtra un queryset de Contacto por un campo personalizado.
    Devuelve el qs sin cambios si falta algún dato."""
    if not campo or valor in (None, ''):
        return qs

    key = f'datos_extra__{campo.slug}'
    valor_coerced = campo.coerce(valor)
    if valor_coerced is None:
        return qs

    if campo.tipo == CampoPersonalizado.Tipo.TEXTO and operador == 'contiene':
        return qs.filter(**{f'{key}__icontains': valor_coerced})
    if operador == 'gte':
        return qs.filter(**{f'{key}__gte': valor_coerced})
    if operador == 'lte':
        return qs.filter(**{f'{key}__lte': valor_coerced})
    # eq (default)
    return qs.filter(**{key: valor_coerced})
