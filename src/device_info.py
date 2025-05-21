import imagingcontrol4 as ic4

ic4.Library.init()

grabber = ic4.Grabber()
dev = ic4.DeviceEnum.devices()[0]
grabber.device_open(dev)

di = grabber.device_info
print("---- DeviceInfo attrs containing 'format' ----")
for a in sorted(dir(di)):
    if "format" in a.lower():
        print(a)

print("\n---- Grabber attrs containing 'format' ----")
for a in sorted(dir(grabber)):
    if "format" in a.lower():
        print(a)
