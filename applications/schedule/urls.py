from django.urls import path

from . import views


urlpatterns = [
    path('', views.schedule_dashboard, name='schedule_dashboard'),
    path('consent/', views.set_schedule_consent, name='set_schedule_consent'),
    path('fest-days/add/', views.add_fest_day, name='add_fest_day'),
    path('fest-days/<int:pk>/edit/', views.edit_fest_day, name='edit_fest_day'),
    path('fest-days/<int:pk>/delete/', views.delete_fest_day, name='delete_fest_day'),
    path('add/', views.add_schedule, name='add_schedule'),
    path('<int:pk>/edit/', views.edit_schedule, name='edit_schedule'),
    path('<int:pk>/delete/', views.delete_schedule, name='delete_schedule'),
    path('api/conflicts/', views.check_schedule_conflicts_api, name='check_schedule_conflicts'),
]