"""Availability engine.

A resource (e.g. Photographer ×3) is "in use" by every CONFIRMED session whose
time overlaps on the same date. Two time ranges overlap when
    start_a < end_b  and  end_a > start_b
Freelancers hired from outside don't consume the studio's own count.
"""
from collections import defaultdict

from django.db.models import F, Sum

from .models import Booking, Session, SessionResource


def overlapping(qs, date, start, end):
    return qs.filter(date=date, start_time__lt=end, end_time__gt=start)


def booked_usage(studio, date, start, end, exclude_booking_id=None):
    """{resource_type_id: in-house quantity already reserved by other confirmed bookings}."""
    qs = SessionResource.objects.filter(
        session__booking__studio=studio,
        session__booking__status=Booking.CONFIRMED,
        session__date=date,
        session__start_time__lt=end,
        session__end_time__gt=start,
    )
    if exclude_booking_id:
        qs = qs.exclude(session__booking_id=exclude_booking_id)
    rows = qs.values("resource_type").annotate(used=Sum(F("quantity") - F("freelancers")))
    return {r["resource_type"]: r["used"] or 0 for r in rows}


def availability(studio, date, start, end, exclude_booking_id=None):
    usage = booked_usage(studio, date, start, end, exclude_booking_id)
    out = []
    for r in studio.resources.filter(active=True):
        used = usage.get(r.id, 0)
        out.append({
            "id": r.id,
            "name": r.name,
            "category": r.category,
            "total": r.count,
            "used": used,
            "free": max(r.count - used, 0),
        })
    return out


def plan_capacity(studio, booking_id, planned, allow_freelancers):
    """Check a booking's sessions against what's free.

    planned: list of dicts {key, label, date, start, end, needs: {resource_id: qty}}
             (needs = quantity that must come from the studio's own team/kit)
    Returns (errors, freelancers):
        errors      {key: [message, ...]}   when short and freelancers not allowed
        freelancers {key: {resource_id: n}} how many to hire when allowed
    Sessions inside the same booking that overlap each other also compete.
    """
    resources = {r.id: r for r in studio.resources.all()}
    errors, freelancers = defaultdict(list), defaultdict(dict)
    allocated = []  # (plan, {rid: in-house qty}) already placed from this booking

    for plan in planned:
        usage = booked_usage(studio, plan["date"], plan["start"], plan["end"], booking_id)
        mine = {}
        for rid, qty in plan["needs"].items():
            if not qty or rid not in resources:
                continue
            same_booking = sum(
                alloc.get(rid, 0)
                for other, alloc in allocated
                if other["date"] == plan["date"]
                and other["start"] < plan["end"]
                and other["end"] > plan["start"]
            )
            res = resources[rid]
            used_elsewhere = usage.get(rid, 0)
            free = max(res.count - used_elsewhere - same_booking, 0)
            short = qty - free
            if short > 0:
                if allow_freelancers:
                    freelancers[plan["key"]][rid] = short
                else:
                    errors[plan["key"]].append(
                        f"{plan['label']}: needs {qty} {res.name}, but only {free} free "
                        f"({res.count} total, {used_elsewhere + same_booking} busy at that time)."
                    )
            mine[rid] = qty - max(short, 0)
        allocated.append((plan, mine))
    return dict(errors), dict(freelancers)


def capacity_for_existing(booking):
    """Re-check an existing booking (used when an enquiry is being confirmed)."""
    planned = []
    for s in booking.sessions.prefetch_related("resource_needs"):
        planned.append({
            "key": s.pk,
            "label": f"{s.name} on {s.date:%d %b}",
            "date": s.date,
            "start": s.start_time,
            "end": s.end_time,
            "needs": {n.resource_type_id: n.in_house for n in s.resource_needs.all()},
        })
    errors, _ = plan_capacity(booking.studio, booking.pk, planned, allow_freelancers=False)
    return [m for msgs in errors.values() for m in msgs]


def staff_conflicts(session, users):
    """Other confirmed shoots at an overlapping time that these staff are already on."""
    qs = overlapping(
        Session.objects.filter(
            booking__studio=session.booking.studio,
            booking__status=Booking.CONFIRMED,
            assigned_staff__in=users,
        ).exclude(pk=session.pk),
        session.date, session.start_time, session.end_time,
    ).select_related("booking__client").prefetch_related("assigned_staff")
    conflicts = []
    ids = {u.pk for u in users}
    for other in qs.distinct():
        for u in other.assigned_staff.all():
            if u.pk in ids:
                conflicts.append((u, other))
    return conflicts
