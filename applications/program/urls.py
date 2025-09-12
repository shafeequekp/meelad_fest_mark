from django.urls import path, include
from django.contrib.auth.decorators import login_required

from . import views


urlpatterns = [
    path('load_categories/', views.load_categories, name='load_categories'),
    path('load_students/', views.load_students, name='load_students'),
    path('load_programs/', views.load_programs, name='load_programs'),
    path('register_program/', views.register_program, name='register_program'),
    path("<int:pk>/participants/", views.program_participants_json, name="program_participants_json"),
    path("<int:pk>/judge-slip/pdf/", views.program_judge_slip_pdf, name="program_participants_pdf"),
    path("download-participants/<int:program_id>/<str:section>/<int:category_id>/", views.download_participants_pdf, name="download_participants_pdf"),

    path('categories/', views.CategoryView.as_view(), name='categories'),
    path('categories/add/', views.AddCategoryView.as_view(), name='add_category'),
    path('categories/<int:pk>/edit/', views.EditCategoryView.as_view(), name='edit_category'),
    path("category/<int:pk>/", views.CategoryDetailView.as_view(), name="category_detail"),
    path('student/<int:student_id>/add-program/', views.AddProgramToStudentView.as_view(), name='add_student_program'),
    path("student-registration/", views.StudentRegistrationView.as_view(), name="student_registration"),
    path('programs/', views.ProgramListView.as_view(), name='program_list'),

]