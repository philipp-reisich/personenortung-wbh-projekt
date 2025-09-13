# BLE Distance Estimator (ESP32 Beacon + Scanner)

Two Arduino sketches to estimate distance between two ESP32 boards using **Bluetooth Low Energy (BLE)** RSSI:

- `Client_Beacon_ESP32_WROOM32D_NimBLE.ino` — advertises as an **iBeacon**.
- `Base_Scanner_ESP32_S3_NimBLE_2x.ino` — **scans** for that beacon and converts RSSI → distance with a path-loss model (plus smoothing).

> Works with **ESP32-WROOM-32D** for both roles. The “S3” in the scanner filename is just a label; it runs fine on WROOM too.

---

## Repo layout

```
/
├─ Client_Beacon_ESP32_WROOM32D_NimBLE.ino
├─ Base_Scanner_ESP32_S3_NimBLE_2x.ino
└─ README.md
```

---

## Requirements

- **Arduino IDE 2.x**
- **ESP32 board package**: Boards Manager → “esp32 by Espressif Systems” (3.x recommended)
- **NimBLE-Arduino** library (Library Manager → search “NimBLE-Arduino”, version **2.x**)
- Two ESP32 dev boards:
  - **ESP32-WROOM-32D** (USB-UART bridge; no USB CDC setting)
  - Optional: **ESP32-S3** (native USB; needs USB CDC enabled)

---

## Board settings (Arduino IDE → Tools)

### ESP32-WROOM-32D (typical devkit)
- **Board:** ESP32 Dev Module  
- **Flash Size:** 4MB (or 8MB if your board has it)  
- **Flash Mode:** DIO  
- **Flash Freq:** 80 MHz  
- **Upload Speed:** 460800 (or 921600)  
- **PSRAM:** Disabled  
- **Serial Monitor:** 115200 baud  

### ESP32-S3 (e.g., S3-CAM)
- **Board:** ESP32S3 Dev Module (or your specific def)  
- **USB CDC On Boot:** Enabled  
- **Flash Size:** match your board (e.g., 8MB)  
- **Flash Mode:** DIO  
- **Flash Freq:** 80 MHz  
- **PSRAM:** match your board (start Disabled if unsure)  
- **Serial Monitor:** 115200 baud  

---

## Quick start

1) **Flash the beacon**  
   - Open `Client_Beacon_ESP32_WROOM32D_NimBLE.ino`  
   - Upload to ESP32 #1  
   - Serial Monitor → `iBeacon advertising started.`

2) **Flash the scanner**  
   - Open `Base_Scanner_ESP32_S3_NimBLE_2x.ino`  
   - Upload to ESP32 #2  
   - Serial Monitor → `Starting BLE scan (NimBLE 2.x)...` and heartbeat `...scanning`  
   - When the beacon is in range you’ll see lines like:  
     ```
     Beacon <UUID> | RSSI=-71 dBm | MP=-71 | d=1.03 m | smooth=1.08 m
     ```

> Close the Serial Monitor while uploading (it can hold the COM port open). Reopen at **115200** after the upload.

---

## Calibration (do this once per setup)

BLE RSSI varies with hardware, orientation, and environment. Calibrate at **exactly 1.00 m**:

1. Place the two boards 1.00 m apart, line-of-sight.
2. Watch the **scanner** for ~20 s and average the RSSI (e.g., `-71 dBm`).
3. In **`Client_Beacon_ESP32_WROOM32D_NimBLE.ino`**, set:
   ```cpp
   static int8_t measuredPower = -71; // your avg RSSI at 1 m
   ```
   Re-upload the beacon.

4. (Optional) Improve fit by tuning the path-loss exponent on the **scanner**:
   ```cpp
   float pathLossN = 2.6f;  // try 2.4–3.0 indoors; 2.0 outdoors
   ```
   For a more exact value, measure an average RSSI at a known distance `d` (e.g., 3 m) and compute:
   ```
   n = (measuredPower - RSSI_d) / (10 * log10(d))
   ```
   Put that `n` into `pathLossN`.

5. (Optional) Make smoothing respond faster/slower:
   ```cpp
   float alpha = 0.45f; // higher = faster but noisier (default 0.3)
   ```

---

## How it works

- **Beacon** advertises iBeacon frames (Apple company ID `0x004C`, type `0x02 0x15`) containing:
  UUID + major + minor + **measuredPower** (RSSI at 1 m).
- **Scanner** reads:
  - Radio **RSSI**
  - **measuredPower** from the payload
  - Estimates distance with the log-distance model:
    ```
    d = 10 ^ ((measuredPower - RSSI) / (10 * n))
    ```
  - Applies an exponential moving average (EMA) for smoothing.

**Expected accuracy:** open air ~±0.5–1.5 m; indoors can be ±2–5 m due to multipath and body blocking (normal for RSSI-based ranging).

---

## Changing the UUID / tags

- In **both** sketches, set the same UUID string:
  ```cpp
  "e2c56db5-dffb-48d2-b060-d0f5a71096e0"
  ```
- (Optional) Change `major`/`minor` in the beacon to tag multiple beacons.

---

## Typical output

```
Starting BLE scan (NimBLE 2.x)...
...scanning
Beacon e2c56db5-dffb-48d2-b060-d0f5a71096e0 | RSSI=-71 dBm | MP=-71 | d=1.01 m | smooth=1.12 m
Beacon e2c56db5-dffb-48d2-b060-d0f5a71096e0 | RSSI=-72 dBm | MP=-71 | d=1.12 m | smooth=1.12 m
...
```

---

## Troubleshooting

- **Nothing on Serial**
  - Check 115200 baud.
  - Close Serial Monitor during upload.
  - **S3 only:** Tools → USB CDC On Boot → Enabled.

- **Upload fails / wrong COM port (Windows)**
  - Unplug/replug and re-select the COM port that appears in Device Manager.
  - For S3, the COM number may change when entering the bootloader.
  - Force bootloader: hold **BOOT**, tap **EN**, release **BOOT** when IDE says “Connecting…”.

- **Boot error: “Detected size smaller than header”**
  - Compiled with wrong **Flash Size**. Set the correct size, **Erase Flash** once, then re-upload.

- **Scanner never sees the beacon**
  - Verify the beacon with a phone app (e.g., *nRF Connect*). Look for **Manufacturer Data** starting `4C 00 02 15`.
  - Ensure UUID matches in both files.
  - Test away from metal/USB hubs/your body; orientation matters.

- **Build errors referencing callbacks or `setAdvertisedDeviceCallbacks`**
  - You’re mixing NimBLE-Arduino versions. These sketches target **NimBLE-Arduino 2.x**. For 1.x, callback types/signatures differ.

- **`NimBLEDevice::setPower(9)` won’t compile**
  - Remove that line; it’s optional and version-dependent.

---

## Notes & limits

- BLE RSSI ranging is approximate; for sub-meter accuracy consider **UWB** or BLE 5.1 **AoA** with antenna arrays.
- Advertising interval and scan window are set to reasonable defaults; you can tweak `scan->setInterval()` / `setWindow()` for responsiveness vs. power.

---

## License

Add the license you prefer (MIT suggested). Example:

```
MIT License
Copyright (c) 2025 ...
Permission is hereby granted, free of charge, to any person obtaining a copy...
```

---

## Roadmap (optional)

- Single sketch that does **beacon + scanner** for one-device testing  
- Rolling median + outlier rejection on the scanner  
- JSON serial output for logging/plotting
