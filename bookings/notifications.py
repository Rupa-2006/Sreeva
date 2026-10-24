"""Notifications: what the owner and staff should know or do today.

Reminders are worked out from the bookings, so nobody has to create them:

  Owner                                         Staff
  - shoot tomorrow → remind the customer        - you're on a shoot (when assigned)
  - shoot today → directions                    - your shoot today / tomorrow
  - no team assigned (next 3 days)
  - no advance yet (next 7 days)
  - balance pending after the event (weekly)
  - delivery due in 3 days / overdue (weekly)
  - enquiry not confirmed (next 7 days)

They clear themselves when they stop being true (payment received, team assigned,
album delivered, day passed). ``refresh`` is cheap and throttled, so it runs while
pages load — no background job or paid SMS service is needed.
"""
from datetime import timedelta
from django.core.cache import cache
from django.db.models import Min
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile

from .models import Booking, Notification, Session
from .utils import format_inr, whatsapp_url

REFRESH_EVERY = 60  # seconds


def _day(d, today):
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    return f"{d:%a %d %b}"


def _week(d):
    y, w, _ = d.isocalendar()
    return f"{y}w{w}"


def _event_title(s):
    b = s.booking
    name = b.display_title
    return name if s.name in (name, b.get_event_type_display()) else f"{name} – {s.name}"


def owner_reminders(studio, today):
    out = []
    confirmed = (
        Session.objects.filter(booking__studio=studio, booking__status=Booking.CONFIRMED)
        .select_related("booking__client", "booking__studio")
        .prefetch_related("assigned_staff")
    )
    has_staff = Profile.objects.filter(studio=studio, role=Profile.STAFF, user__is_active=True).exists()

    # Shoots today and tomorrow
    for s in confirmed.filter(date__in=[today, today + timedelta(days=1)]):
        team = ", ".join(u.first_name or u.username for u in s.assigned_staff.all())
        when = "today" if s.date == today else "tomorrow"
        n = dict(
            key=f"{when}:{s.pk}:{s.date}", ref_date=s.date,
            kind=Notification.SHOOT_TODAY if when == "today" else Notification.SHOOT_TOMORROW,
            title=f"Shoot {when}: {_event_title(s)}",
            body=f"{s.time_label} at {s.place}." + (f" Team: {team}." if team else ""),
            url=s.booking.get_absolute_url(), url_label="Open booking",
        )
        if when == "tomorrow":
            n.update(action_url=s.wa_reminder(), action_label="Remind customer",
                     body=n["body"] + " Send the customer a reminder.")
        else:
            n.update(action_url=s.maps_url, action_label="Directions")
        out.append(n)

    # Nobody assigned to a shoot in the next 3 days
    if has_staff:
        for s in confirmed.filter(date__gte=today, date__lte=today + timedelta(days=3), assigned_staff=None):
            out.append(dict(
                key=f"noteam:{s.pk}:{s.date}", ref_date=s.date, kind=Notification.NO_TEAM,
                urgent=s.date <= today + timedelta(days=1),
                title=f"No team yet: {_event_title(s)}",
                body=f"Shoot is {_day(s.date, today)} ({s.time_label}). Assign staff so they get notified.",
                url=s.booking.get_absolute_url(), url_label="Assign team",
            ))

    money = confirmed.with_money()
    # Upcoming event and no advance at all
    for s in money.filter(date__gte=today, date__lte=today + timedelta(days=7), amount__gt=0, paid_total=0):
        out.append(dict(
            key=f"noadv:{s.pk}", ref_date=s.date, kind=Notification.NO_ADVANCE,
            title=f"No advance yet: {_event_title(s)}",
            body=f"Event is {_day(s.date, today)}. Price {format_inr(s.amount)}, nothing received so far.",
            url=reverse("payment_add", args=[s.booking_id]) + f"?event={s.pk}", url_label="Record payment",
            action_url=s.wa_payment_reminder(), action_label="Ask on WhatsApp",
        ))

    # Event is over and money is still pending (repeats every week until paid)
    for s in money.filter(date__lt=today, pending_total__gt=0):
        late = (today - s.date).days
        out.append(dict(
            key=f"due:{s.pk}:{_week(today)}", ref_date=s.date, kind=Notification.PAYMENT_DUE,
            urgent=late > 14,
            title=f"Balance {format_inr(s.pending)}: {_event_title(s)}",
            body=f"Event was on {s.date:%d %b} ({late} day{'s' if late != 1 else ''} ago). "
                 f"Paid {format_inr(s.paid)} of {format_inr(s.amount)}.",
            url=reverse("payment_add", args=[s.booking_id]) + f"?event={s.pk}", url_label="Record payment",
            action_url=s.wa_payment_reminder(), action_label="Remind on WhatsApp",
        ))

    # Album / video delivery
    open_work = (
        Booking.objects.filter(studio=studio, status=Booking.CONFIRMED, delivery_due__isnull=False)
        .exclude(work_status=Booking.W_DELIVERED).select_related("client", "studio")
    )
    for b in open_work.filter(delivery_due__lte=today + timedelta(days=3)):
        if b.delivery_due < today:
            late = (today - b.delivery_due).days
            n = dict(
                key=f"late:{b.pk}:{_week(today)}", kind=Notification.DELIVERY_LATE, urgent=True,
                title=f"Delivery overdue: {b.display_title}",
                body=f"Promised on {b.delivery_due:%d %b} ({late} day{'s' if late != 1 else ''} late). "
                     f"Tap Delivered on the booking once it's handed over.",
            )
        else:
            n = dict(
                key=f"soon:{b.pk}:{b.delivery_due}", kind=Notification.DELIVERY_SOON,
                title=f"Delivery due {_day(b.delivery_due, today)}: {b.display_title}",
                body=f"Promised for {b.delivery_due:%d %b}.",
            )
        n.update(ref_date=b.delivery_due, url=b.get_absolute_url(), url_label="Open booking")
        n.update(action_url=b.wa_ready(), action_label="Tell customer it's ready")
        out.append(n)

    # Enquiries for the coming week that are still not confirmed
    enquiries = (
        Booking.objects.filter(studio=studio, status=Booking.ENQUIRY)
        .annotate(first=Min("sessions__date"))
        .filter(first__gte=today, first__lte=today + timedelta(days=7))
        .select_related("client", "studio")
    )
    for b in enquiries:
        text = (f"Hello {b.client.name}, this is {b.studio.name}. Following up on your enquiry for "
                f"{b.first:%d %b}. Shall we confirm the booking for you?")
        out.append(dict(
            key=f"enq:{b.pk}:{b.first}", ref_date=b.first, kind=Notification.ENQUIRY,
            urgent=b.first <= today + timedelta(days=2),
            title=f"Enquiry not confirmed: {b.display_title}",
            body=f"Event is {_day(b.first, today)}. Your team isn't reserved until it's confirmed.",
            url=b.get_absolute_url(), url_label="Open booking",
            action_url=whatsapp_url(b.client.phone, text), action_label="Follow up",
        ))
    return out


