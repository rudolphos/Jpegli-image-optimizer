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
    edge = stats["edge_density"]
    texture = stats["texture"]
    variance = stats["variance"]
    noise = stats["noise"]

    if noise < 0.5: return 0.55 
    distance = 0.65
    if texture > 3.0:
        tex_bonus = (texture - 3.0) * 0.04
        distance += tex_bonus 
    if edge > 0.10:
        brake = (edge - 0.10) * 3.5 
        distance -= brake
    if noise > 5.0:
        distance += 0.2
    if variance < 600:
        return 0.65

    return max(0.55, min(distance, 2.2))

def analyze_image_fast(image_path, max_size=None):
    try:
        stream = open(image_path, "rb")
        bytes_data = bytearray(stream.read())
        numpy_array = np.asarray(bytes_data, dtype=np.uint8)
        stream.close()
        gray = cv2.imdecode(numpy_array, 0) 
        if gray is None: raise Exception("Image decode failed")
    except Exception as e:
        img = Image.open(image_path).convert("L")
        gray = np.array(img)

    edges = cv2.Canny(gray, 50, 150)
    edge_density = np.mean(edges) / 255.0
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    texture = np.mean(np.abs(lap))
    variance = np.var(gray)
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
        self.root.geometry("600x700")
        
        style = ttk.Style()
        style.theme_use('xpnative')
        style.configure('Horizontal.TScale', sliderlength=20, sliderthickness=15)
        
        script_dir = Path(__file__).parent
        self.cjpegli_path = script_dir / "jxl" / "cjpegli.exe"
        self.exiftool_path = script_dir / "exiftool.exe"
        
        self.auto_quality = tk.BooleanVar(value=True)
        self.manual_mode = tk.StringVar(value="quality")
        self.quality = tk.IntVar(value=95)
        self.manual_distance_int = tk.IntVar(value=20) 
        self.max_width = tk.IntVar(value=2000)
        self.enable_resize = tk.BooleanVar(value=False)
        self.min_reduction = tk.IntVar(value=15)
        self.enable_min_reduction = tk.BooleanVar(value=False)
        
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
        settings_frame = ttk.LabelFrame(self.root, text="Settings", padding=10)
        settings_frame.pack(fill="x", padx=10, pady=5)
        
        mode_row = ttk.Frame(settings_frame)
        mode_row.pack(fill="x", pady=(0, 5))
        ttk.Checkbutton(mode_row, text="Auto-optimize (Smart Detect)", variable=self.auto_quality, command=self.toggle_quality_mode).pack(side="left")
        
        self.manual_controls_frame = ttk.LabelFrame(settings_frame, text="Manual Configuration", padding=5)
        
        q_row = ttk.Frame(self.manual_controls_frame)
        q_row.pack(fill="x", pady=2)
        ttk.Radiobutton(q_row, text="Fixed Quality:", variable=self.manual_mode, value="quality", command=self.update_manual_sliders, width=15).pack(side="left")
        
        self.qs = ttk.Scale(q_row, from_=60, to=100, variable=self.quality, orient="horizontal", length=200)
        self.qs.pack(side="left", padx=5)
        self.q_val = ttk.Label(q_row, text="95", width=4)
        self.q_val.pack(side="left")
        self.qs.config(command=lambda val: self.q_val.config(text=f"{int(float(val))}"))

        d_row = ttk.Frame(self.manual_controls_frame)
        d_row.pack(fill="x", pady=2)
        ttk.Radiobutton(d_row, text="Fixed Distance:", variable=self.manual_mode, value="distance", command=self.update_manual_sliders, width=15).pack(side="left")
        
        self.ds = ttk.Scale(d_row, from_=2, to=100, variable=self.manual_distance_int, orient="horizontal", length=200)
        self.ds.pack(side="left", padx=5)
        self.d_val = ttk.Label(d_row, text="1.00", width=4)
        self.d_val.pack(side="left")
        self.ds.config(command=lambda val: self.d_val.config(text=f"{float(val)/20:.2f}"))

        resize_frame = ttk.Frame(settings_frame)
        resize_frame.pack(fill="x", pady=5)
        ttk.Checkbutton(resize_frame, text="Resize max width:", variable=self.enable_resize).pack(side="left")
        ttk.Entry(resize_frame, textvariable=self.max_width, width=8).pack(side="left", padx=5)
        ttk.Label(resize_frame, text="px").pack(side="left")
        
        reduction_frame = ttk.Frame(settings_frame)
        reduction_frame.pack(fill="x", pady=5)
        ttk.Checkbutton(reduction_frame, text="Only replace if reduction ≥", variable=self.enable_min_reduction).pack(side="left")
        rs = ttk.Scale(reduction_frame, from_=1, to=50, variable=self.min_reduction, orient="horizontal", length=100)
        rs.pack(side="left", padx=10)
        self.r_val = ttk.Label(reduction_frame, text="15%", width=5)
        self.r_val.pack(side="left")
        rs.config(command=lambda val: self.r_val.config(text=f"{int(float(val))}%"))
        
        self.toggle_quality_mode()
        self.update_manual_sliders()
        
        drop_frame = ttk.LabelFrame(self.root, padding=5)
        drop_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.drop_label = tk.Label(drop_frame, text="Drag & Drop Images Here\n(JPG/JPEG/WEBP/PNG)", font=("Arial Nova", 12), bg="#f0f0f0", relief="solid", bd=1)
        self.drop_label.pack(fill="both", expand=True)
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self.on_drop)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.root, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", padx=10, pady=5)
        
        log_frame = ttk.LabelFrame(self.root, text="Log", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def toggle_quality_mode(self):
        if self.auto_quality.get():
            self.manual_controls_frame.pack_forget()
        else:
            self.manual_controls_frame.pack(fill="x", padx=5, pady=5, after=self.manual_controls_frame.master.winfo_children()[0])

    def update_manual_sliders(self):
        mode = self.manual_mode.get()
        if mode == "quality":
            self.qs.state(["!disabled"])
            self.q_val.config(state="normal")
            self.ds.state(["disabled"])
            self.d_val.config(state="disabled")
        else:
            self.qs.state(["disabled"])
            self.q_val.config(state="disabled")
            self.ds.state(["!disabled"])
            self.d_val.config(state="normal")

    def safe_log(self, message):
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
        image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        
        if not image_files:
            self.safe_log("No JPG/JPEG/PNG/WEBP files found.")
            return
        
        threading.Thread(target=self.process_batch, args=(image_files,), daemon=True).start()

    def process_batch(self, files):
        self.processing = True
        self.safe_progress(0)
        self.log_text.config(state="normal"); self.log_text.delete(1.0, "end"); self.log_text.config(state="disabled")
        
        total = len(files)
        max_workers = max(1, os.cpu_count() - 1)
        
        self.safe_log(f"🚀 Starting parallel batch: {total} images...")
        
        self.batch_stats = {
            'original_size': 0, 'new_size': 0, 
            'processed': 0, 'skipped': 0, 'errors': 0
        }
        
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
        # Fix: treat both PNG and WEBP as non-JPEG inputs requiring conversion
        is_non_jpeg = file_path.suffix.lower() in ('.png', '.webp')
        
        original_size = file_path.stat().st_size
        original_mtime = file_path.stat().st_mtime
        original_atime = file_path.stat().st_atime
        
        output_file = file_path.with_suffix('.jpg') if is_non_jpeg else file_path
        suffix_label = f" [{file_path.suffix.upper()[1:]}→JPG]" if is_non_jpeg else ""
        log_messages = [f"\nProcessing: {file_path.name}{suffix_label}"]
        
        if not is_non_jpeg:
            metadata_file = file_path.parent / (file_path.stem + '.metadata.jpg')
            shutil.copy2(file_path, metadata_file)
        else:
            metadata_file = None
        
        temp_file = output_file.parent / (output_file.stem + '.tmp.jpg')

        try:
            stats = analyze_image_fast(file_path)
            chroma = "444"
            
            if is_non_jpeg:
                source_file = self.convert_to_temp_jpg(file_path)
            else:
                source_file = self.handle_resize(file_path)
            
            cmd = [str(self.cjpegli_path), str(source_file), str(temp_file)]
            
            if self.auto_quality.get():
                predicted_distance = predict_safe_distance(stats)
                log_messages.append(f"  Auto distance: {predicted_distance:.2f} (edge={stats['edge_density']:.3f}, tex={stats['texture']:.1f})")
                cmd.extend([f"--distance={predicted_distance}"])
            else:
                if self.manual_mode.get() == "quality":
                    log_messages.append(f"  Manual Quality: {self.quality.get()}")
                    cmd.append(f"--quality={self.quality.get()}")
                else:
                    dist_val = self.manual_distance_int.get() / 20.0
                    log_messages.append(f"  Manual Distance: {dist_val:.2f}")
                    cmd.append(f"--distance={dist_val:.2f}")

            cmd.extend([f"--chroma_subsampling={chroma}", "--progressive_level=2"])

            subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=0x08000000)
            
            if source_file != file_path and source_file.exists(): 
                source_file.unlink()
            
            new_size = temp_file.stat().st_size
            reduction = ((original_size - new_size) / original_size) * 100
            
            orig_fmt = f"{original_size:,}"
            new_fmt = f"{new_size:,}"
            
            should_replace = False
            skip_reason = ""
            replaced = False

            if reduction <= 0:
                should_replace = False
                skip_reason = f"  ⊘ Skipped: No reduction possible ({orig_fmt} → {new_fmt})"
            elif self.enable_min_reduction.get() and reduction < self.min_reduction.get():
                should_replace = False
                skip_reason = f"  ⊘ Skipped: {reduction:.1f}% < {self.min_reduction.get()}% threshold"
            else:
                should_replace = True
                log_messages.append(f"  {orig_fmt} → {new_fmt} bytes ({reduction:.1f}% reduction)")

            if should_replace:
                shutil.move(str(temp_file), str(output_file))
                replaced = True
                
                if is_non_jpeg:
                    date_str = datetime.fromtimestamp(original_mtime).strftime('%Y:%m:%d %H:%M:%S')
                    exif_cmd = [
                        str(self.exiftool_path), '-charset', 'filename=UTF8',
                        f'-DateTimeOriginal={date_str}', f'-CreateDate={date_str}',
                        '-overwrite_original', str(output_file)
                    ]
                    subprocess.run(exif_cmd, capture_output=True, text=True, creationflags=0x08000000)
                    os.utime(output_file, (original_atime, original_mtime))
                    if HAS_PYWIN32:
                        try:
                            wintime = pywintypes.Time(datetime.fromtimestamp(original_mtime))
                            handle = win32file.CreateFile(str(output_file), win32con.GENERIC_WRITE, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE, None, win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None)
                            win32file.SetFileTime(handle, wintime, None, None)
                            win32file.CloseHandle(handle)
                        except: pass
                    file_path.unlink()
                elif metadata_file:
                    import tempfile, time
                    unique_id = f"{os.getpid()}_{threading.get_ident()}_{int(time.time() * 1000000)}"
                    temp_dir = Path(tempfile.gettempdir())
                    temp_metadata = temp_dir / f"exif_meta_{unique_id}.jpg"
                    temp_output = temp_dir / f"exif_out_{unique_id}.jpg"
                    try:
                        shutil.copy2(metadata_file, temp_metadata)
                        shutil.copy2(output_file, temp_output)
                        restore_cmd = [str(self.exiftool_path), '-tagsfromfile', str(temp_metadata), '-all:all', '-overwrite_original', str(temp_output)]
                        subprocess.run(restore_cmd, capture_output=True, text=True, creationflags=0x08000000)
                        shutil.copy2(temp_output, output_file)
                    finally:
                        if temp_metadata.exists(): temp_metadata.unlink()
                        if temp_output.exists(): temp_output.unlink()
                    try:
                        if output_file.exists(): os.utime(output_file, (original_atime, original_mtime))
                    except: pass
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
            if metadata_file and metadata_file.exists():
                metadata_file.unlink()
            
        return {'original_size': original_size, 'new_size': new_size if replaced else original_size, 'replaced': replaced}

    def convert_to_temp_jpg(self, src_path):
        """Convert PNG or WEBP to a temp JPEG for cjpegli input."""
        temp_jpg = src_path.with_suffix('.converting_temp.jpg')
        img = Image.open(src_path)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P': img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        if self.enable_resize.get():
            w, h = img.size
            if max(w, h) > self.max_width.get():
                ratio = self.max_width.get() / max(w, h)
                img = img.resize((int(w*ratio), int(h*ratio)), Image.Resampling.LANCZOS)
        
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
        msg = (f"\n{'='*60}\nBATCH SUMMARY:\n  Total: {total} | Processed: {s['processed']} | Skipped: {s['skipped']} | Errors: {s['errors']}\n"
               f"  Size: {orig_mb:.2f}MB → {new_mb:.2f}MB (Saved {saved_mb:.2f}MB / {pct:.1f}%)\n{'='*60}\n")
        self.safe_log(msg)

if __name__ == "__main__":
    root = TkinterDnD.Tk()
    app = JPEGLIOptimizer(root)
    root.mainloop()
