from django.contrib import admin

from applications.scoreboard.models import Team, Mark


admin.site.register(Team)
admin.site.register(Mark)
