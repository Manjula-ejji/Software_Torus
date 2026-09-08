/*
  ============================================
  FINGERPRINT PROTOCOL (Direct Command Mode)
  JM101B + STM32L476RG
  ============================================
  For Python Backend Integration
  
  WIRING:
    Sensor VCC  → 3.3V
    Sensor GND  → GND
    Sensor TX   → PA10
    Sensor RX   → PA9

  PROTOCOL (Python sends):
    R\n1\n     → Register finger with ID 1
    F\n        → Find/verify finger
    D\nA\n     → Delete all
    D\n1\n     → Delete ID 1

  RESPONSE (Arduino sends):
    Place finger
    Remove finger
    Place again to confirm
    Saved        (success)
    Matched      (found)
    Not matched  (not found)
  ============================================
*/

#include <Adafruit_Fingerprint.h>

HardwareSerial fpSerial(PA10, PA9);
Adafruit_Fingerprint finger = Adafruit_Fingerprint(&fpSerial);

const unsigned long FIRST_SCAN_TIMEOUT_MS = 20000;
const unsigned long REMOVE_TIMEOUT_MS = 10000;
const unsigned long SECOND_SCAN_TIMEOUT_MS = 20000;
const unsigned long VERIFY_TIMEOUT_MS = 15000;
const unsigned long PROMPT_INTERVAL_MS = 1000;

void setup() {
  Serial.begin(115200);
  delay(2000);

  // Initialize fingerprint sensor
  finger.begin(57600);
  delay(200);

  if (finger.verifyPassword()) {
    Serial.println("SYSTEM: Sensor initialized");
  } else {
    Serial.println("ERROR: Sensor not found");
    while (1) delay(1);
  }
}

void loop() {
  if (!Serial.available()) {
    delay(50);
    return;
  }

  // Read command from Python backend
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  cmd.toUpperCase();

  if (cmd.length() == 0) return;

  // ── R = Register ──────────────────────
  if (cmd == "R") {
    while (!Serial.available()) delay(10);
    String idStr = Serial.readStringUntil('\n');
    idStr.trim();
    int id = idStr.toInt();

    if (id < 0 || id > 119) {
      Serial.println("ERROR: Invalid ID");
      return;
    }

    registerFingerprint(id);
  }
  // ── F = Find/Verify ──────────────────
  else if (cmd == "F") {
    verifyFingerprint();
  }
  // ── D = Delete ────────────────────────
  else if (cmd == "D") {
    while (!Serial.available()) delay(10);
    String param = Serial.readStringUntil('\n');
    param.trim();
    param.toUpperCase();

    if (param == "A") {
      deleteAll();
    } else {
      int id = param.toInt();
      if (id >= 0 && id <= 119) {
        deleteOne(id);
      } else {
        Serial.println("ERROR: Invalid ID");
      }
    }
  }
  else {
    Serial.println("ERROR: Unknown command");
  }
}

