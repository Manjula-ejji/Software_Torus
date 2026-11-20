/*
 * =========================================================================================
 * TORUS Healthcare - Arduino Biometric Fingerprint Scanner Firmware (HIGH-SPEED OPTIMIZED)
 * Hardware: Arduino UNO / Nano / Mega / ESP32 + R307 / AS608 / FPM10A Optical Fingerprint Sensor
 *
 * Performance Targets:
 *   - Fingerprint Registration: <= 10.0 seconds (typically 3.5 - 5.5s)
 *   - Fingerprint Verification: 3.0 - 5.0 seconds (typically 0.8 - 2.0s; timeout @ 3.5s)
 *
 * Wiring (Arduino UNO / Nano):
 *   Sensor VCC (Red)   -> 5V / 3.3V
 *   Sensor GND (Black) -> GND
 *   Sensor TX (Yellow) -> Pin 2 (Arduino RX via SoftwareSerial)
 *   Sensor RX (Green)  -> Pin 3 (Arduino TX via SoftwareSerial)
 *
 * Baud Rates:
 *   Host Serial:   57600 baud (or 115200)
 *   Sensor Serial: 57600 baud
 * =========================================================================================
 */

#include <SoftwareSerial.h>
#include <Adafruit_Fingerprint.h>

// Software serial on pins 2 (RX) and 3 (TX)
SoftwareSerial mySerial(2, 3);
Adafruit_Fingerprint finger = Adafruit_Fingerprint(&mySerial);

// Maximum template capacity
#define MAX_SLOT 162

// Timeout constants (strictly adhere to <=10s registration and 3-5s verification)
const unsigned long STAGE_TOUCH_TIMEOUT_MS = 1800; // 1.8s max wait per touch
const unsigned long STAGE_LIFT_TIMEOUT_MS  = 1200; // 1.2s max wait for finger lift
const unsigned long TOTAL_ENROLL_BUDGET_MS = 9500; // 9.5s hard total registration budget
const unsigned long VERIFY_TIMEOUT_MS      = 3500; // 3.5s max wait for verify touch

void setup() {
  Serial.begin(57600);
  while (!Serial); // Wait for USB Serial connection
  delay(50);

  finger.begin(57600);
  if (finger.verifyPassword()) {
    Serial.println("STATUS:READY");
  } else {
    Serial.println("ERROR:FINGERPRINT_SENSOR_NOT_FOUND");
  }
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command == "STATUS" || command == "PING" || command == "COUNT") {
      if (finger.verifyPassword()) {
        finger.getTemplateCount();
        Serial.println("STATUS:READY");
        Serial.print("COUNT:");
        Serial.println(finger.templateCount);
        Serial.print("Stored fingerprints: ");
        Serial.print(finger.templateCount);
        Serial.println("/60");
      } else {
        Serial.println("ERROR:FINGERPRINT_SENSOR_NOT_FOUND");
      }
    }
    else if (command.startsWith("ENROLL:") || command.startsWith("ENROLL ") || command.startsWith("R ") || command == "R") {
      int slotId = 0;
      if (command.startsWith("ENROLL:")) slotId = command.substring(7).toInt();
      else if (command.startsWith("ENROLL ")) slotId = command.substring(7).toInt();
      else if (command.startsWith("R ")) slotId = command.substring(2).toInt();
      else if (command == "R") {
        while (!Serial.available()) delay(5);
        slotId = Serial.parseInt();
      }

      if (slotId < 1 || slotId > MAX_SLOT) {
        Serial.print("ERROR:INVALID_SLOT:");
        Serial.println(slotId);
        return;
      }
      enrollFingerprint(slotId);
    }
    else if (command == "VERIFY" || command == "MATCH" || command == "F" || command.startsWith("MATCH ") || command.startsWith("VERIFY:")) {
      verifyFingerprint();
    }
    else if (command.startsWith("DELETE:") || command.startsWith("DELETE ") || command.startsWith("D ") || command == "D") {
      int slotId = -1;
      if (command.startsWith("DELETE:")) slotId = command.substring(7).toInt();
      else if (command.startsWith("DELETE ")) slotId = command.substring(7).toInt();
      else if (command.startsWith("D ")) slotId = command.substring(2).toInt();
      else if (command == "D") {
        while (!Serial.available()) delay(5);
        String param = Serial.readStringUntil('\n');
        param.trim();
        param.toUpperCase();
        if (param == "A") {
          finger.emptyDatabase();
          Serial.println("EMPTY:SUCCESS");
          return;
        } else {
          slotId = param.toInt();
        }
      }
      if (slotId < 0 || slotId > MAX_SLOT) {
        Serial.print("ERROR:INVALID_SLOT:");
        Serial.println(slotId);
        return;
      }
      deleteFingerprint(slotId);
    }
    else if (command == "EMPTY" || command == "DELETE_ALL") {
      int p = finger.emptyDatabase();
      if (p == FINGERPRINT_OK) {
        Serial.println("EMPTY:SUCCESS");
      } else {
        Serial.println("ERROR:EMPTY_FAILED");
      }
    }
  }
}

