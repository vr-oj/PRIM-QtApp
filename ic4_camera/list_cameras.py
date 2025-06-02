# list_cameras.py

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
        # DeviceInfo has at least .model_name and .display_name
        print(
            f"  [{idx}] model_name = {info.model_name}, display_name = {info.display_name}"
        )


if __name__ == "__main__":
    main()
