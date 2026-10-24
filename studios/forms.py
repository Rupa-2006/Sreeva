from django import forms

from bookings.utils import normalize_phone

from .models import Package, PackageItem, ResourceType, Studio


class StudioForm(forms.ModelForm):
    class Meta:
        model = Studio
        fields = ["name", "phone", "email", "address", "city"]
        labels = {"name": "Studio name", "phone": "Studio phone"}

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if not phone:
            raise forms.ValidationError("Enter a valid 10-digit mobile number.")
        return phone


class ResourceForm(forms.ModelForm):
    class Meta:
        model = ResourceType
        fields = ["name", "category", "count", "rate", "active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Photographer, Drone"}),
            "count": forms.NumberInput(attrs={"min": 0, "max": 99}),
            "rate": forms.NumberInput(attrs={"min": 0, "step": "1", "placeholder": "0"}),
        }
        labels = {"rate": "Cost for one (₹)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rate"].required = False  # empty box = not charged separately
        rate = self.initial.get("rate")
        if rate is not None and rate == int(rate):
            self.initial["rate"] = int(rate)  # show 8000, not 8000.00

    def clean_rate(self):
        from decimal import Decimal
        return self.cleaned_data.get("rate") or Decimal("0")


class BaseResourceFormSet(forms.BaseModelFormSet):
    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data.get("name"):
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            key = form.cleaned_data["name"].strip().lower()
            if key in seen:
                form.add_error("name", "This name is already in the list.")
            seen.add(key)


ResourceFormSet = forms.modelformset_factory(
    ResourceType, form=ResourceForm, formset=BaseResourceFormSet, extra=0, can_delete=True
)


class PackageForm(forms.ModelForm):
    """Name, price and how many of each resource the package includes."""

    class Meta:
        model = Package
        fields = ["name", "event_type", "price", "description", "active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Wedding – Gold"}),
            "price": forms.NumberInput(attrs={"min": 0, "step": "1"}),
            "description": forms.TextInput(attrs={"placeholder": "e.g. 300 edited photos, 1 album, highlight video"}),
        }
        labels = {"price": "Price (₹)", "event_type": "Usually for", "active": "Show this package when booking"}

    def __init__(self, *args, studio=None, **kwargs):
        super().__init__(*args, **kwargs)
        from bookings.models import Booking
        self.studio = studio
        self.fields["event_type"] = forms.ChoiceField(
            label="Usually for", required=False,
            choices=[("", "Any event")] + list(Booking.EVENT_TYPES),
        )
        self.resource_types = list(studio.resources.filter(active=True)) if studio else []
        have = self.instance.quantities() if self.instance.pk else {}
        for rt in self.resource_types:
            self.fields[f"res_{rt.id}"] = forms.IntegerField(
                label=rt.name, min_value=0, max_value=99, required=False, initial=have.get(rt.id, 0),
                widget=forms.NumberInput(attrs={"min": 0, "max": 99}),
            )

    @property
    def resource_fields(self):
        return [(rt, self[f"res_{rt.id}"]) for rt in self.resource_types]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        dupes = Package.objects.filter(studio=self.studio, name__iexact=name).exclude(pk=self.instance.pk)
        if dupes.exists():
            raise forms.ValidationError("You already have a package with this name.")
        return name

    def save_items(self, package):
        for rt in self.resource_types:
            qty = self.cleaned_data.get(f"res_{rt.id}") or 0
            if qty:
                PackageItem.objects.update_or_create(package=package, resource_type=rt, defaults={"quantity": qty})
            else:
                PackageItem.objects.filter(package=package, resource_type=rt).delete()
