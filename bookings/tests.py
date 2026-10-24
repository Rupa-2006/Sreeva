import os
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, Profile
from studios.models import ResourceType, Studio

from .models import Booking, Client, Payment, Session, SessionResource
from .services import availability, plan_capacity
from .utils import format_inr, normalize_phone


def make_studio(username="owner", name="Test Studio"):
    owner = User.objects.create_user(username, password="Pass@12345", first_name="Owner")
    studio = Studio.objects.create(owner=owner, name=name, phone="9848012345")
    Profile.objects.filter(user=owner).update(studio=studio, role=Profile.OWNER)
    return owner, studio


def make_booking(studio, phone, day, slot, needs, status=Booking.CONFIRMED, total=10000):
    client, _ = Client.objects.get_or_create(studio=studio, phone=phone, defaults={"name": "C " + phone})
    b = Booking.objects.create(studio=studio, client=client, status=status, total_amount=Decimal(total))
    s = Session.objects.create(booking=b, name="Event", date=day, slot=slot, place="Hall", amount=Decimal(total))
    for rt, qty in needs.items():
        SessionResource.objects.create(session=s, resource_type=rt, quantity=qty)
    return b


class UtilsTests(TestCase):
    def test_phone_normalisation(self):
        self.assertEqual(normalize_phone("+91 98480-12345"), "9848012345")
        self.assertEqual(normalize_phone("09848012345"), "9848012345")
        self.assertEqual(normalize_phone("12345"), "")
        self.assertEqual(normalize_phone("1234567890"), "")  # Indian mobiles start 6-9

    def test_indian_currency_format(self):
        self.assertEqual(format_inr(1234567), "₹12,34,567")
        self.assertEqual(format_inr(Decimal("999.50")), "₹999.50")
        self.assertEqual(format_inr(0), "₹0")


class AvailabilityTests(TestCase):
    def setUp(self):
        self.owner, self.studio = make_studio()
        self.photo = ResourceType.objects.create(studio=self.studio, name="Photographer", count=3)
        self.drone = ResourceType.objects.create(studio=self.studio, name="Drone", category="equipment", count=1)
        self.day = timezone.localdate() + timedelta(days=10)

    def free(self, start, end, rt):
        return {r["id"]: r["free"] for r in availability(self.studio, self.day, start, end)}[rt.id]

    def test_overlapping_confirmed_booking_reduces_availability(self):
        make_booking(self.studio, "9000000001", self.day, Session.MORNING, {self.photo: 2, self.drone: 1})
        self.assertEqual(self.free(time(10), time(12), self.photo), 1)
        self.assertEqual(self.free(time(10), time(12), self.drone), 0)

    def test_non_overlapping_slot_is_free(self):
        make_booking(self.studio, "9000000001", self.day, Session.MORNING, {self.photo: 3})
        start, end = Session.SLOT_TIMES[Session.EVENING]
        self.assertEqual(self.free(start, end, self.photo), 3)

    def test_enquiries_and_cancelled_do_not_block(self):
        make_booking(self.studio, "9000000001", self.day, Session.FULL, {self.photo: 3}, status=Booking.ENQUIRY)
        make_booking(self.studio, "9000000002", self.day, Session.FULL, {self.photo: 3}, status=Booking.CANCELLED)
        self.assertEqual(self.free(time(9), time(10), self.photo), 3)

    def test_freelancers_do_not_use_studio_count(self):
        b = make_booking(self.studio, "9000000001", self.day, Session.FULL, {self.photo: 4})
        SessionResource.objects.filter(session__booking=b).update(freelancers=1)
        self.assertEqual(self.free(time(9), time(10), self.photo), 0)  # 3 in-house used

    def test_plan_capacity_blocks_or_hires(self):
        make_booking(self.studio, "9000000001", self.day, Session.FULL, {self.drone: 1})
        plan = [{"key": "a", "label": "Wedding", "date": self.day, "start": time(6), "end": time(13),
                 "needs": {self.drone.id: 1, self.photo.id: 2}}]
        errors, hired = plan_capacity(self.studio, None, plan, allow_freelancers=False)
        self.assertIn("Drone", errors["a"][0])
        errors, hired = plan_capacity(self.studio, None, plan, allow_freelancers=True)
        self.assertEqual(errors, {})
        self.assertEqual(hired["a"], {self.drone.id: 1})

    def test_sessions_in_same_booking_compete(self):
        plan = [
            {"key": "a", "label": "Haldi", "date": self.day, "start": time(6), "end": time(13), "needs": {self.photo.id: 2}},
            {"key": "b", "label": "Lunch", "date": self.day, "start": time(12), "end": time(15), "needs": {self.photo.id: 2}},
        ]
        errors, _ = plan_capacity(self.studio, None, plan, allow_freelancers=False)
        self.assertIn("b", errors)


class BookingFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.studio = make_studio()
        self.photo = ResourceType.objects.create(studio=self.studio, name="Photographer", count=2)
        self.client.login(username="owner", password="Pass@12345")
        self.day = (timezone.localdate() + timedelta(days=5)).isoformat()

    def post_booking(self, qty=1, status="confirmed", allow=False, advance="", name="Muhurtham", place="Hall"):
        data = {
            "client_phone": "98765 43210", "client_name": "Ramesh", "client_alt_phone": "", "client_address": "",
            "event_type": "wedding", "title": "", "status": status,
            "delivery_due": "", "notes": "", "advance_mode": "upi",
            "sessions-0-amount": "50000", "sessions-0-advance": advance,
            "sessions-TOTAL_FORMS": "1", "sessions-INITIAL_FORMS": "0",
            "sessions-MIN_NUM_FORMS": "1", "sessions-MAX_NUM_FORMS": "1000",
            "sessions-0-name": name, "sessions-0-date": self.day, "sessions-0-slot": "full",
            "sessions-0-start_time": "", "sessions-0-end_time": "", "sessions-0-place": place,
            "sessions-0-map_link": "", "sessions-0-notes": "", f"sessions-0-res_{self.photo.id}": str(qty),
        }
        if allow:
            data["allow_freelancers"] = "on"
        return self.client.post(reverse("booking_new"), data)

    def test_items_are_compulsory(self):
        """An event can't be saved without at least one item."""
        r = self.post_booking(qty=0)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Pick at least one item for this event.")
        self.assertEqual(Booking.objects.count(), 0)
        # an enquiry can be saved without items
        r = self.post_booking(qty=0, status="enquiry")
        self.assertEqual(r.status_code, 302)

    def test_whatsapp_booking_details(self):
        """After saving, the owner can send the customer the booking details on WhatsApp."""
        r = self.post_booking(qty=2, advance="10000")
        b = Booking.objects.get()
        self.assertRedirects(r, b.get_absolute_url() + "?saved=1")
        page = self.client.get(r.url)
        self.assertContains(page, "Send details")
        from urllib.parse import unquote
        text = unquote(b.wa_confirmation())
        self.assertIn("wa.me/919876543210", text)
        self.assertIn("confirmed", text)
        self.assertIn("2 Photographer", text)
        self.assertIn("Balance: ₹40,000", text)

    def test_function_name_is_optional(self):
        """No function name typed: the event is named after the event type."""
        page = self.client.get(reverse("booking_new"))
        self.assertNotContains(page, 'value="Main event"')
        r = self.post_booking(name="")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Booking.objects.get().sessions.get().name, "Wedding")

    def test_place_can_hold_a_pasted_maps_link(self):
        """No separate map box: a Maps link pasted into Place is saved as the event's map link."""
        self.assertNotContains(self.client.get(reverse("booking_new")), "map_link")
        r = self.post_booking(place="Sri Lakshmi Hall, Gandhi Road https://maps.app.goo.gl/AbC123")
        self.assertEqual(r.status_code, 302)
        s = Booking.objects.get().sessions.get()
        self.assertEqual(s.place, "Sri Lakshmi Hall, Gandhi Road")
        self.assertEqual(s.maps_url, "https://maps.app.goo.gl/AbC123")

    def test_place_name_only_gets_directions_automatically(self):
        self.post_booking(place="Sri Lakshmi Hall, Vijayawada")
        s = Booking.objects.get().sessions.get()
        self.assertEqual(s.map_link, "")
        self.assertIn("google.com/maps/search", s.maps_url)
        self.assertIn("Sri%20Lakshmi%20Hall", s.maps_url)

    def test_place_link_only(self):
        self.post_booking(place="https://maps.app.goo.gl/XyZ")
        s = Booking.objects.get().sessions.get()
        self.assertEqual(s.place, "Location on map")
        self.assertEqual(s.maps_url, "https://maps.app.goo.gl/XyZ")
        self.assertContains(self.client.get(s.booking.get_absolute_url()), 'href="https://maps.app.goo.gl/XyZ"')

    def test_create_booking_with_advance(self):
        r = self.post_booking(qty=2, advance="10000")
        self.assertEqual(r.status_code, 302)
        b = Booking.objects.get()
        self.assertEqual(b.client.phone, "9876543210")
        self.assertEqual(b.sessions.get().resource_needs.get().quantity, 2)
        self.assertEqual(b.pending, Decimal("40000"))
        self.assertTrue(AuditLog.objects.filter(action="Booking created").exists())

    def test_overbooking_is_refused_then_allowed_with_freelancers(self):
        r = self.post_booking(qty=3)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "only 2 free")
        self.assertEqual(Booking.objects.count(), 0)
        r = self.post_booking(qty=3, allow=True)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SessionResource.objects.get().freelancers, 1)

    def test_enquiry_cannot_be_confirmed_when_team_is_busy(self):
        self.post_booking(qty=2)
        self.post_booking(qty=2, status="enquiry")
        enquiry = Booking.objects.get(status=Booking.ENQUIRY)
        self.client.post(reverse("booking_status", args=[enquiry.pk]), {"status": "confirmed"})
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.status, Booking.ENQUIRY)

    def test_payment_cannot_exceed_pending(self):
        self.post_booking()
        b = Booking.objects.get()
        self.client.post(reverse("payment_add", args=[b.pk]), {"session": b.sessions.get().pk, "amount": "60000", "date": timezone.localdate(), "mode": "cash"})
        self.assertEqual(b.payments.count(), 0)
        self.client.post(reverse("payment_add", args=[b.pk]), {"session": b.sessions.get().pk, "amount": "20000", "date": timezone.localdate(), "mode": "cash"})
        self.assertEqual(b.pending, Decimal("30000"))

    def test_extra_charges_saved_and_shown(self):
        import json
        self.post_booking(advance="")  # base booking
        b = Booking.objects.get()
        s = b.sessions.get()
        data = {
            "client_phone": "9876543210", "client_name": "Ramesh", "client_alt_phone": "", "client_address": "",
            "event_type": "wedding", "title": "", "status": "confirmed", "delivery_due": "", "notes": "", "advance_mode": "cash",
            "sessions-TOTAL_FORMS": "1", "sessions-INITIAL_FORMS": "1", "sessions-MIN_NUM_FORMS": "1", "sessions-MAX_NUM_FORMS": "1000",
            "sessions-0-id": s.pk, "sessions-0-name": "Muhurtham", "sessions-0-date": self.day, "sessions-0-slot": "full",
            "sessions-0-start_time": "", "sessions-0-end_time": "", "sessions-0-place": "Hall", "sessions-0-map_link": "",
            "sessions-0-notes": "", "sessions-0-amount": "52500", "sessions-0-advance": "", f"sessions-0-res_{self.photo.id}": "1",
            "sessions-0-extra_charges": json.dumps([{"label": "Delivery", "amount": 500}, {"label": "Extra album", "amount": 3000},
                                                    {"label": "Discount", "amount": -1000}, {"label": "empty", "amount": 0}]),
        }
        r = self.client.post(reverse("booking_edit", args=[b.pk]), data)
        self.assertEqual(r.status_code, 302)
        s.refresh_from_db()
        self.assertEqual([l for l, _ in s.charges], ["Delivery", "Extra album", "Discount"])  # zero line dropped
        self.assertEqual(s.charges_total, Decimal("2500"))
        self.assertEqual(s.base_price, Decimal("50000"))
        page = self.client.get(reverse("booking_detail", args=[b.pk]))
        self.assertContains(page, "Delivery +₹500")
        self.assertContains(page, "Discount −₹1,000")
        self.client.post(reverse("payment_add", args=[b.pk]), {"from": "page", "session": s.pk, "amount": "1000",
                                                               "date": timezone.localdate(), "mode": "cash"})
        receipt = self.client.get(reverse("payment_receipt", args=[b.payments.get().pk]))
        self.assertContains(receipt, "Extra album")
        # broken / hostile data is refused, not stored
        data["sessions-0-extra_charges"] = "not json"
        r = self.client.post(reverse("booking_edit", args=[b.pk]), data)
        self.assertContains(r, "could not be read")
        data["sessions-0-extra_charges"] = json.dumps([{"label": "x", "amount": 1}] * 25)
        r = self.client.post(reverse("booking_edit", args=[b.pk]), data)
        self.assertContains(r, "Too many extra charges")
        data["sessions-0-extra_charges"] = json.dumps([{"label": "<script>alert(1)</script>", "amount": 100}])
        self.client.post(reverse("booking_edit", args=[b.pk]), data)
        page = self.client.get(reverse("booking_detail", args=[b.pk]))
        self.assertNotContains(page, "<script>alert(1)</script>")  # shown as plain text only

    def test_pay_in_parts_then_full(self):
        """Advance today, balance two days later -> fully paid."""
        self.post_booking(advance="10000")  # total 50,000
        b = Booking.objects.get()
        self.assertEqual(b.pending, Decimal("40000"))
        r = self.client.get(reverse("payment_add", args=[b.pk]))
        self.assertContains(r, 'value="40000"')  # pending amount pre-filled
        r = self.client.post(reverse("payment_add", args=[b.pk]),
                             {"from": "page", "session": b.sessions.get().pk, "amount": "40000", "date": timezone.localdate(), "mode": "upi"}, follow=True)
        self.assertIn("fully paid now", " ".join(str(m) for m in r.context["messages"]))  # saved messages are quiet now
        self.assertEqual(b.pending, Decimal("0"))
        self.assertEqual(b.payments.count(), 2)
        # The payments list no longer shows this customer as owing money
        self.assertNotContains(self.client.get(reverse("payments")), reverse("payment_add", args=[b.pk]))

    def test_edit_payment(self):
        self.post_booking(advance="10000")
        b = Booking.objects.get()
        p = b.payments.get()
        url = reverse("payment_edit", args=[p.pk])
        self.assertContains(self.client.get(url), "Edit payment")
        # can raise it up to the full total (its own old amount counts as available)
        ev = b.sessions.get().pk
        r = self.client.post(url, {"session": ev, "amount": "60000", "date": p.date, "mode": "cash"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "is pending for")
        self.client.post(url, {"session": ev, "amount": "15000", "date": p.date, "mode": "bank", "reference": "UTR123"})
        p.refresh_from_db()
        self.assertEqual((p.amount, p.mode, p.reference), (Decimal("15000"), "bank", "UTR123"))
        self.assertEqual(b.pending, Decimal("35000"))
        self.assertTrue(AuditLog.objects.filter(action="Payment edited").exists())

    def test_two_events_same_day_are_billed_separately(self):
        data = {
            "client_phone": "9876543210", "client_name": "Guru", "client_alt_phone": "", "client_address": "",
            "event_type": "wedding", "title": "", "status": "confirmed", "delivery_due": "", "notes": "",
            "advance_mode": "cash",
            "sessions-TOTAL_FORMS": "2", "sessions-INITIAL_FORMS": "0", "sessions-MIN_NUM_FORMS": "1", "sessions-MAX_NUM_FORMS": "1000",
        }
        for i, (name, slot, price, adv) in enumerate([("Muhurtham", "morning", "40000", "10000"), ("Reception", "evening", "25000", "")]):
            data.update({f"sessions-{i}-name": name, f"sessions-{i}-date": self.day, f"sessions-{i}-slot": slot,
                         f"sessions-{i}-start_time": "", f"sessions-{i}-end_time": "", f"sessions-{i}-place": "Hall",
                         f"sessions-{i}-map_link": "", f"sessions-{i}-notes": "", f"sessions-{i}-amount": price,
                         f"sessions-{i}-advance": adv, f"sessions-{i}-res_{self.photo.id}": "1"})
        self.assertEqual(self.client.post(reverse("booking_new"), data).status_code, 302)
        b = Booking.objects.get()
        muh, rec = b.sessions.order_by("start_time")
        self.assertEqual(b.total_amount, Decimal("65000"))           # sum of the events
        self.assertEqual((muh.paid, muh.pending), (Decimal("10000"), Decimal("30000")))
        self.assertEqual((rec.paid, rec.pending), (Decimal("0"), Decimal("25000")))
        # pay the reception in full: muhurtham is untouched
        r = self.client.post(reverse("payment_add", args=[b.pk]),
                             {"from": "page", "session": rec.pk, "amount": "25000", "date": timezone.localdate(), "mode": "upi"}, follow=True)
        self.assertEqual((muh.name, rec.name), ("Wedding – Morning", "Wedding – Evening"))  # named automatically
        self.assertIn("Wedding – Evening is fully paid now", " ".join(str(m) for m in r.context["messages"]))  # saved messages are quiet now
        self.assertEqual(rec.pending, Decimal("0"))
        self.assertEqual(muh.pending, Decimal("30000"))
        # can't pay more than the event's own pending amount
        r = self.client.post(reverse("payment_add", args=[b.pk]),
                             {"from": "page", "session": muh.pk, "amount": "35000", "date": timezone.localdate(), "mode": "cash"})
        self.assertContains(r, "Only ₹30,000 is pending for Wedding – Morning")
        # payments page lists events separately
        page = self.client.get(reverse("payments")).content.decode()
        self.assertIn(f"event={muh.pk}", page)
        self.assertNotIn(f"event={rec.pk}", page)

    def test_pages_render(self):
        self.post_booking(advance="5000")
        b = Booking.objects.get()
        p = b.payments.get()
        for name, args in [("dashboard", []), ("booking_list", []), ("calendar", []), ("payments", []),
                           ("client_list", []), ("staff_list", []), ("audit_log", []), ("setup_resources", []),
                           ("booking_new", []), ("booking_detail", [b.pk]), ("booking_edit", [b.pk]),
                           ("payment_receipt", [p.pk]), ("payment_edit", [p.pk]), ("payment_add", [b.pk]), ("client_detail", [b.client.pk]), ("setup_studio", [])]:
            r = self.client.get(reverse(name, args=args))
            self.assertEqual(r.status_code, 200, name)

    def test_availability_api(self):
        r = self.client.get(reverse("api_availability"), {"date": self.day, "slot": "morning"})
        self.assertEqual(r.json()["resources"][0]["free"], 2)


class OnboardingTests(TestCase):
    """Sign up -> studio details -> resources -> dashboard; both editable later."""

    def setUp(self):
        cache.clear()

    def test_full_first_time_setup(self):
        r = self.client.post(reverse("signup"), {
            "first_name": "Rupa", "username": "rupa", "email": "rupa@example.com",
            "password1": "Strong@pass9", "password2": "Strong@pass9"}, follow=True)
        self.assertContains(r, "Tell us about your studio")
        self.assertContains(r, "Log out")

        r = self.client.post(reverse("setup_studio"), {
            "name": "Sree Studio", "phone": "9848012345", "email": "", "address": "", "city": "Tirupati"}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("setup_resources"))
        self.assertContains(r, "What does your studio have?")
        self.assertContains(r, "Finish setup")
        self.assertContains(r, "Log out")
        self.assertNotContains(r, 'class="sidebar"')  # no main menu until setup is done

        # Skipping step 3 is not possible: the dashboard sends you back.
        r = self.client.get(reverse("dashboard"))
        self.assertRedirects(r, reverse("setup_resources"))

        studio = Studio.objects.get(name="Sree Studio")
        self.assertFalse(studio.setup_complete)
        rows = list(studio.resources.all())
        data = {"form-TOTAL_FORMS": str(len(rows)), "form-INITIAL_FORMS": str(len(rows)),
                "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000"}
        for i, rt in enumerate(rows):
            data.update({f"form-{i}-id": rt.pk, f"form-{i}-name": rt.name, f"form-{i}-category": rt.category,
                         f"form-{i}-count": rt.count, f"form-{i}-active": "on"})
        r = self.client.post(reverse("setup_resources"), data, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("dashboard"))
        self.assertIn("Setup complete", " ".join(str(m) for m in r.context["messages"]))  # saved messages are quiet now
        studio.refresh_from_db()
        self.assertTrue(studio.setup_complete)

        # Later, both pages open inside the main website with the menu and tabs.
        for name in ["setup_studio", "setup_resources"]:
            r = self.client.get(reverse(name))
            self.assertContains(r, 'class="sidebar"')
            self.assertContains(r, "Studio settings")
            self.assertContains(r, "Resources &amp; equipment")

    def test_cannot_finish_with_no_resources(self):
        owner, studio = make_studio()
        Studio.objects.filter(pk=studio.pk).update(setup_complete=False)
        self.client.login(username="owner", password="Pass@12345")
        data = {"form-TOTAL_FORMS": "0", "form-INITIAL_FORMS": "0", "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000"}
        r = self.client.post(reverse("setup_resources"), data, follow=True)
        self.assertContains(r, "Add at least one resource")
        studio.refresh_from_db()
        self.assertFalse(studio.setup_complete)


class FastEntryTests(TestCase):
    """Packages and the 'is a date free?' check."""

    def setUp(self):
        cache.clear()
        self.owner, self.studio = make_studio()
        self.photo = ResourceType.objects.create(studio=self.studio, name="Photographer", count=2)
        self.drone = ResourceType.objects.create(studio=self.studio, name="Drone", category="equipment", count=1)
        self.client.login(username="owner", password="Pass@12345")
        self.day = timezone.localdate() + timedelta(days=12)

    def make_package(self, name="Wedding – Gold", price="75000", photo=2, drone=1):
        r = self.client.post(reverse("package_new"), {
            "name": name, "event_type": "wedding", "price": price, "description": "", "active": "on",
            f"res_{self.photo.id}": photo, f"res_{self.drone.id}": drone,
        })
        self.assertEqual(r.status_code, 302)
        from studios.models import Package
        return Package.objects.get(studio=self.studio, name=name)

    def test_create_edit_delete_package(self):
        pk = self.make_package()
        self.assertEqual(pk.quantities(), {self.photo.id: 2, self.drone.id: 1})
        self.assertContains(self.client.get(reverse("package_list")), "Wedding – Gold")
        self.client.post(reverse("package_edit", args=[pk.pk]), {
            "name": "Wedding – Gold", "price": "80000", "active": "on", f"res_{self.photo.id}": 1, f"res_{self.drone.id}": 0})
        pk.refresh_from_db()
        self.assertEqual((pk.price, pk.quantities()), (Decimal("80000"), {self.photo.id: 1}))
        # duplicate names are refused
        r = self.client.post(reverse("package_new"), {"name": "wedding – gold", "price": "1"})
        self.assertContains(r, "already have a package")
        self.client.post(reverse("package_delete", args=[pk.pk]))
        self.assertFalse(type(pk).objects.filter(pk=pk.pk).exists())

    def test_resource_price_saved_and_sent_to_booking_form(self):
        rows = [self.photo, self.drone]
        data = {"form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2", "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000"}
        for i, (rt, rate) in enumerate(zip(rows, ["8000", "6000"])):
            data.update({f"form-{i}-id": rt.pk, f"form-{i}-name": rt.name, f"form-{i}-category": rt.category,
                         f"form-{i}-count": rt.count, f"form-{i}-rate": rate, f"form-{i}-active": "on"})
        self.client.post(reverse("setup_resources"), data)
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.rate, Decimal("8000"))
        r = self.client.get(reverse("booking_new"))
        self.assertContains(r, '"rate": 8000.0')
        self.assertContains(r, 'class="price-calc"')

    def test_resource_page_fills_costs_from_packages_and_save_keeps_them(self):
        """Costs typed as single-item packages appear in Resources; one Save stores them there."""
        tv = ResourceType.objects.create(studio=self.studio, name="TV", category="equipment", count=4)
        self.client.post(reverse("package_new"), {"name": "tv", "price": "2000", "active": "on",
                                                  f"res_{tv.id}": 1, f"res_{self.photo.id}": 0, f"res_{self.drone.id}": 0})
        page = self.client.get(reverse("setup_resources"))
        fs = page.context["formset"]
        data = {"form-TOTAL_FORMS": str(len(fs.forms)), "form-INITIAL_FORMS": str(len(fs.forms)),
                "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000"}
        for i, f in enumerate(fs.forms):
            data[f"form-{i}-id"] = f.instance.pk
            for name in ("name", "category", "count"):
                data[f"form-{i}-{name}"] = f.initial.get(name, getattr(f.instance, name))
            data[f"form-{i}-rate"] = f.initial.get("rate") or ""
            data[f"form-{i}-active"] = "on"
        r = self.client.post(reverse("setup_resources"), data)
        self.assertEqual(r.status_code, 302)
        tv.refresh_from_db()
        self.assertEqual(tv.rate, Decimal("2000"))
        self.assertNotContains(self.client.get(reverse("setup_resources")), "Filled in from package")

    def test_single_item_packages_work_as_item_prices(self):
        """Owner enters "tv ₹2,000" as a package: it's the price of one TV, and items add up."""
        import json
        tv = ResourceType.objects.create(studio=self.studio, name="TV", category="equipment", count=4)
        r = self.client.post(reverse("package_new"), {"name": "tv", "price": "2000", "active": "on",
                                                      f"res_{tv.id}": 1, f"res_{self.photo.id}": 0, f"res_{self.drone.id}": 0})
        self.assertEqual(r.status_code, 302)
        self.make_package(name="drone", price="3000", photo=0, drone=1)
        combo = self.make_package(name="Wedding – Gold", price="75000", photo=2, drone=1)
        page = self.client.get(reverse("booking_new"))
        rates = json.loads(page.context["resource_rates"] and json.dumps(page.context["resource_rates"]))
        self.assertEqual(rates[str(tv.id)]["rate"], 2000.0)          # from the "tv" package
        self.assertEqual(rates[str(self.drone.id)]["rate"], 3000.0)  # from the "drone" package
        pk_field = page.context["formset"].forms[0].fields["package"]
        self.assertEqual(list(pk_field.queryset.values_list("name", flat=True)), ["Wedding – Gold"])  # only combos
        self.assertContains(self.client.get(reverse("package_list")), "Used as item prices")
        page = self.client.get(reverse("setup_resources"))
        self.assertContains(page, "Filled in from package “tv”")
        self.assertContains(page, 'value="2000"')
        # the resource's own price wins over the package
        tv.rate = Decimal("2500"); tv.save()
        page = self.client.get(reverse("booking_new"))
        self.assertEqual(page.context["resource_rates"][str(tv.id)]["rate"], 2500.0)

    def test_old_booking_using_single_item_package_can_still_be_edited(self):
        self.make_package(name="drone", price="3000", photo=0, drone=1)
        from studios.models import Package
        single = Package.objects.get(name="drone")
        b = make_booking(self.studio, "9000000009", self.day, Session.FULL, {self.drone: 1})
        Session.objects.filter(booking=b).update(package=single)
        page = self.client.get(reverse("booking_edit", args=[b.pk]))
        self.assertIn(single, list(page.context["formset"].forms[0].fields["package"].queryset))

    def test_single_item_packages_can_be_moved_to_resources(self):
        self.make_package(name="drone", price="3000", photo=0, drone=1)
        r = self.client.post(reverse("package_convert"), follow=True)
        self.drone.refresh_from_db()
        self.assertEqual(self.drone.rate, Decimal("3000"))

    def test_package_shows_in_booking_form(self):
        pk = self.make_package()
        r = self.client.get(reverse("booking_new"))
        self.assertContains(r, "Wedding – Gold · ₹75,000")
        self.assertContains(r, '"price": "75000"')

    def test_quick_booking_removed_opens_full_form_with_date(self):
        r = self.client.get(reverse("quick_booking"), {"date": self.day.isoformat(), "slot": "evening"})
        self.assertRedirects(r, reverse("booking_new") + f"?date={self.day.isoformat()}&slot=evening")
        page = self.client.get(r["Location"])
        self.assertContains(page, f'value="{self.day.isoformat()}"')
        self.assertContains(page, '<option value="evening" selected>')
        self.assertNotContains(self.client.get(reverse("dashboard")), "Quick booking")

    def test_date_check_lists_the_whole_day(self):
        make_booking(self.studio, "9000000001", self.day, Session.MORNING, {self.photo: 1})
        r = self.client.get(reverse("api_availability"), {"date": self.day.isoformat(), "slot": "evening"})
        data = r.json()
        self.assertEqual(len(data["day"]), 1)
        self.assertFalse(data["day"][0]["overlaps"])  # morning shoot doesn't clash with evening
        self.assertEqual({x["name"]: x["free"] for x in data["resources"]}["Photographer"], 2)
        self.assertContains(self.client.get(reverse("dashboard")), "Is a date free?")

    def test_staff_cannot_add_bookings_or_packages(self):
        staff = User.objects.create_user("ravi", password="Pass@12345")
        Profile.objects.filter(user=staff).update(studio=self.studio, role=Profile.STAFF)
        self.client.login(username="ravi", password="Pass@12345")
        for name in ["booking_new", "package_list", "package_new"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)


class ResourcePageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.studio = make_studio()
        self.photo = ResourceType.objects.create(studio=self.studio, name="Photographer", count=2)
        self.drone = ResourceType.objects.create(studio=self.studio, name="Drone", category="equipment", count=1)
        self.client.login(username="owner", password="Pass@12345")

    def post(self, rows):
        data = {"form-TOTAL_FORMS": str(len(rows)), "form-INITIAL_FORMS": str(sum(1 for r in rows if r.get("id"))),
                "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000"}
        for i, r in enumerate(rows):
            data[f"form-{i}-id"] = r.get("id", "")
            data[f"form-{i}-name"] = r["name"]
            data[f"form-{i}-category"] = r.get("category", "people")
            data[f"form-{i}-count"] = str(r.get("count", 1))
            if r.get("active", True):
                data[f"form-{i}-active"] = "on"
            if r.get("delete"):
                data[f"form-{i}-DELETE"] = "on"
        return self.client.post(reverse("setup_resources"), data)

    def existing(self, **changes):
        rows = [{"id": self.photo.pk, "name": "Photographer", "count": 2},
                {"id": self.drone.pk, "name": "Drone", "category": "equipment", "count": 1}]
        for r in rows:
            r.update(changes.get(r["name"], {}))
        return rows

    def test_add_new_resource(self):
        r = self.post(self.existing() + [{"name": "Gimbal", "category": "equipment", "count": 2}])
        self.assertEqual(r.status_code, 302)
        self.assertTrue(ResourceType.objects.filter(studio=self.studio, name="Gimbal", count=2).exists())

    def test_remove_unused_resource_deletes_it(self):
        self.post(self.existing(Drone={"delete": True}))
        self.assertFalse(ResourceType.objects.filter(pk=self.drone.pk).exists())

    def test_remove_used_resource_switches_it_off(self):
        make_booking(self.studio, "9000000001", timezone.localdate(), Session.FULL, {self.drone: 1})
        self.post(self.existing(Drone={"delete": True}))
        self.drone.refresh_from_db()
        self.assertFalse(self.drone.active)
        self.assertEqual(SessionResource.objects.filter(resource_type=self.drone).count(), 1)

    def test_duplicate_name_is_rejected(self):
        r = self.post(self.existing() + [{"name": "drone", "category": "equipment"}])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ResourceType.objects.filter(studio=self.studio).count(), 2)

    def test_remove_and_readd_same_name(self):
        self.post(self.existing(Drone={"delete": True}) + [{"name": "Drone", "category": "equipment", "count": 2}])
        self.assertEqual(ResourceType.objects.get(studio=self.studio, name="Drone").count, 2)


class SecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.studio = make_studio()
        self.other_owner, self.other = make_studio("rival", "Rival Studio")
        self.rt = ResourceType.objects.create(studio=self.other, name="Photographer", count=2)
        self.other_booking = make_booking(self.other, "9111111111", date.today(), Session.FULL, {self.rt: 1})
        self.staff = User.objects.create_user("ravi", password="Pass@12345")
        Profile.objects.filter(user=self.staff).update(studio=self.studio, role=Profile.STAFF)

    def test_studios_cannot_see_each_others_bookings(self):
        self.client.login(username="owner", password="Pass@12345")
        r = self.client.get(reverse("booking_detail", args=[self.other_booking.pk]))
        self.assertEqual(r.status_code, 404)
        r = self.client.post(reverse("payment_add", args=[self.other_booking.pk]), {"session": self.other_booking.sessions.get().pk, "amount": "1", "date": date.today(), "mode": "cash"})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(Payment.objects.exists())

    def test_staff_cannot_reach_owner_pages(self):
        self.client.login(username="ravi", password="Pass@12345")
        for name in ["payments", "booking_new", "staff_list", "audit_log", "setup_resources"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Pending amount")

    def test_login_lockout_after_repeated_failures(self):
        url = reverse("login")
        for _ in range(5):
            self.client.post(url, {"username": "owner", "password": "wrong"})
        r = self.client.post(url, {"username": "owner", "password": "Pass@12345"})
        self.assertEqual(r.status_code, 429)
        self.assertTrue(AuditLog.objects.filter(action="Failed login").count() >= 5)

    def test_double_submitted_signup_does_not_crash(self):
        """Two signups racing for one username: the loser gets a form error, not a 500."""
        from unittest import mock

        from django.db import IntegrityError
        data = {"first_name": "Rupa", "username": "rupa", "email": "rupa@example.com",
                "password1": "Strong@pass9", "password2": "Strong@pass9"}
        with mock.patch("accounts.forms.SignupForm.save", side_effect=IntegrityError("UNIQUE")):
            r = self.client.post(reverse("signup"), data)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "just taken")

    def test_signup_passwords_hidden_from_error_reports(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from accounts.views import signup
        request = RequestFactory().get(reverse("signup"))
        request.user = AnonymousUser()
        signup(request)
        # Django's error pages read this attribute and print ******** instead of the values.
        self.assertEqual(request.sensitive_post_parameters, ("password1", "password2"))

    # --- Forgot username / password ---
    def test_forgot_sends_username_and_working_reset_link(self):
        import re

        from django.core import mail
        self.owner.email = "owner@studio.in"
        self.owner.save()
        r = self.client.post(reverse("password_reset"), {"email": "OWNER@studio.in"}, follow=True)
        self.assertContains(r, "Check your email")
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("Your username is:  owner", body)
        link = re.search(r"https?://[^/]+(/reset/\S+)", body).group(1)
        r = self.client.get(link, follow=True)  # Django swaps the token for a session marker
        self.assertContains(r, "Set a new password")
        r = self.client.post(r.redirect_chain[-1][0], {"new_password1": "Brand-New#2026", "new_password2": "Brand-New#2026"}, follow=True)
        self.assertContains(r, "Password changed")
        self.assertTrue(self.client.login(username="owner", password="Brand-New#2026"))
        self.assertTrue(AuditLog.objects.filter(action="Password reset via email link").exists())
        # the link is single-use
        self.client.logout()
        self.assertContains(self.client.get(link, follow=True), "doesn't work any more")

    def test_forgot_does_not_reveal_unknown_emails(self):
        from django.core import mail
        r = self.client.post(reverse("password_reset"), {"email": "nobody@nowhere.in"}, follow=True)
        self.assertContains(r, "Check your email")  # same page as a real account
        self.assertEqual(len(mail.outbox), 0)

    def test_forgot_is_rate_limited(self):
        for _ in range(5):
            self.client.post(reverse("password_reset"), {"email": "x@y.in"})
        r = self.client.post(reverse("password_reset"), {"email": "x@y.in"})
        self.assertEqual(r.status_code, 429)

    def test_owner_resets_staff_password(self):
        self.client.login(username="owner", password="Pass@12345")
        url = reverse("staff_set_password", args=[self.staff.pk])
        self.client.post(url, {"new_password1": "Fresh#Pass77", "new_password2": "Fresh#Pass77"})
        self.client.logout()
        self.assertTrue(self.client.login(username="ravi", password="Fresh#Pass77"))
        # staff can't reset anyone's password, and owners can't touch another studio's users
        r = self.client.post(url, {"new_password1": "Hack#Pass77", "new_password2": "Hack#Pass77"})
        self.assertEqual(r.status_code, 403)
        self.client.login(username="rival", password="Pass@12345")
        r = self.client.post(url, {"new_password1": "Hack#Pass77", "new_password2": "Hack#Pass77"})
        self.assertEqual(r.status_code, 404)

    def test_signup_requires_email(self):
        data = {"first_name": "A", "username": "anew", "email": "", "password1": "Strong@pass9", "password2": "Strong@pass9"}
        r = self.client.post(reverse("signup"), data)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="anew").exists())

    def test_logout_switches_user(self):
        self.client.login(username="ravi", password="Pass@12345")
        self.assertContains(self.client.get(reverse("dashboard")), "Log out")
        r = self.client.post(reverse("logout"), follow=True)
        self.assertContains(r, "been logged out")
        self.assertFalse(r.context["user"].is_authenticated)
        # next member logs in on the same browser
        self.client.login(username="owner", password="Pass@12345")
        self.assertContains(self.client.get(reverse("payments")), "Who owes what")
        self.assertTrue(AuditLog.objects.filter(action="Logged out", user=self.staff).exists())

    def test_username_any_case_works(self):
        self.assertTrue(self.client.login(username="RAVI", password="Pass@12345"))
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": " Ravi ", "password": "Pass@12345"})
        self.assertRedirects(r, reverse("dashboard"))

    def test_new_usernames_saved_lowercase_and_unique(self):
        self.client.login(username="owner", password="Pass@12345")
        self.client.post(reverse("staff_list"), {"first_name": "Kiran", "username": "Kiran", "phone": "",
                                                 "designation": "", "password1": "Kiran@studio26", "password2": "Kiran@studio26"})
        self.assertTrue(User.objects.filter(username="kiran").exists())
        r = self.client.post(reverse("staff_list"), {"first_name": "K2", "username": "KIRAN", "phone": "",
                                                     "designation": "", "password1": "Kiran@studio26", "password2": "Kiran@studio26"})
        self.assertContains(r, "already taken")

    def test_disabled_staff_gets_clear_message(self):
        self.staff.is_active = False
        self.staff.save()
        r = self.client.post(reverse("login"), {"username": "ravi", "password": "Pass@12345"})
        self.assertContains(r, "turned off by the studio owner")
        # a wrong password does NOT reveal that the account exists
        r = self.client.post(reverse("login"), {"username": "ravi", "password": "wrong-one"})
        self.assertNotContains(r, "turned off")

    def test_login_page_lets_next_person_switch_user(self):
        self.client.login(username="owner", password="Pass@12345")
        r = self.client.get(reverse("login"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "is logged in on this computer")
        self.assertNotContains(r, 'class="sidebar"')
        r = self.client.post(reverse("login"), {"username": "ravi", "password": "Pass@12345"}, follow=True)
        self.assertEqual(r.context["user"].username, "ravi")

    def test_logout_requires_post(self):
        self.client.login(username="ravi", password="Pass@12345")
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_new_owner_can_log_out_during_studio_setup(self):
        User.objects.create_user("newbie", password="Pass@12345")
        self.client.login(username="newbie", password="Pass@12345")
        r = self.client.get(reverse("dashboard"), follow=True)
        self.assertContains(r, "Tell us about your studio")
        self.assertContains(r, 'action="/logout/"')

    def test_anonymous_users_are_redirected_to_login(self):
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])


class NotificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.studio = make_studio()
        self.staff = User.objects.create_user("ravi", password="Pass@12345", first_name="Ravi")
        Profile.objects.filter(user=self.staff).update(studio=self.studio, role=Profile.STAFF)
        self.today = timezone.localdate()
        self.client.login(username="owner", password="Pass@12345")

    def page(self):
        return self.client.get(reverse("notifications"))

    def open_titles(self, user=None):
        from .models import Notification
        return list(Notification.objects.filter(user=user or self.owner, done_at__isnull=True)
                    .values_list("title", flat=True))

    def test_shoot_tomorrow_reminds_customer_on_whatsapp(self):
        b = make_booking(self.studio, "9000000001", self.today + timedelta(days=1), Session.MORNING, {})
        page = self.page()
        self.assertContains(page, "Shoot tomorrow")
        self.assertContains(page, "Remind customer")
        self.assertContains(page, "https://wa.me/919000000001")
        self.assertContains(page, "No team yet")  # staff exist but nobody is assigned

    def test_balance_after_event_clears_when_paid(self):
        b = make_booking(self.studio, "9000000002", self.today - timedelta(days=3), Session.FULL, {}, total=20000)
        s = b.sessions.get()
        self.assertContains(self.page(), "Balance ₹20,000")
        Payment.objects.create(booking=b, session=s, amount=Decimal("5000"), date=self.today)
        self.assertContains(self.page(), "Balance ₹15,000")  # amount kept up to date
        Payment.objects.create(booking=b, session=s, amount=Decimal("15000"), date=self.today)
        page = self.page()
        self.assertNotIn("Balance", " ".join(self.open_titles()))
        self.assertContains(page, "Sorted automatically")

    def test_done_stays_done_and_badge_counts_unread(self):
        make_booking(self.studio, "9000000003", self.today + timedelta(days=1), Session.MORNING, {})
        dash = self.client.get(reverse("dashboard"))
        self.assertGreaterEqual(dash.context["notif_count"], 1)
        from .models import Notification
        n = Notification.objects.filter(user=self.owner, kind=Notification.SHOOT_TOMORROW).get()
        self.client.post(reverse("notification_done", args=[n.pk]))
        cache.clear()
        self.page()
        n.refresh_from_db()
        self.assertIsNotNone(n.done_at)
        self.assertEqual(Notification.objects.filter(user=self.owner, kind=Notification.SHOOT_TOMORROW).count(), 1)
        api = self.client.get(reverse("api_notifications")).json()
        self.assertEqual(api["count"], 0)  # everything was seen on the notifications page

    def test_delivery_and_enquiry_reminders(self):
        b = make_booking(self.studio, "9000000004", self.today - timedelta(days=20), Session.FULL, {})
        Payment.objects.create(booking=b, session=b.sessions.get(), amount=Decimal("10000"), date=self.today)
        b.delivery_due = self.today - timedelta(days=2); b.save()
        make_booking(self.studio, "9000000005", self.today + timedelta(days=2), Session.FULL, {},
                     status=Booking.ENQUIRY)
        page = self.page()
        self.assertContains(page, "Delivery overdue")
        self.assertContains(page, "Enquiry not confirmed")

    def test_staff_told_when_assigned_and_never_sees_money(self):
        b = make_booking(self.studio, "9000000006", self.today + timedelta(days=1), Session.MORNING, {}, total=50000)
        s = b.sessions.get()
        self.client.post(reverse("session_assign", args=[s.pk]), {"staff": [self.staff.pk]})
        self.client.logout()
        self.client.login(username="ravi", password="Pass@12345")
        api = self.client.get(reverse("api_notifications")).json()
        self.assertGreaterEqual(api["count"], 1)
        page = self.page()
        self.assertContains(page, "on a shoot")
        self.assertContains(page, "Your shoot tomorrow")
        self.assertNotContains(page, "₹")       # staff never see payment reminders
        self.assertNotContains(page, "No team yet")

    def test_cannot_touch_another_persons_notification(self):
        from .models import Notification
        make_booking(self.studio, "9000000007", self.today + timedelta(days=1), Session.MORNING, {})
        self.page()
        n = Notification.objects.filter(user=self.owner).first()
        other, other_studio = make_studio("other", "Other Studio")
        self.client.logout()
        self.client.login(username="other", password="Pass@12345")
        self.assertEqual(self.client.post(reverse("notification_done", args=[n.pk])).status_code, 404)
        n.refresh_from_db()
        self.assertIsNone(n.done_at)
        self.assertNotContains(self.page(), "9000000007")


class BackupExportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner, self.studio = make_studio()
        self.client.login(username="owner", password="Pass@12345")
        self.today = timezone.localdate()

    def sheets(self, resp):
        import io, zipfile
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        self.assertIsNone(z.testzip())
        return {n: z.read(n).decode() for n in z.namelist() if n.startswith("xl/worksheets/")}, z.read("xl/workbook.xml").decode()

    def test_excel_has_four_sheets_with_this_studios_data_only(self):
        b = make_booking(self.studio, "9000000001", self.today, Session.FULL, {}, total=25000)
        b.client.name = "Ravi =cmd|' /C calc'!A0"; b.client.save()
        Payment.objects.create(booking=b, session=b.sessions.get(), amount=Decimal("5000"), date=self.today)
        _, other = make_studio("other", "Other Studio")
        make_booking(other, "9111111111", self.today, Session.FULL, {})
        r = self.client.get(reverse("export_excel"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])
        self.assertIn(".xlsx", r["Content-Disposition"])
        sheets, wb = self.sheets(r)
        for name in ("Bookings", "Events", "Payments", "Customers"):
            self.assertIn(f'name="{name}"', wb)
        everything = "".join(sheets.values())
        self.assertIn("9000000001", everything)
        self.assertNotIn("9111111111", everything)       # other studio never leaks
        self.assertIn('t="inlineStr"><is><t xml:space="preserve">Ravi =cmd', everything)  # text, not a formula
        self.assertNotIn("<f>", everything)
        self.assertIn("<v>25000", everything)              # money stored as numbers Excel can add up

    def test_date_range_filters_events_and_payments(self):
        old = make_booking(self.studio, "9000000002", self.today - timedelta(days=60), Session.FULL, {})
        new = make_booking(self.studio, "9000000003", self.today, Session.FULL, {})
        r = self.client.get(reverse("export_excel"), {"from": (self.today - timedelta(days=7)).isoformat(),
                                                       "to": self.today.isoformat()})
        sheets, _ = self.sheets(r)
        events = sheets["xl/worksheets/sheet2.xml"]
        self.assertIn("C 9000000003", events)
        self.assertNotIn("C 9000000002", events)

    def test_staff_cannot_export_or_see_backups(self):
        staff = User.objects.create_user("ravi", password="Pass@12345")
        Profile.objects.filter(user=staff).update(studio=self.studio, role=Profile.STAFF)
        self.client.logout(); self.client.login(username="ravi", password="Pass@12345")
        self.assertEqual(self.client.get(reverse("export_excel")).status_code, 403)
        self.assertEqual(self.client.get(reverse("backup")).status_code, 403)


