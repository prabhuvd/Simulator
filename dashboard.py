#!/usr/bin/env python3
"""
Realistic CAN Bus Instrument Cluster + UDS/DID Server
Features smooth needle animation, professional styling, and FUCYTECH Diagnostics.

UPDATES:
 - Preserved original Asset loading and UI logic.
 - Added UDS Server on ID 0x7E0 (Request) / 0x7E8 (Response).
 - Implemented FUCYTECH DID Database (VIN, Serial, Boot ID, etc).
 - Added ISO-TP Multi-frame support for long responses.
"""

import pygame
import can
import sys
import os
import math
import time

# === CONFIGURATION ===
CAN_INTERFACE = 'vcan0'
WIDTH, HEIGHT = 1200, 600
FPS = 60

# CAN Message IDs (Normal Operation)
ID_SPEED   = 0x244
ID_BLINKER = 0x188
ID_DOORS   = 0x19B

# CAN Message IDs (Diagnostics/UDS)
ID_UDS_REQ = 0x7E0  # Tester (Scan Tool) sends to this ID
ID_UDS_RES = 0x7E8  # ECU responds on this ID

# Speedometer Configuration
GAUGE_CENTER_X = 600
GAUGE_CENTER_Y = 340
MAX_SPEED_KMH = 240

# Needle angles (matching the gauge design)
ANGLE_AT_0_KMH = 225      # Bottom-left
ANGLE_AT_MAX_KMH = -45    # Bottom-right

# Smooth animation settings
NEEDLE_SMOOTHING = 0.15   # Lower = smoother but slower (0.05-0.3)
BLINK_RATE = 0.5          # Blinks per second

