import logging

from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.conf import settings

logger = logging.getLogger(__name__)


def send_password_setup_email(request, user):
    """Send a one-time password-setup link to a newly created employee."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    setup_url = request.build_absolute_uri(
        f"/accounts/setup-password/{uid}/{token}/"
    )

    context = {
        "user": user,
        "setup_url": setup_url,
        "site_name": "Digilatics HR Portal",
    }

    subject = "Set up your Digilatics HR password"
    plain_message = render_to_string("accounts/email/password_setup.txt", context)
    html_message = render_to_string("accounts/email/password_setup.html", context)

    recipient = user.email
    if not recipient:
        logger.warning("Cannot send setup email for user %s — no email address.", user.username)
        return False

    try:
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info("Password setup email sent to %s", recipient)
        return True
    except Exception:
        logger.exception("Failed to send password setup email to %s", recipient)
        return False
