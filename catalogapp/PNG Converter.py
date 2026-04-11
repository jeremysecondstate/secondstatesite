import os
from tkinter import Tk, filedialog
from PIL import Image

# Hide root Tk window
root = Tk()
root.withdraw()

# Prompt user to select a folder
folder_path = filedialog.askdirectory(title="Select Folder")

if not folder_path:
    print("No folder selected. Exiting.")
    exit()

# Supported image extensions
image_extensions = ('.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp', '.png')

for root_dir, _, files in os.walk(folder_path):
    for file in files:
        if file.lower().endswith(image_extensions):
            original_path = os.path.join(root_dir, file)

            try:
                with Image.open(original_path) as img:
                    base_name, _ = os.path.splitext(file)
                    new_name = f"{base_name}_png_copy.png"
                    new_path = os.path.join(root_dir, new_name)

                    # Convert and save as PNG
                    img.convert("RGBA").save(new_path, "PNG")
                    print(f"Created: {new_path}")

            except Exception as e:
                print(f"Failed to process {original_path}: {e}")

print("Done!")
    