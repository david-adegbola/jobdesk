// Woodesk front end core: a small hash router and shared page helpers.
export async function api(path, options = {}) {
  const opts = { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } };
  if (opts.body && typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
  const res = await fetch(path, opts);
  let data;
  try { data = await res.json(); }
  catch { throw new Error(`Unexpected response from server (${res.status}).`); }
  if (!res.ok) {
    if (res.status === 401 && !["/api/auth/me", "/api/auth/login", "/api/auth/register"].includes(path)) {
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
  document.title = "Sign in · Woodesk";
  const feedback = h("div", { "aria-live": "polite" });
  let signup = false;
  const card = h("section", { class: "auth-card" });

  function draw() {
    const form = h("form", { class: "auth-form", onsubmit: async event => {
      event.preventDefault();
      const body = Object.fromEntries(new FormData(form).entries());
      feedback.replaceChildren();
      try {
        const path = signup ? "/api/auth/register" : "/api/auth/login";
        const result = await api(path, { method: "POST", body });
        currentUser = result.user;
        state = null;
        document.body.classList.remove("login-state");
        mountNav();
        location.hash = "#/home";
        await show();
      } catch (error) { feedback.replaceChildren(message(error.message, true)); }
    } },
      signup ? h("label", { class: "field" }, "Name",
        h("input", { name: "name", autocomplete: "name", required: true, maxlength: 100 })) : "",
      h("label", { class: "field" }, "Email",
        h("input", { name: "email", type: "email", autocomplete: "email", required: true, maxlength: 254 })),
      signup ? h("label", { class: "field" }, "Invitation code",
        h("input", { name: "invite", autocomplete: "off", required: true })) : "",
      h("label", { class: "field" }, "Password",
        h("input", { name: "password", type: "password", autocomplete: signup ? "new-password" : "current-password",
          required: true, minlength: signup ? 12 : 1, maxlength: 256 })),
      h("button", { type: "submit" }, signup ? "Create account" : "Sign in"));
    card.replaceChildren(
      h("p", { class: "eyebrow" }, "FORESTRY CAREERS PORTAL"),
      h("h1", null, signup ? "Join Woodesk" : "Welcome back"),
      h("p", { class: "muted" }, signup
        ? "Create your private account with the invitation code you received."
        : "Sign in to see shared forestry opportunities and your private CVs and applications."),
      feedback, form,
      h("button", { class: "secondary auth-switch", type: "button", onclick: () => { signup = !signup; feedback.replaceChildren(); draw(); } },
        signup ? "Already have an account? Sign in" : "Have an invitation? Create an account"));
  }
  draw();
  main.replaceChildren(card);
}

function mountNav() {
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  if (!currentUser) return;
  for (const page of pages) nav.append(h("a", { href: `#/${page.id}`, "data-id": page.id }, page.title));
}

async function show() {
  const main = document.getElementById("page");
  if (!currentUser) {
    renderLogin(main);
    return;
  }
  const id = (location.hash.match(/^#\/([\w-]+)/) || [])[1] || "home";
  const page = pages.find(candidate => candidate.id === id) || pages[0];
  if (!page) return;
  for (const link of document.querySelectorAll("#nav a")) {
    if (link.dataset.id === page.id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  main.replaceChildren();
  document.title = `${page.title} · Woodesk`;
  try { await page.render(main, location.hash.split("?")[1] || ""); }
  catch (error) { main.append(message(error.message, true)); }
}

export async function start() {
  try {
    currentUser = (await api("/api/auth/me")).user;
    document.body.classList.toggle("login-state", !currentUser);
    if (currentUser) mountNav();
  } catch (error) {
    renderLogin(document.getElementById("page"));
    document.getElementById("page").prepend(message(error.message, true));
  }
  window.addEventListener("hashchange", show);
  await show();
}
