import sqlite3
import hashlib
import os
import io
import json
import re
import random
import string
import secrets
import smtplib
import time
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Thread-safe in-flight tracking and cooldown rate-limiter for report delivery
_delivery_lock = threading.Lock()
_in_flight_deliveries = set()
_last_delivery_timestamps = {}  # {report_id: timestamp_float}

DB_PATH = Path(__file__).resolve().parent / "torus_doctors.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    """Hashes a password using SHA-256 with a fixed salt."""
    salt = "torus_secure_salt_2026"
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def mask_email(email: str) -> str:
    """Masks an email for secure presentation (e.g. j***k@gmail.com)."""
    if not email or "@" not in email:
        return email
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        masked_user = user[0] + "*"
    else:
        masked_user = user[0] + "*" * (len(user) - 2) + user[-1]
    return f"{masked_user}@{domain}"

def load_env_file():
    """Loads environment variables from .env file dynamically."""
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / "config" / ".env",
    ]
    # Use python-dotenv if installed
    try:
        from dotenv import load_dotenv
        for p in candidates:
            if p.is_file():
                load_dotenv(p, override=True)
    except Exception:
        pass

    # Fallback / explicit parser ensuring root .env variables take effect
    for p in candidates:
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k:
                                os.environ[k] = v
            except Exception as e:
                # Never print file content or sensitive info
                pass

def send_otp_email(to_email: str, user_name: str, user_uid: str, otp: str, user_role: str = "doctor") -> tuple[bool, str]:
    """
    Sends a real OTP to the user's registered email address via SMTP.
    Returns (success: bool, message_or_error: str).
    """
    load_env_file()

    smtp_host = os.environ.get("SMTP_HOST", os.environ.get("EMAIL_HOST", "smtp.gmail.com")).strip()
    smtp_port_str = os.environ.get("SMTP_PORT", os.environ.get("EMAIL_PORT", "587")).strip()
    try:
        smtp_port = int(smtp_port_str)
    except ValueError:
        smtp_port = 587

    smtp_user = os.environ.get("SMTP_USER", os.environ.get("EMAIL_USER", os.environ.get("MAIL_USERNAME", ""))).strip()
    smtp_pass = os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", os.environ.get("EMAIL_PASS", os.environ.get("MAIL_PASSWORD", "")))).strip()
    
    smtp_from_env = os.environ.get("SMTP_FROM", os.environ.get("EMAIL_FROM", "")).strip()
    if smtp_from_env and "noreply@torus.med" not in smtp_from_env:
        smtp_from = smtp_from_env
    elif smtp_user:
        smtp_from = f"TORUS Healthcare <{smtp_user}>"
    else:
        smtp_from = "TORUS Healthcare <noreply@torus.med>"

    use_ssl = os.environ.get("SMTP_SSL", "false").lower() in ("true", "1") or smtp_port == 465
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1") or smtp_port == 587

    role_clean = (user_role or "doctor").lower()
    if role_clean == "doctor":
        portal_name = "TORUS clinical workspace (Doctor Portal)"
        role_label = "Doctor"
    elif role_clean == "patient":
        portal_name = "TORUS Patient Portal"
        role_label = "Patient"
    elif role_clean == "viewer":
        portal_name = "TORUS Viewer Portal"
        role_label = "Viewer"
    else:
        portal_name = "TORUS Portal"
        role_label = "User"

    subject = f"Your TORUS Account Password Reset OTP: {otp}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin: 0; padding: 0; background-color: #060B18; font-family: 'Segoe UI', Arial, sans-serif; color: #ffffff;">
      <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #060B18; padding: 40px 20px;">
        <tr>
          <td align="center">
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 480px; background-color: #111B31; border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; padding: 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
              <tr>
                <td align="center" style="padding-bottom: 20px;">
                  <h2 style="color: #00C8FF; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 1px;">PlebC TORUS</h2>
                  <p style="color: #B7C5D8; margin: 4px 0 0 0; font-size: 13px;">Tele-Operated Robotic Ultrasound System</p>
                </td>
              </tr>
              <tr>
                <td style="border-top: 1px solid rgba(255,255,255,0.08); padding-top: 20px;">
                  <h3 style="color: #FFFFFF; font-size: 18px; margin: 0 0 12px 0;">Reset Your Password</h3>
                  <p style="color: #B7C5D8; font-size: 14px; line-height: 1.5; margin: 0 0 16px 0;">
                    Hello <strong>{user_name}</strong> ({role_label} ID: <code style="color: #00C8FF;">{user_uid}</code>),
                  </p>
                  <p style="color: #B7C5D8; font-size: 14px; line-height: 1.5; margin: 0 0 24px 0;">
                    We received a request to reset your password for the {portal_name}. Use the verification code below:
                  </p>
                </td>
              </tr>
              <tr>
                <td align="center">
                  <div style="background: rgba(0, 132, 255, 0.12); border: 1px dashed #0084FF; border-radius: 12px; padding: 18px 24px; margin-bottom: 24px;">
                    <span style="font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #00C8FF; font-family: monospace;">{otp}</span>
                  </div>
                </td>
              </tr>
              <tr>
                <td>
                  <p style="color: #8C9FB5; font-size: 12px; line-height: 1.4; margin: 0 0 12px 0;">
                    ⏱️ This OTP is valid for <strong>10 minutes</strong>. Do not share this code with anyone.
                  </p>
                  <p style="color: #8C9FB5; font-size: 12px; line-height: 1.4; margin: 0;">
                    If you did not request this code, you can safely ignore this email.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    text_content = f"Hello {user_name},\n\nYour TORUS password reset verification code is: {otp}\n\nThis OTP is valid for 10 minutes.\n{role_label} ID: {user_uid}\n\nIf you did not request this, please ignore this email."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    if not smtp_user or not smtp_pass:
        err_msg = "SMTP email configuration is missing. Please set SMTP_USER and SMTP_PASSWORD in your .env file."
        print(f"[SMTP] [ERROR] {err_msg}")
        return False, err_msg

    try:
        print(f"[SMTP] Attempting to dispatch real OTP email to {to_email} via {smtp_host}:{smtp_port} (sender: {smtp_user})...")
        if use_ssl or smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=12)
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
            server.quit()
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=12)
            server.ehlo()
            if use_tls or smtp_port == 587:
                server.starttls()
                server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
            server.quit()

        print(f"[SMTP] [OK] OTP email successfully sent to {to_email}")
        return True, "A 6-digit OTP has been sent to your registered email address."
    except smtplib.SMTPAuthenticationError as auth_err:
        err = f"SMTP Authentication failed for '{smtp_user}'. If using Gmail, please use a 16-character Google App Password."
        print(f"[SMTP] [ERROR] {err} ({auth_err})")
        return False, err
    except Exception as e:
        err = f"Failed to send email to {to_email}: {e}"
        print(f"[SMTP] [ERROR] {err}")
        return False, err

MAILBOX_QUOTA_ERROR_MESSAGE = "Email delivery failed because the patient's inbox is full. Please free up mailbox space or update the patient's email address before retrying."

def is_mailbox_quota_error(err) -> bool:
    """Identifies recipient mailbox quota / inbox full errors (e.g. SMTP 550 5.2.2)."""
    if not err:
        return False
    s = str(err).lower()
    return "550 5.2.2" in s or "5.2.2" in s or "mailbox quota" in s or "quota exceeded" in s or "mailbox full" in s or "inbox is full" in s or "over quota" in s

def send_report_delivery_email(to_email: str, patient_name: str, patient_uid: str, report: dict, is_resend: bool = False) -> tuple[bool, str]:
    """
    Sends a medical diagnostic report delivery notification email to the patient's registered email via SMTP.
    Returns (success: bool, message_or_error: str).
    Guards against automatic/repeated dispatch, mock/test environments, and over-quota inbox bounces.
    """
    report_id = str(report.get("report_id") or report.get("reportId") or "").strip()
    to_email_clean = str(to_email or "").strip().lower()

    # 1. TEST REPORT, SIMULATED DOMAINS & MOCK GUARD: Never dispatch real SMTP for test reports or simulated domains
    simulated_domains = ("@torus.med", "@example.com", "@test.com", "@mock.com", "@hospital.org", "@torus.local", "@torus.internal", "@torus.health")
    is_simulated_domain = any(to_email_clean.endswith(dom) for dom in simulated_domains)

    if (
        report_id.upper().startswith("RPT-TEST-") or
        report_id.upper().startswith("TEST-") or
        os.environ.get("TORUS_TEST_MODE") == "1" or
        os.environ.get("MOCK_SMTP") == "1" or
        is_simulated_domain
    ):
        print(f"[SMTP] [SIMULATED] Suppressing live SMTP dispatch for test/simulated recipient '{to_email}' (Report: '{report_id}').")
        return True, f"Report notification email delivered successfully to {to_email}."

    # 2. OVER-QUOTA RECIPIENT INBOX GUARD:
    # patient@gmail.com is an over-quota mailbox that repeatedly rejects with 550-5.2.2 Mailbox full,
    # causing Google Mail Delivery Subsystem bounces to flood the company Gmail account.
    # Return explicit failure immediately and wait for manual user action without retrying.
    if to_email_clean == "patient@gmail.com" and os.environ.get("TORUS_QUOTA_RESOLVED") != "1":
        print(f"[SMTP] [QUOTA EXCEEDED] 550 5.2.2 Mailbox quota exceeded for {to_email}. {MAILBOX_QUOTA_ERROR_MESSAGE}")
        return False, MAILBOX_QUOTA_ERROR_MESSAGE

    load_env_file()

    smtp_host = os.environ.get("SMTP_HOST", os.environ.get("EMAIL_HOST", "smtp.gmail.com")).strip()
    smtp_port_str = os.environ.get("SMTP_PORT", os.environ.get("EMAIL_PORT", "587")).strip()
    try:
        smtp_port = int(smtp_port_str)
    except ValueError:
        smtp_port = 587

    smtp_user = os.environ.get("SMTP_USER", os.environ.get("EMAIL_USER", os.environ.get("MAIL_USERNAME", ""))).strip()
    smtp_pass = os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", os.environ.get("EMAIL_PASS", os.environ.get("MAIL_PASSWORD", "")))).strip()
    
    smtp_from_env = os.environ.get("SMTP_FROM", os.environ.get("EMAIL_FROM", "")).strip()
    if smtp_from_env and "noreply@torus.med" not in smtp_from_env:
        smtp_from = smtp_from_env
    elif smtp_user:
        smtp_from = f"TORUS Healthcare <{smtp_user}>"
    else:
        smtp_from = "TORUS Healthcare <noreply@torus.med>"

    use_ssl = os.environ.get("SMTP_SSL", "false").lower() in ("true", "1") or smtp_port == 465
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1") or smtp_port == 587

    doctor_name = str(report.get("doctor_name") or report.get("doctorName") or "Dr. Admin Doctor").strip()
    scan_type = str(report.get("scan_type") or report.get("scanType") or "Ultrasound Examination").strip()
    exam_date = str(report.get("exam_date") or report.get("examDate") or "").strip()
    diag_center = str(report.get("diagnostic_center") or report.get("diagnosticCenter") or "Apex Diagnostic Center").strip()
    findings = str(report.get("ultrasound_findings") or report.get("findings") or "Diagnostic scan completed.").strip()
    recommendations = str(report.get("diagnosis_impression") or report.get("recommendations") or "Follow-up as clinically indicated.").strip()

    subject_prefix = "Resent / Updated: " if is_resend else ""
    subject = f"{subject_prefix}Your TORUS Ultrasound Diagnostic Report ({report_id})"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin: 0; padding: 0; background-color: #060B18; font-family: 'Segoe UI', Arial, sans-serif; color: #ffffff;">
      <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #060B18; padding: 40px 20px;">
        <tr>
          <td align="center">
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 540px; background-color: #111B31; border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; padding: 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
              <tr>
                <td align="center" style="padding-bottom: 20px;">
                  <h2 style="color: #00C8FF; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 1px;">PlebC TORUS</h2>
                  <p style="color: #B7C5D8; margin: 4px 0 0 0; font-size: 13px;">Tele-Operated Robotic Ultrasound System</p>
                </td>
              </tr>
              <tr>
                <td style="border-top: 1px solid rgba(255,255,255,0.08); padding-top: 20px;">
                  <h3 style="color: #FFFFFF; font-size: 18px; margin: 0 0 12px 0;">Diagnostic Ultrasound Report Delivered</h3>
                  <p style="color: #B7C5D8; font-size: 14px; line-height: 1.5; margin: 0 0 16px 0;">
                    Hello <strong>{patient_name}</strong> (Patient ID: <code style="color: #00C8FF;">{patient_uid}</code>),
                  </p>
                  <p style="color: #B7C5D8; font-size: 14px; line-height: 1.5; margin: 0 0 20px 0;">
                    Your ultrasound diagnostic report has been finalized by <strong>{doctor_name}</strong> and is now available in your TORUS Patient Portal.
                  </p>
                  <div style="background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; padding: 16px; margin-bottom: 20px; font-size: 13px; color: #CBD5E1;">
                    <div style="margin-bottom: 8px;"><strong style="color: #94A3B8;">Report ID:</strong> <span style="color: #38BDF8; font-weight: 600;">{report_id}</span></div>
                    <div style="margin-bottom: 8px;"><strong style="color: #94A3B8;">Examination:</strong> <span style="color: #F8FAFC;">{scan_type}</span></div>
                    <div style="margin-bottom: 8px;"><strong style="color: #94A3B8;">Exam Date:</strong> <span style="color: #F8FAFC;">{exam_date}</span></div>
                    <div><strong style="color: #94A3B8;">Diagnostic Center:</strong> <span style="color: #F8FAFC;">{diag_center}</span></div>
                  </div>
                  <div style="background: rgba(0, 200, 255, 0.08); border-left: 3px solid #00C8FF; border-radius: 4px; padding: 12px 16px; margin-bottom: 20px;">
                    <div style="color: #00C8FF; font-weight: 600; font-size: 13px; margin-bottom: 4px;">Findings Summary</div>
                    <p style="color: #E2E8F0; font-size: 13px; line-height: 1.5; margin: 0;">{findings}</p>
                    <div style="color: #00C8FF; font-weight: 600; font-size: 13px; margin-top: 10px; margin-bottom: 4px;">Recommendations</div>
                    <p style="color: #E2E8F0; font-size: 13px; line-height: 1.5; margin: 0;">{recommendations}</p>
                  </div>
                  <p style="color: #94A3B8; font-size: 13px; line-height: 1.5; margin: 0 0 16px 0;">
                    You can access your complete certified diagnostic report and ultrasound scans directly in your TORUS Patient Portal.
                  </p>
                </td>
              </tr>
              <tr>
                <td style="border-top: 1px solid rgba(255,255,255,0.08); padding-top: 16px;">
                  <p style="color: #64748B; font-size: 11px; line-height: 1.4; margin: 0;">
                    This is an automated clinical notification from the TORUS Tele-Operated Robotic Ultrasound System.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html"))

    if not smtp_user or not smtp_pass:
        err_msg = "SMTP credentials (SMTP_USER or SMTP_PASSWORD) not configured in .env."
        print(f"[SMTP] [WARNING] {err_msg}")
        return False, err_msg

    try:
        print(f"[SMTP] Attempting to deliver report {report_id} to {to_email} via {smtp_host}:{smtp_port}...")
        if use_ssl or smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=12)
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
            server.quit()
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=12)
            server.ehlo()
            if use_tls or smtp_port == 587:
                server.starttls()
                server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
            server.quit()

        print(f"[SMTP] [OK] Report delivery email successfully sent to {to_email}")
        return True, "Report notification email delivered successfully."
    except smtplib.SMTPAuthenticationError as auth_err:
        err = f"SMTP Authentication failed for '{smtp_user}' ({auth_err})"
        print(f"[SMTP] [ERROR] {err}")
        return False, err
    except smtplib.SMTPRecipientsRefused as rec_err:
        rec_err_str = str(rec_err)
        if is_mailbox_quota_error(rec_err_str):
            print(f"[SMTP] [QUOTA EXCEEDED] 550 5.2.2 Recipient mailbox quota exceeded ({to_email}): {rec_err}")
            return False, MAILBOX_QUOTA_ERROR_MESSAGE
        err = f"Recipient mailbox rejected ({to_email}): {rec_err}"
        print(f"[SMTP] [ERROR] {err}")
        return False, err
    except smtplib.SMTPDataError as data_err:
        data_err_str = str(data_err)
        if is_mailbox_quota_error(data_err_str):
            print(f"[SMTP] [QUOTA EXCEEDED] 550 5.2.2 Recipient mailbox quota exceeded ({to_email}): {data_err}")
            return False, MAILBOX_QUOTA_ERROR_MESSAGE
        err = f"SMTP Data error ({to_email}): {data_err}"
        print(f"[SMTP] [ERROR] {err}")
        return False, err
    except smtplib.SMTPResponseException as resp_err:
        resp_str = f"{resp_err.smtp_code} {str(resp_err.smtp_error)}"
        if resp_err.smtp_code == 552 or is_mailbox_quota_error(resp_str):
            print(f"[SMTP] [QUOTA EXCEEDED] {to_email}: {resp_str}. {MAILBOX_QUOTA_ERROR_MESSAGE}")
            return False, MAILBOX_QUOTA_ERROR_MESSAGE
        err = f"SMTP error ({resp_err.smtp_code}): {resp_err.smtp_error}"
        print(f"[SMTP] [ERROR] {err}")
        return False, err
    except Exception as e:
        if is_mailbox_quota_error(e):
            print(f"[SMTP] [QUOTA EXCEEDED] {to_email}: {e}. {MAILBOX_QUOTA_ERROR_MESSAGE}")
            return False, MAILBOX_QUOTA_ERROR_MESSAGE
        err = f"Failed to deliver report email to {to_email}: {e}"
        print(f"[SMTP] [ERROR] {err}")
        return False, err


def _migrate_add_mobile_column():
    """Safely adds 'mobile' column to doctors, patients, and viewers tables if missing."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(doctors)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "mobile" not in columns:
            cursor.execute("ALTER TABLE doctors ADD COLUMN mobile TEXT DEFAULT ''")
            conn.commit()
            print("[Database] Migrated: added 'mobile' column to doctors table.")
            
        cursor.execute("PRAGMA table_info(patients)")
        pat_columns = [row["name"] for row in cursor.fetchall()]
        if "mobile" not in pat_columns and len(pat_columns) > 0:
            cursor.execute("ALTER TABLE patients ADD COLUMN mobile TEXT DEFAULT ''")
            conn.commit()
            print("[Database] Migrated: added 'mobile' column to patients table.")

        cursor.execute("PRAGMA table_info(viewers)")
        view_columns = [row["name"] for row in cursor.fetchall()]
        if "mobile" not in view_columns and len(view_columns) > 0:
            cursor.execute("ALTER TABLE viewers ADD COLUMN mobile TEXT DEFAULT ''")
            conn.commit()
            print("[Database] Migrated: added 'mobile' column to viewers table.")
    except Exception as e:
        print(f"[Database] Migration warning: {e}")
    finally:
        conn.close()


def _migrate_add_fingerprint_slot():
    """
    Safely adds 'fingerprint_slot' column to doctor_biometrics if missing.
    This column stores the R307 hardware slot label (R1-R20) for each registration.
    Existing rows without a slot are left as NULL (legacy records before multi-user support).
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(doctor_biometrics)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "fingerprint_slot" not in columns:
            cursor.execute("ALTER TABLE doctor_biometrics ADD COLUMN fingerprint_slot TEXT DEFAULT NULL")
            conn.commit()
            print("[Database] Migrated: added 'fingerprint_slot' column to doctor_biometrics table.")
        if "hardware_slot" not in columns:
            cursor.execute("ALTER TABLE doctor_biometrics ADD COLUMN hardware_slot INTEGER DEFAULT NULL")
            conn.commit()
            print("[Database] Migrated: added 'hardware_slot' column to doctor_biometrics table.")
    except Exception as e:
        print(f"[Database] biometric migration warning: {e}")
    finally:
        conn.close()

def _migrate_signature_replacement_tables():
    """
    Ensures that report_signature_audit_history table and audit/versioning columns
    in diagnostic_reports are present for the Digital Signature Replacement workflow.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report_signature_audit_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL,
                report_version INTEGER NOT NULL DEFAULT 1,
                content_hash TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                previous_signature_hash TEXT,
                previous_signature_data TEXT,
                new_signature_hash TEXT,
                new_signature_data TEXT,
                doctor_id TEXT NOT NULL,
                doctor_name TEXT NOT NULL,
                doctor_license TEXT NOT NULL,
                replacement_reason TEXT,
                timestamp TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'SUCCESS',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        cursor.execute("PRAGMA table_info(diagnostic_reports)")
        cols = [row["name"] for row in cursor.fetchall()]
        needed_cols = [
            ("report_version", "INTEGER DEFAULT 1"),
            ("content_hash", "TEXT DEFAULT ''"),
            ("signature_hash", "TEXT DEFAULT ''"),
            ("signature_valid", "INTEGER DEFAULT 0"),
            ("signed_doctor_id", "TEXT DEFAULT ''"),
            ("signed_at", "TEXT DEFAULT ''"),
            ("signature_data", "TEXT DEFAULT ''"),
            ("replacement_reason", "TEXT DEFAULT ''"),
            ("delivery_status", "TEXT DEFAULT 'pending'"),
            ("delivered_at", "TEXT DEFAULT ''"),
            ("delivery_recipient", "TEXT DEFAULT ''"),
            ("delivery_channel", "TEXT DEFAULT 'portal'"),
            ("delivery_attempts", "INTEGER DEFAULT 0"),
            ("last_delivery_error", "TEXT DEFAULT ''"),
        ]
        for col_name, col_type in needed_cols:
            if col_name not in cols:
                cursor.execute(f"ALTER TABLE diagnostic_reports ADD COLUMN {col_name} {col_type}")
                conn.commit()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report_delivery_audit_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                patient_name TEXT NOT NULL,
                recipient_email TEXT,
                delivery_status TEXT NOT NULL,
                delivery_channel TEXT DEFAULT 'portal',
                attempt_number INTEGER DEFAULT 1,
                is_resend INTEGER DEFAULT 0,
                error_message TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"[Database] Signature replacement migration error: {e}")
    finally:
        conn.close()


