from django.urls import path, include
from django.contrib.auth.decorators import login_required

from . import views


urlpatterns = [
    path('teams/add/', views.add_team_and_marks, name='add_team'),
    # path("add/", views.add_team_with_marks, name="add_team_marks"),
    # path("edit/<int:pk>/", views.edit_team_with_marks, name="edit_team_marks"),
    path('', login_required(views.MarkView.as_view()), name='home'),
    path('teams/', views.TeamsView.as_view(), name='teams'),

]