from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.shortcuts import redirect, render

from accounts.audit import log
from bookings.utils import format_inr
from accounts.decorators import owner_required
from accounts.models import Profile

from .forms import ResourceFormSet, StudioForm
from .models import DEFAULT_RESOURCES, ResourceType


@login_required
def setup_studio(request):
    """First-time: create the studio. Later: edit its details (owner only)."""
    studio = request.studio
    if studio is not None and not request.is_owner:
        raise PermissionDenied
    if studio is None and request.profile.role != Profile.OWNER:
        raise PermissionDenied

    form = StudioForm(request.POST or None, instance=studio)
    if request.method == "POST" and form.is_valid():
        creating = studio is None
        with transaction.atomic():
            studio = form.save(commit=False)
            if creating:
                studio.owner = request.user
                studio.setup_complete = False
            studio.save()
            if creating:
                Profile.objects.filter(user=request.user).update(studio=studio, role=Profile.OWNER)
                ResourceType.objects.bulk_create(
                    ResourceType(studio=studio, name=n, category=c, count=k)
                    for n, c, k in DEFAULT_RESOURCES
                )
        request.studio = studio
        log(request, "Studio created" if creating else "Studio details updated", detail=studio.name, studio=studio)
        if creating:
            messages.success(
                request,
                "Studio saved. We've filled in common resources — change them to match what you actually have.",
            )
            return redirect("setup_resources")
        messages.success(request, "Studio details saved.")
        if not studio.setup_complete:
            return redirect("setup_resources")
        return redirect("setup_studio")

    return render(
        request,
        "studios/setup_studio.html",
        {"form": form, "creating": studio is None, "nav": "settings", "tab": "details", "step_no": "2"},
    )


@owner_required
def setup_resources(request):
    qs = ResourceType.objects.filter(studio=request.studio).annotate(n_used=Count("usages"))
    formset = ResourceFormSet(request.POST or None, queryset=qs)
    if request.method == "POST" and formset.is_valid():
        objs = formset.save(commit=False)
        removed, hidden = [], []
        with transaction.atomic():
            # 1. Removals. A resource already used in bookings can't be deleted
            #    (old bookings would lose their history), so it is switched off instead.
            for obj in formset.deleted_objects:
                if obj.usages.exists():
                    obj.active = False
                    obj.save(update_fields=["active"])
                    hidden.append(obj.name)
                else:
                    removed.append(obj.name)
                    obj.delete()

            # 2. Edits and new rows.
            existing = {
                r.name.lower(): r.pk for r in ResourceType.objects.filter(studio=request.studio)
            }
            skipped = []
            for obj in objs:
                obj.name = obj.name.strip()
                owner_pk = existing.get(obj.name.lower())
                if owner_pk and owner_pk != obj.pk:
                    skipped.append(obj.name)
                    continue
                obj.studio = request.studio
                obj.save()
                existing[obj.name.lower()] = obj.pk

        active = ResourceType.objects.filter(studio=request.studio, active=True)
        detail = ", ".join(f"{r.name} ×{r.count}" for r in active)
        if removed:
            detail = f"Removed {', '.join(removed)}. " + detail
        log(request, "Resources updated", detail=detail)

        if removed:
            messages.success(request, f"Removed: {', '.join(removed)}.")
        if hidden:
            messages.info(
                request,
                f"{', '.join(hidden)} {'is' if len(hidden) == 1 else 'are'} used in past bookings, so "
                "it was switched off instead of deleted. It won't appear in new bookings. "
                "Tick “In use” to bring it back.",
            )
        if skipped:
            messages.warning(request, f"Not saved — this name already exists: {', '.join(skipped)}.")

        if not request.studio.setup_complete:
            if not active.exists():
                messages.error(request, "Add at least one resource (for example: Photographer ×1) to finish setup.")
                return redirect("setup_resources")
            request.studio.setup_complete = True
            request.studio.save(update_fields=["setup_complete"])
            log(request, "Studio setup completed")
            messages.success(
                request,
                f"Setup complete — welcome to Sreeva! You can change studio details and resources "
                f"any time from “Studio settings” in the menu.",
            )
            return redirect("dashboard")

        messages.success(request, "Resources saved. Availability will use these counts.")
        return redirect("setup_resources")
    # Costs entered earlier as single-item packages are filled in here, so the
    # owner only has to click Save to keep every cost in one place.
    prices = request.studio.item_prices()
    prefilled = 0
    if not formset.is_bound:
        for f in formset.forms:
            if f.instance.pk and not f.instance.rate:
                price, source = prices.get(f.instance.pk, (0, ""))
                if source:
                    f.initial["rate"] = int(price) if price == int(price) else price
                    f.price_note = f"Filled in from package “{source}” — click Save to keep it here"
                    prefilled += 1
    if prefilled:
        messages.info(request, f"{prefilled} cost{'s' if prefilled > 1 else ''} filled in from your packages. "
                               f"Click “Save resources” to keep them here.")
    return render(request, "studios/setup_resources.html", {"formset": formset, "nav": "settings", "tab": "resources", "step_no": "3"})


# --- Packages ---------------------------------------------------------------

@owner_required
def package_list(request):
    from .models import Package
    packages = Package.objects.filter(studio=request.studio).prefetch_related("items__resource_type")
    return render(request, "studios/packages.html", {
        "packages": packages, "nav": "settings", "tab": "packages",
        "single_items": _single_item_packages(request.studio),
    })


@owner_required
def package_edit(request, pk=None):
    from django.shortcuts import get_object_or_404

    from .forms import PackageForm
    from .models import Package
    package = Package(studio=request.studio) if pk is None else get_object_or_404(Package, pk=pk, studio=request.studio)
    form = PackageForm(request.POST or None, instance=package, studio=request.studio)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            package = form.save(commit=False)
            package.studio = request.studio
            package.save()
            form.save_items(package)
        log(request, "Package saved", detail=f"{package.name} {format_inr(package.price)}")
        messages.success(request, f"Package “{package.name}” saved. Pick it on any event to fill the price and team.")
        return redirect("package_list")
    return render(request, "studios/package_form.html", {"form": form, "package": package, "nav": "settings", "tab": "packages"})


@owner_required
def package_delete(request, pk):
    from django.shortcuts import get_object_or_404
    from django.views.decorators.http import require_POST  # noqa: F401

    from .models import Package
    if request.method != "POST":
        return redirect("package_list")
    package = get_object_or_404(Package, pk=pk, studio=request.studio)
    name = package.name
    package.delete()  # old bookings keep their price and team; only the shortcut is removed
    log(request, "Package deleted", detail=name)
    messages.success(request, f"Package “{name}” deleted. Existing bookings are not changed.")
    return redirect("package_list")


def _single_item_packages(studio):
    return studio.single_item_packages()


@owner_required
def package_convert(request):
    """One click: turn single-item packages into item prices, then remove those packages."""
    if request.method != "POST":
        return redirect("package_list")
    moved = []
    with transaction.atomic():
        for package, rt in _single_item_packages(request.studio):
            rt.rate = package.price
            rt.save(update_fields=["rate"])
            moved.append(f"{rt.name} {format_inr(package.price)}")
            package.delete()  # bookings keep their saved price; only the shortcut goes
    if moved:
        log(request, "Single-item packages moved to item prices", detail=", ".join(moved))
        messages.success(request, "Done. These are now item prices, so every item you choose adds up: " + ", ".join(moved) + ".")
    return redirect("setup_resources")
