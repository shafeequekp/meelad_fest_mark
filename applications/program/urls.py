from django.urls import path, include
from django.contrib.auth.decorators import login_required

from . import views


urlpatterns = [
    path('search/', login_required(views.global_search), name='global_search'),
    path('load_categories/', views.load_categories, name='load_categories'),
    path('load_students/', views.load_students, name='load_students'),
    path('load_team_students/', views.load_team_students, name='load_team_students'),
    path('load_programs/', views.load_programs, name='load_programs'),
    path('register_program/', views.register_program, name='register_program'),
    path("<int:pk>/participants/", views.program_participants_json, name="program_participants_json"),
    path("<int:pk>/judge-slip/pdf/<int:category_id>/", views.program_judge_slip_pdf, name="program_participants_pdf"),
    path("download-participants/<int:program_id>/<str:section>/<int:category_id>/", views.download_participants_pdf, name="download_participants_pdf"),

    path("download-poster/<int:program_id>/<str:section>/", views.download_results_poster_image, name="download_results_poster_image"),

    path('<int:program_id>/save-prize/', views.save_prize, name='save-prize'),
    path('<int:program_id>/publish_result/', views.publish_or_unpublish_result, name='publish_result'),

    path('categories/', views.CategoryView.as_view(), name='categories'),
    path('categories/add/', views.AddCategoryView.as_view(), name='add_category'),
    path('categories/<int:pk>/edit/', views.EditCategoryView.as_view(), name='edit_category'),
    path("category/<int:pk>/", views.CategoryDetailView.as_view(), name="category_detail"),
    path('student/<int:student_id>/', views.student_profile, name='student_profile'),
    path('student/<int:student_id>/delete/', views.delete_student, name='delete_student'),
    path('trash/<int:trash_id>/restore/', views.restore_trash, name='restore_trash'),
    path('student/<int:student_id>/edit/', views.edit_student, name='edit_student'),
    path('student/<int:student_id>/add-program/', views.AddProgramToStudentView.as_view(), name='add_student_program'),
    path("student-registration/", views.StudentRegistrationView.as_view(), name="student_registration"),
    path('programs/', views.ProgramListView.as_view(), name='program_list'),
    path('program/add/', views.add_program, name='add_program'),
    path('program/<int:program_id>/delete/', views.delete_program, name='delete_program'),

    path("<int:program_id>/participants/search/", views.participant_search, name="participant_search"),

    path('upload-students/', views.StudentUploadView.as_view(), name='upload-students'),
    path('download-sample-file/', views.SampleStudentUploadFileView.as_view(), name='download-sample-file'),
    path('upload-programs/', views.ProgramUploadView.as_view(), name='upload-programs'),
    path('download-program-sample-file/', views.SampleProgramUploadFileView.as_view(), name='download-program-sample-file'),

    path('results/category-programs/', views.category_program_list, name='results'),
    path('results/all/download/', views.download_all_results_pdf, name='download_all_results_pdf'),
    path('certificates/download/', views.download_certificates_pdf, name='download_certificates_pdf'),
    path('general-programs/', views.general_programs, name='general_programs'),
    path('<int:program_id>/save-general-prize/', views.save_general_prize, name='save_general_prize'),

    path('group-programs/', views.group_programs, name='group_programs'),
    path('group-programs/<int:program_id>/', views.group_program_detail, name='group_program_detail'),
    path('<int:program_id>/save-group-prize/', views.save_group_prize, name='save_group_prize'),

    path('statistics/', views.statistics_dashboard, name='statistics'),
    path('statistics/download/', views.statistics_download_report, name='statistics_download_report'),

    path("<int:pk>/participant-data/", views.get_program_participants, name="get_program_participant_data"),
    path("<int:pk>/participants/save/", views.save_program_participants, name="save_program_participants"),

    path('revoke_program_link/', views.revoke_program_link, name='revoke_program_link'),
    path('generate_program_link/', views.generate_program_reg_link, name='generate_program_link'),

    path('generate-parent-link/', views.generate_parent_link, name='generate_parent_link'),
    path('revoke-parent-link/', views.revoke_parent_link, name='revoke_parent_link'),

    path("save-config/", views.save_config, name="save_config"),

    # for venues
    path("venues/", views.venue_list, name="venue_list"),
    path("venues/add/", views.add_venue, name="add_venue"),
    path("venues/<int:venue_id>/edit/", views.edit_venue, name="edit_venue"),
    path("venues/<int:venue_id>/delete/", views.delete_venue, name="delete_venue"),
    path("venues/<int:venue_id>/", login_required(views.venue_detail), name="venue_detail"),
    path("add-programs-to-venue/<int:pk>/", views.update_venue_with_program, name="add-programs-to-venue"),
    path("programs/<int:program_id>/remove-venue/", views.remove_program_from_venue, name="remove-program-from-venue"),
    path("download-venue-programs/<int:venue_id>/", views.download_venue_programs, name="download-venue-programs"),

    # Judges + digital evaluation
    path("judges/", views.judges, name="judges"),
    path("judges/<int:judge_id>/edit/", views.edit_judge, name="edit_judge"),
    path("judges/<int:judge_id>/delete/", views.delete_judge, name="delete_judge"),
    path("judges/portal/", views.judge_portal, name="judge_portal"),
    path("judges/program/<int:program_id>/rankings/", views.judge_program_rankings, name="judge_program_rankings"),
    path("judges/program/<int:program_id>/publish/", views.judge_publish_rankings, name="judge_publish_rankings"),
    path("judges/<int:judge_id>/program/<int:program_id>/", views.judge_program_evaluation, name="judge_program_evaluation"),
    path("judges/<int:judge_id>/program/<int:program_id>/save/", views.judge_save_evaluation, name="judge_save_evaluation"),
    path("program/<int:program_id>/criteria/save/", views.save_program_evaluation_criteria, name="save_program_criteria"),

    # NOTE: the public student-portal login/portal/logout pages live at the
    # root URLconf (/students/login/, /students/portal/, /students/logout/).

]