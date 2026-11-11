"""Dibuja el voucher de regalo: una imagen PNG y el mismo diseño en PDF.

Se dibuja con Pillow, que ya estaba en el proyecto, y no con HTML a PDF: así no entra ninguna
dependencia nueva (ni librerías de sistema en la imagen de Docker) y el PNG sale del mismo
render, que es el formato que importa — el voucher se manda por WhatsApp, y ahí una imagen se
ve en el chat mientras un PDF hay que abrirlo.

La paleta y las tipografías son las del sitio público (`web/index.html`): crema de fondo,
verde noche, naranja y tan, con Bodoni Moda en los títulos, Montserrat en el cuerpo y Playfair
Display itálica en el mensaje de regalo.
"""
import io
import logging
import unicodedata
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger('apps.vouchers')

# ── Medidas ───────────────────────────────────────────────────────────────────
ANCHO, ALTO = 1200, 1800
MARGEN = 90
PDF_DPI = 200                      # 1200x1800 a 200 dpi = 6 x 9 pulgadas

# ── Paleta (static/css/base.css y web/index.html) ─────────────────────────────
CREMA = '#fdf5ed'
DURAZNO = '#fee8ca'
VERDE_NOCHE = '#252c1a'
VERDE_OLIVA = '#617245'
NARANJA = '#ef8627'
TAN = '#ae8d71'
BLANCO = '#ffffff'

RAIZ = Path(settings.BASE_DIR)
FUENTES = RAIZ / 'static' / 'fonts'
# Las imágenes del voucher viven en `static/voucher/` y no en `web/`: la carpeta de la web
# pública la sirve nginx en el host y está excluida de la imagen de Docker (.dockerignore),
# así que desde el contenedor no existe. Son las mismas fotos del sitio, ya recortadas a la
# franja de arriba y optimizadas.
IMAGENES = RAIZ / 'static' / 'voucher'

# Foto de arriba cuando el circuito no tiene una imagen cargada en el CRM (hoy no la tiene
# ninguno). Si se le carga una al circuito, el voucher usa esa.
FOTOS = {
    'pareja': 'pareja.jpg',
    'grupal': 'grupal.jpg',
    'despedida': 'despedida.jpg',
}
FOTO_POR_DEFECTO = 'general.jpg'


def _sin_tildes(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', str(texto))
                   if unicodedata.category(c) != 'Mn')


def fuente(archivo, tamano, peso=None):
    """Una fuente variable en el peso pedido.

    Si el archivo no está (alguien lo borró, o un deploy sin `static/fonts`), el voucher sale
    con la fuente por defecto de Pillow en vez de reventar: fea, pero sale. Y si la versión de
    FreeType del sistema no soporta fuentes variables, queda el peso Regular del archivo.
    """
    ruta = FUENTES / archivo
    try:
        f = ImageFont.truetype(str(ruta), tamano)
    except OSError:
        logger.warning('Falta la tipografía %s: el voucher sale con la fuente por defecto', ruta)
        return ImageFont.load_default(tamano)
    if peso:
        try:
            f.set_variation_by_name(peso)
        except (OSError, ValueError):
            pass
    return f


def titulo(tamano, peso='Regular'):
    return fuente('BodoniModa-VF.ttf', tamano, peso)


def cuerpo(tamano, peso='Regular'):
    return fuente('Montserrat-VF.ttf', tamano, peso)


def cursiva(tamano, peso='Italic'):
    return fuente('PlayfairDisplay-Italic-VF.ttf', tamano, peso)


# ── Ayudas de dibujo ──────────────────────────────────────────────────────────

def _ancho(d, texto, font, espaciado=0):
    if not espaciado:
        return d.textlength(texto, font=font)
    return sum(d.textlength(c, font=font) for c in texto) + espaciado * max(len(texto) - 1, 0)


def texto_centrado(d, y, texto, font, color, espaciado=0, centro=None):
    """Escribe centrado horizontalmente y devuelve el alto que ocupó."""
    centro = ANCHO // 2 if centro is None else centro
    ancho = _ancho(d, texto, font, espaciado)
    x = centro - ancho / 2
    if espaciado:
        for c in texto:
            d.text((x, y), c, font=font, fill=color)
            x += d.textlength(c, font=font) + espaciado
    else:
        d.text((x, y), texto, font=font, fill=color)
    return font.size


