from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ('username', 'get_full_name', 'email', 'rol', 'is_staff', 'is_active')
    list_filter = ('rol', 'is_staff', 'is_active')
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('CRM Spa', {'fields': ('rol',)}),
    )
