import time, cv2
import serial.tools.list_ports

def list_serial_ports():
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]

def timestamped_filename(prefix, ext):
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{prefix}_{ts}.{ext}"

def list_cameras(max_idx=5):
    cams = []
    for i in range(max_idx):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened() and cap.read()[0]:
            cams.append(i)
        cap.release()
    return cams
