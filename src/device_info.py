import imagingcontrol4 as ic4

ic4.Library.init()

grabber = ic4.Grabber()
dev = ic4.DeviceEnum.devices()[0]
grabber.device_open(dev)

pm = grabber.device_property_map
# List any property names containing 'format'
fmt_props = [prop.name for prop in pm.properties if "format" in prop.name.lower()]
print("Format-related properties:", fmt_props)
