import csv

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.reservas import services as reservas_services
from apps.reservas.models import Pago, Reserva

from .filtros import OPERADORES, aplicar_filtro_campo
from .forms import ContactoForm, NotaContactoForm
from .models import CampoPersonalizado, Contacto


@login_required
def lista(request):
    q = request.GET.get('q', '').strip()
    contactos = Contacto.objects.all()
    if q:
        contactos = contactos.filter(Q(nombre__icontains=q) | Q(telefono__icontains=q) | Q(email__icontains=q))

    # Filtro por campo personalizado: ?campo=<id>&op=<operador>&valor=<texto>
    campo_id = request.GET.get('campo')
    operador = request.GET.get('op', 'eq')
    valor = request.GET.get('valor', '').strip()
    campo_sel = None
    if campo_id:
        campo_sel = CampoPersonalizado.objects.filter(pk=campo_id, activo=True).first()
        if campo_sel and valor:
            contactos = aplicar_filtro_campo(contactos, campo_sel, operador, valor)

    contactos = contactos.prefetch_related('etiquetas').distinct()[:200]
    return render(request, 'contactos/lista.html', {
        'contactos': contactos, 'q': q,
        'campos': CampoPersonalizado.objects.filter(activo=True),
        'campo_sel': campo_sel, 'op_sel': operador, 'valor_sel': valor,
        'operadores': OPERADORES,
    })


@login_required
def export_csv(request):
    """Exporta todos los contactos a CSV, incluyendo columnas de campos personalizados."""
    campos = list(CampoPersonalizado.objects.filter(activo=True))
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="contactos.csv"'
    resp.write('﻿')  # BOM para Excel
    w = csv.writer(resp)
    w.writerow(['Nombre', 'Teléfono', 'Email', 'Nacimiento', 'Etiquetas', 'Alta'] + [c.nombre for c in campos])
    for c in Contacto.objects.prefetch_related('etiquetas').all():
        datos = c.datos_extra or {}
        w.writerow([
            c.nombre, c.telefono, c.email,
            c.fecha_nacimiento.isoformat() if c.fecha_nacimiento else '',
            '; '.join(e.nombre for e in c.etiquetas.all()),
            c.fecha_alta.strftime('%Y-%m-%d'),
        ] + [campo.formato(datos.get(campo.slug)) if datos.get(campo.slug) not in (None, '') else '' for campo in campos])
    return resp


@login_required
def crear(request):
    """Alta de un contacto nuevo. Acepta ?telefono= para prellenar (ej. desde el inbox)."""
    if request.method == 'POST':
        form = ContactoForm(request.POST)
        if form.is_valid():
            contacto = form.save()
            return redirect('contactos:detalle', pk=contacto.pk)
    else:
        initial = {}
        tel = request.GET.get('telefono', '').strip()
        if tel:
            initial['telefono'] = tel
        form = ContactoForm(initial=initial)
    return render(request, 'contactos/nuevo.html', {'form': form})


@login_required
def detalle(request, pk):
    contacto = get_object_or_404(Contacto, pk=pk)
    reservas = contacto.reservas.select_related('circuito', 'turno').order_by('-fecha')
    return render(request, 'contactos/detalle.html', {
        'contacto': contacto,
        'reservas': reservas,
        'notas': contacto.notas.select_related('autor'),
        'nota_form': NotaContactoForm(),
        'total_gastado': sum(r.monto_pagado for r in reservas),
    })


@login_required
def editar(request, pk):
    contacto = get_object_or_404(Contacto, pk=pk)
    if request.method == 'POST':
        form = ContactoForm(request.POST, instance=contacto)
        if form.is_valid():
            form.save()
            return redirect('contactos:detalle', pk=pk)
    else:
        form = ContactoForm(instance=contacto)
    return render(request, 'contactos/editar.html', {'form': form, 'contacto': contacto})


@login_required
def agregar_nota(request, pk):
    contacto = get_object_or_404(Contacto, pk=pk)
    if request.method == 'POST':
        form = NotaContactoForm(request.POST)
        if form.is_valid():
            nota = form.save(commit=False)
            nota.contacto = contacto
            nota.autor = request.user
            nota.save()
    return redirect('contactos:detalle', pk=pk)


@login_required
def registrar_pago(request, reserva_id):
    reserva = get_object_or_404(Reserva, pk=reserva_id)
    if request.method == 'POST':
        monto = request.POST.get('monto')
        medio = request.POST.get('medio_pago')
        tipo = request.POST.get('tipo')
        if monto and medio and tipo:
            from decimal import Decimal
            if tipo == Pago.Tipo.SENA:
                reservas_services.confirmar_sena(reserva, Decimal(monto), medio)
            else:
                reservas_services.registrar_pago_saldo(reserva, Decimal(monto), medio)
    return redirect('contactos:detalle', pk=reserva.contacto_id)
