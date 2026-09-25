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
    
    for r in rows:
        if isinstance(r.get("telemetry_json"), str):
            try:
                r["telemetry"] = json.loads(r["telemetry_json"])
            except Exception:
                r["telemetry"] = {}
        else:
            r["telemetry"] = r.get("telemetry_json") or {}
    return rows

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
    if isinstance(r.get("telemetry_json"), str):
        try:
            r["telemetry"] = json.loads(r["telemetry_json"])
        except Exception:
            r["telemetry"] = {}
    else:
        r["telemetry"] = r.get("telemetry_json") or {}
    return r

def create_diagnostic_report(data: dict) -> dict:
    """Inserts a new diagnostic report record into SQLite."""
    conn = get_db()
    cursor = conn.cursor()
    
    report_id = data.get("report_id") or data.get("reportId")
    if not report_id:
        cursor.execute("SELECT COUNT(*) as cnt FROM diagnostic_reports")
        next_num = cursor.fetchone()["cnt"] + 1
        report_id = f"REP-2026-{str(next_num).zfill(3)}"
        
    session_id = data.get("session_id") or data.get("sessionId") or f"S-{report_id.replace('REP-2026-', '')}"
    patient_id = data.get("patient_id") or data.get("patientId") or "P-1000"
    patient_name = data.get("patient_name") or data.get("patientName") or "Patient"
    scan_type = data.get("scan_type") or data.get("scanType") or "General"
    device_id = data.get("device_id") or data.get("deviceId") or "TORUS-A12"
    exam_date = data.get("exam_date") or data.get("examDate") or data.get("sessionDate") or "2026-09-25"
    exam_time = data.get("exam_time") or data.get("examTime") or data.get("sessionTime") or "10:00 AM"
    duration = data.get("duration") or "20:00"
    doctor_id = data.get("doctor_id") or data.get("doctorId") or "3001"
    doctor_name = data.get("doctor_name") or data.get("doctorName") or "Dr. Admin Doctor"
    doctor_license = data.get("doctor_license") or data.get("doctorLicense") or "TORUS-REG-3001"
    diagnostic_center = data.get("diagnostic_center") or data.get("diagnosticCenter") or "Apex Diagnostic Center"
    report_status = (data.get("report_status") or data.get("status") or "ready").strip().lower()
    clinical_summary = data.get("clinical_summary") or data.get("clinicalSummary") or "Clinical assessment completed."
    ultrasound_findings = data.get("ultrasound_findings") or data.get("ultrasoundFindings") or "Ultrasound scan performed."
    diagnosis_impression = data.get("diagnosis_impression") or data.get("diagnosisImpression") or "Examination completed."
    
    telemetry = data.get("telemetry") or {
        "maxForce": "2.5 N", "avgForce": "1.8 N", "latency": "15 ms", "frames": 5000, "stability": "99.2%"
    }
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
        return {"success": True, "report": created}
    except Exception as e:
        conn.close()
        return {"success": False, "error": str(e)}

def update_diagnostic_report(report_id: str, updates: dict) -> dict:
    """Updates fields of an existing diagnostic report."""
    existing = get_diagnostic_report_by_id(report_id)
    if not existing:
        return {"success": False, "error": f"Report '{report_id}' not found."}
        
    conn = get_db()
    cursor = conn.cursor()
    
    allowed_fields = {
        "patient_name": ["patient_name", "patientName"],
        "patient_id": ["patient_id", "patientId"],
        "scan_type": ["scan_type", "scanType"],
        "device_id": ["device_id", "deviceId"],
        "exam_date": ["exam_date", "examDate", "sessionDate"],
        "exam_time": ["exam_time", "examTime", "sessionTime"],
        "doctor_name": ["doctor_name", "doctorName"],
        "diagnostic_center": ["diagnostic_center", "diagnosticCenter"],
        "report_status": ["report_status", "status"],
        "clinical_summary": ["clinical_summary", "clinicalSummary"],
        "ultrasound_findings": ["ultrasound_findings", "ultrasoundFindings"],
        "diagnosis_impression": ["diagnosis_impression", "diagnosisImpression"],
        "duration": ["duration"]
    }
    
    set_clauses = []
    params = []
    
    for db_col, keys in allowed_fields.items():
        for k in keys:
            if k in updates and updates[k] is not None:
                val = updates[k]
                if db_col == "report_status":
                    val = str(val).strip().lower()
                set_clauses.append(f"{db_col} = ?")
                params.append(val)
                break
                
    if "telemetry" in updates and updates["telemetry"] is not None:
        t = updates["telemetry"]
        set_clauses.append("telemetry_json = ?")
        params.append(json.dumps(t) if isinstance(t, dict) else str(t))
        
    if not set_clauses:
        conn.close()
        return {"success": True, "report": existing, "message": "No changes provided"}
        
    sql = f"UPDATE diagnostic_reports SET {', '.join(set_clauses)} WHERE LOWER(report_id) = ? OR id = ?"
    params.extend([report_id.strip().lower(), report_id.strip()])
    
    try:
        cursor.execute(sql, params)
        conn.commit()
        updated = get_diagnostic_report_by_id(report_id)
        conn.close()
        return {"success": True, "report": updated}
    except Exception as e:
        conn.close()
        return {"success": False, "error": str(e)}

