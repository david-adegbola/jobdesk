// JobDesk front end core: a small hash router and shared page helpers.
export async function api(path, options = {}) {
  const opts = { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } };
  if (opts.body && typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
  const res = await fetch(path, opts);
  let data;
  try { data = await res.json(); }
  catch { throw new Error(`Unexpected response from server (${res.status}).`); }
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      currentUser = null;
      state = null;
      mountNav();
      renderLogin(document.getElementById("page"));
    }
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

export function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem("jobdesk:" + key);
    localStorage.setItem("jobdesk:" + key, value);
  } catch (error) { return null; }
}

export function message(text, isError) {
  return h("p", { class: "msg" + (isError ? " err" : ""), role: isError ? "alert" : "status" }, text);
}

export const today = () => new Date().toISOString().slice(0, 10);

const pages = [];
export function register(page) { pages.push(page); }

let state = null;
let currentUser = null;
export async function getState(refresh) {
  if (!state || refresh) state = await api("/api/state");
  return state;
}

function renderLogin(main) {
  document.body.classList.add("login-state");
  document.title = "Sign in · JobDesk";
  const feedback = h("div", { "aria-live": "polite" });
  let signup = false;
  let authConfig = { open_signup: true, dev_email: false };
  const card = h("section", { class: "auth-card" });

  function draw() {
    const form = h("form", { class: "auth-form", onsubmit: async event => {
      event.preventDefault();
      const body = Object.fromEntries(new FormData(form).entries());
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      feedback.replaceChildren();
      try {
        const result = await api("/api/auth/link", { method: "POST", body });
        form.replaceWith(h("div", null,
          message(result.message),
          authConfig.dev_email ? h("p", { class: "muted small" }, "Development mode: the link is in the server log, not in an email.") : "",
          h("button", { type: "button", class: "secondary", onclick: () => draw() }, "Use another address")));
      } catch (error) {
        feedback.replaceChildren(message(error.message, true));
        button.disabled = false;
      }
    } },
      signup ? h("label", { class: "field" }, "Name",
        h("input", { name: "name", autocomplete: "name", required: true, maxlength: 100 })) : "",
      h("label", { class: "field" }, "Email",
        h("input", { name: "email", type: "email", autocomplete: "email", required: true, maxlength: 254 })),
      signup && !authConfig.open_signup ? h("label", { class: "field" }, "Invitation code",
        h("input", { name: "invite", autocomplete: "off", required: true, maxlength: 128 })) : "",
      h("button", { type: "submit" }, signup ? "Email me a link to create my account" : "Email me a sign-in link"));
    card.replaceChildren(
      h("p", { class: "eyebrow" }, "Jobs and internships for students in Finland"),
      h("h1", null, signup ? "Create your account" : "Sign in"),
      h("p", { class: "muted" }, signup
        ? "Free for students at any university or university of applied sciences. No password: we email you a link."
        : "No password needed: enter your email and we'll send you a link to sign in."),
      feedback, form,
      h("button", { class: "secondary auth-switch", type: "button", onclick: () => {
        signup = !signup;
        feedback.replaceChildren();
        draw();
        card.querySelector("input")?.focus();
      } },
        signup ? "Already have an account? Sign in" : "New here? Create an account"),
      h("p", { class: "muted small" }, h("a", { href: "/jobs" }, "Browse open jobs without an account"),
        " · ", h("a", { href: "/employers.html" }, "Post a job")));
  }
  draw();
  const logo = h("span", { class: "brand" });
  logo.innerHTML = '<svg width="48" height="48" viewBox="0 0 34 34" aria-hidden="true"><rect width="34" height="34" rx="10" fill="#FFE28A"/><circle cx="17" cy="17" r="8" fill="#2340D8"/></svg>';
  const art = h("section", { class: "login-art", "aria-label": "JobDesk" }, logo,
    h("h2", null, "Your future,", h("span", { class: "serif" }, "one tidy desk.")),
    h("div", { class: "login-shapes", "aria-hidden": "true" }, h("span"), h("span"), h("span"), h("span")));
  main.replaceChildren(art, card);
  api("/api/auth/config").then(c => { authConfig = c; draw(); }).catch(() => {});
}

// The page a magic link opens: #/auth?token=... The token is posted (not sent in a GET), so email
// security scanners that open links can't use them up.
async function openMagicLink(main) {
  const token = new URLSearchParams(location.hash.split("?")[1] || "").get("token");
  history.replaceState(null, "", location.pathname + "#/home");     // the token never stays in the address bar
  main.replaceChildren(h("p", { class: "muted", role: "status" }, "Signing you in…"));
  try {
    currentUser = (await api("/api/auth/verify", { method: "POST", body: { token } })).user;
    state = null;
    document.body.classList.remove("login-state");
    await mountNav();
    await show();
  } catch (error) {
    renderLogin(main);
    main.prepend(message(error.message, true));
  }
}

