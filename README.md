
# Jpegli image optimizer

JPEGLI Optimizer is a lightweight, drag-and-drop GUI-based tool designed to be an open source based alternative of JPEGmini.
It uses Computer Vision (OpenCV) to analyze every image individually—detecting noise, texture, and edges—to calculate the compression level. It then uses the [jpegli](https://github.com/google/jpegli) encoder to compress the image without visible quality loss.

### Features

*   Automatically determines the best quality setting based on image content (Texture/Noise/Edge analysis).
*   Simple GUI to process single files or large batches instantly.
*   Preserves all EXIF, IPTC, and XMP data using ExifTool, including file created and modified dates.
*   Only overwrites the file if the file size is actually reduced.
*   Optional resize downscaling for web optimization.
*   Powered by the new JPEG XL library's `cjpegli` encoder (backward compatible with standard JPEG).

### How it Works

Unlike standard compressors that apply a static quality (e.g., Quality 85%) to every image, this tool analyzes the "perceptual complexity" of a photo:

1.  **High Texture/Noise:** The tool allows aggressive compression because the texture hides artifacts.
2.  **Flat Areas/Skies:** The tool increases quality to prevent banding and blocking.
3.  **Text/Sharp Edges:** The tool protects edges to ensure sharpness.

### Installation

#### 1. Python Dependencies
Install the required Python libraries:
```bash
pip install tkinterdnd2-universal pillow opencv-python numpy pywin32
```
#### 2. External Tools

 - **cjpegli**: Download the libjxl binaries (jxl-x64-windows-static.zip) from [github.com/libjxl/libjxl/releases](https://github.com/libjxl/libjxl/releases), extract `cjpegli.exe` and place in a folder named jxl inside the project root.

 - **ExifTool**: Download the "Windows Executable" zip from [exiftool.org](https://exiftool.org/). Extract the zip content into the project root. You should have `exiftool(-k).exe` and the `exiftool_files` folder side-by-side with the python script. Rename `exiftool(-k).exe` to `exiftool.exe`.

#### Folder Structure
Ensure your directory looks like this:
```text
/Project_Folder
 │
 ├── JPEGli_opt.py         # This script
 ├── exiftool.exe         # For metadata preservation
 └── /jxl
      └── cjpegli.exe     # The encoder
```

### 🚀 Usage

1.  Run the script:
    ```bash
    python optimizer.py
    ```
    Or double-click the py file.
2.  **Toggle "Auto-optimize"**: Enables the computer vision analysis.
3.  **Backup"**: Make a back-up of your existing image files.
4.  **Drag and drop** your `.jpg`/`.jpeg` files onto the window.
5.  The tool will replace the original files only if they can be compressed smaller without visual loss.

---

<img width="550" height="630" alt="image" src="https://github.com/user-attachments/assets/42ba9c6d-6475-4a93-8f9b-388c093d78a3" />

---

As shown in this XnView comparison view—with the JPEGmini result above and the script output below—the visual similarity is nearly identical, though this script retains slightly more detail, less blurriness and blockiness when compared at 400% zoom level. 

*Pictured are tiny rocks on the sole of the shoe.*

<img width="959" height="829" alt="image" src="https://github.com/user-attachments/assets/78faf09c-8865-40ed-96ca-83026a61c0e2" />

---
# JPEGLI Optimizer vs JPEGmini: Compression Test

## Test Dataset
27 diverse JPEG images including portraits, landscapes, architecture, text graphics, and various lighting conditions.

## Results

### JPEGLI Optimizer (Adaptive distance)
```
Total images: 27
✓ Processed: 23
⊘ Skipped: 4 (already optimized)
✗ Errors: 0
Original: 65.88 MB
New size: 45.66 MB
Saved: 20.22 MB (30.7% reduction)
```

**Distance distribution:**

The adaptive algorithm selected distances based on image characteristics:
- 0.65 (Conservative): 10 images - Low texture, smooth areas, portraits
- 0.80 (Moderate): 4 images - Medium complexity
- 1.00 (Balanced): 2 images - Mixed content
- 1.20 (Aggressive): 11 images - High texture, complex scenes

### JPEGmini
```
Total images: 27 (all except one processed)
Original: 65.88 MB
Saved: 20.73 MB (36% reduction)
```

## Conclusion

The JPEGLI optimizer achieved **30.7% compression** vs JPEGmini's **36%** - a difference of only 5.3%. The JPEGLI optimizer's conservative approach skips optimized images and preserves fine details better, making it a quality-first open source alternative to commercial solutions.
