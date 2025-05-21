import imagingcontrol4 as ic4

# initialize the underlying IC-ImagingControl core
ic4.Library.init()

grabber = ic4.Grabber()
dev = ic4.DeviceEnum.devices()[0]
grabber.device_open(dev)

di = grabber.device_info
print("---- DeviceInfo attrs ----")
for a in sorted(dir(di)):
    if "video" in a.lower():
        print(a)

print("\n---- Grabber attrs ----")
for a in sorted(dir(grabber)):
    if "video" in a.lower():
        print(a)
