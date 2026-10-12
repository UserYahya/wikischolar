"""Saved advanced searches: shared by every admin who can see the list; the admin who saved one (or a
Super Admin) can update or delete it."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.utils import english_text

from .. import advanced
from ..models import SavedSearch

LIST_URL = {SavedSearch.Entity.STUDENTS: "dashboard:students", SavedSearch.Entity.SCHOOLS: "dashboard:schools"}


def visible(user, entity=None):
    """Saved searches this admin may see and run (all of them, for the lists they can view)."""
    entities = [e for e, perm in SavedSearch.VIEW_PERM.items() if user.has_perm_code(perm)]
    qs = SavedSearch.objects.filter(entity__in=entities).select_related("created_by", "updated_by")
    return qs.filter(entity=entity) if entity else qs


def for_request(request, entity):
    """The saved search a list was opened with (?saved=<id>), if this admin may see it."""
    pk = request.GET.get("saved", "")
    return visible(request.user, entity).filter(pk=pk).first() if pk.isdigit() else None


def run_url(search):
    return f"{reverse(LIST_URL[search.entity])}?saved={search.pk}"


def _back(request, fallback):
    nxt = request.POST.get("next", "")
    return redirect(nxt if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}) else fallback)


@login_required
def search_list(request):
    if not any(request.user.has_perm_code(p) for p in SavedSearch.VIEW_PERM.values()):
        raise PermissionDenied
    searches = visible(request.user).order_by("entity", "name")
    rows = [{"s": s, "text": advanced.describe(s.entity, s.query), "url": run_url(s), "can_change": s.can_change(request.user)}
            for s in searches]
    return render(request, "dashboard/saved_searches.html", {"rows": rows})


@login_required
@require_POST
def search_save(request):
    """Save the current advanced search as a new saved search, or (with `id`) update one."""
    entity = request.POST.get("entity", "")
    if entity not in SavedSearch.VIEW_PERM or not request.user.has_perm_code(SavedSearch.VIEW_PERM[entity]):
        raise PermissionDenied
    fallback = reverse(LIST_URL[entity])
    query = advanced.parse(entity, request.POST.get("adv", ""))[2]
    if not query:
        messages.error(request, "Add at least one complete condition before saving the search.")
        return _back(request, fallback)
    existing = None
    if request.POST.get("id", "").isdigit():
        existing = get_object_or_404(SavedSearch, pk=request.POST["id"], entity=entity)
        if not existing.can_change(request.user):
            raise PermissionDenied
    try:
        name = english_text(request.POST.get("name", "") or (existing.name if existing else ""))
        description = english_text(request.POST.get("description", "")) if request.POST.get("description") else ""
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return _back(request, fallback)
    if not name:
        messages.error(request, "Give the search a name.")
        return _back(request, fallback)
    try:
        with transaction.atomic():
            if existing:
                before = {"name": existing.name, "query": existing.query}
                existing.name, existing.query, existing.updated_by = name[:120], query, request.user
                if "description" in request.POST:
                    existing.description = description[:300]
                existing.save()
                audit.record("search.updated", request=request, entity=existing, before=before,
                             after={"name": existing.name, "query": existing.query})
                search = existing
            else:
                search = SavedSearch.objects.create(entity=entity, name=name[:120], description=description[:300],
                                                    query=query, created_by=request.user)
                audit.record("search.saved", request=request, entity=search, after={"name": search.name, "query": query})
    except IntegrityError:
        messages.error(request, f"A saved search called “{name}” already exists. Choose another name, or open it and "
                                "use Update.")
        return _back(request, fallback)
    messages.success(request, f"Saved search “{search.name}” {'updated' if existing else 'saved'}. Every admin can now run it.")
    return redirect(run_url(search))


@login_required
@require_POST
def search_delete(request, pk):
    search = get_object_or_404(visible(request.user), pk=pk)
    if not search.can_change(request.user):
        raise PermissionDenied
    search.soft_delete(by=request.user)
    audit.record("search.deleted", request=request, entity=search, before={"name": search.name, "query": search.query})
    messages.success(request, f"Saved search “{search.name}” deleted.")
    return _back(request, reverse(LIST_URL[search.entity]))
