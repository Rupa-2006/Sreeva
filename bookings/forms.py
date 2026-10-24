from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import Booking, Client, Payment, Session
from .utils import format_inr, normalize_phone

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
TIME = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class BookingForm(forms.ModelForm):
    client_phone = forms.CharField(
        label="Phone number", max_length=16,
        widget=forms.TextInput(attrs={"inputmode": "tel", "placeholder": "98480 12345", "autocomplete": "off"}),
    )
    client_name = forms.CharField(label="Customer name", max_length=120)

    advance_mode = forms.ChoiceField(
        label="Advances paid by", choices=Payment.MODE_CHOICES, required=False,
    )

    allow_freelancers = forms.BooleanField(
        required=False,
        label="Hire freelancers / rent if we're short",
    )

    class Meta:
        model = Booking
        fields = ["event_type", "title", "status", "delivery_due", "notes"]
        widgets = {
            "delivery_due": DATE,
            "status": forms.Select(attrs={"data-chips": "1"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Special requests, poses, family members to cover, album type…"}),
            "title": forms.TextInput(attrs={"placeholder": "Optional, e.g. Ravi weds Sita"}),
        }
        labels = {"title": "Booking title"}

    def __init__(self, *args, creating=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.creating = creating
        if creating:  # a new booking is never "cancelled"
            self.fields["status"].widget.attrs["data-chips-hide"] = "cancelled"
        self.fields["delivery_due"].help_text = ""
        c = self.instance.client if self.instance.pk else None
        if c and not self.is_bound:
            self.initial.update(client_phone=c.phone, client_name=c.name)

    def clean_client_phone(self):
        phone = normalize_phone(self.cleaned_data["client_phone"])
        if not phone:
            raise forms.ValidationError("Enter a valid 10-digit mobile number.")
        return phone


class SessionForm(forms.ModelForm):
    items_error = ""

    class Meta:
        model = Session
        # Function name and notes are no longer asked for (kept in the database for old bookings).
        fields = ["package", "date", "slot", "start_time", "end_time", "place", "amount", "extra_charges"]
        widgets = {
            "amount": forms.NumberInput(attrs={"min": 0, "step": "1", "placeholder": "0", "data-price": "1"}),
            "date": DATE,
            "start_time": TIME,
            "end_time": TIME,
            "place": forms.TextInput(),
        }
        labels = {"amount": "Price for this event (₹)"}

    extra_charges = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"data-charges-input": "1"}))

    def __init__(self, *args, resource_types=(), packages=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            import json
            self.initial["extra_charges"] = json.dumps(self.instance.extra_charges or [])
        self.resource_types = list(resource_types)
        pk_field = self.fields["package"]
        pk_field.queryset = packages if packages is not None else pk_field.queryset.none()
        pk_field.required = False
        pk_field.empty_label = "— No package (enter price & team yourself) —"
        pk_field.label = "Package"
        pk_field.help_text = ""
        pk_field.label_from_instance = lambda p: f"{p.name} · {format_inr(p.price)}"
        pk_field.widget.attrs["data-package"] = "1"
        self.fields["amount"].help_text = ""
        self.already_paid = self.instance.paid if self.instance.pk else Decimal("0")
        self.fields["advance"] = forms.DecimalField(
            label="Advance received now (₹)", required=False, min_value=0, max_digits=12, decimal_places=2,
            widget=forms.NumberInput(attrs={"min": 0, "step": "1", "placeholder": "0"}),
        )
        self.fields["start_time"].required = False
        self.fields["end_time"].required = False
        # Function name is optional: left empty, the booking's event type is used (e.g. "Wedding").
        # One box for the location: a venue name, or a pasted Google Maps link (or both).
        self.fields["place"].max_length = 800
        self.fields["place"].widget.attrs["maxlength"] = 800
        self.fields["place"].help_text = ""
        self.fields["place"].widget.attrs["placeholder"] = "Venue, or paste a Google Maps link"
        existing = {}
        if self.instance.pk:
            existing = {n.resource_type_id: n.quantity for n in self.instance.resource_needs.all()}
        for rt in self.resource_types:
            self.fields[f"res_{rt.id}"] = forms.IntegerField(
                label=rt.name, min_value=0, max_value=99, required=False,
                initial=existing.get(rt.id, 0),
                widget=forms.NumberInput(attrs={"min": 0, "max": 99, "data-resource": rt.id}),
            )

    @property
    def resource_fields(self):
        return [(rt, self[f"res_{rt.id}"]) for rt in self.resource_types]

    def clean_place(self):
        """Split a pasted Google Maps link out of the place text.

        "Sri Lakshmi Hall https://maps.app.goo.gl/abc" -> place "Sri Lakshmi Hall" + saved link.
        No link and the place changed -> any old link is dropped (it pointed to the old place).
        """
        import re
        from django.core.validators import URLValidator
        from django.core.exceptions import ValidationError as DjangoValidationError
        text = (self.cleaned_data.get("place") or "").strip()
        match = re.search(r"https?://\S+", text)
        if match:
            link = match.group(0).rstrip(".,)")
            try:
                URLValidator()(link)
            except DjangoValidationError:
                raise forms.ValidationError("That map link doesn't look right. Copy it again from Google Maps.")
            if len(link) > 500:
                raise forms.ValidationError("That map link is too long. Use the “Share” link from Google Maps.")
            self.instance.map_link = link
            text = (text[:match.start()] + " " + text[match.end():]).strip(" ,-–") or Session.PINNED
        elif text != (self.instance.place or ""):
            self.instance.map_link = ""
        text = " ".join(text.split())
        if not text:
            raise forms.ValidationError("Enter the venue name or paste a Google Maps link.")
        if len(text) > 200:
            raise forms.ValidationError("Keep the place under 200 characters.")
        return text

    def clean_extra_charges(self):
        """Delivery, travel, extra album… as a small checked list (never trust the browser)."""
        import json
        raw = self.cleaned_data.get("extra_charges") or "[]"
        try:
            items = json.loads(raw)
        except ValueError:
            raise forms.ValidationError("Extra charges could not be read. Please re-enter them.")
        if not isinstance(items, list) or len(items) > 20:
            raise forms.ValidationError("Too many extra charges (max 20).")
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            label = str(it.get("label", "")).strip()[:60]
            try:
                amount = Decimal(str(it.get("amount", "")).strip() or "0")
            except Exception:
                raise forms.ValidationError(f"“{label or 'Extra charge'}” needs a valid amount.")
            if not amount:
                continue
            if abs(amount) > Decimal("10000000"):
                raise forms.ValidationError("An extra charge is too large.")
            out.append({"label": label or ("Discount" if amount < 0 else "Extra charge"),
                        "amount": int(amount) if amount == int(amount) else float(amount)})
        return out

    def clean(self):
        data = super().clean()
        slot = data.get("slot")
        if slot == Session.CUSTOM:
            start, end = data.get("start_time"), data.get("end_time")
            if not start or not end:
                raise forms.ValidationError("Enter start and end time for a custom slot.")
            if end <= start:
                raise forms.ValidationError("End time must be after start time.")
        elif slot in Session.SLOT_TIMES:
            data["start_time"], data["end_time"] = Session.SLOT_TIMES[slot]
        price = data.get("amount") or Decimal("0")
        advance = data.get("advance") or Decimal("0")
        if self.already_paid and price < self.already_paid:
            self.add_error("amount", f"{format_inr(self.already_paid)} is already paid for this event, so the price can't be lower.")
        elif advance and self.already_paid + advance > price:
            left = price - self.already_paid
            self.add_error("advance", f"Only {format_inr(max(left, 0))} is left to pay for this event.")
        # every confirmed event needs at least one item (photographer, videographer, drone...);
        # an enquiry can be saved without, the customer may not have decided yet
        is_enquiry = self.data.get("status") in (Booking.ENQUIRY, Booking.CANCELLED)
        if self.resource_types and not is_enquiry and not any((data.get(f"res_{rt.id}") or 0) > 0 for rt in self.resource_types):
            self.items_error = ITEMS_REQUIRED
            self.add_error(None, ITEMS_REQUIRED)
        return data

    def needs(self):
        return {rt.id: self.cleaned_data.get(f"res_{rt.id}") or 0 for rt in self.resource_types}


ITEMS_REQUIRED = "Pick at least one item for this event."


class BaseSessionFormSet(forms.BaseInlineFormSet):
    def live_forms(self):
        """Forms that will actually be saved (not deleted, not left blank)."""
        out = []
        for f in self.forms:
            if not hasattr(f, "cleaned_data") or not f.cleaned_data:
                continue
            if self.can_delete and self._should_delete_form(f):
                continue
            out.append(f)
        return out

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not self.live_forms():
            raise forms.ValidationError("Add at least one event date.")
        for f in self.deleted_forms:
            if f.instance.pk and f.instance.payments.exists():
                raise forms.ValidationError(
                    f"“{f.instance.name}” already has payments, so it can't be removed. "
                    f"Delete or move its payments first (open the payment and change the event)."
                )


SessionFormSet = forms.inlineformset_factory(
    Booking, Session, form=SessionForm, formset=BaseSessionFormSet,
    extra=0, min_num=1, validate_min=True, can_delete=True,
)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["session", "amount", "date", "mode", "reference", "note"]
        widgets = {"date": DATE, "amount": forms.NumberInput(attrs={"min": 1, "step": "1"})}
        labels = {"amount": "Amount (₹)", "reference": "Transaction ID", "session": "For which event?"}

    def __init__(self, *args, booking=None, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.booking = booking
        sessions = booking.sessions.with_money() if booking is not None else Session.objects.none()
        self.sessions = list(sessions)
        field = self.fields["session"]
        field.queryset = sessions
        field.required = True
        field.empty_label = None
        field.help_text = "Each event has its own price and pending amount."
        field.label_from_instance = lambda s: (
            f"{s.name} · {s.date:%d %b} — pending {format_inr(max(s.amount - s.paid_total, 0))} of {format_inr(s.amount)}"
        )
        # When editing, this payment's own (old) amount is available again.
        self.original = (self.instance.session_id, self.instance.amount) if self.instance.pk else (None, Decimal("0"))
        if not self.is_bound and not self.instance.pk:
            self.initial.setdefault("date", timezone.localdate())
            chosen = session or next((s for s in self.sessions if s.amount > s.paid_total), None) or (
                self.sessions[0] if self.sessions else None)
            if chosen is not None:
                self.initial["session"] = chosen.pk
                left = max(chosen.amount - chosen.paid_total, Decimal("0"))
                if left:
                    self.initial["amount"] = int(left) if left == int(left) else left

    def limit_for(self, session):
        left = session.amount - session.paid
        if self.original[0] == session.pk:
            left += self.original[1]
        return max(left, Decimal("0"))

    def clean(self):
        data = super().clean()
        session, amount = data.get("session"), data.get("amount")
        if session is not None and amount:
            limit = self.limit_for(session)
            if amount > limit:
                self.add_error(
                    "amount",
                    f"Only {format_inr(limit)} is pending for {session.name}. If its price changed, edit the booking first.",
                )
        return data

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d > timezone.localdate():
            raise forms.ValidationError("Payment date can't be in the future.")
        return d


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["name", "phone", "alt_phone", "address", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not phone:
            raise forms.ValidationError("Enter a valid 10-digit mobile number.")
        dupes = Client.objects.filter(studio=self.instance.studio, phone=phone).exclude(pk=self.instance.pk)
        if dupes.exists():
            raise forms.ValidationError("Another client already has this number.")
        return phone

    def clean_alt_phone(self):
        raw = self.cleaned_data.get("alt_phone")
        if not raw:
            return ""
        phone = normalize_phone(raw)
        if not phone:
            raise forms.ValidationError("Enter a valid 10-digit mobile number.")
        return phone


class QuickBookingForm(forms.Form):
    """The 30-second version of a booking: who, what, when, how much.
    Everything else (venue, map, team, more events) can be added later with Edit."""

    phone = forms.CharField(
        label="Phone number", max_length=16,
        widget=forms.TextInput(attrs={"inputmode": "tel", "placeholder": "98480 12345", "autocomplete": "off", "autofocus": True}),
    )
    name = forms.CharField(label="Customer name", max_length=120)
    event_type = forms.ChoiceField(label="Event type", choices=Booking.EVENT_TYPES, initial="wedding")
    date = forms.DateField(label="Date", widget=DATE)
    slot = forms.ChoiceField(
        label="Time", initial=Session.FULL,
        choices=[c for c in Session.SLOT_CHOICES if c[0] != Session.CUSTOM],
    )
    place = forms.CharField(label="Place", max_length=200, required=False,
                            widget=forms.TextInput(attrs={"placeholder": "Optional — add later"}))
    package = forms.ModelChoiceField(label="Package", queryset=None, required=False,
                                     empty_label="— No package —")
    price = forms.DecimalField(label="Price (₹)", min_value=0, max_digits=12, decimal_places=2, required=False,
                               widget=forms.NumberInput(attrs={"min": 0, "step": "1", "placeholder": "0"}))
    advance = forms.DecimalField(label="Advance paid now (₹)", min_value=0, max_digits=12, decimal_places=2,
                                 required=False, widget=forms.NumberInput(attrs={"min": 0, "step": "1", "placeholder": "0"}))
    advance_mode = forms.ChoiceField(label="Paid by", choices=Payment.MODE_CHOICES, required=False)
    status = forms.ChoiceField(
        label="This is a…", choices=[(Booking.CONFIRMED, "Confirmed booking"), (Booking.ENQUIRY, "Enquiry only (just asking)")],
        initial=Booking.CONFIRMED, widget=forms.RadioSelect,
    )
    allow_freelancers = forms.BooleanField(required=False, label="If we're short on people or equipment, I'll hire freelancers / rent")

    def __init__(self, *args, packages=None, **kwargs):
        super().__init__(*args, **kwargs)
        from studios.models import Package
        self.fields["package"].queryset = packages if packages is not None else Package.objects.none()
        self.fields["package"].label_from_instance = lambda p: f"{p.name} · {format_inr(p.price)}"
        self.fields["package"].widget.attrs["data-package"] = "1"

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not phone:
            raise forms.ValidationError("Enter a valid 10-digit mobile number.")
        return phone

    def clean(self):
        data = super().clean()
        package = data.get("package")
        price = data.get("price")
        if price in (None, "") and package is not None:
            price = data["price"] = package.price
        price = price or Decimal("0")
        data["price"] = price
        advance = data.get("advance") or Decimal("0")
        if advance > price:
            self.add_error("advance", "Advance can't be more than the price.")
        return data