def partir(d, texto, font, ancho_max, espaciado=0):
    """Corta el texto en líneas que entren en `ancho_max`."""
    lineas, actual = [], ''
    for palabra in str(texto).split():
        prueba = f'{actual} {palabra}'.strip()
        if _ancho(d, prueba, font, espaciado) <= ancho_max or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def bloque_centrado(d, y, texto, font, color, ancho_max, interlinea=1.25, espaciado=0, max_lineas=3):
    lineas = partir(d, texto, font, ancho_max, espaciado)[:max_lineas]
    for linea in lineas:
        texto_centrado(d, y, linea, font, color, espaciado)
        y += int(font.size * interlinea)
    return y


def _foto(circuito):
    """La foto de arriba: la del circuito si tiene, si no una del sitio por tipo de experiencia."""
    if circuito is not None and getattr(circuito, 'imagen', None):
        try:
            return Image.open(circuito.imagen.path).convert('RGB')
        except (OSError, ValueError):
            logger.warning('No se pudo abrir la imagen del circuito %s', circuito.pk)
    nombre = _sin_tildes(getattr(circuito, 'nombre', '')).lower()
    archivo = FOTO_POR_DEFECTO
    for clave, foto in FOTOS.items():
        if clave in nombre or (clave == 'despedida' and 'solter' in nombre):
            archivo = foto
            break
    try:
        return Image.open(IMAGENES / archivo).convert('RGB')
    except OSError:
        logger.warning('No se encontró la foto %s para el voucher', archivo)
        return None


def _recortar(img, ancho, alto):
    """Recorta al centro para llenar la caja sin deformar (como un object-fit: cover)."""
    escala = max(ancho / img.width, alto / img.height)
    nuevo = (max(int(img.width * escala + 0.5), ancho), max(int(img.height * escala + 0.5), alto))
    img = img.resize(nuevo, Image.LANCZOS)
    izq = (img.width - ancho) // 2
    arriba = (img.height - alto) // 2
    return img.crop((izq, arriba, izq + ancho, arriba + alto))


def _velo(alto_foto):
    """Degradado oscuro de abajo hacia arriba, para que el texto se lea sobre la foto."""
    velo = Image.new('L', (1, alto_foto))
    for y in range(alto_foto):
        p = y / max(alto_foto - 1, 1)
        velo.putpixel((0, y), int(235 * max(0.0, (p - 0.35) / 0.65) ** 1.4))
    return velo.resize((ANCHO, alto_foto))


