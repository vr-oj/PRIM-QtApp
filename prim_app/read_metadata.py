import tifffile, json

with tifffile.TiffFile("recording_XXXX_video.tif") as tif:
    for page in tif.pages:
        desc = page.tags["ImageDescription"].value
        data = json.loads(desc)
        print(data["frameIdx"], data["deviceTime"], data["pressure"])
