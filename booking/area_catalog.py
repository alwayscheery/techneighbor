"""Public U.S. area names; no resident location data."""
from django.db.models import Case, When, Value, F, CharField
from django.db.models.functions import StrIndex, Substr
from .models import NeighborArea

STATES = dict(line.split('|') for line in '''AL|Alabama
AK|Alaska
AZ|Arizona
AR|Arkansas
CA|California
CO|Colorado
CT|Connecticut
DE|Delaware
DC|District of Columbia
FL|Florida
GA|Georgia
HI|Hawaii
ID|Idaho
IL|Illinois
IN|Indiana
IA|Iowa
KS|Kansas
KY|Kentucky
LA|Louisiana
ME|Maine
MD|Maryland
MA|Massachusetts
MI|Michigan
MN|Minnesota
MS|Mississippi
MO|Missouri
MT|Montana
NE|Nebraska
NV|Nevada
NH|New Hampshire
NJ|New Jersey
NM|New Mexico
NY|New York
NC|North Carolina
ND|North Dakota
OH|Ohio
OK|Oklahoma
OR|Oregon
PA|Pennsylvania
RI|Rhode Island
SC|South Carolina
SD|South Dakota
TN|Tennessee
TX|Texas
UT|Utah
VT|Vermont
VA|Virginia
WA|Washington
WV|West Virginia
WI|Wisconsin
WY|Wyoming'''.splitlines())
STATE_CHOICES = sorted(STATES.items(), key=lambda pair: pair[1])


def matching_areas(state='', query=''):
    areas = NeighborArea.objects.all()
    if state in STATES:
        areas = areas.filter(state=state)
    # Search the city portion, so a search for New York does not match every
    # city whose display label ends in the state name New York.
    areas = areas.annotate(search_city=Case(
        When(name__contains=',', then=Substr('name', 1, StrIndex('name', Value(',')) - 1)),
        default=F('name'), output_field=CharField()))
    for word in query.strip()[:80].split()[:6]:
        areas = areas.filter(search_city__icontains=word)
    return areas


def search_areas(state='', query='', selected=None):
    areas = matching_areas(state, query)
    if not state and not query.strip():
        areas = areas.filter(neighbors__status='approved').distinct()
    choices = list(areas.order_by('name')[:40])
    if selected and all(area.pk != selected.pk for area in choices):
        choices.insert(0, selected)
    return choices
