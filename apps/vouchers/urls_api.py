from django.urls import path

from . import api

app_name = 'vouchers_api'

urlpatterns = [
    path('canjear/', api.VoucherCanjearView.as_view(), name='canjear'),
    path('<str:codigo>/', api.VoucherValidarView.as_view(), name='validar'),
]