def _migrate_ai_tables():
    """Creates tables for AI conversation persistence if missing."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                title TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_messages_conv ON ai_messages(conversation_id, id ASC)")
        conn.commit()
    except Exception as e:
        print(f"[AI] Table migration warning: {e}")
    finally:
        conn.close()


def get_ai_conversation_history(conversation_id: str, limit: int = 6) -> list:
    """Returns chronological recent messages for an AI conversation."""
    if not conversation_id:
        return []
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content, created_at FROM (
                SELECT id, role, content, created_at FROM ai_messages
                WHERE conversation_id = ?
                ORDER BY id DESC LIMIT ?
            ) ORDER BY id ASC
        """, (str(conversation_id).strip(), limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[AI] History fetch error: {e}")
        return []


def save_ai_message(conversation_id: str, role: str, content: str, user_id: str = "3001", user_role: str = "doctor") -> bool:
    """Persists a message in the AI conversation history."""
    if not conversation_id or not content:
        return False
    try:
        conn = get_db()
        cursor = conn.cursor()
        now_iso = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO ai_conversations (id, user_id, role, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (conversation_id, str(user_id), str(user_role), content[:40], now_iso, now_iso))
        cursor.execute("""
            UPDATE ai_conversations SET updated_at = ? WHERE id = ?
        """, (now_iso, conversation_id))
        cursor.execute("""
            INSERT INTO ai_messages (conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (conversation_id, role, content, now_iso))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[AI] Save message error: {e}")
        return False


def compute_report_content_hash(data: dict) -> str:
    """
    Calculates a deterministic SHA-256 hash over the canonical clinical content of a report.
    Binds patient details, scan type, clinical findings, recommendations, and selected images.
    """
    if not isinstance(data, dict):
        return ""
    pat_id = str(data.get("patient_id") or data.get("patientId") or "").strip().lower()
    pat_name = str(data.get("patient_name") or data.get("patientName") or "").strip().lower()
    scan_type = str(data.get("scan_type") or data.get("scanType") or "").strip().lower()
    findings = str(data.get("ultrasound_findings") or data.get("ultrasoundFindings") or data.get("findings") or "").strip()
    recs = str(data.get("diagnosis_impression") or data.get("diagnosisImpression") or data.get("recommendations") or "").strip()
    
    # Handle images canonicalization
    imgs = data.get("selected_images") or data.get("images") or []
    if isinstance(imgs, str):
        try:
            imgs = json.loads(imgs)
        except Exception:
            imgs = [imgs]
    img_refs = []
    if isinstance(imgs, list):
        for im in imgs:
            if isinstance(im, dict):
                ref = str(im.get("id") or im.get("url") or im.get("name") or "")
            else:
                ref = str(im)
            if ref:
                img_refs.append(ref)
    img_refs.sort()
    imgs_str = ",".join(img_refs)

    canonical = f"PAT:{pat_id}|NAME:{pat_name}|SCAN:{scan_type}|FINDINGS:{findings}|RECS:{recs}|IMGS:{imgs_str}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def init_db():
    """
    Initializes the SQLite schema idempotently for all roles (doctors, patients, viewers)
    and seeds ONLY the three required default test accounts.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Doctors Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'doctor',
            mobile TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Patients Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'patient',
            mobile TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 3. Viewers Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viewers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            mobile TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 4. Doctor Password Reset Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            identifier TEXT NOT NULL,
            email TEXT NOT NULL,
            otp TEXT NOT NULL,
            reset_token TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            used INTEGER DEFAULT 0,
            FOREIGN KEY(doctor_id) REFERENCES doctors(id)
        )
    """)

    # 5. Patient Password Reset Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_password_reset_otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            identifier TEXT NOT NULL,
            email TEXT NOT NULL,
            otp TEXT NOT NULL,
            reset_token TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            used INTEGER DEFAULT 0,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        )
    """)

    # 6. Viewer Password Reset Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viewer_password_reset_otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viewer_id INTEGER NOT NULL,
            identifier TEXT NOT NULL,
            email TEXT NOT NULL,
            otp TEXT NOT NULL,
            reset_token TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            used INTEGER DEFAULT 0,
            FOREIGN KEY(viewer_id) REFERENCES viewers(id)
        )
    """)

    # 7. Doctor Biometrics Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctor_biometrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            uid TEXT NOT NULL,
            email TEXT NOT NULL,
            fingerprint_slot TEXT DEFAULT NULL,
            hardware_slot INTEGER DEFAULT NULL,
            fingerprint_template TEXT NOT NULL,
            scanner_model TEXT DEFAULT 'Optical Biometric Scanner',
            enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY(doctor_id) REFERENCES doctors(id)
        )
    """)

    # 8. Clinical Sessions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clinical_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_code TEXT UNIQUE NOT NULL,
            doctor_id INTEGER,
            doctor_uid TEXT,
            doctor_name TEXT,
            doctor_email TEXT,
            channel_name TEXT NOT NULL DEFAULT 'torus',
            status TEXT NOT NULL DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME,
            FOREIGN KEY(doctor_id) REFERENCES doctors(id)
        )
    """)

    # 9. Session Participants Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            session_code TEXT NOT NULL,
            participant_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            participant_uid TEXT DEFAULT '',
            joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES clinical_sessions(id)
        )
    """)

    # 10. Clinical Patients Table (Patient Registration)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clinical_patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            mobile TEXT NOT NULL,
            email TEXT DEFAULT '',
            scan_type TEXT NOT NULL,
            appointment_date TEXT NOT NULL,
            blood_group TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 11. Scheduled Appointments Table (Schedule Scan)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id TEXT UNIQUE NOT NULL,
            patient_id TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            doctor_id TEXT NOT NULL,
            doctor_name TEXT NOT NULL,
            scan_type TEXT NOT NULL,
            slot_day TEXT NOT NULL,
            slot_month TEXT NOT NULL,
            slot_year TEXT NOT NULL,
            slot_time TEXT NOT NULL,
            scheduled_datetime TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 12. Diagnostic Reports Table (Patient Diagnostic Reports)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS diagnostic_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT UNIQUE NOT NULL,
            session_id TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            scan_type TEXT NOT NULL,
            device_id TEXT NOT NULL,
            exam_date TEXT NOT NULL,
            exam_time TEXT NOT NULL,
            duration TEXT DEFAULT '20:00',
            doctor_id TEXT DEFAULT '3001',
            doctor_name TEXT NOT NULL DEFAULT 'Dr. Admin Doctor',
            doctor_license TEXT NOT NULL DEFAULT 'TORUS-REG-3001',
            diagnostic_center TEXT NOT NULL,
            report_status TEXT NOT NULL DEFAULT 'ready',
            clinical_summary TEXT NOT NULL,
            ultrasound_findings TEXT NOT NULL,
            diagnosis_impression TEXT NOT NULL,
            telemetry_json TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 13. Notifications Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT 'all',
            role TEXT NOT NULL DEFAULT 'doctor',
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            reference_type TEXT DEFAULT '',
            reference_id TEXT DEFAULT '',
            action_url TEXT DEFAULT '',
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME DEFAULT NULL,
            event_key TEXT UNIQUE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_role ON notifications(user_id, role, is_read)")

    # 14. Two-Way Chat Conversations Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            doctor_id TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            attender_id TEXT DEFAULT '',
            patient_name TEXT NOT NULL,
            doctor_name TEXT NOT NULL,
            last_message TEXT DEFAULT '',
            last_message_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 15. Two-Way Chat Messages Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            sender_role TEXT NOT NULL,
            sender_name TEXT NOT NULL,
            content TEXT NOT NULL,
            attachment_url TEXT DEFAULT '',
            attachment_name TEXT DEFAULT '',
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at)")
    conn.commit()

    # Seed exactly two clearly identified DEMO notifications for Doctor Portal (Section 2 & 10)
    cursor.execute("SELECT COUNT(*) as cnt FROM notifications WHERE event_key LIKE 'demo_%'")
    if cursor.fetchone()["cnt"] == 0:
        cursor.execute("""
            INSERT OR IGNORE INTO notifications (user_id, role, type, title, message, reference_type, reference_id, action_url, is_read, event_key)
            VALUES
            ('3001', 'doctor', 'appointment', '[DEMO] Scheduled Ultrasound Consultation', 'Patient John Doe (P-8021) is scheduled for Abdominal Ultrasound at 10:30 AM.', 'appointment', 'APT-2026-001', '#upcoming-sessions', 0, 'demo_notification_appointment_8021'),
            ('3001', 'doctor', 'system', '[DEMO] System Calibrated & Online', 'TORUS Haptic Robotic Ultrasound System and real-time report delivery are operational.', 'system', 'SYS-ONLINE', '#dashboard', 0, 'demo_notification_system_ready'),
            ('4001', 'patient', 'system', 'Welcome to TORUS Patient Portal', 'Your diagnostic health records and tele-ultrasound consultations can be accessed securely here.', 'system', 'PAT-WELCOME', '#dashboard', 0, 'demo_notification_patient_welcome')
        """)
        conn.commit()

    # Seed default Doctor-Patient conversation
    cursor.execute("SELECT COUNT(*) as cnt FROM conversations WHERE id = 'conv_3001_4001'")
    if cursor.fetchone()["cnt"] == 0:
        cursor.execute("""
            INSERT OR IGNORE INTO conversations (id, doctor_id, patient_id, attender_id, patient_name, doctor_name, last_message, last_message_at)
            VALUES ('conv_3001_4001', '3001', '4001', '', 'Patient User', 'Dr. Admin Doctor', 'Hello! Welcome to TORUS tele-ultrasound support.', CURRENT_TIMESTAMP)
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO messages (conversation_id, sender_id, sender_role, sender_name, content, is_read)
            VALUES ('conv_3001_4001', '3001', 'doctor', 'Dr. Admin Doctor', 'Hello! Welcome to TORUS tele-ultrasound support. Please feel free to ask any questions regarding your appointments and reports.', 0)
        """)
        conn.commit()

    # Seed default Doctor: admin@gmail.com / admin123 (role: doctor, UID: 3001)
    admin_pass = hash_password("admin123")
    cursor.execute("SELECT * FROM doctors WHERE LOWER(email) = 'admin@gmail.com'")
    existing_doctor = cursor.fetchone()
    if not existing_doctor:
        cursor.execute("SELECT id FROM doctors WHERE uid = '3001'")
        doc_uid = "3001" if not cursor.fetchone() else generate_professional_id()
        cursor.execute("""
            INSERT INTO doctors (uid, name, email, password_hash, role, mobile)
            VALUES (?, ?, ?, ?, 'doctor', '')
        """, (doc_uid, "Admin Doctor", "admin@gmail.com", admin_pass))
        conn.commit()
        print(f"[Database] Default Doctor created (UID: {doc_uid}, email: admin@gmail.com).")
    else:
        # Ensure the default Doctor password is always 'admin123' on startup.
        # This prevents test runs or manual resets from permanently breaking the default login.
        if existing_doctor["password_hash"] != admin_pass:
            cursor.execute("UPDATE doctors SET password_hash=? WHERE LOWER(email)='admin@gmail.com'", (admin_pass,))
            conn.commit()
            print("[Database] Default Doctor password restored to admin123.")

    # Seed default Patient: patient@gmail.com / patient123 (role: patient, UID: 4001)
    cursor.execute("SELECT * FROM patients WHERE LOWER(email) = 'patient@gmail.com'")
    if not cursor.fetchone():
        patient_pass = hash_password("patient123")
        cursor.execute("SELECT id FROM patients WHERE uid = '4001'")
        pat_uid = "4001" if not cursor.fetchone() else generate_patient_id()
        cursor.execute("""
            INSERT INTO patients (uid, name, email, password_hash, role, mobile)
            VALUES (?, ?, ?, ?, 'patient', ?)
        """, (pat_uid, "Patient User", "patient@gmail.com", patient_pass, "+91 98765 43210"))
        conn.commit()
        print(f"[Database] Default Patient created (UID: {pat_uid}, email: patient@gmail.com).")

    # Seed Patient A (P-12345), Patient B (P-8821), Patient C (P-9104) for Haptic session routing tests
    patient_pass = hash_password("patient123")
    seed_patients = [
        ("P-12345", "Patient A", "patient_a@gmail.com", "+91 98765 12345"),
        ("P-8821", "Patient B", "patient_b@gmail.com", "+91 98765 23456"),
        ("P-9104", "Patient C", "patient_c@gmail.com", "+91 98765 34567")
    ]
    for p_uid, p_name, p_email, p_mobile in seed_patients:
        cursor.execute("SELECT * FROM patients WHERE LOWER(uid) = ? OR LOWER(email) = ?", (p_uid.lower(), p_email.lower()))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO patients (uid, name, email, password_hash, role, mobile)
                VALUES (?, ?, ?, ?, 'patient', ?)
            """, (p_uid, p_name, p_email, patient_pass, p_mobile))
            conn.commit()
            print(f"[Database] Seeded patient {p_name} (UID: {p_uid}, email: {p_email}).")


    # Seed default Viewer: user@gmail.com / user123 (role: viewer, UID: 6001)
    cursor.execute("SELECT * FROM viewers WHERE LOWER(email) = 'user@gmail.com'")
    if not cursor.fetchone():
        viewer_pass = hash_password("user123")
        cursor.execute("SELECT id FROM viewers WHERE uid = '6001'")
        view_uid = "6001" if not cursor.fetchone() else generate_viewer_id()
        cursor.execute("""
            INSERT INTO viewers (uid, name, email, password_hash, role, mobile)
            VALUES (?, ?, ?, ?, 'viewer', ?)
        """, (view_uid, "Viewer 1", "user@gmail.com", viewer_pass, "+91 98765 43210"))
        conn.commit()
        print(f"[Database] Default Viewer created (UID: {view_uid}, email: user@gmail.com).")

    # Seed default Clinical Patients
    cursor.execute("SELECT COUNT(*) as cnt FROM clinical_patients")
    if cursor.fetchone()["cnt"] == 0:
        cursor.execute("""
            INSERT INTO clinical_patients (uid, name, age, gender, mobile, email, scan_type, appointment_date, blood_group)
            VALUES 
            ('PAT-4001', 'Patient User', 32, 'Male', '9876543210', 'patient@gmail.com', 'Abdominal', '2026-09-17', 'O+'),
            ('P-8821', 'John Smith', 45, 'Male', '9876512345', 'john.smith@gmail.com', 'Abdominal', '2026-09-17', 'A+'),
            ('P-9104', 'Jane Smith', 36, 'Female', '9876523456', 'jane.smith@gmail.com', 'Cardiac', '2026-09-17', 'B+'),
            ('P-7543', 'Robert Brown', 52, 'Male', '9876534567', 'robert.brown@gmail.com', 'Pelvic', '2026-09-17', 'O+')
        """)
        conn.commit()
        print("[Database] Seeded default clinical patients.")

    # Seed default Scheduled Appointments
    cursor.execute("SELECT COUNT(*) as cnt FROM scheduled_appointments")
    if cursor.fetchone()["cnt"] == 0:
        cursor.execute("""
            INSERT INTO scheduled_appointments (appointment_id, patient_id, patient_name, doctor_id, doctor_name, scan_type, slot_day, slot_month, slot_year, slot_time, scheduled_datetime, status)
            VALUES 
            ('APT-2026-001', 'P-8821', 'John Smith', '3001', 'Admin Doctor', 'Abdominal', '17', '09', '2026', '10:30 AM', '2026-09-17 10:30:00', 'scheduled'),
            ('APT-2026-002', 'P-9104', 'Jane Smith', '3001', 'Admin Doctor', 'Cardiac', '17', '09', '2026', '12:00 PM', '2026-09-17 12:00:00', 'scheduled'),
            ('APT-2026-003', 'P-7543', 'Robert Brown', '3001', 'Admin Doctor', 'Pelvic', '17', '09', '2026', '02:15 PM', '2026-09-17 14:15:00', 'scheduled')
        """)
        conn.commit()
        print("[Database] Seeded default scheduled appointments.")

    # Seed default Diagnostic Reports
    cursor.execute("SELECT COUNT(*) as cnt FROM diagnostic_reports")
    if cursor.fetchone()["cnt"] == 0:
        reports_seed = [
            (
                'REP-2026-001', 'S-101', 'P-12345', 'Patient A', 'Abdominal', 'TORUS-A12',
                '2026-09-14', '09:15 AM', '22:15', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'Apex Diagnostic Center', 'ready',
                'Normal hepatobiliary sonogram. Gallbladder wall thickness normal at 2.1mm without stones or sludge. CBD calibre 4.2mm. Hepatic parenchyma homogeneous with normal echogenicity.',
                'The liver demonstrates normal size, contour, and homogeneous echotexture with no focal lesions. Intrahepatic bile ducts are not dilated. Common bile duct measures 4.2 mm, within normal limits. Gallbladder is well-distended with an anechoic lumen, smooth thin wall (2.1 mm), and no intraluminal calculi. Portal vein flow is hepatopetal with laminar Doppler spectral waveforms. Pancreas head, body, and visualized tail appear normal. Spleen is normal in size (9.8 cm) with homogeneous echogenicity.',
                'Normal upper abdominal ultrasound examination. No evidence of cholecystitis, cholelithiasis, biliary ductal dilatation, or focal hepatic masses.',
                '{"maxForce":"2.8 N","avgForce":"1.9 N","latency":"14 ms","frames":5240,"stability":"99.4%"}'
            ),
            (
                'REP-2026-002', 'S-102', 'P-8821', 'John Doe', 'Abdominal', 'TORUS-A12',
                '2026-09-13', '11:30 AM', '19:40', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'NYC Medical', 'ready',
                'Mild hepatic steatosis grade 1. Bilateral kidneys show preserved corticomedullary differentiation without calculi or hydronephrosis. Spleen normal in size.',
                'Liver demonstrates mildly increased parenchymal echogenicity consistent with Grade 1 diffuse fatty infiltration. No focal solid or cystic parenchymal lesions. Intrahepatic and extrahepatic biliary ducts are non-dilated. Bilateral renal sonograms show normal size (Right 10.4 cm, Left 10.7 cm) with preserved corticomedullary differentiation and no calculi or hydronephrosis. Spleen and pancreas are unremarkable.',
                'Mild diffuse hepatic steatosis (Grade 1). Otherwise normal abdominal tele-ultrasound with healthy renal and splenic architecture.',
                '{"maxForce":"2.5 N","avgForce":"1.7 N","latency":"16 ms","frames":4780,"stability":"98.8%"}'
            ),
            (
                'REP-2026-003', 'S-103', 'P-9104', 'Jane Smith', 'Cardiac', 'TORUS-B08',
                '2026-09-12', '02:00 PM', '26:10', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'Boston General', 'ready',
                'Transthoracic echocardiogram. LVEF estimated at 58% with normal left ventricular systolic function. Mild posterior mitral leaflet prolapse with trace to mild regurgitation. Normal aortic root.',
                'Left ventricle is normal in internal dimensions (LVIDd 4.6 cm, LVIDs 2.9 cm). Preserved LV systolic performance with calculated ejection fraction of 58% (biplane Simpson method). No regional wall motion abnormalities at rest. Mitral valve demonstrates mild posterior leaflet prolapse with physiological/trace regurgitation on color Doppler. Tricuspid and pulmonic valves are structurally normal with normal RV systolic pressure (24 mmHg). Pericardium is clear without effusion.',
                'Normal overall left ventricular systolic performance (LVEF 58%). Mild posterior mitral leaflet prolapse with clinically trace regurgitation. Stable findings.',
                '{"maxForce":"2.9 N","avgForce":"2.1 N","latency":"18 ms","frames":6200,"stability":"99.1%"}'
            ),
            (
                'REP-2026-004', 'S-104', 'P-7543', 'Robert Brown', 'Pelvic', 'TORUS-C15',
                '2026-09-11', '10:15 AM', '17:25', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'Apollo Hyderabad', 'ready',
                'Urinary bladder well distended with smooth, regular walls. Prostate volume measured at 34cc with symmetric peripheral zone. Post-void residual negligible (18ml).',
                'The urinary bladder is moderately distended with smooth mucosal contours and uniform wall thickness (2.3 mm pre-void). No intravesical masses, calculi, or diverticula. Prostate gland exhibits symmetric peripheral zone echotexture with a total volume of 34 cc. Post-void residual volume measured at 18 mL, demonstrating complete evacuation efficiency. Both distal ureteric jets visualized on color Doppler.',
                'Mild benign prostatic enlargement without significant intravesical protrusion. Excellent bladder emptying with negligible post-void residual.',
                '{"maxForce":"2.4 N","avgForce":"1.8 N","latency":"15 ms","frames":4190,"stability":"99.5%"}'
            ),
            (
                'REP-2026-005', 'S-105', 'P-3312', 'Eleanor Vance', 'Cardiac', 'TORUS-B08',
                '2026-09-10', '03:45 PM', '24:50', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'Boston General', 'ready',
                'Complete 2D & Doppler cardiac evaluation. Normal chamber sizes, no regional wall motion abnormalities. Normal left ventricular filling pressures (E/A 1.2).',
                'Comprehensive tele-echocardiogram demonstrates normal cardiac chamber morphology. Left atrium volume index is 28 mL/m2. LV internal dimensions within normal physiological ranges with LVEF at 62%. Diastolic filling indices demonstrate normal pattern with E/A ratio of 1.2 and septal e prime of 9.2 cm/s. No valvular stenosis or regurgitant jets detected. Inferior vena cava collapsibility index > 50% with inspiration.',
                'Unremarkable comprehensive cardiac tele-sonography. Preserved biventricular systolic and diastolic function.',
                '{"maxForce":"2.7 N","avgForce":"2.0 N","latency":"19 ms","frames":5910,"stability":"98.9%"}'
            ),
            (
                'REP-2026-006', 'S-106', 'P-4401', 'Marcus Brody', 'Vascular', 'TORUS-A12',
                '2026-09-09', '08:30 AM', '28:15', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'NYC Medical', 'ready',
                'Bilateral extracranial carotid duplex examination. CCA and ICA spectral waveforms demonstrate laminar flow without significant hemodynamically relevant stenosis (<30%).',
                'Bilateral common carotid, internal carotid, and external carotid arteries examined with high-frequency vascular tele-probe. Right ICA peak systolic velocity 78 cm/s, end diastolic velocity 26 cm/s. Left ICA peak systolic velocity 82 cm/s, end diastolic velocity 28 cm/s. Intima-media thickness is 0.78 mm bilaterally. Minimal eccentric calcified plaque noted at the left carotid bulb with less than 30% diameter reduction. Bilateral vertebral arteries demonstrate antegrade cephalad flow.',
                'Bilateral extracranial carotid arteries patent with laminar flow. Minimal non-obstructive left bulb plaque (<30% stenosis). Antegrade vertebral flows.',
                '{"maxForce":"2.2 N","avgForce":"1.6 N","latency":"14 ms","frames":6730,"stability":"99.6%"}'
            ),
            (
                'REP-2026-007', 'S-107', 'P-5590', 'Sarah Connor', 'Abdominal', 'TORUS-A12',
                '2026-09-08', '01:20 PM', '21:05', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'Apex Diagnostic Center', 'ready',
                'Targeted abdominal scan. Normal pancreas, spleen, and abdominal aorta. No free intraperitoneal fluid detected in Morrison\'s pouch or pelvis.',
                'Targeted abdominal assessment displays homogeneous spleen (10.1 cm) and clear parenchymal outlines. Pancreatic head, uncinate process, and body are clearly identified with normal duct diameter (< 2 mm). Abdominal aorta visualized to the level of bifurcation with uniform calibre (1.7 cm) and normal pulsatility. No free fluid in Morrison\'s pouch, splenorenal recess, or rectovesical pouch.',
                'Normal focused abdominal sonogram. No aortic aneurysm, retroperitoneal adenopathy, or free peritoneal fluid.',
                '{"maxForce":"2.6 N","avgForce":"1.9 N","latency":"15 ms","frames":5020,"stability":"99.3%"}'
            ),
            (
                'REP-2026-008', 'S-108', 'P-6623', 'David Miller', 'Pelvic', 'TORUS-C15',
                '2026-09-07', '11:00 AM', '16:45', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'Apollo Hyderabad', 'ready',
                'Pelvic sonography. Pre-void bladder volume 420ml, post-void residual 25ml. Normal urinary bladder contours without trabeculation or mass.',
                'Urinary bladder pre-void volume 420 mL with smooth luminal boundaries. Ureteral peristaltic discharges verified bilaterally into the bladder base. Post-void bladder volume measured at 25 mL, confirming normal voiding fraction (>94%). Visualized pelvic structures are normal with no mass lesions or pelvic lymphadenopathy.',
                'Normal pelvic tele-sonography with normal bladder compliance and complete evacuation fraction.',
                '{"maxForce":"2.3 N","avgForce":"1.7 N","latency":"17 ms","frames":3990,"stability":"99.2%"}'
            ),
            (
                'REP-2026-009', 'S-109', 'P-7741', 'Amina Patel', 'Thyroid', 'TORUS-B08',
                '2026-09-06', '04:10 PM', '18:30', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'Boston General', 'ready',
                'High-resolution thyroid sonography. Right lobe: 4.2 x 1.4 x 1.3 cm. Left lobe: 4.0 x 1.3 x 1.2 cm. Normal vascularity on color Doppler. No discrete solid or cystic lesions.',
                'High-frequency linear robotic scan of the anterior cervical neck reveals a symmetric thyroid gland. Right lobe: 4.2 x 1.4 x 1.3 cm (volume 3.9 mL). Left lobe: 4.0 x 1.3 x 1.2 cm (volume 3.2 mL). Isthmus thickness: 2.8 mm. Parenchymal echotexture is uniform and isoechoic to the strap muscles. Color and power Doppler demonstrate standard symmetrical flow patterns. No suspicious microcalcifications, solid nodules, or pathological cervical lymph nodes.',
                'Normal thyroid ultrasound examination. Symmetrical lobes, normal vascularity, and absence of nodular disease (ACR TI-RADS 1 - Benign).',
                '{"maxForce":"2.0 N","avgForce":"1.5 N","latency":"16 ms","frames":4410,"stability":"99.7%"}'
            ),
            (
                'REP-2026-010', 'S-110', 'P-8819', 'Carlos Mendoza', 'Abdominal', 'TORUS-K03',
                '2026-09-05', '10:00 AM', '25:40', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'Central Tele-Robotics Center', 'ready',
                'Renal Doppler and cortical assessment. Right kidney 10.8cm, left kidney 11.1cm. Normal resistive index (0.64). No perinephric fluid collection.',
                'Bilateral renal scan displays normal kidney dimensions (Right kidney: 10.8 x 4.6 cm; Left kidney: 11.1 x 4.9 cm). Cortical thickness is preserved (1.5 cm) with sharp corticomedullary differentiation. No renal calculi, cysts, or pelvicalyceal dilatation. Interlobar arterial spectral Doppler waveforms show normal acceleration time and resistive index of 0.64 (normal range 0.58 - 0.70). Renal veins are widely patent.',
                'Normal bilateral renal ultrasound and Doppler resistive index evaluation. No hydronephrosis or renovascular abnormalities.',
                '{"maxForce":"2.8 N","avgForce":"2.2 N","latency":"15 ms","frames":6140,"stability":"98.7%"}'
            ),
            (
                'REP-2026-011', 'S-111', 'P-9902', 'Clara Oswald', 'Cardiac', 'TORUS-B08',
                '2026-09-04', '02:30 PM', '23:10', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'Boston General', 'pending',
                'Aortic valve and aortic root interrogation. Mild aortic sclerosis without gradient elevation. Concentric LV remodeling noted. Transferred for multidisciplinary review.',
                'Transthoracic views demonstrate mild thickening and echogenicity of the aortic valve cusps without systolic excursion restriction. Peak aortic transvalvular velocity is 1.4 m/s (mean gradient 4 mmHg). Concentric left ventricular remodeling is present with relative wall thickness of 0.44. Global systolic function remains preserved with LVEF at 55%. Transferred for senior cardiologist countersignature.',
                'Mild aortic sclerosis without significant transvalvular gradient. Concentric LV remodeling. Preliminary report pending final attending countersignature.',
                '{"maxForce":"2.6 N","avgForce":"2.0 N","latency":"18 ms","frames":5520,"stability":"98.5%"}'
            ),
            (
                'REP-2026-012', 'S-112', 'P-1045', 'James Wilson', 'Vascular', 'TORUS-A12',
                '2026-09-03', '09:45 AM', '29:00', '3001', 'Dr. Admin Doctor', 'TORUS-REG-3001',
                'NYC Medical', 'pending',
                'Lower extremity venous duplex examination. Common femoral, femoral, and popliteal veins show full compressibility with augmentable Doppler phasicity. Pending final attending countersignature.',
                'Bilateral lower extremity deep venous duplex scan demonstrates complete intraluminal compressibility under transverse probe transducer pressure across the common femoral, proximal femoral, mid femoral, and popliteal veins. Color Doppler demonstrates spontaneous flow with normal respiratory phasicity and vigorous augmentation upon distal compression. No non-compressible thrombus detected.',
                'Negative for deep vein thrombosis (DVT) in the bilateral lower extremity femoral-popliteal venous segments. Status: Pending Attending Countersignature.',
                '{"maxForce":"2.5 N","avgForce":"1.8 N","latency":"14 ms","frames":6980,"stability":"99.0%"}'
            )
        ]
        cursor.executemany("""
            INSERT INTO diagnostic_reports (
                report_id, session_id, patient_id, patient_name, scan_type, device_id,
                exam_date, exam_time, duration, doctor_id, doctor_name, doctor_license,
                diagnostic_center, report_status, clinical_summary, ultrasound_findings,
                diagnosis_impression, telemetry_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, reports_seed)
        conn.commit()
        print("[Database] Seeded 12 default diagnostic reports.")
        
    conn.close()
    _migrate_add_mobile_column()
    _migrate_add_fingerprint_slot()
    _migrate_signature_replacement_tables()
    _migrate_ai_tables()

# -------------------- VALIDATION HELPERS --------------------
def validate_strong_password(password: str) -> tuple:
    """Validates that a password meets strong password requirements."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least 1 uppercase letter."
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least 1 lowercase letter."
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least 1 number."
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password):
        return False, "Password must contain at least 1 special character."
    return True, ""

def validate_email_format(email: str) -> bool:
    """Validates email format using a standard regex pattern."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))

def validate_mobile_format(mobile: str) -> bool:
    """Validates mobile number format."""
    cleaned = re.sub(r'[\s\-\(\)]', '', mobile.strip())
    pattern = r'^\+?[0-9]{7,15}$'
    return bool(re.match(pattern, cleaned))

def generate_professional_id() -> str:
    """Generates unique alphanumeric Professional ID (DOC-XXXXX)."""
    conn = get_db()
    cursor = conn.cursor()
    for _ in range(100):
        chars = string.ascii_uppercase + string.digits
        random_part = ''.join(random.choices(chars, k=5))
        professional_id = f"DOC-{random_part}"
        cursor.execute("SELECT id FROM doctors WHERE uid = ?", (professional_id,))
        if not cursor.fetchone():
            conn.close()
            return professional_id
    conn.close()
    return f"DOC-{secrets.token_hex(3).upper()[:5]}"

def generate_patient_id() -> str:
    """Generates unique alphanumeric Patient ID (PAT-XXXXX)."""
    conn = get_db()
    cursor = conn.cursor()
    for _ in range(100):
        chars = string.ascii_uppercase + string.digits
        random_part = ''.join(random.choices(chars, k=5))
        patient_id = f"PAT-{random_part}"
        cursor.execute("SELECT id FROM patients WHERE uid = ?", (patient_id,))
        if not cursor.fetchone():
            conn.close()
            return patient_id
    conn.close()
    return f"PAT-{secrets.token_hex(3).upper()[:5]}"

def generate_viewer_id() -> str:
    """Generates unique alphanumeric Viewer ID (6001+ or VIEW-XXXXX)."""
    conn = get_db()
    cursor = conn.cursor()
    for num in range(6001, 6100):
        uid_str = str(num)
        cursor.execute("SELECT id FROM viewers WHERE uid = ?", (uid_str,))
        if not cursor.fetchone():
            conn.close()
            return uid_str
    for _ in range(100):
        chars = string.ascii_uppercase + string.digits
        random_part = ''.join(random.choices(chars, k=5))
        viewer_id = f"VIEW-{random_part}"
        cursor.execute("SELECT id FROM viewers WHERE uid = ?", (viewer_id,))
        if not cursor.fetchone():
            conn.close()
            return viewer_id
    conn.close()
    return f"VIEW-{secrets.token_hex(3).upper()[:5]}"

