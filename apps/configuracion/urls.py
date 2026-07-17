from django.urls import path

from . import views

app_name = 'configuracion'


def crud(prefix, name, v):
    return [
        path(f'{prefix}/', v['list'].as_view(), name=f'{name}s'),
        path(f'{prefix}/nuevo/', v['crear'].as_view(), name=f'{name}_crear'),
        path(f'{prefix}/<int:pk>/editar/', v['editar'].as_view(), name=f'{name}_editar'),
        path(f'{prefix}/<int:pk>/borrar/', v['borrar'].as_view(), name=f'{name}_borrar'),
    ]


urlpatterns = [
    path('', views.hub, name='hub'),
    path('negocio/', views.NegocioEditar.as_view(), name='negocio'),
]

urlpatterns += crud('turnos', 'turno', {
    'list': views.TurnoList, 'crear': views.TurnoCrear, 'editar': views.TurnoEditar, 'borrar': views.TurnoBorrar})
urlpatterns += crud('circuitos', 'circuito', {
    'list': views.CircuitoList, 'crear': views.CircuitoCrear, 'editar': views.CircuitoEditar, 'borrar': views.CircuitoBorrar})
urlpatterns += [
    path('circuitos/<int:pk>/tramos/', views.CircuitoTarifas.as_view(), name='circuito_tarifas'),
]
urlpatterns += crud('feriados', 'feriado', {
    'list': views.FeriadoList, 'crear': views.FeriadoCrear, 'editar': views.FeriadoEditar, 'borrar': views.FeriadoBorrar})
urlpatterns += crud('bloqueos', 'bloqueo', {
    'list': views.BloqueoList, 'crear': views.BloqueoCrear, 'editar': views.BloqueoEditar, 'borrar': views.BloqueoBorrar})
urlpatterns += crud('plantillas', 'plantilla', {
    'list': views.PlantillaList, 'crear': views.PlantillaCrear, 'editar': views.PlantillaEditar, 'borrar': views.PlantillaBorrar})
urlpatterns += crud('respuestas-rapidas', 'respuesta', {
    'list': views.RespuestaRapidaList, 'crear': views.RespuestaRapidaCrear,
    'editar': views.RespuestaRapidaEditar, 'borrar': views.RespuestaRapidaBorrar})
urlpatterns += crud('campos', 'campo', {
    'list': views.CampoPersonalizadoList, 'crear': views.CampoPersonalizadoCrear,
    'editar': views.CampoPersonalizadoEditar, 'borrar': views.CampoPersonalizadoBorrar})
urlpatterns += crud('extras', 'extra', {
    'list': views.ExtraList, 'crear': views.ExtraCrear,
    'editar': views.ExtraEditar, 'borrar': views.ExtraBorrar})

urlpatterns += [
    path('usuarios/', views.UsuarioList.as_view(), name='usuarios'),
    path('usuarios/nuevo/', views.UsuarioCrear.as_view(), name='usuario_crear'),
    path('usuarios/<int:pk>/editar/', views.UsuarioEditar.as_view(), name='usuario_editar'),
    path('automatizaciones/', views.AutomatizacionList.as_view(), name='automatizaciones'),
    path('automatizaciones/<int:pk>/editar/', views.AutomatizacionEditar.as_view(), name='automatizacion_editar'),
]
