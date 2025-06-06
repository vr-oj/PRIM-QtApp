import tifffile
import json

# Replace "recording_video.tif" with the actual file name (or full path)
tif_path = "C:/Users/Tykocki Lab - PRIM/Documents/PRIMAcquisition Results/2025-06-06/Fill1/recording_2025-06-06_12-35-41_video.tif"

with tifffile.TiffFile(tif_path) as tif:
    for page in tif.pages:
        desc = page.tags["ImageDescription"].value
        data = json.loads(desc)
        print(
            f"frameIdx={data['frameIdx']},  deviceTime={data['deviceTime']},  pressure={data['pressure']}"
        )
