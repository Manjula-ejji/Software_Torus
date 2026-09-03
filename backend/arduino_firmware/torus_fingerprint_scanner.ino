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
 *   Host -> Arduino:  "ENROLL:<doctor_id>\n" => Multi-pass hardware enrollment & template creation
 *   Host -> Arduino:  "VERIFY\n"            => Hardware scan & 1:N / 1:1 biometric template match
 * =========================================================================================
 */

#include <SoftwareSerial.h>
#include <Adafruit_Fingerprint.h>

// Software serial on pins 2 (RX) and 3 (TX)
SoftwareSerial mySerial(2, 3);
Adafruit_Fingerprint finger = Adafruit_Fingerprint(&mySerial);

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
      if (finger.verifyPassword()) {
        Serial.println("STATUS:READY");
      } else {
        Serial.println("ERROR:FINGERPRINT_SENSOR_NOT_FOUND");
      }
    }
    else if (command.startsWith("ENROLL:")) {
      String doctorId = command.substring(7);
      doctorId.trim();
      enrollFingerprint(doctorId);
    }
    else if (command == "VERIFY") {
      verifyFingerprint();
    }
  }
}

// -------------------- REAL ENROLLMENT HANDLER --------------------
void enrollFingerprint(String doctorId) {
  int id = 1; // Primary hardware slot or dynamic slot
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

  // Convert Pass 1 Image
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

  // Convert Pass 2 Image
  p = finger.image2Tz(2);
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR:CONVERT_PASS_2_FAILED");
    return;
  }

  // Create Model / Biometric Template
  p = finger.createModel();
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR:FINGERPRINT_MISMATCH_BETWEEN_PASSES");
    return;
  }

  // Store in sensor flash memory
  p = finger.storeModel(id);
  if (p == FINGERPRINT_OK) {
    Serial.print("ENROLL:SUCCESS:");
    Serial.println(doctorId);
  } else {
    Serial.println("ERROR:STORAGE_FAILED");
  }
}

// -------------------- REAL VERIFICATION HANDLER --------------------
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

  // Convert Image
  p = finger.image2Tz(1);
  if (p != FINGERPRINT_OK) {
    Serial.println("ERROR:CONVERT_FAILED");
    return;
  }

  // Search in Sensor Database
  p = finger.fingerFastSearch();
  if (p == FINGERPRINT_OK) {
    Serial.print("VERIFY:SUCCESS:");
    Serial.print(finger.fingerID);
    Serial.print(":CONFIDENCE:");
    Serial.println(finger.confidence);
  } else if (p == FINGERPRINT_NOTFOUND) {
    Serial.println("VERIFY:NO_MATCH");
  } else {
    Serial.println("ERROR:SEARCH_FAILED");
  }
}
