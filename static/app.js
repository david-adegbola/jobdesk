// JobDesk entry point: load the pages (each registers itself, in nav order), then start.
import { start } from "./core.js";
import "./pages/jobs.js";
import "./pages/tracker.js";

start();
