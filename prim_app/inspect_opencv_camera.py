import cv2

# Use DirectShow backend on Windows
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if cap.isOpened():
    print("✅ Opened camera at index 0 using DirectShow")

    # Attempt to set resolution
    print("\n--- Attempting to set resolution to 1920x1080 ---")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    # Attempt to set Auto Exposure ON
    print("\n--- Trying Auto Exposure ON (0.75) ---")
    success_on = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
    print(f"Set Auto Exposure to 0.75 → success: {success_on}")

    # Read current values
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    auto_exp = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
    exposure = cap.get(cv2.CAP_PROP_EXPOSURE)
    gain = cap.get(cv2.CAP_PROP_GAIN)

    print("\n=== Camera Properties After Auto ON ===")
    print(f"Frame Width: {width}")
    print(f"Frame Height: {height}")
    print(f"Auto Exposure: {auto_exp}")
    print(f"Exposure: {exposure}")
    print(f"Gain: {gain}")

    # Now try turning Auto Exposure OFF
    print("\n--- Trying Auto Exposure OFF (0.25) ---")
    success_off = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    print(f"Set Auto Exposure to 0.25 → success: {success_off}")

    # Read again
    auto_exp_off = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
    exposure_off = cap.get(cv2.CAP_PROP_EXPOSURE)

    print("\n=== Camera Properties After Auto OFF ===")
    print(f"Auto Exposure: {auto_exp_off}")
    print(f"Exposure: {exposure_off}")

    cap.release()
else:
    print("❌ Failed to open camera")
