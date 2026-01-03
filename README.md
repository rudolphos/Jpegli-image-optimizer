# Jpegli image optimizer

JPEGLI Optimizer is a simplistic, drag-and-drop desktop tool designed to be an open source based alternative of JPEGmini.
It uses Computer Vision (OpenCV) to analyze every image individually—detecting noise, texture, and edges—to calculate the compression level. It then uses the cjpegli encoder to compress the image without visible quality loss.

### ✨ Features

*   **Smart Compression:** Automatically determines the best quality setting based on image content (Texture/Noise/Edge analysis).
*   **Drag & Drop:** Simple GUI to process single files or huge batches instantly.
*   **Metadata Safe:** Preserves all EXIF, IPTC, and XMP data using ExifTool.
*   **Safety Checks:** Only overwrites the file if the file size is actually reduced.
*   **Resize Options:** Optional downscaling for web optimization.
*   **High Efficiency:** Powered by the new JPEG XL library's `cjpegli` encoder (backward compatible with standard JPEG).

### 🛠️ How it Works

Unlike standard compressors that apply a static quality (e.g., Quality 85%) to every image, this tool analyzes the "perceptual complexity" of your photo:

1.  **High Texture/Noise:** The tool allows aggressive compression because the texture hides artifacts.
2.  **Flat Areas/Skies:** The tool increases quality to prevent banding and blocking.
3.  **Text/Sharp Edges:** The tool protects edges to ensure sharpness.

### 📦 Installation

#### 1. Python Dependencies
Install the required Python libraries:
```bash
pip install tkinterdnd2-universal pillow opencv-python numpy
```
#### 2. External Tools

**cjpegli**: Download the libjxl binaries [https://github.com/libjxl/libjxl/releases](https://github.com/libjxl/libjxl/releases), extract cjpegli.exe, and place it in a folder named jxl inside the project root.

**ExifTool**: Download the "Windows Executable" zip from [exiftool.org](https://exiftool.org/). Extract the zip content into the project root. You should have exiftool(-k).exe and the exiftool_files folder side-by-side with the python script. Rename exiftool(-k).exe to exiftool.exe.

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
3.  Make a back-up of your existing image files.
4.  **Drag and drop** your `.jpg`/`.jpeg` files onto the window.
5.  The tool will replace the original files only if they can be compressed smaller without visual loss.

<img width="688" height="825" alt="screen" src="https://github.com/user-attachments/assets/8739f1e7-5fd2-4726-a374-b7d06a628d5c" />
