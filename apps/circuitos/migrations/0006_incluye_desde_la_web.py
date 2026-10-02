"""Siembra el "¿Qué incluye?" de cada circuito con lo que hoy está escrito en la web.

A partir de acá la lista se edita en el CRM (Configuración → Circuitos) y la web la lee por la
API pública. Solo completa los circuitos que la tengan vacía: si alguien ya la cargó, no la pisa.
"""
from django.db import migrations

# Las mismas claves que usa web/crm-precios.js para machear la web con el CRM.
LISTAS = {
    'grupal-clasico': (
        'Merienda clásica (dulce y salada)\n'
        'Masaje relajante 25\'\n'
        'Ozonoterapia 25\'\n'
        'Jacuzzi con hidromasaje 40\'\n'
        'Sector de hidratación\n'
        'Infusiones libres (café, té, yogurt y jugos)\n'
        'Living exterior\n'
        'Kit de batas, toallas y toallón\n'
        'Pool y juegos de mesa\n'
        'Quincho climatizado (frío/calor)\n'
        'Acceso a las áreas comunes de la residencia\n'
    ),
    'grupal-premium': (
        'Brunch Premium\n'
        'Picada de campo\n'
        'Opciones dulces y saladas completas\n'
        'Masaje descontracturante 35\'\n'
        'Ozonoterapia\n'
        'Sauna individual 30\'\n'
        'Mascarilla facial de ácido hialurónico\n'
        'Mascarilla de limpieza facial\n'
        'Jacuzzi + tina finlandesa\n'
        'Ensalada de frutas en el jacuzzi\n'
        'Infusiones libres\n'
        'Living exterior y ducha exterior\n'
        'Kit de batas, toallas y toallón\n'
        'Pool y juegos de mesa\n'
        'Quincho climatizado\n'
        'Acceso a las áreas comunes de la residencia\n'
        '1 trago o daikiri por persona\n'
        'Brindis final con champagne\n'
    ),
    'pareja-clasico': (
        'Merienda completa (dulce y salada)\n'
        'Masaje relajante 35\'\n'
        'Ozonoterapia\n'
        'Sauna individual 25\'\n'
        'Jacuzzi para dos\n'
        'Infusiones libres\n'
        'Living exterior\n'
        'Pool y juegos de mesa\n'
        'Ambientación con luces y velas\n'
        'Kit de batas, toallas y toallón\n'
        'Quincho climatizado (frío/calor)\n'
        'Acceso a las áreas comunes de la residencia\n'
        'Brindis final\n'
    ),
    'pareja-premium': (
        'Brunch Premium completo (dulce y salado)\n'
        'Infusiones libres\n'
        'Masaje descontracturante 55-60\'\n'
        'Sillón masajeador Relax\n'
        'Ozonoterapia\n'
        'Sauna individual 30\'\n'
        'Mascarilla hidratante\n'
        'Jacuzzi con sales de baño\n'
        'Mascarilla de limpieza facial\n'
        'Ensalada de frutas\n'
        'Tina finlandesa\n'
        'Sauna seco\n'
        '2 tragos o daikiris\n'
        'Living exterior\n'
        'Pool y juegos de mesa\n'
        'Ambientación con luces y velas\n'
        'Kit de batas, toallas y toallón\n'
        'Quincho climatizado (frío/calor)\n'
        'Acceso a las áreas comunes de la residencia\n'
        'Brindis final\n'
    ),
}


def clave(nombre):
    s = (nombre or '').lower()
    s = (s.replace('á', 'a').replace('é', 'e').replace('í', 'i')
          .replace('ó', 'o').replace('ú', 'u'))
    tipo = 'grupal' if 'grupal' in s else ('pareja' if 'pareja' in s else '')
    tier = 'premium' if 'premium' in s else ('clasico' if 'clasico' in s else '')
    return f'{tipo}-{tier}'


def sembrar(apps, schema_editor):
    Circuito = apps.get_model('circuitos', 'Circuito')
    for c in Circuito.objects.all():
        if c.incluye.strip():
            continue
        texto = LISTAS.get(clave(c.nombre))
        if texto:
            c.incluye = texto
            c.save(update_fields=['incluye'])


def vaciar(apps, schema_editor):
    Circuito = apps.get_model('circuitos', 'Circuito')
    for c in Circuito.objects.all():
        if c.incluye in LISTAS.values():
            c.incluye = ''
            c.save(update_fields=['incluye'])


class Migration(migrations.Migration):

    dependencies = [('circuitos', '0005_circuito_incluye')]

    operations = [migrations.RunPython(sembrar, vaciar)]
