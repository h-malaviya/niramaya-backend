import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import os
from core.config import SMTP_HOST,SMTP_PASS,SMTP_PORT,SMTP_USER
load_dotenv()
def send_email(to_email: str, subject: str, html: str):
  

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER # type: ignore
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server: # pyright: ignore[reportArgumentType]
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS) # pyright: ignore[reportArgumentType]
        server.send_message(msg)
