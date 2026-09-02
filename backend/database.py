import sqlite3
import hashlib
import os
import re
import random
import string
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "torus_doctors.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
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
                print(f"[ENV] Notice reading {p}: {e}")

def send_otp_email(to_email: str, doctor_name: str, doctor_uid: str, otp: str) -> tuple[bool, str]:
    """
    Sends a real OTP to the doctor's registered email address via SMTP.
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
    
    # If no custom from address is provided, use authenticated user
    smtp_from_env = os.environ.get("SMTP_FROM", os.environ.get("EMAIL_FROM", "")).strip()
    if smtp_from_env and "noreply@torus.med" not in smtp_from_env:
        smtp_from = smtp_from_env
    elif smtp_user:
        smtp_from = f"TORUS Healthcare <{smtp_user}>"
    else:
        smtp_from = "TORUS Healthcare <noreply@torus.med>"

    use_ssl = os.environ.get("SMTP_SSL", "false").lower() in ("true", "1") or smtp_port == 465
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1") or smtp_port == 587

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
                    Hello <strong>{doctor_name}</strong> (User ID: <code style="color: #00C8FF;">{doctor_uid}</code>),
                  </p>
                  <p style="color: #B7C5D8; font-size: 14px; line-height: 1.5; margin: 0 0 24px 0;">
                    We received a request to reset your password for the TORUS clinical workspace. Use the verification code below:
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

    text_content = f"Hello {doctor_name},\n\nYour TORUS password reset verification code is: {otp}\n\nThis OTP is valid for 10 minutes.\nUser ID: {doctor_uid}\n\nIf you did not request this, please ignore this email."

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
        err = f"SMTP Authentication failed for '{smtp_user}'. If using Gmail, please use a 16-character Google App Password (from https://myaccount.google.com/apppasswords)."
        print(f"[SMTP] [ERROR] {err} ({auth_err})")
        return False, err
    except Exception as e:
        err = f"Failed to send email to {to_email}: {e}"
        print(f"[SMTP] [ERROR] {err}")
        return False, err

def _migrate_add_mobile_column():
    """Safely adds 'mobile' column to doctors table if it doesn't exist."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(doctors)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "mobile" not in columns:
            cursor.execute("ALTER TABLE doctors ADD COLUMN mobile TEXT DEFAULT ''")
            conn.commit()
            print("[Database] Migrated: added 'mobile' column to doctors table.")
    except Exception as e:
        print(f"[Database] Migration warning: {e}")
    finally:
        conn.close()

def init_db():
    """Initializes the doctors table, password_reset_otps table, and seeds default admin doctor if empty."""
    conn = get_db()
    cursor = conn.cursor()
    
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
    conn.commit()
    
    # Check if admin exists
    cursor.execute("SELECT * FROM doctors WHERE email = ?", ("admin@gmail.com",))
    if not cursor.fetchone():
        admin_pass = hash_password("admin123")
        cursor.execute("""
            INSERT INTO doctors (uid, name, email, password_hash, role)
            VALUES (?, ?, ?, ?, ?)
        """, ("3001", "Admin Doctor", "admin@gmail.com", admin_pass, "admin"))
        conn.commit()
        print("[Database] Default Admin Doctor created (UID: 3001, email: admin@gmail.com).")
        
    conn.close()
    
    # Run migration for existing databases that might not have mobile column
    _migrate_add_mobile_column()

def generate_professional_id() -> str:
    """
    Generates a unique alphanumeric Professional ID in format DOC-XXXXX.
    Each X is a random uppercase letter or digit. Checks for uniqueness in the database.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    for _ in range(100):  # max retries to avoid infinite loop
        chars = string.ascii_uppercase + string.digits
        random_part = ''.join(random.choices(chars, k=5))
        professional_id = f"DOC-{random_part}"
        
        cursor.execute("SELECT id FROM doctors WHERE uid = ?", (professional_id,))
        if not cursor.fetchone():
            conn.close()
            return professional_id
    
    conn.close()
    # Extremely unlikely fallback
    raise RuntimeError("Could not generate a unique Professional ID after 100 attempts.")

def validate_strong_password(password: str) -> tuple:
    """
    Validates that a password meets strong password requirements.
    Returns (is_valid: bool, error_message: str).
    """
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
    """Validates mobile number format (allows various international formats)."""
    cleaned = re.sub(r'[\s\-\(\)]', '', mobile.strip())
    # Allow formats like: +919876543210, 9876543210, +1-234-567-8910, etc.
    pattern = r'^\+?[0-9]{7,15}$'
    return bool(re.match(pattern, cleaned))

def validate_professional_id_format(uid: str) -> bool:
    """Validates that a Professional ID matches DOC-XXXXX format."""
    pattern = r'^DOC-[A-Z0-9]{5}$'
    return bool(re.match(pattern, uid.strip()))

def get_next_uid() -> str:
    """Generates the next sequential UID starting at 3002. (Legacy, kept for backward compatibility)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT uid FROM doctors WHERE uid GLOB '[0-9]*' ORDER BY CAST(uid AS INTEGER) DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    
    if row and row["uid"].isdigit():
        last_uid = int(row["uid"])
        return str(max(3002, last_uid + 1))
    return "3002"

