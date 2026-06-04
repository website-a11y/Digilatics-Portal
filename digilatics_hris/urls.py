from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.shortcuts import render

def custom_404(request, exception=None):
    return render(request, "404.html", status=404)

handler404 = custom_404

urlpatterns = [
    # Home → portal login
    path("", RedirectView.as_view(url="/portal/login/", permanent=False)),
    # Redirect admin login to the unified portal login
    path("admin/login/", RedirectView.as_view(url="/portal/login/?next=/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    path("", include("attendance.urls")),
    path("", include("accounts.urls")),
    path("portal/", include("portal.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
