#!/usr/bin/env python3
"""
Realistic CAN Bus Instrument Cluster + UDS Server
Features:
 - Smooth needle animation
 - FUCYTECH UDS/DID Response System
 - ISO-TP (Multi-frame) support for long DIDs (like VIN)

Usage:
 1. Setup vcan0
 2. Run this script
 3. Send UDS requests (e.g., cangen vcan0 -I 7E0 -D 0322F19000000000 -L 8)
"""

import pygame
import can
import sys
import os
import math
import struct
import time

# === CONFIGURATION ===
CAN_INTERFACE = 'vcan0'
WIDTH, HEIGHT = 1200, 600
FPS = 60

# CAN Message IDs
ID_SPEED   = 0x244
ID_BLINKER = 0x188
ID_DOORS   = 0x19B

# UDS / Diagnostics Configuration
ID_UDS_REQ = 0x7E0  # Tester sends here
ID_UDS_RES = 0x7E8  # ECU responds here

# Speedometer Configuration
GAUGE_CENTER_X = 600
GAUGE_CENTER_Y = 340
MAX_SPEED_KMH = 240
ANGLE_AT_0_KMH = 225
ANGLE_AT_MAX_KMH = -45

NEEDLE_SMOOTHING = 0.15
BLINK_RATE = 0.5

