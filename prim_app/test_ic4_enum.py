# test_ic4_enum.py
import imagingcontrol4 as ic4


def main():
    try:
        # ─── Initialize the IC4 library first ────────────────────────
        ic4.Library.init()

        grab = ic4.Grabber()
        devices = grab.device_info.enumerate()

        if not devices:
            print("→ No devices found.")
        else:
            print("→ Found devices:")
            for i, dev in enumerate(devices):
                print(f"  {i}: {dev.display_name!r}")

        # Always close the library when you’re done:
        grab.device_close()
        ic4.Library.close()  # or ic4.Library.destroy(), depending on version

    except Exception as e:
        print("Exception during Grabber/device enumeration:")
        print(" ", e)


if __name__ == "__main__":
    main()
