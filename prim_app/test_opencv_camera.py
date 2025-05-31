import cv2

cap = cv2.VideoCapture(0)
if cap.isOpened():
    print("✅ OpenCV camera opened!")
    ret, frame = cap.read()
    if ret:
        print("✅ Captured frame size:", frame.shape)
    else:
        print("❌ Failed to capture frame.")
else:
    print("❌ OpenCV cannot open this camera.")
cap.release()
