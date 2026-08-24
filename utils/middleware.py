"""Middleware propio del CRM."""


class NoIndexMiddleware:
    """Marca TODA respuesta del CRM como no indexable (`X-Robots-Tag: noindex, nofollow`).

    El CRM vive en crm.spacuatroestaciones.com, un subdominio público: sin esto, Google puede
    indexar la pantalla de login y mostrarla en los resultados junto a la web del spa. Feo para
    la marca y sin ningún beneficio.

    Va por header y no por robots.txt a propósito, por el mismo motivo que las páginas legales
    de la web: `Disallow` impide que Google *lea* la página, y entonces nunca se entera del
    noindex — puede llegar a listar la URL igual, sin descripción, si alguien la enlaza. El
    header lo ve sí o sí en cada respuesta, así que es lo que garantiza que quede afuera.

    Aplica a todo, incluidos los endpoints públicos (`/api/v1/publico/...`): son JSON para la
    web, no páginas para buscar.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response
