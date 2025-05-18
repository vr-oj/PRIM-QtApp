# list_propids.py
import imagingcontrol4 as ic4
import inspect

print("All PropId members:")
print([name for name in dir(ic4.PropId) if not name.startswith("_")])

# Optionally, filter for integer constants (most PropIds are ints)
ints = [
    name for name, val in inspect.getmembers(ic4.PropId, lambda v: isinstance(v, int))
]
print("\nPropId integer members:")
print(ints)
