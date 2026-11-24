// Home: the member's own desk. A short brief written from their data (no AI), colour blocks for what to
// notice (deadlines, progress, preparing documents, skills), a paste-a-link bar, jobs picked from their
// fit and match scores, and the dates coming up. Everything comes from existing APIs; nothing is stored here.
import { api, h, register } from "../core.js";
import { FINNISH } from "../finnish.js";

const BEFORE_APPLYING = new Set(["Saved", "Shortlisted"]);     // a job's deadline matters only until you apply
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });

function parseDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
}
function daysUntil(iso) {
  const d = parseDay(iso);
  if (!d) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return Math.round((d - today) / 86400000);
}
const when = days => days === 0 ? "today" : days === 1 ? "tomorrow" : days < 7 ? `in ${days} days` : `on ${DAY.format(new Date(Date.now() + days * 86400000))}`;
const score = job => job.fit && !job.fit.stale ? job.fit.suitability : (job.match?.score ?? 0);
const level = n => n >= 75 ? "high" : n >= 60 ? "mid" : "low";
const firstName = user => String(user?.name || "").trim().split(/\s+/)[0] || "";
const where = job => [job.company, job.location].filter(Boolean).join(" · ");

function fitRing(n, label) {
  return h("span", { class: `fit-ring ${level(n)}`, role: "img", "aria-label": `${label}: ${n} out of 100` }, h("span", null, String(n)));
}

function brief(data) {
  const { mine, picks, cvs, applications } = data;
  const lines = [];
  if (!cvs.length) lines.push(["Start with your CV. Fit scores, tailored CVs and letters are all written from it.", "#/cvs", "Open My CV"]);
  const next = mine.filter(j => BEFORE_APPLYING.has(j.status) && j.days_left != null && j.days_left >= 0)
    .sort((a, b) => a.days_left - b.days_left)[0];
  if (next) lines.push([`${next.title}${next.company ? ` at ${next.company}` : ""} closes ${when(next.days_left)}.`, `#/prepare?job=${next.id}`, "Prepare documents"]);
  const followUp = applications.find(a => a.follow_up || a.overdue);
  if (followUp) lines.push([`${followUp.title}: ${followUp.overdue ? `“${followUp.next_action || "next step"}” is overdue` : followUp.follow_up}`, "#/tracker", "Open the tracker"]);
  const unchecked = mine.filter(j => (j.status === "Saved" || j.status === "Shortlisted") && !j.fit).length;
  if (unchecked && lines.length < 3) lines.push([`${unchecked} saved job${unchecked === 1 ? " isn't" : "s aren't"} checked against your CV yet.`, "#/myjobs", "Check fit"]);
  if (picks[0] && lines.length < 3) lines.push([`Your closest match right now fits ${score(picks[0])}%: ${picks[0].title}.`, null, null]);
  if (!lines.length) lines.push(["Nothing urgent today. Paste a job link below to add the next one.", null, null]);
  return lines.slice(0, 3);
}

function blocks(data) {
  const { mine } = data;
  const soon = mine.filter(j => BEFORE_APPLYING.has(j.status) && j.days_left != null && j.days_left >= 0 && j.days_left <= 7)
    .sort((a, b) => a.days_left - b.days_left);
  const count = s => mine.filter(j => s.includes(j.status)).length;
  const bars = [["saved", count(["Saved", "Shortlisted"]), "saved"], ["applied", count(["Applied"]), "applied"], ["interview", count(["Interview"]), "interview"]];
  const top = Math.max(1, ...bars.map(b => b[1]));
  return h("div", { class: "dash-blocks" },
    h("a", { class: "dash-block coral", href: "#/tracker" },
      h("span", { class: "dash-label" }, "Deadlines this week"),
      h("span", { class: "dash-number" }, String(soon.length)),
      h("span", null, soon[0] ? `Next: ${soon[0].company || soon[0].title}, ${when(soon[0].days_left)}` : "None in the next 7 days")),
    h("a", { class: "dash-block butter", href: "#/tracker" },
      h("span", { class: "dash-label" }, "In progress"),
      h("span", { class: "dash-bars", role: "img", "aria-label": bars.map(([, n, l]) => `${n} ${l}`).join(", ") },
        bars.map(([cls, n, label]) => h("span", { class: `dash-bar ${cls}` },
          h("span", { class: "dash-bar-fill", style: `height: ${Math.max(6, Math.round(72 * n / top))}px` }),
          h("span", null, `${n} ${label}`))))),
    h("a", { class: "dash-block forest", href: "#/prepare" },
      h("span", { class: "dash-label" }, "Make a tailored CV"),
      h("span", null, "CV, cover letter and email for one job, checked against your CV."),
      h("span", { class: "dash-go" }, "Prepare →")),
    h("a", { class: "dash-block lilac", href: "#/study" },
      h("span", { class: "dash-label" }, "What to study"),
      h("span", null, "See which skills your saved jobs ask for, and where to learn them."),
      h("span", { class: "dash-go lilac" }, "Open →")));
}

