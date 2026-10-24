import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Min, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.audit import log
from accounts.decorators import owner_required, studio_required
from accounts.models import Profile

from .forms import BookingForm, ClientForm, PaymentForm, SessionFormSet
from .models import Booking, Client, Notification, Payment, Session, SessionResource
from . import notifications as notif
from .services import availability, capacity_for_existing, plan_capacity, staff_conflicts
from .utils import format_inr, normalize_phone


def _sessions(studio):
    return (
        Session.objects.filter(booking__studio=studio)
        .exclude(booking__status=Booking.CANCELLED)
        .select_related("booking__client", "booking__studio")
        .prefetch_related("resource_needs__resource_type", "assigned_staff")
    )


def _item_price_data(studio, resource_types):
    """{resource id: {name, rate}} — price for one of each item, for the booking form."""
    prices = studio.item_prices()
    return {str(rt.id): {"name": rt.name, "rate": float(prices.get(rt.id, (rt.rate, ""))[0]), "count": rt.count}
            for rt in resource_types}


def _package_data(packages):
    """{package id: {price, items: {resource id: qty}}} for the booking form's JavaScript."""
    return {
        str(p.pk): {"name": p.name, "event_type": p.event_type,
                    "price": str(int(p.price)) if p.price == int(p.price) else str(p.price),
                    "items": {str(i.resource_type_id): i.quantity for i in p.items.all()}}
        for p in packages
    }


def _event_pending(booking):
    """{event id: pending amount} for the payment page (amount auto-fills when you switch event)."""
    out = {}
    for s in booking.sessions.with_money():
        left = max(s.amount - s.paid_total, Decimal("0"))
        out[str(s.pk)] = str(int(left)) if left == int(left) else str(left)
    return out


def _event_dues(studio):
    """Every event of a confirmed booking that still has money pending."""
    return (
        Session.objects.filter(booking__studio=studio, booking__status=Booking.CONFIRMED)
        .with_money().filter(pending_total__gt=0)
        .select_related("booking__client", "booking__studio")
    )


# --- Dashboard --------------------------------------------------------------

def _greeting():
    hour = timezone.localtime().hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"


@studio_required
def dashboard(request):
    studio = request.studio
    today = timezone.localdate()
    sessions = _sessions(studio)

    ctx = {
        "nav": "dashboard",
        "today": today,
        "greeting": _greeting(),
        "today_sessions": sessions.filter(date=today),
        "tomorrow_sessions": sessions.filter(date=today + timedelta(days=1)),
        "upcoming_sessions": sessions.filter(date__gt=today + timedelta(days=1), date__lte=today + timedelta(days=30))[:5],
        "my_sessions": sessions.filter(assigned_staff=request.user, date__gte=today)[:8],
    }

    confirmed = Booking.objects.filter(studio=studio, status=Booking.CONFIRMED)
    deliveries = (
        confirmed.exclude(work_status=Booking.W_DELIVERED)
        .annotate(last_date=Max("sessions__date"))
        .filter(last_date__lt=today)
        .select_related("client")
        .order_by("delivery_due", "last_date")
    )
    ctx["pending_deliveries"] = deliveries[:10]
    ctx["pending_deliveries_count"] = deliveries.count()
    ctx["overdue_count"] = deliveries.filter(delivery_due__lt=today).count()
    ctx["enquiries"] = (
        Booking.objects.filter(studio=studio, status=Booking.ENQUIRY)
        .annotate(first_date=Min("sessions__date"))
        .filter(first_date__gte=today)
        .select_related("client")
        .order_by("first_date")[:6]
    )

    if request.is_owner:
        dues = _event_dues(studio)  # one row per EVENT, each billed separately
        ctx["pending_total"] = dues.aggregate(s=Sum("pending_total"))["s"] or Decimal("0")
        ctx["dues"] = dues.order_by("-pending_total")[:5]
        ctx["dues_count"] = dues.count()
        month_start = today.replace(day=1)
        ctx["collected_month"] = (
            Payment.objects.filter(booking__studio=studio, date__gte=month_start, date__lte=today)
            .aggregate(s=Sum("amount"))["s"] or Decimal("0")
        )
        ctx["bookings_month"] = (
            Session.objects.filter(
                booking__studio=studio, booking__status=Booking.CONFIRMED,
                date__year=today.year, date__month=today.month,
            ).values("booking").distinct().count()
        )
    return render(request, "bookings/dashboard.html", ctx)


