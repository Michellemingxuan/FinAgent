import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str):
        self._host = smtp_host
        self._port = smtp_port
        self._username = username
        self._password = password

    def send(self, to_addresses: list[str], subject: str, html_body: str, text_body: str) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._username
            msg["To"] = ", ".join(to_addresses)
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            if self._port == 465:
                with smtplib.SMTP_SSL(self._host, self._port) as server:
                    server.login(self._username, self._password)
                    server.sendmail(self._username, to_addresses, msg.as_string())
            else:
                with smtplib.SMTP(self._host, self._port) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(self._username, self._password)
                    server.sendmail(self._username, to_addresses, msg.as_string())

            logger.info("Email sent to %s", to_addresses)
            return True
        except Exception as exc:
            logger.error("Email send failed: %s", exc)
            return False