from django.test import TransactionTestCase


class BackupFileTests(TransactionTestCase):
    """Real database copy (needs no open test transaction, like the live website)."""

    def setUp(self):
        cache.clear()
        self.owner, self.studio = make_studio()
        self.client.login(username="owner", password="Pass@12345")
        self.today = timezone.localdate()

    def test_backup_now_and_daily_backup(self):
        import sqlite3, tempfile
        from django.test import override_settings
        from . import backup
        with tempfile.TemporaryDirectory() as tmp, override_settings(BACKUP_DIR=tmp, AUTO_BACKUP=True):
            make_booking(self.studio, "9000000004", self.today, Session.FULL, {})
            r = self.client.post(reverse("backup_now"))
            self.assertEqual(r.status_code, 302)
            files = backup.list_backups()
            self.assertEqual(len(files), 1)
            con = sqlite3.connect(f"{tmp}/{files[0]['name']}")
            self.assertEqual(con.execute("select count(*) from bookings_client where phone='9000000004'").fetchone()[0], 1)
            con.close()
            self.assertIsNone(backup.backup_today_if_needed())  # already have today's copy
            page = self.client.get(reverse("backup"))
            self.assertContains(page, "Last backup")
            self.assertContains(page, files[0]["name"])


class SettingsTabsTests(TestCase):
    def test_all_six_tabs_on_every_settings_page(self):
        cache.clear()
        owner, studio = make_studio()
        self.client.login(username="owner", password="Pass@12345")
        for name in ["setup_studio", "setup_resources", "package_list", "staff_list", "backup", "audit_log"]:
            page = self.client.get(reverse(name))
            self.assertEqual(page.status_code, 200, name)
            for tab in ["Studio details", "Resources &amp; equipment", "Packages", "Staff logins",
                        "Backup &amp; export", "Activity log"]:
                self.assertContains(page, tab, msg_prefix=name)