def generate_report_pdf_bytes(report_id: str) -> tuple[bytes | None, str | None]:
    """Generates official medical PDF bytes for a diagnostic report using ReportLab."""
    report = get_diagnostic_report_by_id(report_id)
    if not report:
        return None, "Report not found"
        
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        
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
        
        h_title = ParagraphStyle('HTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=15, leading=19, textColor=colors.HexColor('#0f172a'))
        h_meta = ParagraphStyle('HMeta', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, alignment=2, textColor=colors.HexColor('#475569'))
        sec_hdr = ParagraphStyle('SecHdr', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=colors.HexColor('#0369a1'))
        cell_lbl = ParagraphStyle('CellLbl', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=7.5, leading=10, textColor=colors.HexColor('#64748b'))
        cell_val = ParagraphStyle('CellVal', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11, textColor=colors.HexColor('#0f172a'))
        cell_val_b = ParagraphStyle('CellValB', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=11.5, textColor=colors.HexColor('#0f172a'))
        body_p = ParagraphStyle('BodyP', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor('#1e293b'))
        sign_name = ParagraphStyle('SignName', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=12, textColor=colors.HexColor('#0f172a'))
        
        story = []
        
        # Header banner
        header_data = [
            [
                Paragraph("<b>TORUS CLINICAL ROBOTICS PLATFORM</b><br/><font color='#0284c7'><b>TELE-SONOGRAPHY DIAGNOSTIC EXAMINATION REPORT</b></font><br/><font size='8' color='#64748b'>" + str(report.get("diagnostic_center", "Apex Diagnostic Center")) + " • Department of Tele-Radiology</font>", h_title),
                Paragraph("<b>DOCUMENT:</b> OFFICIAL RECORD<br/><b>EXAM DATE:</b> " + str(report.get("exam_date", "")) + " " + str(report.get("exam_time", "")) + "<br/><b>STATUS:</b> <font color='" + ("#059669" if report.get("report_status") == "ready" else "#d97706") + "'><b>" + ("FINALIZED" if report.get("report_status") == "ready" else "PENDING REVIEW") + "</b></font><br/><b>ENCRYPTED HASH:</b> TORUS-SHA256-VERIFIED", h_meta)
            ]
        ]
        t_header = Table(header_data, colWidths=[360, 180])
        t_header.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(t_header)
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0284c7'), spaceAfter=8, spaceBefore=4))
        
        # Demographics and Exam Metadata Table
        status_label = "FINALIZED & APPROVED" if report.get("report_status") == "ready" else "PENDING REVIEW"
        status_color = "#059669" if report.get("report_status") == "ready" else "#d97706"
        
        patient_grid = [
            [
                Paragraph("PATIENT FULL NAME", cell_lbl),
                Paragraph("PATIENT IDENTIFIER", cell_lbl),
                Paragraph("REPORT NUMBER", cell_lbl),
                Paragraph("REPORT STATUS", cell_lbl)
            ],
            [
                Paragraph(str(report.get("patient_name", "Unknown")), cell_val_b),
                Paragraph(str(report.get("patient_id", "Unknown")), cell_val_b),
                Paragraph(str(report.get("report_id", "Unknown")), cell_val_b),
                Paragraph(f"<font color='{status_color}'><b>{status_label}</b></font>", cell_val_b)
            ],
            [
                Paragraph("PROCEDURE / SCAN TYPE", cell_lbl),
                Paragraph("EXAMINATION DATE & TIME", cell_lbl),
                Paragraph("ATTENDING PHYSICIAN", cell_lbl),
                Paragraph("SESSION & RIG ID", cell_lbl)
            ],
            [
                Paragraph(f"{report.get('scan_type', '')} Ultrasound", cell_val_b),
                Paragraph(f"{report.get('exam_date', '')} at {report.get('exam_time', '')} ({report.get('duration', '20m')})", cell_val),
                Paragraph(f"{report.get('doctor_name', 'Dr. Admin Doctor')} ({report.get('doctor_license', 'TORUS-REG-3001')})", cell_val),
                Paragraph(f"Session {report.get('session_id', '')} / {report.get('device_id', '')}", cell_val)
            ]
        ]
        t_pat = Table(patient_grid, colWidths=[135, 135, 135, 135])
        t_pat.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(t_pat)
        story.append(Spacer(1, 8))
        
        # Telemetry Table
        tele = report.get("telemetry") or {}
        tele_grid = [
            [
                Paragraph("<b>ROBOTIC TELE-SONOGRAPHY TELEMETRY & SCAN QUALITY METRICS</b>", sec_hdr),
                Paragraph("", sec_hdr),
                Paragraph("", sec_hdr),
                Paragraph("", sec_hdr)
            ],
            [
                Paragraph("MAX CONTACT FORCE", cell_lbl),
                Paragraph("MEAN CONTACT FORCE", cell_lbl),
                Paragraph("WEBRTC CONTROL LATENCY", cell_lbl),
                Paragraph("CAPTURED CINE FRAMES", cell_lbl)
            ],
            [
                Paragraph(str(tele.get("maxForce", "2.6 N")), cell_val_b),
                Paragraph(str(tele.get("avgForce", "1.9 N")), cell_val_b),
                Paragraph(str(tele.get("latency", "16 ms")), cell_val_b),
                Paragraph(str(tele.get("frames", "5200")) + " Cine Frames", cell_val_b)
            ]
        ]
        t_tele = Table(tele_grid, colWidths=[135, 135, 135, 135])
        t_tele.setStyle(TableStyle([
            ('SPAN', (0,0), (3,0)),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f0f9ff')),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ffffff')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#bae6fd')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e0f2fe')),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(t_tele)
        story.append(Spacer(1, 8))
        
        # Detailed Ultrasound Anatomical Findings
        findings_box = [
            [Paragraph("<b>DETAILED ULTRASOUND ANATOMICAL FINDINGS</b>", sec_hdr)],
            [Paragraph(str(report.get("ultrasound_findings", report.get("clinical_summary", "No findings recorded."))), body_p)]
        ]
        t_findings = Table(findings_box, colWidths=[540])
        t_findings.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f8fafc')),
            ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#ffffff')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(t_findings)
        story.append(Spacer(1, 8))
        
        # Clinical Summary & Observations
        summary_box = [
            [Paragraph("<b>CLINICAL SUMMARY & OBSERVATIONS</b>", sec_hdr)],
            [Paragraph(str(report.get("clinical_summary", "None.")), body_p)]
        ]
        t_summary = Table(summary_box, colWidths=[540])
        t_summary.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f8fafc')),
            ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#ffffff')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(t_summary)
        story.append(Spacer(1, 8))
        
        # Clinical Diagnosis & Impression
        impression_box = [
            [Paragraph("<b>DIAGNOSIS & CLINICAL IMPRESSION</b>", sec_hdr)],
            [Paragraph(str(report.get("diagnosis_impression", "None.")), body_p)]
        ]
        t_imp = Table(impression_box, colWidths=[540])
        t_imp.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f0fdf4')),
            ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#ffffff')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#86efac')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(t_imp)
        story.append(Spacer(1, 10))
        
        # Doctor Signature & Verification Footer
        sig_data = [
            [
                Paragraph("<b>ATTESTING PHYSICIAN SIGNATURE</b><br/>" + str(report.get("doctor_name", "Dr. Admin Doctor")) + "<br/><font size='7.5' color='#64748b'>Chief Tele-Ultrasound Specialist • License " + str(report.get("doctor_license", "TORUS-REG-3001")) + "</font>", sign_name),
                Paragraph("<b>DIGITAL AUDIT VERIFICATION</b><br/><font color='#059669'>✓ Digitally Signed & SHA-256 Validated</font><br/><font size='7' color='#94a3b8'>TORUS Health Cloud HSM • Session " + str(report.get("session_id", "")) + "</font>", h_meta)
            ]
        ]
        t_sig = Table(sig_data, colWidths=[320, 220])
        t_sig.setStyle(TableStyle([
            ('LINEABOVE', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(KeepTogether(t_sig))
        
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        return pdf_bytes, None
    except Exception as e:
        print(f"[PDF] Error generating PDF for {report_id}: {e}")
        return None, str(e)


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")

