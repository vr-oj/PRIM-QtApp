import glob
import serial.tools.list_ports
import cv2

def list_serial_ports():
    """
    Return a list of (port, description) for all available serial ports.
    """
    ports = serial.tools.list_ports.comports()
    return [(p.device, p.description) for p in ports]


def timestamped_filename(prefix, ext):
    """
    e.g. timestamped_filename('trial', 'csv') -> 'trial_20250513-142501.csv'
    """
    import time
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{prefix}_{ts}.{ext}"

def list_cameras(max_idx=5):
    """
    Probe the first max_idx camera indices and return a list of
    indices that respond with at least one frame.
    """
    cams = []
    for idx in range(max_idx):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)  # on Windows
        if not cap.isOpened():
            cap.release()
            continue
        ret, _ = cap.read()
        cap.release()
        if ret:
            cams.append(idx)
    return cams
