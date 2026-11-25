// Run with: node --test tests/js/tracker.test.mjs  (in a container; see AGENTS.md)
import { test } from "node:test";
import assert from "node:assert/strict";
import * as M from "../../static/tracker-model.js";

const app = (id, status, extra = {}) => ({ id, status, title: `Job ${id}`, company: "Esimerkki Oy", created_at: `2026-11-${String(id % 28 + 1).padStart(2, "0")}`, ...extra });

test("deadline chips: red within three days, grey once closed", () => {
  assert.equal(M.deadlineChip({ days_left: null }), null);
  assert.deepEqual(M.deadlineChip({ days_left: -2, deadline: "2026-11-15" }), { kind: "closed", text: "Closed" });
  assert.equal(M.deadlineChip({ days_left: 0 }).kind, "soon");
  assert.equal(M.deadlineChip({ days_left: 3 }).kind, "soon");
  assert.deepEqual(M.deadlineChip({ days_left: 20, deadline: "2026-12-15" }), { kind: "normal", text: "Closes 15.12." });
});

test("employer and place are separate; a posting that also names places abroad says so", () => {
  assert.equal(M.placeText({ town: "Espoo", other_towns: 0, abroad: true }), "Espoo · also abroad");
  assert.equal(M.placeText({ town: "Espoo", other_towns: 1, abroad: true }), "Espoo +1 · also abroad");
  assert.equal(M.placeText({ town: "", place_text: "Remote" }), "Remote");
});

test("closed cards go to the end of their stage, or away when hidden", () => {
  const apps = [app(1, "Saved", { days_left: 5 }), app(2, "Saved", { days_left: -3, closed: true }), app(3, "Saved", { days_left: 1 }),
                app(4, "Applied")];
  const shown = M.stageCards(apps, "Saved");
  assert.deepEqual(shown.open.map(a => a.id), [3, 1]);
  assert.deepEqual(shown.closed.map(a => a.id), [2]);
  assert.deepEqual(M.stageCards(apps, "Saved", { hideClosed: true }).closed, []);
  assert.deepEqual(M.stageCards(apps, "Saved", { filter: "closed", hideClosed: true }).closed.map(a => a.id), [2]);
  assert.deepEqual(M.stageCards(apps, "Saved", { filter: "week" }).open.map(a => a.id), [3, 1]);
  assert.deepEqual(M.stageCards(apps, "Saved", { query: "job 3" }).open.map(a => a.id), [3]);
});

test("sorting by fit puts real comparisons first", () => {
  const apps = [app(1, "Saved"), app(2, "Saved", { rating: "weak" }), app(3, "Saved", { rating: "strong" })];
  assert.deepEqual(M.sortCards(apps, "match").map(a => a.id), [3, 2, 1]);
});

test("empty stages are rails, folded stages stay rails, opened ones stay stacks", () => {
  assert.equal(M.layoutFor("Offer", 0, {}), "rail");
  assert.equal(M.layoutFor("Saved", 5, {}), "stack");
  assert.equal(M.layoutFor("Saved", 5, { collapsed: ["Saved"] }), "rail");
  assert.equal(M.layoutFor("Offer", 0, { expanded: ["Offer"] }), "stack");
});

test("the summary line and the optimistic move with its way back", () => {
  const apps = [app(1, "Saved", { days_left: 2 }), app(2, "Saved"), app(3, "Applied")];
  assert.equal(M.summary(apps), "2 saved · 1 closing this week · 1 applied");
  const { before, after } = M.moved(apps, 2, "Applied");
  assert.equal(after.find(a => a.id === 2).status, "Applied");
  assert.equal(before.find(a => a.id === 2).status, "Saved");
});

test("150 cards: sorting and grouping stay quick", () => {
  const many = Array.from({ length: 150 }, (_, i) => app(i + 1, "Saved", { days_left: (i % 40) - 5, closed: (i % 40) < 5 }));
  const started = performance.now();
  for (let n = 0; n < 50; n++) M.stageCards(many, "Saved", { sort: "deadline", query: "job" });
  assert.ok(performance.now() - started < 500);
});