function jobRow(job, reload) {
  const n = score(job);
  const fin = FINNISH[job.finnish?.level];
  const words = [];     // matched CV words, skipping near-duplicates such as "assistant" and "assisted"
  for (const w of job.match?.words || []) if (words.length < 3 && !words.some(x => x.slice(0, 5) === w.slice(0, 5))) words.push(w);
  const actions = h("div", { class: "dash-actions" });
  if (!job.status) {
    actions.append(h("button", { type: "button", class: "secondary", onclick: async e => {
      e.target.disabled = true;
      try { await api(`/api/jobs/${job.id}/status`, { method: "POST", body: { status: "Saved" } }); reload(); }
      catch (err) { e.target.disabled = false; e.target.textContent = err.message; }
    } }, "Save"));
  } else {
    actions.append(h("span", { class: "tag status", "data-status": job.status }, job.status));
  }
  actions.append(h("a", { class: "btn", href: `#/prepare?job=${job.id}` }, "Prepare"));
  return h("article", { class: "dash-job" },
    fitRing(n, job.fit && !job.fit.stale ? "Fit with your CV" : "Keyword match with your CV"),
    h("div", { class: "dash-job-main" },
      h("h3", null, job.url ? h("a", { href: job.url, target: "_blank", rel: "noopener" }, job.title) : job.title),
      h("p", { class: "muted" }, [where(job), job.days_left != null && job.days_left >= 0 ? `closes ${when(job.days_left)}` : ""].filter(Boolean).join(" · ")),
      h("p", { class: "dash-tags" },
        words.length ? h("span", { class: "tag strength" }, `✓ ${words.join(", ")}`) : "",
        fin && job.finnish.level !== "not_needed" && job.finnish.level !== "unclear" ? h("span", { class: fin[1] }, fin[0]) : "",
        fin && job.finnish.level === "not_needed" ? h("span", { class: fin[1] }, fin[0]) : "")),
    actions);
}

function dates(data) {
  const items = [];
  for (const j of data.mine) if (j.deadline && j.days_left != null && j.days_left >= 0 && BEFORE_APPLYING.has(j.status))
    items.push({ date: j.deadline, kind: "deadline", what: `Deadline: ${j.company || j.title}`, note: j.title });
  for (const a of data.applications) if (a.next_action_date && (daysUntil(a.next_action_date) ?? -1) >= 0)
    items.push({ date: a.next_action_date, kind: a.status === "Interview" ? "interview" : "step",
      what: a.next_action || (a.status === "Interview" ? "Interview" : "Next step"), note: [a.title, a.company].filter(Boolean).join(", ") });
  items.sort((a, b) => a.date.localeCompare(b.date));
  if (!items.length) return h("p", { class: "dash-empty" }, "No dates yet. Deadlines from your saved jobs and next steps from the tracker appear here.");
  return h("ol", { class: "dash-dates" }, items.slice(0, 5).map(i => {
    const d = parseDay(i.date);
    return h("li", { class: `dash-date ${i.kind}` },
      h("span", { class: "dash-tile", "aria-hidden": "true" }, h("span", null, MONTHS[d.getMonth()]), h("strong", null, String(d.getDate()).padStart(2, "0"))),
      h("span", null, h("strong", null, i.what), h("span", { class: "muted" }, `${DAY.format(d)}${i.note ? ` · ${i.note}` : ""}`)));
  }));
}

register({
  id: "home", title: "Home",
  async render(main) {
    const [me, { jobs }, { cvs }, apps] = await Promise.all([
      api("/api/auth/me"), api("/api/jobs"), api("/api/cvs"), api("/api/applications").catch(() => ({ applications: [] }))]);
    const applications = apps.applications || [];
    const mine = jobs.filter(j => j.status);
    const picks = jobs.filter(j => j.status !== "Rejected" && !["Applied", "Interview", "Offer"].includes(j.status) && (j.days_left == null || j.days_left >= 0))
      .sort((a, b) => score(b) - score(a)).slice(0, 3);
    const data = { mine, picks, cvs, applications };
    const name = firstName(me.user);

    const hello = h("h1", { class: "dash-hello" }, "Hei", name ? [", ", h("span", { class: "serif" }, `${name}.`)] : ".");
    const brief_ = h("section", { class: "dash-brief", "aria-labelledby": "dash-brief-title" },
      h("div", null, h("p", { class: "dash-date-line" }, DAY.format(new Date())), hello),
      h("div", null, h("p", { class: "overline", id: "dash-brief-title" }, "Your brief"),
        h("ul", null, brief(data).map(([text, href, label]) => h("li", null, text, href ? [" ", h("a", { href }, label)] : "")))));

    const link = h("input", { type: "url", required: true, placeholder: "Paste a job link: JobDesk reads the ad for you", "aria-label": "Link to a job ad" });
    const quick = h("form", { class: "dash-quick", onsubmit: e => {
      e.preventDefault();
      location.hash = `#/myjobs?add=${encodeURIComponent(link.value.trim())}`;
    } }, link, h("button", { type: "submit" }, "Add job"));

    const reload = () => { main.replaceChildren(); this.render(main); };
    const picked = h("section", { class: "dash-picked", "aria-labelledby": "dash-picked-title" },
      h("div", { class: "dash-heading" }, h("h2", { id: "dash-picked-title" }, "Picked for you"), h("a", { href: "#/jobs" }, `All ${jobs.length} jobs`)),
      picks.length ? picks.map(j => jobRow(j, reload))
        : h("p", { class: "dash-empty" }, "No jobs yet. Paste a link above, or choose your fields under Profile to see shared ads."));
    const coming = h("section", { class: "dash-coming", "aria-labelledby": "dash-coming-title" },
      h("div", { class: "dash-heading" }, h("h2", { id: "dash-coming-title" }, "Coming up")), dates(data));

    main.append(h("div", { class: "dash" }, h("div", { class: "dash-top" }, brief_, blocks(data)), quick,
      h("div", { class: "dash-lower" }, picked, coming)));
  },
});