# --- Bookings ---------------------------------------------------------------

@studio_required
def booking_list(request):
    studio = request.studio
    today = timezone.localdate()
    qs = (
        Booking.objects.filter(studio=studio)
        .with_money()
        .select_related("client")
        .annotate(first_date=Min("sessions__date"), last_date=Max("sessions__date"), n_sessions=Count("sessions"))
    )
    q = request.GET.get("q", "").strip()
    if q:
        digits = normalize_phone(q) or q
        qs = qs.filter(
            Q(client__name__icontains=q) | Q(title__icontains=q)
            | Q(client__phone__icontains=digits) | Q(sessions__place__icontains=q)
        ).distinct()
    status = request.GET.get("status", "")
    if status in dict(Booking.STATUS_CHOICES):
        qs = qs.filter(status=status)
    work = request.GET.get("work", "")
    if work == "delivered":
        qs = qs.filter(work_status=Booking.W_DELIVERED)
    elif work == "pending":
        qs = qs.filter(status=Booking.CONFIRMED, last_date__lt=today).exclude(work_status=Booking.W_DELIVERED)
    when = request.GET.get("when", "upcoming")
    if when == "upcoming":
        qs = qs.filter(last_date__gte=today).order_by("first_date")
    elif when == "past":
        qs = qs.filter(last_date__lt=today).order_by("-last_date")
    elif when == "dues" and request.is_owner:
        qs = qs.filter(pending_total__gt=0, status=Booking.CONFIRMED).order_by("-pending_total")
    else:
        when = "all"
        qs = qs.order_by("-first_date")

    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "bookings/booking_list.html", {
        "page": page, "q": q, "status": status, "work": work, "when": when,
        "status_choices": Booking.STATUS_CHOICES, "work_choices": Booking.WORK_CHOICES,
        "nav": "bookings", "today": today,
    })


def _save_needs(session, needs, freelancers):
    for rid, qty in needs.items():
        if qty and qty > 0:
            SessionResource.objects.update_or_create(
                session=session, resource_type_id=rid,
                defaults={"quantity": qty, "freelancers": min(freelancers.get(rid, 0), qty)},
            )
        else:
            SessionResource.objects.filter(session=session, resource_type_id=rid).delete()


