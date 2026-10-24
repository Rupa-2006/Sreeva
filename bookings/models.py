from datetime import time
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse

from .utils import format_inr, whatsapp_url

MONEY = dict(max_digits=12, decimal_places=2)


class Client(models.Model):
    studio = models.ForeignKey("studios.Studio", on_delete=models.CASCADE, related_name="clients")
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=10, help_text="10-digit mobile number")
    alt_phone = models.CharField(max_length=10, blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["studio", "phone"], name="unique_client_phone_per_studio")
        ]

    def __str__(self):
        return f"{self.name} ({self.phone})"

    def get_absolute_url(self):
        return reverse("client_detail", args=[self.pk])


class BookingQuerySet(models.QuerySet):
    def with_money(self):
        """Annotate paid_total and pending_total in one query (no N+1 sums)."""
        paid = (
            Payment.objects.filter(booking=OuterRef("pk"))
            .values("booking")
            .annotate(s=Sum("amount"))
            .values("s")
        )
        money = DecimalField(**MONEY)
        return self.annotate(
            paid_total=Coalesce(Subquery(paid, output_field=money), Value(Decimal("0")), output_field=money),
        ).annotate(pending_total=F("total_amount") - F("paid_total"))


class Booking(models.Model):
    ENQUIRY, CONFIRMED, CANCELLED = "enquiry", "confirmed", "cancelled"
    STATUS_CHOICES = [(ENQUIRY, "Enquiry"), (CONFIRMED, "Confirmed"), (CANCELLED, "Cancelled")]

    W_UPCOMING, W_SHOOT_DONE, W_EDITING = "upcoming", "shoot_done", "editing"
    W_ALBUM, W_PRINTING, W_READY, W_DELIVERED = "album_design", "printing", "ready", "delivered"
    WORK_CHOICES = [
        (W_UPCOMING, "Shoot upcoming"),
        (W_SHOOT_DONE, "Shoot done"),
        (W_EDITING, "Editing"),
        (W_ALBUM, "Album design"),
        (W_PRINTING, "Printing"),
        (W_READY, "Ready to deliver"),
        (W_DELIVERED, "Delivered"),
    ]

    EVENT_TYPES = [
        ("wedding", "Wedding"),
        ("engagement", "Engagement"),
        ("pre_wedding", "Pre-wedding shoot"),
        ("reception", "Reception"),
        ("half_saree", "Half Saree / Dhoti function"),
        ("birthday", "Birthday"),
        ("naming", "Naming ceremony / Cradle"),
        ("housewarming", "House warming"),
        ("baby_shoot", "Baby / Maternity shoot"),
        ("corporate", "Corporate / College event"),
        ("portrait", "Studio portrait"),
        ("other", "Other"),
    ]

    studio = models.ForeignKey("studios.Studio", on_delete=models.CASCADE, related_name="bookings")
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="bookings")
    title = models.CharField(max_length=150, blank=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default="wedding")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=CONFIRMED)
    work_status = models.CharField(max_length=15, choices=WORK_CHOICES, default=W_UPCOMING)
    total_amount = models.DecimalField(
        **MONEY, default=0, validators=[MinValueValidator(0)], help_text="Final package price agreed"
    )
    delivery_due = models.DateField(null=True, blank=True, help_text="Promised album/video delivery date")
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.display_title

    def get_absolute_url(self):
        return reverse("booking_detail", args=[self.pk])

    @property
    def display_title(self):
        return self.title or f"{self.client.name} – {self.get_event_type_display()}"

    # --- money ---
    def sync_total(self):
        """Booking total = sum of its events' prices."""
        total = self.sessions.aggregate(s=Sum("amount"))["s"] or Decimal("0")
        if total != self.total_amount:
            self.total_amount = total
            self.save(update_fields=["total_amount", "updated_at"])
        return total

    @property
    def paid(self):
        if hasattr(self, "paid_total"):
            return self.paid_total
        return self.payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    @property
    def pending(self):
        return max(self.total_amount - self.paid, Decimal("0"))

    @property
    def paid_percent(self):
        if not self.total_amount:
            return 100
        return min(int(self.paid * 100 / self.total_amount), 100)

    @property
    def album_delivered(self):
        return self.work_status == self.W_DELIVERED

    # --- work pipeline (older versions tracked 7 steps; now only "delivered" matters) ---
    @property
    def work_step(self):
        keys = [k for k, _ in self.WORK_CHOICES]
        return keys.index(self.work_status)

    @property
    def next_work_status(self):
        keys = self.WORK_CHOICES
        i = self.work_step
        return keys[i + 1] if i + 1 < len(keys) else None

    # --- WhatsApp templates ---
    def wa_payment_reminder(self):
        text = (
            f"Hello {self.client.name}, greetings from {self.studio.name}. "
            f"This is a gentle reminder that {format_inr(self.pending)} is pending for "
            f"{self.display_title}. Thank you!"
        )
        return whatsapp_url(self.client.phone, text)

    def wa_confirmation(self):
        """Booking details for the customer on WhatsApp: dates, place, team, money."""
        lines = [f"Hello {self.client.name} 🙏", ""]
        if self.status == self.CONFIRMED:
            lines.append(f"Thank you for booking with *{self.studio.name}*. Your booking is confirmed ✅")
        else:
            lines.append(f"Thank you for contacting *{self.studio.name}*. Here are the details we have noted:")
        for s in self.sessions.prefetch_related("resource_needs__resource_type").order_by("date", "start_time"):
            lines += ["", f"📅 *{s.name}* – {s.date:%a, %d %b %Y}, {s.time_label}", f"📍 {s.place}"]
            items = ", ".join(f"{n.quantity} {n.resource_type.name}" for n in s.resource_needs.all() if n.quantity)
            if items:
                lines.append(f"📸 {items}")
        if self.total_amount:
            lines += ["", f"Total: {format_inr(self.total_amount)}"]
            if self.paid:
                lines.append(f"Advance paid: {format_inr(self.paid)}")
            if self.pending:
                lines.append(f"Balance: {format_inr(self.pending)}")
        lines += ["", f"– {self.studio.name}" + (f", {self.studio.phone}" if self.studio.phone else "")]
        return whatsapp_url(self.client.phone, "\n".join(lines))

    def wa_ready(self):
        text = (
            f"Hello {self.client.name}, good news from {self.studio.name}! "
            f"Your photos/album for {self.display_title} are ready. Please let us know a "
            f"convenient time to collect them."
        )
        if self.pending:
            text += f" Balance due: {format_inr(self.pending)}."
        return whatsapp_url(self.client.phone, text)