def staff_reminders(user, studio, today):
    out = []
    mine = (
        Session.objects.filter(booking__studio=studio, booking__status=Booking.CONFIRMED, assigned_staff=user,
                               date__in=[today, today + timedelta(days=1)])
        .select_related("booking__client")
    )
    for s in mine:
        when = "today" if s.date == today else "tomorrow"
        out.append(dict(
            key=f"{when}:{s.pk}:{s.date}", ref_date=s.date,
            kind=Notification.SHOOT_TODAY if when == "today" else Notification.SHOOT_TOMORROW,
            title=f"Your shoot {when}: {_event_title(s)}",
            body=f"{s.time_label} at {s.place}." + (f" Note: {s.notes}" if s.notes else ""),
            url=s.booking.get_absolute_url(), url_label="See details",
            action_url=s.maps_url, action_label="Directions",
        ))
    return out


DEFAULTS = dict(kind="", title="", body="", url="", url_label="", action_url="", action_label="",
                urgent=False, ref_date=None)


def refresh(user, studio, is_owner, force=False):
    """Bring this person's reminders up to date (at most once a minute unless forced)."""
    if not studio or not user.is_authenticated:
        return
    throttle = f"notif-refresh:{user.pk}"
    if not force and cache.get(throttle):
        return
    cache.set(throttle, 1, REFRESH_EVERY)

    today = timezone.localdate()
    found = (owner_reminders(studio, today) if is_owner else []) + staff_reminders(user, studio, today)
    wanted = {}
    for n in found:
        data = {**DEFAULTS, **n}
        wanted[data.pop("key")] = data
    mine = Notification.objects.filter(user=user, studio=studio)
    existing = {n.key: n for n in mine.filter(key__in=list(wanted))}

    new = []
    for key, data in wanted.items():
        n = existing.get(key)
        if n is None:
            new.append(Notification(studio=studio, user=user, key=key, **data))
        elif not n.done_at:  # keep the text current (e.g. the pending amount changed)
            changed = [f for f, v in data.items() if getattr(n, f) != v]
            for f in changed:
                setattr(n, f, data[f])
            if changed:
                n.save(update_fields=changed)
    if new:
        Notification.objects.bulk_create(new, ignore_conflicts=True)

    now = timezone.now()
    # Reminders that are no longer true clear themselves.
    mine.filter(done_at__isnull=True, auto=True).exclude(key__in=list(wanted)).update(
        done_at=now, closed_by_system=True)
    # "You're on a shoot" clears once the shoot day has passed.
    mine.filter(done_at__isnull=True, auto=False, ref_date__lt=today).update(done_at=now, closed_by_system=True)
    # Housekeeping: forget finished notifications after 60 days.
    mine.filter(done_at__lt=now - timedelta(days=60)).delete()


def notify_assigned(session, added, removed):
    """Tell staff when they're put on (or taken off) a shoot."""
    b = session.booking
    for user in added:
        n, made = Notification.objects.get_or_create(
            user=user, key=f"assigned:{session.pk}:{session.date}",
            defaults=dict(studio=b.studio, kind=Notification.ASSIGNED, auto=False, ref_date=session.date,
                          title=f"You're on a shoot: {_event_title(session)}",
                          body=f"{session.date:%a %d %b}, {session.time_label} at {session.place}.",
                          url=b.get_absolute_url(), url_label="See details",
                          action_url=session.maps_url, action_label="Directions"),
        )
        if not made and n.done_at:
            n.done_at = n.read_at = None
            n.closed_by_system = False
            n.save(update_fields=["done_at", "read_at", "closed_by_system"])
        cache.delete(f"notif-refresh:{user.pk}")
    Notification.objects.filter(
        user__in=list(removed), key=f"assigned:{session.pk}:{session.date}", done_at__isnull=True,
    ).update(done_at=timezone.now(), closed_by_system=True)


def unread_count(user, studio):
    return Notification.objects.filter(user=user, studio=studio, done_at__isnull=True, read_at__isnull=True).count()
