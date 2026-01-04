import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
import subprocess
import os
import shutil
from pathlib import Path
from PIL import Image
import threading
import concurrent.futures
import cv2
import numpy as np
from datetime import datetime

# Windows-specific imports for setting file creation time
try:
    import pywintypes  # type: ignore
    import win32file  # type: ignore
    import win32con  # type: ignore
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False

# --- HELPER FUNCTIONS ---

def predict_safe_distance(stats):
    """
    Predict optimal distance.
    MODE A: Screenshots (0.55 dist).
    MODE B: Photos (Aggressive, 0.75 - 2.2 dist).
    """
    edge = stats["edge_density"]
    texture = stats["texture"]
    variance = stats["variance"]
    noise = stats["noise"]

    # --- 1. STRICT SCREENSHOT PROTECTION ---
    # Digital graphics (Noise ~0.0). Absolute safety required.
    if noise < 0.5:
        return 0.55 

    # --- 2. PHOTO BASELINE (Aggressive) ---
    # This acts as the "Floor" for photography.
    distance = 0.65

    # --- 3. AGGRESSIVE TEXTURE SCALING ---
    # We allow distance to climb significantly if texture exists.
    if texture > 3.0:
        # Steeper slope (0.04) allows rapid quality drop on busy images.
        tex_bonus = (texture - 3.0) * 0.04
        distance += tex_bonus 

    # --- 4. INTELLIGENT BRAKING (Face Protection) ---
    # If the image has edges (faces) but not infinite texture, pull back.
    if edge > 0.10:
        brake = (edge - 0.10) * 3.5 
        distance -= brake

    # --- 5. NOISE HANDLING ---
    if noise > 5.0:
        # High ISO noise hides artifacts, allow more compression
        distance += 0.2
    
    # Sky protection (Low variance)
    # Critical: If variance is low, FORCE distance down.
    if variance < 600:
        return 0.65

    # --- 6. LIMITS ---
    return max(0.55, min(distance, 2.2))

def analyze_image_fast(image_path, max_size=None):
    """
    Full resolution analysis using OpenCV directly.
    Works with JPEG and PNG files.
    """
    try:
        # Load image stream directly to numpy array (Fastest & Unicode safe)
        stream = open(image_path, "rb")
        bytes_data = bytearray(stream.read())
        numpy_array = np.asarray(bytes_data, dtype=np.uint8)
        stream.close()
        
        # 0 flag loads as Grayscale directly
        gray = cv2.imdecode(numpy_array, 0) 
        
        if gray is None:
            raise Exception("Image decode failed")

    except Exception as e:
        # Fallback
        img = Image.open(image_path).convert("L")
        gray = np.array(img)

    # 1. Edge Detection
    edges = cv2.Canny(gray, 50, 150)
    edge_density = np.mean(edges) / 255.0

    # 2. Texture/Detail
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    texture = np.mean(np.abs(lap))

    # 3. Variance (Flatness)
    variance = np.var(gray)

    # 4. Noise Estimation (Center Crop Strategy)
    h, w = gray.shape
    sample_size = 2048
    if h > sample_size and w > sample_size:
        y, x = (h - sample_size)//2, (w - sample_size)//2
        crop = gray[y:y+sample_size, x:x+sample_size]
    else:
        crop = gray
        
    noise = np.median(np.abs(crop - cv2.GaussianBlur(crop, (3, 3), 0)))

    return {
        "edge_density": edge_density,
        "texture": texture,
        "variance": variance,
        "noise": noise
    }

# --- MAIN CLASS ---

