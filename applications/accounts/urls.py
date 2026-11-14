from django.urls import path
from django.contrib import admin

from .views import (
    login_view, signup_view, logout_view, update_madrasa,
    upload_madrasa_profile_pic, upload_fest_rules, remove_fest_rules,
    forgot_password_view,
)

urlpatterns = [
    path("login/", login_view, name="login"),
    path("signup/", signup_view, name="signup"),
    path("logout/", logout_view, name="logout"),
    path("forgot-password/", forgot_password_view, name="forgot_password"),
    path("madrasa/update/", update_madrasa, name="update_madrasa"),
    path("madrasa/avatar/upload/", upload_madrasa_profile_pic,
         name="upload_madrasa_profile_pic"),
    path("madrasa/fest-rules/upload/", upload_fest_rules,
         name="upload_fest_rules"),
    path("madrasa/fest-rules/remove/", remove_fest_rules,
         name="remove_fest_rules"),
]

admin.site.site_header = "Meelad Admin Central"
