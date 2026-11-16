"""Verification email content, configuration, and failure handling."""

from __future__ import annotations

import smtplib
import unittest
from unittest.mock import MagicMock, patch

import emails

SETTINGS = {
    "SMTP_EMAIL_USER": "login@example.com",
    "SMTP_PASSWORD": "app-password",
    "NO_REPLY_EMAIL_ALIAS": "no-reply@example.com",
    "PRODUCT_PUBLIC_BASE_URL": "https://fleet.example.com/",
}


class VerificationEmailTests(unittest.TestCase):
    def test_sends_the_verify_link_to_the_user(self) -> None:
        with patch.dict("os.environ", SETTINGS), patch("emails.smtplib.SMTP") as smtp_class:
            emails.send_verification_email("FleetAI", "ada@example.com", "tok123", 7)
        smtp_class.assert_called_once_with(emails.SMTP_HOST, emails.SMTP_PORT, timeout=emails.SMTP_TIMEOUT_SECONDS)
        smtp = smtp_class.return_value.__enter__.return_value
        smtp.starttls.assert_called_once_with()
        smtp.login.assert_called_once_with("login@example.com", "app-password")
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "ada@example.com")
        self.assertEqual(message["From"], "no-reply@example.com")
        self.assertEqual(message["Subject"], "Verify your FleetAI email")
        text = message.get_content()
        self.assertIn("https://fleet.example.com/verify?token=tok123", text)
        self.assertIn("valid for 7 days", text)
        self.assertIn("If you did not ask for this, ignore this email.", text)

    def test_password_reset_email_links_to_the_reset_page(self) -> None:
        with patch.dict("os.environ", SETTINGS), patch("emails.smtplib.SMTP") as smtp_class:
            emails.send_password_reset_email("Other Product", "ada@example.com", "tok456", 60)
        message = smtp_class.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(message["Subject"], "Reset your Other Product password")
        self.assertIn("https://fleet.example.com/reset?token=tok456", message.get_content())
        self.assertIn("valid for 60 minutes", message.get_content())

    def test_sends_nothing_when_settings_are_missing(self) -> None:
        for missing in ("SMTP_EMAIL_USER", "NO_REPLY_EMAIL_ALIAS", "PRODUCT_PUBLIC_BASE_URL"):
            with self.subTest(missing=missing):
                with patch.dict("os.environ", {**SETTINGS, missing: ""}), patch("emails.smtplib.SMTP") as smtp_class:
                    with self.assertLogs("emails", level="WARNING"):
                        emails.send_verification_email("FleetAI", "ada@example.com", "tok123", 7)
                smtp_class.assert_not_called()

    def test_a_failed_send_is_logged_and_not_raised(self) -> None:
        smtp_class = MagicMock(side_effect=smtplib.SMTPException("down"))
        with patch.dict("os.environ", SETTINGS), patch("emails.smtplib.SMTP", smtp_class):
            with self.assertLogs("emails", level="ERROR"):
                emails.send_verification_email("FleetAI", "ada@example.com", "tok123", 7)


if __name__ == "__main__":
    unittest.main()
