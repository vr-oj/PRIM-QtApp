import imagingcontrol4 as ic4
from imagingcontrol4.library import Library
from imagingcontrol4.grabber import Grabber
from imagingcontrol4.devenum import DeviceEnum

print("=== Testing device_open() ===")
Library.init(
    "C:/Program Files/The Imaging Source Europe GmbH/IC4 GenTL Driver for USB3Vision Devices 1.4/bin/ic4-gentl-u3v_x64.cti"
)

devices = DeviceEnum.devices()
print(f"Devices found: {len(devices)}")
for i, dev in enumerate(devices):
    print(f"[{i}] {dev.model_name} - {dev.serial}")

if devices:
    grabber = Grabber()
    device = grabber.device_open(devices[0])
    if device:
        print("✅ Device opened successfully!")
        grabber.device_close()
    else:
        print("❌ device_open() returned None.")
Library.exit()