@owner_required
def booking_edit(request, pk=None):
    studio = request.studio
    creating = pk is None
    booking = Booking(studio=studio) if creating else get_object_or_404(Booking, pk=pk, studio=studio)
    resource_types = list(studio.resources.filter(active=True))
    packages = studio.combo_packages().prefetch_related("items")
    if booking.pk:  # keep any package this booking already uses selectable (even hidden / single-item ones)
        used = studio.packages.filter(sessions__booking=booking).values_list("pk", flat=True)
        combo_ids = studio.combo_packages().values_list("pk", flat=True)
        packages = studio.packages.filter(Q(pk__in=list(combo_ids)) | Q(pk__in=list(used))).distinct().prefetch_related("items")
    fs_kwargs = {"form_kwargs": {"resource_types": resource_types, "packages": packages}, "prefix": "sessions"}

    if request.method == "POST":
        form = BookingForm(request.POST, instance=booking, creating=creating)
        formset = SessionFormSet(request.POST, instance=booking, **fs_kwargs)
        if form.is_valid() and formset.is_valid():
            live = formset.live_forms()
            event_label = dict(Booking.EVENT_TYPES).get(form.cleaned_data["event_type"], "Main event")
            for f in live:  # new events are named after the event type; old names are kept
                if not f.instance.pk or not f.instance.name or f.instance.name == "Main event":
                    # one event: "Wedding"; several: "Wedding – Morning", "Wedding – Evening"
                    f.instance.name = event_label if len(live) == 1 else f"{event_label} – {f.instance.time_label}"
                f.cleaned_data["name"] = f.instance.name
            planned = [{
                "key": f.prefix,
                "label": f"{f.cleaned_data['name']} on {f.cleaned_data['date']:%d %b}",
                "date": f.cleaned_data["date"],
                "start": f.cleaned_data["start_time"],
                "end": f.cleaned_data["end_time"],
                "needs": f.needs(),
            } for f in live]

            errors, freelancers = {}, {}
            if form.cleaned_data["status"] == Booking.CONFIRMED:
                errors, freelancers = plan_capacity(
                    studio, booking.pk, planned, form.cleaned_data.get("allow_freelancers")
                )
            if errors:
                for f in live:
                    for msg in errors.get(f.prefix, []):
                        f.add_error(None, msg)
                messages.error(
                    request,
                    "Not enough people/equipment free for some dates. Reduce the numbers, pick another "
                    "slot, or tick “Hire freelancers / rent if we're short”.",
                )
            else:
                with transaction.atomic():
                    cd = form.cleaned_data
                    client, made = Client.objects.get_or_create(
                        studio=studio, phone=cd["client_phone"],
                        defaults={"name": cd["client_name"]},
                    )
                    if not made:
                        client.name = cd["client_name"]
                        client.save()
                    booking = form.save(commit=False)
                    booking.client = client
                    if creating:
                        booking.created_by = request.user
                    booking.save()

                    formset.instance = booking
                    formset.save(commit=False)
                    for obj in formset.deleted_objects:
                        obj.delete()
                    for f in live:
                        session = f.save(commit=False)
                        session.booking = booking
                        session.save()
                        _save_needs(session, f.needs(), freelancers.get(f.prefix, {}))
                        advance = f.cleaned_data.get("advance")
                        if advance:
                            Payment.objects.create(
                                booking=booking, session=session, amount=advance, date=timezone.localdate(),
                                mode=cd.get("advance_mode") or Payment.CASH, note="Advance",
                                received_by=request.user,
                            )
                    booking.sync_total()
                hired = sum(sum(v.values()) for v in freelancers.values())
                log(request, "Booking created" if creating else "Booking edited",
                    detail=f"#{booking.pk} {booking.display_title}")
                messages.success(request, "Booking saved.")
                if hired:  # important: shown even though "saved" messages are quiet
                    messages.warning(request, f"Arrange {hired} freelancer/rental slot(s) — marked on the booking.")
                return redirect(f"{booking.get_absolute_url()}?saved=1")
        else:
            messages.error(request, "Please fix the highlighted fields.")
    else:
        initial = {}
        if creating and request.GET.get("date"):  # e.g. "Book this date" from the dashboard
            first = {"date": request.GET["date"]}
            if request.GET.get("slot") in dict(Session.SLOT_CHOICES):
                first["slot"] = request.GET["slot"]
            initial = [first]
        form = BookingForm(instance=booking, creating=creating)
        formset = SessionFormSet(instance=booking, initial=initial or None, **fs_kwargs)

    return render(request, "bookings/booking_form.html", {
        "form": form, "formset": formset, "booking": booking, "creating": creating,
        "resource_types": resource_types, "nav": "new" if creating else "bookings",
        "package_data": _package_data(packages),
        "resource_rates": _item_price_data(studio, resource_types),
    })


@owner_required
def quick_booking(request):
    """Quick booking was removed (it skipped details that had to be added later).
    Old links and bookmarks open the full booking form instead, keeping the date."""
    url = reverse("booking_new")
    keep = {k: request.GET[k] for k in ("date", "slot") if request.GET.get(k)}
    if keep:
        from urllib.parse import urlencode
        url += "?" + urlencode(keep)
    return redirect(url)


