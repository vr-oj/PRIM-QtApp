import cv2

# Change this to try a different camera index if needed
CAMERA_INDEX = 0

cap = cv2.VideoCapture(CAMERA_INDEX)
if not cap.isOpened():
    print(f"❌ Could not open camera at index {CAMERA_INDEX}")
    exit(1)

print(f"✅ Opened camera at index {CAMERA_INDEX}")
print("=== Camera Properties ===")

# Define OpenCV property names
property_names = {
    cv2.CAP_PROP_FRAME_WIDTH: "Frame Width",
    cv2.CAP_PROP_FRAME_HEIGHT: "Frame Height",
    cv2.CAP_PROP_FPS: "FPS",
    cv2.CAP_PROP_FOURCC: "FOURCC (codec)",
    cv2.CAP_PROP_AUTO_EXPOSURE: "Auto Exposure",
    cv2.CAP_PROP_EXPOSURE: "Exposure",
    cv2.CAP_PROP_BRIGHTNESS: "Brightness",
    cv2.CAP_PROP_CONTRAST: "Contrast",
    cv2.CAP_PROP_SATURATION: "Saturation",
    cv2.CAP_PROP_HUE: "Hue",
    cv2.CAP_PROP_GAIN: "Gain",
    cv2.CAP_PROP_BACKLIGHT: "Backlight Compensation",
    cv2.CAP_PROP_TEMPERATURE: "White Balance Temperature",
    cv2.CAP_PROP_AUTO_WB: "Auto White Balance",
    cv2.CAP_PROP_RECTIFICATION: "Rectification",
}

# Print each property value
for prop_id, name in property_names.items():
    value = cap.get(prop_id)
    if value != -1 and value != 0:
        print(f"{name}: {value:.2f}")
    else:
        print(f"{name}: Not supported or 0")

cap.release()
