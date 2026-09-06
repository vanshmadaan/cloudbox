from typing import Optional, Tuple
import asyncio
import boto3
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.logging import logger


class EmailService:
    """Service for sending emails via AWS SES with logging fallback."""

    @staticmethod
    async def send_password_reset_otp(to_email: str, otp: str) -> Tuple[bool, Optional[str]]:
        """
        Send a 6-digit password reset OTP to user's email.
        Uses AWS SES when configured, with graceful logging fallback.
        Returns (delivered: bool, error_message: Optional[str]).
        """
        subject = f"Your CloudBox Password Reset Code: {otp}"
        text_body = (
            f"CloudBox Password Reset\n\n"
            f"Your 6-digit verification code is: {otp}\n\n"
            f"This code is valid for 5 minutes only.\n\n"
            f"If you did not request this password reset, please ignore this email."
        )
        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #ffffff;">
          <h2 style="color: #4f46e5; margin-top: 0; font-size: 20px;">☁️ CloudBox Password Reset</h2>
          <p style="color: #334155; font-size: 15px; line-height: 1.5;">You requested to reset your CloudBox account password. Use the verification code below to proceed:</p>
          <div style="text-align: center; margin: 28px 0;">
            <span style="display: inline-block; font-size: 32px; font-weight: 700; letter-spacing: 6px; color: #1e293b; background-color: #f1f5f9; padding: 12px 24px; border-radius: 8px; border: 1px solid #cbd5e1;">{otp}</span>
          </div>
          <p style="color: #64748b; font-size: 13px; line-height: 1.5;"><strong>⏱️ This code is valid for 5 minutes only.</strong></p>
          <p style="color: #94a3b8; font-size: 12px; margin-top: 24px; border-top: 1px solid #f1f5f9; padding-top: 16px;">If you did not request this password reset, please ignore this email. Your password will remain unchanged.</p>
        </div>
        """

        # Log OTP to server logs for verification and debugging
        logger.info(f"=== [PASSWORD RESET OTP] Target: {to_email} | OTP: {otp} | Valid for: 5 minutes ===")

        if not settings.EMAILS_ENABLED:
            logger.info("Emails are disabled via EMAILS_ENABLED=False. OTP logged only.")
            return False, "Email sending is disabled via EMAILS_ENABLED=False"

        def _send() -> Tuple[bool, Optional[str]]:
            try:
                boto_kwargs = {"region_name": settings.AWS_REGION}
                if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                    boto_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                    boto_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
                    if settings.AWS_SESSION_TOKEN:
                        boto_kwargs["aws_session_token"] = settings.AWS_SESSION_TOKEN

                ses_client = boto3.client("ses", **boto_kwargs)
                ses_client.send_email(
                    Source=settings.SES_SENDER_EMAIL,
                    Destination={"ToAddresses": [to_email]},
                    Message={
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": text_body, "Charset": "UTF-8"},
                            "Html": {"Data": html_body, "Charset": "UTF-8"},
                        },
                    },
                )
                logger.info(f"Password reset OTP successfully dispatched via AWS SES to {to_email}")
                return True, None
            except ClientError as ce:
                error_code = ce.response.get("Error", {}).get("Code", "Unknown")
                error_msg = ce.response.get("Error", {}).get("Message", str(ce))
                logger.warning(
                    f"AWS SES dispatch failed ({error_code}: {error_msg}). "
                    f"Continuing with logged OTP fallback for {to_email}."
                )
                return False, f"{error_code}: {error_msg}"
            except Exception as ex:
                logger.warning(
                    f"Could not deliver email via SES ({type(ex).__name__}: {ex}). "
                    f"Continuing with logged OTP fallback for {to_email}."
                )
                return False, f"{type(ex).__name__}: {str(ex)}"

        return await asyncio.to_thread(_send)