@studio_required
def booking_detail(request, pk):
    booking = get_object_or_404(
        Booking.objects.select_related("client", "studio", "created_by"), pk=pk, studio=request.studio
    )
    sessions = booking.sessions.with_money().prefetch_related("resource_needs__resource_type", "assigned_staff")
    staff = User.objects.filter(profile__studio=request.studio, is_active=True).order_by("first_name")
    ctx = {
        "booking": booking, "sessions": sessions, "staff": staff, "nav": "bookings",
        "today": timezone.localdate(),
        "work_choices": Booking.WORK_CHOICES,
    }
    if request.is_owner:
        ctx["payments"] = booking.payments.select_related("received_by", "session")
        rid = request.GET.get("receipt", "")
        if rid.isdigit() and booking.payments.filter(pk=rid).exists():
            ctx["receipt_id"] = int(rid)
        ctx["just_saved"] = request.GET.get("saved") == "1" and booking.status != Booking.CANCELLED
    return render(request, "bookings/booking_detail.html", ctx)


@studio_required
@require_POST
def booking_status(request, pk):
    booking = get_object_or_404(Booking, pk=pk, studio=request.studio)
    work = request.POST.get("work_status")
    status = request.POST.get("status")

    if work in (Booking.W_DELIVERED, Booking.W_UPCOMING):
        booking.work_status = work
        booking.save(update_fields=["work_status", "updated_at"])
        done = work == Booking.W_DELIVERED
        log(request, "Album delivered" if done else "Album marked not delivered", detail=f"#{booking.pk} {booking.display_title}")
        messages.success(request, f"Album for {booking.display_title} marked as delivered. ✓" if done
                         else "Marked as not delivered yet.")
        back = request.POST.get("next", "")
        if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(back)
    elif status in dict(Booking.STATUS_CHOICES):
        if not request.is_owner:
            messages.error(request, "Only the owner can confirm or cancel bookings.")
            return redirect(booking)
        if status == Booking.CONFIRMED and booking.status != Booking.CONFIRMED:
            problems = capacity_for_existing(booking)
            if problems:
                for p in problems:
                    messages.error(request, p)
                messages.info(request, "Edit the booking to change numbers or allow freelancers, then confirm.")
                return redirect(booking)
        booking.status = status
        booking.save(update_fields=["status", "updated_at"])
        log(request, "Booking status changed", detail=f"#{booking.pk} → {booking.get_status_display()}")
        messages.success(request, f"Booking {booking.get_status_display().lower()}.")
    return redirect(booking)


@owner_required
@require_POST
def booking_delete(request, pk):
    booking = get_object_or_404(Booking, pk=pk, studio=request.studio)
    if booking.payments.exists():
        messages.error(request, "This booking has payments. Cancel it instead of deleting, so your accounts stay correct.")
        return redirect(booking)
    title = booking.display_title
    booking.delete()
    log(request, "Booking deleted", detail=title)
    messages.success(request, "Booking deleted.")
    return redirect("booking_list")


@owner_required
@require_POST
def session_assign(request, pk):
    session = get_object_or_404(Session.objects.select_related("booking"), pk=pk, booking__studio=request.studio)
    ids = request.POST.getlist("staff")
    users = list(User.objects.filter(pk__in=ids, profile__studio=request.studio, is_active=True))
    conflicts = staff_conflicts(session, users)
    if conflicts and not request.POST.get("force"):
        for user, other in conflicts:
            messages.error(
                request,
                f"{user.first_name or user.username} is already on “{other.booking.display_title} – {other.name}” "
                f"({other.time_label}) that day.",
            )
        messages.info(request, "Pick someone else, or tick “Assign anyway”.")
        return redirect(session.booking)
    before = set(session.assigned_staff.all())
    session.assigned_staff.set(users)
    notif.notify_assigned(session, added=set(users) - before, removed=before - set(users))
    names = ", ".join(u.first_name or u.username for u in users) or "nobody"
    log(request, "Staff assigned", detail=f"{session} → {names}")
    messages.success(request, f"Team for {session.name}: {names}.")
    return redirect(session.booking)


# --- Payments ---------------------------------------------------------------

