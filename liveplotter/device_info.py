import imagingcontrol4 as ic4

ic4.Library.init()

grabber = ic4.Grabber()
grabber.device_open(ic4.DeviceEnum.devices()[0])
pm = grabber.device_property_map

# Drill into AcquisitionControl
acq_cat = pm.find_category("AcquisitionControl")
if not acq_cat:
    print("AcquisitionControl category not found; available root categories:")
    for c in pm.root_category.categories:
        print("  ", c.name)
    exit()

print("Features in AcquisitionControl:")
for feat in acq_cat.features:
    print("  ", feat.name)
