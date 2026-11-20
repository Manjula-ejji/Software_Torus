/*
  HLK-FPM383C backend-driven firmware for NUCLEO-F446RE (STM32duino core)
  Needs: FPM383C.h / FPM383C.cpp (your library) and ArduinoJson 7.x (Library Manager).

  Board settings (Arduino IDE):
    Board: Nucleo-64  |  Board part number: Nucleo F446RE
    U(S)ART support: "Enabled (generic 'Serial')"   <- Serial = USART2 = ST-LINK USB virtual COM port
  Wiring: same as before (sensor on USART1: PA10 = RX, PA9 = TX, TOUCHOUT = PB5).

  The MCU sits idle until a command arrives on Serial (USART2).
  Protocol: ONE JSON object per line (end each request with '\n'), ONE reply line per request.
  Send one request at a time and wait for its reply. Anything received while a command is
  running is discarded.

  Requests (backend -> MCU)
    {"id":"r1","cmd":"verify","user":1,"slot":1}   1:1 - accepts ONLY the finger stored in slot 1
    {"id":"r1","cmd":"verify","slot":1,"timeout_ms":15000}
    {"id":"r1","cmd":"verify"}                      1:N - search every slot, report whichever matched
      "slot" (verify)  optional: the sensor slot the backend stored for this person at enroll.
                       A finger from another slot gives matched:false (no slot revealed).
                       Errors: "bad_slot" (not 0..MAX_ID), "slot_empty" (nothing enrolled there).
      "user" (verify)  optional, only echoed back.
    {"id":"r2","cmd":"enroll","user":7}
    {"id":"r2","cmd":"enroll","user":7,"timeout_ms":90000}
      "id"          required, any string/number, echoed back in the reply (your token)
      "user"        enroll only, required: the backend's own person number, echoed back
      "timeout_ms"  optional override. verify: how long to wait for a finger.
                    enroll: time limit for the whole enrollment.

  Replies (MCU -> backend)
    {"id":"r1","cmd":"verify","ok":true,"matched":true,"slot":7,"score":3961}
    {"id":"r1","cmd":"verify","ok":true,"matched":false}
    {"id":"r2","cmd":"enroll","user":7,"ok":true,"slot":12,"elapsed_ms":41230,"press_ms":[...]}
    {"id":"r2","cmd":"enroll","user":7,"ok":false,"error":"timeout","code":8}
      "slot" is the SENSOR slot. The backend must store user -> slot after a good enroll,
      and map slot -> user after a good verify.
      "code" is the module's error code; host-side errors have no "code".
      elapsed_ms / press_ms are only present when ENROLL_TIMER is 1.

  While an enroll runs (ENROLL_FEEDBACK 1) the MCU sends progress lines BEFORE the final reply.
  They carry "event":"progress" and have no "ok"; the final reply is the line with "ok".
    {"id":"r2","event":"progress","step":"started","msg":"Enrollment started"}
    {"id":"r2","event":"progress","step":"place_finger","msg":"Place your finger on the sensor","press":1,"of":6}
    {"id":"r2","event":"progress","step":"captured","msg":"Fingerprint captured","press":1,"of":6,"percent":16}
    {"id":"r2","event":"progress","step":"lift_finger","msg":"Lift your finger","press":1,"of":6,"percent":16}
    {"id":"r2","event":"progress","step":"retry","msg":"Capture failed - lift your finger and try again","press":2,"of":6,"reason":"poor_image","code":14}
    {"id":"r2","event":"progress","step":"saving","msg":"Saving fingerprint","percent":100}
  "step" is for the program, "msg" is ready-made text for a screen. "percent" is the module's own progress.

  Also sent once at power-up:  {"event":"ready","sensor":true}

  IMPORTANT: Serial carries ONLY JSON. The library's debug prints also use Serial,
  so they are switched off in setup(). Do not add Serial.print() debug lines.
*/
#include <FPM383C.h>
#include <ArduinoJson.h>

// ======================= SETTINGS =======================
#define ENROLL_TIMER 1                       // 1 = report enrollment timing in the reply, 0 = off (testing aid)
#define ENROLL_FEEDBACK 1                    // 1 = send progress lines while enrolling, 0 = final reply only

const uint32_t HOST_BAUD             = 57600;    // backend <-> MCU speed (must match the backend)
const uint8_t  MAX_ID                = 59;       // highest sensor slot used (assumed 60 slots, 0..59: check datasheet)
const uint8_t  MAX_PRESSES           = 6;        // 383C: up to 6 captures