class JPEGLIOptimizer:
    def __init__(self, root):
        self.root = root
        self.root.title("JPEGLI Optimizer")
        self.root.geometry("600x650")
        
        # Style configuration
        style = ttk.Style()
        style.theme_use('xpnative')
        style.configure('Horizontal.TScale', sliderlength=20, sliderthickness=15)
        
        # Paths
        script_dir = Path(__file__).parent
        self.cjpegli_path = script_dir / "jxl" / "cjpegli.exe"
        self.exiftool_path = script_dir / "exiftool.exe"
        
        # Variables
        self.quality = tk.IntVar(value=95)
        self.max_width = tk.IntVar(value=2000)
        self.enable_resize = tk.BooleanVar(value=False)
        self.auto_quality = tk.BooleanVar(value=True)
        self.min_reduction = tk.IntVar(value=15)
        self.enable_min_reduction = tk.BooleanVar(value=False)
        
        # Threading Stats
        self.stats_lock = threading.Lock()
        self.batch_stats = {}
        self.processing = False
        
        self.validate_tools()
        self.setup_ui()
        
    def validate_tools(self):
        errors = []
        if not self.cjpegli_path.exists():
            errors.append(f"cjpegli.exe not found at:\n{self.cjpegli_path}")
        if not self.exiftool_path.exists():
            errors.append(f"exiftool.exe not found at:\n{self.exiftool_path}")
        if errors:
            messagebox.showerror("Missing Tools", "\n\n".join(errors))
            self.root.quit()
        
    def setup_ui(self):
        # Settings
        settings_frame = ttk.LabelFrame(self.root, text="Settings", padding=10)
        settings_frame.pack(fill="x", padx=10, pady=5)
        
        # Combined Quality Control Row
        qc_row = ttk.Frame(settings_frame)
        qc_row.pack(fill="x", pady=5)
        
        # Auto Checkbox
        ttk.Checkbutton(qc_row, text="Auto-optimize (Smart Detect)", variable=self.auto_quality, command=self.toggle_quality_mode).pack(side="left")
        
        # Manual Controls Group
        self.manual_controls_frame = ttk.Frame(qc_row)
        ttk.Label(self.manual_controls_frame, text="Quality:").pack(side="left", padx=(15, 5))
        qs = ttk.Scale(self.manual_controls_frame, from_=60, to=100, variable=self.quality, orient="horizontal", length=150)
        qs.pack(side="left")
        self.q_val = ttk.Label(self.manual_controls_frame, text="95", width=4)
        self.q_val.pack(side="left", padx=5)
        qs.config(command=lambda val: self.q_val.config(text=f"{int(float(val))}"))
        
        # Resize
        resize_frame = ttk.Frame(settings_frame)
        resize_frame.pack(fill="x", pady=5)
        ttk.Checkbutton(resize_frame, text="Resize max width:", variable=self.enable_resize).pack(side="left")
        ttk.Entry(resize_frame, textvariable=self.max_width, width=8).pack(side="left", padx=5)
        ttk.Label(resize_frame, text="px").pack(side="left")
        
        # Minimum Reduction
        reduction_frame = ttk.Frame(settings_frame)
        reduction_frame.pack(fill="x", pady=5)
        ttk.Checkbutton(
            reduction_frame, 
            text="Only replace if reduction ≥", 
            variable=self.enable_min_reduction
        ).pack(side="left")
        
        rs = ttk.Scale(reduction_frame, from_=1, to=50, variable=self.min_reduction, orient="horizontal", length=100)
        rs.pack(side="left", padx=10)
        self.r_val = ttk.Label(reduction_frame, text="15%", width=5)
        self.r_val.pack(side="left")
        rs.config(command=lambda val: self.r_val.config(text=f"{int(float(val))}%"))
        
        self.toggle_quality_mode()
        
        # Drop Zone
        drop_frame = ttk.LabelFrame(self.root, padding=5)
        drop_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.drop_label = tk.Label(drop_frame, text="Drag & Drop Images Here\n(JPG/JPEG/PNG)", font=("Arial Nova", 12), bg="#f0f0f0", relief="solid", bd=1)
        self.drop_label.pack(fill="both", expand=True)
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self.on_drop)
        
        # Progress
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", padx=10, pady=5)
        
        # Log
        log_frame = ttk.LabelFrame(self.root, text="Log", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def toggle_quality_mode(self):
        if self.auto_quality.get():
            self.manual_controls_frame.pack_forget()
        else:
            self.manual_controls_frame.pack(side="left")

    def safe_log(self, message):
        """Thread-safe UI logging"""
        self.root.after(0, self._log_impl, message)

    def _log_impl(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def safe_progress(self, value):
        self.root.after(0, lambda: self.progress_var.set(value))

    def on_drop(self, event):
        if self.processing: return
        files = self.root.tk.splitlist(event.data)
        # Accept both JPEG and PNG files
        image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        if not image_files:
            self.safe_log("No JPG/JPEG/PNG files found in dropped items.")
            return
        
        # Run batch in thread
        threading.Thread(target=self.process_batch, args=(image_files,), daemon=True).start()

    def process_batch(self, files):
        self.processing = True
        self.safe_progress(0)
        self.log_text.config(state="normal"); self.log_text.delete(1.0, "end"); self.log_text.config(state="disabled")
        
        total = len(files)
        # Use All Cores minus 1 (min 1 worker)
        max_workers = max(1, os.cpu_count() - 1)
        
        self.safe_log(f"🚀 Starting parallel batch: {total} images using {max_workers} threads...")
        
        self.batch_stats = {
            'original_size': 0, 'new_size': 0, 
            'processed': 0, 'skipped': 0, 'errors': 0
        }
        
        completed = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.process_single_image, f): f for f in files}
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        with self.stats_lock:
                            self.batch_stats['original_size'] += result['original_size']
                            self.batch_stats['new_size'] += result['new_size']
                            self.batch_stats['processed' if result['replaced'] else 'skipped'] += 1
                except Exception as e:
                    with self.stats_lock:
                        self.batch_stats['errors'] += 1
                    self.safe_log(f"✗ Error: {os.path.basename(futures[future])}: {e}")
                
                self.safe_progress((len([f for f in futures if f.done()]) / total) * 100)

        self.print_summary(total)
        self.processing = False

    def process_single_image(self, file_path):
        file_path = Path(file_path)
        is_png = file_path.suffix.lower() == '.png'
        
        original_size = file_path.stat().st_size
        original_mtime = file_path.stat().st_mtime
        original_atime = file_path.stat().st_atime
        original_ctime = file_path.stat().st_ctime  # Creation time
        
        # For PNG: output will replace the PNG with JPG
        output_file = file_path.with_suffix('.jpg') if is_png else file_path
             
        # --- Start collecting log for this file ---
        log_messages = [f"\nProcessing: {file_path.name}" + (" [PNG→JPG]" if is_png else "")]
        
        # 1. Metadata Backup (only for JPEG)
        if not is_png:
            metadata_file = file_path.with_suffix('.metadata.jpg')
            shutil.copy2(file_path, metadata_file)
        else:
            metadata_file = None
        
        temp_file = output_file.with_suffix('.tmp.jpg')

        try:
            # 2. Analyze
            stats = analyze_image_fast(file_path)
            
            # --- CHROMA: Always use 4:4:4 with jpegli for best quality ---
            chroma = "444"
            
            # For PNG, convert to high-quality temp JPEG first for cjpegli input
            if is_png:
                source_file = self.convert_png_to_temp_jpg(file_path)
            else:
                source_file = self.handle_resize(file_path)
            
            # Build Command
            cmd = [str(self.cjpegli_path), str(source_file), str(temp_file)]
            
            predicted_distance = 0.0 
            if self.auto_quality.get():
                predicted_distance = predict_safe_distance(stats)
                log_messages.append(f"  Auto distance: {predicted_distance:.2f} (edge={stats['edge_density']:.3f}, tex={stats['texture']:.1f}, var={stats['variance']:.0f})")
                cmd.extend([f"--distance={predicted_distance}", f"--chroma_subsampling={chroma}", "--progressive_level=2"])
            else:
                log_messages.append(f"  Manual quality: {self.quality.get()}")
                cmd.append(f"--quality={self.quality.get()}")

            # 3. Execute cjpegli
            subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=0x08000000)
            
            if source_file != file_path and source_file.exists(): 
                source_file.unlink()
            
            # 4. Check Size
            new_size = temp_file.stat().st_size
            reduction = ((original_size - new_size) / original_size) * 100
            
            orig_fmt = f"{original_size:,}"
            new_fmt = f"{new_size:,}"
            
            should_replace = False
            skip_reason = ""
            replaced = False  # Initialize here

            
            # --- Size comparison logic (works for both PNG and JPEG) ---
            if reduction <= 5:
                should_replace = False
                skip_reason = f"  ⊘ Skipped: No reduction possible ({orig_fmt} → {new_fmt})"
            elif self.enable_min_reduction.get() and reduction < self.min_reduction.get():
                should_replace = False
                skip_reason = f"  ⊘ Skipped: {reduction:.1f}% < {self.min_reduction.get()}% threshold ({orig_fmt} → {new_fmt})"
            else:
                should_replace = True
                if is_png:
                    log_messages.append(f"  {orig_fmt} (PNG) → {new_fmt} (JPG) ({reduction:.1f}% reduction)")
                else:
                    log_messages.append(f"  {orig_fmt} → {new_fmt} bytes ({reduction:.1f}% reduction)")

            if should_replace:
                # Move to final location
                shutil.move(str(temp_file), str(output_file))

                
                # 5. Restore Metadata and Timestamps
                if is_png:
                    # For PNG: Set EXIF creation date, then restore file timestamps
                    date_str = datetime.fromtimestamp(original_mtime).strftime('%Y:%m:%d %H:%M:%S')
                    
                    exif_cmd = [
                        str(self.exiftool_path),
                        '-charset', 'filename=UTF8',
                        f'-DateTimeOriginal={date_str}',
                        f'-CreateDate={date_str}',
                        '-overwrite_original',
                        str(output_file)
                    ]
                    subprocess.run(exif_cmd, capture_output=True, text=True, creationflags=0x08000000)
                    
                    # Restore file system timestamps AFTER ExifTool
                    os.utime(output_file, (original_atime, original_mtime))
                    
                    # Set Windows creation time if pywin32 is available
                    if HAS_PYWIN32:
                        try:
                            wintime = pywintypes.Time(datetime.fromtimestamp(original_mtime))
                            handle = win32file.CreateFile(
                                str(output_file),
                                win32con.GENERIC_WRITE,
                                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                None,
                                win32con.OPEN_EXISTING,
                                win32con.FILE_ATTRIBUTE_NORMAL,
                                None
                            )
                            win32file.SetFileTime(handle, wintime, None, None)
                            win32file.CloseHandle(handle)
                        except Exception:
                            pass  # Silent fail on timestamp errors
                    
                    # Delete original PNG
                    file_path.unlink()
                elif metadata_file:
                    # For JPEG: Restore full EXIF metadata
                    if not metadata_file.exists():
                        # Revert: restore original from temp if metadata backup is missing
                        if output_file.exists():
                            output_file.unlink()
                        raise Exception(f"Metadata backup file missing: {metadata_file.name}")
                    
                    # Use short 8.3 DOS paths ONLY for ExifTool command
                    import ctypes
                    buf_meta = ctypes.create_unicode_buffer(512)
                    buf_output = ctypes.create_unicode_buffer(512)
                    ctypes.windll.kernel32.GetShortPathNameW(str(metadata_file), buf_meta, 512)
                    ctypes.windll.kernel32.GetShortPathNameW(str(output_file), buf_output, 512)
                    short_metadata_path = buf_meta.value if buf_meta.value else str(metadata_file)
                    short_output_path = buf_output.value if buf_output.value else str(output_file)
                    
                    restore_cmd = [
                        str(self.exiftool_path),
                        '-charset', 'filename=UTF8',
                        f'-tagsfromfile={short_metadata_path}',
                        '-all:all', 
                        '-overwrite_original', 
                        short_output_path
                    ]
                    
                    result = subprocess.run(restore_cmd, capture_output=True, text=True, creationflags=0x08000000)
                    
                    if result.returncode != 0:
                        # Revert: restore original from metadata backup
                        shutil.copy2(metadata_file, output_file)
                        raise Exception(f"ExifTool Error: {result.stderr}")

                    # Use LONG path for Python operations
                    try:
                        # Check if file exists (ExifTool might not have renamed it)
                        if output_file.exists():
                            os.utime(output_file, (original_atime, original_mtime))
                        elif Path(short_output_path).exists():
                            # If short name exists, rename back to long name first
                            Path(short_output_path).rename(output_file)
                            os.utime(output_file, (original_atime, original_mtime))
                    except Exception as e:
                        log_messages.append(f"  [WARNING] Could not set timestamps: {str(e)}")

                    replaced = True
            else:
                temp_file.unlink()
                log_messages.append(skip_reason)
                replaced = False
            
            self.safe_log("\n".join(log_messages))
                
        except Exception as e:
            if temp_file.exists(): temp_file.unlink()
            log_messages.append(f"✗ ERROR: {str(e)}")
            self.safe_log("\n".join(log_messages))
            raise e
        finally:
            # Always delete metadata backup (whether replaced or skipped)
            if metadata_file and metadata_file.exists():
                metadata_file.unlink()

            
        return {'original_size': original_size, 'new_size': new_size if replaced else original_size, 'replaced': replaced}

    def convert_png_to_temp_jpg(self, png_path):
        """Convert PNG to high-quality temporary JPEG for cjpegli processing."""
        temp_jpg = png_path.with_suffix('.png_temp.jpg')
        
        img = Image.open(png_path)
        
        # Handle transparency by converting to RGB
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Apply resize if enabled
        if self.enable_resize.get():
            w, h = img.size
            if max(w, h) > self.max_width.get():
                ratio = self.max_width.get() / max(w, h)
                img = img.resize((int(w*ratio), int(h*ratio)), Image.Resampling.LANCZOS)
        
        # Save as high-quality JPEG for cjpegli input
        img.save(temp_jpg, 'JPEG', quality=98, subsampling=0)
        return temp_jpg

    def handle_resize(self, file_path):
        if not self.enable_resize.get(): return file_path
        img = Image.open(file_path)
        w, h = img.size
        if max(w, h) <= self.max_width.get(): return file_path
        
        ratio = self.max_width.get() / max(w, h)
        img = img.resize((int(w*ratio), int(h*ratio)), Image.Resampling.LANCZOS)
        temp = file_path.with_suffix('.resized.jpg')
        img.save(temp, quality=98)
        return temp

    def print_summary(self, total):
        s = self.batch_stats
        
        orig_mb = s['original_size'] / (1024*1024)
        new_mb = s['new_size'] / (1024*1024)
        saved_mb = orig_mb - new_mb
        
        pct = 0
        if s['original_size'] > 0:
             pct = ((s['original_size'] - s['new_size']) / s['original_size']) * 100
        
        msg = (f"\n{'='*60}\n"
               f"BATCH SUMMARY:\n"
               f"  Total images: {total}\n"
               f"  ✓ Processed: {s['processed']}\n"
               f"  ⊘ Skipped: {s['skipped']}\n"
               f"  ✗ Errors: {s['errors']}\n"
               f"{'-'*30}\n"
               f"  Original Size: {orig_mb:.2f} MB\n"
               f"  Optimized Size: {new_mb:.2f} MB\n"
               f"  Total Saved: {saved_mb:.2f} MB ({pct:.1f}% reduction)\n"
               f"{'='*60}\n")
        self.safe_log(msg)

if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = JPEGLIOptimizer(root)
    root.mainloop()
