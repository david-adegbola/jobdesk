// Page navigation without stale content, and a short cache for the lists pages load on arrival.
// No DOM here, so tests/js/nav.test.mjs can run it in Node.

// Each navigation gets a ticket. A page renders with its ticket; when its data arrives after the member has
// already moved on, ticket.current is false and the result is thrown away. The ticket's signal aborts the
// page's requests as soon as the next navigation starts.
export function createNavigator() {
  let latest = 0;
  let controller = null;
  return {
    begin() {
      controller?.abort();
      controller = new AbortController();
      const id = ++latest;
      const signal = controller.signal;
      return { id, signal, get current() { return id === latest; } };
    },
    get latest() { return latest; },
  };
}

// GET responses for the list endpoints pages load on arrival (jobs, applications, CVs, search ...), kept for a
// few seconds so going back to a tab is instant. Anything that changes data (a POST) empties it, so a page never
// shows data older than the member's own last change. Endpoints that are polled for progress are not listed.
const CACHEABLE = [/^\/api\/jobs(\?scope=\w+)?$/, /^\/api\/applications$/, /^\/api\/cvs$/, /^\/api\/search(\?.*)?$/,
  /^\/api\/searches$/, /^\/api\/skills(\?.*)?$/];

export function createCache(ttlMs = 20000, now = () => Date.now()) {
  const entries = new Map();
  return {
    cacheable: path => CACHEABLE.some(pattern => pattern.test(path)),
    get(path) {
      const entry = entries.get(path);
      if (!entry || now() - entry.time > ttlMs) { entries.delete(path); return undefined; }
      return structuredClone(entry.data);        // pages may change what they get; the cache keeps its own copy
    },
    set(path, data) { entries.set(path, { time: now(), data: structuredClone(data) }); },
    clear() { entries.clear(); },
    get size() { return entries.size; },
  };
}
