/*
 * Wearable (ESP32-C3) BLE-Advertiser – volle Leistung (+9 dBm), gültige Manufacturer Data
 *
 * Manufacturer Data (14 Byte) – inkl. Company ID (0xFFFF):
 * [0..1]  company_id_le = 0xFF, 0xFF
 * [2..4]  uid_3 = erste 3 Zeichen aus WEARABLE_UID (nur informativ)
 * [5..6]  adv_seq (uint16, BE)
 * [7..8]  batt_mV (uint16, BE)   // VBUS/2 via Spannungsteiler
 * [9..10] temp_c_x100 (int16, BE)
 * [11]    flags (bit0=Emergency)
 * [12]    tx_power_dbm (int8)    -> immer 9
 * [13]    reserved
 *
 * - Advert-Name = WEARABLE_UID (z.B. "W-01"); Anchor nutzt den Namen als UID.
 * - TX-Power: immer +9 dBm
 * - Advert-Intervall: Idle ~1–1.25 s, Emergency ~100–125 ms
 * - Payload-Refresh: alle 5 s (Emergency: 1 s)
 * - VBUS messen: Spannungsteiler 1:2 auf ADC0 (GPIO0/ADC1_CH0)
 */

#include <Arduino.h>
#include <NimBLEDevice.h>
#include "secrets.h"   // definiert WEARABLE_UID

#define PIN_EMERGENCY   9     // Taster nach GND, interner Pullup
#define ADV_LEN         14
#define TX_DBM_CONST    9     // immer volle Leistung

NimBLEAdvertising *pAdvertising = nullptr;
uint32_t advSeq = 1;

// --- Temperatur lesen ---
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

// --- VBUS/"Battery" (mit Teiler 1:2 auf ADC0) ---
static float readBatteryVoltage() {
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  uint32_t mv = analogReadMilliVolts(0); // GPIO0 / ADC1_CH0
  return (mv * 2.0f) / 1000.0f;          // zurückrechnen auf VBUS in Volt
}

static void setAdvIntervalMs(uint16_t min_ms, uint16_t max_ms) {
  // BLE-Einheiten: 0.625 ms
  uint16_t min_itv = min<uint16_t>(max<uint16_t>(min_ms * 1000 / 625, 32), 16384);
  uint16_t max_itv = min<uint16_t>(max<uint16_t>(max_ms * 1000 / 625, 32), 16384);
  pAdvertising->setMinInterval(min_itv);
  pAdvertising->setMaxInterval(max_itv);
}

// --- Advertisement-Daten aktualisieren ---
static void updateAdvertisement() {
  uint32_t seq = advSeq++;
  float vbat = readBatteryVoltage();
  float tC   = readBoardTempC();
  bool  emergency = (digitalRead(PIN_EMERGENCY) == LOW);

  uint8_t mfg[ADV_LEN] = {0};

  // Company ID (little endian) – 0xFFFF als Test-ID
  mfg[0] = 0xFF;
  mfg[1] = 0xFF;

  // UID (3 Bytes) – nur als Marker
  size_t uid_len = strlen(WEARABLE_UID);
  memcpy(&mfg[2], WEARABLE_UID, min(uid_len, (size_t)3));

  // Sequence (BE)
  mfg[5] = (seq >> 8) & 0xFF;
  mfg[6] = (seq) & 0xFF;

  // Battery mV (BE)
  uint16_t batt_mv = (uint16_t) lroundf(vbat * 1000.0f);
  mfg[7] = (batt_mv >> 8) & 0xFF;
  mfg[8] = batt_mv & 0xFF;

  // Temp * 100 (int16, BE), NaN -> 0x7FFF
  int16_t t100 = isnan(tC) ? (int16_t)0x7FFF : (int16_t) lroundf(tC * 100.0f);
  mfg[9]  = (t100 >> 8) & 0xFF;
  mfg[10] = t100 & 0xFF;

  // Flags
  mfg[11] = emergency ? 0x01 : 0x00;

  // TX power (dBm) – immer +9
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

  // Immer volle Leistung (+9 dBm)
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_DEFAULT, ESP_PWR_LVL_P9);
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV,     ESP_PWR_LVL_P9);
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_SCAN,    ESP_PWR_LVL_P9);

  pAdvertising = NimBLEDevice::getAdvertising();
  pAdvertising->enableScanResponse(false);

  // Idle-Intervall: 1–1.25 s
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

  // Bei Notfall nur WerbeINTERVALL beschleunigen (Leistung bleibt +9 dBm)
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