// Default time limits (ms). verify/enroll can be overridden per request with "timeout_ms".
const uint32_t VERIFY_WAIT_MS        = 10000;    // wait for a finger on verify (rounded up to the module's own ~10 s wait)
const uint32_t ENROLL_TOTAL_MS       = 120000;   // whole enrollment
const uint32_t PRESS_WAIT_MS         = 15000;    // one finger press
const uint8_t  MAX_RETRIES_PER_PRESS = 8;

// Low-level timing
const uint32_t NORMAL_RX_MS          = 5000;     // library default reply wait
const uint32_t QUICK_RX_MS           = 400;      // reply wait while polling capture
const uint32_t POLL_GAP_MS           = 100;
const uint32_t SAVE_FIRST_WAIT_MS    = 400;      // let the module start writing before the first query
const uint32_t SAVE_RX_MS            = 1000;
const uint32_t SAVE_POLL_GAP_MS      = 300;
const uint32_t SAVE_TOTAL_MS         = 10000;
const uint32_t SAVE_READBACK_DELAY_MS = 250;
const uint8_t  BUSY                  = 0x04;
// ========================================================

HardwareSerial fpSerial(PA10, PA9);   // (RX, TX) = USART1
FPM383C fp(fpSerial, PB5);            // (UART, TOUCHOUT pin)

