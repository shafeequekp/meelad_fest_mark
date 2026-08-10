from django.urls import path, include
from django.contrib.auth.decorators import login_required

from . import views


urlpatterns = [
    path('teams/add/', views.add_team_and_marks, name='add_team'),
    path('teams/<int:team_id>/edit/', views.edit_team, name='edit_team'),
    # path("add/", views.add_team_with_marks, name="add_team_marks"),
    # path("teams/<int:team_id>/edit-marks/", views.edit_marks_view, name="edit_marks"),


    path('', login_required(views.MarkView.as_view()), name='home'),
    path('teams/', views.TeamsView.as_view(), name='teams'),

]