// A page may name the career fields it belongs to (page.fields, e.g. ["forestry"]).
// It is then shown only to members who chose one of those fields; other pages are shown to everyone.
let userFields = [];
const visiblePages = () => pages.filter(page => !page.fields || page.fields.some(field => userFields.includes(field)));

// The menu shows sections; a section with several pages gets a row of tabs under the header (#subnav).
// Profile is reached from the avatar, not the menu. A page in no section is listed under Profile.
const ICON = {
  home: '<path d="M3 11 12 4l9 7v9h-6v-6H9v6H3z"/>',
  discover: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  myjobs: '<path d="M6 3h12v18l-6-4-6 4z"/>',
  applications: '<rect x="3" y="4" width="5" height="16" rx="1.5"/><rect x="10" y="4" width="5" height="11" rx="1.5"/><rect x="17" y="4" width="4" height="7" rx="1.5"/>',
  cv: '<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h5"/>',
};
const SECTIONS = [
  { id: "home", title: "Home", pages: ["home"] },
  { id: "discover", title: "Discover", pages: ["jobs"] },
  { id: "myjobs", title: "My jobs", pages: ["myjobs", "shortlist"] },
  { id: "applications", title: "Applications", short: "Tracker", pages: ["tracker", "prepare", "draft"] },
  { id: "cv", title: "My CV", pages: ["cvs"] },
  { id: "profile", title: "Profile", pages: ["account", "study"], avatar: true },
];
const sectionOf = id => SECTIONS.find(s => s.pages.includes(id)) || SECTIONS.find(s => s.id === "profile");
const sectionPages = section => visiblePages().filter(p => sectionOf(p.id) === section)
  .sort((a, b) => (section.pages.indexOf(a.id) + 1 || 99) - (section.pages.indexOf(b.id) + 1 || 99));

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [k, v] of Object.entries({ width: 24, height: 24, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) svg.setAttribute(k, v);
  svg.innerHTML = ICON[name] || "";
  return svg;
}

function initials(user) {
  const words = String(user?.name || user?.email || "?").split(/[\s@._-]+/).filter(Boolean);
  return words.slice(0, 2).map(w => w[0].toUpperCase()).join("") || "?";
}

export async function mountNav() {
  const nav = document.getElementById("nav");
  const actions = document.getElementById("top-actions");
  nav.replaceChildren();
  actions.replaceChildren();
  document.getElementById("subnav").hidden = true;
  if (!currentUser) return;
  userFields = (await getState()).user_fields || [];
  for (const section of SECTIONS) {
    const first = sectionPages(section)[0];
    if (!first || section.avatar) continue;
    const label = h("span", null, section.title);
    if (section.short) label.dataset.short = section.short;
    nav.append(h("a", { href: `#/${first.id}`, "data-section": section.id }, icon(section.id), label));
  }
  if (visiblePages().some(p => p.id === "myjobs")) actions.append(h("a", { class: "btn accent", href: "#/myjobs" }, "+ Add a job"));
  const profileFirst = sectionPages(SECTIONS.find(s => s.avatar))[0];
  if (profileFirst) actions.append(h("a", { class: "avatar", href: `#/${profileFirst.id}`, "data-section": "profile",
    "aria-label": `Profile and settings (${currentUser.name || currentUser.email || "you"})` }, initials(currentUser)));
}

function markCurrent(page) {
  const section = sectionOf(page.id);
  for (const link of document.querySelectorAll("#nav a, #top-actions .avatar")) {
    if (link.dataset.section === section.id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  const subnav = document.getElementById("subnav");
  const siblings = sectionPages(section);
  subnav.hidden = siblings.length < 2;
  subnav.replaceChildren(...(siblings.length < 2 ? [] : siblings.map(p =>
    h("a", { href: `#/${p.id}`, "aria-current": p.id === page.id ? "page" : null }, p.title))));
}

async function show(focusMain = false) {
  const main = document.getElementById("page");
  if (location.hash.startsWith("#/auth")) return openMagicLink(main);
  if (!currentUser) {
    renderLogin(main);
    if (focusMain) main.focus();
    return;
  }
  const id = (location.hash.match(/^#\/([\w-]+)/) || [])[1] || "home";
  const shown = visiblePages();
  const page = shown.find(candidate => candidate.id === id) || shown[0];
  if (!page) return;
  markCurrent(page);
  main.replaceChildren();
  document.title = `${page.title} · JobDesk`;
  try { await page.render(main, location.hash.split("?")[1] || ""); }
  catch (error) { main.append(message(error.message, true)); }
  if (focusMain) main.focus();
}

export async function start() {
  try {
    currentUser = (await api("/api/auth/me")).user;
    document.body.classList.toggle("login-state", !currentUser);
    if (currentUser) await mountNav();
  } catch (error) {
    renderLogin(document.getElementById("page"));
    document.getElementById("page").prepend(message(error.message, true));
  }
  window.addEventListener("hashchange", () => show(true));
  await show();
}
