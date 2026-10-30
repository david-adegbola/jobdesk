// JobDesk front end core: a tiny hash router plus helpers shared by the pages in /static/pages/.
// app.js imports the pages and then calls start().

export async function api(path, options = {}) {
  const opts = { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } };
  if (opts.body && typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// h("a", {href: "#"}, "text", child, ...) -> element. Text is always set as text, never as HTML.
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

export function store(key, value) {           // per-browser preferences only; never job data
  try {
    if (value === undefined) return localStorage.getItem("jobdesk:" + key);
    localStorage.setItem("jobdesk:" + key, value);
  } catch (e) { return null; }
}

export function message(text, isError) {
  return h("p", { class: "msg" + (isError ? " err" : ""), role: isError ? "alert" : "status" }, text);
}

export const today = () => new Date().toISOString().slice(0, 10);

const pages = [];
export function register(page) { pages.push(page); }

let state = null;
export async function getState(refresh) {
  if (!state || refresh) state = await api("/api/state");
  return state;
}

async function show() {
  const id = (location.hash.match(/^#\/([\w-]+)/) || [])[1] || pages[0].id;
  const page = pages.find(p => p.id === id) || pages[0];
  for (const a of document.querySelectorAll("#nav a")) {
    if (a.dataset.id === page.id) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  const main = document.getElementById("page");
  main.textContent = "";
  document.title = `${page.title} · JobDesk`;
  try {
    await page.render(main, location.hash.split("?")[1] || "");
  } catch (e) {
    main.append(message(e.message, true));
  }
}

export async function start() {
  const nav = document.getElementById("nav");
  for (const p of pages) nav.append(h("a", { href: `#/${p.id}`, "data-id": p.id }, p.title));
  try {
    const s = await getState();
    const banner = document.getElementById("banner");
    if (s.facts_warning) { banner.textContent = s.facts_warning; banner.hidden = false; }
  } catch (e) { /* the page shows its own error */ }
  window.addEventListener("hashchange", show);
  show();
}

