"""Calendar export (.ics) of upcoming application deadlines and interviews, for Apple/Google Calendar."""

from datetime import date, datetime, timedelta


def _esc(text):
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    out, raw = [], line.encode("utf-8")
    while len(raw) > 75:
        cut = 75
        while (raw[cut] & 0xC0) == 0x80:      # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


def _event(uid, day, summary, description="", url=""):
    d = date.fromisoformat(day)
    lines = ["BEGIN:VEVENT", f"UID:{uid}@jobdesk.local",
             f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
             f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}",
             f"SUMMARY:{_esc(summary)}"]
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    if url:
        lines.append(f"URL:{url}")
    lines.append("END:VEVENT")
    return lines


def build(applications):
    """Deadlines of open applications and interview dates, from today on."""
    today = date.today().isoformat()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobDesk//David Adegbola//EN",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:JobDesk"]
    for a in applications:
        if a["status"] in ("Rejected", "Offer"):
            continue
        name = " – ".join(x for x in (a["title"], a["company"]) if x)
        contact = a["contact"] or " ".join(x for x in (a["contact_name"], a["contact_phone"]) if x)
        if a["deadline"] and a["deadline"] >= today:
            lines += _event(f"deadline-{a['job_id']}", a["deadline"], f"Deadline: {name}",
                            f"Status: {a['status']}. CV: {a['cv_role'] or '-'}", a["url"])
        if a["status"] == "Interview" and a["next_action_date"] and a["next_action_date"] >= today:
            lines += _event(f"interview-{a['id']}", a["next_action_date"], f"Interview: {name}",
                            "\n".join(x for x in (a["next_action"], f"Contact: {contact}" if contact else "", a["notes"]) if x),
                            a["url"])
    lines.append("END:VCALENDAR")
    return ("\r\n".join(_fold(l) for l in lines) + "\r\n").encode("utf-8")