// ════════════════════════════════════════
// REGISTER FINGERPRINT
// ════════════════════════════════════════
void registerFingerprint(uint8_t id) {
  int p = -1;
  unsigned long startMs = 0;
  unsigned long lastPromptMs = 0;

  // STEP 1: First scan
  Serial.println("Place finger");
  startMs = millis();
  lastPromptMs = startMs;

  while (p != FINGERPRINT_OK) {
    p = finger.getImage();
    if (p == FINGERPRINT_OK) {
      // Image taken, continue
    } else if (p == FINGERPRINT_NOFINGER) {
      if (millis() - lastPromptMs >= PROMPT_INTERVAL_MS) {
        Serial.println("Place finger");
        lastPromptMs = millis();
      }
      delay(50);
    } else {
      Serial.println("ERROR: Could not read");
      return;
    }

    if (millis() - startMs >= FIRST_SCAN_TIMEOUT_MS) {
      Serial.println("ERROR: First scan timeout");
      return;
    }
  }

  p = finger.image2Tz(1);
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR: Bad image");
    return;
  }

  // STEP 2: Remove finger
  p = 0;
  startMs = millis();
  Serial.println("Remove finger");
  while (p != FINGERPRINT_NOFINGER) {
    p = finger.getImage();
    if (millis() - startMs >= REMOVE_TIMEOUT_MS) {
      Serial.println("ERROR: Remove finger timeout");
      return;
    }
  }
  delay(1000);

  // STEP 3: Second scan
  p = -1;
  Serial.println("Place again to confirm");
  startMs = millis();
  lastPromptMs = startMs;

  while (p != FINGERPRINT_OK) {
    p = finger.getImage();
    if (p == FINGERPRINT_OK) {
      // Image taken, continue
    } else if (p == FINGERPRINT_NOFINGER) {
      if (millis() - lastPromptMs >= PROMPT_INTERVAL_MS) {
        Serial.println("Place again to confirm");
        lastPromptMs = millis();
      }
      delay(50);
    } else {
      Serial.println("ERROR: Could not read");
      return;
    }

    if (millis() - startMs >= SECOND_SCAN_TIMEOUT_MS) {
      Serial.println("ERROR: Second scan timeout");
      return;
    }
  }

  p = finger.image2Tz(2);
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR: Bad image");
    return;
  }

  // STEP 4: Compare and save
  p = finger.createModel();
  if (p == FINGERPRINT_ENROLLMISMATCH) {
    Serial.println("Fingerprints did not match");
    return;
  } else if (p != FINGERPRINT_OK) {
    Serial.println("ERROR: Comparison failed");
    return;
  }

  p = finger.storeModel(id);
  if (p == FINGERPRINT_OK) {
    Serial.println("Saved");
  } else {
    Serial.println("ERROR: Could not save");
  }
}

// ════════════════════════════════════════
// VERIFY FINGERPRINT
// ════════════════════════════════════════
void verifyFingerprint() {
  int p = -1;
  unsigned long startMs = millis();
  unsigned long lastPromptMs = startMs;

  Serial.println("Place finger");

  while (p != FINGERPRINT_OK) {
    p = finger.getImage();
    if (p == FINGERPRINT_OK) {
      // Image taken
    } else if (p == FINGERPRINT_NOFINGER) {
      if (millis() - lastPromptMs >= PROMPT_INTERVAL_MS) {
        Serial.println("Place finger");
        lastPromptMs = millis();
      }
      delay(50);
    } else {
      Serial.println("ERROR: Read error");
      return;
    }

    if (millis() - startMs >= VERIFY_TIMEOUT_MS) {
      Serial.println("ERROR: Verify timeout");
      return;
    }
  }

  p = finger.image2Tz();
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR: Bad image");
    return;
  }

  p = finger.fingerFastSearch();

  if (p == FINGERPRINT_OK) {
    Serial.print("Matched ID ");
    Serial.println(finger.fingerID);
  } else if (p == FINGERPRINT_NOTFOUND) {
    Serial.println("Not matched");
  } else {
    Serial.println("ERROR: Search failed");
  }
}

// ════════════════════════════════════════
// DELETE ALL FINGERPRINTS
// ════════════════════════════════════════
void deleteAll() {
  uint8_t p = finger.emptyDatabase();

  if (p == FINGERPRINT_OK) {
    Serial.println("Database cleared");
  } else {
    Serial.println("ERROR: Could not clear");
  }
}

// ════════════════════════════════════════
// DELETE ONE FINGERPRINT
// ════════════════════════════════════════
void deleteOne(uint8_t id) {
  uint8_t p = finger.deleteModel(id);

  if (p == FINGERPRINT_OK) {
    Serial.print("Deleted ID ");
    Serial.println(id);
  } else if (p == FINGERPRINT_BADLOCATION) {
    Serial.println("ERROR: ID not found");
  } else {
    Serial.println("ERROR: Delete failed");
  }
}
