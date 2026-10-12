from django.core.paginator import Paginator


def paginate(request, qs, per_page=50):
    page = Paginator(qs, per_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


def post_only_redirect(request, fallback):
    from django.shortcuts import redirect
    return redirect(request.POST.get("next") or fallback)


def advanced_context(request, entity, adv):
    """What the advanced-search panel needs: the builder's fields, the current (valid) query, its
    plain-English description and what was left out of the query as given in the link."""
    from .. import advanced
    from .searches import for_request, visible
    saved = for_request(request, entity)
    problems = advanced.parse(entity, request.GET.get("adv", ""))[1] if request.GET.get("adv") else []
    clear = request.GET.copy()
    for key in ("adv", "saved", "page"):
        clear.pop(key, None)
    return {"adv": adv, "adv_entity": entity, "adv_meta": advanced.metadata(entity), "adv_clear": clear.urlencode(),
            "adv_query": advanced.load(adv), "adv_text": advanced.describe(entity, adv) if adv else "",
            "adv_problems": problems, "saved": saved, "saved_list": visible(request.user, entity),
            "saved_can_change": bool(saved and saved.can_change(request.user)),
            "this_url": request.get_full_path()}
