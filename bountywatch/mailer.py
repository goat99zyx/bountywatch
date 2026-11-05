"""Send the daily email over SMTP (works with Brevo, Resend, Postmark, Amazon SES, Zoho and others)."""
import os
import smtplib
from email.message import EmailMessage


def send(to, subject, html_body, text_body, attachment=None):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASS", "")
    sender = os.environ["MAIL_FROM"]
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    if os.environ.get("MAIL_REPLY_TO"):
        msg["Reply-To"] = os.environ["MAIL_REPLY_TO"]
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    if attachment:
        name, data = attachment
        msg.add_attachment(data.encode("utf-8"), maintype="application", subtype="json", filename=name)
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        s = smtplib.SMTP(host, port, timeout=30)
        s.starttls()
    with s:
        if user:
            s.login(user, pwd)
        s.send_message(msg)
