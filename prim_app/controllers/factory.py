from .arduino_serial import ArduinoSerialController
from .ic4_camera import IC4CameraController


def create_arduino(port: str):
    return ArduinoSerialController(port)


def create_ic4_camera(device_info):
    return IC4CameraController(device_info)
