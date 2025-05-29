
import imagingcontrol4 as ic4

def test_camera_open_and_reset():
    print("=== IC4 Camera Open + Property Reset Test ===")
    try:
        ic4.Library.init()
        devices = ic4.DeviceEnum.devices()
        if not devices:
            print("No cameras detected.")
            return

        for i, dev in enumerate(devices):
            print(f"[{i}] {dev.model_name} - Serial: {dev.serial}")

        cam = devices[0]
        print(f"Trying to open: {cam.model_name} (Serial: {cam.serial})")
        grabber = ic4.Grabber()
        device = grabber.device_open(cam)

        if device is None:
            print("❌ Failed to open device with grabber.device_open()")
            return
        else:
            print("✅ Camera opened successfully!")

        if hasattr(device, "reset_properties"):
            try:
                device.reset_properties()
                print("🔄 Properties reset to default.")
            except Exception as e:
                print(f"⚠️ Failed to reset properties: {e}")

        pm = device.property_map
        print("Available camera properties:")
        for prop in pm.properties():
            print(f" - {prop.name}")

        grabber.device_close()
        print("📴 Camera closed cleanly.")

    except Exception as e:
        print(f"💥 Exception: {e}")
    finally:
        try:
            ic4.Library.exit()
            print("✅ Library exited cleanly.")
        except:
            pass

if __name__ == "__main__":
    test_camera_open_and_reset()
