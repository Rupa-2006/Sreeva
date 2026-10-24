"""Backup & export page: Excel download of the studio's records + database backups."""
from datetime import date

from django.contrib import messages
from django.db.models import Count, Max, Min, Prefetch, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.audit import log
from accounts.decorators import owner_required

from . import backup, xlsx
from .models import Booking, Client, Payment, Session, SessionResource
from .xlsx import DATE, MONEY, NUMBER, TEXT


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@owner_required
def backup_page(request):
    files = backup.list_backups()
    today = timezone.localdate()
    return render(request, "bookings/backup.html", {
        "nav": "backup", "tab": "backup", "files": files[:10], "count": len(files),
        "folder": backup.backup_dir().resolve(), "latest": files[0] if files else None,
        "month_start": today.replace(day=1), "today": today,
        "just_now": bool(files) and (timezone.now() - files[0]["when"]).total_seconds() < 60,
    })


@owner_required
@require_POST
def backup_now(request):
    path = backup.make_backup()
    log(request, "Backup made", detail=path.name if path else "not sqlite")
    messages.success(request, "Backup saved. ✓" if path else "Backups work only with the built-in database.")
    return redirect("backup")


@owner_required
def export_excel(request):
    """Everything for this studio in one Excel file: Bookings, Events, Payments, Customers."""
    studio = request.studio
    start, end = _date(request.GET.get("from")), _date(request.GET.get("to"))
    if start and end and start > end:
        start, end = end, start

    sessions = (
        Session.objects.filter(booking__studio=studio).with_money()
        .select_related("booking__client")
        .prefetch_related("assigned_staff",
                          Prefetch("resource_needs", queryset=SessionResource.objects.select_related("resource_type")))
        .order_by("date", "start_time")
    )
    payments = (Payment.objects.filter(booking__studio=studio)
                .select_related("booking__client", "session", "received_by").order_by("date", "pk"))
    bookings = (Booking.objects.filter(studio=studio).with_money().select_related("client")
                .annotate(first=Min("sessions__date"), last=Max("sessions__date")).order_by("first"))
    if start:
        sessions, payments, bookings = (sessions.filter(date__gte=start), payments.filter(date__gte=start),
                                        bookings.filter(last__gte=start))
    if end:
        sessions, payments, bookings = (sessions.filter(date__lte=end), payments.filter(date__lte=end),
                                        bookings.filter(first__lte=end))

    sheets = [
        ("Bookings", [("Booking #", NUMBER, 10), ("Customer", TEXT, 22), ("Phone", TEXT, 13),
                      ("Event type", TEXT, 18), ("Booking name", TEXT, 26), ("Status", TEXT, 11),
                      ("Album delivered", TEXT, 15), ("First date", DATE, 13), ("Last date", DATE, 13),
                      ("Total", MONEY, 13), ("Paid", MONEY, 13), ("Pending", MONEY, 13),
                      ("Delivery due", DATE, 13), ("Notes", TEXT, 40)],
         [[b.pk, b.client.name, b.client.phone, b.get_event_type_display(), b.display_title,
           b.get_status_display(), "Yes" if b.album_delivered else "", b.first, b.last,
           b.total_amount, b.paid_total, max(b.pending_total, 0), b.delivery_due, b.notes] for b in bookings]),
        ("Events", [("Booking #", NUMBER, 10), ("Customer", TEXT, 22), ("Function", TEXT, 20),
                    ("Date", DATE, 13), ("Time", TEXT, 14), ("Place", TEXT, 34), ("Needs", TEXT, 36),
                    ("Team", TEXT, 20), ("Status", TEXT, 11), ("Price", MONEY, 13), ("Paid", MONEY, 13),
                    ("Pending", MONEY, 13), ("Notes", TEXT, 30)],
         [[s.booking_id, s.booking.client.name, s.name, s.date, s.time_label, s.place,
           ", ".join(f"{n.quantity} {n.resource_type.name}" for n in s.resource_needs.all()),
           ", ".join(u.first_name or u.username for u in s.assigned_staff.all()),
           s.booking.get_status_display(), s.amount, s.paid_total, max(s.pending_total, 0), s.notes]
          for s in sessions]),
        ("Payments", [("Receipt", TEXT, 16), ("Date", DATE, 13), ("Customer", TEXT, 22), ("Booking #", NUMBER, 10),
                      ("For event", TEXT, 22), ("Amount", MONEY, 13), ("Mode", TEXT, 22),
                      ("Reference", TEXT, 18), ("Note", TEXT, 24), ("Received by", TEXT, 14)],
         [[p.receipt_no, p.date, p.booking.client.name, p.booking_id, p.session.label if p.session else "",
           p.amount, p.get_mode_display(), p.reference, p.note,
           (p.received_by.first_name or p.received_by.username) if p.received_by else ""] for p in payments]),
    ]
    clients = (Client.objects.filter(studio=studio)
               .annotate(n=Count("bookings", distinct=True)).order_by("name"))
    business = dict(Booking.objects.filter(studio=studio, status=Booking.CONFIRMED)
                    .values_list("client").annotate(s=Sum("total_amount")))
    paid = dict(Payment.objects.filter(booking__studio=studio).values_list("booking__client").annotate(s=Sum("amount")))
    sheets.append(("Customers", [("Name", TEXT, 22), ("Phone", TEXT, 13), ("Alternate phone", TEXT, 15),
                                 ("Address", TEXT, 36), ("Bookings", NUMBER, 10), ("Total business", MONEY, 15),
                                 ("Paid", MONEY, 13), ("Customer since", DATE, 14)],
                   [[c.name, c.phone, c.alt_phone, c.address, c.n, business.get(c.pk, 0), paid.get(c.pk, 0),
                     timezone.localtime(c.created_at).date()] for c in clients]))

    span = (f"{start:%d-%b-%Y} to {end:%d-%b-%Y}" if start and end else
            f"from {start:%d-%b-%Y}" if start else f"until {end:%d-%b-%Y}" if end else "all time")
    log(request, "Exported to Excel", detail=span)
    name = f"{studio.name} {span}" if (start or end) else f"{studio.name} till {timezone.localdate():%d-%b-%Y}"
    safe = "".join(ch for ch in name if ch.isalnum() or ch in " -_").strip()[:80] or "Sreeva export"
    resp = HttpResponse(xlsx.workbook(sheets),
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{safe}.xlsx"'
    return resp
