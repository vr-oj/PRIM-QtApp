# test_ic4_enum.py
import imagingcontrol4 as ic4


def main():
    try:
        grab = ic4.Grabber()  # construct the Grabber
        devices = grab.device_info.enumerate()  # attempt to enumerate
        if not devices:
            print("→ No devices found.")
        else:
            print("→ Found devices:")
            for i, dev in enumerate(devices):
                # display_name is the human‐readable string you saw in IC Capture
                print(f"  {i}: {dev.display_name!r}")
    except Exception as e:
        print("Exception during Grabber/device enumeration:")
        print(" ", e)


if __name__ == "__main__":
    main()