@owner_required
def payment_add(request, pk):
    """Record a new payment (part or full) for a booking.

    GET shows a simple page with the booking's total / paid / pending and the form;
    the same form also sits on the booking page and POSTs here.
    """
    booking = get_object_or_404(Booking.objects.select_related("client", "studio"), pk=pk, studio=request.studio)
    sid = request.GET.get("event", "")
    chosen = booking.sessions.with_money().filter(pk=sid).first() if sid.isdigit() else None
    form = PaymentForm(request.POST or None, booking=booking, session=chosen)
    if request.method == "POST":
        if form.is_valid():
            payment = form.save(commit=False)
            payment.booking = booking
            payment.received_by = request.user
            payment.save()
            ev = Session.objects.get(pk=payment.session_id)  # fresh totals, after this payment
            log(request, "Payment recorded",
                detail=f"{format_inr(payment.amount)} for #{booking.pk} {ev.name} ({payment.get_mode_display()})")
            left = ev.pending
            msg = f"{format_inr(payment.amount)} received for {ev.name} ({ev.date:%d %b}). "
            msg += f"{ev.name} is fully paid now. 🎉" if not left else f"Still pending for {ev.name}: {format_inr(left)}."
            messages.success(request, msg)
            return redirect(f"{booking.get_absolute_url()}?receipt={payment.pk}")
        if request.POST.get("from") != "page":
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
            return redirect(booking)
    return render(request, "bookings/payment_form.html", {
        "booking": booking, "form": form, "nav": "payments", "editing": False,
        "payments": booking.payments.select_related("session"),
        "events": booking.sessions.with_money(),
        "event_pending": _event_pending(booking),
    })


@owner_required
def payment_edit(request, pk):
    """Correct a payment that was entered wrongly (amount, date, mode, transaction ID)."""
    payment = get_object_or_404(
        Payment.objects.select_related("booking__client", "booking__studio"), pk=pk, booking__studio=request.studio
    )
    booking = payment.booking
    before = f"{format_inr(payment.amount)} on {payment.date:%d %b %Y} ({payment.get_mode_display()}) for {payment.session.name if payment.session else '-'}"
    form = PaymentForm(request.POST or None, instance=payment, booking=booking)
    if request.method == "POST" and form.is_valid():
        payment = form.save()
        after = f"{format_inr(payment.amount)} on {payment.date:%d %b %Y} ({payment.get_mode_display()}) for {payment.session.name}"
        log(request, "Payment edited", detail=f"#{booking.pk}: {before} → {after}")
        messages.success(request, f"Payment updated. Pending now {format_inr(booking.pending)}.")
        return redirect(booking)
    return render(request, "bookings/payment_form.html", {
        "booking": booking, "form": form, "payment": payment, "nav": "payments", "editing": True,
        "payments": booking.payments.select_related("session"),
        "events": booking.sessions.with_money(),
        "event_pending": _event_pending(booking),
    })


@owner_required
@require_POST
def payment_delete(request, pk):
    payment = get_object_or_404(Payment, pk=pk, booking__studio=request.studio)
    booking = payment.booking
    log(request, "Payment deleted", detail=f"{format_inr(payment.amount)} of {payment.date} from #{booking.pk}")
    payment.delete()
    messages.success(request, "Payment removed.")
    return redirect(booking)


@owner_required
def payment_receipt(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("booking__client", "booking__studio", "received_by"),
        pk=pk, booking__studio=request.studio,
    )
    return render(request, "bookings/receipt.html", {"payment": payment, "booking": payment.booking})


