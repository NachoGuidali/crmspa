from django.urls import path

from . import api

app_name = 'vouchers_api'

urlpatterns = [
    path('', api.VoucherCrearView.as_view(), name='crear'),
    # `canjear/` va antes que `<codigo>/` para que no se lo coma la ruta del código.
    path('canjear/', api.VoucherCanjearView.as_view(), name='canjear'),
    path('<str:codigo>/', api.VoucherValidarView.as_view(), name='validar'),
    path('<str:codigo>/comprobante/', api.VoucherComprobanteView.as_view(), name='comprobante'),
]
