// Client_Beacon_ESP32_WROOM32D_NimBLE.ino
#include <NimBLEDevice.h>
#include <vector>
#include <ctype.h>

static const char* BEACON_UUID = "e2c56db5-dffb-48d2-b060-d0f5a71096e0"; // same as scanner
static int8_t   measuredPower = -71;   // calibrate to avg RSSI at 1 m
static uint16_t major = 1, minor = 1;

static uint8_t hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  c = tolower(c);
  if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
  return 0;
}
static void uuidFromString(const char* s, uint8_t out[16]) {
  int j = 0; uint8_t b = 0; bool high = true;
  for (int i = 0; s[i] != '\0' && j < 16; ++i) {
    char c = s[i];
    if (c == '-') continue;
    if (high) { b = hexNibble(c) << 4; high = false; }
    else      { b |= hexNibble(c); out[j++] = b; high = true; }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("iBeacon advertising started.");
  NimBLEDevice::init("ESP32-Beacon");
  NimBLEDevice::setPower(9); // optional; can remove if your core complains

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();

  NimBLEAdvertisementData advData;
  advData.setFlags(0x04); // BR/EDR not supported

  // Build iBeacon AD structure: [len=0x1A][type=0xFF][0x4C 0x00][0x02][0x15][UUID(16)][major][minor][measuredPower]
  std::vector<uint8_t> p;
  p.reserve(2 + 1 + 1 + 16 + 2 + 2 + 1);
  p.push_back(0x1A); // length of (type + payload)
  p.push_back(0xFF); // AD type: Manufacturer Specific Data
  // Company ID (Apple) little-endian:
  p.push_back(0x4C); p.push_back(0x00);
  // iBeacon type and length:
  p.push_back(0x02); p.push_back(0x15);
  // UUID:
  uint8_t uuid[16]; uuidFromString(BEACON_UUID, uuid);
  for (int i = 0; i < 16; ++i) p.push_back(uuid[i]);
  // Major, Minor (big-endian):
  p.push_back((major >> 8) & 0xFF); p.push_back(major & 0xFF);
  p.push_back((minor >> 8) & 0xFF); p.push_back(minor & 0xFF);
  // Measured Power @1m:
  p.push_back((uint8_t)measuredPower);

  advData.addData(p.data(), p.size());     // << feed raw bytes
  adv->setAdvertisementData(advData);
  adv->start();

  Serial.println("iBeacon advertising started.");
}

void loop() { delay(1000); }
