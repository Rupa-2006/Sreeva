from django import template

from bookings.utils import format_inr

register = template.Library()


@register.filter
def inr(value):
    return format_inr(value)


@register.filter
def phone(value):
    v = str(value or "")
    return f"{v[:5]} {v[5:]}" if len(v) == 10 else v


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Rebuild the current query string with some keys replaced (for filters + pagination)."""
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag
def vstatic(path):
    """{% vstatic 'css/app.css' %} -> /static/css/app.css?v=<last-modified time>.

    The URL changes whenever the file changes, so browsers always load the
    newest design instead of an old saved copy.
    """
    import os

    from django.contrib.staticfiles import finders
    from django.templatetags.static import static

    url = static(path)
    found = finders.find(path)
    if found and os.path.exists(found):
        return f"{url}?v={int(os.path.getmtime(found))}"
    return url


@register.filter
def inr_signed(value):
    """500 -> '+₹500', -1000 -> '−₹1,000' (for extra charges and discounts)."""
    from decimal import Decimal, InvalidOperation
    try:
        v = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return ("−" if v < 0 else "+") + format_inr(abs(v))


@register.filter
def inr_short(value):
    """Short money for small charts: 80000 -> '₹80K', 150000 -> '₹1.5L'."""
    from decimal import Decimal, InvalidOperation
    try:
        v = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    if v >= 100000:
        return f"₹{(v / 100000):.1f}".rstrip("0").rstrip(".") + "L"
    if v >= 1000:
        return f"₹{(v / 1000):.0f}K"
    return f"₹{v:.0f}"