def _logo(img, ancho_max=360):
    for archivo in ('logo-blanco.png',):
        ruta = IMAGENES / archivo
        if not ruta.exists():
            continue
        try:
            logo = Image.open(ruta).convert('RGBA')
        except OSError:
            continue
        escala = min(ancho_max / logo.width, 150 / logo.height)
        logo = logo.resize((int(logo.width * escala), int(logo.height * escala)), Image.LANCZOS)
        img.paste(logo, ((ANCHO - logo.width) // 2, 72), logo)
        return
    logger.warning('No se encontró el logo para el voucher')


def _rombo(d, y, color=NARANJA, lado=9):
    cx = ANCHO // 2
    d.line([(cx - 180, y), (cx - lado - 14, y)], fill=TAN, width=2)
    d.line([(cx + lado + 14, y), (cx + 180, y)], fill=TAN, width=2)
    d.polygon([(cx, y - lado), (cx + lado, y), (cx, y + lado), (cx - lado, y)], fill=color)


def _dato(d, y, etiqueta, valor, x, ancho_max, centrado=False):
    """Un par etiqueta/valor. Centrado cuando es el único (un voucher sin destinatario)."""
    font = titulo(46)
    if centrado:
        texto_centrado(d, y, etiqueta.upper(), cuerpo(23, 'SemiBold'), TAN, espaciado=2)
    else:
        d.text((x, y), etiqueta.upper(), font=cuerpo(23, 'SemiBold'), fill=TAN)
    y += 36
    for linea in partir(d, valor, font, ancho_max)[:2]:
        if centrado:
            texto_centrado(d, y, linea, font, VERDE_NOCHE)
        else:
            d.text((x, y), linea, font=font, fill=VERDE_NOCHE)
        y += 54
    return y


# ── El voucher ────────────────────────────────────────────────────────────────

def dibujar(voucher):
    """Devuelve la imagen del voucher (PIL.Image) lista para guardar."""
    img = Image.new('RGB', (ANCHO, ALTO), CREMA)
    d = ImageDraw.Draw(img)

    # ── Foto de arriba con el logo y el título ──
    alto_foto = 620
    foto = _foto(voucher.circuito)
    if foto is not None:
        recorte = _recortar(foto, ANCHO, alto_foto)
        oscuro = Image.new('RGB', (ANCHO, alto_foto), VERDE_NOCHE)
        img.paste(Image.composite(oscuro, recorte, _velo(alto_foto)), (0, 0))
    else:
        d.rectangle([(0, 0), (ANCHO, alto_foto)], fill=VERDE_NOCHE)
    _logo(img)

    texto_centrado(d, alto_foto - 215, 'VOUCHER DE REGALO', cuerpo(34, 'SemiBold'), CREMA, espaciado=11)
    bloque_centrado(d, alto_foto - 148, voucher.circuito.nombre, titulo(66, 'Medium'), DURAZNO,
                    ANCHO - 2 * MARGEN, interlinea=1.12, max_lineas=2)

    # ── El medio: cantidad, nombres y mensaje ──
    # Se dibuja aparte y después se pega centrado en el espacio que queda entre la foto y la
    # caja del código. Dibujándolo de corrido, un voucher sin mensaje de regalo dejaba un
    # hueco enorme en el medio y otro con mensaje largo se amontonaba contra el código.
    caja_y = ALTO - 460
    medio = Image.new('RGBA', (ANCHO, caja_y - alto_foto), (0, 0, 0, 0))
    dm = ImageDraw.Draw(medio)
    y = 0

    personas = voucher.personas or 1
    detalle = [f'{personas} {"persona" if personas == 1 else "personas"}']
    minutos = getattr(voucher.circuito, 'duracion_minutos', 0) or 0
    if minutos >= 60:
        horas = minutos / 60
        detalle.append(f'{int(horas) if horas.is_integer() else round(horas, 1)} horas')
    texto_centrado(dm, y, ' · '.join(detalle), cuerpo(28, 'Medium'), VERDE_OLIVA, espaciado=3)
    y += 76
    _rombo(dm, y)
    y += 52

    mitad = (ANCHO - 2 * MARGEN) // 2
    if voucher.destinatario_nombre:
        alto_a = _dato(dm, y, 'Para', voucher.destinatario_nombre, MARGEN, mitad - 30)
        alto_b = _dato(dm, y, 'De parte de', voucher.comprador_nombre, MARGEN + mitad + 30, mitad - 30)
        y = max(alto_a, alto_b)
    else:
        y = _dato(dm, y, 'De parte de', voucher.comprador_nombre, MARGEN, ANCHO - 2 * MARGEN,
                  centrado=True)

    if voucher.mensaje_regalo:
        y += 34
        y = bloque_centrado(dm, y, f'“{voucher.mensaje_regalo.strip()}”', cursiva(38), VERDE_OLIVA,
                            ANCHO - 2 * MARGEN - 60, interlinea=1.42, max_lineas=4)

    alto_usado = min(y + 12, medio.height)
    medio = medio.crop((0, 0, ANCHO, alto_usado))
    img.paste(medio, (0, alto_foto + max((caja_y - alto_foto - alto_usado) // 2, 30)), medio)

    # ── El código ──
    caja_alto = 190
    y = caja_y
    d.rounded_rectangle([(MARGEN, y), (ANCHO - MARGEN, y + caja_alto)], radius=18,
                        fill=BLANCO, outline=TAN, width=2)
    texto_centrado(d, y + 34, 'CÓDIGO DEL VOUCHER', cuerpo(22, 'SemiBold'), TAN, espaciado=7)
    texto_centrado(d, y + 86, voucher.codigo, cuerpo(58, 'SemiBold'), VERDE_NOCHE, espaciado=5)
    y += caja_alto + 44

    vence = voucher.fecha_vencimiento.strftime('%d/%m/%Y') if voucher.fecha_vencimiento else ''
    if vence:
        texto_centrado(d, y, f'Válido hasta el {vence}', cuerpo(28, 'Medium'), VERDE_NOCHE)
    y += 46
    texto_centrado(d, y, 'Coordiná tu fecha por WhatsApp antes de venir', cuerpo(24), VERDE_OLIVA)

    # ── Pie ──
    d.rectangle([(0, ALTO - 96), (ANCHO, ALTO)], fill=VERDE_NOCHE)
    texto_centrado(d, ALTO - 62, 'SPACUATRORAICES.COM.AR', cuerpo(26, 'Medium'), DURAZNO, espaciado=6)

    return img


def png(voucher):
    """El voucher en PNG, como bytes."""
    buf = io.BytesIO()
    dibujar(voucher).save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def pdf(voucher, imagen=None):
    """El mismo diseño en PDF, como bytes (una página, sin librerías extra)."""
    buf = io.BytesIO()
    (imagen or dibujar(voucher)).save(buf, 'PDF', resolution=PDF_DPI)
    return buf.getvalue()
