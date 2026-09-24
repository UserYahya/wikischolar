"""
Module registry. Each module registers its dashboard navigation (and the
permission required to see it) from AppConfig.ready(). The dashboard shell
only reads this registry, so adding a Phase 2 module (Exams, CRM, ...) needs
no edits to existing modules.
"""
from dataclasses import dataclass

_NAV = []


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: str
    perm: str
    order: int = 100
    module: str = ""


def register_nav(label, url_name, perm, order=100, module=""):
    item = NavItem(label, url_name, perm, order, module)
    if item not in _NAV:
        _NAV.append(item)


def nav_for(user):
    return [i for i in sorted(_NAV, key=lambda i: i.order) if user.has_perm_code(i.perm)]
