#!/usr/bin/env python3
"""
LED Test Script for Bin LED Reminder
Tests all LED functions and colors
"""

import math
import blinkt
import time
import sys
from datetime import datetime

def clear_leds():
    """Clear all LEDs"""
    blinkt.clear()
    blinkt.show()

def test_basic_functionality():
    """Test basic LED functionality"""
    print("🔧 Testing basic LED functionality...")
    
    # Test all LEDs red
    print("   → All LEDs RED for 2 seconds")
    blinkt.set_all(255, 0, 0, 0.1)
    blinkt.show()
    time.sleep(2)
    
    # Test all LEDs green
    print("   → All LEDs GREEN for 2 seconds")
    blinkt.set_all(0, 255, 0, 0.1)
    blinkt.show()
    time.sleep(2)
    
    # Test all LEDs blue
    print("   → All LEDs BLUE for 2 seconds")
    blinkt.set_all(0, 0, 255, 0.1)
    blinkt.show()
    time.sleep(2)
    
    clear_leds()
    print("   ✅ Basic functionality test complete")

def test_individual_leds():
    """Test each LED individually"""
    print("🔍 Testing individual LEDs...")
    
    clear_leds()
    
    for i in range(8):
        print(f"   → LED {i} (white)")
        blinkt.set_pixel(i, 255, 255, 255, 0.1)
        blinkt.show()
        time.sleep(0.3)
        clear_leds()
        time.sleep(0.1)
    
    print("   ✅ Individual LED test complete")

def test_bin_colors():
    """Test actual bin collection colors"""
    print("🗑️  Testing bin collection colors...")
    
    # Blue bin test
    print("   → BLUE BIN color (recycling)")
    blinkt.set_all(0, 0, 255, 0.1)
    blinkt.show()
    time.sleep(3)
    
    # Green bin test  
    print("   → GREEN BIN color (garden waste)")
    blinkt.set_all(0, 255, 0, 0.1)
    blinkt.show()
    time.sleep(3)
    
    # Error state test
    print("   → ERROR STATE color (red)")
    blinkt.set_all(255, 0, 0, 0.1)
    blinkt.show()
    time.sleep(3)
    
    clear_leds()
    print("   ✅ Bin color test complete")

def test_brightness_levels():
    """Test different brightness levels"""
    print("💡 Testing brightness levels...")
    
    brightness_levels = [0.02, 0.05, 0.1, 0.2, 0.5]
    
    for brightness in brightness_levels:
        print(f"   → Brightness {brightness} (blue)")
        blinkt.set_all(0, 0, 255, brightness)
        blinkt.show()
        time.sleep(1.5)
    
    clear_leds()
    print("   ✅ Brightness test complete")

def test_breathing_effect():
    """Test breathing/pulsing effect"""
    print("🫁 Testing breathing effect (5 seconds)...")
    
    start_time = time.time()
    while time.time() - start_time < 5:
        # Calculate breathing brightness
        progress = (time.time() - start_time) * 2  # Speed multiplier
        brightness = (math.sin(progress) + 1) * 0.05  # 0 to 0.1 range
        
        blinkt.set_all(0, 0, 255, brightness)
        blinkt.show()
        time.sleep(0.05)
    
    clear_leds()
    print("   ✅ Breathing effect test complete")

def test_service_integration():
    """Test integration with service logic"""
    print("⚙️  Testing service integration...")
    
    try:
        from bin_led_service import BinLEDService
        
        service = BinLEDService()
        
        # Test schedule detection
        schedule = service.detect_collection_schedule()
        if schedule:
            print(f"   → Detected schedule: {schedule['collection_day']} collection")
            print(f"   → Reminder day: {schedule['reminder_day']}")
            print(f"   → Bins due: {schedule['bins_due']}")
            
            # Test what colors would show
            if schedule['bins_due']:
                primary_bin = schedule['bins_due'][0]
                if "Blue" in primary_bin:
                    print("   → Would show: BLUE LEDs")
                    blinkt.set_all(0, 0, 255, 0.1)
                elif "Green" in primary_bin or "Brown" in primary_bin:
                    print("   → Would show: GREEN LEDs")
                    blinkt.set_all(0, 255, 0, 0.1)
                
                blinkt.show()
                time.sleep(2)
                clear_leds()
        else:
            print("   → No schedule detected")
        
        print("   ✅ Service integration test complete")
        
    except ImportError:
        print("   ⚠️  Could not import bin_led_service - skipping integration test")
    except Exception as e:
        print(f"   ⚠️  Integration test failed: {e}")

def interactive_test():
    """Interactive LED testing"""
    print("🎮 Interactive mode - press Enter for each test...")
    
    input("Press Enter to test RED LEDs...")
    blinkt.set_all(255, 0, 0, 0.1)
    blinkt.show()
    
    input("Press Enter to test GREEN LEDs...")
    blinkt.set_all(0, 255, 0, 0.1)
    blinkt.show()
    
    input("Press Enter to test BLUE LEDs...")
    blinkt.set_all(0, 0, 255, 0.1)
    blinkt.show()
    
    input("Press Enter to test WHITE LEDs...")
    blinkt.set_all(255, 255, 255, 0.1)
    blinkt.show()
    
    input("Press Enter to clear LEDs...")
    clear_leds()
    
    print("   ✅ Interactive test complete")

def main():
    """Main test runner"""
    print("🧪 Bin LED Reminder - LED Test Suite")
    print("=" * 50)
    print(f"Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    if len(sys.argv) > 1:
        test_type = sys.argv[1].lower()
        
        if test_type == "basic":
            test_basic_functionality()
        elif test_type == "individual":
            test_individual_leds()
        elif test_type == "colors":
            test_bin_colors()
        elif test_type == "brightness":
            test_brightness_levels()
        elif test_type == "breathing":
            test_breathing_effect()
        elif test_type == "service":
            test_service_integration()
        elif test_type == "interactive":
            interactive_test()
        else:
            print(f"Unknown test type: {test_type}")
            print("Available tests: basic, individual, colors, brightness, breathing, service, interactive")
            sys.exit(1)
    else:
        # Run all tests
        try:
            test_basic_functionality()
            print()
            
            test_individual_leds()
            print()
            
            test_bin_colors()
            print()
            
            test_brightness_levels()
            print()
            
            test_breathing_effect()
            print()
            
            test_service_integration()
            print()
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Test interrupted by user")
            clear_leds()
            sys.exit(0)
        except Exception as e:
            print(f"\n\n❌ Test failed with error: {e}")
            clear_leds()
            sys.exit(1)
    
    print()
    print("🎉 All tests completed successfully!")
    print("LEDs should now be off.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted")
        clear_leds()
    except Exception as e:
        print(f"\n\n❌ Test failed: {e}")
        clear_leds()
        sys.exit(1)
