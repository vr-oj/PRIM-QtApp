import imagingcontrol4 as ic4


def test_camera_open():
    print("=== IC4 Camera Open Test ===")
    try:
        ic4.Library.init()  # Required initialization
        devices = ic4.DeviceEnum.devices()
        if not devices:
            print("No devices found.")
            return

        for idx, dev in enumerate(devices):
            print(f"[{idx}] {dev.model_name} - Serial: {dev.serial}")

        target = devices[0]
        print(f"Attempting to open: {target.model_name} (Serial: {target.serial})")

        grabber = ic4.Grabber()
        device = grabber.device_open(target)
        if device is None:
            print("❌ grabber.device_open() returned None.")
        else:
            print("✅ Camera opened successfully.")
            pm = device.property_map
            print("Available Properties:")
            for prop in pm.properties():
                print(f"  - {prop.name}")
            grabber.device_close()
            print("Camera closed.")

    except Exception as e:
        print(f"Exception occurred: {e}")
    finally:
        try:
            ic4.Library.exit()  # Clean up
            print("Library exited cleanly.")
        except:
            pass


if __name__ == "__main__":
    test_camera_open()