@owner_required
def payments_overview(request):
    studio = request.studio
    dues = _event_dues(studio).order_by("date", "start_time")
    recent = Payment.objects.filter(booking__studio=studio).select_related("booking__client", "session")[:25]
    today = timezone.localdate()
    # money received in each of the last 6 months, for the small bar chart
    months = []
    first = today.replace(day=1)
    for _ in range(6):
        months.insert(0, first)
        first = (first - timedelta(days=1)).replace(day=1)
    by_month = {}
    for p in Payment.objects.filter(booking__studio=studio, date__gte=months[0]).values("date", "amount"):
        key = p["date"].replace(day=1)
        by_month[key] = by_month.get(key, Decimal("0")) + p["amount"]
    top = max(by_month.values(), default=Decimal("0")) or Decimal("1")
    chart = [{"month": m, "amount": by_month.get(m, Decimal("0")),
              "pct": int(by_month.get(m, Decimal("0")) * 100 / top), "now": m == months[-1]} for m in months]
    return render(request, "bookings/payments.html", {
        "dues": dues, "recent": recent, "nav": "payments", "today": today, "chart": chart,
        "pending_total": dues.aggregate(s=Sum("pending_total"))["s"] or Decimal("0"),
        "collected_month": by_month.get(months[-1], Decimal("0")),
    })


# --- Calendar ---------------------------------------------------------------

@studio_required
def calendar_view(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("y", today.year))
        month = int(request.GET.get("m", today.month))
        first = date(year, month, 1)
    except (TypeError, ValueError):
        first = today.replace(day=1)
    cal = calendar.Calendar(firstweekday=6)  # weeks start on Sunday
    weeks = cal.monthdatescalendar(first.year, first.month)
    start, end = weeks[0][0], weeks[-1][-1]

    by_day = {}
    for s in Session.objects.filter(booking__studio=request.studio, date__range=(start, end)).exclude(
        booking__status=Booking.CANCELLED
    ).select_related("booking__client").prefetch_related("assigned_staff"):
        by_day.setdefault(s.date, []).append(s)

    grid = [[{"date": d, "in_month": d.month == first.month, "sessions": by_day.get(d, [])} for d in w] for w in weeks]
    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    # the day whose details are shown under / beside the calendar
    try:
        selected = date.fromisoformat(request.GET.get("d", ""))
        if (selected.year, selected.month) != (first.year, first.month):
            raise ValueError
    except ValueError:
        if (today.year, today.month) == (first.year, first.month):
            selected = today
        else:
            selected = next((d for d in sorted(by_day) if d.month == first.month), first)
    days = [(d, by_day.get(d, [])) for w in weeks for d in w if d.month == first.month]
    return render(request, "bookings/calendar.html", {
        "grid": grid, "month": first, "prev": prev_month, "next": next_month,
        "today": today, "days": days, "selected": selected, "nav": "calendar",
        "weekdays": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    })


# --- Clients ----------------------------------------------------------------

@studio_required
def client_list(request):
    q = request.GET.get("q", "").strip()
    qs = Client.objects.filter(studio=request.studio).annotate(
        n_bookings=Count("bookings"), last_event=Max("bookings__sessions__date")
    )
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=normalize_phone(q) or q))
    page = Paginator(qs.order_by("name"), 30).get_page(request.GET.get("page"))
    return render(request, "bookings/client_list.html", {"page": page, "q": q, "nav": "clients"})


@studio_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk, studio=request.studio)
    bookings = (
        client.bookings.with_money()
        .annotate(first_date=Min("sessions__date"))
        .order_by("-first_date")
    )
    form = None
    if request.is_owner:
        form = ClientForm(request.POST or None, instance=client)
        if request.method == "POST" and form.is_valid():
            form.save()
            log(request, "Client edited", detail=client.name)
            messages.success(request, "Client details saved.")
            return redirect(client)
    totals = bookings.filter(status=Booking.CONFIRMED).aggregate(
        business=Sum("total_amount"), pending=Sum("pending_total")
    )
    return render(request, "bookings/client_detail.html", {
        "client": client, "bookings": bookings, "form": form, "totals": totals, "nav": "clients",
    })


# --- JSON APIs used by the booking form --------------------------------------

