/*
 * =========================================================================================
 * TORUS Healthcare - Arduino Biometric Fingerprint Scanner Firmware
 * Hardware: Arduino UNO / Nano / Mega / ESP32 + R307 / AS608 / FPM10A Optical Fingerprint Sensor
 *
 * Wiring (Arduino UNO / Nano):
 *   Sensor VCC (Red)   -> 5V / 3.3V
 *   Sensor GND (Black) -> GND
 *   Sensor TX (Yellow) -> Pin 2 (Arduino RX via SoftwareSerial)
 *   Sensor RX (Green)  -> Pin 3 (Arduino TX via SoftwareSerial)
 *
 * Protocol over USB Serial (Baud Rate: 57600):
 *   Host -> Arduino:  "STATUS\n"           => Arduino -> Host: "STATUS:READY\n"
 *   Host -> Arduino:  "ENROLL:<slot_id>\n" => Multi-pass hardware enrollment into slot <slot_id>
 *                                             slot_id is an integer 1-162 (maps to R1-R20 logically)
 *   Host -> Arduino:  "VERIFY\n"           => 1:N search across all enrolled templates
 *                                             Returns: VERIFY:SUCCESS:<fingerID>:<confidence>
 *                                             or       VERIFY:NO_MATCH
 *   Host -> Arduino:  "DELETE:<slot_id>\n" => Delete fingerprint from hardware slot <slot_id>
 *   Host -> Arduino:  "COUNT\n"            => Returns: COUNT:<n> (number of enrolled templates)
 *
 * Enrollment events (Arduino -> Host during ENROLL):
 *   EVENT:WAITING_FOR_FINGER         (ready for scan 1)
 *   EVENT:PASS_1_CAPTURED_LIFT_FINGER (scan 1 done, lift finger)
 *   EVENT:WAITING_FOR_SECOND_TOUCH   (ready for scan 2)
 *   ENROLL:SUCCESS:<slot_id>         (both scans matched, stored)
 *   ERROR:IMAGING_FAILED
 *   ERROR:CONVERT_PASS_1_FAILED
 *   ERROR:CONVERT_PASS_2_FAILED
 *   ERROR:FINGERPRINT_MISMATCH_BETWEEN_PASSES
 *   ERROR:STORAGE_FAILED
 *   ERROR:INVALID_SLOT               (slot_id out of range or bad)
 * =========================================================================================
 */

#include <SoftwareSerial.h>
#include <Adafruit_Fingerprint.h>

// Software serial on pins 2 (RX) and 3 (TX)
SoftwareSerial mySerial(2, 3);
Adafruit_Fingerprint finger = Adafruit_Fingerprint(&mySerial);

// R307 / AS608 maximum template capacity
#define MAX_SLOT 162

