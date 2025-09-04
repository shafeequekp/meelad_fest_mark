from django.contrib import admin

from accounts.models import User, Madrasa


class UserAdmin(admin.ModelAdmin):
    list_display = ['email', 'madrasa']


admin.site.register(User, UserAdmin)
admin.site.register(Madrasa)

