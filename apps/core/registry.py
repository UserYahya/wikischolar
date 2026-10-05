"""
Module registry. Each module registers its dashboard navigation (and the
permission required to see it) from AppConfig.ready(). The dashboard shell
only reads this registry, so adding a Phase 2 module (Exams, CRM, ...) needs
no edits to existing modules.

Related tools share a `group` (e.g. "Schools & places"); the sidebar shows a
group as one collapsible section. A group the user can see only one tool of is
shown as that single link.
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
    group: str = ""


@dataclass
class NavGroup:
    label: str
    items: list

    @property
    def url_names(self):
        return [i.url_name for i in self.items]


def register_nav(label, url_name, perm, order=100, module="", group=""):
    item = NavItem(label, url_name, perm, order, module, group)
    if item not in _NAV:
        _NAV.append(item)


def nav_for(user):
    return [i for i in sorted(_NAV, key=lambda i: i.order) if user.has_perm_code(i.perm)]


def nav_groups_for(user):
    """The user's navigation as groups, ordered by their first tool. Ungrouped tools are a group
    without a label; so is a group with only one tool this user may open."""
    groups, by_label = [], {}
    for item in nav_for(user):
        if item.group and item.group in by_label:
            by_label[item.group].items.append(item)
            continue
        group = NavGroup(item.group, [item])
        groups.append(group)
        if item.group:
            by_label[item.group] = group
    for g in groups:
        if len(g.items) == 1:
            g.label = ""
    return groups
