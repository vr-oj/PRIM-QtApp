# File: list_cameras.py

import imagingcontrol4 as ic4


def main():
    try:
        ic4.Library.init()
    except ic4.IC4Exception as e:
        print("Library.init() failed:", e)
        return

    try:
        devices = ic4.DeviceEnum.devices()
    except ic4.IC4Exception as e:
        print("DeviceEnum.devices() failed:", e)
        return

    if not devices:
        print("No IC4 cameras found.")
        return

    print("Detected IC4 cameras:")
    for idx, info in enumerate(devices):
        # DeviceInfo has model_name; it might also have uri or other fields you can inspect via dir(info)
        print(f"  [{idx}] model_name = {info.model_name}")


if __name__ == "__main__":
    main()
