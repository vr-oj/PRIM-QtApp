import imagingcontrol4 as ic4

grabber = ic4.Grabber()
dev = ic4.DeviceEnum.devices()[0]
grabber.device_open(dev)

# List out anything with “video” in its name on both DeviceInfo and Grabber:
di = grabber.device_info
print("---- DeviceInfo attrs ----")
for a in sorted(dir(di)):
    if "video" in a.lower():
        print(a)

print("\n---- Grabber attrs ----")
for a in sorted(dir(grabber)):
    if "video" in a.lower():
        print(a)
