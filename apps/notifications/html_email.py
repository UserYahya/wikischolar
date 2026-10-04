"""
Branded HTML for every outgoing email.

The plain text stays the source: it is what admins edit on Dashboard -> System emails and type in
Messages, and it is still sent as the text part for mail apps that don't show HTML. This module turns
that text into the WikiScholar layout (logo, card, footer) and lets a system email show some
placeholders richly, e.g. the OTP code in a large box and the registration details as a table.
"""
import re

from django.conf import settings
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils.html import escape

_LINK = re.compile(r"(https?://[^\s<]+[^\s<.,;:!?)\]'\"])|([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_TOKEN = "\x00{}\x00"  # stands in for a placeholder while the text is escaped; never typed by anyone


def _linkify(escaped):
    def repl(m):
        url, email = m.group(1), m.group(2)
        href = url if url else f"mailto:{email}"
        return f'<a href="{href}" style="color:#0A6B4B;">{m.group(0)}</a>'
    return _LINK.sub(repl, escaped)


def text_to_html(text, fragments=None):
    """Plain text -> HTML paragraphs (blank line = new paragraph, line break = <br>), with links.
    `fragments` maps a token in the text to ready-made HTML; a paragraph that is only a token is
    inserted as a block, without a <p> around it."""
    fragments = fragments or {}
    out = []
    for para in re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").strip()):
        if not para.strip():
            continue
        if para.strip() in fragments:
            out.append(f'<div style="margin:0 0 18px;">{fragments[para.strip()]}</div>')
            continue
        html = "<br>".join(_linkify(escape(line)) for line in para.split("\n"))
        for token, frag in fragments.items():
            html = html.replace(escape(token), frag)
        out.append(f'<p style="margin:0 0 16px;">{html}</p>')
    return "\n".join(out)


def logo_url(base_url=None):
    """Absolute URL of the English logo, for mail apps (they can't load relative paths)."""
    base = (base_url or settings.WIKISCHOLAR["PUBLIC_URL"]).rstrip("/")
    if not base:
        return ""
    try:
        path = static("img/wikischolar-logo-en.png")
    except ValueError:  # manifest storage before collectstatic has run
        path = settings.STATIC_URL + "img/wikischolar-logo-en.png"
    return path if path.startswith("http") else base + path


def render_html(body, *, subject="", fragments=None, base_url=None):
    """The full HTML document for an email whose plain text is `body`. `base_url` overrides
    WS_PUBLIC_URL for the logo (the dashboard preview uses the address it is opened at)."""
    ws = settings.WIKISCHOLAR
    return render_to_string("notifications/email.html", {
        "subject": subject, "content": text_to_html(body, fragments), "logo_url": logo_url(base_url),
        "contact_email": ws["CONTACT_EMAIL"], "site_url": ws["SITE_URL"].rstrip("/"),
        "site_host": ws["SITE_URL"].rstrip("/").split("://", 1)[-1],
    })


def fill_html(template, values, html_values=None):
    """HTML for a template with {placeholders}: values are escaped, except those in `html_values`
    (ready-made HTML, e.g. a table of details), which are inserted as they are."""
    html_values = html_values or {}
    fragments, text = {}, template
    for name, value in values.items():
        token = _TOKEN.format(name)
        if "{" + name + "}" not in text:
            continue
        text = text.replace("{" + name + "}", token)
        fragments[token] = html_values.get(name) or "<br>".join(_linkify(escape(line)) for line in str(value).split("\n"))
    return text, fragments


# ---- Pieces a module can use for its rich placeholders -------------------- #
def code_box(code):
    return ('<span style="display:inline-block;padding:10px 18px;border-radius:8px;background:#E3F0E9;color:#084D37;'
            'font:700 30px/1.1 ui-monospace,Menlo,Consolas,monospace;letter-spacing:8px;">'
            f"{escape(code)}</span>")


def highlight(text):
    return ('<span style="display:inline-block;padding:4px 12px;border-radius:6px;background:#FCF1DA;color:#1C2521;'
            f'font-weight:700;font-size:20px;letter-spacing:1px;">{escape(text)}</span>')


def details_table(rows):
    """rows: [(label, value), ...] -> a two-column table."""
    cells = "".join(
        '<tr><td style="padding:7px 14px 7px 0;color:#56635C;white-space:nowrap;vertical-align:top;'
        f'border-bottom:1px solid #E8ECE9;">{escape(k)}</td>'
        f'<td style="padding:7px 0;font-weight:600;border-bottom:1px solid #E8ECE9;">{escape(v)}</td></tr>'
        for k, v in rows)
    return ('<table role="presentation" cellpadding="0" cellspacing="0" '
            f'style="width:100%;border-collapse:collapse;font-size:15px;">{cells}</table>')
