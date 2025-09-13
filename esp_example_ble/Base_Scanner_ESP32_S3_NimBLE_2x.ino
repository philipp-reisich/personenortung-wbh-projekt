// Base_Scanner_ESP32_S3_NimBLE_2x.ino
#include <NimBLEDevice.h>
#include <math.h>

static const char* TARGET_UUID = "e2c56db5-dffb-48d2-b060-d0f5a71096e0"; // match your beacon
float pathLossN = 2.2f;   // tune for your space
float alpha     = 0.3f;   // EMA smoothing
float emaDist   = NAN;

static String toLower(const String& s){ String t=s; t.toLowerCase(); return t; }

class AdvCallbacks : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* adv) override {
    if (!adv->haveManufacturerData()) return;
    std::string md = adv->getManufacturerData();
    if (md.size() < 25) return;

    const uint8_t* d = (const uint8_t*)md.data();
    // iBeacon header: 4C 00 02 15
    if (d[0]!=0x4C || d[1]!=0x00 || d[2]!=0x02 || d[3]!=0x15) return;

    // UUID (bytes 4..19)
    char uuid[37];
    snprintf(uuid, sizeof(uuid),
      "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
      d[4],d[5],d[6],d[7], d[8],d[9], d[10],d[11], d[12],d[13],
      d[14],d[15], d[16],d[17],d[18],d[19]);

    if (toLower(String(uuid)) != toLower(String(TARGET_UUID))) return;

    int8_t measuredPower = (int8_t)d[24];
    int    rssi          = adv->getRSSI();

    float distance = powf(10.0f, ((float)measuredPower - (float)rssi) / (10.0f * pathLossN));
    if (isnan(emaDist)) emaDist = distance; else emaDist = alpha*distance + (1.0f-alpha)*emaDist;

    Serial.printf("Beacon %s | RSSI=%d dBm | MP=%d | d=%.2f m | smooth=%.2f m\n",
                  uuid, rssi, measuredPower, distance, emaDist);
  }

  void onScanEnd(const NimBLEScanResults& results, int reason) override {
    Serial.printf("Scan ended (%d devices, reason=%d). Restarting...\n",
                  results.getCount(), reason);
    NimBLEDevice::getScan()->start(0, false, false);  // continuous
  }
};

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("Starting BLE scan (NimBLE 2.x)...");
  NimBLEDevice::init("S3-Scanner");

  NimBLEScan* scan = NimBLEDevice::getScan();
  scan->setScanCallbacks(new AdvCallbacks(), true); // true = library owns/deletes
  scan->setActiveScan(true);
  scan->setInterval(45);   // ms
  scan->setWindow(30);     // ms (<= interval)
  scan->start(0, false, false);
}

void loop() {
  static uint32_t t=0;
  if (millis()-t > 3000) { t=millis(); Serial.println("...scanning"); }
}
