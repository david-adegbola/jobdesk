// "Show in English": machine-translates Finnish and Swedish titles and summaries on this device with
// the browser's built-in Translator API (desktop Chrome 138+ / Edge 148+). Nothing is sent to a server.
// Pages mark translatable text with sourceAttrs(item); translateWithin(root) swaps it in place and back.
import { h, store } from "./core.js";

const KEY = "show-in";                          // "en" or "" (original), remembered in this browser
const NAMES = { fi: "Finnish", sv: "Swedish" };
const translators = {};                         // source language -> Promise<Translator>
const cache = new Map();                        // "fi\ntext" -> English, kept while the app is open

export const supported = () => "Translator" in self;
export const showEnglish = () => store(KEY) === "en";

// The language to translate an item from: its main language when that is Finnish or Swedish and the
// item has no English version of its own. item.languages comes from the server (language.py).
export function sourceLanguage(item) {
  const langs = item.languages || [];
  return langs.length && !langs.includes("en") && NAMES[langs[0]] ? langs[0] : "";
}

// Attributes for an element holding only the item's text. lang also helps screen readers and the
// browser's own "Translate page" in browsers without the Translator API.
export function sourceAttrs(item) {
  const lang = sourceLanguage(item);
  return lang ? { lang, "data-translate": lang } : {};
}

async function translatorFor(lang, report, gesture) {
  if (translators[lang]) return translators[lang];
  const options = { sourceLanguage: lang, targetLanguage: "en" };
  const availability = await Translator.availability(options);
  if (availability === "unavailable") {
    report(`This device can't translate ${NAMES[lang]} to English; showing the original text.`);
    return null;
  }
  // Downloading a language pack needs a click; on page load only an installed model is used
  if (availability !== "available" && !gesture) {
    report(`Choose English again to download the ${NAMES[lang]} → English language pack (once per browser).`);
    return null;
  }
  translators[lang] = Translator.create({
    ...options,
    monitor(m) {
      m.addEventListener("downloadprogress", e =>
        report(`Downloading the ${NAMES[lang]} → English language pack: ${Math.round(e.loaded * 100)}%`));
    },
  });
  try { return await translators[lang]; }
  catch (error) { delete translators[lang]; throw error; }
}

function restore(el) {
  if (el.dataset.original == null) return;
  el.textContent = el.dataset.original;
  el.lang = el.dataset.translate;
  el.removeAttribute("title");
  delete el.dataset.original;
}

// Translate (or, with the switch on Original, restore) every marked element inside root.
// gesture: true when called from the user's click, which may start a language-pack download.
export async function translateWithin(root, report = () => {}, gesture = false) {
  const els = [...root.querySelectorAll("[data-translate]")];
  if (!showEnglish() || !supported()) {
    els.forEach(restore);
    if (supported()) report("");
    return;
  }
  const langs = [...new Set(els.map(el => el.dataset.translate))];
  if (!langs.length) return;
  // One update for assistive technology instead of one announcement per translated title
  root.setAttribute("aria-busy", "true");
  try { await translateAll(els, langs, report, gesture); }
  finally { root.removeAttribute("aria-busy"); }
}

async function translateAll(els, langs, report, gesture) {
  // Start every language's download inside the click, before any of them finishes
  const ready = await Promise.all(langs.map(lang => translatorFor(lang, report, gesture).catch(error => {
    report(`Translation isn't available: ${error.message}`);
    return null;
  })));
  let done = 0;
  const pending = els.filter(el => el.dataset.original == null && ready[langs.indexOf(el.dataset.translate)]
    && !cache.has(`${el.dataset.translate}\n${el.textContent}`)).length;
  let fresh = 0;
  for (const [i, lang] of langs.entries()) {
    const translator = ready[i];
    if (!translator) continue;
    for (const el of els) {
      if (!showEnglish()) return;                 // switched back to Original meanwhile
      if (el.dataset.translate !== lang || el.dataset.original != null || !el.isConnected) continue;
      const original = el.textContent;
      const key = `${lang}\n${original}`;
      if (!cache.has(key)) {
        cache.set(key, await translator.translate(original));
        if (pending > 20 && ++fresh % 20 === 0) report(`Translating… ${fresh} of ${pending}`);
      }
      if (!showEnglish()) return;
      if (!el.isConnected || el.dataset.original != null) continue;
      el.dataset.original = original;
      el.textContent = cache.get(key);
      el.lang = "en";
      el.title = `Machine-translated from ${NAMES[lang]}. Original: ${original}`;
      done++;
    }
  }
  if (ready.some(Boolean)) report(done || els.length
    ? "Finnish and Swedish text is machine-translated on this device and may contain mistakes. Hover a title, or switch to Original, to see the original."
    : "");
}

// The Original / English switch. getRoot() returns the element whose text is translated.
export function translateSwitch(getRoot) {
  const note = h("span", { class: "muted small", role: "status" });
  const report = text => { note.textContent = text; };
  const apply = gesture => translateWithin(getRoot(), report, gesture)
    .catch(error => report(`Translation failed: ${error.message}`));
  const name = "show-in-" + Math.random().toString(36).slice(2);
  const choice = (value, label) => h("label", null,
    h("input", { type: "radio", name, value, checked: (showEnglish() ? "en" : "") === value,
      disabled: value === "en" && !supported(),
      onchange: () => { store(KEY, value); apply(true); } }),
    h("span", null, label));
  if (!supported()) report("Automatic translation needs Chrome or Edge on a computer. " +
    "In this browser, its own Translate page option can translate the Finnish text.");
  const element = h("div", { class: "row translate-switch" },
    h("fieldset", { class: "segmented" }, h("legend", { class: "small" }, "Show text in"),
      choice("", "Original"), choice("en", "English")),
    note);
  return { element, apply: () => apply(false) };
}