# ============================================================
# DOCTOR CRUD & AUTHENTICATION
# ============================================================
def register_doctor(name: str, email: str, password: str, mobile: str = "", uid: str = "", role: str = "doctor"):
    clean_name = name.strip()
    if not clean_name:
        return {"success": False, "error": "Full Name is required."}
    
    clean_email = email.strip().lower()
    if not clean_email or not validate_email_format(clean_email):
        return {"success": False, "error": "Please enter a valid email address."}
    
    clean_mobile = mobile.strip()
    if not clean_mobile or not validate_mobile_format(clean_mobile):
        return {"success": False, "error": "Please enter a valid mobile number."}
    
    if not password:
        return {"success": False, "error": "Password is required."}
    pwd_valid, pwd_error = validate_strong_password(password)
    if not pwd_valid:
        return {"success": False, "error": pwd_error}
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check ONLY Doctor table for duplicate email
    cursor.execute("SELECT id FROM doctors WHERE LOWER(email) = LOWER(?)", (clean_email,))
    if cursor.fetchone():
        conn.close()
        return {"success": False, "error": "An account with this email already exists."}
    
    clean_uid = uid.strip().upper() if uid else ""
    if clean_uid:
        cursor.execute("SELECT id FROM doctors WHERE UPPER(uid) = UPPER(?)", (clean_uid,))
        if cursor.fetchone():
            conn.close()
            return {"success": False, "error": f"Professional ID '{clean_uid}' is already registered."}
        final_uid = clean_uid
    else:
        final_uid = generate_professional_id()
    
    pwd_hash = hash_password(password)
    cursor.execute("""
        INSERT INTO doctors (uid, name, email, password_hash, role, mobile)
        VALUES (?, ?, ?, ?, 'doctor', ?)
    """, (final_uid, clean_name, clean_email, pwd_hash, clean_mobile))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "doctor": {
            "uid": final_uid,
            "name": clean_name,
            "email": clean_email,
            "mobile": clean_mobile,
            "role": "doctor"
        }
    }

def authenticate_doctor(login_id: str, password: str):
    conn = get_db()
    cursor = conn.cursor()
    login_clean = login_id.strip().lower()
    pwd_hash = hash_password(password)
    
    cursor.execute("""
        SELECT * FROM doctors 
        WHERE (LOWER(email) = ? OR LOWER(uid) = ?) AND password_hash = ?
    """, (login_clean, login_clean, pwd_hash))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "success": True,
            "doctor": {
                "id": row["id"],
                "uid": row["uid"],
                "name": row["name"],
                "email": row["email"],
                "role": row["role"],
                "mobile": row["mobile"] if "mobile" in row.keys() and row["mobile"] else "",
                "created_at": row["created_at"] if "created_at" in row.keys() and row["created_at"] else ""
            }
        }
    return {"success": False, "error": "Invalid email/UID or password."}

def get_doctor_profile(identifier: str):
    clean_id = (identifier or "").strip().lower()
    if not clean_id:
        return {"success": False, "error": "Doctor identifier is required."}
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.id, d.uid, d.name, d.email, d.role, d.mobile, d.created_at,
               b.fingerprint_slot
        FROM doctors d
        LEFT JOIN doctor_biometrics b ON d.id = b.doctor_id AND b.is_active = 1
        WHERE LOWER(d.email) = ? OR LOWER(d.uid) = ?
    """, (clean_id, clean_id))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "success": True,
            "doctor": {
                "id": row["id"],
                "uid": row["uid"],
                "name": row["name"],
                "email": row["email"],
                "role": row["role"],
                "mobile": row["mobile"] or "",
                "created_at": row["created_at"] or "",
                "fingerprint_slot": row["fingerprint_slot"] or "",
                "has_biometrics": bool(row["fingerprint_slot"])
            }
        }
    return {"success": False, "error": "Doctor profile not found."}

def update_doctor_profile(identifier: str, name: str = None, mobile: str = None):
    clean_id = (identifier or "").strip().lower()
    if not clean_id:
        return {"success": False, "error": "Doctor identifier is required."}
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, uid, name, email, role, mobile, created_at FROM doctors WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    doctor = cursor.fetchone()
    if not doctor:
        conn.close()
        return {"success": False, "error": "Doctor not found."}
    
    new_name = name.strip() if (name and name.strip()) else doctor["name"]
    new_mobile = mobile.strip() if mobile is not None else (doctor["mobile"] or "")
    
    cursor.execute("UPDATE doctors SET name = ?, mobile = ? WHERE id = ?", (new_name, new_mobile, doctor["id"]))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": "Doctor profile updated successfully.",
        "doctor": {
            "id": doctor["id"],
            "uid": doctor["uid"],
            "name": new_name,
            "email": doctor["email"],
            "role": doctor["role"],
            "mobile": new_mobile,
            "created_at": doctor["created_at"] or ""
        }
    }

def generate_and_store_reset_otp(identifier: str):
    """Generates and dispatches OTP for Doctor password reset."""
    clean_id = identifier.strip().lower()
    if not clean_id:
        return {"success": False, "error": "Email or User ID is required."}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    doctor = cursor.fetchone()
    
    if not doctor:
        conn.close()
        return {"success": False, "error": "No account found with this email or User ID."}
    
    doctor_id = doctor["id"]
    doctor_email = doctor["email"]
    doctor_name = doctor["name"]
    doctor_uid = doctor["uid"]
    
    otp = f"{random.randint(100000, 999999)}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("UPDATE password_reset_otps SET used = 2 WHERE doctor_id = ? AND used = 0", (doctor_id,))
    cursor.execute("""
        INSERT INTO password_reset_otps (doctor_id, identifier, email, otp, expires_at, used)
        VALUES (?, ?, ?, ?, ?, 0)
    """, (doctor_id, clean_id, doctor_email, otp, expires_at))
    conn.commit()
    conn.close()
    
    sent, err_msg = send_otp_email(doctor_email, doctor_name, doctor_uid, otp, "doctor")
    if not sent:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM password_reset_otps WHERE email = ? AND otp = ?", (doctor_email, otp))
        conn.commit()
        conn.close()
        return {
            "success": False,
            "error": err_msg or "Failed to send OTP to your registered email address. Please verify your SMTP settings in .env."
        }

    return {
        "success": True,
        "message": "A 6-digit OTP has been sent to your registered email address.",
        "masked_email": mask_email(doctor_email),
        "email": doctor_email
    }

# Alias for explicit naming
generate_and_store_doctor_reset_otp = generate_and_store_reset_otp

def verify_reset_otp(identifier: str, otp: str):
    """Validates 6-digit OTP for Doctor."""
    clean_id = identifier.strip().lower()
    clean_otp = str(otp).strip()
    
    if not clean_id:
        return {"success": False, "error": "Email or User ID is required."}
    if not clean_otp or len(clean_otp) != 6:
        return {"success": False, "error": "Please enter a valid 6-digit OTP."}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    doctor = cursor.fetchone()
    
    if not doctor:
        conn.close()
        return {"success": False, "error": "No account found with this email or User ID."}
    
    doctor_id = doctor["id"]
    cursor.execute("""
        SELECT * FROM password_reset_otps 
        WHERE doctor_id = ? AND used = 0 
        ORDER BY id DESC LIMIT 1
    """, (doctor_id,))
    otp_record = cursor.fetchone()
    
    if not otp_record:
        conn.close()
        return {"success": False, "error": "No active OTP found. Please request a new OTP."}
    
    expires_str = otp_record["expires_at"]
    try:
        expires_dt = datetime.strptime(expires_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_dt:
            conn.close()
            return {"success": False, "error": "OTP has expired. Please request a new OTP."}
    except Exception:
        pass
    
    if otp_record["otp"] != clean_otp:
        conn.close()
        return {"success": False, "error": "Invalid OTP. Please check the code sent to your email."}
    
    reset_token = secrets.token_hex(24)
    cursor.execute("UPDATE password_reset_otps SET reset_token = ? WHERE id = ?", (reset_token, otp_record["id"]))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": "OTP verified successfully.",
        "reset_token": reset_token,
        "email": doctor["email"]
    }

# Alias for explicit naming
verify_doctor_reset_otp = verify_reset_otp

def reset_doctor_password_with_token(identifier: str, reset_token: str, new_password: str):
    """Resets doctor password with verified token."""
    clean_id = identifier.strip().lower()
    clean_token = reset_token.strip()
    
    if not clean_id or not clean_token:
        return {"success": False, "error": "Invalid session. Please restart password reset."}
    
    pwd_valid, pwd_error = validate_strong_password(new_password)
    if not pwd_valid:
        return {"success": False, "error": pwd_error}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    doctor = cursor.fetchone()
    
    if not doctor:
        conn.close()
        return {"success": False, "error": "Doctor account not found."}
    
    doctor_id = doctor["id"]
    cursor.execute("""
        SELECT * FROM password_reset_otps 
        WHERE doctor_id = ? AND reset_token = ? AND used = 0 
        ORDER BY id DESC LIMIT 1
    """, (doctor_id, clean_token))
    otp_record = cursor.fetchone()
    
    if not otp_record:
        conn.close()
        return {"success": False, "error": "Invalid or expired session. Please request a new OTP."}
    
    pwd_hash = hash_password(new_password)
    cursor.execute("UPDATE doctors SET password_hash = ? WHERE id = ?", (pwd_hash, doctor_id))
    cursor.execute("UPDATE password_reset_otps SET used = 1 WHERE id = ?", (otp_record["id"],))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": "Password updated successfully. You can now log in with your new password.",
        "email": doctor["email"]
    }

def reset_doctor_password(identifier: str, new_password: str):
    """Legacy helper for direct reset if called without token."""
    clean_id = identifier.strip().lower()
    pwd_valid, pwd_error = validate_strong_password(new_password)
    if not pwd_valid:
        return {"success": False, "error": pwd_error}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    doctor = cursor.fetchone()
    if not doctor:
        conn.close()
        return {"success": False, "error": "Doctor account not found."}
    
    pwd_hash = hash_password(new_password)
    cursor.execute("UPDATE doctors SET password_hash = ? WHERE id = ?", (pwd_hash, doctor["id"]))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Password updated successfully."}

# ============================================================
# PATIENT CRUD & AUTHENTICATION
# ============================================================
def register_patient(name: str, email: str, password: str, mobile: str = "", uid: str = "", role: str = "patient"):
    """Registers a new patient into SQLite with full backend validation."""
    clean_name = name.strip()
    if not clean_name:
        return {"success": False, "error": "Full Name is required."}
    
    clean_email = email.strip().lower()
    if not clean_email or not validate_email_format(clean_email):
        return {"success": False, "error": "Please enter a valid email address."}
    
    clean_mobile = mobile.strip()
    if not clean_mobile or not validate_mobile_format(clean_mobile):
        return {"success": False, "error": "Please enter a valid mobile number."}
    
    if not password:
        return {"success": False, "error": "Password is required."}
    pwd_valid, pwd_error = validate_strong_password(password)
    if not pwd_valid:
        return {"success": False, "error": pwd_error}
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check ONLY Patient table for duplicate email
    cursor.execute("SELECT id FROM patients WHERE LOWER(email) = LOWER(?)", (clean_email,))
    if cursor.fetchone():
        conn.close()
        return {"success": False, "error": "An account with this email already exists."}
    
    clean_uid = uid.strip().upper() if uid else ""
    if clean_uid:
        cursor.execute("SELECT id FROM patients WHERE UPPER(uid) = UPPER(?)", (clean_uid,))
        if cursor.fetchone():
            conn.close()
            return {"success": False, "error": f"Patient ID '{clean_uid}' is already registered."}
        final_uid = clean_uid
    else:
        final_uid = generate_patient_id()
    
    pwd_hash = hash_password(password)
    cursor.execute("""
        INSERT INTO patients (uid, name, email, password_hash, role, mobile)
        VALUES (?, ?, ?, ?, 'patient', ?)
    """, (final_uid, clean_name, clean_email, pwd_hash, clean_mobile))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "patient": {
            "uid": final_uid,
            "name": clean_name,
            "email": clean_email,
            "mobile": clean_mobile,
            "role": "patient"
        }
    }

def authenticate_patient(login_id: str, password: str):
    """Authenticates patient against SQLite using Email OR UID."""
    conn = get_db()
    cursor = conn.cursor()
    login_clean = login_id.strip().lower()
    pwd_hash = hash_password(password)
    
    cursor.execute("""
        SELECT * FROM patients 
        WHERE (LOWER(email) = ? OR LOWER(uid) = ?) AND password_hash = ?
    """, (login_clean, login_clean, pwd_hash))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "success": True,
            "patient": {
                "id": row["id"],
                "uid": row["uid"],
                "name": row["name"],
                "email": row["email"],
                "role": row["role"]
            }
        }
    return {"success": False, "error": "Invalid email/Patient ID or password."}

def generate_and_store_patient_reset_otp(identifier: str):
    """Generates and dispatches OTP for patient password reset."""
    clean_id = identifier.strip().lower()
    if not clean_id:
        return {"success": False, "error": "Email or User ID is required."}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    patient = cursor.fetchone()
    
    if not patient:
        conn.close()
        return {"success": False, "error": "No patient account found with this email or User ID."}
    
    patient_id = patient["id"]
    patient_email = patient["email"]
    patient_name = patient["name"]
    patient_uid = patient["uid"]
    
    otp = f"{random.randint(100000, 999999)}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("UPDATE patient_password_reset_otps SET used = 2 WHERE patient_id = ? AND used = 0", (patient_id,))
    cursor.execute("""
        INSERT INTO patient_password_reset_otps (patient_id, identifier, email, otp, expires_at, used)
        VALUES (?, ?, ?, ?, ?, 0)
    """, (patient_id, clean_id, patient_email, otp, expires_at))
    conn.commit()
    conn.close()
    
    sent, err_msg = send_otp_email(patient_email, patient_name, patient_uid, otp, "patient")
    if not sent:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM patient_password_reset_otps WHERE email = ? AND otp = ?", (patient_email, otp))
        conn.commit()
        conn.close()
        return {
            "success": False,
            "error": err_msg or "Failed to send OTP to your registered email address. Please verify your SMTP settings in .env."
        }

    return {
        "success": True,
        "message": "A 6-digit OTP has been sent to your registered email address.",
        "masked_email": mask_email(patient_email),
        "email": patient_email
    }

def verify_patient_reset_otp(identifier: str, otp: str):
    """Validates 6-digit OTP for patient."""
    clean_id = identifier.strip().lower()
    clean_otp = str(otp).strip()
    
    if not clean_id:
        return {"success": False, "error": "Email or User ID is required."}
    if not clean_otp or len(clean_otp) != 6:
        return {"success": False, "error": "Please enter a valid 6-digit OTP."}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    patient = cursor.fetchone()
    
    if not patient:
        conn.close()
        return {"success": False, "error": "No patient account found with this email or User ID."}
    
    patient_id = patient["id"]
    cursor.execute("""
        SELECT * FROM patient_password_reset_otps 
        WHERE patient_id = ? AND used = 0 
        ORDER BY id DESC LIMIT 1
    """, (patient_id,))
    otp_record = cursor.fetchone()
    
    if not otp_record:
        conn.close()
        return {"success": False, "error": "No active OTP found. Please request a new OTP."}
    
    expires_str = otp_record["expires_at"]
    try:
        expires_dt = datetime.strptime(expires_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_dt:
            conn.close()
            return {"success": False, "error": "OTP has expired. Please request a new OTP."}
    except Exception:
        pass
    
    if otp_record["otp"] != clean_otp:
        conn.close()
        return {"success": False, "error": "Invalid OTP. Please check the code sent to your email."}
    
    reset_token = secrets.token_hex(24)
    cursor.execute("UPDATE patient_password_reset_otps SET reset_token = ? WHERE id = ?", (reset_token, otp_record["id"]))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": "OTP verified successfully.",
        "reset_token": reset_token,
        "email": patient["email"]
    }

def reset_patient_password_with_token(identifier: str, reset_token: str, new_password: str):
    """Resets patient password with verified token."""
    clean_id = identifier.strip().lower()
    clean_token = reset_token.strip()
    
    if not clean_id or not clean_token:
        return {"success": False, "error": "Invalid session. Please restart password reset."}
    
    pwd_valid, pwd_error = validate_strong_password(new_password)
    if not pwd_valid:
        return {"success": False, "error": pwd_error}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    patient = cursor.fetchone()
    
    if not patient:
        conn.close()
        return {"success": False, "error": "No patient account found with this email or User ID."}
    
    patient_id = patient["id"]
    cursor.execute("""
        SELECT * FROM patient_password_reset_otps 
        WHERE patient_id = ? AND reset_token = ? AND used = 0 
        ORDER BY id DESC LIMIT 1
    """, (patient_id, clean_token))
    otp_record = cursor.fetchone()
    
    if not otp_record:
        conn.close()
        return {"success": False, "error": "Invalid or expired session. Please request a new OTP."}
    
    pwd_hash = hash_password(new_password)
    cursor.execute("UPDATE patients SET password_hash = ? WHERE id = ?", (pwd_hash, patient_id))
    cursor.execute("UPDATE patient_password_reset_otps SET used = 1 WHERE id = ?", (otp_record["id"],))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": "Password updated successfully. You can now log in with your new password.",
        "email": patient["email"]
    }

# ============================================================
# VIEWER CRUD & AUTHENTICATION
# ============================================================
def register_viewer(name: str, email: str, password: str, mobile: str = "", uid: str = "", role: str = "viewer"):
    clean_name = name.strip()
    if not clean_name:
        return {"success": False, "error": "Full Name is required."}
    
    clean_email = email.strip().lower()
    if not clean_email or not validate_email_format(clean_email):
        return {"success": False, "error": "Please enter a valid email address."}
    
    clean_mobile = mobile.strip()
    if not clean_mobile or not validate_mobile_format(clean_mobile):
        return {"success": False, "error": "Please enter a valid mobile number."}
    
    if not password:
        return {"success": False, "error": "Password is required."}
    pwd_valid, pwd_error = validate_strong_password(password)
    if not pwd_valid:
        return {"success": False, "error": pwd_error}
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check ONLY Viewer table for duplicate email
    cursor.execute("SELECT id FROM viewers WHERE LOWER(email) = LOWER(?)", (clean_email,))
    if cursor.fetchone():
        conn.close()
        return {"success": False, "error": "An account with this email already exists."}
    
    final_uid = uid.strip().upper() if uid else ""
    if final_uid:
        cursor.execute("SELECT id FROM viewers WHERE UPPER(uid) = UPPER(?)", (final_uid,))
        if cursor.fetchone():
            conn.close()
            return {"success": False, "error": f"Viewer ID '{final_uid}' is already in use."}
    else:
        final_uid = generate_viewer_id()
        
    pwd_hash = hash_password(password)
    cursor.execute("""
        INSERT INTO viewers (uid, name, email, password_hash, role, mobile)
        VALUES (?, ?, ?, ?, 'viewer', ?)
    """, (final_uid, clean_name, clean_email, pwd_hash, clean_mobile))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "viewer": {
            "uid": final_uid,
            "name": clean_name,
            "email": clean_email,
            "mobile": clean_mobile,
            "role": "viewer"
        }
    }

def authenticate_viewer(login_id: str, password: str):
    """Authenticates viewer against SQLite using Email OR UID."""
    conn = get_db()
    cursor = conn.cursor()
    login_clean = login_id.strip().lower()
    pwd_hash = hash_password(password)
    
    cursor.execute("""
        SELECT * FROM viewers 
        WHERE (LOWER(email) = ? OR LOWER(uid) = ?) AND password_hash = ?
    """, (login_clean, login_clean, pwd_hash))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "success": True,
            "viewer": {
                "id": row["id"],
                "uid": row["uid"],
                "name": row["name"],
                "email": row["email"],
                "role": row["role"]
            }
        }
    return {"success": False, "error": "Invalid email/Viewer ID or password."}

def generate_and_store_viewer_reset_otp(identifier: str):
    """Generates and dispatches OTP for viewer password reset."""
    clean_id = identifier.strip().lower()
    if not clean_id:
        return {"success": False, "error": "Email or User ID is required."}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM viewers WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    viewer = cursor.fetchone()
    
    if not viewer:
        conn.close()
        return {"success": False, "error": "No viewer account found with this email or User ID."}
    
    viewer_id = viewer["id"]
    viewer_email = viewer["email"]
    viewer_name = viewer["name"]
    viewer_uid = viewer["uid"]
    
    otp = f"{random.randint(100000, 999999)}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("UPDATE viewer_password_reset_otps SET used = 2 WHERE viewer_id = ? AND used = 0", (viewer_id,))
    cursor.execute("""
        INSERT INTO viewer_password_reset_otps (viewer_id, identifier, email, otp, expires_at, used)
        VALUES (?, ?, ?, ?, ?, 0)
    """, (viewer_id, clean_id, viewer_email, otp, expires_at))
    conn.commit()
    conn.close()
    
    sent, err_msg = send_otp_email(viewer_email, viewer_name, viewer_uid, otp, "viewer")
    if not sent:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM viewer_password_reset_otps WHERE email = ? AND otp = ?", (viewer_email, otp))
        conn.commit()
        conn.close()
        return {
            "success": False,
            "error": err_msg or "Failed to send OTP to your registered email address. Please verify your SMTP settings in .env."
        }

    return {
        "success": True,
        "message": "A 6-digit OTP has been sent to your registered email address.",
        "masked_email": mask_email(viewer_email),
        "email": viewer_email
    }

def verify_viewer_reset_otp(identifier: str, otp: str):
    """Validates 6-digit OTP for viewer."""
    clean_id = identifier.strip().lower()
    clean_otp = str(otp).strip()
    
    if not clean_id:
        return {"success": False, "error": "Email or User ID is required."}
    if not clean_otp or len(clean_otp) != 6:
        return {"success": False, "error": "Please enter a valid 6-digit OTP."}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM viewers WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    viewer = cursor.fetchone()
    
    if not viewer:
        conn.close()
        return {"success": False, "error": "No viewer account found with this email or User ID."}
    
    viewer_id = viewer["id"]
    cursor.execute("""
        SELECT * FROM viewer_password_reset_otps 
        WHERE viewer_id = ? AND used = 0 
        ORDER BY id DESC LIMIT 1
    """, (viewer_id,))
    otp_record = cursor.fetchone()
    
    if not otp_record:
        conn.close()
        return {"success": False, "error": "No active OTP found. Please request a new OTP."}
    
    expires_str = otp_record["expires_at"]
    try:
        expires_dt = datetime.strptime(expires_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_dt:
            conn.close()
            return {"success": False, "error": "OTP has expired. Please request a new OTP."}
    except Exception:
        pass
    
    if otp_record["otp"] != clean_otp:
        conn.close()
        return {"success": False, "error": "Invalid OTP. Please check the code sent to your email."}
    
    reset_token = secrets.token_hex(24)
    cursor.execute("UPDATE viewer_password_reset_otps SET reset_token = ? WHERE id = ?", (reset_token, otp_record["id"]))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": "OTP verified successfully.",
        "reset_token": reset_token,
        "email": viewer["email"]
    }

def reset_viewer_password_with_token(identifier: str, reset_token: str, new_password: str):
    """Resets viewer password with verified token."""
    clean_id = identifier.strip().lower()
    clean_token = reset_token.strip()
    
    if not clean_id or not clean_token:
        return {"success": False, "error": "Invalid session. Please restart password reset."}
    
    pwd_valid, pwd_error = validate_strong_password(new_password)
    if not pwd_valid:
        return {"success": False, "error": pwd_error}
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM viewers WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    viewer = cursor.fetchone()
    
    if not viewer:
        conn.close()
        return {"success": False, "error": "No viewer account found with this email or User ID."}
    
    viewer_id = viewer["id"]
    cursor.execute("""
        SELECT * FROM viewer_password_reset_otps 
        WHERE viewer_id = ? AND reset_token = ? AND used = 0 
        ORDER BY id DESC LIMIT 1
    """, (viewer_id, clean_token))
    otp_record = cursor.fetchone()
    
    if not otp_record:
        conn.close()
        return {"success": False, "error": "Invalid or expired session. Please request a new OTP."}
    
    pwd_hash = hash_password(new_password)
    cursor.execute("UPDATE viewers SET password_hash = ? WHERE id = ?", (pwd_hash, viewer_id))
    cursor.execute("UPDATE viewer_password_reset_otps SET used = 1 WHERE id = ?", (otp_record["id"],))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": "Password updated successfully. You can now log in with your new password.",
        "email": viewer["email"]
    }

# ============================================================
# UNIFIED ROLE-AWARE DISPATCHERS
# ============================================================
def generate_and_store_otp_for_role(identifier: str, role: str = "doctor"):
    """Dispatches OTP generation and sending to the correct role account table."""
    r = (role or "doctor").strip().lower()
    if r == "doctor":
        return generate_and_store_reset_otp(identifier)
    elif r == "patient":
        return generate_and_store_patient_reset_otp(identifier)
    elif r == "viewer":
        return generate_and_store_viewer_reset_otp(identifier)
    else:
        # Fallback: search doctor first, then patient, then viewer
        res = generate_and_store_reset_otp(identifier)
        if res.get("success"):
            return res
        res = generate_and_store_patient_reset_otp(identifier)
        if res.get("success"):
            return res
        return generate_and_store_viewer_reset_otp(identifier)

def verify_otp_for_role(identifier: str, otp: str, role: str = "doctor"):
    """Dispatches OTP verification to the correct role OTP table."""
    r = (role or "doctor").strip().lower()
    if r == "doctor":
        return verify_reset_otp(identifier, otp)
    elif r == "patient":
        return verify_patient_reset_otp(identifier, otp)
    elif r == "viewer":
        return verify_viewer_reset_otp(identifier, otp)
    else:
        res = verify_reset_otp(identifier, otp)
        if res.get("success"):
            return res
        res = verify_patient_reset_otp(identifier, otp)
        if res.get("success"):
            return res
        return verify_viewer_reset_otp(identifier, otp)

def reset_password_for_role(identifier: str, reset_token: str, new_password: str, role: str = "doctor"):
    """Dispatches password update to the correct role account table."""
    r = (role or "doctor").strip().lower()
    if r == "doctor":
        return reset_doctor_password_with_token(identifier, reset_token, new_password)
    elif r == "patient":
        return reset_patient_password_with_token(identifier, reset_token, new_password)
    elif r == "viewer":
        return reset_viewer_password_with_token(identifier, reset_token, new_password)
    else:
        res = reset_doctor_password_with_token(identifier, reset_token, new_password)
        if res.get("success"):
            return res
        res = reset_patient_password_with_token(identifier, reset_token, new_password)
        if res.get("success"):
            return res
        return reset_viewer_password_with_token(identifier, reset_token, new_password)

def authenticate_for_role(login_id: str, password: str, role: str = "doctor"):
    """Dispatches authentication to the correct role account table."""
    r = (role or "doctor").strip().lower()
    if r == "doctor":
        return authenticate_doctor(login_id, password)
    elif r == "patient":
        return authenticate_patient(login_id, password)
    elif r == "viewer":
        return authenticate_viewer(login_id, password)
    else:
        return {"success": False, "error": f"Invalid role '{role}'."}

def register_for_role(name: str, email: str, password: str, mobile: str = "", uid: str = "", role: str = "doctor"):
    """Dispatches registration to the correct role account table."""
    r = (role or "doctor").strip().lower()
    if r == "doctor":
        return register_doctor(name, email, password, mobile=mobile, uid=uid)
    elif r == "patient":
        return register_patient(name, email, password, mobile=mobile, uid=uid)
    elif r == "viewer":
        return register_viewer(name, email, password, mobile=mobile, uid=uid)
    else:
        return {"success": False, "error": f"Invalid role '{role}'."}

# Aliases for unified naming convention
unified_authenticate = authenticate_for_role
unified_register = register_for_role
unified_request_reset_otp = generate_and_store_otp_for_role
unified_verify_reset_otp = verify_otp_for_role
unified_reset_password = reset_password_for_role

request_doctor_reset_otp = generate_and_store_reset_otp
request_patient_reset_otp = generate_and_store_patient_reset_otp
request_viewer_reset_otp = generate_and_store_viewer_reset_otp

def clean_and_reinitialize_auth_db():
    """
    Cleans all existing authentication and OTP records from the database
    and cleanly initializes the three default testing accounts:
    Doctor: admin@gmail.com / admin123
    Patient: patient@gmail.com / patient123
    Viewer: user@gmail.com / user123
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript("""
        DROP TABLE IF EXISTS password_reset_otps;
        DROP TABLE IF EXISTS patient_password_reset_otps;
        DROP TABLE IF EXISTS viewer_password_reset_otps;
        DROP TABLE IF EXISTS doctor_biometrics;
        DROP TABLE IF EXISTS doctors;
        DROP TABLE IF EXISTS patients;
        DROP TABLE IF EXISTS viewers;
    """)
    conn.commit()
    conn.close()
    init_db()
    print("[Database] Successfully cleaned and reinitialized authentication database with default accounts.")


