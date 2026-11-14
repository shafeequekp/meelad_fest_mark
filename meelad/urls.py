"""meelad URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import render
from django.views.static import serve as static_serve

import os

from applications.program.views import (
    program_reg_short_link_redirect,
    parents_portal,
    student_programs_results,
)


# ---------- Themed error pages ----------
# Referenced by Django's handler{403,404,500} settings via the ROOT_URLCONF.
# 404/403 render the shared app shell; 500 (templates/500.html) is fully
# standalone so it renders even when the app or the network is broken.
def handler403(request, exception):
    return render(request, '403.html', status=403)


def handler404(request, exception):
    return render(request, '404.html', status=404)


def handler500(request):
    return render(request, '500.html', status=500)

# Student portal (public login with the student's fest code)
from applications.program.views import (
    student_login,
    student_logout,
    student_portal,
)

urlpatterns = [
    # Service worker must be served from the root scope to control the whole
    # origin (a /static/... location would only ever scope to /static/).
    re_path(r'^sw\.js$', static_serve, {
        'document_root': os.path.join(settings.BASE_DIR, 'staticfiles'),
        'path': 'sw.js',
    }, name='service-worker'),

    # Offline fallback page (served by the service worker when a navigation
    # fails and no cached copy exists). Reads from staticfiles/ like sw.js.
    re_path(r'^offline/$', static_serve, {
        'document_root': os.path.join(settings.BASE_DIR, 'staticfiles'),
        'path': 'offline.html',
    }, name='offline-page'),

    path('admin/', admin.site.urls),
    path('', include('applications.scoreboard.urls')),
    path("x/<str:code>/", program_reg_short_link_redirect),
    path("p/<str:code>/", parents_portal, name="parents_portal"),
    path("p/<str:code>/student/<int:student_id>/", student_programs_results, name="student_programs_results"),
    path("students/login/", student_login, name="student_login"),
    path("students/logout/", student_logout, name="student_logout"),
    path("students/portal/", student_portal, name="student_portal"),
    path('accounts/', include('applications.accounts.urls')),
    path('program/', include('applications.program.urls')),
    path('subscription/', include('applications.subscription.urls')),
    path('ai/', include('applications.aiassistant.urls')),
    path('schedule/', include('applications.schedule.urls')),

]
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
