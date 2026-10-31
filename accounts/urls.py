from django.urls import path
from django.views.decorators.debug import sensitive_post_parameters

from . import recovery, verify, views

urlpatterns = [
    path("", views.home, name="home"),
    path("privacy/", views.privacy, name="privacy"),
    path("login/", views.RateLimitedLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("signup/", views.signup, name="signup"),
    path("demo/", views.try_demo, name="try_demo"),
    path("verify-email/resend/", verify.resend_verification, name="resend_verification"),
    path("verify-email/<str:token>/", verify.verify_email, name="verify_email"),
    # Forgot username / password
    path("forgot/", recovery.ForgotView.as_view(), name="password_reset"),
    path("forgot/sent/", recovery.ForgotSentView.as_view(), name="password_reset_done"),
    path(
        "reset/<uidb64>/<token>/",
        sensitive_post_parameters("new_password1", "new_password2")(recovery.ResetConfirmView.as_view()),
        name="password_reset_confirm",
    ),
    # Staff
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/<int:user_id>/toggle/", views.staff_toggle, name="staff_toggle"),
    path("staff/<int:user_id>/password/", views.staff_set_password, name="staff_set_password"),
    path("activity/", views.audit_log, name="audit_log"),
]