class InstrumentCluster:
    def __init__(self):
        """Initialize the instrument cluster"""
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("FUCYTECH Instrument Cluster & UDS Server")
        self.clock = pygame.time.Clock()

        # Fonts
        self.digital_font = pygame.font.SysFont("Courier New", 32, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 16)
        self.diag_font = pygame.font.SysFont("Arial", 20, bold=True)

        # Load assets
        self.load_assets()

        # Calculate angle conversion
        self.angle_range = ANGLE_AT_0_KMH - ANGLE_AT_MAX_KMH
        self.degrees_per_kmh = self.angle_range / MAX_SPEED_KMH

        # Vehicle state
        self.target_speed = 0      # Target speed from CAN
        self.current_speed = 0     # Current displayed speed (smoothed)
        self.current_angle = ANGLE_AT_0_KMH  # Current needle angle

        self.left_signal = False
        self.right_signal = False
        self.blink_state = False
        self.blink_timer = 0

        # Door states: [Front-Left, Front-Right, Rear-Left, Rear-Right]
        self.doors = [False, False, False, False]
        
        # Diagnostic / UDS State
        self.diag_active = False # Controls the UI indicator
        self.diag_timer = 0
        self.last_did_read = ""
        
        # --- FUCYTECH DID DATABASE ---
        # Maps DID (int) to Byte Data or String
        self.did_database = {
            0xF190: "FUCYTECH-VIN-0001",       # 17-char VIN
            0xF180: "FUCY-BOOT-V1.0",          # Boot SW ID
            0xF181: "FUCY-APP-V2.5.1",         # App SW ID
            0xF186: b'\x01',                   # Active Session (01=Default)
            0xF187: "FUCY-HW-9999-X",          # Spare Part No
            0xF188: "FT-SW-BUILD-2025",        # ECU SW No
            0xF198: "SHOP-CODE-007",           # Repair Shop Code
            0xF18C: "SN-FUCY-88888888"         # ECU Serial
        }

        # Statistics
        self.frame_count = 0
        self.last_can_time = pygame.time.get_ticks()

        # Setup CAN bus
        self.setup_can()
        self.print_welcome_message()

    def print_welcome_message(self):
        print("\n" + "="*70)
        print("🚗 FUCYTECH's FuzzCAN - INSTRUMENT CLUSTER + UDS ECU")
        print("="*70)
        print(f"Interface: {CAN_INTERFACE}")
        print(f"Gauge: 0-{MAX_SPEED_KMH} km/h")
        print("-" * 30)
        print(f"Diagnostics: Listening on 0x{ID_UDS_REQ:03X} / Responding on 0x{ID_UDS_RES:03X}")
        print("Supported DIDs (Service 0x22):")
        for did, val in self.did_database.items():
            val_str = val if isinstance(val, str) else f"Hex: {val.hex()}"
            print(f"  0x{did:04X} : {val_str}")
        print("="*70)

    def load_assets(self):
        """Load background and needle images"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        assets_dir = os.path.join(script_dir, "assets")

        bg_path = os.path.join(assets_dir, "dashboard_bg.png")
        needle_path = os.path.join(assets_dir, "needle.png")

        try:
            # Load background
            self.bg_image = pygame.image.load(bg_path).convert()
            if self.bg_image.get_size() != (WIDTH, HEIGHT):
                self.bg_image = pygame.transform.scale(self.bg_image, (WIDTH, HEIGHT))
            print(f"✓ Loaded dashboard background: {self.bg_image.get_size()}")

            # Load needle
            self.needle_original = pygame.image.load(needle_path).convert_alpha()
            # Scale needle to appropriate size
            self.needle_original = pygame.transform.scale(self.needle_original, (200, 40))
            print(f"✓ Loaded needle: {self.needle_original.get_size()}")

        except FileNotFoundError as e:
            print(f"\n❌ ERROR: Asset files not found!")
            print(f"Looking in: {assets_dir}")
            print(f"\n📁 Please create 'assets' folder with:")
            print("   1. dashboard_bg.png (1200x600)")
            print("   2. needle.png (200x40)")
            print(f"\nError: {e}")
            sys.exit(1)

    def setup_can(self):
        """Setup CAN bus connection"""
        try:
            self.bus = can.interface.Bus(channel=CAN_INTERFACE, bustype='socketcan')
            print(f"✓ Connected to {CAN_INTERFACE}")
        except OSError as e:
            print(f"⚠ CAN interface not available: {e}")
            print(f"\n📋 To setup vcan0:")
            print("   sudo modprobe vcan")
            print("   sudo ip link add dev vcan0 type vcan")
            print("   sudo ip link set up vcan0")
            print("\n▶ Running in DEMO mode (use arrow keys)")
            self.bus = None

    def rotate_needle(self, angle):
        """Rotate needle image around pivot point"""
        # The pivot point in the needle image (where it connects to gauge center)
        pivot_x, pivot_y = 12, 20

        # Rotate the entire image
        rotated_image = pygame.transform.rotate(self.needle_original, angle)

        # Get the rect of the rotated image
        rotated_rect = rotated_image.get_rect()

        # Calculate where the pivot point moved to after rotation
        image_center = (self.needle_original.get_width() / 2, self.needle_original.get_height() / 2)
        pivot_offset = pygame.math.Vector2(pivot_x - image_center[0], pivot_y - image_center[1])
        rotated_offset = pivot_offset.rotate(-angle)

        # Position the rotated image so the pivot point is at GAUGE_CENTER
        rotated_rect.center = (GAUGE_CENTER_X - rotated_offset.x, 
                               GAUGE_CENTER_Y - rotated_offset.y)

        return rotated_image, rotated_rect

    # =========================================================================
    #  UDS & ISO-TP HANDLER
    # =========================================================================

    def handle_uds_request(self, msg):
        """Handle incoming ISO-TP/UDS requests"""
        data = msg.data
        if not data: return

        # ISO-TP Parsing (PCI Byte)
        # We only strictly handle Single Frames (SF) for incoming requests for simplicity
        pci_type = (data[0] & 0xF0) >> 4
        
        if pci_type == 0: # Single Frame
            sid = data[1] # Service ID
            
            if sid == 0x22: # Read Data By Identifier
                if len(data) >= 4:
                    did = (data[2] << 8) | data[3]
                    self.process_did_read(did)
            else:
                # Service not supported in this sim
                pass

    def process_did_read(self, did):
        """Lookup DID and send response"""
        if did in self.did_database:
            raw_val = self.did_database[did]
            
            # Convert string to bytes if needed
            if isinstance(raw_val, str):
                payload = raw_val.encode('ascii')
            else:
                payload = raw_val

            # Update UI Diagnostics Status
            self.diag_active = True
            self.diag_timer = 40 # frames
            self.last_did_read = f"0x{did:04X}"
            
            # Construct UDS Response Payload: [0x62] [DID_H] [DID_L] [DATA...]
            uds_response = [0x62, (did >> 8) & 0xFF, did & 0xFF] + list(payload)
            
            self.send_isotp_response(uds_response)
            print(f"🔍 UDS READ: 0x{did:04X} -> Sent {len(payload)} bytes")
        else:
            # Negative Response: [7F] [SID] [NRC=31 (Request Out of Range)]
            self.send_isotp_response([0x7F, 0x22, 0x31])
            print(f"❌ UDS READ: 0x{did:04X} -> Not Found")

    def send_isotp_response(self, payload):
        """Send payload using lightweight ISO-TP (handles fragmentation)"""
        total_len = len(payload)
        
        # --- Single Frame (SF) ---
        if total_len <= 7:
            # PCI: [0] [Length]
            frame = [total_len] + payload
            # Padding (0xAA or 0x00 is common)
            while len(frame) < 8: frame.append(0xAA)
            self.bus.send(can.Message(arbitration_id=ID_UDS_RES, data=frame, is_extended_id=False))

        # --- Multi Frame (MF) ---
        else:
            # 1. First Frame (FF)
            # PCI: [1] [Len_H] [Len_L]
            pci_high = 0x10 | ((total_len >> 8) & 0x0F)
            pci_low = total_len & 0xFF
            frame = [pci_high, pci_low] + payload[:6]
            self.bus.send(can.Message(arbitration_id=ID_UDS_RES, data=frame, is_extended_id=False))
            
            # (Simulation Shortcut: We assume Tester sends Flow Control instantly, so we just wait a tiny bit)
            time.sleep(0.01)

            # 2. Consecutive Frames (CF)
            remaining = payload[6:]
            seq_num = 1
            
            while remaining:
                chunk = remaining[:7]
                remaining = remaining[7:]
                
                # PCI: [2] [Sequence Number (0-F)]
                pci = 0x20 | (seq_num & 0x0F)
                frame = [pci] + chunk
                
                # Padding for last frame
                while len(frame) < 8: frame.append(0xAA)
                
                self.bus.send(can.Message(arbitration_id=ID_UDS_RES, data=frame, is_extended_id=False))
                
                seq_num = (seq_num + 1) % 16
                time.sleep(0.005) # Small delay to prevent buffer overflow on simple receivers

    # =========================================================================

    def process_can_messages(self):
        """Read and process CAN messages"""
        if not self.bus:
            return

        # Process up to 20 messages per frame to handle bursts (like UDS)
        message_count = 0
        while message_count < 20: 
            msg = self.bus.recv(0)  # Non-blocking
            if msg is None:
                break

            message_count += 1
            self.last_can_time = pygame.time.get_ticks()

            # --- Normal Vehicle Data ---
            if msg.arbitration_id == ID_SPEED:
                if len(msg.data) >= 1:
                    try:
                        speed_val = int(msg.data[0])
                        self.target_speed = min(MAX_SPEED_KMH, float(speed_val))
                    except: pass
                elif len(msg.data) >= 4:
                    raw = (msg.data[2] << 8) | msg.data[3]
                    self.target_speed = raw / 100.0

            elif msg.arbitration_id == ID_BLINKER:
                if len(msg.data) >= 1:
                    self.left_signal = bool(msg.data[0] & 0x01)
                    self.right_signal = bool(msg.data[0] & 0x02)

            elif msg.arbitration_id == ID_DOORS:
                # Check each byte independently to allow variable length messages
                # Byte 0: Front-Left
                if len(msg.data) > 0:
                    self.doors[0] = bool(msg.data[0] & 0x01)
                
                # Byte 1: Front-Right
                if len(msg.data) > 1:
                    self.doors[1] = bool(msg.data[1] & 0x01)
                
                # Byte 2: Rear-Left
                if len(msg.data) > 2:
                    self.doors[2] = bool(msg.data[2] & 0x01)
                
                # Byte 3: Rear-Right
                if len(msg.data) > 3:
                    self.doors[3] = bool(msg.data[3] & 0x01)
            
            # --- Diagnostic Request ---
            elif msg.arbitration_id == ID_UDS_REQ:
                self.handle_uds_request(msg)

    def update(self, dt):
        """Update instrument cluster state"""
        self.process_can_messages()

        # Needle Physics
        speed_diff = self.target_speed - self.current_speed
        self.current_speed += speed_diff * NEEDLE_SMOOTHING

        # Needle Angle
        target_angle = ANGLE_AT_0_KMH - (self.current_speed * self.degrees_per_kmh)
        target_angle = max(ANGLE_AT_MAX_KMH, min(ANGLE_AT_0_KMH, target_angle))

        # Angle Smoothing
        angle_diff = target_angle - self.current_angle
        if abs(angle_diff) > 180: # Wrap check
            angle_diff += 360 if angle_diff < 0 else -360
        self.current_angle += angle_diff * NEEDLE_SMOOTHING

        # Blinker Animation
        self.blink_timer += dt
        if self.blink_timer >= (1.0 / BLINK_RATE / 2):
            self.blink_state = not self.blink_state
            self.blink_timer = 0
        
        # Diagnostic Icon Timer
        if self.diag_timer > 0:
            self.diag_timer -= 1
            if self.diag_timer <= 0:
                self.diag_active = False

    def draw_digital_speed(self):
        """Draw digital speed display"""
        speed_text = f"{int(self.current_speed):03d}"
        rect = pygame.Rect(GAUGE_CENTER_X - 60, GAUGE_CENTER_Y + 50, 120, 45)
        pygame.draw.rect(self.screen, (10, 10, 10), rect)
        pygame.draw.rect(self.screen, (51, 51, 51), rect, 2)
        text = self.digital_font.render(speed_text, True, (0, 255, 0))
        text_rect = text.get_rect(center=(GAUGE_CENTER_X, GAUGE_CENTER_Y + 72))
        self.screen.blit(text, text_rect)

    def draw_blinkers(self):
        """Draw turn signal indicators"""
        if self.left_signal and self.blink_state:
            points = [(150, 130), (190, 100), (190, 120), (230, 120), 
                     (230, 140), (190, 140), (190, 160)]
            pygame.draw.polygon(self.screen, (0, 255, 0), points)
            pygame.draw.polygon(self.screen, (0, 200, 0), points, 3)

        if self.right_signal and self.blink_state:
            points = [(1050, 130), (1010, 100), (1010, 120), (970, 120),
                     (970, 140), (1010, 140), (1010, 160)]
            pygame.draw.polygon(self.screen, (0, 255, 0), points)
            pygame.draw.polygon(self.screen, (0, 200, 0), points, 3)

    def draw_door_status(self):
        """Draw door status indicators"""
        door_positions = [(480, 520), (560, 520), (640, 520), (720, 520)]
        for i, (x, y) in enumerate(door_positions):
            if self.doors[i]:
                color = (255, 0, 0)
                fill_color = (100, 0, 0)
            else:
                color = (0, 255, 0)
                fill_color = (0, 50, 0)
            rect = pygame.Rect(x - 25, y - 10, 50, 35)
            pygame.draw.rect(self.screen, fill_color, rect)
            pygame.draw.rect(self.screen, color, rect, 2)
            door_outline = [(x-15, y-5), (x-15, y+20), (x+15, y+20), (x+15, y-5)]
            pygame.draw.lines(self.screen, color, False, door_outline, 2)
            handle_x = x - 18 if i % 2 == 0 else x + 18
            pygame.draw.circle(self.screen, color, (handle_x, y + 7), 2)
            
    def draw_diagnostics_overlay(self):
        """Draws an overlay when UDS diagnostics are active"""
        if self.diag_active:
            # Draw Orange "OBD" Connector Icon
            x, y = WIDTH - 120, 50
            rect = pygame.Rect(x, y, 80, 50)
            pygame.draw.rect(self.screen, (255, 140, 0), rect, border_radius=4)
            pygame.draw.rect(self.screen, (255, 255, 255), rect, 2, border_radius=4)
            
            # Text "DIAG"
            text = self.diag_font.render("DIAG", True, (0, 0, 0))
            self.screen.blit(text, (x + 18, y + 14))
            
            # Info text below
            did_txt = self.small_font.render(f"Read: {self.last_did_read}", True, (255, 140, 0))
            self.screen.blit(did_txt, (x - 20, y + 60))

    def draw_debug_info(self):
        """Draw debug information"""
        fps = self.clock.get_fps()
        info_lines = [
            f"FPS: {fps:.1f}",
            f"Speed: {self.current_speed:.1f} km/h",
            f"CAN: {'Connected' if self.bus else 'DEMO'}",
        ]
        y = 10
        for line in info_lines:
            text = self.small_font.render(line, True, (100, 200, 100))
            self.screen.blit(text, (10, y))
            y += 20

    def handle_demo_input(self):
        """Handle keyboard input for demo mode"""
        if not self.bus:
            keys = pygame.key.get_pressed()
            if keys[pygame.K_UP]: self.target_speed = min(MAX_SPEED_KMH, self.target_speed + 2)
            if keys[pygame.K_DOWN]: self.target_speed = max(0, self.target_speed - 2)
            if keys[pygame.K_LEFT]: self.left_signal = True
            else: self.left_signal = False
            if keys[pygame.K_RIGHT]: self.right_signal = True
            else: self.right_signal = False
            if keys[pygame.K_1]: self.doors[0] = not self.doors[0]; pygame.time.wait(200)
            if keys[pygame.K_2]: self.doors[1] = not self.doors[1]; pygame.time.wait(200)
            if keys[pygame.K_3]: self.doors[2] = not self.doors[2]; pygame.time.wait(200)
            if keys[pygame.K_4]: self.doors[3] = not self.doors[3]; pygame.time.wait(200)

    def run(self):
        """Main loop"""
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        running = False

            self.handle_demo_input()
            self.update(dt)

            self.screen.blit(self.bg_image, (0, 0))
            rotated_needle, needle_pos = self.rotate_needle(self.current_angle)
            self.screen.blit(rotated_needle, needle_pos)

            self.draw_digital_speed()
            self.draw_blinkers()
            self.draw_door_status()
            self.draw_diagnostics_overlay() # New overlay
            self.draw_debug_info()

            pygame.display.flip()
            self.frame_count += 1

        print("\n👋 Shutting down...")
        if self.bus: self.bus.shutdown()
        pygame.quit()

if __name__ == "__main__":
    try:
        InstrumentCluster().run()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
