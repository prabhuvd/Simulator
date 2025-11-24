#!/usr/bin/env python3
"""
Realistic CAN Bus Instrument Cluster
Features smooth needle animation and professional styling
"""

import pygame
import can
import sys
import os
import math

# === CONFIGURATION ===
CAN_INTERFACE = 'vcan0'
WIDTH, HEIGHT = 1200, 600
FPS = 60

# CAN Message IDs
ID_SPEED   = 0x244
ID_BLINKER = 0x188
ID_DOORS   = 0x19B

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
        pygame.display.set_caption("CAN Instrument Cluster")
        self.clock = pygame.time.Clock()
        
        # Fonts
        self.digital_font = pygame.font.SysFont("Courier New", 32, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 16)
        
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
        
        # Statistics
        self.frame_count = 0
        self.last_can_time = pygame.time.get_ticks()
        
        # Setup CAN bus
        self.setup_can()
        
        print("\n" + "="*70)
        print("🚗 FuzzyTech's FuzzCAN - INSTRUMENT CLUSTER")
        print("="*70)
        print(f"Resolution: {WIDTH}x{HEIGHT} @ {FPS} FPS")
        print(f"Gauge: 0-{MAX_SPEED_KMH} km/h")
        print(f"Smoothing: {NEEDLE_SMOOTHING} (Lower = Smoother)")
        print("="*70)
        print("Controls:")
        print("  Q = Quit")
        print("  ↑/↓ = Speed (Demo mode)")
        print("  ←/→ = Turn signals (Demo mode)")
        print("  1/2/3/4 = Toggle doors FL/FR/RL/RR (Demo mode)")
        print("="*70 + "\n")
    
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
            print(f"  Listening for:")
            print(f"    Speed:    0x{ID_SPEED:03X}")
            print(f"    Blinkers: 0x{ID_BLINKER:03X}")
            print(f"    Doors:    0x{ID_DOORS:03X}")
        except OSError as e:
            print(f"⚠ CAN interface not available: {e}")
            print(f"\n📋 To setup vcan0:")
            print("   sudo modprobe vcan")
            print("   sudo ip link add dev vcan0 type vcan")
            print("   sudo ip link set up vcan0")
            print("\n▶ Running in DEMO mode (use arrow keys)")
            self.bus = None
    
    def rotate_needle(self, angle):
        """Rotate needle image around pivot point - FIXED centering"""
        # The pivot point in the needle image (where it connects to gauge center)
        pivot_x, pivot_y = 12, 20
        
        # Rotate the entire image
        rotated_image = pygame.transform.rotate(self.needle_original, angle)
        
        # Get the rect of the rotated image
        rotated_rect = rotated_image.get_rect()
        
        # Calculate where the pivot point moved to after rotation
        # We need to find the new position of the pivot point in the rotated image
        image_center = (self.needle_original.get_width() / 2, self.needle_original.get_height() / 2)
        pivot_offset = pygame.math.Vector2(pivot_x - image_center[0], pivot_y - image_center[1])
        rotated_offset = pivot_offset.rotate(-angle)
        
        # Position the rotated image so the pivot point is at GAUGE_CENTER
        rotated_rect.center = (GAUGE_CENTER_X - rotated_offset.x, 
                               GAUGE_CENTER_Y - rotated_offset.y)
        
        return rotated_image, rotated_rect
    
    def process_can_messages(self):
        """Read and process CAN messages"""
        if not self.bus:
            return
        
        message_count = 0
        while message_count < 10:  # Limit messages per frame
            msg = self.bus.recv(0)  # Non-blocking
            if msg is None:
                break
            
            message_count += 1
            self.last_can_time = pygame.time.get_ticks()
            
            if msg.arbitration_id == ID_SPEED:
                # Speed: bytes 2-3, big-endian, value/100 = km/h
                if len(msg.data) >= 4:
                    raw = (msg.data[2] << 8) | msg.data[3]
                    self.target_speed = raw / 100.0
                    
            elif msg.arbitration_id == ID_BLINKER:
                # Blinker: byte 0, bit 0=left, bit 1=right
                if len(msg.data) >= 1:
                    self.left_signal = bool(msg.data[0] & 0x01)
                    self.right_signal = bool(msg.data[0] & 0x02)
                    
            elif msg.arbitration_id == ID_DOORS:
                # Door status: each byte represents a door (0=closed, 1=open)
                # Byte 0: Front-Left, Byte 1: Front-Right
                # Byte 2: Rear-Left,  Byte 3: Rear-Right
                if len(msg.data) >= 4:
                    new_doors = [
                        bool(msg.data[0] & 0x01),  # Front-Left
                        bool(msg.data[1] & 0x01),  # Front-Right
                        bool(msg.data[2] & 0x01),  # Rear-Left
                        bool(msg.data[3] & 0x01)   # Rear-Right
                    ]
                    if new_doors != self.doors:
                        self.doors = new_doors
                        door_names = ['FL', 'FR', 'RL', 'RR']
                        open_doors = [door_names[i] for i, open in enumerate(self.doors) if open]
                        if open_doors:
                            print(f"🚪 Doors OPEN: {', '.join(open_doors)}")
                        else:
                            print(f"🚪 All doors CLOSED")
    
    def update(self, dt):
        """Update instrument cluster state"""
        # Process CAN messages
        self.process_can_messages()
        
        # Smooth needle movement using exponential smoothing
        speed_diff = self.target_speed - self.current_speed
        self.current_speed += speed_diff * NEEDLE_SMOOTHING
        
        # Calculate needle angle
        target_angle = ANGLE_AT_0_KMH - (self.current_speed * self.degrees_per_kmh)
        target_angle = max(ANGLE_AT_MAX_KMH, min(ANGLE_AT_0_KMH, target_angle))
        
        # Smooth angle transition
        angle_diff = target_angle - self.current_angle
        # Handle angle wrapping
        if abs(angle_diff) > 180:
            if angle_diff > 0:
                angle_diff -= 360
            else:
                angle_diff += 360
        
        self.current_angle += angle_diff * NEEDLE_SMOOTHING
        
        # Update blinker animation
        self.blink_timer += dt
        if self.blink_timer >= (1.0 / BLINK_RATE / 2):
            self.blink_state = not self.blink_state
            self.blink_timer = 0
    
    def draw_digital_speed(self):
        """Draw digital speed display"""
        speed_text = f"{int(self.current_speed):03d}"
        
        # Draw background rectangle
        rect = pygame.Rect(GAUGE_CENTER_X - 60, GAUGE_CENTER_Y + 50, 120, 45)
        pygame.draw.rect(self.screen, (10, 10, 10), rect)
        pygame.draw.rect(self.screen, (51, 51, 51), rect, 2)
        
        # Draw speed text
        text = self.digital_font.render(speed_text, True, (0, 255, 0))
        text_rect = text.get_rect(center=(GAUGE_CENTER_X, GAUGE_CENTER_Y + 72))
        self.screen.blit(text, text_rect)
    
    def draw_blinkers(self):
        """Draw turn signal indicators - Icons swapped to match text position"""
        # LEFT indicator (on left side of screen) - arrow points RIGHT
        if self.left_signal and self.blink_state:
            points = [(150, 130), (190, 100), (190, 120), (230, 120), 
                     (230, 140), (190, 140), (190, 160)]
            pygame.draw.polygon(self.screen, (0, 255, 0), points)
            pygame.draw.polygon(self.screen, (0, 200, 0), points, 3)
        
        # RIGHT indicator (on right side of screen) - arrow points LEFT
        if self.right_signal and self.blink_state:
            points = [(1050, 130), (1010, 100), (1010, 120), (970, 120),
                     (970, 140), (1010, 140), (1010, 160)]
            pygame.draw.polygon(self.screen, (0, 255, 0), points)
            pygame.draw.polygon(self.screen, (0, 200, 0), points, 3)
    
    def draw_door_status(self):
        """Draw door status indicators"""
        door_positions = [
            (480, 520),  # Front-Left
            (560, 520),  # Front-Right
            (640, 520),  # Rear-Left
            (720, 520)   # Rear-Right
        ]
        
        for i, (x, y) in enumerate(door_positions):
            if self.doors[i]:
                # Door is OPEN - draw in RED
                color = (255, 0, 0)
                fill_color = (100, 0, 0)
            else:
                # Door is CLOSED - draw in GREEN
                color = (0, 255, 0)
                fill_color = (0, 50, 0)
            
            # Draw door rectangle
            rect = pygame.Rect(x - 25, y - 10, 50, 35)
            pygame.draw.rect(self.screen, fill_color, rect)
            pygame.draw.rect(self.screen, color, rect, 2)
            
            # Draw door outline
            door_outline = [
                (x - 15, y - 5), (x - 15, y + 20),
                (x + 15, y + 20), (x + 15, y - 5)
            ]
            pygame.draw.lines(self.screen, color, False, door_outline, 2)
            
            # Draw door handle
            handle_x = x - 18 if i % 2 == 0 else x + 18  # Left side for FL/RL, right for FR/RR
            pygame.draw.circle(self.screen, color, (handle_x, y + 7), 2)
    
    def draw_debug_info(self):
        """Draw debug information"""
        fps = self.clock.get_fps()
        
        info_lines = [
            f"FPS: {fps:.1f}",
            f"Speed: {self.current_speed:.1f} km/h (Target: {self.target_speed:.1f})",
            f"Angle: {self.current_angle:.1f}°",
            f"CAN: {'Connected' if self.bus else 'DEMO'}",
        ]
        
        y = 10
        for line in info_lines:
            text = self.small_font.render(line, True, (100, 200, 100))
            self.screen.blit(text, (10, y))
            y += 20
        
        # Draw center marker to verify needle centering (for debugging)
        # Uncomment these lines to see the exact gauge center
        # pygame.draw.circle(self.screen, (255, 0, 0), (GAUGE_CENTER_X, GAUGE_CENTER_Y), 5, 1)
        # pygame.draw.line(self.screen, (255, 0, 0), (GAUGE_CENTER_X-10, GAUGE_CENTER_Y), (GAUGE_CENTER_X+10, GAUGE_CENTER_Y), 1)
        # pygame.draw.line(self.screen, (255, 0, 0), (GAUGE_CENTER_X, GAUGE_CENTER_Y-10), (GAUGE_CENTER_X, GAUGE_CENTER_Y+10), 1)
    
    def handle_demo_input(self):
        """Handle keyboard input for demo mode"""
        if not self.bus:
            keys = pygame.key.get_pressed()
            if keys[pygame.K_UP]:
                self.target_speed = min(MAX_SPEED_KMH, self.target_speed + 2)
            if keys[pygame.K_DOWN]:
                self.target_speed = max(0, self.target_speed - 2)
            if keys[pygame.K_LEFT]:
                self.left_signal = True   # Left arrow activates LEFT blinker (left side)
            else:
                self.left_signal = False
            if keys[pygame.K_RIGHT]:
                self.right_signal = True  # Right arrow activates RIGHT blinker (right side)
            else:
                self.right_signal = False
            
            # Door controls (1-4 keys toggle doors)
            if keys[pygame.K_1]:
                self.doors[0] = not self.doors[0]  # Toggle Front-Left
                pygame.time.wait(200)  # Debounce
            if keys[pygame.K_2]:
                self.doors[1] = not self.doors[1]  # Toggle Front-Right
                pygame.time.wait(200)
            if keys[pygame.K_3]:
                self.doors[2] = not self.doors[2]  # Toggle Rear-Left
                pygame.time.wait(200)
            if keys[pygame.K_4]:
                self.doors[3] = not self.doors[3]  # Toggle Rear-Right
                pygame.time.wait(200)
    
    def run(self):
        """Main loop"""
        running = True
        
        while running:
            dt = self.clock.tick(FPS) / 1000.0  # Delta time in seconds
            
            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        running = False
            
            # Demo mode input
            self.handle_demo_input()
            
            # Update state
            self.update(dt)
            
            # Draw everything
            self.screen.blit(self.bg_image, (0, 0))
            
            # Draw needle
            rotated_needle, needle_pos = self.rotate_needle(self.current_angle)
            self.screen.blit(rotated_needle, needle_pos)
            
            # Draw digital display
            self.draw_digital_speed()
            
            # Draw blinkers
            self.draw_blinkers()
            
            # Draw door status
            self.draw_door_status()
            
            # Draw debug info
            self.draw_debug_info()
            
            # Update display
            pygame.display.flip()
            self.frame_count += 1
            
            # Log speed changes
            if self.frame_count % 60 == 0 and self.target_speed > 0:
                print(f"Speed: {self.current_speed:6.1f} km/h | "
                      f"Angle: {self.current_angle:6.1f}° | "
                      f"FPS: {self.clock.get_fps():.0f}")
        
        # Cleanup
        print("\n👋 Shutting down...")
        if self.bus:
            self.bus.shutdown()
        pygame.quit()

def main():
    """Main entry point"""
    try:
        cluster = InstrumentCluster()
        cluster.run()
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()