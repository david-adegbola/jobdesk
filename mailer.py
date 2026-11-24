"""Sending email: the sign-in links. Python standard library only.

JOBDESK_EMAIL_BACKEND chooses how:
  log     (default) development: the message, including the link, is written to the server log. Nothing is sent.
  smtp    a real email service over SMTP with STARTTLS. Brevo, Amazon SES, Postmark, Mailgun and most others
          offer SMTP, so no provider-specific code is needed. Settings:
            JOBDESK_SMTP_HOST, JOBDESK_SMTP_PORT (default 587), JOBDESK_SMTP_USER, JOBDESK_SMTP_PASSWORD,
            JOBDESK_EMAIL_FROM (e.g. "JobDesk <signin@your-domain.fi>")
  memory  tests: messages are kept in OUTBOX instead of being sent.

The sending domain needs SPF and DKIM DNS records (the provider explains them), or sign-in emails land in spam.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

OUTBOX = []          # memory backend


class MailError(Exception):
    """The message could not be sent. The text never contains the link or the SMTP password."""


def backend():
    return os.environ.get("JOBDESK_EMAIL_BACKEND", "log").strip().lower()


def send(to, subject, text):
    choice = backend()
    if choice == "memory":
        OUTBOX.append({"to": to, "subject": subject, "text": text})
        return
    if choice == "log":
        print(f"\n--- Email (development mode: not sent) ---\nTo: {to}\nSubject: {subject}\n\n{text}\n---\n", flush=True)
        return
    if choice != "smtp":
        raise MailError(f"Unknown JOBDESK_EMAIL_BACKEND {choice!r}.")
    message = EmailMessage()
    message["From"] = os.environ.get("JOBDESK_EMAIL_FROM", "")
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    try:
        with smtplib.SMTP(os.environ["JOBDESK_SMTP_HOST"], int(os.environ.get("JOBDESK_SMTP_PORT", "587")),
                          timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(os.environ["JOBDESK_SMTP_USER"], os.environ["JOBDESK_SMTP_PASSWORD"])
            smtp.send_message(message)
    except (KeyError, OSError, smtplib.SMTPException) as error:
        raise MailError(f"The sign-in email could not be sent ({type(error).__name__}).") from error


def sign_in_text(url, new_account):
    action = "create your JobDesk account" if new_account else "sign in to JobDesk"
    return (f"Hi,\n\nOpen this link to {action}:\n\n{url}\n\n"
            "The link works once and expires in 15 minutes. If you didn't ask for it, you can ignore this email: "
            "nothing happens until the link is opened.\n\nJobDesk")
