from django.urls import path

from . import views
from . import operations

app_name = "aiassistant"

# Browser-facing (session auth) + service-facing (token auth) routes.
urlpatterns = [
    # Frontend chat proxy (login_required enforced in the view)
    path("chat/", views.chat_proxy, name="chat"),
    path("chat/health/", views.chat_health, name="chat_health"),
    path("chat/history/", views.chat_history, name="chat_history"),
    path("chat/history/<str:conversation_id>/", views.chat_history_detail,
         name="chat_history_detail"),
    path("chat/new/", views.chat_new, name="chat_new"),

    # ---- Internal API consumed by the FastAPI AI service (service token) ----
    path("api/health/", views.health, name="ai_health"),
    path("api/fest-rules/", views.fest_rules, name="ai_fest_rules"),

    path("api/teams/", views.list_teams, name="ai_teams"),
    path("api/teams/rankings/", views.team_rankings, name="ai_team_rankings"),
    path("api/teams/<int:team_id>/", views.team_detail, name="ai_team_detail"),

    path("api/students/search/", views.search_students, name="ai_student_search"),
    path("api/students/<int:student_id>/", views.student_detail, name="ai_student_detail"),
    path("api/students/<int:student_id>/programs/", views.student_programs, name="ai_student_programs"),
    path("api/students/<int:student_id>/results/", views.student_results, name="ai_student_results"),

    path("api/programs/", views.list_programs, name="ai_programs"),
    path("api/programs/unscheduled/", views.unscheduled_programs, name="ai_programs_unscheduled"),
    path("api/programs/<int:program_id>/", views.program_detail, name="ai_program_detail"),
    path("api/programs/<int:program_id>/participants/", views.program_participants, name="ai_program_participants"),
    path("api/programs/<int:program_id>/result/", views.program_result, name="ai_program_result"),

    path("api/group-programs/", views.list_group_programs, name="ai_group_programs"),
    path("api/group-programs/<int:program_id>/groups/", views.group_program_groups, name="ai_group_groups"),

    path("api/venues/", views.list_venues, name="ai_venues"),
    path("api/venues/<int:venue_id>/schedule/", views.venue_schedule, name="ai_venue_schedule"),
    path("api/venues/<int:venue_id>/availability/", views.venue_availability, name="ai_venue_availability"),

    path("api/fest-days/", views.list_fest_days, name="ai_fest_days"),

    path("api/schedules/", views.list_schedules, name="ai_schedules"),
    path("api/schedules/conflicts/", views.schedule_conflicts, name="ai_schedule_conflicts"),
    path("api/schedules/suggest/", views.suggest_schedule, name="ai_schedule_suggest"),

    # ---- Write operations (service token + actor + confirmation) ----
    path("api/operations/schedule/", operations.op_schedule, name="ai_op_schedule"),
    path("api/operations/groups/", operations.op_create_group, name="ai_op_create_group"),
    path("api/operations/groups/remove-participant/",
         operations.op_remove_group_participant, name="ai_op_remove_participant"),
]