import glob
import serial.tools.list_ports

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
