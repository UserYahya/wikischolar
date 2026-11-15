// Dashboard menu on phones/tablets (≤900px, matches dashboard.css): the sidebar is an off-canvas drawer.
// Open with the Menu button; close with ×, the backdrop, Esc, or a link. Focus moves into the drawer and back,
// the page behind is inert while it is open, and only one tool group stays open at a time.
(() => {
  const root = document.documentElement;
  const side = document.getElementById("sideNav");
  const openBtn = document.getElementById("navOpen");
  const closeBtn = document.getElementById("navClose");
  const scrim = document.getElementById("navScrim");
  if (!side || !openBtn) return;
  const mobile = matchMedia("(max-width: 900px)");
  const behind = [document.querySelector(".topbar"), document.querySelector(".main")].filter(Boolean);

  function setOpen(open, { restoreFocus = true } = {}) {
    root.classList.toggle("nav-open", open);
    openBtn.setAttribute("aria-expanded", String(open));
    behind.forEach((el) => { el.inert = open; });
    if (open) {
      side.setAttribute("role", "dialog");
      side.setAttribute("aria-modal", "true");
      (side.querySelector('[aria-current="page"]') || closeBtn).focus({ preventScroll: true });
    } else {
      side.removeAttribute("role");
      side.removeAttribute("aria-modal");
      if (restoreFocus && mobile.matches) openBtn.focus({ preventScroll: true });
    }
  }
  const isOpen = () => root.classList.contains("nav-open");

  openBtn.addEventListener("click", () => setOpen(true));
  closeBtn.addEventListener("click", () => setOpen(false));
  scrim.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isOpen()) setOpen(false); });
  // Following a link: close first so the drawer is not left open on Back/forward cache restores
  side.addEventListener("click", (e) => { if (e.target.closest("nav a") && isOpen()) setOpen(false, { restoreFocus: false }); });
  // Only on a Back/Forward cache restore: a plain pageshow also fires when a slow page finishes
  // loading, which would snap shut a menu the user opened early.
  window.addEventListener("pageshow", (e) => { if (e.persisted && isOpen()) setOpen(false, { restoreFocus: false }); });
  // Rotating or resizing to desktop width: drop the drawer state
  mobile.addEventListener("change", () => { if (!mobile.matches && isOpen()) setOpen(false, { restoreFocus: false }); });

  // Accordion on small screens: opening one group closes the others
  const groups = [...side.querySelectorAll(".nav-group")];
  groups.forEach((g) => g.addEventListener("toggle", () => {
    if (g.open && mobile.matches) groups.forEach((o) => { if (o !== g) o.open = false; });
  }));
})();