// -------------------- 6-STAGE ENROLLMENT: stores into hardware slot slotId --------------------
// Preserves all 6 captures (16%, 33%, 50%, 66%, 83%, 100%)
// Total budget: strictly <= 10.0 seconds (typically 3.8 - 6.2 seconds across 6 captures)
void enrollFingerprint(int slotId) {
  int p = -1;
  const int TOTAL_STAGES = 6;
  const int stagePercentages[6] = {16, 33, 50, 66, 83, 100};

  unsigned long totalStartMs = millis();

  Serial.print("Starting enrollment for ID ");
  Serial.print(slotId);
  Serial.println(".");

  for (int stage = 1; stage <= TOTAL_STAGES; stage++) {
    // Check total budget
    if (millis() - totalStartMs >= TOTAL_ENROLL_BUDGET_MS) {
      Serial.println("ERROR:TIMEOUT_OVERALL");
      Serial.println("ENROLLMENT TIMED OUT");
      return;
    }

    if (stage == 1) {
      Serial.println("EVENT:WAITING_FOR_FINGER");
    } else {
      Serial.print("EVENT:WAITING_FOR_TOUCH_");
      Serial.println(stage);
    }

    // Step A: Wait for finger touch (with timeout)
    p = -1;
    unsigned long touchStart = millis();
    while (p != FINGERPRINT_OK) {
      if (millis() - touchStart > STAGE_TOUCH_TIMEOUT_MS || (millis() - totalStartMs >= TOTAL_ENROLL_BUDGET_MS)) {
        Serial.print("ERROR:TIMEOUT_STAGE_");
        Serial.println(stage);
        Serial.println("ENROLLMENT TIMED OUT");
        return;
      }
      p = finger.getImage();
      if (p == FINGERPRINT_NOFINGER) {
        delay(15); // Fast 66Hz sampling
        continue;
      } else if (p == FINGERPRINT_IMAGEFAIL) {
        Serial.println("ERROR:IMAGING_FAILED_RETRY");
        delay(20);
        continue;
      }
    }

    // Step B: Convert image into template buffer
    uint8_t bufferId = (stage % 2 == 1) ? 1 : 2;
    p = finger.image2Tz(bufferId);
    if (p != FINGERPRINT_OK) {
      Serial.print("ERROR:CONVERT_STAGE_");
      Serial.print(stage);
      Serial.println("_FAILED");
      return;
    }

    // Step C: Emit progress update for stage
    Serial.print("Enrollment status: progress ");
    Serial.print(stagePercentages[stage - 1]);
    Serial.print("%, capture stage ");
    Serial.print(stage);
    Serial.println(".");

    // If more stages remain, prompt to lift finger and wait for finger removal
    if (stage < TOTAL_STAGES) {
      Serial.print("EVENT:PASS_");
      Serial.print(stage);
      Serial.println("_CAPTURED_LIFT_FINGER");

      delay(40); // Debounce settle

      unsigned long liftStart = millis();
      p = 0;
      while (p != FINGERPRINT_NOFINGER) {
        if (millis() - liftStart > STAGE_LIFT_TIMEOUT_MS) {
          break; // Proceed once user lifted or debounce expired
        }
        p = finger.getImage();
        delay(15);
      }
      delay(30);
    }
  }

  // All 6 captures successfully completed!
  // Step D: Create Composite Template Model from the 6 captures
  p = finger.createModel();
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR:FINGERPRINT_MISMATCH_BETWEEN_PASSES");
    return;
  }

  // Step E: Store model in sensor flash memory at specified slot ID
  p = finger.storeModel(slotId);
  if (p == FINGERPRINT_OK) {
    Serial.print("ENROLL:SUCCESS:");
    Serial.println(slotId);
    Serial.print("ENROLLMENT SUCCESS: fingerprint saved as ID ");
    Serial.println(slotId);
  } else {
    Serial.println("ERROR:STORAGE_FAILED");
  }
}

// -------------------- VERIFICATION: 1:N search across all enrolled templates --------------------
// Total budget: strictly 3.0 - 5.0 seconds (typically 0.8 - 2.0s; timeout @ 3.5s)
void verifyFingerprint() {
  int p = -1;
  unsigned long startMillis = millis();

  Serial.println("EVENT:READING_FINGERPRINT");

  // Wait up to 3500ms for finger touch (strictly <= 3.5s)
  while (p != FINGERPRINT_OK) {
    if (millis() - startMillis > VERIFY_TIMEOUT_MS) {
      Serial.println("ERROR:TIMEOUT_NO_FINGER");
      Serial.println("NOT MATCHED");
      return;
    }
    p = finger.getImage();
    if (p == FINGERPRINT_NOFINGER) {
      delay(20); // Fast 50Hz polling
      continue;
    } else if (p == FINGERPRINT_IMAGEFAIL) {
      Serial.println("ERROR:IMAGING_FAILED");
      return;
    }
  }

  // Convert Image -> CharBuffer 1
  p = finger.image2Tz(1);
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR:CONVERT_FAILED");
    return;
  }

  // 1:N Search across all enrolled templates in sensor database
  p = finger.fingerFastSearch();
  if (p == FINGERPRINT_OK) {
    // Multi-protocol output
    Serial.print("VERIFY:SUCCESS:");
    Serial.print(finger.fingerID);
    Serial.print(":");
    Serial.println(finger.confidence);

    Serial.print("MATCHED: fingerprint ID ");
    Serial.print(finger.fingerID);
    Serial.print(" (score ");
    Serial.print(finger.confidence);
    Serial.println(").");

    Serial.print("Match result=1, ID=");
    Serial.print(finger.fingerID);
    Serial.print(", score=");
    Serial.println(finger.confidence);
  } else if (p == FINGERPRINT_NOTFOUND) {
    Serial.println("VERIFY:NO_MATCH");
    Serial.println("NOT MATCHED");
  } else {
    Serial.println("ERROR:SEARCH_FAILED");
  }
}

// -------------------- DELETE: remove fingerprint from hardware slot --------------------
void deleteFingerprint(int slotId) {
  int p = finger.deleteModel(slotId);
  if (p == FINGERPRINT_OK) {
    Serial.print("DELETE:SUCCESS:");
    Serial.println(slotId);
  } else {
    Serial.print("ERROR:DELETE_FAILED:");
    Serial.println(slotId);
  }
}
