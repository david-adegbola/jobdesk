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
      h("p", { class: "eyebrow" }, "JOBS AND INTERNSHIPS FOR STUDENTS IN FINLAND"),
      h("h1", null, signup ? "Create your JobDesk account" : "Welcome"),
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
        signup ? "Already have an account? Sign in" : "New here? Create an account"));
  }
  draw();
  main.replaceChildren(card);
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

// A page may name the fields it belongs to (page.fields, e.g. ["forestry"] for the forestry News desk).
// It is then shown only to members who chose one of those fields; other pages are shown to everyone.
let userFields = [];
const visiblePages = () => pages.filter(page => !page.fields || page.fields.some(field => userFields.includes(field)));

export async function mountNav() {
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  if (!currentUser) return;
  userFields = (await getState()).user_fields || [];
  for (const page of visiblePages()) nav.append(h("a", { href: `#/${page.id}`, "data-id": page.id }, page.title));
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
  for (const link of document.querySelectorAll("#nav a")) {
    if (link.dataset.id === page.id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
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