class InstrumentCluster:
    def __init__(self):
        """Initialize the instrument cluster"""
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("FUCYTECH Instrument Cluster & ECU Simulator")
        self.clock = pygame.time.Clock()

        self.digital_font = pygame.font.SysFont("Courier New", 32, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 16)
        self.diag_font = pygame.font.SysFont("Arial", 20, bold=True)

        self.load_assets()

        self.angle_range = ANGLE_AT_0_KMH - ANGLE_AT_MAX_KMH
        self.degrees_per_kmh = self.angle_range / MAX_SPEED_KMH

        # Vehicle state
        self.target_speed = 0
        self.current_speed = 0
        self.current_angle = ANGLE_AT_0_KMH
        self.left_signal = False
        self.right_signal = False
        self.blink_state = False
        self.blink_timer = 0
        self.doors = [False, False, False, False]
        
        # Diagnostic State
        self.diag_active = False
        self.diag_timer = 0
        self.last_did_read = "None"

        # --- FUCYTECH DID DATABASE ---
        # Format: DID (int) : Data (bytes or string)
        self.did_database = {
            0xF190: "FUCYTECH-VIN-0001",       # 17 char VIN
            0xF180: "FUCY-BOOT-V1.0",          # Boot ID
            0xF181: "FUCY-APP-V2.5.1",         # App ID
            0xF186: b'\x01',                   # 0x01 = Default Session
            0xF187: "FUCY-HW-9999-X",          # Spare Part
            0xF188: "FT-SW-BUILD-2025",        # SW Number
            0xF198: "SHOP-CODE-007",           # Shop Code
            0xF18C: "SN-FUCY-88888888"         # Serial
        }

        self.setup_can()
        self.print_header()

    def print_header(self):
        print("\n" + "="*70)
        print("🚗 FUCYTECH INSTURMENT CLUSTER + ECU SIMULATOR")
        print("="*70)
        print(f"CAN Interface: {CAN_INTERFACE}")
        print(f"UDS Request ID: 0x{ID_UDS_REQ:03X} | Response ID: 0x{ID_UDS_RES:03X}")
        print("-" * 20)
        print("Supported DIDs:")
        for did, val in self.did_database.items():
            val_str = val if isinstance(val, str) else f"0x{val.hex()}"
            print(f"  0x{did:04X} : {val_str}")
        print("="*70 + "\n")

    def load_assets(self):
        # Create dummy assets if files don't exist
        self.bg_image = pygame.Surface((WIDTH, HEIGHT))
        self.bg_image.fill((20, 20, 30)) # Dark Blue-Grey background
        
        # Draw a gauge circle on the background
        pygame.draw.circle(self.bg_image, (40, 40, 50), (GAUGE_CENTER_X, GAUGE_CENTER_Y), 250)
        pygame.draw.circle(self.bg_image, (200, 200, 200), (GAUGE_CENTER_X, GAUGE_CENTER_Y), 250, 4)

        # Create a simple needle
        self.needle_original = pygame.Surface((200, 10), pygame.SRCALPHA)
        self.needle_original.fill((255, 50, 50)) # Red needle

    def setup_can(self):
        try:
            self.bus = can.interface.Bus(channel=CAN_INTERFACE, bustype='socketcan')
            print(f"✓ Connected to {CAN_INTERFACE}")
        except OSError as e:
            print(f"⚠ CAN interface error: {e}")
            self.bus = None

    def rotate_needle(self, angle):
        """Rotate needle around pivot"""
        # Simple rotation for the generated surface
        pivot = pygame.math.Vector2(0, 5) # Middle-Left of the needle rect
        image_rect = self.needle_original.get_rect(topleft=(GAUGE_CENTER_X, GAUGE_CENTER_Y - 5))
        offset_center_to_pivot = pygame.math.Vector2(GAUGE_CENTER_X, GAUGE_CENTER_Y) - image_rect.center
        
        rotated_image = pygame.transform.rotate(self.needle_original, angle)
        rotated_offset = offset_center_to_pivot.rotate(-angle)
        rotated_rect = rotated_image.get_rect(center=image_rect.center + rotated_offset)
        
        # Adjust so it pivots from the center of the gauge
        # (Simplified math for the fallback generated needle)
        rad = math.radians(angle)
        x = GAUGE_CENTER_X + 100 * math.cos(-rad) # 100 is half length
        y = GAUGE_CENTER_Y + 100 * math.sin(-rad)
        
        # Re-use simple line drawing if asset loading failed to keep it robust
        return None, None

    def handle_uds_request(self, msg):
        """
        Handle incoming ISO-TP/UDS requests on 0x7E0
        Logic:
        1. Parse Single Frame (SF)
        2. Identify Service (0x22) and DID
        3. Lookup Data
        4. Send Response (Single Frame or Multi-Frame)
        """
        data = msg.data
        if not data: return

        # ISO-TP Protocol Control Information (PCI)
        pci_type = (data[0] & 0xF0) >> 4
        length = data[0] & 0x0F

        # We only handle Single Frames (0x0) for requests in this simple sim
        if pci_type == 0:
            sid = data[1]
            if sid == 0x22: # Read Data By Identifier
                did = (data[2] << 8) | data[3]
                self.process_did_read(did)

    def process_did_read(self, did):
        """Prepare and send the UDS Response"""
        if did in self.did_database:
            raw_val = self.did_database[did]
            
            # Convert string to bytes if necessary
            if isinstance(raw_val, str):
                payload_data = raw_val.encode('ascii')
            else:
                payload_data = raw_val

            self.last_did_read = f"0x{did:04X}"
            self.diag_active = True
            self.diag_timer = 30 # Show icon for 0.5s

            # Construct UDS Response Payload: [0x62 (Positive Response)] + [DID_H] + [DID_L] + [DATA]
            uds_payload = [0x62, (did >> 8) & 0xFF, did & 0xFF] + list(payload_data)
            
            self.send_isotp_response(uds_payload)
            print(f"🔍 UDS Read: DID 0x{did:04X} -> Sent {len(payload_data)} bytes")
        else:
            # Send Negative Response: [7F] [22] [31 (Request Out of Range)]
            self.send_isotp_response([0x7F, 0x22, 0x31])
            print(f"❌ UDS Read: DID 0x{did:04X} -> Unknown DID")

    def send_isotp_response(self, payload):
        """
        Send payload over CAN using ISO-TP (Handles Fragmentation)
        """
        total_len = len(payload)
        
        # CASE 1: Single Frame (Data fits in 7 bytes or less)
        if total_len <= 7:
            # Byte 0: PCI (0x0 | Length)
            frame_data = [total_len] + payload
            # Padding
            while len(frame_data) < 8:
                frame_data.append(0xAA) # Padding byte
            
            self.bus.send(can.Message(arbitration_id=ID_UDS_RES, data=frame_data, is_extended_id=False))

        # CASE 2: Multi-Frame (Data > 7 bytes)
        else:
            # 1. Send First Frame (FF)
            # PCI: 0x10 (FF) | High 4 bits of length
            pci_byte1 = 0x10 | ((total_len >> 8) & 0x0F)
            pci_byte2 = total_len & 0xFF
            
            # FF Data: First 6 bytes of payload
            frame_data = [pci_byte1, pci_byte2] + payload[:6]
            self.bus.send(can.Message(arbitration_id=ID_UDS_RES, data=frame_data, is_extended_id=False))
            
            # Ideally, we wait for Flow Control (FC) here. 
            # For simulation speed, we assume the tester is fast and send Consecutive Frames (CF).
            time.sleep(0.01) # Small gap
            
            remaining_data = payload[6:]
            seq_num = 1
            
            # 2. Send Consecutive Frames (CF)
            while remaining_data:
                chunk = remaining_data[:7] # Can take 7 bytes
                remaining_data = remaining_data[7:]
                
                # PCI: 0x20 (CF) | Sequence Number (0-F)
                pci_byte = 0x20 | (seq_num & 0x0F)
                
                frame_data = [pci_byte] + chunk
                # Pad last frame
                while len(frame_data) < 8:
                    frame_data.append(0xAA)
                
                self.bus.send(can.Message(arbitration_id=ID_UDS_RES, data=frame_data, is_extended_id=False))
                seq_num += 1
                time.sleep(0.005) # Inter-frame spacing

    def process_can_messages(self):
        if not self.bus: return

        # Process up to 20 messages per frame to prevent lag
        for _ in range(20):
            msg = self.bus.recv(0)
            if msg is None: break

            if msg.arbitration_id == ID_SPEED:
                if len(msg.data) >= 1:
                    # ICSim Standard (Byte 0 = speed)
                    self.target_speed = min(MAX_SPEED_KMH, float(msg.data[0]))
                elif len(msg.data) >= 4:
                    # Old Fallback
                    raw = (msg.data[2] << 8) | msg.data[3]
                    self.target_speed = raw / 100.0

            elif msg.arbitration_id == ID_BLINKER:
                if len(msg.data) >= 1:
                    self.left_signal = bool(msg.data[0] & 0x01)
                    self.right_signal = bool(msg.data[0] & 0x02)

            elif msg.arbitration_id == ID_DOORS:
                if len(msg.data) >= 4:
                    self.doors = [bool(msg.data[i] & 0x01) for i in range(4)]

            elif msg.arbitration_id == ID_UDS_REQ:
                self.handle_uds_request(msg)

    def draw_gauge_needle(self):
        # Calculate endpoint
        rad = math.radians(self.current_angle)
        length = 180
        end_x = GAUGE_CENTER_X + length * math.cos(-rad)
        end_y = GAUGE_CENTER_Y + length * math.sin(-rad)
        
        # Draw Needle Line
        pygame.draw.line(self.screen, (255, 50, 50), (GAUGE_CENTER_X, GAUGE_CENTER_Y), (end_x, end_y), 6)
        # Draw Pivot Cap
        pygame.draw.circle(self.screen, (20, 20, 20), (GAUGE_CENTER_X, GAUGE_CENTER_Y), 15)

    def draw_diagnostics_overlay(self):
        """Draw diagnostic connection status"""
        if self.diag_timer > 0:
            self.diag_timer -= 1
            
            # Draw Engine/Diag Icon (Orange)
            rect = pygame.Rect(WIDTH - 150, 50, 100, 60)
            pygame.draw.rect(self.screen, (255, 140, 0), rect, border_radius=5)
            pygame.draw.rect(self.screen, (255, 255, 255), rect, 2, border_radius=5)
            
            text = self.diag_font.render("DIAG", True, (0,0,0))
            self.screen.blit(text, (rect.x + 25, rect.y + 10))
            
            # Draw last Read DID
            did_text = self.small_font.render(f"Read: {self.last_did_read}", True, (255, 140, 0))
            self.screen.blit(did_text, (WIDTH - 150, 120))

    def update(self, dt):
        self.process_can_messages()
        
        # Needle Physics
        speed_diff = self.target_speed - self.current_speed
        self.current_speed += speed_diff * NEEDLE_SMOOTHING
        
        target_angle = ANGLE_AT_0_KMH - (self.current_speed * self.degrees_per_kmh)
        self.current_angle += (target_angle - self.current_angle) * NEEDLE_SMOOTHING
        
        # Blinker Timer
        self.blink_timer += dt
        if self.blink_timer >= (1.0 / BLINK_RATE / 2):
            self.blink_state = not self.blink_state
            self.blink_timer = 0

    def draw_digital_speed(self):
        text = self.digital_font.render(f"{int(self.current_speed)} km/h", True, (255, 255, 255))
        rect = text.get_rect(center=(GAUGE_CENTER_X, GAUGE_CENTER_Y + 100))
        self.screen.blit(text, rect)

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            # Demo Controls
            if not self.bus:
                keys = pygame.key.get_pressed()
                if keys[pygame.K_UP]: self.target_speed += 1
                if keys[pygame.K_DOWN]: self.target_speed -= 1

            self.update(dt)

            # Render
            self.screen.blit(self.bg_image, (0,0))
            self.draw_gauge_needle()
            self.draw_digital_speed()
            self.draw_diagnostics_overlay()
            
            # Simple Text Overlay for Info
            info = self.small_font.render("FUCYTECH ECU SIMULATOR - LISTENING ON ID 0x7E0", True, (100, 100, 100))
            self.screen.blit(info, (10, HEIGHT - 30))

            pygame.display.flip()

        if self.bus: self.bus.shutdown()
        pygame.quit()

if __name__ == "__main__":
    try:
        InstrumentCluster().run()
    except KeyboardInterrupt:
        sys.exit(0)
