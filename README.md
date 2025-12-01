

# 🚗  Instrument Cluster & ECU Simulator

A Python-based automotive instrument cluster simulator designed for learning **CAN Bus Reverse Engineering** and **UDS (Unified Diagnostic Services)** protocols.

This tool acts as a modern vehicle's ECU and Dashboard, allowing you to "drive" a virtual car, sniff the traffic, and perform diagnostic queries (OBD-II/UDS) against it.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue) ![Pygame](https://img.shields.io/badge/Library-Pygame-green) ![Protocol](https://img.shields.io/badge/Protocol-CAN%20%2F%20UDS-orange)

## ✨ Features

*   **Virtual Instrument Cluster:** Smooth analog speedometer and digital indicators rendered in real-time.
*   **Integrated ECU:** Simulates a realistic Engine Control Unit that broadcasts telemetry.
*   **Hybrid Networking:**
    *   **Linux Mode:** Uses native `SocketCAN` (`vcan0`) for use with tools like `can-utils`, `Wireshark`, and `SavvyCAN`.
    *   **Online/Windows Mode:** Uses a memory-based virtual bus for easy testing without kernel drivers.
*   **UDS Server (ISO-14229):** Responds to diagnostic requests (Read Data By Identifier `0x22`) with custom "FUCYTECH" data.
*   **ISO-TP Support:** Handles multi-frame messages (fragmentation) for long data like VINs.

---

## 🛠️ Installation

### Prerequisites
You need Python 3 installed.

```bash
pip install pygame python-can
```

*(Optional but Recommended on Linux)* Install `can-utils` to analyze the traffic:
```bash
sudo apt-get install can-utils
```

---

## 🚀 Usage

### 1. Online / Windows / Mac (No Setup Required)
By default, the script is configured to run in **Virtual Mode** (RAM-based). This allows it to run anywhere, including online IDEs like Replit.

1.  Open the script.
2.  Ensure configuration is set to: `CAN_BUSTYPE = 'virtual'`
3.  Run the script:
    ```bash
    python3 main.py
    ```
4.  **Controls:**
    *   **UP / DOWN Arrow:** Accelerate / Decelerate.
    *   **LEFT / RIGHT Arrow:** Toggle Turn Signals.
    *   **'D' Key:** Inject a simulated UDS Diagnostic Request (Simulates a hacker tool).

### 2. Linux (SocketCAN Mode)
To use this with professional tools like `candump`, `cansniffer`, or `isotpsend`, you must use a virtual CAN interface.

1.  **Setup the Interface:**
    ```bash
    sudo modprobe vcan
    sudo ip link add dev vcan0 type vcan
    sudo ip link set up vcan0
    ```

2.  **Edit the Code:**
    Change the configuration lines at the top of the script:
    ```python
    CAN_BUSTYPE = 'socketcan'
    CAN_CHANNEL = 'vcan0'
    ```

3.  **Run the Simulator:**
    ```bash
    python3 main.py
    ```

4.  **Hack the Network (In a separate terminal):**
    *   **Sniff Traffic:** `cansniffer -c vcan0`
    *   **Dump Traffic:** `candump vcan0`
    *   **Send Manual Packet:** `cansend vcan0 244#6400000000000000` (Sets speed to 100km/h)

---

## 📡 CAN Bus Protocol Specification

If you are reverse engineering this simulator, here is the "Cheatsheet" for the traffic it generates.

### Broadcast Messages (Periodical)

| CAN ID | Name | Frequency | Data Format |
| :--- | :--- | :--- | :--- |
| **0x244** | **Engine/Speed** | 20Hz | **Byte 0:** Vehicle Speed (km/h)<br>**Bytes 1-7:** Reserved (0x00) |
| **0x188** | **Lighting** | 20Hz | **Byte 0:** Bitmask<br>`0x01` = Left Turn<br>`0x02` = Right Turn |
| **0x19B** | **Door Status** | On Change | **Byte 0-3:** Door Open (1) / Closed (0)<br>`[FL, FR, RL, RR]` |

### Diagnostic Messages (UDS / ISO-TP)

| CAN ID | Description |
| :--- | :--- |
| **0x7E0** | **Request ID** (Tool -> ECU) |
| **0x7E8** | **Response ID** (ECU -> Tool) |

---

## 🔍 Supported DIDs (Data Identifiers)

The simulator implements a UDS Server. You can query these IDs using Service `0x22` (Read Data By Identifier).

| DID | Description | Return Data (ASCII/Hex) |
| :--- | :--- | :--- |
| **0xF190** | VIN (Vehicle ID Number) | `FUCYTECH-VIN-0001` |
| **0xF180** | Boot Software ID | `FUCY-BOOT-V1.0` |
| **0xF181** | Application Software ID | `FUCY-APP-V2.5.1` |
| **0xF187** | Spare Part Number | `FUCY-HW-9999-X` |
| **0xF18C** | ECU Serial Number | `SN-FUCY-88888888` |

### How to Request Data (Linux/Can-Utils)
To manually request the VIN via the terminal while the simulator is running:

```bash
   #Read Boot Software ID (0xF180)
   cansend vcan0 7E0#0322F18000000000

   #Read ECU Serial (0xF18C)
   cansend vcan0 7E0#0322F18C00000000

   # Request VIN (Length 03, Service 22, DID F1 90)
   cansend vcan0 7E0#0322F19000000000

```

You should see the dashboard light up with a **"DIAG"** warning icon when this happens!

---

## 🤝 Contributing

Feel free to fork this project and add:
*   More DIDs (e.g., Engine Temp, Odometer).
*   Write support (Service `0x2E`) to change configuration.
*   Security Access (`0x27`) simulation.

## 📄 License

Open Source (MIT). Free for educational use.
