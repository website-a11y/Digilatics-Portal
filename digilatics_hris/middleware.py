import os

from django.shortcuts import redirect


class BlockAdminForNonSuperusers:
    """Redirect any authenticated non-superuser away from /admin/."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            user = getattr(request, "user", None)
            if user and user.is_authenticated and not user.is_superuser:
                return redirect("/portal/")
        return self.get_response(request)


class ZKTecoRequestLogger:
    """Logs every HTTP request to zkteco_debug.log for debugging device push."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.log_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "zkteco_debug.log"
        )

    def __call__(self, request):
        remote = request.META.get("REMOTE_ADDR", "?")
        body = request.body.decode("utf-8", errors="replace")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(
                f"\n{'='*60}\n"
                f"FROM   : {remote}\n"
                f"METHOD : {request.method}\n"
                f"PATH   : {request.get_full_path()}\n"
                f"C-TYPE : {request.content_type}\n"
                f"BODY   : {body[:2000]}\n"
            )
        response = self.get_response(request)
        try:
            resp_body = response.content.decode("utf-8", errors="replace")[:500]
        except Exception:
            resp_body = "(unreadable)"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"STATUS : {response.status_code}\n")
            f.write(f"RESP   : {resp_body}\n")
        return response
