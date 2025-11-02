/*
 * Anchor (ESP32/ESP32-C3) BLE-Scanner + MQTT Publisher (zuverlässige Scans)
 *
 * Änderungen:
 *  - Active Scan EIN (liefert mehr Felder stabiler)
 *  - 100% Duty (Intervall=Window=100 ms) für saubere Erkennung
 *  - Dedupe AUS; wir deduplizieren per adv_seq (nur neue Sequence => Publish)
 *  - Manufacturer Data jetzt mit Company ID im Wearable (0xFFFF):
 *      Offsets +2 (siehe Parser unten). Wenn Mfg fehlt/zu kurz: trotzdem publish (ohne Battery/Temp)
 *  - UID: aus Advert-Namen ("W-.."). Fallback: wenn kein Name, scan ignorieren.
 *
 * Topics:
 *   rtls/anchor/<ANCHOR_ID>/scan
 *   rtls/anchor/<ANCHOR_ID>/status (retained)
 *   rtls/events  (Emergency)
 */

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <NimBLEDevice.h>
#include <time.h>
#include <map>
#include "secrets.h"

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
uint64_t startEpochMs = 0;
uint32_t startMillis  = 0;
unsigned long lastStatus = 0;

static inline uint64_t nowEpochMs() { return startEpochMs + (millis() - startMillis); }

static void connectWiFi() {
  Serial.printf("Connecting WiFi SSID=%s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - t0 > 30000) ESP.restart();
  }
  Serial.printf("\nWiFi connected, IP=%s RSSI=%d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());

  // NTP
  configTime(0, 0, "pool.ntp.org");
  time_t now = time(nullptr);
  while (now < 1700000000) { delay(500); now = time(nullptr); }
  startEpochMs = (uint64_t)now * 1000ULL;
  startMillis = millis();
}

static bool connectMQTT() {
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setKeepAlive(60);
  mqttClient.setSocketTimeout(5);
  mqttClient.setBufferSize(1024);

  uint8_t tries = 0;
  while (!mqttClient.connected() && tries < 8) {
    Serial.printf("MQTT connect to %s:%d ...\n", MQTT_HOST, MQTT_PORT);
    if (mqttClient.connect(ANCHOR_ID)) {
      Serial.println("MQTT connected");
      return true;
    }
    Serial.printf("MQTT failed, state=%d\n", mqttClient.state());
    delay(1000);
    tries++;
  }
  return mqttClient.connected();
}

static std::map<String, uint16_t> lastSeqByUid;

class ScanCallbacks : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* d) override {
    // UID aus Name (z.B. "W-01")
    String uid;
    if (d->haveName()) {
      std::string nm = d->getName();
      if (nm.rfind("W-", 0) == 0) uid = String(nm.c_str());
    }
    if (uid.length() == 0) return; // nur unsere Wearables

    // Felder aus Manufacturer Data (mit Company ID -> +2 Offset)
    uint16_t adv_seq = 0;
    float battery_v = NAN;
    float temp_c = NAN;
    bool emergency = false;
    int8_t txp_dbm = 0;

    if (d->haveManufacturerData()) {
      std::string md = d->getManufacturerData();
      // erwartet >=14 Bytes (0..1 company_id, dann unsere Nutzdaten)
      if (md.size() >= 14) {
        const uint8_t* m = (const uint8_t*)md.data();
        // uint8_t uid0=m[2], uid1=m[3], uid2=m[4]; // optional
        adv_seq = (uint16_t)((m[5] << 8) | m[6]);
        uint16_t batt_mv = (uint16_t)((m[7] << 8) | m[8]);
        int16_t  t100    = (int16_t)((m[9] << 8) | m[10]);
        uint8_t  flags   = m[11];
        txp_dbm = (int8_t)m[12];

        battery_v = batt_mv / 1000.0f;
        temp_c = (t100 == (int16_t)0x7FFF) ? NAN : ((float)t100 / 100.0f);
        emergency = (flags & 0x01);
      }
    }