def _parse_time(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return None


@studio_required
@require_GET
def api_availability(request):
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        return JsonResponse({"error": "Invalid date"}, status=400)
    slot = request.GET.get("slot", Session.FULL)
    if slot in Session.SLOT_TIMES:
        start, end = Session.SLOT_TIMES[slot]
    else:
        start, end = _parse_time(request.GET.get("start")), _parse_time(request.GET.get("end"))
        if not start or not end or end <= start:
            return JsonResponse({"error": "Enter a valid start and end time"}, status=400)
    exclude = request.GET.get("booking")
    exclude_id = int(exclude) if exclude and exclude.isdigit() else None
    if exclude_id and not Booking.objects.filter(pk=exclude_id, studio=request.studio).exists():
        exclude_id = None

    others = (
        Session.objects.filter(booking__studio=request.studio, booking__status=Booking.CONFIRMED,
                               date=day, start_time__lt=end, end_time__gt=start)
        .exclude(booking_id=exclude_id).select_related("booking__client")
    )
    whole_day = (
        Session.objects.filter(booking__studio=request.studio, date=day)
        .exclude(booking__status=Booking.CANCELLED).exclude(booking_id=exclude_id)
        .select_related("booking__client").order_by("start_time")
    )
    return JsonResponse({
        "resources": availability(request.studio, day, start, end, exclude_id),
        "clashes": [f"{s.booking.client.name} – {s.name} ({s.time_label})" for s in others[:5]],
        "day": [{
            "customer": s.booking.client.name, "event": s.name, "time": s.time_label,
            "place": s.place, "status": s.booking.get_status_display(),
            "overlaps": s.start_time < end and s.end_time > start,
            "url": s.booking.get_absolute_url(),
        } for s in whole_day[:12]],
        "date_label": f"{day:%a, %d %b %Y}",
    })


@owner_required
@require_GET
def api_client_lookup(request):
    phone = normalize_phone(request.GET.get("phone", ""))
    if not phone:
        return JsonResponse({"found": False})
    client = Client.objects.filter(studio=request.studio, phone=phone).annotate(n=Count("bookings")).first()
    if not client:
        return JsonResponse({"found": False})
    return JsonResponse({
        "found": True, "name": client.name, "alt_phone": client.alt_phone,
        "address": client.address, "bookings": client.n,
    })


# --- Notifications ----------------------------------------------------------

@studio_required
def notification_list(request):
    notif.refresh(request.user, request.studio, request.is_owner, force=True)
    mine = Notification.objects.filter(user=request.user, studio=request.studio)
    # Most time-critical first: today's shoots, then tomorrow, then anything urgent, then the rest.
    order = {Notification.SHOOT_TODAY: 0, Notification.ASSIGNED: 1, Notification.SHOOT_TOMORROW: 1}
    open_items = sorted(
        mine.filter(done_at__isnull=True),
        key=lambda n: (order.get(n.kind, 2 if n.urgent else 3), n.ref_date or timezone.localdate()),
    )
    done_items = mine.filter(done_at__isnull=False, done_at__gte=timezone.now() - timedelta(days=7)).order_by("-done_at")[:15]
    new_ids = {n.pk for n in open_items if not n.read_at}
    mine.filter(pk__in=new_ids).update(read_at=timezone.now())  # seen now
    return render(request, "bookings/notifications.html", {
        "nav": "notifications", "open_items": open_items, "done_items": done_items, "new_ids": new_ids,
        "notif_count": 0,
    })


@studio_required
@require_POST
def notification_done(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user, studio=request.studio)
    if request.POST.get("undo"):
        n.done_at = None
        n.closed_by_system = False
    else:
        n.done_at = n.done_at or timezone.now()
        n.read_at = n.read_at or timezone.now()
    n.save(update_fields=["done_at", "read_at", "closed_by_system"])
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": True, "count": notif.unread_count(request.user, request.studio)})
    return redirect("notifications")


@studio_required
@require_GET
def api_notifications(request):
    """Badge count + newest unread items, polled by the page for desktop alerts."""
    notif.refresh(request.user, request.studio, request.is_owner)
    unread = Notification.objects.filter(
        user=request.user, studio=request.studio, done_at__isnull=True, read_at__isnull=True,
    ).order_by("-pk")
    items = [{"id": n.pk, "title": n.title, "body": n.body, "url": reverse("notifications")} for n in unread[:5]]
    return JsonResponse({"count": unread.count(), "items": items})