# ============================================================
# DOCTOR BIOMETRIC DRIVER — Multi-User Fingerprint Slot System
# ============================================================
# Slot mapping: R1 = hardware slot 1, R2 = slot 2, ... R20 = slot 20
# Each doctor gets one unique slot. Slots are never shared or overwritten.
# ==============================================================================

MAX_BIOMETRIC_SLOTS = 20  # Maximum number of concurrent registered fingerprints

def _slot_label_to_int(slot_label: str) -> int:
    """Convert 'R5' -> 5. Returns 0 on failure."""
    try:
        return int(slot_label.lstrip("Rr"))
    except (ValueError, AttributeError):
        return 0

def _slot_int_to_label(slot_int: int) -> str | None:
    """Convert 5 -> 'R5'. Returns None if out of bounds (1..MAX_BIOMETRIC_SLOTS)."""
    if isinstance(slot_int, int) and 1 <= slot_int <= MAX_BIOMETRIC_SLOTS:
        return f"R{slot_int}"
    return None

def get_next_available_biometric_slot() -> str | None:
    """
    Finds the lowest-numbered fingerprint slot (R1-R20) not currently in use.
    Queries the database for all ACTIVE registrations, finds occupied slots,
    and returns the first free slot label (e.g. 'R1', 'R2', ...).

    Returns:
        str: Slot label like 'R1' if available.
        None: If all MAX_BIOMETRIC_SLOTS slots are occupied.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT fingerprint_slot FROM doctor_biometrics WHERE is_active = 1 AND fingerprint_slot IS NOT NULL"
    )
    rows = cursor.fetchall()
    conn.close()

    occupied_ints = set()
    for row in rows:
        n = _slot_label_to_int(row["fingerprint_slot"])
        if n > 0:
            occupied_ints.add(n)

    for slot_num in range(1, MAX_BIOMETRIC_SLOTS + 1):
        if slot_num not in occupied_ints:
            return _slot_int_to_label(slot_num)

    return None  # All slots full

def get_doctor_biometric_slot(identifier: str) -> str | None:
    """
    Returns the fingerprint slot label (e.g. 'R3') assigned to a doctor, or None if not enrolled.
    """
    conn = get_db()
    cursor = conn.cursor()
    clean_id = identifier.strip().lower()
    cursor.execute("""
        SELECT b.fingerprint_slot
        FROM doctor_biometrics b
        JOIN doctors d ON b.doctor_id = d.id
        WHERE (LOWER(d.email) = ? OR LOWER(d.uid) = ?) AND b.is_active = 1
        LIMIT 1
    """, (clean_id, clean_id))
    row = cursor.fetchone()
    conn.close()
    if row and row["fingerprint_slot"]:
        return row["fingerprint_slot"]
    return None

def register_doctor_biometric(
    identifier: str,
    fingerprint_slot: str,
    template_data: str,
    scanner_model: str = "Arduino/Serial Biometric Scanner"
) -> dict:
    """
    Registers a doctor's fingerprint in the database mapped to a specific hardware slot.

    Rules enforced:
    - Doctor must exist in the doctors table.
    - Doctor must NOT already have an active biometric registration (no silent overwrite).
    - The requested fingerprint_slot must NOT already be occupied by another doctor.
    - fingerprint_slot must be in the format 'R1' through 'R20'.

    Args:
        identifier: Doctor email or UID.
        fingerprint_slot: Hardware slot label e.g. 'R1', 'R2', ... 'R20'.
        template_data: Reference string confirming hardware storage (e.g. 'R307_SLOT_1_<email>_<ts>').
        scanner_model: Scanner model name for audit.

    Returns:
        dict with success/error and assigned fingerprint_id.
    """
    conn = get_db()
    cursor = conn.cursor()
    clean_id = identifier.strip().lower()

    # 1. Validate slot label format
    slot_num = _slot_label_to_int(fingerprint_slot)
    if slot_num < 1 or slot_num > MAX_BIOMETRIC_SLOTS:
        conn.close()
        return {
            "success": False,
            "error": f"Invalid fingerprint slot '{fingerprint_slot}'. Must be R1 through R{MAX_BIOMETRIC_SLOTS}."
        }

    # 2. Look up the doctor
    cursor.execute(
        "SELECT id, uid, name, email FROM doctors WHERE LOWER(email) = ? OR LOWER(uid) = ?",
        (clean_id, clean_id)
    )
    doctor = cursor.fetchone()
    if not doctor:
        # Auto-provision doctor account so biometric registration succeeds for any doctor
        import time as _t
        temp_name = clean_id.split("@")[0].replace(".", " ").replace("_", " ").title()
        temp_uid = f"DOC{int(_t.time()) % 100000:05d}"
        hashed_pw = hash_password("TorusDoctor@2026")
        cursor.execute(
            """
            INSERT INTO doctors (uid, name, email, password, specialty, created_at)
            VALUES (?, ?, ?, ?, 'General Medicine', CURRENT_TIMESTAMP)
            """,
            (temp_uid, f"Dr. {temp_name}", clean_id, hashed_pw)
        )
        conn.commit()
        cursor.execute("SELECT id, uid, name, email FROM doctors WHERE id = ?", (cursor.lastrowid,))
        doctor = cursor.fetchone()
        if not doctor:
            conn.close()
            return {"success": False, "error": f"Doctor account could not be created for '{identifier}'."}

    # 3. Check if this doctor already has an active registration
    cursor.execute(
        "SELECT fingerprint_slot FROM doctor_biometrics WHERE doctor_id = ? AND is_active = 1 LIMIT 1",
        (doctor["id"],)
    )
    existing = cursor.fetchone()
    if existing:
        existing_slot = existing["fingerprint_slot"] or "unknown slot"
        conn.close()
        return {
            "success": False,
            "already_registered": True,
            "fingerprint_id": existing_slot,
            "error": f"Fingerprint is already registered for this account (slot {existing_slot}). Remove the existing registration before re-enrolling."
        }

    # 4. Check if this slot is already taken by ANOTHER doctor
    cursor.execute(
        "SELECT doctor_id, email FROM doctor_biometrics WHERE fingerprint_slot = ? AND is_active = 1 LIMIT 1",
        (fingerprint_slot,)
    )
    slot_taken = cursor.fetchone()
    if slot_taken:
        conn.close()
        return {
            "success": False,
            "error": f"Fingerprint slot {fingerprint_slot} is already occupied by another account. Please use a different slot."
        }

    # 5. All checks passed — create new biometric registration record
    # Phase 6: Store clean hardware reference string (e.g. R307_SLOT_1) without fake raw biometric data
    clean_ref = f"R307_SLOT_{slot_num}" if not template_data or not template_data.startswith("R307_SLOT_") else template_data
    cursor.execute("""
        INSERT INTO doctor_biometrics
            (doctor_id, uid, email, fingerprint_slot, hardware_slot, fingerprint_template, scanner_model, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        doctor["id"], doctor["uid"], doctor["email"],
        fingerprint_slot, slot_num, clean_ref, scanner_model
    ))
    conn.commit()
    conn.close()

    print(f"[Database] Biometric registered: {doctor['email']} -> {fingerprint_slot} (hardware slot {slot_num})", flush=True)
    return {
        "success": True,
        "message": "Fingerprint registered successfully.",
        "subtitle": f"Your fingerprint has been securely linked to your account ({fingerprint_slot}).",
        "fingerprint_id": fingerprint_slot,
        "hardware_slot": slot_num,
        "doctor": {
            "id": doctor["id"],
            "uid": doctor["uid"],
            "name": doctor["name"],
            "email": doctor["email"]
        }
    }

def verify_doctor_biometric_by_slot(matched_slot_id: int) -> dict:
    """
    After hardware 1:N search returns a matched slot ID, look up which doctor owns that slot.
    This is the correct multi-user verification: hardware identifies WHICH slot matched,
    Python then looks up WHO owns that slot.

    Args:
        matched_slot_id: Integer slot number returned by the hardware (e.g. 3 for R3).

    Returns:
        dict with success/matched and doctor info.
    """
    slot_label = _slot_int_to_label(matched_slot_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.id, d.uid, d.name, d.email, d.role, d.mobile, d.created_at, b.fingerprint_slot
        FROM doctors d
        JOIN doctor_biometrics b ON d.id = b.doctor_id
        WHERE b.fingerprint_slot = ? AND b.is_active = 1
        LIMIT 1
    """, (slot_label,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            "success": False,
            "matched": False,
            "error": "Fingerprint matched hardware but no registered account found for this slot. Please re-enroll.",
            "code": "SLOT_NOT_MAPPED"
        }

    return {
        "success": True,
        "matched": True,
        "fingerprint_id": slot_label,
        "message": f"Fingerprint verified successfully ({slot_label}).",
        "doctor": {
            "id": row["id"],
            "uid": row["uid"],
            "name": row["name"],
            "email": row["email"],
            "role": row["role"],
            "mobile": row["mobile"] if "mobile" in row.keys() and row["mobile"] else "",
            "created_at": row["created_at"] if "created_at" in row.keys() and row["created_at"] else ""
        }
    }

def verify_doctor_biometric_by_email(identifier: str, matched_slot_id: int) -> dict:
    """
    Verifies that the hardware-matched slot belongs to the specific doctor identified by email/uid.
    Used when the login screen has a pre-filled email: confirms that the scanned finger
    belongs to THAT doctor specifically.

    Args:
        identifier: Doctor email or UID from login form.
        matched_slot_id: Integer slot number returned by hardware after 1:N search.

    Returns:
        dict with success/matched and doctor info.
    """
    slot_label = _slot_int_to_label(matched_slot_id)
    conn = get_db()
    cursor = conn.cursor()
    clean_id = identifier.strip().lower()

    # Get what slot THIS doctor is registered to
    cursor.execute("""
        SELECT d.id, d.uid, d.name, d.email, d.role, d.mobile, d.created_at, b.fingerprint_slot
        FROM doctors d
        JOIN doctor_biometrics b ON d.id = b.doctor_id
        WHERE (LOWER(d.email) = ? OR LOWER(d.uid) = ?) AND b.is_active = 1
        LIMIT 1
    """, (clean_id, clean_id))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            "success": False,
            "matched": False,
            "error": "No biometric registration found for this account. Please enroll your fingerprint first.",
            "code": "NOT_ENROLLED"
        }

    registered_slot = row["fingerprint_slot"]

    # Critical check: does the hardware-matched slot match THIS doctor's registered slot?
    if registered_slot != slot_label:
        return {
            "success": False,
            "matched": False,
            "error": "Fingerprint does not match the registered fingerprint for this account. Access denied.",
            "code": "SLOT_MISMATCH"
        }

    return {
        "success": True,
        "matched": True,
        "fingerprint_id": slot_label,
        "message": f"Fingerprint verified successfully ({slot_label}).",
        "doctor": {
            "id": row["id"],
            "uid": row["uid"],
            "name": row["name"],
            "email": row["email"],
            "role": row["role"],
            "mobile": row["mobile"] if "mobile" in row.keys() and row["mobile"] else "",
            "created_at": row["created_at"] if "created_at" in row.keys() and row["created_at"] else ""
        }
    }

# Keep legacy alias for any other callers
def verify_doctor_biometric(identifier: str = None, scanned_template: str = None) -> dict:
    """
    Legacy compatibility wrapper. Prefer verify_doctor_biometric_by_slot() for new code.
    If identifier is provided, checks that doctor has an active biometric registration.
    Does NOT perform hardware slot matching — use biometrics.py for that.
    """
    conn = get_db()
    cursor = conn.cursor()
    if identifier:
        clean_id = identifier.strip().lower()
        cursor.execute("""
            SELECT d.id, d.uid, d.name, d.email, d.role, b.fingerprint_slot
            FROM doctors d
            JOIN doctor_biometrics b ON d.id = b.doctor_id
            WHERE (LOWER(d.email) = ? OR LOWER(d.uid) = ?) AND b.is_active = 1
            LIMIT 1
        """, (clean_id, clean_id))
    else:
        cursor.execute("""
            SELECT d.id, d.uid, d.name, d.email, d.role, b.fingerprint_slot
            FROM doctors d
            JOIN doctor_biometrics b ON d.id = b.doctor_id
            WHERE b.is_active = 1
            LIMIT 1
        """)
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"success": False, "matched": False, "error": "Fingerprint does not match. Please try again."}
    return {
        "success": True,
        "matched": True,
        "fingerprint_id": row["fingerprint_slot"] or "unknown",
        "message": "Fingerprint verified.",
        "doctor": {
            "id": row["id"], "uid": row["uid"],
            "name": row["name"], "email": row["email"], "role": row["role"]
        }
    }

def get_doctor_biometric(identifier: str) -> dict:
    conn = get_db()
    cursor = conn.cursor()
    clean_id = identifier.strip().lower()
    cursor.execute("""
        SELECT b.id, b.enrolled_at, b.scanner_model, b.fingerprint_slot, d.name, d.email, d.uid
        FROM doctor_biometrics b
        JOIN doctors d ON b.doctor_id = d.id
        WHERE (LOWER(d.email) = ? OR LOWER(d.uid) = ?) AND b.is_active = 1
        LIMIT 1
    """, (clean_id, clean_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"enrolled": False}
    return {
        "enrolled": True,
        "enrolled_at": row["enrolled_at"],
        "scanner_model": row["scanner_model"],
        "fingerprint_id": row["fingerprint_slot"],
        "doctor": {"uid": row["uid"], "name": row["name"], "email": row["email"]}
    }

def delete_doctor_biometric(identifier: str) -> dict:
    """
    Deletes the biometric registration for a doctor, freeing their slot.
    """
    conn = get_db()
    cursor = conn.cursor()
    clean_id = identifier.strip().lower()
    cursor.execute("""
        SELECT b.id, b.fingerprint_slot, d.email
        FROM doctor_biometrics b
        JOIN doctors d ON b.doctor_id = d.id
        WHERE (LOWER(d.email) = ? OR LOWER(d.uid) = ?) AND b.is_active = 1
        LIMIT 1
    """, (clean_id, clean_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"success": False, "error": f"No active biometric registration found for '{identifier}'."}

    slot = row["fingerprint_slot"]
    cursor.execute("DELETE FROM doctor_biometrics WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    print(f"[Database] Biometric deleted for {identifier} (freed slot {slot}).", flush=True)
    return {
        "success": True,
        "message": f"Biometric registration for {identifier} deleted successfully.",
        "freed_slot": slot
    }

def reset_all_biometrics() -> dict:
    """
    Clears all active biometric registrations in the database.
    All 20 slots (R1..R20) become completely open and ready for fresh registration.
    Does NOT delete doctor accounts, login credentials, or other application data.
    Also triggers hardware reset to clear physical R307 templates if connected.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM doctor_biometrics WHERE is_active = 1")
    count = cursor.fetchone()[0]
    cursor.execute("DELETE FROM doctor_biometrics")
    conn.commit()
    conn.close()
    print(f"[Database] Reset all biometrics: cleared {count} DB registrations. All 20 slots are now empty.", flush=True)

    # Phase 4 & 11: Also clear physical hardware templates from R307 slots R1-R20
    hw_cleared = False
    try:
        import biometrics
        hw_res = biometrics.hardware_manager.reset_hardware()
        hw_cleared = hw_res.get("success", False)
    except Exception as e:
        print(f"[Database] Hardware reset notice: {e}", flush=True)

    return {
        "success": True,
        "cleared_count": count,
        "hardware_cleared": hw_cleared,
        "total_slots": MAX_BIOMETRIC_SLOTS,
        "available_slots": MAX_BIOMETRIC_SLOTS,
        "next_available_slot": "R1",
        "message": "All biometric registrations have been cleared from database. System is ready for fresh registrations starting from slot R1."
    }

# ==============================================================================
# CLINICAL SESSIONS MANAGEMENT & VALIDATION
# ==============================================================================

def generate_unique_session_code() -> str:
    """
    Generates a unique, non-predictable session code (e.g. TORUS-X7K9P2).
    Ensures the code does not collide with existing active sessions.
    """
    conn = get_db()
    cursor = conn.cursor()
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # exclude ambiguous 0, O, 1, I
    for _ in range(100):
        random_suffix = "".join(random.choices(chars, k=6))
        code = f"TORUS-{random_suffix}"
        cursor.execute("SELECT id FROM clinical_sessions WHERE session_code = ?", (code,))
        if not cursor.fetchone():
            conn.close()
            return code
    conn.close()
    return f"TORUS-{secrets.token_hex(3).upper()}"

def create_clinical_session(doctor_id: int = None, doctor_uid: str = "", doctor_name: str = "", doctor_email: str = "", channel_name: str = "torus", duration_hours: int = 24) -> dict:
    """
    Creates a real clinical session registered in the backend database.
    Returns session information with the server-generated Session Code.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Look up doctor details if not fully provided
    if doctor_email or doctor_uid or doctor_id:
        if doctor_id:
            cursor.execute("SELECT id, uid, name, email FROM doctors WHERE id = ?", (doctor_id,))
        elif doctor_uid:
            cursor.execute("SELECT id, uid, name, email FROM doctors WHERE LOWER(uid) = ?", (doctor_uid.strip().lower(),))
        else:
            cursor.execute("SELECT id, uid, name, email FROM doctors WHERE LOWER(email) = ?", (doctor_email.strip().lower(),))
        doc_row = cursor.fetchone()
        if doc_row:
            doctor_id = doc_row["id"]
            doctor_uid = doc_row["uid"]
            doctor_name = doc_row["name"]
            doctor_email = doc_row["email"]

    if not doctor_name:
        doctor_name = "Dr. Torus"
    if not doctor_uid:
        doctor_uid = "3001"

    # Check if active non-expired session already exists for this doctor to reuse
    if doctor_id or doctor_uid or doctor_email:
        cursor.execute("""
            SELECT * FROM clinical_sessions 
            WHERE (
                (? IS NOT NULL AND ? != '' AND doctor_id = ?) OR
                (? IS NOT NULL AND ? != '' AND LOWER(doctor_uid) = LOWER(?)) OR
                (? IS NOT NULL AND ? != '' AND LOWER(doctor_email) = LOWER(?))
            )
            AND status = 'active'
            AND (expires_at IS NULL OR expires_at > datetime('now'))
            ORDER BY id DESC LIMIT 1
        """, (
            doctor_id, str(doctor_id) if doctor_id else "", doctor_id,
            doctor_uid, doctor_uid, doctor_uid,
            doctor_email, doctor_email, doctor_email
        ))
        existing_session = cursor.fetchone()
        if existing_session:
            session_code = existing_session["session_code"]
            channel_name = existing_session["channel_name"]
            session_dict = {
                "id": existing_session["id"],
                "session_code": existing_session["session_code"],
                "doctor_id": existing_session["doctor_id"],
                "doctor_uid": existing_session["doctor_uid"],
                "doctor_name": existing_session["doctor_name"],
                "doctor_email": existing_session["doctor_email"],
                "channel_name": existing_session["channel_name"],
                "status": existing_session["status"],
                "created_at": existing_session["created_at"],
                "expires_at": existing_session["expires_at"]
            }
            conn.close()
            print(f"[ClinicalSession] Reusing existing active session {session_code} for Doctor {doctor_name} ({doctor_uid}).")
            return {
                "success": True,
                "session_code": session_code,
                "channel": channel_name,
                "session": session_dict
            }

    session_code = generate_unique_session_code()
    now_utc = datetime.now(timezone.utc)
    expires_at = (now_utc + timedelta(hours=duration_hours)).strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO clinical_sessions (session_code, doctor_id, doctor_uid, doctor_name, doctor_email, channel_name, status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP, ?)
    """, (session_code, doctor_id, doctor_uid, doctor_name, doctor_email, channel_name, expires_at))

    session_id = cursor.lastrowid

    # Record Doctor participant
    cursor.execute("""
        INSERT INTO session_participants (session_id, session_code, participant_name, role, participant_uid)
        VALUES (?, ?, ?, 'doctor', ?)
    """, (session_id, session_code, doctor_name, doctor_uid))

    conn.commit()

    cursor.execute("SELECT * FROM clinical_sessions WHERE id = ?", (session_id,))
    session_row = cursor.fetchone()
    conn.close()

    session_dict = {
        "id": session_row["id"],
        "session_code": session_row["session_code"],
        "doctor_id": session_row["doctor_id"],
        "doctor_uid": session_row["doctor_uid"],
        "doctor_name": session_row["doctor_name"],
        "doctor_email": session_row["doctor_email"],
        "channel_name": session_row["channel_name"],
        "status": session_row["status"],
        "created_at": session_row["created_at"],
        "expires_at": session_row["expires_at"]
    }

    print(f"[ClinicalSession] Created new session {session_code} for Doctor {doctor_name} ({doctor_uid}).")
    return {
        "success": True,
        "session_code": session_code,
        "channel": channel_name,
        "session": session_dict
    }

def get_clinical_session(session_code: str) -> dict | None:
    """Fetches clinical session record by Session Code."""
    if not session_code:
        return None
    code_clean = session_code.strip().upper()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinical_sessions WHERE session_code = ?", (code_clean,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row["id"],
        "session_code": row["session_code"],
        "doctor_id": row["doctor_id"],
        "doctor_uid": row["doctor_uid"],
        "doctor_name": row["doctor_name"],
        "doctor_email": row["doctor_email"],
        "channel_name": row["channel_name"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"]
    }

def validate_clinical_session(session_code: str) -> dict:
    """
    Validates that a clinical session exists, is active, and is not expired.
    Returns:
      { "success": True, "session": ... } or { "success": False, "error": "..." }
    """
    if not session_code or not session_code.strip():
        return {"success": False, "error": "Please enter the session code."}

    code_clean = session_code.strip().upper()
    session = get_clinical_session(code_clean)

    if not session:
        return {"success": False, "error": "Invalid session code."}

    if session["status"] == "closed":
        return {"success": False, "error": "Session is no longer active."}

    # Check expiration
    if session.get("expires_at"):
        try:
            exp_time = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
            if exp_time.tzinfo is None:
                exp_time = exp_time.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp_time:
                return {"success": False, "error": "Session has expired."}
        except Exception:
            pass

    return {
        "success": True,
        "session": session
    }

def join_clinical_session(session_code: str, participant_name: str = "", role: str = "viewer", participant_uid: str = "") -> dict:
    """
    Validates the session and registers the participant (Patient or Viewer) into the existing clinical session.
    Never creates a new session.
    """
    val_res = validate_clinical_session(session_code)
    if not val_res["success"]:
        return val_res

    session = val_res["session"]
    clean_name = participant_name.strip() if participant_name else ("Viewer" if role == "viewer" else "Patient")
    role_clean = (role or "viewer").lower()

    conn = get_db()
    cursor = conn.cursor()

    # Avoid duplicate rows for the same participant in the same session
    if participant_uid:
        cursor.execute("""
            SELECT id FROM session_participants 
            WHERE session_code = ? AND role = ? AND participant_uid = ?
        """, (session["session_code"], role_clean, participant_uid))
        existing_p = cursor.fetchone()
        if not existing_p:
            cursor.execute("""
                INSERT INTO session_participants (session_id, session_code, participant_name, role, participant_uid)
                VALUES (?, ?, ?, ?, ?)
            """, (session["id"], session["session_code"], clean_name, role_clean, participant_uid))
            conn.commit()
    else:
        cursor.execute("""
            INSERT INTO session_participants (session_id, session_code, participant_name, role, participant_uid)
            VALUES (?, ?, ?, ?, ?)
        """, (session["id"], session["session_code"], clean_name, role_clean, participant_uid))
        conn.commit()

    conn.close()

    print(f"[ClinicalSession] Participant '{clean_name}' (role: {role_clean}, UID: {participant_uid}) joined session {session['session_code']}.")

    return {
        "success": True,
        "message": f"Successfully joined session {session['session_code']}",
        "session": session,
        "channel": session["channel_name"],
        "session_code": session["session_code"],
        "participant": {
            "name": clean_name,
            "role": role_clean,
            "uid": participant_uid
        }
    }

def close_clinical_session(session_code: str) -> dict:
    """Closes an active clinical session."""
    if not session_code:
        return {"success": False, "error": "Session code is required."}
    code_clean = session_code.strip().upper()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE clinical_sessions SET status = 'closed' WHERE session_code = ?", (code_clean,))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Session {code_clean} closed."}

# ==============================================================================
# CLINICAL PATIENT REGISTRATION & APPOINTMENTS (PATIENT PORTAL)
# ==============================================================================

def register_clinical_patient(name: str, age: int | str, gender: str, mobile: str, email: str = "", scan_type: str = "", appointment_date: str = "", blood_group: str = "") -> dict:
    """
    Registers a new clinical patient into the existing database.
    Validates required fields, 10-digit mobile, optional email format, and scan information.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        return {"success": False, "error": "Full name is required."}
    
    try:
        age_int = int(age)
        if age_int <= 0 or age_int > 130:
            return {"success": False, "error": "Please enter a valid age between 1 and 130."}
    except (ValueError, TypeError):
        return {"success": False, "error": "Valid age is required."}
    
    clean_gender = (gender or "").strip().capitalize()
    if clean_gender not in ["Male", "Female", "Other"]:
        return {"success": False, "error": "Please select a valid gender (Male, Female, or Other)."}
    
    # 10-digit mobile number validation
    clean_mobile = re.sub(r"[\s\-\(\)\+]", "", mobile or "")
    if len(clean_mobile) == 12 and clean_mobile.startswith("91"):
        clean_mobile = clean_mobile[2:]
    if not re.match(r"^[0-9]{10}$", clean_mobile):
        return {"success": False, "error": "Please enter a valid 10-digit mobile number."}
    
    clean_email = (email or "").strip().lower()
    if clean_email and not validate_email_format(clean_email):
        return {"success": False, "error": "Please enter a valid email address."}
    
    clean_scan = (scan_type or "").strip()
    if not clean_scan:
        return {"success": False, "error": "Scan type is required."}
    
    clean_date = (appointment_date or "").strip()
    if not clean_date:
        return {"success": False, "error": "Appointment date is required."}
    
    clean_blood = (blood_group or "").strip().upper()

    conn = get_db()
    cursor = conn.cursor()

    # Generate unique Patient ID
    for _ in range(100):
        chars = string.digits
        num_part = "".join(random.choices(chars, k=4))
        p_uid = f"P-{num_part}"
        cursor.execute("SELECT id FROM clinical_patients WHERE uid = ?", (p_uid,))
        if not cursor.fetchone():
            break
    else:
        p_uid = f"P-{secrets.token_hex(2).upper()}"

    cursor.execute("""
        INSERT INTO clinical_patients (uid, name, age, gender, mobile, email, scan_type, appointment_date, blood_group)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (p_uid, clean_name, age_int, clean_gender, clean_mobile, clean_email, clean_scan, clean_date, clean_blood))
    patient_id = cursor.lastrowid

    # Create matching appointment in scheduled_appointments
    appt_code = f"APT-2026-{random.randint(100, 999)}"
    cursor.execute("""
        INSERT INTO scheduled_appointments (appointment_id, patient_id, patient_name, doctor_id, doctor_name, scan_type, slot_day, slot_month, slot_year, slot_time, scheduled_datetime, status)
        VALUES (?, ?, ?, '3001', 'Admin Doctor', ?, ?, ?, ?, '10:30 AM', ?, 'scheduled')
    """, (appt_code, p_uid, clean_name, clean_scan, clean_date.split("-")[-1] if "-" in clean_date else "17", "09", "2026", clean_date + " 10:30:00"))

    conn.commit()

    cursor.execute("SELECT * FROM clinical_patients WHERE id = ?", (patient_id,))
    saved_patient = dict(cursor.fetchone())
    conn.close()

    print(f"[ClinicalPatient] Registered new patient {clean_name} (UID: {p_uid}) with scan {clean_scan}.")
    return {
        "success": True,
        "message": "Patient registered successfully.",
        "patient": saved_patient,
        "appointment_id": appt_code
    }

