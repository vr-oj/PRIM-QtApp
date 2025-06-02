import imagingcontrol4 as ic4

ic4.Library.init()
devs = ic4.DeviceEnum.devices()
if len(devs) == 0:
    print("No devices found!")
    exit(0)

dev = devs[0]  # e.g. the DMK 33UP5000
grab = ic4.Grabber()
grab.device_open(dev)

# List all enumeration nodes under device_property_map:
enum_nodes = grab.device_property_map.all
print("All enum names under device_property_map:")
for p in enum_nodes:
    if isinstance(p, ic4.PropEnumeration):
        print("  •", p.name)
grab.device_close()
ic4.Library.exit()
