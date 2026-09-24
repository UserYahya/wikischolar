from django.core.paginator import Paginator


def paginate(request, qs, per_page=50):
    page = Paginator(qs, per_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


def post_only_redirect(request, fallback):
    from django.shortcuts import redirect
    return redirect(request.POST.get("next") or fallback)
