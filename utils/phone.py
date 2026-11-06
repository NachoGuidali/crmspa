import re


def normalize_ar_phone(phone: str) -> str:
    """
    Normaliza un celular argentino a +549XXXXXXXXXX (el formato que usa WhatsApp), para que
    un mismo cliente sea SIEMPRE el mismo contacto, lo cargue el bot (viene con código de país
    desde WhatsApp) o recepción a mano (suele tipear el número local sin código).

    Maneja:
      +54XXXXXXXXXX   → +549XXXXXXXXXX   (falta el 9 de celular)
      549XXXXXXXXXX   → +549XXXXXXXXXX   (falta el +)
      54XXXXXXXXXX    → +549XXXXXXXXXX   (faltan + y 9)
      3815551234      → +5493815551234   (local sin código de país)
      03815551234     → +5493815551234   (con 0 de larga distancia)
      11 5551 2345    → +5491155512345   (con espacios/guiones)

    La suposición "es argentino" solo se aplica a los locales de 10 dígitos (y a los de 11
    que empiezan con 9). Un número de otro país recibe solo la normalización del '+', venga
    con + (+34...), con 00 (0034...) o pelado (34644462625): si no, el código de país se
    confundía con una característica argentina. Valores vacíos se devuelven sin cambios.
    """
    if not phone:
        return phone

    cleaned = re.sub(r'[\s\-\(\).]', '', phone.strip())

    # Prefijo internacional en formato 00 → +
    if cleaned.startswith('00'):
        cleaned = '+' + cleaned[2:]

    # Ya trae '+': respetamos el código de país; solo agregamos el 9 si es +54 sin él.
    if cleaned.startswith('+'):
        if cleaned.startswith('+54'):
            after = cleaned[3:]
            if after and after[0] != '9':
                cleaned = '+549' + after
        return cleaned

    # Sin '+': viene con código de país argentino (54...) explícito
    if cleaned.startswith('54'):
        rest = cleaned[2:]
        if rest and rest[0] != '9':
            rest = '9' + rest
        return '+54' + rest

    # Sin '+' ni código de país: número local. Asumimos Argentina (el negocio es argentino),
    # pero SOLO si tiene la forma de un local argentino: 10 dígitos (característica + número).
    # Un número de 11 dígitos sin '+' no es un local argentino, es un extranjero al que le
    # falta el '+': España, EEUU, Chile y Uruguay dan justo 11. Asumirlos argentinos convertía
    # +34644462625 en +54934644462625, un número que no existe — y como el bot le pide al CRM
    # el teléfono en dígitos (lo necesita para armar las URLs), el circuito completo se rompía:
    # la conversación real no se encontraba, se creaba otra con el número inventado y la
    # respuesta se mandaba ahí, así que a la persona no le llegaba nada.
    local = cleaned.lstrip('0')  # quita el 0 de larga distancia nacional
    if local.isdigit():
        if len(local) == 10:
            return '+549' + local
        # Celular argentino con el 9 pero sin el 54 (ej. 91155512345).
        if len(local) == 11 and local.startswith('9'):
            return '+54' + local

    # No parece argentino: se respeta el código de país que trae.
    return '+' + cleaned


def ar_phone_variants(phone: str) -> list:
    """
    Return both +549X and +54X variants of an Argentine number for fuzzy DB lookup.
    """
    variants = [phone]
    if phone.startswith('+549'):
        variants.append('+54' + phone[4:])
    elif phone.startswith('+54') and len(phone) > 3:
        variants.append('+549' + phone[3:])
    return variants
