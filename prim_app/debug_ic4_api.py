# file: debug_ic4_inspect.py
import imagingcontrol4 as ic4

print("Attributes in imagingcontrol4:")
print(dir(ic4))

if hasattr(ic4, "Grabber"):
    g = ic4.Grabber()
    print("Grabber object methods:")
    print(dir(g))
