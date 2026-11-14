"""Django admin definitions for the accounts app.

Registers the ``User`` and ``Madrasa`` models with customized admin forms.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from applications.accounts.models import User, Madrasa


@admin.register(User)
class UserAdmin(UserAdmin):
    """User admin with a clean, subscription-independent configuration.

    The default Django ``UserAdmin`` fieldsets reference ``username``, which
    this User model does not have (``username = None``). We explicitly
    rebuild the fieldsets without the ``username`` field.
    """

    list_display = ['email', 'madrasa', 'is_staff', 'is_active', 'date_joined']
    list_filter = ['is_staff', 'is_active', 'is_superuser', 'madrasa']
    search_fields = ['email', 'phone_number', 'madrasa__name']
    ordering = ['-date_joined']

    # Use the same fieldsets as the base UserAdmin, minus the username field.
    _base_fieldsets = UserAdmin.fieldsets
    _username_field = "username"

    def get_fieldsets(self, request, obj=None):
        """Return fieldsets without the username field."""
        fieldsets = []
        for name, opts in self._base_fieldsets:
            f = list(opts.get("fields", ()))
            if self._username_field in f:
                f.remove(self._username_field)
            fieldsets.append((name, {**opts, "fields": tuple(f)}))
        return fieldsets

    def get_add_fieldsets(self, request, obj=None):
        """Return add fieldsets without the username field."""
        fieldsets = []
        for name, opts in self._base_fieldsets:
            f = list(opts.get("fields", ()))
            if self._username_field in f:
                f.remove(self._username_field)
            fieldsets.append((name, {**opts, "fields": tuple(f)}))
        return fieldsets


class MadrasaAdmin(admin.ModelAdmin):
    list_display = ['name', 'reg_number', 'sadr', 'committee_name', 'meelad_fest_name',
                    'madrasa_profile_pic', 'fest_type']
    search_fields = ['name', 'reg_number']


admin.site.register(Madrasa, MadrasaAdmin)
