from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profile(models.Model):
    """Extra details for every login: which studio they belong to and their role.

    Owner  -> full access (bookings, money, staff, settings, audit log)
    Staff  -> sees shoots and updates work progress, never sees money
    """

    OWNER = "owner"
    STAFF = "staff"
    ROLE_CHOICES = [(OWNER, "Owner"), (STAFF, "Staff")]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    studio = models.ForeignKey(
        "studios.Studio", on_delete=models.CASCADE, null=True, blank=True, related_name="members"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=OWNER)
    phone = models.CharField(max_length=15, blank=True)
    designation = models.CharField(
        max_length=60, blank=True, help_text="e.g. Photographer, Videographer, Editor"
    )

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.get_role_display()})"

    @property
    def is_owner(self):
        return self.role == self.OWNER


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


class AuditLog(models.Model):
    """Who did what, and from where. Owners can review it from the Activity page."""

    studio = models.ForeignKey(
        "studios.Studio", on_delete=models.CASCADE, null=True, blank=True, related_name="audit_logs"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=60)
    detail = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%d %b %H:%M} {self.user} {self.action}"