    // Dedupe: gleiche Seq (ohne Emergency) => skip
    auto it = lastSeqByUid.find(uid);
    if (it != lastSeqByUid.end() && it->second == adv_seq && !emergency) return;
    lastSeqByUid[uid] = adv_seq;

    uint64_t ts = nowEpochMs();

    // Publish Scan (auch wenn battery/temp fehlen)
    String payload = "{";
    payload += "\"ts\":" + String(ts) + ",";
    payload += "\"anchor_id\":\"" + String(ANCHOR_ID) + "\",";
    payload += "\"uid\":\"" + uid + "\",";
    payload += "\"rssi\":" + String(d->getRSSI());
    if (!isnan(battery_v)) payload += ",\"battery\":" + String(battery_v, 3);
    if (!isnan(temp_c))    payload += ",\"temp_c\":" + String(temp_c, 2);
    if (adv_seq != 0)      payload += ",\"adv_seq\":" + String(adv_seq);
    payload += ",\"tx_power_dbm\":" + String((int)txp_dbm) + ",";
    payload += "\"emergency\":" + String(emergency ? "true" : "false");
    payload += "}";

    mqttClient.publish(("rtls/anchor/" + String(ANCHOR_ID) + "/scan").c_str(), payload.c_str());

    if (emergency) {
      String ev = "{";
      ev += "\"ts\":" + String(ts) + ",";
      ev += "\"uid\":\"" + uid + "\",";
      ev += "\"type\":\"emergency_button\",";
      ev += "\"severity\":2,";
      ev += "\"details\":\"pressed=true\",";
      ev += "\"anchor_id\":\"" + String(ANCHOR_ID) + "\"}";
      mqttClient.publish("rtls/events", ev.c_str());
    }
  }
};

static void publishAnchorStatus() {
  uint64_t ts = nowEpochMs();
  long   wifi_rssi = WiFi.RSSI();
  String ip        = WiFi.localIP().toString();
  size_t heap_free = ESP.getFreeHeap();
  size_t heap_min  = ESP.getMinFreeHeap();
  uint32_t uptime_s = millis() / 1000;

  float tC = NAN;
  #ifdef temperatureRead
    tC = temperatureRead();
  #endif

  String payload = "{";
  payload += "\"ts\":" + String(ts) + ",";
  payload += "\"anchor_id\":\"" + String(ANCHOR_ID) + "\",";
  payload += "\"ip\":\"" + ip + "\",";
  payload += "\"fw\":\"" + String(FW_VERSION) + "\",";
  payload += "\"uptime_s\":" + String(uptime_s) + ",";
  payload += "\"wifi_rssi\":" + String(wifi_rssi) + ",";
  payload += "\"heap_free\":" + String(heap_free) + ",";
  payload += "\"heap_min\":" + String(heap_min) + ",";
  payload += "\"ble_scan_active\":true";
  payload += "}";

  mqttClient.publish(("rtls/anchor/" + String(ANCHOR_ID) + "/status").c_str(), payload.c_str(), true); // retained
}

void setup() {
  Serial.begin(115200);
  connectWiFi();
  connectMQTT();

  NimBLEDevice::init("");
  NimBLEScan* scan = NimBLEDevice::getScan();
  scan->setScanCallbacks(new ScanCallbacks());

  // >>> Zuverlässig scannen:
  scan->setActiveScan(true);         // Name/MD sicher sehen
  scan->setDuplicateFilter(false);   // wir deduplizieren per adv_seq
  // 100% Duty: 100 ms Window = 100 ms Interval
  scan->setInterval(160);            // 160 * 0.625ms = 100 ms
  scan->setWindow(160);              // 100 ms
  scan->start(0, false);

  publishAnchorStatus();
}

void loop() {
  if (!mqttClient.connected()) connectMQTT();
  mqttClient.loop();

  if (millis() - lastStatus >= 10000) {
    lastStatus = millis();
    publishAnchorStatus();
  }
  delay(5);
}
