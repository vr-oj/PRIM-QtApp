import imagingcontrol4 as ic4

ic4.Library.init()
grabber = ic4.Grabber()
grabber.device_open(ic4.DeviceEnum.devices()[0])
pm = grabber.device_property_map

# Try the most common enumeration names:
for name in (
    "VideoFormat",
    "Video Format",
    "AcquisitionVideoFormat",
    "AcquisitionFormat",
):
    enum = pm.find_enumeration(name)
    print(f"{name!r} →", "FOUND" if enum and enum.is_available else "not found")
    if enum and enum.is_available:
        print("    entries:", [e.name for e in enum.entries])