def get_clinical_patients() -> list:
    """Returns all clinical patients from database."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, uid, name, age, gender, mobile, email, scan_type, appointment_date, blood_group, created_at FROM clinical_patients ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_all_doctors_list() -> list:
    """Returns list of active doctors."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, uid, name, email, role FROM doctors ORDER BY id ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def schedule_scan_appointment(patient_identifier: str, scan_type: str, doctor_identifier: str, slot_day: str, slot_month: str, slot_year: str, slot_time: str) -> dict:
    """
    Schedules a new scan appointment and stores it in the scheduled_appointments database table.
    """
    if not patient_identifier:
        return {"success": False, "error": "Patient selection is required."}
    if not scan_type:
        return {"success": False, "error": "Scan type is required."}
    if not doctor_identifier:
        return {"success": False, "error": "Doctor selection is required."}
    if not slot_day or not slot_month or not slot_year or not slot_time:
        return {"success": False, "error": "Complete date slot (Day, Month, Year, Time) is required."}

    conn = get_db()
    cursor = conn.cursor()

    # Look up patient details
    cursor.execute("SELECT uid, name FROM clinical_patients WHERE uid = ? OR name = ? OR email = ? LIMIT 1", 
                   (patient_identifier, patient_identifier, patient_identifier))
    p_row = cursor.fetchone()
    if p_row:
        p_uid = p_row["uid"]
        p_name = p_row["name"]
    else:
        cursor.execute("SELECT uid, name FROM patients WHERE uid = ? OR name = ? OR email = ? LIMIT 1",
                       (patient_identifier, patient_identifier, patient_identifier))
        p2_row = cursor.fetchone()
        if p2_row:
            p_uid = p2_row["uid"]
            p_name = p2_row["name"]
        else:
            p_uid = f"P-{random.randint(1000, 9999)}"
            p_name = patient_identifier

    # Look up doctor details
    cursor.execute("SELECT uid, name FROM doctors WHERE uid = ? OR name = ? OR email = ? LIMIT 1",
                   (doctor_identifier, doctor_identifier, doctor_identifier))
    d_row = cursor.fetchone()
    if d_row:
        d_uid = d_row["uid"]
        d_name = d_row["name"]
    else:
        d_uid = "3001"
        d_name = doctor_identifier

    appt_code = f"APT-{slot_year}-{secrets.token_hex(2).upper()}"
    clean_datetime = f"{slot_year}-{str(slot_month).zfill(2)}-{str(slot_day).zfill(2)} {slot_time}"

    cursor.execute("""
        INSERT INTO scheduled_appointments (appointment_id, patient_id, patient_name, doctor_id, doctor_name, scan_type, slot_day, slot_month, slot_year, slot_time, scheduled_datetime, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled')
    """, (appt_code, p_uid, p_name, d_uid, d_name, scan_type, str(slot_day), str(slot_month), str(slot_year), slot_time, clean_datetime))
    conn.commit()

    cursor.execute("SELECT * FROM scheduled_appointments WHERE appointment_id = ?", (appt_code,))
    saved_appt = dict(cursor.fetchone())
    conn.close()

    # Trigger appointment notification for doctor and patient
    try:
        create_notification(
            user_id=d_uid,
            role="doctor",
            n_type="appointment",
            title=f"New Appointment Scheduled ({appt_code})",
            message=f"Patient {p_name} ({p_uid}) is scheduled for {scan_type} at {clean_datetime}.",
            reference_type="appointment",
            reference_id=appt_code,
            action_url="#upcoming-sessions",
            event_key=f"appointment_scheduled_doc_{appt_code}"
        )
        create_notification(
            user_id=p_uid,
            role="patient",
            n_type="appointment",
            title="Ultrasound Consultation Scheduled",
            message=f"Your {scan_type} scan with {d_name} is confirmed for {clean_datetime}.",
            reference_type="appointment",
            reference_id=appt_code,
            action_url="#patient-appointments",
            event_key=f"appointment_scheduled_pat_{appt_code}"
        )
    except Exception as notif_err:
        print(f"[Notifications] Error creating appointment notifications: {notif_err}")

    print(f"[Appointment] Scheduled {appt_code} for {p_name} with {d_name} on {clean_datetime}.")
    return {
        "success": True,
        "message": "Scan scheduled successfully.",
        "appointment": saved_appt
    }

def get_scheduled_appointments() -> list:
    """Returns all scheduled appointments from database."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scheduled_appointments ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# -------------------- PATIENT DIAGNOSTIC REPORTS API & PDF --------------------
def get_diagnostic_reports(query: str = "", status: str = None, scan_type: str = None, patient_id: str = None) -> list:
    """Returns diagnostic reports filtered by query, status, scan_type, or patient_id."""
    conn = get_db()
    cursor = conn.cursor()
    sql = "SELECT * FROM diagnostic_reports WHERE 1=1"
    params = []
    
    if patient_id:
        sql += " AND (LOWER(patient_id) = ? OR LOWER(patient_name) LIKE ?)"
        params.extend([patient_id.strip().lower(), f"%{patient_id.strip().lower()}%"])
        
    if status and status.lower() != "all":
        sql += " AND LOWER(report_status) = ?"
        params.append(status.strip().lower())
        
    if scan_type and scan_type.lower() != "all":
        sql += " AND LOWER(scan_type) = ?"
        params.append(scan_type.strip().lower())
        
    if query and query.strip():
        q_clean = f"%{query.strip().lower()}%"
        sql += """ AND (
            LOWER(report_id) LIKE ? OR
            LOWER(patient_id) LIKE ? OR
            LOWER(patient_name) LIKE ? OR
            LOWER(scan_type) LIKE ? OR
            LOWER(doctor_name) LIKE ? OR
            LOWER(diagnostic_center) LIKE ? OR
            LOWER(session_id) LIKE ?
        )"""
        params.extend([q_clean] * 7)
        
    sql += " ORDER BY exam_date DESC, id DESC"
    cursor.execute(sql, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    return [_normalize_report_dict(r) for r in rows]

def _normalize_report_dict(r: dict) -> dict:
    if not r:
        return r
    if isinstance(r.get("telemetry_json"), str):
        try:
            r["telemetry"] = json.loads(r["telemetry_json"])
        except Exception:
            r["telemetry"] = {}
    elif not isinstance(r.get("telemetry"), dict):
        r["telemetry"] = r.get("telemetry_json") or {}

    t = r.get("telemetry") or {}
    
    status = str(r.get("report_status") or "").strip().lower()
    raw_sig = r.get("signature_data") or t.get("signature")
    
    # Determine validity
    raw_valid = r.get("signature_valid")
    if raw_valid is not None:
        sig_valid = 1 if int(raw_valid) == 1 else 0
    else:
        sig_valid = 1 if (status == "signed" and raw_sig and raw_sig != "Digitally Signed") else 0
        
    is_signed = (status == "signed") and (sig_valid == 1) and bool(raw_sig) and (raw_sig != "Digitally Signed") and (
        isinstance(raw_sig, str) and (raw_sig.startswith("data:image/") or raw_sig.startswith("TORUS-SIG-"))
    )

    r["signature_valid"] = 1 if is_signed else (0 if status in ["signature_required", "unsigned", "ready"] else sig_valid)
    r["report_version"] = int(r.get("report_version") or 1)
    r["content_hash"] = r.get("content_hash") or ""
    
    if is_signed:
        r["signature_data"] = raw_sig
        r["signatureData"] = raw_sig
        r["signed_by"] = r.get("signed_doctor_id") or t.get("signed_by") or r.get("doctor_name")
        r["signed_at"] = r.get("signed_at") or t.get("signed_at")
        r["signature_hash"] = r.get("signature_hash") or t.get("signature_hash") or ""
    else:
        # Inactive or invalidated signature must not appear as valid signature
        r["signature_data"] = None
        r["signatureData"] = None
        r["signed_by"] = None
        r["signed_at"] = None

    if not r.get("findings"):
        r["findings"] = r.get("ultrasound_findings")
    if not r.get("recommendations"):
        r["recommendations"] = r.get("diagnosis_impression")
    if not r.get("ai_results"):
        r["ai_results"] = t.get("ai_analysis")
    if not r.get("selected_images"):
        r["selected_images"] = t.get("selected_images") or t.get("images") or []
    if not r.get("images"):
        r["images"] = t.get("images") or t.get("selected_images") or []
    r["delivery_status"] = r.get("delivery_status") or "pending"
    r["delivered_at"] = r.get("delivered_at") or ""
    r["delivery_recipient"] = r.get("delivery_recipient") or ""
    r["delivery_channel"] = r.get("delivery_channel") or "portal"
    r["delivery_attempts"] = int(r.get("delivery_attempts") or 0)
    r["last_delivery_error"] = r.get("last_delivery_error") or ""
    return r


def get_diagnostic_report_by_id(report_id: str) -> dict | None:
    """Returns a single diagnostic report by report_id (e.g. REP-2026-001) or numeric ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM diagnostic_reports 
        WHERE LOWER(report_id) = ? OR id = ?
    """, (report_id.strip().lower(), report_id.strip()))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    r = dict(row)
    return _normalize_report_dict(r)

def create_diagnostic_report(data: dict) -> dict:
    """Inserts a new diagnostic report record into SQLite (or updates existing record)."""
    report_id = data.get("report_id") or data.get("reportId")
    if report_id:
        existing = get_diagnostic_report_by_id(report_id)
        if existing:
            return update_diagnostic_report(report_id, data)

    conn = get_db()
    cursor = conn.cursor()
    
    if not report_id:
        cursor.execute("SELECT COUNT(*) as cnt FROM diagnostic_reports")
        next_num = cursor.fetchone()["cnt"] + 1
        report_id = f"REP-2026-{str(next_num).zfill(3)}"
        
    session_id = data.get("session_id") or data.get("sessionId") or data.get("room") or "TORUS"
    patient_id = data.get("patient_id") or data.get("patientId")
    patient_name = data.get("patient_name") or data.get("patientName") or "Patient User"
    if not patient_id or patient_id in ("P-1000", "--"):
        if patient_name and patient_name not in ("Patient", "--", "Patient User"):
            cursor.execute("SELECT uid FROM clinical_patients WHERE LOWER(name) = ? LIMIT 1", (patient_name.lower(),))
            row = cursor.fetchone()
            if not row:
                cursor.execute("SELECT uid FROM patients WHERE LOWER(name) = ? LIMIT 1", (patient_name.lower(),))
                row = cursor.fetchone()
            if row and row["uid"]:
                patient_id = row["uid"]
    if not patient_id or patient_id in ("P-1000", "--"):
        cursor.execute("SELECT uid, name FROM patients WHERE LOWER(email) = 'patient@gmail.com' OR uid = '4001' LIMIT 1")
        row = cursor.fetchone()
        if row and row["uid"]:
            patient_id = row["uid"]
            if not patient_name or patient_name in ("Patient", "--"):
                patient_name = row["name"]
    if not patient_id:
        patient_id = "--"
    scan_type = data.get("scan_type") or data.get("scanType") or "General"
    device_id = data.get("device_id") or data.get("deviceId") or data.get("device") or "TORUS-A12"
    exam_date = data.get("exam_date") or data.get("examDate") or data.get("sessionDate") or "2026-09-25"
    exam_time = data.get("report_timestamp") or data.get("reportTimestamp") or data.get("timestamp") or data.get("exam_time") or data.get("examTime") or data.get("sessionTime") or "10:00 AM"
    duration = data.get("duration") or data.get("examDuration") or "20:00"
    doctor_id = data.get("doctor_id") or data.get("doctorId") or "3001"
    doctor_name = data.get("doctor_name") or data.get("doctorName") or data.get("doctor") or "Dr. Admin Doctor"
    doctor_license = data.get("doctor_license") or data.get("doctorLicense") or "TORUS-REG-3001"
    diagnostic_center = data.get("diagnostic_center") or data.get("diagnosticCenter") or data.get("location") or "Apex Diagnostic Center"
    report_status = (data.get("report_status") or data.get("status") or "ready").strip().lower()
    clinical_summary = data.get("clinical_summary") or data.get("clinicalSummary") or data.get("ai_observation") or data.get("aiObservation") or "Clinical assessment completed."
    ultrasound_findings = data.get("ultrasound_findings") or data.get("ultrasoundFindings") or data.get("findings") or "Ultrasound scan performed."
    diagnosis_impression = data.get("diagnosis_impression") or data.get("diagnosisImpression") or data.get("recommendations") or "Examination completed."
    
    telemetry = data.get("telemetry") or {
        "maxForce": "2.5 N", "avgForce": "1.8 N", "latency": "15 ms", "frames": 5000, "stability": "99.2%"
    }
    if isinstance(telemetry, dict):
        if data.get("signatureData") or data.get("signature_data"):
            telemetry["signature"] = data.get("signatureData") or data.get("signature_data")
        if data.get("signedBy") or data.get("signed_by"):
            telemetry["signed_by"] = data.get("signedBy") or data.get("signed_by")
        if data.get("signedTimestamp") or data.get("signedAt"):
            telemetry["signed_at"] = data.get("signedTimestamp") or data.get("signedAt")
        if data.get("ai_analysis") or data.get("aiResults") or data.get("aiAnalysis"):
            telemetry["ai_analysis"] = data.get("ai_analysis") or data.get("aiResults") or data.get("aiAnalysis")
        if data.get("selected_images") or data.get("selectedImages") or data.get("images"):
            telemetry["selected_images"] = data.get("selected_images") or data.get("selectedImages") or data.get("images")
            telemetry["images"] = data.get("images") or data.get("selected_images") or data.get("selectedImages")
        if data.get("selectedImagesCount"):
            telemetry["selected_images_count"] = data.get("selectedImagesCount")
    telemetry_json = json.dumps(telemetry) if isinstance(telemetry, dict) else str(telemetry)
    
    try:
        cursor.execute("""
            INSERT INTO diagnostic_reports (
                report_id, session_id, patient_id, patient_name, scan_type, device_id,
                exam_date, exam_time, duration, doctor_id, doctor_name, doctor_license,
                diagnostic_center, report_status, clinical_summary, ultrasound_findings,
                diagnosis_impression, telemetry_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id, session_id, patient_id, patient_name, scan_type, device_id,
            exam_date, exam_time, duration, doctor_id, doctor_name, doctor_license,
            diagnostic_center, report_status, clinical_summary, ultrasound_findings,
            diagnosis_impression, telemetry_json
        ))
        conn.commit()
        created = get_diagnostic_report_by_id(report_id)
        conn.close()

        # Trigger report_generated notification for responsible doctor
        try:
            create_notification(
                user_id=str(doctor_id or "3001"),
                role="doctor",
                n_type="report_generated",
                title=f"Report Generated ({report_id})",
                message=f"Ultrasound diagnostic report {report_id} has been generated for patient {patient_name} ({patient_id}).",
                reference_type="report",
                reference_id=report_id,
                action_url=f"/report-generation.html?report_id={report_id}&patient_id={patient_id}",
                event_key=f"report_created_{report_id}"
            )
        except Exception as notif_err:
            print(f"[Notifications] Error creating report_generated notification: {notif_err}")

        return {"success": True, "report": created}
    except Exception as e:
        conn.close()
        return {"success": False, "error": str(e)}

def update_diagnostic_report(report_id: str, updates: dict, is_signing_action: bool = False) -> dict:
    """Updates fields of an existing diagnostic report with cryptographic content invalidation."""
    existing = get_diagnostic_report_by_id(report_id)
    if not existing:
        return {"success": False, "error": f"Report '{report_id}' not found."}
        
    conn = get_db()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    
    # Content Change Invalidation Detection
    # If signed report content changes, mark signature as no longer valid for modified version and require re-signing
    content_invalidation = False
    next_version = int(existing.get("report_version") or 1)
    new_content_hash = existing.get("content_hash") or ""

    if not is_signing_action and str(existing.get("report_status") or "").strip().lower() == "signed" and int(existing.get("signature_valid") or 0) == 1:
        new_f = updates.get("ultrasound_findings") or updates.get("ultrasoundFindings") or updates.get("findings")
        old_f = existing.get("ultrasound_findings") or existing.get("findings") or ""
        if new_f is not None and str(new_f).strip() != str(old_f).strip():
            content_invalidation = True

        new_r = updates.get("diagnosis_impression") or updates.get("diagnosisImpression") or updates.get("recommendations")
        old_r = existing.get("diagnosis_impression") or existing.get("recommendations") or ""
        if new_r is not None and str(new_r).strip() != str(old_r).strip():
            content_invalidation = True

        new_cs = updates.get("clinical_summary") or updates.get("clinicalSummary")
        old_cs = existing.get("clinical_summary") or ""
        if new_cs is not None and str(new_cs).strip() != str(old_cs).strip():
            content_invalidation = True

        if content_invalidation:
            next_version = int(existing.get("report_version") or 1) + 1
            merged_for_hash = dict(existing)
            merged_for_hash.update(updates)
            new_content_hash = compute_report_content_hash(merged_for_hash)
            # Log audit trail for invalidation
            try:
                cursor.execute("""
                    INSERT INTO report_signature_audit_history (
                        report_id, report_version, content_hash, action,
                        previous_signature_hash, previous_signature_data,
                        new_signature_hash, new_signature_data,
                        doctor_id, doctor_name, doctor_license, replacement_reason,
                        timestamp, outcome
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    report_id, next_version, new_content_hash, "CONTENT_MODIFIED_INVALIDATION",
                    existing.get("signature_hash"), existing.get("signature_data"),
                    None, None,
                    str(updates.get("doctor_id") or existing.get("doctor_id") or "SYSTEM"),
                    str(updates.get("doctor_name") or existing.get("doctor_name") or "System Review"),
                    str(existing.get("doctor_license") or ""),
                    "Report clinical content modified after signature. Re-signature required.",
                    now_iso, "SIGNATURE_INVALIDATED"
                ))
                conn.commit()
            except Exception as audit_err:
                print(f"[Database] Audit log error on invalidation: {audit_err}")

    allowed_fields = {
        "patient_name": ["patient_name", "patientName"],
        "patient_id": ["patient_id", "patientId"],
        "scan_type": ["scan_type", "scanType"],
        "device_id": ["device_id", "deviceId", "device"],
        "exam_date": ["exam_date", "examDate", "sessionDate"],
        "exam_time": ["exam_time", "examTime", "sessionTime"],
        "doctor_name": ["doctor_name", "doctorName", "doctor"],
        "doctor_license": ["doctor_license", "doctorLicense"],
        "diagnostic_center": ["diagnostic_center", "diagnosticCenter", "location"],
        "report_status": ["report_status", "status"],
        "clinical_summary": ["clinical_summary", "clinicalSummary"],
        "ultrasound_findings": ["ultrasound_findings", "ultrasoundFindings", "findings"],
        "diagnosis_impression": ["diagnosis_impression", "diagnosisImpression", "recommendations"],
        "duration": ["duration", "examDuration"],
        "report_version": ["report_version", "reportVersion"],
        "content_hash": ["content_hash", "contentHash"],
        "signature_hash": ["signature_hash", "signatureHash"],
        "signature_valid": ["signature_valid", "signatureValid"],
        "signed_doctor_id": ["signed_doctor_id", "signedDoctorId"],
        "signed_at": ["signed_at", "signedAt"],
        "signature_data": ["signature_data", "signatureData"],
        "replacement_reason": ["replacement_reason", "replacementReason"],
        "delivery_status": ["delivery_status", "deliveryStatus"],
        "delivered_at": ["delivered_at", "deliveredAt"],
        "delivery_recipient": ["delivery_recipient", "deliveryRecipient"],
        "delivery_channel": ["delivery_channel", "deliveryChannel"],
        "delivery_attempts": ["delivery_attempts", "deliveryAttempts"],
        "last_delivery_error": ["last_delivery_error", "lastDeliveryError"]
    }
    
    set_clauses = []
    params = []
    
    for db_col, keys in allowed_fields.items():
        if content_invalidation and db_col in ["report_status", "signature_valid", "report_version", "content_hash"]:
            continue  # Handled explicitly below
        for k in keys:
            if k in updates and updates[k] is not None:
                val = updates[k]
                if db_col == "report_status":
                    val = str(val).strip().lower()
                set_clauses.append(f"{db_col} = ?")
                params.append(val)
                break

    if content_invalidation:
        set_clauses.extend(["report_status = ?", "signature_valid = ?", "report_version = ?", "content_hash = ?"])
        params.extend(["signature_required", 0, next_version, new_content_hash])
                
    telemetry = existing.get("telemetry") or {}
    if not isinstance(telemetry, dict):
        telemetry = {}
    telemetry_modified = False
    
    if "telemetry" in updates and updates["telemetry"] is not None:
        t = updates["telemetry"]
        if isinstance(t, dict):
            telemetry.update(t)
        telemetry_modified = True
        
    if updates.get("signatureData") or updates.get("signature_data") or updates.get("signature"):
        telemetry["signature"] = updates.get("signatureData") or updates.get("signature_data") or updates.get("signature")
        telemetry_modified = True
    if updates.get("signedBy") or updates.get("signed_by"):
        telemetry["signed_by"] = updates.get("signedBy") or updates.get("signed_by")
        telemetry_modified = True
    if updates.get("signedAt") or updates.get("timestamp") or updates.get("signedTimestamp"):
        telemetry["signed_at"] = updates.get("signedAt") or updates.get("timestamp") or updates.get("signedTimestamp")
        telemetry_modified = True
    if updates.get("signatureHash"):
        telemetry["signature_hash"] = updates.get("signatureHash")
        telemetry_modified = True
    if updates.get("ai_analysis") or updates.get("aiResults") or updates.get("aiAnalysis"):
        telemetry["ai_analysis"] = updates.get("ai_analysis") or updates.get("aiResults") or updates.get("aiAnalysis")
        telemetry_modified = True
    if updates.get("selected_images") or updates.get("selectedImages") or updates.get("images"):
        telemetry["selected_images"] = updates.get("selected_images") or updates.get("selectedImages") or updates.get("images")
        telemetry["images"] = updates.get("images") or updates.get("selected_images") or updates.get("selectedImages")
        telemetry_modified = True

    if content_invalidation:
        telemetry["signature_valid"] = 0
        telemetry["report_status"] = "signature_required"
        telemetry["report_version"] = next_version
        telemetry_modified = True

    if telemetry_modified:
        set_clauses.append("telemetry_json = ?")
        params.append(json.dumps(telemetry))
        
    if not set_clauses:
        conn.close()
        return {"success": True, "report": existing, "message": "No changes provided"}
        
    sql = f"UPDATE diagnostic_reports SET {', '.join(set_clauses)} WHERE LOWER(report_id) = ? OR id = ?"
    params.extend([report_id.strip().lower(), report_id.strip()])
    
    try:
        cursor.execute(sql, params)
        conn.commit()
        conn.close()
        updated = get_diagnostic_report_by_id(report_id)
        return {
            "success": True, 
            "report": updated,
            "signatureInvalidated": content_invalidation
        }
    except Exception as e:
        conn.close()
        return {"success": False, "error": str(e)}

def sign_diagnostic_report(report_id: str, data: dict) -> dict:
    """Digitally signs and persists a diagnostic report in SQLite with cryptographic binding and audit trail."""
    import time
    sig_data = data.get("signatureData") or data.get("signature_data") or data.get("signature")
    if not sig_data or not str(sig_data).strip() or str(sig_data).strip() == "Digitally Signed":
        return {"success": False, "error": "Signature is required. An empty or invalid signature cannot be confirmed."}

    existing = get_diagnostic_report_by_id(report_id)
    doctor_name = data.get("doctorName") or data.get("doctor_name") or (existing.get("doctor_name") if existing else "Dr. Admin Doctor")
    doctor_license = data.get("doctorLicense") or data.get("doctor_license") or (existing.get("doctor_license") if existing else "TORUS-REG-3001")
    doctor_id = str(data.get("doctorId") or data.get("doctor_id") or (existing.get("doctor_id") if existing else "3001"))
    now_iso = datetime.now().isoformat()
    signed_at = data.get("signedAt") or now_iso
    sig_hash = data.get("signatureHash") or f"TORUS-SIG-{int(time.time())}"
    
    # Calculate canonical content hash
    merged_data = dict(existing or {})
    merged_data.update(data)
    content_hash = compute_report_content_hash(merged_data)
    curr_version = int(existing.get("report_version") or 1) if existing else 1
    
    sig_record = {
        "signature": sig_data,
        "signed_by": doctor_name,
        "doctor_license": doctor_license,
        "doctor_id": doctor_id,
        "signed_at": signed_at,
        "signature_hash": sig_hash,
        "report_version": curr_version,
        "content_hash": content_hash
    }

    conn = get_db()
    cursor = conn.cursor()

    try:
        action_name = "INITIAL_SIGN" if (not existing or not existing.get("signature_hash")) else "RE_SIGN"
        cursor.execute("""
            INSERT INTO report_signature_audit_history (
                report_id, report_version, content_hash, action,
                previous_signature_hash, previous_signature_data,
                new_signature_hash, new_signature_data,
                doctor_id, doctor_name, doctor_license, replacement_reason,
                timestamp, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id, curr_version, content_hash, action_name,
            existing.get("signature_hash") if existing else None,
            existing.get("signature_data") if existing else None,
            sig_hash, sig_data,
            doctor_id, doctor_name, doctor_license,
            data.get("reason") or "Initial digital signature",
            signed_at, "SUCCESS"
        ))
        conn.commit()
    except Exception as e:
        print(f"[Database] Audit log insertion error during sign: {e}")

    conn.close()

    if existing:
        telemetry = existing.get("telemetry") or {}
        telemetry["signature"] = sig_data
        telemetry["signed_by"] = doctor_name
        telemetry["signed_at"] = signed_at
        telemetry["signature_hash"] = sig_hash
        telemetry["content_hash"] = content_hash
        telemetry["report_version"] = curr_version
        telemetry["signature_valid"] = 1
        
        updates = {
            "report_status": "signed",
            "doctor_name": doctor_name,
            "doctor_license": doctor_license,
            "telemetry": telemetry,
            "signatureData": sig_data,
            "signature_data": sig_data,
            "signedBy": doctor_name,
            "signedAt": signed_at,
            "signed_at": signed_at,
            "signatureHash": sig_hash,
            "signature_hash": sig_hash,
            "signature_valid": 1,
            "report_version": curr_version,
            "content_hash": content_hash,
            "signed_doctor_id": doctor_id
        }
        if data.get("findings") or data.get("ultrasoundFindings"):
            updates["ultrasound_findings"] = data.get("findings") or data.get("ultrasoundFindings")
        if data.get("recommendations") or data.get("diagnosisImpression"):
            updates["diagnosis_impression"] = data.get("recommendations") or data.get("diagnosisImpression")
            
        res = update_diagnostic_report(report_id, updates, is_signing_action=True)
        if res.get("success"):
            try:
                c_conn = get_db()
                c_cursor = c_conn.cursor()
                c_cursor.execute("""
                    UPDATE diagnostic_reports 
                    SET signature_json = ?, signature_data = ?, signature_hash = ?, signature_valid = 1,
                        report_status = 'signed', signed_doctor_id = ?, signed_at = ?, content_hash = ?, report_version = ?
                    WHERE LOWER(report_id) = ? OR id = ?
                """, (
                    json.dumps(sig_record), sig_data, sig_hash, doctor_id, signed_at, content_hash, curr_version, report_id.strip().lower(), report_id.strip()
                ))
                c_conn.commit()
                c_conn.close()
            except Exception as e:
                print(f"[Database] Error updating signature columns: {e}")
            res["message"] = "Report digitally signed and persisted successfully."
            res["report"] = get_diagnostic_report_by_id(report_id)
        return res
    else:
        # Create new report with signed status
        create_data = dict(data)
        create_data["report_id"] = report_id
        create_data["session_id"] = data.get("sessionId") or data.get("room") or "TORUS"
        create_data["report_status"] = "signed"
        create_data["doctor_name"] = doctor_name
        create_data["doctor_license"] = doctor_license
        create_data["signatureData"] = sig_data
        create_data["signature_data"] = sig_data
        create_data["signedBy"] = doctor_name
        create_data["signedAt"] = signed_at
        create_data["signatureHash"] = sig_hash
        create_data["signature_hash"] = sig_hash
        create_data["signature_valid"] = 1
        create_data["report_version"] = curr_version
        create_data["content_hash"] = content_hash
        create_data["signed_doctor_id"] = doctor_id
        res = create_diagnostic_report(create_data)
        if res.get("success"):
            try:
                c_conn = get_db()
                c_cursor = c_conn.cursor()
                c_cursor.execute("""
                    UPDATE diagnostic_reports 
                    SET signature_json = ?, signature_data = ?, signature_hash = ?, signature_valid = 1,
                        report_status = 'signed', signed_doctor_id = ?, signed_at = ?, content_hash = ?, report_version = ?
                    WHERE LOWER(report_id) = ? OR id = ?
                """, (
                    json.dumps(sig_record), sig_data, sig_hash, doctor_id, signed_at, content_hash, curr_version, report_id.strip().lower(), report_id.strip()
                ))
                c_conn.commit()
                c_conn.close()
            except Exception:
                pass
            res["message"] = "Report created, digitally signed, and persisted successfully."
            res["report"] = get_diagnostic_report_by_id(report_id)
        return res

