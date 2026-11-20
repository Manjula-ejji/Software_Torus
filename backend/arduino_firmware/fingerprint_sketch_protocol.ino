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

const unsigned long FIRST_SCAN_TIMEOUT_MS = 3500;
const unsigned long REMOVE_TIMEOUT_MS = 1500;
const unsigned long SECOND_SCAN_TIMEOUT_MS = 3000;
const unsigned long VERIFY_TIMEOUT_MS = 3500;
const unsigned long PROMPT_INTERVAL_MS = 500;

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
// REGISTER FINGERPRINT (6 STAGES)
// ════════════════════════════════════════
void registerFingerprint(uint8_t id) {
  int p = -1;
  const int TOTAL_STAGES = 6;
  const int stagePercentages[6] = {16, 33, 50, 66, 83, 100};
  const unsigned long STAGE_TIMEOUT_MS = 1800;
  const unsigned long LIFT_TIMEOUT_MS = 1200;
  const unsigned long TOTAL_MAX_MS = 9500;

  unsigned long totalStartMs = millis();
  Serial.print("Starting enrollment for ID ");
  Serial.print(id);
  Serial.println(".");

  for (int stage = 1; stage <= TOTAL_STAGES; stage++) {
    if (millis() - totalStartMs >= TOTAL_MAX_MS) {
      Serial.println("ERROR: First scan timeout");
      return;
    }

    if (stage == 1) {
      Serial.println("Place finger");
    } else {
      Serial.print("Place again to confirm (Capture ");
      Serial.print(stage);
      Serial.println("/6)");
    }

    p = -1;
    unsigned long touchStart = millis();
    while (p != FINGERPRINT_OK) {
      if (millis() - touchStart >= STAGE_TIMEOUT_MS || (millis() - totalStartMs >= TOTAL_MAX_MS)) {
        Serial.println("ERROR: First scan timeout");
        return;
      }
      p = finger.getImage();
      if (p == FINGERPRINT_NOFINGER) {
        delay(15);
        continue;
      } else if (p != FINGERPRINT_OK) {
        Serial.println("ERROR: Could not read");
        return;
      }
    }

    uint8_t bufferId = (stage % 2 == 1) ? 1 : 2;
    p = finger.image2Tz(bufferId);
    if (p != FINGERPRINT_OK) {
      Serial.println("ERROR: Bad image");
      return;
    }

    Serial.print("Enrollment status: progress ");
    Serial.print(stagePercentages[stage - 1]);
    Serial.print("%, capture stage ");
    Serial.print(stage);
    Serial.println(".");

    if (stage < TOTAL_STAGES) {
      Serial.println("Remove finger");
      delay(40);
      unsigned long liftStart = millis();
      p = 0;
      while (p != FINGERPRINT_NOFINGER) {
        if (millis() - liftStart >= LIFT_TIMEOUT_MS) {
          break;
        }
        p = finger.getImage();
        delay(15);
      }
      delay(30);
    }
  }

  // STEP: Compare and save
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
    Serial.print("ENROLLMENT SUCCESS: fingerprint saved as ID ");
    Serial.println(id);
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
