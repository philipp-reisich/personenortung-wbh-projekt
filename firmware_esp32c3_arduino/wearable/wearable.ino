/*
 * Wearable (ESP32-C3) BLE Advertiser – full TX power (+9 dBm), valid Manufacturer Data
 *
 * Manufacturer Data (14 bytes) – including Company ID (0xFFFF):
 * [0..1]  company_id_le = 0xFF, 0xFF
 * [2..4]  uid_3 = first 3 characters of WEARABLE_UID (informational only)
 * [5..6]  adv_seq (uint16, BE)
 * [7..8]  batt_mV (uint16, BE)   // VBUS/2 through voltage divider
 * [9..10] temp_c_x100 (int16, BE)
 * [11]    flags (bit0 = Emergency)
 * [12]    tx_power_dbm (int8)    -> always 9
 * [13]    reserved
 *
 * - Advertised name = WEARABLE_UID (e.g. "W-01"); the anchor uses the name as UID.
 * - TX power: always +9 dBm
 * - Advertising interval: Idle ~1–1.25 s, Emergency ~100–125 ms
 * - Payload refresh rate: every 5 s (Emergency: every 1 s)
 * - VBUS measurement: voltage divider 1:2 on ADC0 (GPIO0 / ADC1_CH0)
 */

#include <Arduino.h>
#include <NimBLEDevice.h>
#include "secrets.h"

#define PIN_EMERGENCY   9     // Button to GND, internal pull-up
#define ADV_LEN         14
#define TX_DBM_CONST    9     // always full power

NimBLEAdvertising *pAdvertising = nullptr;
uint32_t advSeq = 1;

// --- Read onboard temperature ---
static float readBoardTempC() {
#if defined(ARDUINO_ARCH_ESP32)
  #ifdef temperatureRead
    return temperatureRead();
  #else
    return NAN;
  #endif
#else
  return NAN;
#endif
}

// --- Read VBUS/"Battery" (with 1:2 divider on ADC0) ---
static float readBatteryVoltage() {
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  uint32_t mv = analogReadMilliVolts(0); // GPIO0 / ADC1_CH0
  return (mv * 2.0f) / 1000.0f;
}

static void setAdvIntervalMs(uint16_t min_ms, uint16_t max_ms) {
  uint16_t min_itv = min<uint16_t>(max<uint16_t>(min_ms * 1000 / 625, 32), 16384);
  uint16_t max_itv = min<uint16_t>(max<uint16_t>(max_ms * 1000 / 625, 32), 16384);
  pAdvertising->setMinInterval(min_itv);
  pAdvertising->setMaxInterval(max_itv);
}

// --- Update advertisement payload ---
static void updateAdvertisement() {
  uint32_t seq = advSeq++;
  float vbat = readBatteryVoltage();
  float tC   = readBoardTempC();
  bool  emergency = (digitalRead(PIN_EMERGENCY) == LOW);

  uint8_t mfg[ADV_LEN] = {0};

  // Company ID (little endian) – 0xFFFF as test ID
  mfg[0] = 0xFF;
  mfg[1] = 0xFF;

  // UID (3 bytes)
  size_t uid_len = strlen(WEARABLE_UID);
  memcpy(&mfg[2], WEARABLE_UID, min(uid_len, (size_t)3));

  // Sequence (BE)
  mfg[5] = (seq >> 8) & 0xFF;
  mfg[6] = (seq) & 0xFF;

  // Battery mV (BE)
  uint16_t batt_mv = (uint16_t) lroundf(vbat * 1000.0f);
  mfg[7] = (batt_mv >> 8) & 0xFF;
  mfg[8] = batt_mv & 0xFF;

  // Temperature * 100 (int16, BE), NaN -> 0x7FFF
  int16_t t100 = isnan(tC) ? (int16_t)0x7FFF : (int16_t) lroundf(tC * 100.0f);
  mfg[9]  = (t100 >> 8) & 0xFF;
  mfg[10] = t100 & 0xFF;

  // Flags
  mfg[11] = emergency ? 0x01 : 0x00;

  // TX power (dBm) – always +9
  mfg[12] = (uint8_t)TX_DBM_CONST;

  // Reserved
  mfg[13] = 0;

  NimBLEAdvertisementData advData;
  advData.setFlags(0x06);
  advData.setManufacturerData(std::string((char*)mfg, ADV_LEN));
  advData.setName(WEARABLE_UID);

  pAdvertising->setAdvertisementData(advData);
  if (pAdvertising->isAdvertising()) pAdvertising->refreshAdvertisingData();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_EMERGENCY, INPUT_PULLUP);

  NimBLEDevice::init("");

  // Always full TX power (+9 dBm)
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_DEFAULT, ESP_PWR_LVL_P9);
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV,     ESP_PWR_LVL_P9);
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_SCAN,    ESP_PWR_LVL_P9);

  pAdvertising = NimBLEDevice::getAdvertising();
  pAdvertising->enableScanResponse(false);

  // Idle interval: 1–1.25 s
  setAdvIntervalMs(1000, 1250);

  updateAdvertisement();
  pAdvertising->start();
  Serial.println("Wearable advertising @ +9 dBm");
}

void loop() {
  static unsigned long last = 0;
  static bool fastAdv = false;

  const bool emergency = (digitalRead(PIN_EMERGENCY) == LOW);
  const unsigned long period = emergency ? 1000 : 5000;

  // In emergency mode only the advertising INTERVAL is increased (TX power stays +9 dBm)
  if (emergency && !fastAdv) {
    setAdvIntervalMs(100, 125);
    if (pAdvertising->isAdvertising()) pAdvertising->refreshAdvertisingData();
    fastAdv = true;
  } else if (!emergency && fastAdv) {
    setAdvIntervalMs(1000, 1250);
    if (pAdvertising->isAdvertising()) pAdvertising->refreshAdvertisingData();
    fastAdv = false;
  }

  if (millis() - last >= period) {
    last = millis();
    updateAdvertisement();
    Serial.printf("seq=%lu vbus=%.3fV temp=%.2fC emergency=%d tx=+%d dBm\n",
      (unsigned long)(advSeq - 1), readBatteryVoltage(), readBoardTempC(), emergency, TX_DBM_CONST);
  }
  delay(5);
}
