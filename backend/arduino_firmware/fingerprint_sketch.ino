/*
  Biometric Fingerprint Registration & Verification System
  Arduino Sketch - Serial Communication Protocol
  Compatible with R305 Fingerprint Sensor Module
*/

#include <Adafruit_Fingerprint.h>
#include <SoftwareSerial.h>

// Fingerprint sensor on pins 10 (RX) and 11 (TX)
SoftwareSerial mySerial(10, 11);
Adafruit_Fingerprint finger = Adafruit_Fingerprint(&mySerial);

// Global state
uint8_t id = 0;

void setup() {
  Serial.begin(115200);  // USB Serial for commands from Python
  delay(2000);           // Wait for serial to stabilize

  Serial.println("SYSTEM: Initializing fingerprint sensor...");

  // Initialize fingerprint sensor on pins 10-11 at 57600 baud
  finger.begin(57600);
  delay(500);

  if (finger.verifyPassword()) {
    Serial.println("SYSTEM: Fingerprint sensor initialized successfully");
  } else {
    Serial.println("ERROR: Could not find fingerprint sensor");
    while (1) delay(1);
  }
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.length() == 0) {
      return;
    }

    cmd.toUpperCase();

    if (cmd == "R") {
      while (!Serial.available()) {
        delay(10);
      }

      int registrationId = Serial.parseInt();

      if (registrationId <= 0 || registrationId > 162) {
        Serial.println("ERROR: Invalid ID. Must be between 1 and 162");
        return;
      }

      registerFingerprint(registrationId);
    }

    else if (cmd == "F") {
      verifyFingerprint();
    }

    else if (cmd == "D") {
      while (!Serial.available()) {
        delay(10);
      }

      String param = Serial.readStringUntil('\n');
      param.trim();
      param.toUpperCase();

      if (param == "A") {
        deleteAll();
      } else {
        uint16_t deleteId = param.toInt();
        deleteFingerprint(deleteId);
      }
    }

    else {
      Serial.print("ERROR: Unknown command: ");
      Serial.println(cmd);
    }
  }

  delay(100);
}

void registerFingerprint(uint16_t id) {
  Serial.println("Place finger");
  
  int p = -1;
  while (p != FINGERPRINT_OK) {
    p = finger.getImage();
    switch (p) {
      case FINGERPRINT_OK:
        Serial.println("Image taken");
        break;
      case FINGERPRINT_NOFINGER:
        Serial.println("Place finger");
        break;
      case FINGERPRINT_PACKETRECIEVEERR:
        Serial.println("Communication error");
        break;
      case FINGERPRINT_IMAGEFAIL:
        Serial.println("Imaging error");
        break;
      default:
        Serial.println("Unknown error");
        break;
    }
    delay(50);
  }

  // REMOVE FINGER
  p = 0;
  while (p != FINGERPRINT_NOFINGER) {
    p = finger.getImage();
  }
  Serial.println("Remove finger");

  delay(500);

  // PLACE AGAIN
  Serial.println("Place again to confirm");
  p = -1;
  while (p != FINGERPRINT_OK) {
    p = finger.getImage();
    switch (p) {
      case FINGERPRINT_OK:
        Serial.println("Image taken");
        break;
      case FINGERPRINT_NOFINGER:
        Serial.println("Place again to confirm");
        break;
      case FINGERPRINT_PACKETRECIEVEERR:
        Serial.println("Communication error");
        break;
      case FINGERPRINT_IMAGEFAIL:
        Serial.println("Imaging error");
        break;
      default:
        Serial.println("Unknown error");
        break;
    }
    delay(50);
  }

  // Create model from both images
  p = finger.createModel();
  if (p == FINGERPRINT_OK) {
    Serial.println("Prints matched!");
  } else if (p == FINGERPRINT_ENROLLMISMATCH) {
    Serial.println("Fingerprints did not match");
    return;
  } else {
    Serial.println("Unknown error");
    return;
  }

  // Store the model
  p = finger.storeModel(id);
  if (p == FINGERPRINT_OK) {
    Serial.println("Saved");
  } else if (p == FINGERPRINT_BADLOCATION) {
    Serial.println("Could not store in that location");
  } else if (p == FINGERPRINT_FLASHERR) {
    Serial.println("Error writing to flash");
  } else {
    Serial.println("Unknown error");
  }
}

void verifyFingerprint() {
  Serial.println("Place finger");

  int p = -1;
  while (p != FINGERPRINT_OK) {
    p = finger.getImage();
    if (p == FINGERPRINT_NOFINGER) {
      Serial.println("Place finger");
    }
    delay(50);
  }

  // Convert fingerprint to template
  p = finger.image2Tz(1);
  if (p != FINGERPRINT_OK) {
    Serial.println("Image conversion error");
    return;
  }

  // Search for matching template
  p = finger.fingerFastSearch();

  if (p == FINGERPRINT_OK) {
    Serial.print("Found ID #");
    Serial.println(finger.fingerID);
    Serial.println("Matched");
  } else if (p == FINGERPRINT_NOTFOUND) {
    Serial.println("Not matched");
  } else {
    Serial.println("Search error");
  }
}

void deleteAll() {
  deleteAllFingerprints();
}

void deleteFingerprint(uint16_t id) {
  int p = -1;

  p = finger.deleteModel(id);

  if (p == FINGERPRINT_OK) {
    Serial.print("Deleted ID #");
    Serial.println(id);
  } else if (p == FINGERPRINT_BADLOCATION) {
    Serial.println("No fingerprint at that location");
  } else if (p == FINGERPRINT_FLASHERR) {
    Serial.println("Error writing to flash");
  } else {
    Serial.print("Unknown error: ");
    Serial.println(p);
  }
}

void deleteAllFingerprints() {
  int p = finger.emptyDatabase();

  if (p == FINGERPRINT_OK) {
    Serial.println("Database emptied");
  } else {
    Serial.println("Could not delete database");
  }
}