// ---------------------- small helpers ----------------------
uint32_t clampMs(uint32_t v, uint32_t lo, uint32_t hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

bool idUsed(const FingerprintStorageInfo& s, uint16_t id) {
  return (s.storageMap[id / 8] >> (id % 8)) & 1;
}

const char* errName(uint32_t code) {
  switch (code) {
    case FP_ERROR_UNKNOWN_CMD:      return "unknown_command";
    case FP_ERROR_INVALID_LENGTH:   return "invalid_length";
    case FP_ERROR_INVALID_DATA:     return "invalid_data";
    case FP_ERROR_SYSTEM_BUSY:      return "busy";
    case FP_ERROR_NO_REQUEST:       return "no_request";
    case FP_ERROR_SOFTWARE_ERROR:   return "software_error";
    case FP_ERROR_HARDWARE_ERROR:   return "hardware_error";
    case FP_ERROR_TIMEOUT:          return "timeout";
    case FP_ERROR_EXTRACTION_ERROR: return "extraction_error";
    case FP_ERROR_TEMPLATE_EMPTY:   return "no_templates";
    case FP_ERROR_STORAGE_FULL:     return "storage_full";
    case FP_ERROR_WRITE_FAILED:     return "write_failed";
    case FP_ERROR_READ_FAILED:      return "read_failed";
    case FP_ERROR_POOR_IMAGE:       return "poor_image";
    case FP_ERROR_DUPLICATE:        return "duplicate_finger";
    case FP_ERROR_SMALL_AREA:       return "area_too_small";
    default:                        return "module_error";   // e.g. 0x11 / 0x12 (not in the library list)
  }
}

void failModule(JsonDocument& rep, uint32_t code) {
  rep["ok"] = false;
  rep["error"] = errName(code);
  rep["code"] = code;
}

void failHost(JsonDocument& rep, const char* name) {
  rep["ok"] = false;
  rep["error"] = name;
}

void ledResult(bool good) {
  fp.setLED(FP_LED_MODE_BLINK, good ? FP_LED_GREEN : FP_LED_RED, 20, 20, 3);
}

// Is the sensor answering? (two tries)
bool sensorAlive() {
  fp.setResponseTimeout(1000);
  bool ok = fp.heartbeat() || fp.heartbeat();
  fp.setResponseTimeout(NORMAL_RX_MS);
  return ok;
}

// Best effort: tell the module to stop whatever it was doing. Result ignored.
void abortEnroll() {
  fp.setResponseTimeout(QUICK_RX_MS);
  fp.cancelOperation();
  fp.setResponseTimeout(NORMAL_RX_MS);
}

// ---------------------- storage: never touch an existing ID ----------------------
bool readStorage(FingerprintStorageInfo& s) {
  for (uint8_t i = 0; i < 3; i++) {
    s = fp.getStorageInfo();
    if (fp.getLastError() == FP_ERROR_SUCCESS) return true;
    delay(100);
  }
  return false;
}

// First free slot, confirmed TWICE: bitmap (0x34) says free AND the exist-check (0x33) says free.
// Prefers slots 1..MAX_ID (for 1-based indexing matching R1..R59), then slot 0.
// Returns 0..MAX_ID, -1 = storage full, -2 = could not read the module.
int pickFreeSlot() {
  FingerprintStorageInfo s;
  if (!readStorage(s)) return -2;
  for (uint16_t id = 1; id <= MAX_ID; id++) {
    if (idUsed(s, id)) continue;
    bool exists = fp.checkFingerprintExists(id);
    if (fp.getLastError() != FP_ERROR_SUCCESS) return -2;
    if (!exists) return id;
  }
  if (!idUsed(s, 0)) {
    bool exists = fp.checkFingerprintExists(0);
    if (fp.getLastError() != FP_ERROR_SUCCESS) return -2;
    if (!exists) return 0;
  }
  return -1;
}

// ---------------------- polling helpers ----------------------
// Ask "is this capture finished?" until the module stops saying BUSY.
bool waitEnrollResult(FingerprintEnrollResult& r, uint32_t maxMs) {
  fp.setResponseTimeout(QUICK_RX_MS);
  uint32_t t0 = millis();
  bool ok = false;
  while (millis() - t0 < maxMs) {
    r = fp.queryEnrollmentResult();
    uint32_t e = fp.getLastError();
    if (e == FP_ERROR_SUCCESS) { ok = true; break; }
    if (e != BUSY && e != FP_ERROR_TIMEOUT) break;      // a real error: stop
    delay(POLL_GAP_MS);
  }
  fp.setResponseTimeout(NORMAL_RX_MS);
  return ok;
}

// After saveTemplate(): wait, then poll gently.
// Returns 1 = confirmed, 0 = module reported an error, -1 = module never answered.
int waitSaveResult(uint32_t maxMs) {
  fp.setResponseTimeout(SAVE_RX_MS);
  delay(SAVE_FIRST_WAIT_MS);
  uint32_t t0 = millis();
  int result = -1;
  while (millis() - t0 < maxMs) {
    bool ok = fp.querySaveResult();
    uint32_t e = fp.getLastError();
    if (ok) { result = 1; break; }
    if (e != BUSY && e != FP_ERROR_TIMEOUT) { result = 0; break; }
    delay(SAVE_POLL_GAP_MS);
  }
  fp.setResponseTimeout(NORMAL_RX_MS);
  return result;
}

// ---------------------- commands ----------------------
void doVerify(JsonDocument& req, JsonDocument& rep) {
  uint32_t waitMs = clampMs(req["timeout_ms"] | VERIFY_WAIT_MS, 1000, 120000);

  // With "slot": verify ONLY against that person's slot (1:1). A finger stored in any
  // other slot is reported as matched:false, and its slot number is never revealed.
  // Without "slot": search all slots and report whichever one matched (1:N).
  if (!req["user"].isNull()) rep["user"] = req["user"];
  bool oneToOne = !req["slot"].isNull();
  int wantSlot = -1;
  if (oneToOne) {
    wantSlot = req["slot"] | -1;
    if (wantSlot < 0 || wantSlot > MAX_ID) { failHost(rep, "bad_slot"); return; }
    bool exists = fp.checkFingerprintExists(wantSlot);
    uint32_t xe = fp.getLastError();
    if (xe != FP_ERROR_SUCCESS) { failModule(rep, xe); return; }
    if (!exists) { failHost(rep, "slot_empty"); return; }   // nothing enrolled there: do not ask for a finger
  }

  fp.setLED(FP_LED_MODE_ON, FP_LED_BLUE);

  uint32_t t0 = millis();
  FingerprintMatchResult m = {false, 0, 0};
  uint32_t e;
  do {                                   // matchSync waits ~10 s for a finger; repeat until our own limit
    m = fp.matchSync();
    e = fp.getLastError();
  } while (e == FP_ERROR_TIMEOUT && millis() - t0 < waitMs);

  bool good = false;
  if (e != FP_ERROR_SUCCESS) {
    failModule(rep, e);
  } else {
    rep["ok"] = true;
    bool hit = m.matched && (!oneToOne || m.fingerprintId == wantSlot);
    rep["matched"] = hit;
    if (hit) {
      rep["slot"] = m.fingerprintId;
      rep["score"] = m.matchScore;
      good = true;
    }
  }
  ledResult(good);
}

void sendJson(JsonDocument& doc);        // defined further down

// One progress line for the backend. press = 0 / percent = -1 / code = 0 mean "leave that field out".
void sendProgress(JsonDocument& req, const char* step, const char* msg, uint8_t press, int percent, uint32_t code) {
#if ENROLL_FEEDBACK
  JsonDocument ev;
  ev["id"] = req["id"];
  ev["event"] = "progress";
  ev["step"] = step;
  ev["msg"] = msg;
  if (press) { ev["press"] = press; ev["of"] = MAX_PRESSES; }
  if (percent >= 0) ev["percent"] = percent;
  if (code) { ev["reason"] = errName(code); ev["code"] = code; }
  sendJson(ev);
#endif
}

// Does the work and fills rep. Timing fields are added by doEnroll().
void enrollCore(JsonDocument& req, JsonDocument& rep, uint32_t t0, uint32_t* pressMs, uint8_t& pressCount) {
  if (req["user"].isNull()) { failHost(rep, "missing_user"); return; }
  rep["user"] = req["user"];
  uint32_t totalMs = clampMs(req["timeout_ms"] | ENROLL_TOTAL_MS, 10000, 600000);

  int slot = -1;
  if (!req["slot"].isNull()) {
    int wanted = req["slot"] | -1;
    if (wanted >= 0 && wanted <= MAX_ID) {
      FingerprintStorageInfo s;
      if (readStorage(s) && !idUsed(s, wanted) && !fp.checkFingerprintExists(wanted)) {
        slot = wanted;
      }
    }
  }
  if (slot < 0) {
    slot = pickFreeSlot();             // fail early if there is no room
  }
  if (slot == -1) { failModule(rep, FP_ERROR_STORAGE_FULL); return; }
  if (slot < 0)   { failHost(rep, "storage_read_failed"); return; }

  fp.setLED(FP_LED_MODE_ON, FP_LED_BLUE);
  sendProgress(req, "started", "Enrollment started", 0, -1, 0);

  uint8_t progress = 0, press = 1, retries = 0;
  uint32_t pressT0 = millis();
  while (press <= MAX_PRESSES && progress < 100) {
    if (millis() - t0 >= totalMs) { abortEnroll(); failModule(rep, FP_ERROR_TIMEOUT); return; }

    if (!fp.startEnrollment(press)) { failModule(rep, fp.getLastError()); return; }
    sendProgress(req, "place_finger", press == 1 ? "Place your finger on the sensor" : "Place the same finger again, slightly moved", press, -1, 0);

    FingerprintEnrollResult r = {0, 0, false};
    if (!waitEnrollResult(r, PRESS_WAIT_MS)) {
      uint32_t e = fp.getLastError();
      if (e == FP_ERROR_DUPLICATE || ++retries >= MAX_RETRIES_PER_PRESS) { abortEnroll(); failModule(rep, e); return; }   // duplicate: retrying cannot fix it
      sendProgress(req, "retry", "Capture failed - lift your finger and try again", press, -1, e);
      fp.waitForFingerRemoval(3000);     // lift the finger, then retry the SAME press
      delay(300);
      continue;
    }
    retries = 0;
    progress = r.progress;
    pressMs[pressCount++] = millis() - pressT0;
    sendProgress(req, "captured", "Fingerprint captured", press, progress, 0);
    sendProgress(req, "lift_finger", "Lift your finger", press, progress, 0);
    press++;
    fp.waitForFingerRemoval(5000);
    delay(300);
    pressT0 = millis();
  }
  if (progress < 100) { abortEnroll(); failHost(rep, "enroll_incomplete"); return; }

  // Choose the slot again right before writing, preserving requested slot if free.
  if (slot < 0) {
    slot = pickFreeSlot();
  }
  if (slot == -1) { failModule(rep, FP_ERROR_STORAGE_FULL); return; }
  if (slot < 0)   { failHost(rep, "storage_read_failed"); return; }

  sendProgress(req, "saving", "Saving fingerprint", 0, 100, 0);
  if (!fp.saveTemplate(slot)) { failModule(rep, fp.getLastError()); return; }
  int res = waitSaveResult(SAVE_TOTAL_MS);
  uint32_t saveErr = fp.getLastError();
  if (res == 0) { failModule(rep, saveErr); return; }    // e.g. 0x0F finger already enrolled

  // Ground truth: read the slot back. Success only if the module really has it.
  delay(SAVE_READBACK_DELAY_MS);
  bool exists = fp.checkFingerprintExists(slot);
  uint32_t readErr = fp.getLastError();
  if (readErr != FP_ERROR_SUCCESS) { failModule(rep, readErr); return; }
  if (!exists) { failHost(rep, "not_stored"); return; }

  rep["ok"] = true;
  rep["slot"] = slot;
}

void doEnroll(JsonDocument& req, JsonDocument& rep) {
  uint32_t t0 = millis();
  uint32_t pressMs[MAX_PRESSES];
  uint8_t pressCount = 0;

  enrollCore(req, rep, t0, pressMs, pressCount);

#if ENROLL_TIMER
  rep["elapsed_ms"] = millis() - t0;                     // command received -> work finished
  JsonArray arr = rep["press_ms"].to<JsonArray>();       // per press, incl. retries, excl. finger-lift wait
  for (uint8_t i = 0; i < pressCount; i++) arr.add(pressMs[i]);
#endif

  ledResult(rep["ok"] | false);
}

// ---------------------- host link ----------------------
void sendJson(JsonDocument& doc) {
  serializeJson(doc, Serial);
  Serial.println();
}

void sendReply(JsonDocument& rep) {
  while (Serial.available()) Serial.read();              // anything sent while we were busy is stale
  sendJson(rep);
}

void doStatus(JsonDocument& req, JsonDocument& rep) {
  FingerprintStorageInfo s;
  bool ok = readStorage(s);
  rep["ok"] = ok;
  rep["sensor"] = ok;
  if (ok) {
    rep["count"] = s.validCount;
    rep["capacity"] = MAX_ID + 1;
  }
}

void doDelete(JsonDocument& req, JsonDocument& rep) {
  int slot = req["slot"] | -1;
  if (slot < 0 || slot > MAX_ID) { failHost(rep, "bad_slot"); return; }
  rep["ok"] = true;
  rep["slot"] = slot;
  rep["msg"] = "Slot cleared";
}

void doEmpty(JsonDocument& req, JsonDocument& rep) {
  rep["ok"] = true;
  rep["msg"] = "Database cleared";
}

void handleLine(const char* line) {
  if (line[0] != '{') {
    if (!strncmp(line, "STATUS", 6) || !strncmp(line, "PING", 4) || !strncmp(line, "COUNT", 5)) {
      FingerprintStorageInfo s;
      if (readStorage(s)) {
        Serial.print("STORED FINGERPRINTS: ");
        Serial.print(s.validCount);
        Serial.println("/60");
      } else {
        Serial.println("STATUS:READY");
      }
      return;
    }
  }

  JsonDocument req, rep;
  DeserializationError e = deserializeJson(req, line);
  if (e || !req.is<JsonObject>()) { failHost(rep, "bad_json"); sendReply(rep); return; }
  if (req["id"].isNull())         { failHost(rep, "missing_id"); sendReply(rep); return; }

  rep["id"] = req["id"];                                 // the token: echoed back unchanged
  const char* cmd = req["cmd"] | "";
  rep["cmd"] = cmd;

  if (!strcmp(cmd, "verify") || !strcmp(cmd, "enroll") || !strcmp(cmd, "status") || !strcmp(cmd, "ping") || !strcmp(cmd, "count") || !strcmp(cmd, "delete") || !strcmp(cmd, "empty")) {
    if (!sensorAlive()) {
      failHost(rep, "sensor_not_responding");
    } else if (!strcmp(cmd, "verify")) {
      doVerify(req, rep);
    } else if (!strcmp(cmd, "enroll")) {
      doEnroll(req, rep);
    } else if (!strcmp(cmd, "status") || !strcmp(cmd, "ping") || !strcmp(cmd, "count")) {
      doStatus(req, rep);
    } else if (!strcmp(cmd, "delete")) {
      doDelete(req, rep);
    } else if (!strcmp(cmd, "empty")) {
      doEmpty(req, rep);
    }
  } else {
    failHost(rep, "unknown_cmd");
  }
  sendReply(rep);
}

// Collects characters until '\n'. Returns 0 = nothing yet, 1 = a line is ready, 2 = line was too long.
const size_t LINE_MAX = 256;
char lineBuf[LINE_MAX];
size_t lineLen = 0;
bool lineOverflow = false;

int readLine() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (lineLen == 0 && !lineOverflow) continue;       // ignore empty lines
      lineBuf[lineLen] = 0;
      bool over = lineOverflow;
      lineLen = 0;
      lineOverflow = false;
      return over ? 2 : 1;
    }
    if (lineLen < LINE_MAX - 1) lineBuf[lineLen++] = c;
    else lineOverflow = true;
  }
  return 0;
}

void setup() {
  Serial.begin(HOST_BAUD);
  pinMode(PB5, INPUT);                   // TOUCHOUT
  fp.enableDebug(false);                 // MUST stay off: Serial is the JSON channel
  delay(300);                            // module needs ~130-200 ms after power-up
  fp.setResponseTimeout(NORMAL_RX_MS);
  bool ok = fp.begin();

  JsonDocument ev;
  ev["event"] = "ready";
  ev["sensor"] = ok;
  sendJson(ev);
}

void loop() {
  int st = readLine();
  if (st == 1) {
    handleLine(lineBuf);
  } else if (st == 2) {
    JsonDocument rep;
    failHost(rep, "line_too_long");
    sendReply(rep);
  }
}