void setup() {
  Serial.begin(57600);
  while (!Serial); // Wait for USB Serial connection
  delay(100);

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

    if (command == "STATUS" || command == "PING") {
      // Report hardware readiness
      if (finger.verifyPassword()) {
        Serial.println("STATUS:READY");
      } else {
        Serial.println("ERROR:FINGERPRINT_SENSOR_NOT_FOUND");
      }
    }
    else if (command.startsWith("ENROLL:")) {
      // Extract slot_id from command: ENROLL:<slot_id>
      String slotStr = command.substring(7);
      slotStr.trim();
      int slotId = slotStr.toInt();

      if (slotId < 1 || slotId > MAX_SLOT) {
        Serial.print("ERROR:INVALID_SLOT:");
        Serial.println(slotId);
        return;
      }
      enrollFingerprint(slotId);
    }
    else if (command == "VERIFY") {
      verifyFingerprint();
    }
    else if (command.startsWith("DELETE:")) {
      // Extract slot_id from command: DELETE:<slot_id>
      String slotStr = command.substring(7);
      slotStr.trim();
      int slotId = slotStr.toInt();
      if (slotId < 1 || slotId > MAX_SLOT) {
        Serial.print("ERROR:INVALID_SLOT:");
        Serial.println(slotId);
        return;
      }
      deleteFingerprint(slotId);
    }
    else if (command == "COUNT") {
      // Return number of enrolled templates
      finger.getTemplateCount();
      Serial.print("COUNT:");
      Serial.println(finger.templateCount);
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

// -------------------- ENROLLMENT: stores into hardware slot slotId --------------------
void enrollFingerprint(int slotId) {
  int p = -1;

  Serial.println("EVENT:WAITING_FOR_FINGER");

  // Pass 1: Wait until finger is placed
  while (p != FINGERPRINT_OK) {
    p = finger.getImage();
    if (p == FINGERPRINT_NOFINGER) {
      delay(50);
      continue;
    } else if (p == FINGERPRINT_IMAGEFAIL) {
      Serial.println("ERROR:IMAGING_FAILED");
      return;
    }
  }

  // Convert Pass 1 Image → CharBuffer 1
  p = finger.image2Tz(1);
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR:CONVERT_PASS_1_FAILED");
    return;
  }
  Serial.println("EVENT:PASS_1_CAPTURED_LIFT_FINGER");
  delay(1000);

  // Wait for user to lift finger
  p = 0;
  while (p != FINGERPRINT_NOFINGER) {
    p = finger.getImage();
    delay(50);
  }

  Serial.println("EVENT:WAITING_FOR_SECOND_TOUCH");

  // Pass 2: Wait until finger is placed again
  p = -1;
  while (p != FINGERPRINT_OK) {
    p = finger.getImage();
    if (p == FINGERPRINT_NOFINGER) {
      delay(50);
      continue;
    } else if (p == FINGERPRINT_IMAGEFAIL) {
      Serial.println("ERROR:IMAGING_FAILED");
      return;
    }
  }

  // Convert Pass 2 Image → CharBuffer 2
  p = finger.image2Tz(2);
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR:CONVERT_PASS_2_FAILED");
    return;
  }

  // Create Model / Biometric Template (merges CharBuffer 1 + 2)
  p = finger.createModel();
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR:FINGERPRINT_MISMATCH_BETWEEN_PASSES");
    return;
  }

  // Store model in sensor flash memory at the specified slot ID
  p = finger.storeModel(slotId);
  if (p == FINGERPRINT_OK) {
    Serial.print("ENROLL:SUCCESS:");
    Serial.println(slotId);
  } else {
    Serial.println("ERROR:STORAGE_FAILED");
  }
}

// -------------------- VERIFICATION: 1:N search across all enrolled templates --------------------
void verifyFingerprint() {
  int p = -1;
  unsigned long startMillis = millis();

  Serial.println("EVENT:READING_FINGERPRINT");

  // Wait up to 15 seconds for a finger
  while (p != FINGERPRINT_OK) {
    if (millis() - startMillis > 15000) {
      Serial.println("ERROR:TIMEOUT_NO_FINGER");
      return;
    }
    p = finger.getImage();
    if (p == FINGERPRINT_NOFINGER) {
      delay(50);
      continue;
    } else if (p == FINGERPRINT_IMAGEFAIL) {
      Serial.println("ERROR:IMAGING_FAILED");
      return;
    }
  }

  // Convert Image → CharBuffer 1
  p = finger.image2Tz(1);
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR:CONVERT_FAILED");
    return;
  }

  // 1:N Search across all enrolled templates in sensor database
  p = finger.fingerFastSearch();
  if (p == FINGERPRINT_OK) {
    // Report matched slot ID and confidence score
    Serial.print("VERIFY:SUCCESS:");
    Serial.print(finger.fingerID);
    Serial.print(":");
    Serial.println(finger.confidence);
  } else if (p == FINGERPRINT_NOTFOUND) {
    Serial.println("VERIFY:NO_MATCH");
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
