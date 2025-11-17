/*
 * Anchor (ESP32 / ESP32-C3) BLE Scanner + MQTT Publisher
 *
 * MQTT Topics:
 *   rtls/anchor/<ANCHOR_ID>/scan       – publishes every BLE advertisement of a wearable
 *   rtls/anchor/<ANCHOR_ID>/status     – periodic status report (retained)
 *   rtls/events                        – emergency events
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

// Current epoch time in milliseconds (NTP-synchronized)
static inline uint64_t nowEpochMs() { return startEpochMs + (millis() - startMillis); }

static void connectWiFi() {
  Serial.printf("Connecting to WiFi SSID=%s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - t0 > 30000) ESP.restart();   // fail-safe reboot after 30s
  }

  Serial.printf("\nWiFi connected, IP=%s RSSI=%d\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());

  // Time sync via NTP
  configTime(0, 0, "pool.ntp.org");
  time_t now = time(nullptr);

  // Wait until time is valid (>= Nov 2023)
  while (now < 1700000000) {
    delay(500);
    now = time(nullptr);
  }

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

// Deduplication: remember last advertised sequence number per wearable UID
static std::map<String, uint16_t> lastSeqByUid;

class ScanCallbacks : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* d) override {

    // UID from advertised name ("W-01", ...)
    String uid;
    if (d->haveName()) {
      std::string nm = d->getName();
      // must start with "W-"
      if (nm.rfind("W-", 0) == 0) uid = String(nm.c_str());
    }
    if (uid.length() == 0) return;

    uint16_t adv_seq = 0;
    float battery_v = NAN;
    float temp_c = NAN;
    bool emergency = false;
    int8_t txp_dbm = 0;

    // Parse Manufacturer Data (14 bytes)
    if (d->haveManufacturerData()) {
      std::string md = d->getManufacturerData();
      if (md.size() >= 14) {
        const uint8_t* m = (const uint8_t*)md.data();

        // wearable UID (3 bytes) is ignored here; name already contains full UID

        adv_seq =    (uint16_t)((m[5] << 8) | m[6]);
        uint16_t mv = (uint16_t)((m[7] << 8) | m[8]);
        int16_t  t100 = (int16_t)((m[9] << 8) | m[10]);
        uint8_t  flags = m[11];
        txp_dbm = (int8_t)m[12];

        battery_v = mv / 1000.0f;
        temp_c = (t100 == (int16_t)0x7FFF) ? NAN : ((float)t100 / 100.0f);
        emergency = (flags & 0x01);
      }
    }

    // Deduplication: ignore repeated packets with same seq (unless emergency)
    auto it = lastSeqByUid.find(uid);
    if (it != lastSeqByUid.end() && it->second == adv_seq && !emergency) return;
    lastSeqByUid[uid] = adv_seq;

    uint64_t ts = nowEpochMs();

    // Publish scan event
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

    mqttClient.publish(
      ("rtls/anchor/" + String(ANCHOR_ID) + "/scan").c_str(),
      payload.c_str()
    );

    // Emergency event
    if (emergency) {
      String ev = "{";
      ev += "\"ts\":" + String(ts) + ",";
      ev += "\"uid\":\"" + uid + "\",";
      ev += "\"type\":\"emergency_button\",";
      ev += "\"severity\":2,";              // fixed severity level
      ev += "\"details\":\"pressed=true\",";
      ev += "\"anchor_id\":\"" + String(ANCHOR_ID) + "\"}";
      mqttClient.publish("rtls/events", ev.c_str());
    }
  }
};

static void publishAnchorStatus() {
  uint64_t ts = nowEpochMs();
  long wifi_rssi = WiFi.RSSI();
  String ip = WiFi.localIP().toString();
  size_t heap_free = ESP.getFreeHeap();
  size_t heap_min  = ESP.getMinFreeHeap();
  uint32_t uptime_s = millis() / 1000;

  float tC = NAN;
  #ifdef temperatureRead
    tC = temperatureRead();     // onboard temperature sensor (ESP32 only)
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

  // retained: Status persists across MQTT reconnects
  mqttClient.publish(
    ("rtls/anchor/" + String(ANCHOR_ID) + "/status").c_str(),
    payload.c_str(),
    true
  );
}

void setup() {
  Serial.begin(115200);
  connectWiFi();
  connectMQTT();

  NimBLEDevice::init("");
  NimBLEScan* scan = NimBLEDevice::getScan();
  scan->setScanCallbacks(new ScanCallbacks());

  // Passive scan, full duty cycle
  scan->setActiveScan(false);
  scan->setDuplicateFilter(false);
  scan->setInterval(512);
  scan->setWindow(128);
  scan->start(0, false);   // continuous scanning

  publishAnchorStatus();
}

void loop() {
  if (!mqttClient.connected()) connectMQTT();
  mqttClient.loop();

  // Publish status every 60 seconds
  if (millis() - lastStatus >= 60000) {
    lastStatus = millis();
    publishAnchorStatus();
  }

  delay(5);
}
