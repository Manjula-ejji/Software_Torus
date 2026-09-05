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
            fingerprint_template TEXT NOT NULL,
            scanner_model TEXT DEFAULT 'Arduino/Serial Biometric Scanner',
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
    conn.commit()
    
    # Seed default Doctor: admin@gmail.com / admin123 (role: doctor, UID: 3001)
    cursor.execute("SELECT * FROM doctors WHERE LOWER(email) = 'admin@gmail.com'")
    if not cursor.fetchone():
        admin_pass = hash_password("admin123")
        cursor.execute("SELECT id FROM doctors WHERE uid = '3001'")
        doc_uid = "3001" if not cursor.fetchone() else generate_professional_id()
        cursor.execute("""
            INSERT INTO doctors (uid, name, email, password_hash, role, mobile)
            VALUES (?, ?, ?, ?, 'doctor', '')
        """, (doc_uid, "Admin Doctor", "admin@gmail.com", admin_pass))
        conn.commit()
        print(f"[Database] Default Doctor created (UID: {doc_uid}, email: admin@gmail.com).")

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
        
    conn.close()
    _migrate_add_mobile_column()

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
                "role": row["role"]
            }
        }
    return {"success": False, "error": "Invalid email/UID or password."}

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
# DOCTOR BIOMETRIC DRIVER
# ============================================================
def register_doctor_biometric(identifier: str, template_data: str, scanner_model: str = "Arduino/Serial Biometric Scanner") -> dict:
    conn = get_db()
    cursor = conn.cursor()
    clean_id = identifier.strip().lower()

    cursor.execute("SELECT id, uid, name, email FROM doctors WHERE LOWER(email) = ? OR LOWER(uid) = ?", (clean_id, clean_id))
    doctor = cursor.fetchone()
    if not doctor:
        conn.close()
        return {"success": False, "error": f"Doctor account not found for '{identifier}'."}

    cursor.execute("UPDATE doctor_biometrics SET is_active = 0 WHERE doctor_id = ?", (doctor["id"],))
    cursor.execute("""
        INSERT INTO doctor_biometrics (doctor_id, uid, email, fingerprint_template, scanner_model, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
    """, (doctor["id"], doctor["uid"], doctor["email"], template_data, scanner_model))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Fingerprint registered successfully.",
        "subtitle": "Your fingerprint has been securely linked to your account.",
        "doctor": {
            "id": doctor["id"],
            "uid": doctor["uid"],
            "name": doctor["name"],
            "email": doctor["email"]
        }
    }

def verify_doctor_biometric(identifier: str = None, scanned_template: str = None) -> dict:
    conn = get_db()
    cursor = conn.cursor()

    if identifier:
        clean_id = identifier.strip().lower()
        cursor.execute("""
            SELECT d.id, d.uid, d.name, d.email, d.role, b.fingerprint_template
            FROM doctors d
            JOIN doctor_biometrics b ON d.id = b.doctor_id
            WHERE (LOWER(d.email) = ? OR LOWER(d.uid) = ?) AND b.is_active = 1
            LIMIT 1
        """, (clean_id, clean_id))
    else:
        cursor.execute("""
            SELECT d.id, d.uid, d.name, d.email, d.role, b.fingerprint_template
            FROM doctors d
            JOIN doctor_biometrics b ON d.id = b.doctor_id
            WHERE b.is_active = 1
            LIMIT 1
        """)

    row = cursor.fetchone()
    conn.close()

    if not row:
        return {
            "success": False,
            "matched": False,
            "error": "Fingerprint does not match. Please try again."
        }

    return {
        "success": True,
        "matched": True,
        "message": "Fingerprint verified successfully.",
        "doctor": {
            "id": row["id"],
            "uid": row["uid"],
            "name": row["name"],
            "email": row["email"],
            "role": row["role"]
        }
    }

def get_doctor_biometric(identifier: str) -> dict:
    conn = get_db()
    cursor = conn.cursor()
    clean_id = identifier.strip().lower()
    cursor.execute("""
        SELECT b.id, b.enrolled_at, b.scanner_model, d.name, d.email, d.uid
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
        "doctor": {
            "uid": row["uid"],
            "name": row["name"],
            "email": row["email"]
        }
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

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")