class AlbumDeliveredTests(TestCase):
    """No 7-step progress any more: one tap marks the album delivered."""

    def setUp(self):
        cache.clear()
        self.owner, self.studio = make_studio()
        self.client.login(username="owner", password="Pass@12345")
        self.b = make_booking(self.studio, "9000000001", timezone.localdate() - timedelta(days=10), Session.FULL, {})
        self.b.delivery_due = timezone.localdate() - timedelta(days=1); self.b.save()

    def test_one_tap_delivered_from_dashboard_and_undo(self):
        dash = self.client.get(reverse("dashboard"))
        self.assertIn(self.b, list(dash.context["pending_deliveries"]))
        self.assertNotContains(self.client.get(self.b.get_absolute_url()), "Change step")
        r = self.client.post(reverse("booking_status", args=[self.b.pk]),
                             {"work_status": "delivered", "next": reverse("dashboard")})
        self.assertRedirects(r, reverse("dashboard"))
        self.b.refresh_from_db()
        self.assertTrue(self.b.album_delivered)
        self.assertNotIn(self.b, list(self.client.get(reverse("dashboard")).context["pending_deliveries"]))
        self.client.post(reverse("booking_status", args=[self.b.pk]), {"work_status": "upcoming"})
        self.b.refresh_from_db()
        self.assertFalse(self.b.album_delivered)

    def test_old_step_values_and_outside_redirects_are_refused(self):
        self.client.post(reverse("booking_status", args=[self.b.pk]), {"work_status": "editing"})
        self.b.refresh_from_db()
        self.assertEqual(self.b.work_status, Booking.W_UPCOMING)
        r = self.client.post(reverse("booking_status", args=[self.b.pk]),
                             {"work_status": "delivered", "next": "https://evil.example.com/"})
        self.assertEqual(r["Location"], self.b.get_absolute_url())

    def test_staff_can_mark_delivered(self):
        staff = User.objects.create_user("ravi", password="Pass@12345")
        Profile.objects.filter(user=staff).update(studio=self.studio, role=Profile.STAFF)
        self.client.logout(); self.client.login(username="ravi", password="Pass@12345")
        self.client.post(reverse("booking_status", args=[self.b.pk]), {"work_status": "delivered"})
        self.b.refresh_from_db()
        self.assertTrue(self.b.album_delivered)


class SignupSwitchTests(TestCase):
    def test_signup_can_be_closed_online(self):
        from django.test import override_settings
        with override_settings(ALLOW_SIGNUP=False):
            r = self.client.get(reverse("signup"))
            self.assertRedirects(r, reverse("login"))
            self.assertNotContains(self.client.get(reverse("login")), "Create an account")
        self.assertContains(self.client.get(reverse("login")), "Create an account")


class DemoStudioTests(TestCase):
    def test_demo_is_separate_and_one_tap(self):
        from django.core.management import call_command
        from studios.models import Studio
        real = User.objects.create_user("realowner", password="Strong@pass9")
        Studio.objects.create(owner=real, name="Real Studio", phone="9848012345")
        self.assertNotContains(self.client.get(reverse("home")), "Try the demo")
        call_command("setup_demo", stdout=open(os.devnull, "w"))
        self.assertContains(self.client.get(reverse("home")), "Try the demo")
        r = self.client.post(reverse("try_demo"))
        self.assertRedirects(r, reverse("dashboard"))
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Demo Studio")
        self.assertNotContains(page, "Real Studio")
        # an old demo is refreshed; real studios are never touched
        User.objects.filter(username="demo").update(date_joined=timezone.now() - timedelta(days=2))
        self.client.logout()
        self.client.post(reverse("try_demo"))
        self.assertTrue(Studio.objects.filter(name="Real Studio").exists())
        self.assertEqual(Studio.objects.filter(name="Demo Studio").count(), 1)
        self.assertGreater(User.objects.get(username="demo").date_joined, timezone.now() - timedelta(hours=1))
