"""Background tasks: slow work (AI calls) runs here instead of inside a web request. Standard library only.

The queue is the `tasks` table in SQLite, so it survives a restart: tasks left running by a stopped server are
queued again at start-up (db.requeue_interrupted_tasks).

  register(kind, handler)     handler(user_id, payload) does the work; an exception marks the task failed.
  submit(user_id, kind, key, payload)
                              queue a task, unless the same one (same key) is already waiting or running;
                              wakes the worker. Returns (task id, newly queued).
  run_pending()               run queued tasks until none are left (the worker loop; tests call it directly).
  start_worker()              start the one worker thread (idempotent).

One worker thread runs tasks one at a time. That keeps AI spending and rate limits predictable; a second worker
could be added safely, because db.claim_task marks a task running in the same transaction that picks it.
"""

import threading
import traceback

import db

HANDLERS = {}
_wake = threading.Event()
_started = False
_start_lock = threading.Lock()


class TaskError(Exception):
    """A failure whose message is safe to show the member (no CV text, no API key)."""


def register(kind, handler):
    HANDLERS[kind] = handler


def submit(user_id, kind, key, payload):
    task_id, new = db.enqueue_task(user_id, kind, key, payload)
    start_worker()
    _wake.set()
    return task_id, new


def run_one():
    task = db.claim_task()
    if not task:
        return False
    try:
        HANDLERS[task["kind"]](task["user_id"], task["payload"])
    except TaskError as error:
        db.finish_task(task["id"], str(error) or "The task failed.")
    except Exception:                       # noqa: BLE001 - a task must never stop the worker
        traceback.print_exc()
        db.finish_task(task["id"], "Something went wrong. Try again later.")
    else:
        db.finish_task(task["id"])
    return True


def run_pending():
    while run_one():
        pass


def _loop():
    while True:
        _wake.wait()            # woken by submit(), and once at start for tasks left from a restart
        _wake.clear()
        try:
            run_pending()
        except Exception:                   # noqa: BLE001 - e.g. the database is briefly locked; try again later
            traceback.print_exc()


def start_worker():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_loop, name="jobdesk-tasks", daemon=True).start()
    _wake.set()
