"""Fill the database with a realistic demo studio for presentations.

    python manage.py seed_demo            # create demo data
    python manage.py seed_demo --reset    # delete the old demo studio first

Logins created:
    owner  / Studio@2026   (studio owner – sees everything)
    ravi   / Staff@2026    (photographer – staff view, no money)
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Profile
from bookings.models import Booking, Client, Payment, Session, SessionResource
from studios.models import DEFAULT_RESOURCES, ResourceType, Studio


class Command(BaseCommand):
    help = "Create a demo studio with sample bookings, payments and staff."

    # who gets created (the online "Try the demo" studio uses other names, see setup_demo)
    OWNER, OWNER_PASSWORD, STAFF_PASSWORD, STAFF_PREFIX = "owner", "Studio@2026", "Staff@2026", ""
    STUDIO_NAME, OWNER_EMAIL = "Sri Sai Photography", "owner@srisaiphoto.example"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Remove the existing demo studio first")

    def staff_names(self):
        return [self.STAFF_PREFIX + n for n in ("ravi", "kiran", "suresh")]

    @transaction.atomic
    def handle(self, *args, reset=False, **opts):
        if reset:
            for s in Studio.objects.filter(owner__username=self.OWNER):
                Payment.objects.filter(booking__studio=s).delete()
                Booking.objects.filter(studio=s).delete()
                s.delete()
            User.objects.filter(username__in=[self.OWNER] + self.staff_names()).delete()
        if User.objects.filter(username=self.OWNER).exists():
            self.stdout.write(self.style.WARNING("Demo data already exists. Use --reset to recreate."))
            return

        owner = User.objects.create_user(
            self.OWNER, email=self.OWNER_EMAIL, password=self.OWNER_PASSWORD, first_name="Srinivas"
        )
        studio = Studio.objects.create(
            owner=owner, name=self.STUDIO_NAME, phone="9848012345",
            address="Main Road, near Bus Stand", city="Tirupati",
        )
        Profile.objects.filter(user=owner).update(studio=studio, role=Profile.OWNER, phone="9848012345")

        counts = {"Photographer": 3, "Candid Photographer": 1, "Videographer": 2,
                  "Drone": 1, "LED Screen": 1, "Lighting Kit": 2}
        rates = {"Photographer": 8000, "Candid Photographer": 12000, "Videographer": 10000,
                 "Drone": 6000, "LED Screen": 8000, "Lighting Kit": 2000}
        res = {}
        for name, cat, _ in DEFAULT_RESOURCES:
            res[name] = ResourceType.objects.create(studio=studio, name=name, category=cat,
                                                    count=counts[name], rate=rates[name])

        from studios.models import Package, PackageItem
        for pname, etype, price, desc, items in [
            ("Birthday – Basic", "birthday", 15000, "Photos + 1 short video", {"Photographer": 1, "Videographer": 1}),
            ("Wedding – Silver", "wedding", 60000, "300 photos, 1 album, full video", {"Photographer": 2, "Videographer": 1}),
            ("Wedding – Gold", "wedding", 120000, "Candid + drone + LED, 2 albums, highlight film",
             {"Photographer": 2, "Candid Photographer": 1, "Videographer": 2, "Drone": 1, "LED Screen": 1}),
        ]:
            pk = Package.objects.create(studio=studio, name=pname, event_type=etype, price=price, description=desc)
            for rname, q in items.items():
                PackageItem.objects.create(package=pk, resource_type=res[rname], quantity=q)

        staff = {}
        for username, first, designation in [
            ("ravi", "Ravi", "Photographer"), ("kiran", "Kiran", "Videographer"), ("suresh", "Suresh", "Editor"),
        ]:
            u = User.objects.create_user(self.STAFF_PREFIX + username, password=self.STAFF_PASSWORD, first_name=first)
            Profile.objects.filter(user=u).update(studio=studio, role=Profile.STAFF, designation=designation)
            staff[username] = u

        today = timezone.localdate()
        d = lambda n: today + timedelta(days=n)  # noqa: E731

        def booking(name, phone, event, total, status, work, sessions, payments=(), title="", due=None, notes=""):
            client, _ = Client.objects.get_or_create(studio=studio, phone=phone, defaults={"name": name})
            b = Booking.objects.create(
                studio=studio, client=client, title=title, event_type=event, status=status,
                work_status=work, total_amount=Decimal(total), delivery_due=due, notes=notes, created_by=owner,
            )
            created = []
            for s in sessions:
                needs = s.pop("needs")
                team = s.pop("team", [])
                price = s.pop("price", total if len(sessions) == 1 else 0)
                sess = Session.objects.create(booking=b, amount=Decimal(price), **s)
                for rname, qty in needs.items():
                    SessionResource.objects.create(session=sess, resource_type=res[rname], quantity=qty)
                sess.assigned_staff.set([staff[t] for t in team])
                created.append(sess)
            for pay in payments:
                amount, days_ago, mode = pay[:3]
                ev = created[pay[3] if len(pay) > 3 else 0]
                Payment.objects.create(booking=b, session=ev, amount=Decimal(amount), date=d(-days_ago), mode=mode,
                                       received_by=owner, note="Advance" if days_ago > 20 else "")
            b.sync_total()
            return b

        C, E, X = Booking.CONFIRMED, Booking.ENQUIRY, Booking.CANCELLED
        booking("Ramesh Naidu", "9876543210", "wedding", 185000, C, Booking.W_UPCOMING, title="Ramesh weds Lakshmi",
                notes="Cover both families' entry. Traditional album + 1 candid album.", due=d(45), sessions=[
                    dict(name="Haldi / Pellikuthuru", date=d(0), slot="morning", place="Bride's house, KT Road",
                         needs={"Photographer": 1, "Videographer": 1}, team=["ravi"], price=35000),
                    dict(name="Muhurtham", date=d(1), slot="full", place="Sri Padmavathi Kalyana Mandapam, Tiruchanur Road",
                         needs={"Photographer": 2, "Candid Photographer": 1, "Videographer": 2, "Drone": 1, "LED Screen": 1},
                         team=["ravi", "kiran"], price=150000),
                ], payments=[(15000, 30, "upi", 0), (50000, 30, "upi", 1), (10000, 3, "cash", 1)])
        booking("Priya Reddy", "9123456780", "birthday", 18000, C, Booking.W_UPCOMING, sessions=[
            dict(name="1st Birthday", date=d(0), slot="evening", place="Hotel Bliss, Renigunta Road",
                 needs={"Photographer": 1, "Videographer": 1, "Lighting Kit": 1}, team=["kiran"]),
        ], payments=[(5000, 10, "upi")])
        booking("Venkatesh K", "9988776655", "half_saree", 45000, C, Booking.W_UPCOMING, sessions=[
            dict(name="Half Saree Function", date=d(5), slot="morning", place="Annamayya Kalyana Vedika, AIR Bypass Road",
                 needs={"Photographer": 2, "Videographer": 1, "LED Screen": 1}),
        ], payments=[(15000, 6, "cash")])
        booking("Sandeep & Anusha", "9000011111", "pre_wedding", 30000, C, Booking.W_UPCOMING, sessions=[
            dict(name="Pre-wedding outdoor", date=d(9), slot="custom", start_time="06:00", end_time="10:00",
                 place="Talakona Waterfalls", needs={"Photographer": 1, "Candid Photographer": 1, "Drone": 1}),
        ], payments=[(10000, 4, "upi")])
        booking("Harsha Vardhan", "9111122222", "engagement", 40000, E, Booking.W_UPCOMING, sessions=[
            dict(name="Engagement", date=d(12), slot="evening", place="Function hall, Bairagipatteda",
                 needs={"Photographer": 2, "Videographer": 1}),
        ])
        booking("Madhavi S", "9222233333", "naming", 12000, C, Booking.W_UPCOMING, sessions=[
            dict(name="Cradle ceremony", date=d(18), slot="morning", place="Residence, Korlagunta",
                 needs={"Photographer": 1}),
        ])
        # Past events in the post-production pipeline
        booking("Suresh Babu", "9333344444", "wedding", 150000, C, Booking.W_EDITING, title="Suresh weds Kavya",
                due=d(20), sessions=[
                    dict(name="Muhurtham", date=d(-12), slot="full", place="TTD Kalyana Mandapam, Balaji Colony",
                         needs={"Photographer": 2, "Videographer": 2, "Drone": 1}),
                ], payments=[(60000, 40, "bank"), (40000, 12, "cash")])
        booking("Anil Kumar", "9444455555", "housewarming", 15000, C, Booking.W_READY, due=d(-2), sessions=[
            dict(name="Gruhapravesam", date=d(-20), slot="morning", place="New house, Alipiri", needs={"Photographer": 1}),
        ], payments=[(5000, 25, "upi")])
        booking("Kavitha R", "9555566666", "reception", 60000, C, Booking.W_ALBUM, due=d(-5), sessions=[
            dict(name="Reception", date=d(-35), slot="evening", place="Hotel Marasa Sarovar",
                 needs={"Photographer": 2, "Videographer": 1, "LED Screen": 1}),
        ], payments=[(20000, 50, "upi"), (20000, 35, "cash")])
        booking("Ganesh T", "9666677777", "birthday", 10000, C, Booking.W_DELIVERED, sessions=[
            dict(name="Birthday", date=d(-40), slot="evening", place="Residence, Tilak Road", needs={"Photographer": 1}),
        ], payments=[(10000, 38, "cash")])
        booking("Lokesh P", "9777788888", "corporate", 25000, X, Booking.W_UPCOMING, sessions=[
            dict(name="College fest", date=d(7), slot="full", place="SV University", needs={"Photographer": 2}),
        ])

        if hasattr(studio, "setup_complete"):
            Studio.objects.filter(pk=studio.pk).update(setup_complete=True)
        self.stdout.write(self.style.SUCCESS(
            f"Demo studio ready.\n  Owner login:  {self.OWNER} / {self.OWNER_PASSWORD}"
            f"\n  Staff login:  {self.STAFF_PREFIX}ravi / {self.STAFF_PASSWORD}"
        ))
