from django.contrib import admin
from django.db import connections

from .models import AIChatMessage, AIChatSession, AIOperationAuditLog


class AIChatMessageInline(admin.TabularInline):
    model = AIChatMessage
    extra = 0
    readonly_fields = ("role", "content", "created")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class AIChatSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "conversation_id", "updated", "created")
    list_filter = ()
    search_fields = ("user__email", "user__phone_number", "title",
                     "conversation_id")
    readonly_fields = ("user", "conversation_id", "title", "created",
                       "updated")
    ordering = ("-updated",)
    inlines = [AIChatMessageInline]

    def has_add_permission(self, request):
        return False


admin.site.register(AIChatSession, AIChatSessionAdmin)


class AIOperationAuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "target_type", "target_id", "approved",
                    "success", "created")
    list_filter = ("action", "success", "approved")
    search_fields = ("user__email", "user__phone_number", "idempotency_key")
    readonly_fields = ("user", "action", "target_type", "target_id", "payload",
                       "idempotency_key", "approved", "success", "message",
                       "source", "created")
    ordering = ("-created",)
    date_hierarchy = "created"

    def changelist_view(self, request, extra_context=None):
        # ``date_hierarchy`` renders TruncYear/TruncMonth/TruncDay aggregates.
        # With USE_TZ=True, MySQL returns NULLs until its timezone tables are
        # loaded (mysql_tzinfo_to_sql), which Django turns into a hard
        # "Database returned an invalid datetime value" crash — taking the
        # whole changelist down. Postgres ships the tz data, so the drill-down
        # stays there; on MySQL without the tz tables we drop it gracefully
        # instead of 500ing.
        try:
            conn = connections[self.model.objects.db]
            if not conn.features.has_zoneinfo_database:
                self.date_hierarchy = None
        except Exception:
            pass
        return super().changelist_view(request, extra_context)


admin.site.register(AIOperationAuditLog, AIOperationAuditLogAdmin)