class SessionQuerySet(models.QuerySet):
    def with_money(self):
        """Annotate paid_total / pending_total per event in one query."""
        paid = (
            Payment.objects.filter(session=OuterRef("pk"))
            .values("session")
            .annotate(s=Sum("amount"))
            .values("s")
        )
        money = DecimalField(**MONEY)
        return self.annotate(
            paid_total=Coalesce(Subquery(paid, output_field=money), Value(Decimal("0")), output_field=money),
        ).annotate(pending_total=F("amount") - F("paid_total"))


class Session(models.Model):
    """One event within a booking (Haldi, Muhurtham, Reception…).

    Each event has its OWN price and its OWN payments, so two events on the same
    day are billed separately. The booking total is the sum of its events.
    """

    MORNING, EVENING, FULL, CUSTOM = "morning", "evening", "full", "custom"
    SLOT_CHOICES = [
        (MORNING, "Morning (6 AM – 1 PM)"),
        (EVENING, "Evening (3 PM – 11:30 PM)"),
        (FULL, "Full day"),
        (CUSTOM, "Custom time"),
    ]
    SLOT_TIMES = {
        MORNING: (time(6, 0), time(13, 0)),
        EVENING: (time(15, 0), time(23, 30)),
        FULL: (time(6, 0), time(23, 30)),
    }

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="sessions")
    name = models.CharField(max_length=80, default="Main event", help_text="e.g. Haldi, Muhurtham, Reception")
    date = models.DateField()
    slot = models.CharField(max_length=10, choices=SLOT_CHOICES, default=FULL)
    start_time = models.TimeField()
    end_time = models.TimeField()
    place = models.CharField(max_length=200, help_text="Venue name and area")
    map_link = models.URLField(max_length=500, blank=True, help_text="Paste a Google Maps link (optional)")
    notes = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(
        **MONEY, default=0, validators=[MinValueValidator(0)], help_text="Price agreed for this event"
    )
    extra_charges = models.JSONField(
        default=list, blank=True,
        help_text='Extra lines added to the price, e.g. [{"label": "Delivery", "amount": 500}]. Negative = discount.',
    )
    package = models.ForeignKey(
        "studios.Package", on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions",
        help_text="Package chosen for this event (fills price and team)",
    )
    assigned_staff = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="assigned_sessions"
    )

    objects = SessionQuerySet.as_manager()

    class Meta:
        ordering = ["date", "start_time"]

    # --- money for this event ---
    @property
    def paid(self):
        if hasattr(self, "paid_total"):
            return self.paid_total
        return self.payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    @property
    def pending(self):
        return max(self.amount - self.paid, Decimal("0"))

    @property
    def paid_percent(self):
        if not self.amount:
            return 100
        return min(int(self.paid * 100 / self.amount), 100)

    @property
    def label(self):
        return f"{self.name} · {self.date:%d %b}"

    @property
    def charges(self):
        """Extra charges as [(label, Decimal amount)] — safe to show in templates."""
        out = []
        for c in self.extra_charges or []:
            try:
                out.append((str(c.get("label", ""))[:60], Decimal(str(c.get("amount", 0)))))
            except Exception:
                continue
        return out

    @property
    def charges_total(self):
        return sum((a for _, a in self.charges), Decimal("0"))

    @property
    def base_price(self):
        """Price before extra charges (package / team)."""
        return self.amount - self.charges_total

    def wa_payment_reminder(self):
        b = self.booking
        text = (
            f"Hello {b.client.name}, greetings from {b.studio.name}. A gentle reminder that "
            f"{format_inr(self.pending)} is pending for {self.name} ({self.date:%d %b}). Thank you!"
        )
        return whatsapp_url(b.client.phone, text)

    def __str__(self):
        return f"{self.name} · {self.date:%d %b %Y}"

    def save(self, *args, **kwargs):
        if self.slot in self.SLOT_TIMES:
            self.start_time, self.end_time = self.SLOT_TIMES[self.slot]
        super().save(*args, **kwargs)

    @property
    def time_label(self):
        if self.slot == self.CUSTOM:
            def fmt(t, suffix=True):
                s = f"{t:%I:%M}".lstrip("0")
                return f"{s} {t:%p}".lower() if suffix else s
            return f"{fmt(self.start_time, False)}–{fmt(self.end_time)}"
        return {self.MORNING: "Morning", self.EVENING: "Evening", self.FULL: "Full day"}[self.slot]

    @property
    def short_label(self):
        if self.slot == self.CUSTOM:
            return f"{self.start_time:%I:%M}".lstrip("0")
        return {self.MORNING: "AM", self.EVENING: "PM", self.FULL: "Day"}[self.slot]

    PINNED = "Location on map"  # place text when only a Maps link was given

    @property
    def has_place_name(self):
        return self.place != self.PINNED

    @property
    def maps_url(self):
        return self.map_link or f"https://www.google.com/maps/search/?api=1&query={quote(self.place)}"

    @property
    def maps_embed_url(self):
        return f"https://maps.google.com/maps?q={quote(self.place)}&output=embed"

    def wa_reminder(self):
        b = self.booking
        text = (
            f"Hello {b.client.name}, this is {b.studio.name}. Reminder: our team will be at "
            f"{self.place} for your {self.name} on {self.date:%d %b} ({self.time_label}). "
            f"See you there!"
        )
        return whatsapp_url(b.client.phone, text)


