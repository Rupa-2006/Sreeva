from django.conf import settings
from django.db import models


class Studio(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_studios"
    )
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=15)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=80, blank=True)
    # False until the owner finishes step 3 (resources) of the first-time setup.
    setup_complete = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    # --- Prices ----------------------------------------------------------------
    def single_item_packages(self):
        """Packages that are the price of ONE item, e.g. "tv" = 1 TV for ₹2,000.

        Many owners enter item prices this way, so they are treated as the
        price of that item: every item chosen on a booking adds up.
        """
        out = []
        for p in self.packages.filter(active=True).prefetch_related("items__resource_type").order_by("price"):
            items = list(p.items.all())
            if len(items) == 1 and items[0].quantity == 1:
                out.append((p, items[0].resource_type))
        return out

    def item_prices(self):
        """{resource id: (price for one, where it came from)}.

        The resource's own "Price for one" wins; otherwise a single-item package
        for that resource is used.
        """
        from_packages = {}
        for p, rt in self.single_item_packages():
            from_packages.setdefault(rt.id, p)
        out = {}
        for rt in self.resources.all():
            if rt.rate:
                out[rt.id] = (rt.rate, "")
            elif rt.id in from_packages:
                out[rt.id] = (from_packages[rt.id].price, from_packages[rt.id].name)
            else:
                out[rt.id] = (rt.rate, "")
        return out

    def combo_packages(self, queryset=None):
        """Real combos (more than one item) — the ones offered in the package dropdown."""
        qs = queryset if queryset is not None else self.packages.filter(active=True)
        singles = [p.pk for p, _ in self.single_item_packages()]
        return qs.exclude(pk__in=singles)


class ResourceType(models.Model):
    """Something the studio has a limited number of: people or equipment.

    Example: Photographer x3, Videographer x2, Drone x1, LED Screen x1.
    Bookings reserve a quantity of each for a time slot, which is how the app
    knows what is still available on a given date.
    """

    PEOPLE = "people"
    EQUIPMENT = "equipment"
    CATEGORY_CHOICES = [(PEOPLE, "People"), (EQUIPMENT, "Equipment")]

    studio = models.ForeignKey(Studio, on_delete=models.CASCADE, related_name="resources")
    name = models.CharField(max_length=60)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default=PEOPLE)
    count = models.PositiveIntegerField(default=1)
    rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="What you charge for one of these per event. Used to calculate the event price automatically.",
    )
    active = models.BooleanField(default=True, help_text="Untick instead of deleting, so old bookings keep their history.")

    class Meta:
        ordering = ["-category", "name"]  # people first, then equipment
        constraints = [
            models.UniqueConstraint(fields=["studio", "name"], name="unique_resource_name_per_studio")
        ]

    def __str__(self):
        return f"{self.name} ×{self.count}"


DEFAULT_RESOURCES = [
    ("Photographer", ResourceType.PEOPLE, 2),
    ("Candid Photographer", ResourceType.PEOPLE, 1),
    ("Videographer", ResourceType.PEOPLE, 2),
    ("Drone", ResourceType.EQUIPMENT, 1),
    ("LED Screen", ResourceType.EQUIPMENT, 1),
    ("Lighting Kit", ResourceType.EQUIPMENT, 2),
]


class Package(models.Model):
    """A ready-made offer, e.g. "Wedding – Gold": ₹75,000 with 2 photographers,
    2 videographers and a drone. Choosing it on an event fills the price and team
    in one click (both can still be changed for that booking)."""

    studio = models.ForeignKey(Studio, on_delete=models.CASCADE, related_name="packages")
    name = models.CharField(max_length=80)
    event_type = models.CharField(max_length=20, blank=True, help_text="Optional: suggest it for this event type")
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    description = models.CharField(max_length=200, blank=True, help_text="e.g. 300 edited photos, 1 album, highlight video")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price", "name"]
        constraints = [
            models.UniqueConstraint(fields=["studio", "name"], name="unique_package_name_per_studio")
        ]

    def __str__(self):
        return self.name

    def quantities(self):
        return {i.resource_type_id: i.quantity for i in self.items.all()}


class PackageItem(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="items")
    resource_type = models.ForeignKey(ResourceType, on_delete=models.CASCADE, related_name="package_items")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["package", "resource_type"], name="unique_item_per_package")
        ]
