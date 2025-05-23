from PIL import Image

sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
img = Image.open("A_flat_vector_icon_depicts_a_schematic_representat.png")
img.save("PRIM.ico", sizes=sizes)
