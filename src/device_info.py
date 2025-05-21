import imagingcontrol4 as ic4

ic4.Library.init()

grabber = ic4.Grabber()
grabber.device_open(ic4.DeviceEnum.devices()[0])
pm = grabber.device_property_map

print("=== PropertyMap members ===")
for attr in sorted(dir(pm)):
    if not attr.startswith("_"):
        print(attr)
