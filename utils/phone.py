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

    Números claramente de otro país (+1..., +55..., 0055...) reciben solo normalización
    básica del +. Valores vacíos se devuelven sin cambios.
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

    # Sin '+' ni código de país: número local. Asumimos Argentina (el negocio es argentino).
    local = cleaned.lstrip('0')  # quita el 0 de larga distancia nacional
    if local.isdigit() and 10 <= len(local) <= 11:
        return '+549' + local

    # No parece un número argentino reconocible: normalización básica.
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