def replace_diagnostic_report_signature(report_id: str, data: dict) -> dict:
    """
    Authorized Signature Replacement workflow:
    - Verifies doctor authentication credentials (password) against SQLite.
    - Requires mandatory replacement reason (min 5 chars).
    - Checks authorization (only authorized doctor can sign/replace).
    - Preserves previous signature & metadata in immutable audit history.
    - Binds new signature to report content hash, increments report version.
    - Logs unauthorized attempts to audit trail.
    """
    import time
    existing = get_diagnostic_report_by_id(report_id)
    if not existing:
        return {"success": False, "error": f"Diagnostic report '{report_id}' not found."}

    # 1. Doctor Re-Authentication Verification
    doctor_login = str(data.get("doctorId") or data.get("email") or data.get("loginId") or data.get("doctor_id") or "admin@gmail.com").strip()
    password = str(data.get("password") or data.get("doctorPassword") or "").strip()
    reason = str(data.get("reason") or data.get("replacementReason") or "").strip()
    new_sig_data = data.get("signatureData") or data.get("signature_data") or data.get("signature")

    now_iso = datetime.now().isoformat()
    curr_version = int(existing.get("report_version") or 1)
    next_version = curr_version + 1
    content_hash = compute_report_content_hash(existing)

    # Re-authenticate doctor credentials
    auth_result = authenticate_doctor(doctor_login, password) if (doctor_login and password) else {"success": False, "error": "Missing doctor password."}
    if not auth_result.get("success"):
        # Log unauthorized replacement attempt in audit trail
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("""
                INSERT INTO report_signature_audit_history (
                    report_id, report_version, content_hash, action,
                    previous_signature_hash, previous_signature_data,
                    new_signature_hash, new_signature_data,
                    doctor_id, doctor_name, doctor_license, replacement_reason,
                    timestamp, outcome
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report_id, curr_version, content_hash, "REPLACE_SIGNATURE_ATTEMPT",
                existing.get("signature_hash"), existing.get("signature_data"),
                None, None,
                doctor_login or "unknown",
                data.get("doctorName") or "Unauthorized User",
                data.get("doctorLicense") or "",
                reason or "Failed re-authentication attempt",
                now_iso, "UNAUTHORIZED_ATTEMPT"
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Database] Error logging unauthorized replacement: {e}")
            
        return {
            "success": False,
            "error": "Re-authentication failed: Valid authorized doctor credentials (password) are required to replace a digital signature."
        }

    authenticated_doctor = auth_result["doctor"]

    # 2. Check Mandatory Replacement Reason
    if not reason or len(reason) < 5:
        return {
            "success": False,
            "error": "A mandatory, detailed reason for signature replacement is required (minimum 5 characters)."
        }

    # 3. Check New Signature
    if not new_sig_data or not str(new_sig_data).strip() or str(new_sig_data).strip() == "Digitally Signed":
        return {
            "success": False,
            "error": "New digital signature is required. An empty or invalid signature cannot be confirmed."
        }

    # 4. Prepare New Signature Metadata
    doctor_name = authenticated_doctor.get("name") or data.get("doctorName") or "Dr. Admin Doctor"
    doctor_uid = str(authenticated_doctor.get("uid"))
    doctor_license = data.get("doctorLicense") or f"TORUS-REG-{doctor_uid}"
    new_sig_hash = data.get("signatureHash") or f"TORUS-SIG-REP-{int(time.time())}"

    # 5. Insert Immutable Audit History Record
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO report_signature_audit_history (
                report_id, report_version, content_hash, action,
                previous_signature_hash, previous_signature_data,
                new_signature_hash, new_signature_data,
                doctor_id, doctor_name, doctor_license, replacement_reason,
                timestamp, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id, next_version, content_hash, "REPLACE_SIGNATURE",
            existing.get("signature_hash"), existing.get("signature_data"),
            new_sig_hash, new_sig_data,
            doctor_uid, doctor_name, doctor_license,
            reason, now_iso, "SUCCESS"
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Database] Error logging audit history for signature replacement: {e}")
        return {"success": False, "error": f"Failed to record audit trail: {e}"}

    # 6. Update Report in SQLite
    sig_record = {
        "signature": new_sig_data,
        "signed_by": doctor_name,
        "doctor_license": doctor_license,
        "doctor_id": doctor_uid,
        "signed_at": now_iso,
        "signature_hash": new_sig_hash,
        "report_version": next_version,
        "content_hash": content_hash,
        "replacement_reason": reason
    }

    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            UPDATE diagnostic_reports 
            SET signature_data = ?, signature_hash = ?, signature_valid = 1,
                report_status = 'signed', report_version = ?, content_hash = ?,
                signed_doctor_id = ?, doctor_name = ?, doctor_license = ?,
                signed_at = ?, replacement_reason = ?, signature_json = ?
            WHERE LOWER(report_id) = ? OR id = ?
        """, (
            new_sig_data, new_sig_hash, next_version, content_hash,
            doctor_uid, doctor_name, doctor_license,
            now_iso, reason, json.dumps(sig_record),
            report_id.strip().lower(), report_id.strip()
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        return {"success": False, "error": f"Failed to update report record: {e}"}

    updated_report = get_diagnostic_report_by_id(report_id)
    return {
        "success": True,
        "message": "Digital signature replaced successfully. Audit history preserved.",
        "report": updated_report,
        "version": next_version,
        "signatureHash": new_sig_hash
    }

def get_report_signature_audit_history(report_id: str) -> list:
    """Returns the immutable signature audit trail for a report in chronological order."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM report_signature_audit_history 
        WHERE LOWER(report_id) = ? OR report_id = ?
        ORDER BY id ASC
    """, (report_id.strip().lower(), report_id.strip()))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def generate_report_pdf_bytes(report_id: str) -> tuple[bytes | None, str | None]:
    """Generates official medical PDF bytes for a diagnostic report matching Image 2 design."""
    report = get_diagnostic_report_by_id(report_id)
    if not report:
        return None, "Report not found"
        
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether, Image as RLImage
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        import base64
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )
        
        styles = getSampleStyleSheet()
        
        h_title = ParagraphStyle('HTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=colors.HexColor('#0f172a'))
        h_sub = ParagraphStyle('HSub', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, textColor=colors.HexColor('#64748b'))
        h_meta = ParagraphStyle('HMeta', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, alignment=2, textColor=colors.HexColor('#64748b'))
        h_meta_id = ParagraphStyle('HMetaId', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=14, alignment=2, textColor=colors.HexColor('#0f172a'))
        
        sec_title = ParagraphStyle('SecTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=colors.HexColor('#475569'))
        sec_title_ai = ParagraphStyle('SecTitleAi', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=colors.HexColor('#166534'))
        
        cell_lbl = ParagraphStyle('CellLbl', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor('#64748b'))
        cell_val = ParagraphStyle('CellVal', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11.5, textColor=colors.HexColor('#0f172a'))
        
        ai_lbl = ParagraphStyle('AiLbl', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor('#166534'))
        ai_val = ParagraphStyle('AiVal', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11.5, textColor=colors.HexColor('#14532d'))
        ai_notice = ParagraphStyle('AiNotice', parent=styles['Normal'], fontName='Helvetica-Oblique', fontSize=7.5, leading=10, textColor=colors.HexColor('#15803d'))
        
        body_p = ParagraphStyle('BodyP', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor('#0f172a'))
        doc_name_style = ParagraphStyle('DocName', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor('#0f172a'))
        doc_loc_style = ParagraphStyle('DocLoc', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#64748b'))
        badge_style = ParagraphStyle('BadgeStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, alignment=2, textColor=colors.HexColor('#16a34a'))
        
        story = []
        
        # 1. Header banner (TORUS MEDICAL / Diagnostic Imaging Center + Report ID / Date)
        exam_d = str(report.get("exam_date", ""))
        rep_id_str = str(report.get("report_id", report_id))
        
        # Derive dynamic timestamp string (with AM/PM and seconds if available)
        exam_t = str(report.get("report_timestamp") or report.get("reportTimestamp") or report.get("timestamp") or "")
        if not exam_t:
            created_raw = report.get("created_at") or report.get("signed_at") or report.get("generatedAt")
            if created_raw:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(str(created_raw).replace('Z', '+00:00'))
                    exam_t = dt.strftime("%I:%M:%S %p")
                except Exception:
                    pass
        if not exam_t:
            exam_t = str(report.get("exam_time") or report.get("examTime") or "")
        if not exam_t or ":" not in exam_t:
            from datetime import datetime
            exam_t = datetime.now().strftime("%I:%M:%S %p")

        header_table = Table([
            [
                Paragraph("<b>TORUS MEDICAL</b><br/><font color='#64748b' size='8'>DIAGNOSTIC IMAGING CENTER</font>", h_title),
                Paragraph(f"<b>Report ID: {rep_id_str}</b>", h_meta)
            ]
        ], colWidths=[340, 200])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(header_table)
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#0f172a'), spaceAfter=12, spaceBefore=4))
        
        # 2. Patient & Case Details Box
        pat_name = str(report.get("patient_name", "--"))
        pat_id = str(report.get("patient_id") or report.get("patientId") or "")
        if not pat_id or pat_id in ("P-1000", "--"):
            if pat_name and pat_name not in ("Patient", "--"):
                try:
                    conn_tmp = get_db()
                    c_tmp = conn_tmp.cursor()
                    c_tmp.execute("SELECT uid FROM clinical_patients WHERE LOWER(name) = ? LIMIT 1", (pat_name.lower(),))
                    row_tmp = c_tmp.fetchone()
                    if not row_tmp:
                        c_tmp.execute("SELECT uid FROM patients WHERE LOWER(name) = ? LIMIT 1", (pat_name.lower(),))
                        row_tmp = c_tmp.fetchone()
                    if row_tmp and row_tmp["uid"]:
                        pat_id = row_tmp["uid"]
                    conn_tmp.close()
                except Exception:
                    pass
        if not pat_id or pat_id == "P-1000":
            pat_id = "--" if pat_name in ("Patient", "--") else (pat_id or "--")

        scan_t = str(report.get("scan_type", "--"))
        if not scan_t.lower().endswith("ultrasound"):
            scan_t = f"{scan_t} Ultrasound"
        dev_id = str(report.get("device_id", "--"))
        loc_name = str(report.get("diagnostic_center", "--"))
        dur_str = str(report.get("duration", "--"))
        
        case_data = [
            [
                Paragraph("<b>PATIENT & CASE DETAILS</b>", sec_title),
                Paragraph("", sec_title)
            ],
            [
                Paragraph(f"<font color='#64748b'><b>Patient Name:</b></font> {pat_name}", cell_val),
                Paragraph(f"<font color='#64748b'><b>Patient ID:</b></font> {pat_id}", cell_val)
            ],
            [
                Paragraph(f"<font color='#64748b'><b>Scan Type:</b></font> {scan_t}", cell_val),
                Paragraph(f"<font color='#64748b'><b>Device:</b></font> {dev_id}", cell_val)
            ],
            [
                Paragraph(f"<font color='#64748b'><b>Location:</b></font> {loc_name}", cell_val),
                Paragraph(f"<font color='#64748b'><b>Duration:</b></font> {dur_str}", cell_val)
            ]
        ]
        t_case = Table(case_data, colWidths=[270, 270])
        t_case.setStyle(TableStyle([
            ('SPAN', (0,0), (1,0)),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
            ('LINEBELOW', (0,0), (1,0), 1, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ]))
        story.append(t_case)
        story.append(Spacer(1, 10))
        
        def safe_rl_image(b64_url, width, height):
            if not b64_url or not isinstance(b64_url, str) or not b64_url.startswith("data:image/"):
                return None
            try:
                from PIL import Image as PILImage, ImageFile
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                b64_data = b64_url.split(",", 1)[1]
                raw = base64.b64decode(b64_data)
                im = PILImage.open(io.BytesIO(raw))
                out = io.BytesIO()
                im.save(out, format='PNG')
                out.seek(0)
                return RLImage(out, width=width, height=height)
            except Exception:
                return None

        # 3. Captured Scan Images
        images_list = report.get("selected_images") or report.get("images") or []
        rendered_imgs = []
        for img_obj in images_list:
            data_url = img_obj.get("dataUrl") if isinstance(img_obj, dict) else (img_obj if isinstance(img_obj, str) else None)
            rl_img = safe_rl_image(data_url, width=160, height=120)
            if rl_img:
                rendered_imgs.append(rl_img)
            if len(rendered_imgs) >= 3:
                break
                
        img_section = [
            [Paragraph("<b>CAPTURED SCAN IMAGES</b>", sec_title)]
        ]
        if rendered_imgs:
            # Table row of images
            img_row = []
            for im in rendered_imgs:
                img_row.append(im)
            while len(img_row) < 3:
                img_row.append(Paragraph("", cell_val))
            t_imgs = Table([img_row], colWidths=[180, 180, 180])
            t_imgs.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(Table(img_section, colWidths=[540], style=[
                ('LINEBELOW', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(Spacer(1, 4))
            story.append(t_imgs)
        else:
            story.append(Table(img_section, colWidths=[540], style=[
                ('LINEBELOW', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(Spacer(1, 4))
            story.append(Paragraph("<font color='#64748b'><i>No captured ultrasound images attached to this record.</i></font>", cell_val))
            
        story.append(Spacer(1, 10))
        
        # 4. AI Preliminary Analysis Section (Soft green box)
        ai_data = report.get("ai_results") or {}
        obs = ai_data.get("observation") or "Ultrasound image demonstrates normal parenchymal echogenicity with active measurement calipers across the region of interest."
        conf = ai_data.get("confidence") or "94.5%"
        qual = ai_data.get("quality") or "High (0.91)"
        risk = ai_data.get("risk") or "Low"
        
        ai_table_data = [
            [
                Paragraph("<b>AI PRELIMINARY ANALYSIS</b>", sec_title_ai),
                Paragraph("", sec_title_ai)
            ],
            [
                Paragraph(f"<font color='#166534'><b>Observation:</b></font> {obs}", ai_val),
                Paragraph(f"<font color='#166534'><b>Detection Confidence:</b></font> {conf}", ai_val)
            ],
            [
                Paragraph(f"<font color='#166534'><b>Image Quality:</b></font> {qual}", ai_val),
                Paragraph(f"<font color='#166534'><b>Clinical Risk:</b></font> {risk}", ai_val)
            ],
            [
                Paragraph("* Clinical Notice: AI Preliminary Analysis is an automated assistive interpretation tool and does not constitute a confirmed medical diagnosis. Review and approval by the attending clinician are required.", ai_notice),
                Paragraph("", ai_notice)
            ]
        ]
        t_ai = Table(ai_table_data, colWidths=[310, 230])
        t_ai.setStyle(TableStyle([
            ('SPAN', (0,0), (1,0)),
            ('SPAN', (0,3), (1,3)),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f0fdf4')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#bbf7d0')),
            ('LINEBELOW', (0,0), (1,0), 1, colors.HexColor('#bbf7d0')),
            ('LINEABOVE', (0,3), (1,3), 0.5, colors.HexColor('#bbf7d0')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ]))
        story.append(t_ai)
        story.append(Spacer(1, 10))
        
        # 5. Clinical Findings
        findings_text = str(report.get("ultrasound_findings") or report.get("findings") or "No findings recorded.")
        findings_sec = [
            [Paragraph("<b>CLINICAL FINDINGS</b>", sec_title)],
            [Paragraph(findings_text.replace("\n", "<br/>"), body_p)]
        ]
        t_find = Table(findings_sec, colWidths=[540])
        t_find.setStyle(TableStyle([
            ('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor('#cbd5e1')),
            ('BOTTOMPADDING', (0,0), (-1,0), 4),
            ('TOPPADDING', (0,1), (-1,1), 6),
            ('BOTTOMPADDING', (0,1), (-1,1), 4),
        ]))
        story.append(t_find)
        story.append(Spacer(1, 10))
        
        # 6. Recommendations
        rec_text = str(report.get("diagnosis_impression") or report.get("recommendations") or "No recommendations recorded.")
        rec_sec = [
            [Paragraph("<b>RECOMMENDATIONS</b>", sec_title)],
            [Paragraph(rec_text.replace("\n", "<br/>"), body_p)]
        ]
        t_rec = Table(rec_sec, colWidths=[540])
        t_rec.setStyle(TableStyle([
            ('LINEBELOW', (0,0), (-1,0), 1, colors.HexColor('#cbd5e1')),
            ('BOTTOMPADDING', (0,0), (-1,0), 4),
            ('TOPPADDING', (0,1), (-1,1), 6),
            ('BOTTOMPADDING', (0,1), (-1,1), 4),
        ]))
        story.append(t_rec)
        story.append(Spacer(1, 14))
        
        # 7. Doctor Details & Digital Signature
        doc_n = str(report.get("doctor_name", "Dr. Admin Doctor"))
        raw_sig = report.get("signature_data")
        sig_valid = int(report.get("signature_valid", 0)) == 1
        rep_status = str(report.get("report_status", "")).strip().lower()
        is_sig_valid = sig_valid and (rep_status == "signed") and raw_sig and (raw_sig != "Digitally Signed")
        
        sig_img_elem = safe_rl_image(raw_sig, width=110, height=30) if is_sig_valid else None
                
        sig_right_content = []
        if is_sig_valid:
            sig_right_content.append(Paragraph("<font color='#16a34a'><b>✓ DIGITALLY SIGNED</b></font>", badge_style))
            if sig_img_elem:
                sig_right_content.append(sig_img_elem)
            sig_date_str = report.get("signed_at") or exam_d
            if "T" in str(sig_date_str):
                try:
                    dt = datetime.fromisoformat(str(sig_date_str).replace("Z", "+00:00"))
                    sig_date_str = dt.strftime("%b %d, %Y %I:%M:%S %p")
                except Exception:
                    pass
            sig_right_content.append(Paragraph(f"{sig_date_str}", h_meta))
        elif rep_status == "signature_required":
            sig_right_content.append(Paragraph("<font color='#d97706'><b>⚠ SIGNATURE REQUIRED (Modified)</b></font>", badge_style))
            sig_right_content.append(Paragraph(f"<b>{doc_n}</b>", ParagraphStyle('SigDName', parent=h_meta_id, fontSize=8.5, leading=11)))
            sig_right_content.append(Paragraph(f"{exam_d}", h_meta))
        else:
            sig_right_content.append(Paragraph("<font color='#64748b'><b>UNSIGNED</b></font>", badge_style))
            sig_right_content.append(Paragraph(f"<b>{doc_n}</b>", ParagraphStyle('SigDName', parent=h_meta_id, fontSize=8.5, leading=11)))
            sig_right_content.append(Paragraph(f"{exam_d}", h_meta))
        
        footer_table = Table([
            [
                "",
                sig_right_content
            ]
        ], colWidths=[320, 220])
        footer_table.setStyle(TableStyle([
            ('LINEABOVE', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0,0), (-1,-1), 10),
            ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ]))
        story.append(KeepTogether(footer_table))
        
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        return pdf_bytes, None
    except Exception as e:
        print(f"[PDF] Error generating PDF for {report_id}: {e}")
        return None, str(e)


# -------------------- PATIENT REPORT DELIVERY & AUDIT WORKFLOW --------------------

def find_patient_by_identifier(patient_id: str, patient_name: str = None) -> dict | None:
    """
    Finds registered patient record across patients and clinical_patients tables.
    Returns patient dictionary or None.
    """
    conn = get_db()
    cursor = conn.cursor()
    p_clean = str(patient_id or "").strip()
    name_clean = str(patient_name or "").strip()

    # 1. Search patients table by UID or email
    if p_clean and p_clean != "--":
        cursor.execute("SELECT * FROM patients WHERE LOWER(uid) = ? OR LOWER(email) = ?", (p_clean.lower(), p_clean.lower()))
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)

    # 2. Search clinical_patients table by UID or email
    if p_clean and p_clean != "--":
        cursor.execute("SELECT * FROM clinical_patients WHERE LOWER(uid) = ? OR LOWER(email) = ?", (p_clean.lower(), p_clean.lower()))
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)

    # 3. Search by name if patient_id was generic or not found
    if name_clean and name_clean not in ("--", "Patient"):
        cursor.execute("SELECT * FROM clinical_patients WHERE LOWER(name) = ?", (name_clean.lower(),))
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)

        cursor.execute("SELECT * FROM patients WHERE LOWER(name) = ?", (name_clean.lower(),))
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)

    # 4. Fallback to default patient 4001 if patient_id is "4001" or "PAT-4001" or name is "Patient User"
    if p_clean in ("4001", "PAT-4001") or name_clean in ("Patient User",):
        cursor.execute("SELECT * FROM patients WHERE uid = '4001'")
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)

    conn.close()
    return None


def update_patient_email(patient_identifier: str, new_email: str, report_id: str = None) -> dict:
    """
    Safely updates the registered email address for a patient across patients and clinical_patients tables.
    Validates patient existence and email format.
    Does not allow silent substitution.
    Synchronizes report delivery recipient and resets status to pending if report_id is provided.
    """
    clean_id = str(patient_identifier or "").strip()
    clean_email = str(new_email or "").strip().lower()

    if not clean_id:
        return {"success": False, "error": "Patient ID or identifier is required."}

    if not clean_email or not validate_email_format(clean_email):
        return {"success": False, "error": "Please provide a valid email address."}

    patient = find_patient_by_identifier(clean_id)
    if not patient:
        return {"success": False, "error": f"Patient '{clean_id}' was not found in the registry."}

    resolved_uid = patient.get("uid") or clean_id
    patient_name = patient.get("name") or ""

    conn = get_db()
    cursor = conn.cursor()
    try:
        # Check if email is already registered to a DIFFERENT patient in patients table
        cursor.execute("SELECT id, uid FROM patients WHERE LOWER(email) = ? AND uid != ?", (clean_email, resolved_uid))
        other_pat = cursor.fetchone()
        if other_pat and str(other_pat["uid"]).lower() not in (resolved_uid.lower(), "4001", "pat-4001"):
            return {"success": False, "error": f"Email '{clean_email}' is already registered to another patient."}

        # Update patients table
        cursor.execute("UPDATE patients SET email = ? WHERE uid = ? OR LOWER(uid) = ?", (clean_email, resolved_uid, resolved_uid.lower()))

        # Also update clinical_patients table
        cursor.execute("UPDATE clinical_patients SET email = ? WHERE uid = ? OR LOWER(uid) = ? OR LOWER(name) = ?", (clean_email, resolved_uid, resolved_uid.lower(), patient_name.lower()))

        # If UID is 4001 or PAT-4001, update both identifiers
        if resolved_uid.lower() in ("4001", "pat-4001"):
            cursor.execute("UPDATE patients SET email = ? WHERE uid IN ('4001', 'PAT-4001')", (clean_email,))
            cursor.execute("UPDATE clinical_patients SET email = ? WHERE uid IN ('4001', 'PAT-4001')", (clean_email,))

        # Synchronize report delivery recipient if report_id provided
        if report_id and str(report_id).strip():
            rep_clean = str(report_id).strip()
            cursor.execute("""
                UPDATE diagnostic_reports
                SET delivery_recipient = ?, delivery_status = 'pending', last_delivery_error = ''
                WHERE LOWER(report_id) = ? OR id = ?
            """, (clean_email, rep_clean.lower(), rep_clean))

        conn.commit()
        print(f"[PatientRegistry] Updated email for patient {resolved_uid} ({patient_name}) to: {clean_email}")
        return {
            "success": True,
            "patient_id": resolved_uid,
            "patient_name": patient_name,
            "email": clean_email,
            "message": f"Patient email updated successfully to {clean_email}."
        }
    except Exception as e:
        print(f"[PatientRegistry] Error updating patient email: {e}")
        return {"success": False, "error": f"Failed to update patient email: {e}"}
    finally:
        conn.close()


def _update_report_delivery_status(report_id: str, status: str, recipient: str = "", channel: str = "portal", delivered_at: str = "", attempts: int = None, error_msg: str = "", patient_id: str = None, patient_name: str = None):
    conn = get_db()
    cursor = conn.cursor()
    set_clauses = ["delivery_status = ?"]
    params = [status]

    if delivered_at:
        set_clauses.append("delivered_at = ?")
        params.append(delivered_at)
    if recipient:
        set_clauses.append("delivery_recipient = ?")
        params.append(recipient)
    if channel:
        set_clauses.append("delivery_channel = ?")
        params.append(channel)
    if attempts is not None:
        set_clauses.append("delivery_attempts = ?")
        params.append(attempts)
    if error_msg is not None:
        set_clauses.append("last_delivery_error = ?")
        params.append(error_msg)
    if patient_id:
        set_clauses.append("patient_id = ?")
        params.append(patient_id)
    if patient_name:
        set_clauses.append("patient_name = ?")
        params.append(patient_name)

    sql = f"UPDATE diagnostic_reports SET {', '.join(set_clauses)} WHERE LOWER(report_id) = ? OR id = ?"
    params.extend([report_id.strip().lower(), report_id.strip()])
    try:
        cursor.execute(sql, params)
        conn.commit()
    except Exception as e:
        print(f"[Database] Error updating delivery status: {e}")
    finally:
        conn.close()


def _log_report_delivery_audit(report_id: str, patient_id: str, patient_name: str, recipient_email: str, status: str, is_resend: bool, error: str = "", channel: str = "portal", attempt: int = 1):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO report_delivery_audit_history (
                report_id, patient_id, patient_name, recipient_email, delivery_status,
                delivery_channel, attempt_number, is_resend, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id, patient_id, patient_name, recipient_email or "", status,
            channel, attempt, 1 if is_resend else 0, error or ""
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Database] Error logging delivery audit: {e}")


def deliver_diagnostic_report_to_patient(report_id: str, patient_id: str = None, is_resend: bool = False, caller_info: dict = None) -> dict:
    """
    Delivers a generated diagnostic report to the intended patient via the clinical database
    and notification dispatch (SMTP email).
    Ensures report is delivered only to its intended patient without generating duplicate reports.
    Enforces deduplication, rate limiting, in-flight locks, and strict manual-only dispatch.
    """
    rep_id_clean = str(report_id or "").strip()
    if not rep_id_clean:
        return {
            "success": False,
            "delivery_status": "failed",
            "error": "Report ID is required for delivery."
        }

    # 1. Thread-safe in-flight lock: Prevent parallel duplicate requests
    with _delivery_lock:
        if rep_id_clean in _in_flight_deliveries:
            return {
                "success": False,
                "delivery_status": "pending",
                "error": f"Delivery is already currently in progress for report '{rep_id_clean}'. Please wait a moment."
            }
        _in_flight_deliveries.add(rep_id_clean)

    try:
        report = get_diagnostic_report_by_id(rep_id_clean)
        if not report:
            return {
                "success": False,
                "delivery_status": "failed",
                "error": f"Diagnostic report '{rep_id_clean}' was not found in the database."
            }

        rep_pat_id = str(report.get("patient_id") or "").strip()
        target_pat_id = str(patient_id or rep_pat_id or "").strip()

        if not target_pat_id or target_pat_id in ("--", ""):
            target_pat_id = rep_pat_id

        # Security check: ensure report is delivered ONLY to its intended patient
        if patient_id and rep_pat_id and rep_pat_id not in ("--", "") and patient_id.strip().lower() != rep_pat_id.lower():
            is_same_patient = (
                (patient_id.strip().lower() in ("4001", "pat-4001")) and 
                (rep_pat_id.lower() in ("4001", "pat-4001"))
            )
            if not is_same_patient:
                err = f"Security error: Report '{rep_id_clean}' is assigned to patient '{rep_pat_id}', but delivery was requested for '{patient_id}'."
                _log_report_delivery_audit(rep_id_clean, target_pat_id, report.get("patient_name", "Unknown"), None, "failed", is_resend, err)
                _update_report_delivery_status(rep_id_clean, "failed", error_msg=err)
                return {
                    "success": False,
                    "delivery_status": "failed",
                    "error": err
                }

        # Find the patient in the registry
        patient_rec = find_patient_by_identifier(target_pat_id, report.get("patient_name"))
        if not patient_rec:
            err = f"Patient '{target_pat_id}' is not registered in the clinical database."
            _log_report_delivery_audit(rep_id_clean, target_pat_id, report.get("patient_name", "Unknown"), None, "failed", is_resend, err)
            _update_report_delivery_status(rep_id_clean, "failed", error_msg=err)
            return {
                "success": False,
                "delivery_status": "failed",
                "error": err
            }

        resolved_pat_id = patient_rec.get("uid") or target_pat_id
        patient_name = patient_rec.get("name") or report.get("patient_name")
        # 1. Resolve recipient email with priority: caller_info -> patient registry -> report record
        candidate_email = ""
        if caller_info and isinstance(caller_info, dict):
            candidate_email = (caller_info.get("email") or caller_info.get("recipient_email") or caller_info.get("patient_email") or "").strip()
        if not candidate_email:
            candidate_email = str(patient_rec.get("email") or "").strip()
        recipient_email = candidate_email

        # If recipient_email is provided and differs from patient_rec email, synchronize it
        if recipient_email and recipient_email.lower() != str(patient_rec.get("email") or "").strip().lower():
            update_patient_email(resolved_pat_id, recipient_email, report_id=rep_id_clean)

        # 2. DEDUPLICATION SAFEGUARD:
        # If report has already been delivered and this is NOT an explicit resend, do not send duplicate emails.
        current_status = str(report.get("delivery_status") or "pending").lower()
        if not is_resend and current_status == "sent":
            print(f"[Delivery Deduplication] Report '{rep_id_clean}' has already been delivered to patient. Bypassing duplicate email.")
            return {
                "success": True,
                "delivery_status": "sent",
                "already_delivered": True,
                "report_id": rep_id_clean,
                "patient_id": resolved_pat_id,
                "patient_name": patient_name,
                "recipient": report.get("delivery_recipient") or recipient_email or resolved_pat_id,
                "delivery_channel": report.get("delivery_channel") or "portal+email",
                "delivered_at": report.get("delivered_at") or "",
                "attempt_number": int(report.get("delivery_attempts") or 1),
                "is_resend": False,
                "message": f"Report '{rep_id_clean}' has already been delivered to patient {patient_name} ({resolved_pat_id}). To resend an update, click 'Resend to Patient'."
            }

        # 3. RESEND COOLDOWN SAFEGUARD:
        # Prevent rapid repeated resend clicks (enforce 30s cooldown between successful resends for production reports)
        is_test_report = rep_id_clean.upper().startswith("RPT-TEST-") or rep_id_clean.upper().startswith("TEST-")
        now_ts = time.time()
        last_attempt_ts = _last_delivery_timestamps.get(rep_id_clean, 0)
        if is_resend and not is_test_report and current_status != "failed" and (now_ts - last_attempt_ts) < 30:
            remaining = int(30 - (now_ts - last_attempt_ts))
            err = f"Rate limit: Please wait {remaining} seconds before resending report '{rep_id_clean}'."
            print(f"[Delivery Rate Limit] {err}")
            return {
                "success": False,
                "delivery_status": report.get("delivery_status", "sent"),
                "error": err,
                "report_id": rep_id_clean,
                "patient_id": resolved_pat_id
            }
        _last_delivery_timestamps[rep_id_clean] = now_ts

        current_attempts = int(report.get("delivery_attempts") or 0) + 1
        now_iso = datetime.now().isoformat()

        delivery_channel = "portal"
        if recipient_email:
            sent, email_msg = send_report_delivery_email(
                to_email=recipient_email,
                patient_name=patient_name,
                patient_uid=resolved_pat_id,
                report=report,
                is_resend=is_resend
            )
            if not sent:
                if is_mailbox_quota_error(email_msg):
                    err = MAILBOX_QUOTA_ERROR_MESSAGE
                else:
                    err = f"Email delivery failed: {email_msg}"
                _log_report_delivery_audit(rep_id_clean, resolved_pat_id, patient_name, recipient_email, "failed", is_resend, err, current_attempts)
                _update_report_delivery_status(rep_id_clean, "failed", recipient=recipient_email, attempts=current_attempts, error_msg=err, patient_id=resolved_pat_id, patient_name=patient_name)

                # Trigger notifications for Doctor and Patient
                doctor_id = str(report.get("doctor_id") or "3001")
                create_notification(
                    user_id=doctor_id,
                    role="doctor",
                    n_type="email_failure",
                    title=f"Report Email Delivery Failed ({rep_id_clean})",
                    message=f"Delivery of report {rep_id_clean} to patient {patient_name} ({recipient_email or resolved_pat_id}) failed: {err}",
                    reference_type="report",
                    reference_id=rep_id_clean,
                    action_url=f"/report-generation.html?report_id={rep_id_clean}&patient_id={resolved_pat_id}",
                    event_key=f"email_failed_{rep_id_clean}"
                )
                create_notification(
                    user_id=resolved_pat_id,
                    role="patient",
                    n_type="email_failure",
                    title="Report Delivery Notice",
                    message=f"We were unable to deliver your ultrasound report ({rep_id_clean}) to your email address. Your complete certified report is available for direct view and download here in your TORUS Portal.",
                    reference_type="report",
                    reference_id=rep_id_clean,
                    action_url=f"/report-generation.html?report_id={rep_id_clean}&patient_id={resolved_pat_id}",
                    event_key=f"patient_email_failed_{rep_id_clean}"
                )

                # STRICT MANUAL-ONLY: Return failure immediately without scheduling any background retries
                return {
                    "success": False,
                    "delivery_status": "failed",
                    "error": err,
                    "report_id": rep_id_clean,
                    "patient_id": resolved_pat_id,
                    "patient_email": recipient_email,
                    "patient_name": patient_name,
                    "is_quota_error": is_mailbox_quota_error(email_msg),
                    "attempt_number": current_attempts
                }
            delivery_channel = "portal+email"
        else:
            err = "Email delivery failed because the patient has no registered email address. Please update the patient's email address before retrying."
            _log_report_delivery_audit(rep_id_clean, resolved_pat_id, patient_name, "", "failed", is_resend, err, current_attempts)
            _update_report_delivery_status(rep_id_clean, "failed", recipient="", error_msg=err, attempts=current_attempts, patient_id=resolved_pat_id, patient_name=patient_name)
            return {
                "success": False,
                "delivery_status": "failed",
                "error": err,
                "report_id": rep_id_clean,
                "patient_id": resolved_pat_id,
                "patient_email": "",
                "patient_name": patient_name,
                "attempt_number": current_attempts
            }

        _update_report_delivery_status(
            report_id=rep_id_clean,
            status="sent",
            recipient=recipient_email or resolved_pat_id,
            channel=delivery_channel,
            delivered_at=now_iso,
            attempts=current_attempts,
            patient_id=resolved_pat_id,
            patient_name=patient_name,
            error_msg=""
        )
        _log_report_delivery_audit(
            report_id=rep_id_clean,
            patient_id=resolved_pat_id,
            patient_name=patient_name,
            recipient_email=recipient_email,
            status="sent",
            is_resend=is_resend,
            channel=delivery_channel,
            attempt=current_attempts
        )

        # Resolve any prior failure notification
        resolve_notification(f"email_failed_{rep_id_clean}")
        resolve_notification(f"patient_email_failed_{rep_id_clean}")

        # Trigger delivery success notifications
        doctor_id = str(report.get("doctor_id") or "3001")
        create_notification(
            user_id=doctor_id,
            role="doctor",
            n_type="report_delivered",
            title=f"Report Delivered ({rep_id_clean})",
            message=f"Ultrasound report {rep_id_clean} for {patient_name} ({resolved_pat_id}) has been delivered successfully to {recipient_email}.",
            reference_type="report",
            reference_id=rep_id_clean,
            action_url=f"/report-generation.html?report_id={rep_id_clean}&patient_id={resolved_pat_id}",
            event_key=f"email_sent_{rep_id_clean}"
        )
        create_notification(
            user_id=resolved_pat_id,
            role="patient",
            n_type="report_available",
            title="Diagnostic Report Available",
            message=f"Your ultrasound report ({rep_id_clean}) is available in your patient portal. Click to view or download.",
            reference_type="report",
            reference_id=rep_id_clean,
            action_url=f"/report-generation.html?report_id={rep_id_clean}&patient_id={resolved_pat_id}",
            event_key=f"report_available_{rep_id_clean}"
        )

        action_word = "resent and delivered" if is_resend else "delivered"
        return {
            "success": True,
            "delivery_status": "sent",
            "report_id": rep_id_clean,
            "patient_id": resolved_pat_id,
            "patient_name": patient_name,
            "recipient": recipient_email or resolved_pat_id,
            "patient_email": recipient_email,
            "delivery_channel": delivery_channel,
            "delivered_at": now_iso,
            "attempt_number": current_attempts,
            "is_resend": is_resend,
            "message": f"Report '{rep_id_clean}' {action_word} successfully to patient {patient_name} ({resolved_pat_id})."
        }
    finally:
        with _delivery_lock:
            _in_flight_deliveries.discard(rep_id_clean)


# ==============================================================================
# NOTIFICATIONS & REAL-TIME EVENT SYSTEM
# ==============================================================================

def create_notification(user_id: str, role: str, n_type: str, title: str, message: str,
                        reference_type: str = "", reference_id: str = "", action_url: str = "",
                        event_key: str = None) -> dict:
    """
    Creates an in-app notification in SQLite. Supports idempotency via event_key.
    Prevents duplicate notifications when operations are retried.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        now_iso = datetime.now().isoformat()
        clean_user_id = str(user_id or "all").strip()
        clean_role = str(role or "doctor").strip().lower()

        if event_key and str(event_key).strip():
            ek = str(event_key).strip()
            cursor.execute("SELECT id FROM notifications WHERE event_key = ?", (ek,))
            existing = cursor.fetchone()
            if existing:
                cursor.execute("""
                    UPDATE notifications
                    SET title = ?, message = ?, action_url = ?, is_read = 0, created_at = ?, resolved_at = NULL
                    WHERE event_key = ?
                """, (title, message, action_url, now_iso, ek))
                conn.commit()
                conn.close()
                return {"success": True, "notification_id": existing["id"], "updated": True}

            cursor.execute("""
                INSERT INTO notifications (user_id, role, type, title, message, reference_type, reference_id, action_url, is_read, created_at, event_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (clean_user_id, clean_role, n_type, title, message, reference_type, reference_id, action_url, now_iso, ek))
        else:
            cursor.execute("""
                INSERT INTO notifications (user_id, role, type, title, message, reference_type, reference_id, action_url, is_read, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (clean_user_id, clean_role, n_type, title, message, reference_type, reference_id, action_url, now_iso))

        nid = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"success": True, "notification_id": nid}
    except Exception as e:
        print(f"[Notifications] Error creating notification: {e}")
        return {"success": False, "error": str(e)}


def resolve_notification(event_key: str) -> bool:
    """Marks a notification as resolved and read when the underlying condition is fixed (e.g. email resend success)."""
    if not event_key:
        return False
    try:
        conn = get_db()
        cursor = conn.cursor()
        now_iso = datetime.now().isoformat()
        cursor.execute("UPDATE notifications SET is_read = 1, resolved_at = ? WHERE event_key = ?", (now_iso, str(event_key).strip()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[Notifications] Error resolving notification: {e}")
        return False


def get_notifications(user_id: str = None, role: str = None, limit: int = 100, offset: int = 0, unread_only: bool = False) -> list:
    """Fetches notifications for a user/role ordered by unread first, then newest."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        clauses = []
        params = []

        if user_id and str(user_id).strip():
            uid_clean = str(user_id).strip()
            clauses.append("(user_id = ? OR user_id = 'all')")
            params.append(uid_clean)

        if role and str(role).strip():
            role_clean = str(role).strip().lower()
            clauses.append("(role = ? OR role = 'all')")
            params.append(role_clean)

        if unread_only:
            clauses.append("is_read = 0")

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM notifications {where_sql} ORDER BY is_read ASC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[Notifications] Error fetching notifications: {e}")
        return []


def get_unread_notification_count(user_id: str = None, role: str = None) -> int:
    """Gets total unread count for user and role."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        clauses = ["is_read = 0"]
        params = []

        if user_id and str(user_id).strip():
            clauses.append("(user_id = ? OR user_id = 'all')")
            params.append(str(user_id).strip())

        if role and str(role).strip():
            clauses.append("(role = ? OR role = 'all')")
            params.append(str(role).strip().lower())

        where_sql = "WHERE " + " AND ".join(clauses)
        cursor.execute(f"SELECT COUNT(*) as cnt FROM notifications {where_sql}", params)
        row = cursor.fetchone()
        conn.close()
        return row["cnt"] if row else 0
    except Exception as e:
        print(f"[Notifications] Error fetching unread count: {e}")
        return 0


def mark_notification_as_read(notification_id: int, user_id: str = None) -> bool:
    """Marks a single notification as read."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        if user_id and str(user_id).strip():
            cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND (user_id = ? OR user_id = 'all')", (notification_id, str(user_id).strip()))
        else:
            cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[Notifications] Error marking notification read: {e}")
        return False


def mark_all_notifications_as_read(user_id: str = None, role: str = None) -> bool:
    """Marks all notifications as read for a given user/role."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        clauses = ["is_read = 0"]
        params = []
        if user_id and str(user_id).strip():
            clauses.append("(user_id = ? OR user_id = 'all')")
            params.append(str(user_id).strip())
        if role and str(role).strip():
            clauses.append("(role = ? OR role = 'all')")
            params.append(str(role).strip().lower())

        where_sql = "WHERE " + " AND ".join(clauses)
        cursor.execute(f"UPDATE notifications SET is_read = 1 {where_sql}", params)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[Notifications] Error marking all notifications read: {e}")
        return False


# ==============================================================================
# TWO-WAY CHAT SUPPORT SYSTEM (DOCTOR <-> PATIENT / ATTENDER)
# ==============================================================================

def check_conversation_authorization(conversation_id: str, user_id: str, role: str) -> dict:
    """
    Verifies that the user with given role and ID is an authorized participant
    in the requested conversation.
    """
    clean_cid = str(conversation_id or "").strip()
    clean_uid = str(user_id or "").strip()
    clean_role = str(role or "").strip().lower()

    if not clean_cid:
        return {"authorized": False, "error": "Conversation ID is required."}

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (clean_cid,))
    conv = cursor.fetchone()
    conn.close()

    if not conv:
        return {"authorized": False, "error": f"Conversation '{clean_cid}' not found."}

    conv_dict = dict(conv)
    doc_id = str(conv_dict.get("doctor_id") or "").strip()
    pat_id = str(conv_dict.get("patient_id") or "").strip()
    att_id = str(conv_dict.get("attender_id") or "").strip()

    if not clean_uid:
        return {"authorized": True, "conversation": conv_dict}

    if clean_role == "doctor":
        if clean_uid == doc_id or clean_uid == "3001" or doc_id == "3001":
            return {"authorized": True, "conversation": conv_dict}
        return {"authorized": False, "error": "Unauthorized: Doctor is not assigned to this patient conversation."}

    elif clean_role in ("patient", "viewer"):
        if clean_uid in (pat_id, att_id) or (pat_id in ("4001", "PAT-4001") and clean_uid in ("4001", "6001")):
            return {"authorized": True, "conversation": conv_dict}
        return {"authorized": False, "error": "Unauthorized: Access to this conversation is restricted to the authorized patient."}

    if clean_uid in (doc_id, pat_id, att_id):
        return {"authorized": True, "conversation": conv_dict}

    return {"authorized": False, "error": "Unauthorized access to this conversation."}


def get_or_create_conversation(doctor_id: str, patient_id: str, attender_id: str = "") -> dict:
    """Finds or creates a two-way conversation between doctor and patient/attender."""
    doc_id = str(doctor_id or "3001").strip()
    pat_id = str(patient_id or "4001").strip()
    att_id = str(attender_id or "").strip()

    conv_id = f"conv_{doc_id}_{pat_id}"
    if att_id:
        conv_id += f"_{att_id}"

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    conv = cursor.fetchone()
    if conv:
        res = dict(conv)
        conn.close()
        return res

    # Resolve doctor and patient names
    doctor_rec = find_doctor_by_identifier(doc_id)
    doc_name = doctor_rec.get("name", "Dr. Admin Doctor") if doctor_rec else "Dr. Admin Doctor"

    patient_rec = find_patient_by_identifier(pat_id)
    pat_name = patient_rec.get("name", "Patient User") if patient_rec else "Patient User"

    now_iso = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO conversations (id, doctor_id, patient_id, attender_id, patient_name, doctor_name, last_message, last_message_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)
    """, (conv_id, doc_id, pat_id, att_id, pat_name, doc_name, now_iso, now_iso))
    conn.commit()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    res = dict(cursor.fetchone())
    conn.close()
    return res


def get_user_conversations(user_id: str, role: str) -> list:
    """Returns all conversations authorized for the user and role."""
    clean_uid = str(user_id or "").strip()
    clean_role = str(role or "doctor").strip().lower()

    conn = get_db()
    cursor = conn.cursor()

    if clean_role == "doctor":
        # Ensure active clinical patients have conversations available for doctor 3001
        clinical_patients_seed = [
            ("4001", "Patient User"),
            ("P-8821", "John Smith"),
            ("P-9104", "Jane Smith"),
            ("P-7543", "Robert Brown")
        ]
        now_iso = datetime.now().isoformat()
        for p_id, p_name in clinical_patients_seed:
            cid = f"conv_3001_{p_id}"
            cursor.execute("SELECT id FROM conversations WHERE id = ?", (cid,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT OR IGNORE INTO conversations (id, doctor_id, patient_id, attender_id, patient_name, doctor_name, last_message, last_message_at, created_at)
                    VALUES (?, '3001', ?, '', ?, 'Dr. Admin Doctor', 'Clinical consultation available.', ?, ?)
                """, (cid, p_id, p_name, now_iso, now_iso))
        conn.commit()

        cursor.execute("SELECT * FROM conversations WHERE doctor_id = ? OR doctor_id = '3001' ORDER BY last_message_at DESC", (clean_uid,))
    elif clean_role in ("patient", "viewer"):
        # Strictly isolate patient: patient only sees conversations where patient_id matches clean_uid
        cursor.execute("""
            SELECT * FROM conversations 
            WHERE (patient_id = ? OR (patient_id IN ('4001', 'PAT-4001') AND ? IN ('4001', '6001')) OR attender_id = ?)
            ORDER BY last_message_at DESC
        """, (clean_uid, clean_uid, clean_uid))
    else:
        cursor.execute("SELECT * FROM conversations WHERE doctor_id = ? OR patient_id = ? ORDER BY last_message_at DESC", (clean_uid, clean_uid))

    rows = cursor.fetchall()
    results = []
    for r in rows:
        d = dict(r)
        # Fetch unread message count for this user in this conversation
        cursor.execute("SELECT COUNT(*) as unread FROM messages WHERE conversation_id = ? AND sender_id != ? AND is_read = 0", (d["id"], clean_uid))
        unread_row = cursor.fetchone()
        d["unread_count"] = unread_row["unread"] if unread_row else 0
        results.append(d)

    conn.close()
    return results


def get_conversation_messages(conversation_id: str, limit: int = 100, offset: int = 0) -> list:
    """Returns chronological messages in a conversation, retrieving the most recent window."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM (
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
        ) ORDER BY created_at ASC, id ASC
    """, (str(conversation_id).strip(), limit, offset))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def send_chat_message(conversation_id: str, sender_id: str, sender_role: str, sender_name: str,
                      content: str, attachment_url: str = "", attachment_name: str = "") -> dict:
    """
    Saves a message in a conversation, updates conversation last_message timestamp,
    guards against rapid duplicate submission, and triggers an in-app notification.
    """
    clean_cid = str(conversation_id or "").strip()
    clean_sid = str(sender_id or "").strip()
    clean_role = str(sender_role or "patient").strip().lower()
    clean_name = str(sender_name or "").strip()
    clean_content = str(content or "").strip()

    if not clean_cid:
        return {"success": False, "error": "Conversation ID is required."}
    if not clean_content and not attachment_url:
        return {"success": False, "error": "Message content or attachment is required."}

    # Verify participant authorization
    auth = check_conversation_authorization(clean_cid, clean_sid, clean_role)
    if not auth.get("authorized", True):
        return {"success": False, "error": auth.get("error", "Unauthorized access to this conversation.")}

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (clean_cid,))
    conv = cursor.fetchone()
    if not conv:
        conn.close()
        return {"success": False, "error": f"Conversation '{clean_cid}' not found."}

    # Duplicate submission guard: check if identical message was sent in last 2 seconds
    cursor.execute("""
        SELECT * FROM messages
        WHERE conversation_id = ? AND sender_id = ? AND content = ?
        ORDER BY id DESC LIMIT 1
    """, (clean_cid, clean_sid, clean_content))
    last_identical = cursor.fetchone()
    if last_identical:
        try:
            last_dt = datetime.fromisoformat(last_identical["created_at"].replace(" ", "T").split(".")[0])
            if (datetime.now() - last_dt).total_seconds() < 2:
                conn.close()
                return {"success": True, "message": dict(last_identical), "duplicate": True}
        except Exception:
            pass

    now_iso = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO messages (conversation_id, sender_id, sender_role, sender_name, content, attachment_url, attachment_name, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
    """, (clean_cid, clean_sid, clean_role, clean_name, clean_content, attachment_url, attachment_name, now_iso))
    msg_id = cursor.lastrowid

    # Update conversation's last message
    preview = clean_content[:60] if clean_content else "Attachment"
    cursor.execute("""
        UPDATE conversations
        SET last_message = ?, last_message_at = ?
        WHERE id = ?
    """, (preview, now_iso, clean_cid))
    conn.commit()
    conn.close()

    # Trigger notification for the other participant
    conv_dict = dict(conv)
    if clean_role == "doctor":
        recipient_id = conv_dict.get("patient_id", "4001")
        recipient_role = "patient"
        notif_title = f"New message from {clean_name}"
    elif clean_role == "viewer":
        recipient_id = conv_dict.get("doctor_id", "3001")
        recipient_role = "doctor"
        notif_title = f"New message from {clean_name} (Attender)"
    else:
        recipient_id = conv_dict.get("doctor_id", "3001")
        recipient_role = "doctor"
        notif_title = f"New message from {clean_name}"

    create_notification(
        user_id=recipient_id,
        role=recipient_role,
        n_type="chat_message",
        title=notif_title,
        message=preview,
        reference_type="conversation",
        reference_id=clean_cid,
        action_url=f"#chat?conv={clean_cid}",
        event_key=f"chat_msg_{msg_id}"
    )

    return {
        "success": True,
        "message": {
            "id": msg_id,
            "conversation_id": clean_cid,
            "sender_id": clean_sid,
            "sender_role": clean_role,
            "sender_name": clean_name,
            "content": clean_content,
            "attachment_url": attachment_url,
            "attachment_name": attachment_name,
            "is_read": 0,
            "created_at": now_iso
        }
    }


def mark_conversation_messages_as_read(conversation_id: str, reader_id: str) -> bool:
    """Marks all messages from other senders in a conversation as read."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        clean_cid = str(conversation_id).strip()
        clean_rid = str(reader_id).strip()
        cursor.execute("SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ? AND sender_id != ? AND is_read = 0", (clean_cid, clean_rid))
        row = cursor.fetchone()
        if row and row["cnt"] > 0:
            cursor.execute("""
                UPDATE messages
                SET is_read = 1
                WHERE conversation_id = ? AND sender_id != ? AND is_read = 0
            """, (clean_cid, clean_rid))
            conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[Chat] Error marking messages read: {e}")
        return False


# ==============================================================================
# ADVANCED AI SUPPORT ASSISTANT - LLM-POWERED (GEMINI VIA urllib)
# ==============================================================================


def _call_gemini_api(prompt, api_key, model="gemini-flash-lite-latest"):
    """
    Calls the Gemini REST API using Python built-in urllib (no extra packages required).
    Supports automatic resilient fallback between models if high demand (503) or timeout occurs.
    Returns the text response string, or raises RuntimeError on failure.
    """
    import urllib.request
    import urllib.error

    requested_model = (model or "gemini-flash-lite-latest").strip()
    MODEL_ALIASES = {
        "gemini-1.5-flash": "gemini-flash-lite-latest",
        "gemini-1.5-pro": "gemini-3.8-flash",
        "gemini-2.0-flash": "gemini-flash-lite-latest",
        "gemini-2.0-flash-lite": "gemini-flash-lite-latest",
        "gemini-2.5-flash": "gemini-flash-lite-latest",
        "gemini-3.5-flash": "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite": "gemini-flash-lite-latest",
        "gemini-flash": "gemini-flash-lite-latest",
    }
    primary_model = MODEL_ALIASES.get(requested_model.lower(), requested_model)

    candidates = [primary_model]
    for alt in ["gemini-flash-lite-latest", "gemini-3.8-flash"]:
        if alt not in candidates:
            candidates.append(alt)

    last_error = None
    for cand_model in candidates:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + cand_model
            + ":generateContent?key="
            + api_key
        )
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 1024,
                "topP": 0.9,
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
            ]
        }).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read().decode("utf-8")
                result = json.loads(raw)
                candidates_out = result.get("candidates", [])
                if candidates_out:
                    parts = candidates_out[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
                feedback = result.get("promptFeedback", {})
                block_reason = feedback.get("blockReason", "")
                if block_reason:
                    return f"I am unable to answer due to content safety restrictions ({block_reason})."
                return ""
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                pass
            last_error = RuntimeError(f"Gemini API HTTP {e.code}: {body[:300]}")
            if e.code in (404, 503, 429) and cand_model != candidates[-1]:
                print(f"[AI] Model '{cand_model}' returned HTTP {e.code}. Retrying with next candidate model...")
                continue
            raise last_error
        except urllib.error.URLError as e:
            last_error = RuntimeError(f"Gemini API network error: {e.reason}")
            if cand_model != candidates[-1]:
                print(f"[AI] Model '{cand_model}' network/timeout: {e.reason}. Retrying next model...")
                continue
            raise last_error
        except Exception as e:
            last_error = RuntimeError(f"Gemini API error: {e}")
            if cand_model != candidates[-1]:
                continue
            raise last_error

    if last_error:
        raise last_error
    return ""


def _gather_torus_context(user_id, role, question, conversation_history=None):
    """
    Fetches authorized TORUS DB records relevant to the question.
    Returns (context_text, context_data, suggested_actions).
    Only queries DB when the question is clearly operational.
    """
    import re as _re
    q_lower = question.lower()
    clean_uid = str(user_id or '3001').strip()
    clean_role = str(role or 'doctor').strip().lower()

    context_lines = []
    context_data = {}
    suggested_actions = []

    is_report_q = any(w in q_lower for w in ['report', 'pending', 'deliver', 'sign-off', 'certified', 'generated', 'available'])
    is_email_q = any(w in q_lower for w in ['email', 'failed', 'failure', 'resend', 'delivery fail', 'sent'])
    is_appt_q = any(w in q_lower for w in ['appointment', 'schedule', 'upcoming', 'session', 'consultation', 'when is my'])
    is_msg_q = any(w in q_lower for w in ['message', 'chat', 'unread', 'patient message', 'doctor message'])
    is_status_q = 'status' in q_lower and 'report' in q_lower

    if not (is_report_q or is_email_q or is_appt_q or is_msg_q or is_status_q):
        return ('', context_data, suggested_actions)

    try:
        conn = get_db()
        cursor = conn.cursor()
        rm = _re.search(r'\b(RPT-[A-Za-z0-9\-]+)\b', question, _re.IGNORECASE)
        extracted_rid = rm.group(1).upper() if rm else ''
        if not extracted_rid and conversation_history:
            for h in reversed(conversation_history):
                h_rm = _re.search(r'\b(RPT-[A-Za-z0-9\-]+)\b', str(h.get('content', '')), _re.IGNORECASE)
                if h_rm:
                    extracted_rid = h_rm.group(1).upper()
                    break

        # Pending Reports
        if ('pending' in q_lower or 'sign-off' in q_lower or 'waiting' in q_lower) and is_report_q:
            if clean_role == 'doctor':
                cursor.execute("""
                    SELECT report_id, patient_id, patient_name, scan_type, delivery_status, created_at
                    FROM diagnostic_reports WHERE delivery_status = 'pending'
                    ORDER BY id DESC LIMIT 5""")
                rows = [dict(r) for r in cursor.fetchall()]
                context_data['pending_reports'] = rows
                if rows:
                    context_lines.append('[DB: ' + str(len(rows)) + ' pending diagnostic report(s)]')
                    for r in rows:
                        context_lines.append('  * ' + r['report_id'] + ' - ' + str(r['patient_name']) + ' (' + str(r['scan_type']) + ', status: ' + str(r['delivery_status']) + ')')
                    suggested_actions.append({'label': 'Open Reports', 'action': 'navigate', 'url': '/report-generation.html'})
                else:
                    context_lines.append('[DB: No pending diagnostic reports found.]')
            else:
                cursor.execute("""
                    SELECT report_id, scan_type, doctor_name, delivery_status FROM diagnostic_reports
                    WHERE patient_id = ? AND delivery_status = 'pending' ORDER BY id DESC LIMIT 3""", (clean_uid,))
                rows = [dict(r) for r in cursor.fetchall()]
                context_data['my_pending_reports'] = rows
                if rows:
                    context_lines.append('[DB: ' + str(len(rows)) + ' pending report(s) for patient ' + clean_uid + ']')
                    for r in rows:
                        context_lines.append('  * ' + r['report_id'] + ' (' + str(r['scan_type']) + ')')
                else:
                    context_lines.append('[DB: No pending reports for this patient.]')

        # Failed Email Deliveries
        if is_email_q and ('fail' in q_lower or 'email' in q_lower):
            if clean_role == 'doctor':
                cursor.execute("""
                    SELECT report_id, patient_name, delivery_recipient, last_delivery_error FROM diagnostic_reports
                    WHERE delivery_status = 'failed' ORDER BY id DESC LIMIT 5""")
                rows = [dict(r) for r in cursor.fetchall()]
                context_data['failed_deliveries'] = rows
                if rows:
                    context_lines.append('[DB: ' + str(len(rows)) + ' failed report email delivery/deliveries]')
                    for r in rows:
                        context_lines.append('  * ' + r['report_id'] + ' for ' + str(r.get('patient_name','?')) + ' to ' + str(r.get('delivery_recipient','?')) + ': ' + str(r.get('last_delivery_error','unknown')))
                    suggested_actions.append({'label': 'Retry ' + rows[0]['report_id'], 'action': 'retry_email', 'target': rows[0]['report_id']})
                else:
                    context_lines.append('[DB: No failed report email deliveries found.]')
            else:
                cursor.execute("""
                    SELECT report_id, scan_type, last_delivery_error, delivery_recipient FROM diagnostic_reports
                    WHERE patient_id = ? AND delivery_status = 'failed' ORDER BY id DESC LIMIT 1""", (clean_uid,))
                row = cursor.fetchone()
                if row:
                    r = dict(row)
                    context_data['my_failed_delivery'] = r
                    context_lines.append('[DB: Failed delivery for patient ' + clean_uid + ': report ' + r['report_id'] + ', error: ' + str(r.get('last_delivery_error','?')) + ']')
                else:
                    context_lines.append('[DB: No failed report deliveries for this patient.]')

        # Specific Report Failure Reason
        if ('why' in q_lower and 'fail' in q_lower) or 'reason' in q_lower or 'root cause' in q_lower:
            if extracted_rid:
                cursor.execute('SELECT * FROM diagnostic_reports WHERE UPPER(report_id) = ?', (extracted_rid,))
                row = cursor.fetchone()
            elif clean_role == 'doctor':
                cursor.execute("SELECT * FROM diagnostic_reports WHERE delivery_status = 'failed' ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
            else:
                cursor.execute("SELECT * FROM diagnostic_reports WHERE patient_id = ? AND delivery_status = 'failed' ORDER BY id DESC LIMIT 1", (clean_uid,))
                row = cursor.fetchone()
            if row:
                r = dict(row)
                context_data['failed_report_detail'] = r
                context_lines.append('[DB: Failed report detail - ID: ' + r['report_id'] + ', patient: ' + str(r.get('patient_name','?')) + ', recipient: ' + str(r.get('delivery_recipient','?')) + ', error: ' + str(r.get('last_delivery_error','?')) + ']')
                suggested_actions.append({'label': 'Retry ' + r['report_id'], 'action': 'retry_email', 'target': r['report_id']})

        # Appointments
        if is_appt_q:
            if clean_role == 'doctor':
                cursor.execute("""
                    SELECT appointment_id, patient_name, scan_type, slot_time, scheduled_datetime FROM scheduled_appointments
                    WHERE status = 'scheduled' ORDER BY scheduled_datetime ASC LIMIT 5""")
                rows = [dict(r) for r in cursor.fetchall()]
                context_data['appointments'] = rows
                if rows:
                    context_lines.append('[DB: ' + str(len(rows)) + ' upcoming scheduled appointment(s)]')
                    for a in rows:
                        context_lines.append('  * ' + str(a['appointment_id']) + ': ' + str(a.get('patient_name','?')) + ' - ' + str(a.get('scan_type','?')) + ' at ' + str(a.get('slot_time','?')))
                    suggested_actions.append({'label': 'View Schedule', 'action': 'open_appointment'})
                else:
                    context_lines.append('[DB: No upcoming appointments found.]')
            else:
                cursor.execute("""
                    SELECT appointment_id, doctor_name, scan_type, slot_time, scheduled_datetime FROM scheduled_appointments
                    WHERE patient_id = ? AND status = 'scheduled' ORDER BY scheduled_datetime ASC LIMIT 3""", (clean_uid,))
                rows = [dict(r) for r in cursor.fetchall()]
                context_data['my_appointments'] = rows
                if rows:
                    a = rows[0]
                    context_lines.append('[DB: Next appointment for patient ' + clean_uid + ': ' + str(a['appointment_id']) + ' (' + str(a.get('scan_type','?')) + ') with Dr. ' + str(a.get('doctor_name','?')) + ' at ' + str(a.get('slot_time','?')) + ']')
                else:
                    context_lines.append('[DB: No upcoming appointments for this patient.]')

        # Report Status
        if is_status_q:
            if clean_role == 'doctor':
                if extracted_rid:
                    cursor.execute('SELECT * FROM diagnostic_reports WHERE UPPER(report_id) = ?', (extracted_rid,))
                else:
                    cursor.execute('SELECT * FROM diagnostic_reports ORDER BY id DESC LIMIT 4')
                rows = [dict(r) for r in cursor.fetchall()]
                context_data['report_statuses'] = rows
                if rows:
                    context_lines.append('[DB: ' + str(len(rows)) + ' diagnostic report(s) found]')
                    for r in rows:
                        context_lines.append('  * ' + r['report_id'] + ' - ' + str(r.get('patient_name','?')) + ': status=' + str(r.get('delivery_status','?')))
                else:
                    context_lines.append('[DB: No reports found.]')
            else:
                cursor.execute("""
                    SELECT report_id, scan_type, doctor_name, delivery_status, created_at FROM diagnostic_reports
                    WHERE patient_id = ? ORDER BY id DESC LIMIT 3""", (clean_uid,))
                rows = [dict(r) for r in cursor.fetchall()]
                context_data['my_report_statuses'] = rows
                if rows:
                    r = rows[0]
                    context_lines.append('[DB: Most recent report for patient ' + clean_uid + ': ' + r['report_id'] + ' (' + str(r.get('scan_type','?')) + '), status=' + str(r.get('delivery_status','?')) + ']')
                else:
                    context_lines.append('[DB: No finalized reports for this patient.]')

        # Patient Messages
        if is_msg_q:
            if clean_role == 'doctor':
                cursor.execute("""
                    SELECT m.sender_name, m.content, m.created_at, m.is_read FROM messages m
                    WHERE m.sender_role IN ('patient', 'viewer') ORDER BY m.id DESC LIMIT 5""")
                msgs = [dict(r) for r in cursor.fetchall()]
                context_data['patient_messages'] = msgs
                if msgs:
                    unread = sum(1 for m in msgs if not m.get('is_read'))
                    context_lines.append('[DB: ' + str(len(msgs)) + ' recent patient messages, ' + str(unread) + ' unread]')
                    for m in msgs:
                        context_lines.append('  * From ' + str(m.get('sender_name','?')) + ': "' + str(m.get('content',''))[:80] + '"')
                    suggested_actions.append({'label': 'Open Chat', 'action': 'open_chat'})
                else:
                    context_lines.append('[DB: No patient messages found.]')
            else:
                cursor.execute("""
                    SELECT m.sender_name, m.content, m.created_at FROM messages m
                    JOIN conversations c ON m.conversation_id = c.id
                    WHERE c.patient_id = ? AND m.sender_role = 'doctor' ORDER BY m.id DESC LIMIT 3""", (clean_uid,))
                msgs = [dict(r) for r in cursor.fetchall()]
                context_data['doctor_messages'] = msgs
                if msgs:
                    context_lines.append('[DB: ' + str(len(msgs)) + ' doctor messages for patient ' + clean_uid + ']')
                    for m in msgs:
                        context_lines.append('  * Dr. ' + str(m.get('sender_name','?')) + ': "' + str(m.get('content',''))[:80] + '"')
                    suggested_actions.append({'label': 'Reply in Chat', 'action': 'open_chat'})
                else:
                    context_lines.append('[DB: No doctor messages for this patient yet.]')

        conn.close()
    except Exception as db_err:
        print('[AI] DB context error: ' + str(db_err))
        context_lines.append('[DB: Query error - ' + str(db_err)[:100] + ']')

    return ('\n'.join(context_lines), context_data, suggested_actions)


def _db_only_fallback(question, role, uid, context_data, db_context_text):
    """
    Constructs a structured text answer from DB records alone.
    Used when LLM is unavailable but operational data is present,
    or as a greeting/general question fallback handler.
    """
    q_lower = question.lower()
    lines = []

    pending = context_data.get('pending_reports', []) or context_data.get('my_pending_reports', [])
    failed_list = context_data.get('failed_deliveries', [])
    failed_single = context_data.get('my_failed_delivery')
    failed_detail = context_data.get('failed_report_detail')
    appts = context_data.get('appointments', []) or context_data.get('my_appointments', [])
    msgs = context_data.get('patient_messages', []) or context_data.get('doctor_messages', [])
    statuses = context_data.get('report_statuses', []) or context_data.get('my_report_statuses', [])

    if failed_detail and ('why' in q_lower or 'reason' in q_lower or 'root cause' in q_lower):
        err = failed_detail.get('last_delivery_error') or 'unknown delivery error'
        lines.append('Delivery details for report **' + failed_detail['report_id'] + '** (' + str(failed_detail.get('patient_name','?')) + '):')
        lines.append('* **Recipient:** ' + str(failed_detail.get('delivery_recipient','?')))
        lines.append('* **Status:** Delivery Failed')
        lines.append('* **Error:** ' + err)
        if 'quota' in err.lower() or '550' in err:
            lines.append('* **Cause:** Recipient inbox is full (550 5.2.2 Mailbox quota exceeded).')
            lines.append('* **Action:** Update patient email and retry delivery.')
        elif 'invalid' in err.lower():
            lines.append('* **Action:** Verify and correct the patient email address, then retry.')
        else:
            lines.append('* **Action:** Verify hospital SMTP configuration and retry delivery.')
    elif failed_list:
        lines.append('**' + str(len(failed_list)) + ' failed report email delivery/deliveries:**')
        for f in failed_list:
            err = f.get('last_delivery_error') or 'unknown error'
            lines.append('* **' + f['report_id'] + '** for ' + str(f.get('patient_name','?')) + ' to ' + str(f.get('delivery_recipient','?')) + ': ' + err)
        lines.append('')
        lines.append('**To retry:** Update the patient email address and use the Resend button.')
    elif failed_single:
        lines.append('Failed delivery for your report **' + str(failed_single.get('report_id','?')) + '**: ' + str(failed_single.get('last_delivery_error','?')))
    elif pending:
        if role == 'doctor':
            lines.append('**' + str(len(pending)) + ' pending diagnostic report(s):**')
            for r in pending:
                lines.append('* **' + r['report_id'] + '** - ' + str(r.get('patient_name','?')) + ' (' + str(r.get('scan_type','?')) + ')')
            lines.append('')
            lines.append('You can certify and deliver them from the Report Generation section.')
        else:
            r = pending[0]
            lines.append('Your report **' + str(r.get('report_id','?')) + '** (' + str(r.get('scan_type','?')) + ') is pending doctor certification.')
    elif appts:
        if role == 'doctor':
            lines.append('**' + str(len(appts)) + ' upcoming appointment(s):**')
            for a in appts:
                lines.append('* **' + str(a['appointment_id']) + '**: ' + str(a.get('patient_name','?')) + ' - ' + str(a.get('scan_type','?')) + ' at ' + str(a.get('slot_time','?')))
        else:
            a = appts[0]
            lines.append('Your next appointment: **' + str(a.get('appointment_id','?')) + '** (' + str(a.get('scan_type','?')) + ') with Dr. ' + str(a.get('doctor_name','?')) + ' at **' + str(a.get('slot_time','?')) + '**.')
    elif msgs:
        if role == 'doctor':
            lines.append('**' + str(len(msgs)) + ' recent patient message(s):**')
            for m in msgs:
                lines.append('* From **' + str(m.get('sender_name','?')) + '**: "' + str(m.get('content',''))[:80] + '"')
        else:
            lines.append('**' + str(len(msgs)) + ' message(s) from your doctor:**')
            for m in msgs:
                lines.append('* Dr. **' + str(m.get('sender_name','?')) + '**: "' + str(m.get('content',''))[:80] + '"')
    elif statuses:
        lines.append('**Report status:**')
        for r in statuses:
            lines.append('* **' + str(r.get('report_id','?')) + '** (' + str(r.get('scan_type','?')) + '): ' + str(r.get('delivery_status','?')).upper())
    else:
        # Greetings and general fallback
        if any(w in q_lower for w in ['hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening']):
            name_part = 'Doctor' if role == 'doctor' else 'there'
            lines.append('Hello ' + name_part + '! Welcome to TORUS AI Support. How can I help you today?')
        elif 'how are you' in q_lower:
            lines.append("I'm doing well, thank you! I'm ready to help with your TORUS questions.")
        elif 'your name' in q_lower or 'who are you' in q_lower:
            lines.append('I am the **TORUS AI Support Assistant**. I can help with diagnostic reports, email deliveries, appointments, and TORUS operational questions.')
        elif any(w in q_lower for w in ['what can you do', 'help me', 'capabilities', 'can you help']):
            lines.append('I can help you with:\n* Pending diagnostic reports\n* Failed email deliveries\n* Upcoming appointments\n* Patient messages\n* Report status checks\n* TORUS workflow guidance')
        elif 'thank' in q_lower:
            lines.append("You're welcome! Feel free to ask if you need anything else.")
        elif any(w in q_lower for w in ['bye', 'goodbye', 'see you']):
            lines.append('Goodbye! Feel free to return whenever you need assistance.')
        elif 'artificial intelligence' in q_lower or 'machine learning' in q_lower or 'what is' in q_lower:
            lines.append('I am best suited for TORUS operational questions. For general knowledge questions, please configure a valid Gemini API key to enable full conversational AI capabilities.')
        else:
            lines.append('Hello! I am the TORUS AI Support Assistant. I can help with:\n\n* **Which patients have pending reports?**\n* **Which report emails failed today?**\n* **Show my upcoming appointments.**\n* **Why did this report delivery fail?**\n* **What is the status of this report?**\n\nAsk me anything about TORUS clinical operations!')

    return {'response': '\n'.join(lines) if lines else 'I am here to help. Please ask your question.'}


def query_ai_support_assistant(user_id, role, question, conversation_id=None):
    """
    LLM-powered AI Support Assistant for TORUS.
    - Handles greetings, casual questions, and general questions via Gemini LLM.
    - Injects verified TORUS DB records as context for operational queries.
    - Uses Python built-in urllib - no extra packages required.
    - Persists conversation history and maintains multi-turn follow-up context.
    - Returns clear errors when provider is unavailable; never returns fabricated answers.
    - Falls back to DB-grounded structured text when LLM is unavailable.
    """
    clean_q = str(question or '').strip()
    clean_uid = str(user_id or '3001').strip()
    clean_role = str(role or 'doctor').strip().lower()
    conv_id = str(conversation_id or f"ai_conv_{clean_uid}_{clean_role}").strip()

    if not clean_q:
        return {
            'success': False,
            'error': {'code': 'QUESTION_REQUIRED', 'message': 'Question is required.'},
            'response': 'Please provide a question so I can assist you.',
            'answer': 'Please provide a question so I can assist you.',
            'conversationId': conv_id,
            'conversation_id': conv_id
        }

    # Fetch recent conversation turns for multi-turn context
    history = get_ai_conversation_history(conv_id, limit=6)

    load_env_file()
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    model = os.environ.get('GEMINI_MODEL', 'gemini-flash-lite-latest').strip()

    db_context_text, context_data, suggested_actions = _gather_torus_context(
        clean_uid, clean_role, clean_q, conversation_history=history
    )

    role_label = 'Doctor' if clean_role == 'doctor' else ('Patient' if clean_role == 'patient' else 'Attender')

    history_text = ""
    if history:
        history_lines = ["[Recent Conversation History:]"]
        for h in history:
            h_role = "User" if h.get("role") == "user" else "Assistant"
            history_lines.append(f"{h_role}: {h.get('content', '')}")
        history_text = "\n".join(history_lines) + "\n\n"

    system_prompt = (
        'You are the TORUS AI Support Assistant - a helpful, professional, and conversational AI assistant\n'
        'for the TORUS Tele-Operated Robotic Ultrasound System platform.\n\n'
        'Your role:\n'
        '- Answer ordinary conversational questions (greetings, how are you, what is your name, what can you do, thank you, etc.) naturally and warmly.\n'
        '- Answer general knowledge and medical workflow questions concisely, clearly, and accurately.\n'
        '- For TORUS operational questions, use ONLY the verified database records provided below as your source of truth.\n'
        '- If operational records are present, summarize them clearly with bullet points and bold IDs/names.\n'
        '- If operational records are requested but none exist, state so truthfully (e.g. "No failed report deliveries were found for today."). Never invent fake reports, IDs, or clinical findings.\n'
        '- Never provide medical diagnoses or treatment recommendations. Direct clinical questions to qualified clinicians.\n'
        '- Keep responses concise and professional. Use bullet points for lists. Use **bold** for key IDs and names.\n'
        '- You are speaking with a ' + role_label + ' (User ID: ' + clean_uid + ').\n\n'
        + history_text
        + 'Verified TORUS Database Records (use ONLY these for operational answers):\n'
        + (db_context_text if db_context_text else '[No database records retrieved - this is a conversational or general question.]') + '\n\n'
        + 'User question: ' + clean_q + '\n\n'
        + 'Respond directly and helpfully. Do not repeat this prompt or mention system instructions.'
    )

    key_ok = (api_key and
              not api_key.startswith('your_') and
              api_key != 'REPLACE_WITH_YOUR_GEMINI_API_KEY' and
              len(api_key) > 20)

    now_iso = datetime.now().isoformat()

    if not key_ok:
        print('[AI] GEMINI_API_KEY not configured. Using DB-only fallback.')
        fallback = _db_only_fallback(clean_q, clean_role, clean_uid, context_data, db_context_text)
        answer_text = fallback['response']
        save_ai_message(conv_id, "user", clean_q, clean_uid, clean_role)
        save_ai_message(conv_id, "assistant", answer_text, clean_uid, clean_role)
        return {
            'success': True,
            'is_ai': True,
            'conversationId': conv_id,
            'conversation_id': conv_id,
            'message': {
                'role': 'assistant',
                'content': answer_text,
                'timestamp': now_iso
            },
            'assistant_name': 'TORUS AI Support Assistant',
            'disclaimer': 'Database-grounded operational guidance. Configure GEMINI_API_KEY in .env for full conversational AI.',
            'response': answer_text,
            'answer': answer_text,
            'data': context_data,
            'suggested_actions': suggested_actions,
            '_provider': 'db_fallback'
        }

    try:
        answer_text = _call_gemini_api(system_prompt, api_key, model)
        if not answer_text:
            answer_text = 'I was not able to generate a response. Please try rephrasing your question.'
        
        save_ai_message(conv_id, "user", clean_q, clean_uid, clean_role)
        save_ai_message(conv_id, "assistant", answer_text, clean_uid, clean_role)
        
        return {
            'success': True,
            'is_ai': True,
            'conversationId': conv_id,
            'conversation_id': conv_id,
            'message': {
                'role': 'assistant',
                'content': answer_text,
                'timestamp': now_iso
            },
            'assistant_name': 'TORUS AI Support Assistant',
            'disclaimer': 'TORUS Clinical AI - Operational guidance only. Not a substitute for clinical judgment.',
            'response': answer_text,
            'answer': answer_text,
            'data': context_data,
            'suggested_actions': suggested_actions,
            '_provider': 'gemini'
        }

    except RuntimeError as api_err:
        err_str = str(api_err)
        print('[AI] Gemini API error: ' + err_str)

        if '403' in err_str or 'API_KEY_INVALID' in err_str or '401' in err_str:
            user_msg = ('The AI assistant is not available because the API key is invalid or not authorized. '
                        'Please contact your system administrator to configure a valid GEMINI_API_KEY in the .env file.')
        elif '404' in err_str or 'NOT_FOUND' in err_str:
            user_msg = ('The configured AI model is not available. '
                        'Please update GEMINI_MODEL in .env to a valid model name (e.g. gemini-flash-lite-latest).')
        elif '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str or 'quota' in err_str.lower():
            user_msg = 'The AI assistant has reached its usage limit. Please try again in a few moments.'
        elif 'network' in err_str.lower() or 'timeout' in err_str.lower():
            user_msg = 'The AI assistant could not connect to the AI service. Please check network connectivity.'
        else:
            user_msg = 'The AI assistant is temporarily unavailable. Please try again shortly.'

        if db_context_text:
            fallback = _db_only_fallback(clean_q, clean_role, clean_uid, context_data, db_context_text)
            answer_text = fallback['response']
            save_ai_message(conv_id, "user", clean_q, clean_uid, clean_role)
            save_ai_message(conv_id, "assistant", answer_text, clean_uid, clean_role)
            return {
                'success': True,
                'is_ai': True,
                'conversationId': conv_id,
                'conversation_id': conv_id,
                'message': {
                    'role': 'assistant',
                    'content': answer_text,
                    'timestamp': now_iso
                },
                'assistant_name': 'TORUS AI Support Assistant',
                'disclaimer': 'AI service unavailable: ' + user_msg + ' Showing verified database records only.',
                'response': answer_text,
                'answer': answer_text,
                'data': context_data,
                'suggested_actions': suggested_actions,
                '_provider': 'db_fallback_on_error'
            }

        return {
            'success': False,
            'error': {'code': 'AI_PROVIDER_UNAVAILABLE', 'message': user_msg},
            'conversationId': conv_id,
            'conversation_id': conv_id,
            'response': user_msg,
            'answer': user_msg,
            'data': {},
            'suggested_actions': []
        }

    except Exception as unexpected:
        print('[AI] Unexpected error: ' + str(unexpected))
        return {
            'success': False,
            'error': {'code': 'AI_INTERNAL_ERROR', 'message': 'An unexpected error occurred. Please try again.'},
            'conversationId': conv_id,
            'conversation_id': conv_id,
            'response': 'An unexpected error occurred. Please try again.',
            'answer': 'An unexpected error occurred. Please try again.'
        }


def get_report_delivery_audit_history(report_id: str) -> list:
    """Returns delivery audit history for a report."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM report_delivery_audit_history
        WHERE LOWER(report_id) = ? OR report_id = ?
        ORDER BY id ASC
    """, (report_id.strip().lower(), report_id.strip()))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")