def register_doctor(name: str, email: str, password: str, mobile: str = "", uid: str = "", role: str = "doctor"):
    """Registers a new doctor into SQLite with full backend validation."""
    
    # --- Backend Validations ---
    
    # Validate name
    clean_name = name.strip()
    if not clean_name:
        return {"success": False, "error": "Full Name is required."}
    
    # Validate email
    clean_email = email.strip().lower()
    if not clean_email:
        return {"success": False, "error": "Email is required."}
    if not validate_email_format(clean_email):
        return {"success": False, "error": "Please enter a valid email address."}
    
    # Validate mobile
    clean_mobile = mobile.strip()
    if not clean_mobile:
        return {"success": False, "error": "Mobile Number is required."}
    if not validate_mobile_format(clean_mobile):
        return {"success": False, "error": "Please enter a valid mobile number."}
    
    # Validate password strength
    if not password:
        return {"success": False, "error": "Password is required."}
    pwd_valid, pwd_error = validate_strong_password(password)
    if not pwd_valid:
        return {"success": False, "error": pwd_error}
    
    # Force role to doctor (never trust frontend)
    role = "doctor"
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check duplicate email
    cursor.execute("SELECT id FROM doctors WHERE LOWER(email) = LOWER(?)", (clean_email,))
    if cursor.fetchone():
        conn.close()
        return {"success": False, "error": "An account with this email already exists."}
    
    # Process Professional ID
    clean_uid = uid.strip().upper() if uid else ""
    if clean_uid:
        # Check duplicate Professional ID
        cursor.execute("SELECT id FROM doctors WHERE UPPER(uid) = UPPER(?)", (clean_uid,))
        if cursor.fetchone():
            conn.close()
            return {"success": False, "error": f"Professional ID '{clean_uid}' is already registered."}
        final_uid = clean_uid
    else:
        # Generate unique Professional ID
        final_uid = generate_professional_id()
    
    pwd_hash = hash_password(password)
    
    cursor.execute("""
        INSERT INTO doctors (uid, name, email, password_hash, role, mobile)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (final_uid, clean_name, clean_email, pwd_hash, role, clean_mobile))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "doctor": {
            "uid": final_uid,
            "name": clean_name,
            "email": clean_email,
            "mobile": clean_mobile,
            "role": role
        }
    }

def authenticate_doctor(login_id: str, password: str):
    """Authenticates doctor against SQLite using Email OR UID."""
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
                "role": row["role"]
            }
        }
    return {"success": False, "error": "Invalid email/UID or password."}

def generate_and_store_reset_otp(identifier: str):
    """
    Finds doctor by email or UID, generates a secure 6-digit OTP, stores it with 10m expiry,
    and dispatches it to the doctor's registered email via SMTP.
    """
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
    
    # Generate 6-digit numeric OTP
    otp = f"{random.randint(100000, 999999)}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Invalidate older unused OTPs for this doctor
    cursor.execute("UPDATE password_reset_otps SET used = 2 WHERE doctor_id = ? AND used = 0", (doctor_id,))
    
    # Insert new OTP record
    cursor.execute("""
        INSERT INTO password_reset_otps (doctor_id, identifier, email, otp, expires_at, used)
        VALUES (?, ?, ?, ?, ?, 0)
    """, (doctor_id, clean_id, doctor_email, otp, expires_at))
    conn.commit()
    conn.close()
    
    # Send email via SMTP
    sent, err_msg = send_otp_email(doctor_email, doctor_name, doctor_uid, otp)
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

    masked = mask_email(doctor_email)
    return {
        "success": True,
        "message": "A 6-digit OTP has been sent to your registered email address.",
        "masked_email": masked,
        "email": doctor_email
    }

def verify_reset_otp(identifier: str, otp: str):
    """
    Validates the 6-digit OTP against the active record for this doctor in SQLite.
    Returns a reset_token if valid.
    """
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
    
    # Fetch active OTP
    cursor.execute("""
        SELECT * FROM password_reset_otps 
        WHERE doctor_id = ? AND used = 0 
        ORDER BY id DESC LIMIT 1
    """, (doctor_id,))
    otp_record = cursor.fetchone()
    
    if not otp_record:
        conn.close()
        return {"success": False, "error": "No active OTP found. Please request a new OTP."}
    
    # Check expiry
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
    
    # Generate temporary reset token
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

def reset_doctor_password_with_token(identifier: str, reset_token: str, new_password: str):
    """
    Validates token and strong password, updates doctor password in SQLite.
    """
    clean_id = identifier.strip().lower()
    clean_token = reset_token.strip()
    
    if not clean_id or not clean_token:
        return {"success": False, "error": "Invalid session. Please restart password reset."}
    
    # Validate password strength
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
    
    # Hash password securely
    pwd_hash = hash_password(new_password)
    
    # Update doctor password
    cursor.execute("UPDATE doctors SET password_hash = ? WHERE id = ?", (pwd_hash, doctor_id))
    # Mark OTP as used
    cursor.execute("UPDATE password_reset_otps SET used = 1 WHERE id = ?", (otp_record["id"],))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": "Password updated successfully. You can now log in with your new password.",
        "email": doctor["email"]
    }

def reset_doctor_password(email: str, new_password: str):
    """Resets password for doctor with specified email (legacy)."""
    conn = get_db()
    cursor = conn.cursor()
    email_clean = email.strip().lower()
    
    cursor.execute("SELECT id FROM doctors WHERE LOWER(email) = ? OR LOWER(uid) = ?", (email_clean, email_clean))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"success": False, "error": "No account found with this email or User ID."}
    
    pwd_hash = hash_password(new_password)
    cursor.execute("UPDATE doctors SET password_hash = ? WHERE id = ?", (pwd_hash, row["id"]))
    conn.commit()
    conn.close()
    
    return {"success": True, "message": "Password updated successfully."}

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
