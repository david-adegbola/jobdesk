"""JobDesk core: logic shared by the JobDesk server and other apps (for example a small Flask app).

Rules for everything in this package:
  * Python standard library only.
  * No imports from server.py, db.py or any other module outside core/.
  * Nothing runs at import time (no network, no subprocesses, no file reads).
"""