class SessionResource(models.Model):
    """How many of a resource a session needs. `freelancers` = how many are hired from outside."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="resource_needs")
    resource_type = models.ForeignKey("studios.ResourceType", on_delete=models.PROTECT, related_name="usages")
    quantity = models.PositiveIntegerField(default=1)
    freelancers = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "resource_type"], name="unique_resource_per_session")
        ]

    def __str__(self):
        return f"{self.resource_type.name} ×{self.quantity}"

    @property
    def in_house(self):
        return self.quantity - self.freelancers


class Payment(models.Model):
    CASH, UPI, BANK, CARD, CHEQUE = "cash", "upi", "bank", "card", "cheque"
    MODE_CHOICES = [
        (CASH, "Cash"),
        (UPI, "UPI (GPay / PhonePe / Paytm)"),
        (BANK, "Bank transfer"),
        (CARD, "Card"),
        (CHEQUE, "Cheque"),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    session = models.ForeignKey(
        Session, on_delete=models.PROTECT, null=True, blank=True, related_name="payments",
        verbose_name="Event", help_text="Which event this money is for",
    )
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("1"))])
    date = models.DateField()
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=CASH)
    reference = models.CharField(max_length=60, blank=True, help_text="UPI / transaction ID")
    note = models.CharField(max_length=150, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{format_inr(self.amount)} on {self.date}"

    @property
    def receipt_no(self):
        return f"RCPT-{self.booking.studio_id:02d}-{self.pk:05d}"


class Notification(models.Model):
    """Something a person at the studio should know or do, e.g. "Shoot tomorrow:
    remind the customer" or "₹20,000 still pending".

    Most are reminders built from the bookings themselves (see notifications.py):
    they appear on their own and clear themselves once the work is done (payment
    received, album delivered…). "Assigned" notifications are sent to staff when the
    owner puts them on a shoot.
    """

    SHOOT_TODAY, SHOOT_TOMORROW = "shoot_today", "shoot_tomorrow"
    NO_TEAM, NO_ADVANCE, PAYMENT_DUE = "no_team", "no_advance", "payment_due"
    DELIVERY_SOON, DELIVERY_LATE = "delivery_soon", "delivery_late"
    ENQUIRY, ASSIGNED = "enquiry", "assigned"
    KIND_CHOICES = [
        (SHOOT_TODAY, "Shoot today"),
        (SHOOT_TOMORROW, "Shoot tomorrow"),
        (NO_TEAM, "No team assigned"),
        (NO_ADVANCE, "No advance yet"),
        (PAYMENT_DUE, "Balance pending"),
        (DELIVERY_SOON, "Delivery due soon"),
        (DELIVERY_LATE, "Delivery overdue"),
        (ENQUIRY, "Enquiry not confirmed"),
        (ASSIGNED, "You're on a shoot"),
    ]

    studio = models.ForeignKey("studios.Studio", on_delete=models.CASCADE, related_name="notifications")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    key = models.CharField(max_length=120, help_text="Stops the same reminder being created twice")
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=300, blank=True, help_text="Page inside the website")
    url_label = models.CharField(max_length=40, blank=True)
    action_url = models.CharField(max_length=1000, blank=True, help_text="WhatsApp message or directions")
    action_label = models.CharField(max_length=40, blank=True)
    urgent = models.BooleanField(default=False)
    ref_date = models.DateField(null=True, blank=True, help_text="The day this is about")
    auto = models.BooleanField(default=True, help_text="Clears itself when no longer true")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    closed_by_system = models.BooleanField(default=False, help_text="Cleared automatically (e.g. payment received)")

    class Meta:
        ordering = ["-urgent", "ref_date", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="unique_notification_per_user")]
        indexes = [models.Index(fields=["user", "done_at"])]

    def __str__(self):
        return self.title

    @property
    def is_whatsapp(self):
        return self.action_url.startswith("https://wa.me/")
