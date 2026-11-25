// Run with: node --test tests/js/nav.test.mjs  (in a container; see AGENTS.md)
import { test } from "node:test";
import assert from "node:assert/strict";
import { createCache, createNavigator } from "../../static/nav.js";

test("a page whose data arrives after the member moved on is not shown", async () => {
  const nav = createNavigator();
  const shown = [];
  const render = async (ticket, name, delay) => {
    await new Promise(resolve => setTimeout(resolve, delay));
    if (ticket.current) shown.push(name);
  };
  const slow = render(nav.begin(), "Home (slow)", 30);     // the member opens Home ...
  const fast = render(nav.begin(), "Tracker", 5);          // ... and moves to the Tracker before Home's data arrives
  await Promise.all([slow, fast]);
  assert.deepEqual(shown, ["Tracker"]);
});

test("starting a navigation aborts the previous page's requests", () => {
  const nav = createNavigator();
  const first = nav.begin();
  assert.equal(first.signal.aborted, false);
  const second = nav.begin();
  assert.equal(first.signal.aborted, true);
  assert.equal(second.signal.aborted, false);
  assert.equal(first.current, false);
  assert.equal(second.current, true);
});

test("the cache keeps list reads for a short time and never shares objects", () => {
  let clock = 0;
  const cache = createCache(20000, () => clock);
  assert.equal(cache.cacheable("/api/jobs?scope=mine"), true);
  assert.equal(cache.cacheable("/api/search?q=nurse&page=2"), true);
  assert.equal(cache.cacheable("/api/jobs/12/fit"), false);          // polled for progress: always fresh
  assert.equal(cache.cacheable("/api/scrape"), false);
  cache.set("/api/applications", { applications: [1] });
  const copy = cache.get("/api/applications");
  copy.applications.push(2);                                          // a page changing its data ...
  assert.deepEqual(cache.get("/api/applications"), { applications: [1] });   // ... doesn't change the cache
  clock = 20001;
  assert.equal(cache.get("/api/applications"), undefined);           // too old
  cache.set("/api/cvs", { cvs: [] });
  cache.clear();                                                      // what a save does
  assert.equal(cache.size, 0);
});
