from django.urls import path
from . import views

app_name = "attendance"

urlpatterns = [
    # ZKTeco ADMS push protocol endpoints
    path("iclock/cdata",        views.iclock_cdata,      name="adms_cdata"),
    path("iclock/getrequest",   views.iclock_getrequest, name="adms_getrequest"),
    path("iclock/devicecmd",    views.iclock_devicecmd,  name="adms_devicecmd"),

    # Employee self-punch portal
    path("punch/", views.employee_punch_view, name="employee_punch"),
]
