import sys
import os
import re
import time
import struct
import shutil
import datetime
import threading
import platform
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

# Global imports that will be loaded dynamically if needed
Image = None
pillow_heif = None

# Color palettes for Themes
THEMES = {
    'dark': {
        'bg': '#1e1e2e',
        'card_bg': '#252538',
        'text': '#cdd6f4',
        'subtext': '#a6adc8',
        'entry_bg': '#313244',
        'accent': '#89b4fa',
        'accent_hover': '#b4befe',
        'accent_text': '#11111b',
        'log_bg': '#181825',
        'success': '#a6e3a1',
        'warning': '#f9e2af',
        'error': '#f38ba8'
    },
    'light': {
        'bg': '#f4f4f7',
        'card_bg': '#ffffff',
        'text': '#1e1e2e',
        'subtext': '#585b70',
        'entry_bg': '#e6e6ea',
        'accent': '#3f51b5',
        'accent_hover': '#5c6bc0',
        'accent_text': '#ffffff',
        'log_bg': '#fafafa',
        'success': '#2e7d32',
        'warning': '#f57c00',
        'error': '#d32f2f'
    }
}

import json

CONFIG_FILE = "config.json"

def load_config():
    defaults = {
        'theme': 'dark',
        'source_path': '',
        'destination_path': ''
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                defaults.update(config)
        except Exception:
            pass
    return defaults

def save_config(theme, source_path, destination_path):
    try:
        config = {
            'theme': theme,
            'source_path': source_path,
            'destination_path': destination_path
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

def check_dependencies():
    """Check if mandatory libraries are installed."""
    try:
        from PIL import Image as PILImage
        import pillow_heif as HEIF
        return True
    except ImportError:
        return False

# Helper functions for metadata parsing
def extract_date_from_filename(filename):
    """Try to extract a datetime from the filename using common patterns."""
    name = filename.rsplit('.', 1)[0]
    
    # 1. YYYYMMDD_HHMMSS patterns (e.g. IMG_20231024_153022.jpg, 2023-10-24_15-30-22)
    pattern_dt = re.compile(
        r'(?P<year>(?:19|20)\d{2})[-_.]?(?P<month>0[1-9]|1[0-2])[-_.]?(?P<day>0[1-9]|[12]\d|3[01])'
        r'[-_.\s]+'
        r'(?P<hour>[01]\d|2[0-3])[-_.:]?(?P<minute>[0-5]\d)[-_.:]?(?P<second>[0-5]\d)'
    )
    match = pattern_dt.search(name)
    if match:
        d = match.groupdict()
        try:
            return datetime.datetime(
                int(d['year']), int(d['month']), int(d['day']),
                int(d['hour']), int(d['minute']), int(d['second'])
            )
        except ValueError:
            pass

    # 2. YYYY-MM-DD pattern (date only)
    pattern_date = re.compile(
        r'(?P<year>(?:19|20)\d{2})[-_.]?(?P<month>0[1-9]|1[0-2])[-_.]?(?P<day>0[1-9]|[12]\d|3[01])'
    )
    match = pattern_date.search(name)
    if match:
        d = match.groupdict()
        try:
            # Default to noon to avoid timezone boundary issues
            return datetime.datetime(
                int(d['year']), int(d['month']), int(d['day']),
                12, 0, 0
            )
        except ValueError:
            pass

    # 3. Unix timestamp (10 or 13 digits)
    pattern_ts = re.compile(r'(?<!\d)(?P<ts>\d{10}|\d{13})(?!\d)')
    for match in pattern_ts.finditer(name):
        val = int(match.group('ts'))
        if len(match.group('ts')) == 13:
            val = val // 1000
        # Check if timestamp is within a reasonable range (1995 to 2038)
        if 788918400 < val < 2147483647:
            try:
                return datetime.datetime.fromtimestamp(val)
            except (ValueError, OSError, OverflowError):
                pass
                
    return None

def parse_exif_date(date_str):
    """Parse common EXIF date string formats."""
    date_str = date_str.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    # Resilient search for first 6 numeric groups
    match = re.search(r'^(\d{4})[-:.](\d{2})[-:.](\d{2})\s+(\d{2})[-:.](\d{2})[-:.](\d{2})', date_str)
    if match:
        parts = [int(p) for p in match.groups()]
        try:
            return datetime.datetime(*parts)
        except ValueError:
            pass
    return None

def get_photo_creation_time(file_path):
    """Retrieve date from photo EXIF tags."""
    global Image
    if Image is None:
        from PIL import Image
    try:
        with Image.open(file_path) as img:
            exif = img.getexif()
            if not exif:
                return None
            # DateTimeOriginal (36867), DateTimeDigitized (36868), DateTime (306)
            for tag_id in (36867, 36868, 306):
                val = exif.get(tag_id)
                if val and isinstance(val, str):
                    dt = parse_exif_date(val)
                    if dt:
                        return dt
    except Exception:
        pass
    return None

def find_mvhd(f, end_pos):
    """Walk through MP4 containers to locate the mvhd atom."""
    while f.tell() < end_pos:
        header = f.read(8)
        if len(header) < 8:
            break
        
        size, atom_type = struct.unpack(">I4s", header)
        box_end = f.tell() - 8 + size
        if size == 1:
            large_size_bytes = f.read(8)
            if len(large_size_bytes) < 8:
                break
            size = struct.unpack(">Q", large_size_bytes)[0]
            box_end = f.tell() - 16 + size
        
        if atom_type == b'moov':
            res = find_mvhd(f, box_end)
            if res:
                return res
        elif atom_type == b'mvhd':
            version = struct.unpack("B", f.read(1))[0]
            f.seek(3, 1) # Skip flags
            if version == 1:
                creation_time = struct.unpack(">Q", f.read(8))[0]
            else:
                creation_time = struct.unpack(">I", f.read(4))[0]
            return creation_time
        
        f.seek(box_end)
    return None

def get_mp4_creation_time(file_path):
    """Parse MP4/MOV header to find creation time."""
    epoch = datetime.datetime(1904, 1, 1, tzinfo=datetime.timezone.utc)
    try:
        with open(file_path, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            f.seek(0)
            ctime = find_mvhd(f, file_size)
            if ctime and ctime > 0:
                dt = epoch + datetime.timedelta(seconds=ctime)
                if dt.year >= 1990:
                    return dt
    except Exception:
        pass
    return None

def parse_iso_date(val):
    """Parse standard ISO 8601 timestamps."""
    val = val.strip()
    match = re.search(r'^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?(?:[T\s](\d{2}):(\d{2}):(\d{2}))?', val)
    if match:
        parts = match.groups()
        y = int(parts[0])
        m = int(parts[1]) if parts[1] else 1
        d = int(parts[2]) if parts[2] else 1
        h = int(parts[3]) if parts[3] else 12
        mn = int(parts[4]) if parts[4] else 0
        s = int(parts[5]) if parts[5] else 0
        try:
            return datetime.datetime(y, m, d, h, mn, s)
        except ValueError:
            pass
    return None

def get_mp3_creation_time(file_path):
    """Extract creation/recording date from ID3v2 tags of MP3 files."""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(10)
            if len(header) < 10 or header[:3] != b'ID3':
                return None
            
            major = header[3]
            size = (header[6] << 21) | (header[7] << 14) | (header[8] << 7) | header[9]
            tag_data = f.read(size)
            
            frames = {}
            offset = 0
            
            if major in (3, 4):
                while offset + 10 <= len(tag_data):
                    frame_id_bytes = tag_data[offset:offset+4]
                    if not frame_id_bytes or frame_id_bytes == b'\x00\x00\x00\x00':
                        break
                    
                    frame_size_bytes = tag_data[offset+4:offset+8]
                    if major == 4:
                        frame_size = (frame_size_bytes[0] << 21) | (frame_size_bytes[1] << 14) | (frame_size_bytes[2] << 7) | frame_size_bytes[3]
                    else:
                        frame_size = struct.unpack(">I", frame_size_bytes)[0]
                    
                    if offset + 10 + frame_size > len(tag_data):
                        break
                    
                    frame_data = tag_data[offset+10:offset+10+frame_size]
                    if frame_id_bytes.startswith(b'T') and len(frame_data) > 1:
                        try:
                            enc = frame_data[0]
                            text_bytes = frame_data[1:]
                            if enc == 0:
                                text = text_bytes.decode('iso-8859-1').strip('\x00')
                            elif enc == 1:
                                text = text_bytes.decode('utf-16').strip('\x00')
                            elif enc == 2:
                                text = text_bytes.decode('utf-16-be').strip('\x00')
                            elif enc == 3:
                                text = text_bytes.decode('utf-8').strip('\x00')
                            else:
                                text = text_bytes.decode('utf-8', errors='ignore').strip('\x00')
                            
                            fid = frame_id_bytes.decode('ascii', errors='ignore')
                            frames[fid] = text
                        except Exception:
                            pass
                    
                    offset += 10 + frame_size
            elif major == 2:
                while offset + 6 <= len(tag_data):
                    frame_id_bytes = tag_data[offset:offset+3]
                    if not frame_id_bytes or frame_id_bytes == b'\x00\x00\x00':
                        break
                    
                    frame_size_bytes = tag_data[offset+3:offset+6]
                    frame_size = (frame_size_bytes[0] << 16) | (frame_size_bytes[1] << 8) | frame_size_bytes[2]
                    
                    if offset + 6 + frame_size > len(tag_data):
                        break
                        
                    frame_data = tag_data[offset+6:offset+6+frame_size]
                    if frame_id_bytes.startswith(b'T') and len(frame_data) > 1:
                        try:
                            enc = frame_data[0]
                            text_bytes = frame_data[1:]
                            if enc == 0:
                                text = text_bytes.decode('iso-8859-1').strip('\x00')
                            elif enc == 1:
                                text = text_bytes.decode('utf-16').strip('\x00')
                            else:
                                text = text_bytes.decode('utf-8', errors='ignore').strip('\x00')
                            
                            fid = frame_id_bytes.decode('ascii', errors='ignore')
                            frames[fid] = text
                        except Exception:
                            pass
                    
                    offset += 6 + frame_size
            
            if 'TDRC' in frames:
                dt = parse_iso_date(frames['TDRC'])
                if dt:
                    return dt
            
            year = frames.get('TYER') or frames.get('TYE')
            date_ddmm = frames.get('TDAT') or frames.get('TDA')
            time_hhmm = frames.get('TIME') or frames.get('TIM')
            
            if year and len(year) == 4:
                y = int(year)
                m, d = 1, 1
                h, mn, s = 12, 0, 0
                if date_ddmm and len(date_ddmm) == 4:
                    try:
                        d = int(date_ddmm[:2])
                        m = int(date_ddmm[2:])
                    except ValueError:
                        pass
                if time_hhmm and len(time_hhmm) == 4:
                    try:
                        h = int(time_hhmm[:2])
                        mn = int(time_hhmm[2:])
                    except ValueError:
                        pass
                try:
                    return datetime.datetime(y, m, d, h, mn, s)
                except ValueError:
                    pass
    except Exception:
        pass
    return None

def set_file_times(filepath, dt):
    """Sets creation, modification and access time of a file. Supports Windows ctime setting."""
    epoch_time = dt.timestamp()
    if platform.system() == 'Windows':
        try:
            import ctypes
            from ctypes import wintypes
            
            CreateFileW = ctypes.windll.kernel32.CreateFileW
            SetFileTime = ctypes.windll.kernel32.SetFileTime
            CloseHandle = ctypes.windll.kernel32.CloseHandle
            
            timestamp = int((epoch_time * 10000000) + 116444736000000000)
            low_dword = timestamp & 0xFFFFFFFF
            high_dword = (timestamp >> 32) & 0xFFFFFFFF
            ctime = wintypes.FILETIME(low_dword, high_dword)
            
            handle = CreateFileW(
                filepath, 
                0x0100, # FILE_WRITE_ATTRIBUTES
                0,      # Share mode
                None,   # Security attributes
                3,      # OPEN_EXISTING
                128,    # FILE_ATTRIBUTE_NORMAL
                None
            )
            
            if handle != -1 and handle is not None:
                # Update creation time, access time, and write time to match target datetime
                SetFileTime(handle, ctypes.byref(ctime), ctypes.byref(ctime), ctypes.byref(ctime))
                CloseHandle(handle)
            else:
                os.utime(filepath, (epoch_time, epoch_time))
        except Exception:
            try:
                os.utime(filepath, (epoch_time, epoch_time))
            except Exception:
                pass
    else:
        try:
            os.utime(filepath, (epoch_time, epoch_time))
        except Exception:
            pass

def apply_theme_to_widget(widget, colors):
    """Recursively styles a widget and its children based on the theme colors."""
    w_type = widget.winfo_class()
    
    if w_type == 'Tk' or w_type == 'Toplevel':
        widget.configure(bg=colors['bg'])
    elif w_type in ('Frame', 'LabelFrame'):
        is_card = getattr(widget, 'is_card', True)
        bg_color = colors['card_bg'] if is_card else colors['bg']
        widget.configure(bg=bg_color)
    elif w_type == 'Label':
        is_header = getattr(widget, 'is_header', False)
        is_subtext = getattr(widget, 'is_subtext', False)
        
        if is_header:
            widget.configure(bg=colors['bg'], fg=colors['accent'])
        elif is_subtext:
            widget.configure(bg=colors['card_bg'], fg=colors['subtext'])
        else:
            widget.configure(bg=colors['card_bg'], fg=colors['text'])
    elif w_type == 'Button':
        is_primary = getattr(widget, 'is_primary', False)
        is_header_btn = getattr(widget, 'is_header_btn', False)
        
        if is_primary:
            widget.configure(
                bg=colors['accent'], 
                fg=colors['accent_text'], 
                activebackground=colors['accent_hover'],
                activeforeground=colors['accent_text'],
                relief='flat',
                bd=0
            )
        elif is_header_btn:
            widget.configure(
                bg=colors['bg'],
                fg=colors['text'],
                activebackground=colors['card_bg'],
                activeforeground=colors['text'],
                relief='flat',
                bd=0
            )
        else:
            widget.configure(
                bg=colors['entry_bg'], 
                fg=colors['text'], 
                activebackground=colors['bg'],
                activeforeground=colors['text'],
                relief='flat',
                bd=0
            )
    elif w_type == 'Entry':
        widget.configure(
            bg=colors['entry_bg'], 
            fg=colors['text'], 
            insertbackground=colors['text'],
            highlightbackground=colors['card_bg'],
            highlightcolor=colors['accent']
        )
    elif w_type == 'Text':
        widget.configure(
            bg=colors['log_bg'], 
            fg=colors['text'], 
            insertbackground=colors['text']
        )
        
    for child in widget.winfo_children():
        apply_theme_to_widget(child, colors)

def render_markdown_in_text(text_widget, md_content):
    """Renders basic Markdown headers, lists, code, and links in a Text widget."""
    text_widget.configure(state='normal')
    text_widget.delete('1.0', 'end')
    
    lines = md_content.split('\n')
    in_code_block = False
    code_block_text = ""
    
    for line in lines:
        if line.startswith('```'):
            if in_code_block:
                text_widget.insert('end', code_block_text, 'code')
                text_widget.insert('end', '\n')
                in_code_block = False
                code_block_text = ""
            else:
                in_code_block = True
            continue
            
        if in_code_block:
            code_block_text += line + '\n'
            continue
            
        if line.startswith('# '):
            text_widget.insert('end', line[2:] + '\n', 'h1')
        elif line.startswith('## '):
            text_widget.insert('end', line[3:] + '\n', 'h2')
        elif line.startswith('### '):
            text_widget.insert('end', line[4:] + '\n', 'h3')
        elif line.startswith('* ') or line.startswith('- '):
            text_widget.insert('end', '  • ', 'bullet')
            parse_inline_formatting(text_widget, line[2:] + '\n', 'bullet')
        elif line.strip() == '---':
            text_widget.insert('end', '—' * 50 + '\n', 'body')
        else:
            parse_inline_formatting(text_widget, line + '\n', 'body')
            
    text_widget.configure(state='disabled')

def parse_inline_formatting(text_widget, text, default_tag):
    """Parses bold strings **text** and [link](url) inlines."""
    pattern = re.compile(r'(\*\*.*?\*\*|\[.*?\]\(.*?\))')
    parts = pattern.split(text)
    
    for part in parts:
        if not part:
            continue
        if part.startswith('**') and part.endswith('**'):
            text_widget.insert('end', part[2:-2], 'bold')
        elif part.startswith('[') and part.endswith(')'):
            match = re.match(r'\[(.*?)\]\((.*?)\)', part)
            if match:
                link_text, url = match.groups()
                text_widget.insert('end', link_text, 'link')
            else:
                text_widget.insert('end', part, default_tag)
        else:
            text_widget.insert('end', part, default_tag)


class PhotoCheckDateApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PhotoCheckDate - Упорядкування та відновлення дат")
        self.root.geometry("700x650")
        self.root.minsize(600, 550)
        
        # Center main window on screen
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
        # Load README.md contents for Help window
        self.readme_content = "Файл README.md не знайдено."
        if os.path.exists("README.md"):
            try:
                with open("README.md", "r", encoding="utf-8") as f:
                    self.readme_content = f.read()
            except Exception:
                pass
                
        # Load config
        self.config = load_config()
        self.current_theme = self.config['theme']
        
        self.help_window = None
        self.help_text_widget = None
        
        self.create_widgets()
        
        # Populate entries from config
        if self.config['source_path']:
            self.src_entry.insert(0, self.config['source_path'])
        if self.config['destination_path']:
            self.dest_entry.insert(0, self.config['destination_path'])
            
        self.apply_current_theme()
        
        # Bind window close event to save settings
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

    def on_exit(self):
        save_config(self.current_theme, self.src_entry.get().strip(), self.dest_entry.get().strip())
        self.root.destroy()

    def create_widgets(self):
        # Grid settings
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        # 1. Header frame
        self.header_frame = tk.Frame(self.root)
        self.header_frame.is_card = False
        self.header_frame.grid(row=0, column=0, fill='x', padx=15, pady=10)
        self.header_frame.columnconfigure(0, weight=1)
        
        self.title_label = tk.Label(self.header_frame, text="PhotoCheckDate 📷", font=("Segoe UI", 16, "bold"))
        self.title_label.is_header = True
        self.title_label.grid(row=0, column=0, sticky='w')
        
        # Header control buttons frame
        self.btn_frame = tk.Frame(self.header_frame)
        self.btn_frame.is_card = False
        self.btn_frame.grid(row=0, column=1, sticky='e')
        
        self.help_btn = tk.Button(self.btn_frame, text="Довідка 📚", font=("Segoe UI", 10), command=self.show_help, padx=10, pady=5)
        self.help_btn.is_header_btn = True
        self.help_btn.grid(row=0, column=0, padx=5)
        
        self.theme_btn = tk.Button(self.btn_frame, text="Світла тема ☀️", font=("Segoe UI", 10), command=self.toggle_theme, padx=10, pady=5)
        self.theme_btn.is_header_btn = True
        self.theme_btn.grid(row=0, column=1, padx=5)
        
        # 2. Paths inputs frame
        self.content_frame = tk.Frame(self.root, padx=15, pady=15)
        self.content_frame.is_card = True
        self.content_frame.grid(row=1, column=0, fill='x', padx=15, pady=5)
        self.content_frame.columnconfigure(1, weight=1)
        
        # Source Files path
        self.src_label = tk.Label(self.content_frame, text="Початкові файли:", font=("Segoe UI", 10, "bold"))
        self.src_label.grid(row=0, column=0, sticky='w', pady=(5, 2))
        
        self.src_entry = tk.Entry(self.content_frame, font=("Segoe UI", 10), relief='flat', bd=1, highlightthickness=1)
        self.src_entry.grid(row=1, column=0, columnspan=2, fill='x', sticky='we', ipady=4, padx=(0, 5))
        
        self.src_browse_btn = tk.Button(self.content_frame, text="Огляд...", font=("Segoe UI", 10), command=self.browse_src, padx=10)
        self.src_browse_btn.grid(row=1, column=2, sticky='e', ipady=2)
        
        self.src_desc = tk.Label(self.content_frame, text="Оберіть папку, яка містить оригінальні фото- та відеофайли для аналізу.", font=("Segoe UI", 8, "italic"))
        self.src_desc.is_subtext = True
        self.src_desc.grid(row=2, column=0, columnspan=3, sticky='w', pady=(2, 10))
        
        # Results path
        self.dest_label = tk.Label(self.content_frame, text="Результати:", font=("Segoe UI", 10, "bold"))
        self.dest_label.grid(row=3, column=0, sticky='w', pady=(5, 2))
        
        self.dest_entry = tk.Entry(self.content_frame, font=("Segoe UI", 10), relief='flat', bd=1, highlightthickness=1)
        self.dest_entry.grid(row=4, column=0, columnspan=2, fill='x', sticky='we', ipady=4, padx=(0, 5))
        
        self.dest_browse_btn = tk.Button(self.content_frame, text="Огляд...", font=("Segoe UI", 10), command=self.browse_dest, padx=10)
        self.dest_browse_btn.grid(row=4, column=2, sticky='e', ipady=2)
        
        self.dest_desc = tk.Label(self.content_frame, text="Оберіть папку, куди будуть збережені копії файлів із відновленими атрибутами дати.", font=("Segoe UI", 8, "italic"))
        self.dest_desc.is_subtext = True
        self.dest_desc.grid(row=5, column=0, columnspan=3, sticky='w', pady=(2, 5))
        
        # 3. Log console frame
        self.log_frame = tk.Frame(self.root, padx=15, pady=5)
        self.log_frame.is_card = True
        self.log_frame.grid(row=2, column=0, fill='both', padx=15, pady=5)
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(1, weight=1)
        
        self.log_label = tk.Label(self.log_frame, text="Журнал роботи:", font=("Segoe UI", 10, "bold"))
        self.log_label.grid(row=0, column=0, sticky='w', pady=(0, 2))
        
        self.log_console = ScrolledText(self.log_frame, font=("Courier New", 9), wrap='word', state='disabled', relief='flat', bd=0)
        self.log_console.grid(row=1, column=0, fill='both', sticky='nsew')
        
        # 4. Progress and start processing frame
        self.control_frame = tk.Frame(self.root, padx=15, pady=10)
        self.control_frame.is_card = False
        self.control_frame.grid(row=3, column=0, fill='x', padx=15, pady=10)
        self.control_frame.columnconfigure(0, weight=1)
        
        self.progress_label = tk.Label(self.control_frame, text="Готово до роботи", font=("Segoe UI", 9))
        self.progress_label.is_subtext = True
        self.progress_label.grid(row=0, column=0, sticky='w', pady=(0, 2))
        
        self.progress_bar = ttk.Progressbar(self.control_frame, orient="horizontal", mode="determinate")
        self.progress_bar.grid(row=1, column=0, fill='x', sticky='we', pady=(0, 10))
        
        self.action_btn_frame = tk.Frame(self.control_frame)
        self.action_btn_frame.is_card = False
        self.action_btn_frame.grid(row=2, column=0, fill='x')
        self.action_btn_frame.columnconfigure(0, weight=1)
        
        self.start_btn = tk.Button(self.action_btn_frame, text="Запустити обробку 🚀", font=("Segoe UI", 11, "bold"), command=self.start_processing, padx=20, pady=10)
        self.start_btn.is_primary = True
        self.start_btn.grid(row=0, column=0, fill='x')

    def toggle_theme(self):
        self.current_theme = 'light' if self.current_theme == 'dark' else 'dark'
        self.apply_current_theme()
        save_config(self.current_theme, self.src_entry.get().strip(), self.dest_entry.get().strip())

    def apply_current_theme(self):
        colors = THEMES[self.current_theme]
        self.root.configure(bg=colors['bg'])
        apply_theme_to_widget(self.root, colors)
        
        theme_btn_text = "Світла тема ☀️" if self.current_theme == 'dark' else "Темна тема 🌙"
        self.theme_btn.configure(text=theme_btn_text)
        
        self.configure_log_tags(colors)
        
        self.style = ttk.Style()
        self.style.theme_use('default')
        self.style.configure(
            "TProgressbar",
            troughcolor=colors['entry_bg'],
            background=colors['accent'],
            bordercolor=colors['bg'],
            lightcolor=colors['accent'],
            darkcolor=colors['accent']
        )
        
        # Apply theme to open Help window
        if self.help_window is not None and tk.Toplevel.winfo_exists(self.help_window):
            self.help_window.configure(bg=colors['bg'])
            self.configure_text_tags(self.help_text_widget, colors)
            apply_theme_to_widget(self.help_window, colors)

    def configure_log_tags(self, colors):
        self.log_console.tag_configure('info', foreground=colors['text'])
        self.log_console.tag_configure('success', foreground=colors['success'])
        self.log_console.tag_configure('warning', foreground=colors['warning'])
        self.log_console.tag_configure('error', foreground=colors['error'])

    def configure_text_tags(self, text_widget, colors):
        text_widget.configure(bg=colors['log_bg'], fg=colors['text'])
        text_widget.tag_configure('h1', font=('Segoe UI', 18, 'bold'), foreground=colors['accent'], spacing1=15, spacing3=5)
        text_widget.tag_configure('h2', font=('Segoe UI', 14, 'bold'), foreground=colors['text'], spacing1=10, spacing3=5)
        text_widget.tag_configure('h3', font=('Segoe UI', 12, 'bold'), foreground=colors['text'], spacing1=8, spacing3=3)
        text_widget.tag_configure('body', font=('Segoe UI', 10), foreground=colors['text'], spacing2=3)
        text_widget.tag_configure('bold', font=('Segoe UI', 10, 'bold'), foreground=colors['text'])
        text_widget.tag_configure('bullet', font=('Segoe UI', 10), foreground=colors['text'], lmargin1=20, lmargin2=30, spacing1=3)
        text_widget.tag_configure('code', font=('Courier New', 10), background=colors['entry_bg'], foreground=colors['text'], lmargin1=15, lmargin2=15)
        text_widget.tag_configure('link', font=('Segoe UI', 10, 'underline'), foreground=colors['accent'])

    def show_help(self):
        if self.help_window is not None and tk.Toplevel.winfo_exists(self.help_window):
            self.help_window.lift()
            return
            
        self.help_window = tk.Toplevel(self.root)
        self.help_window.title("Довідка - PhotoCheckDate")
        self.help_window.geometry("650x550")
        self.help_window.minsize(500, 400)
        
        # Center help window
        self.help_window.update_idletasks()
        w = self.help_window.winfo_width()
        h = self.help_window.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.help_window.geometry(f'{w}x{h}+{x}+{y}')
        
        colors = THEMES[self.current_theme]
        self.help_window.configure(bg=colors['bg'])
        
        self.help_window.columnconfigure(0, weight=1)
        self.help_window.rowconfigure(0, weight=1)
        
        self.help_text_widget = ScrolledText(self.help_window, font=("Segoe UI", 10), wrap='word', relief='flat', bd=0, padx=15, pady=15)
        self.help_text_widget.grid(row=0, column=0, fill='both', sticky='nsew', padx=10, pady=10)
        
        self.configure_text_tags(self.help_text_widget, colors)
        render_markdown_in_text(self.help_text_widget, self.readme_content)
        
        apply_theme_to_widget(self.help_window, colors)
        
        def on_close():
            self.help_window.destroy()
            self.help_window = None
            self.help_text_widget = None
            
        self.help_window.protocol("WM_DELETE_WINDOW", on_close)

    def browse_src(self):
        path = filedialog.askdirectory(title="Оберіть початкову папку")
        if path:
            self.src_entry.delete(0, tk.END)
            self.src_entry.insert(0, os.path.normpath(path))
            
    def browse_dest(self):
        path = filedialog.askdirectory(title="Оберіть папку результатів")
        if path:
            self.dest_entry.delete(0, tk.END)
            self.dest_entry.insert(0, os.path.normpath(path))

    def set_ui_state(self, state):
        self.src_entry.configure(state=state)
        self.dest_entry.configure(state=state)
        self.src_browse_btn.configure(state=state)
        self.dest_browse_btn.configure(state=state)
        self.start_btn.configure(state=state)
        self.help_btn.configure(state=state)
        self.theme_btn.configure(state=state)

    def log(self, message, level='INFO'):
        self.root.after(0, self._log_main_thread, message, level)
        
    def _log_main_thread(self, message, level):
        self.log_console.configure(state='normal')
        self.log_console.insert('end', message + '\n', level.lower())
        self.log_console.configure(state='disabled')
        self.log_console.see('end')

    def setup_progress(self, total):
        self.progress_bar.configure(maximum=total, value=0)
        self.progress_label.configure(text=f"Оброблено файлів: 0 з {total} (0%)")
        
    def update_progress(self, current, total):
        self.progress_bar.configure(value=current)
        percent = int((current / total) * 100)
        self.progress_label.configure(text=f"Оброблено файлів: {current} з {total} ({percent}%)")
        
    def processing_finished(self, total, success):
        self.set_ui_state('normal')
        self.progress_label.configure(text="Обробку завершено")
        self.log(f"\nРоботу завершено! Оброблено файлів: {total}. Змінено атрибути для: {success}.", "SUCCESS")
        messagebox.showinfo(
            "Завершено", 
            f"Успішно оброблено файлів: {total}.\nЗмінено атрибутів дати: {success}."
        )

    def start_processing(self):
        src_path = self.src_entry.get().strip()
        dest_path = self.dest_entry.get().strip()
        
        if not src_path:
            messagebox.showerror("Помилка", "Будь ласка, вкажіть початкову папку.")
            return
        if not os.path.isdir(src_path):
            messagebox.showerror("Помилка", "Початкова папка не існує.")
            return
        if not dest_path:
            messagebox.showerror("Помилка", "Будь ласка, вкажіть папку результатів.")
            return
            
        # Save settings to config
        save_config(self.current_theme, src_path, dest_path)
        
        src_abs = os.path.abspath(src_path)
        dest_abs = os.path.abspath(dest_path)
        
        if dest_abs == src_abs or dest_abs.startswith(src_abs + os.sep):
            messagebox.showerror(
                "Помилка", 
                "Папка результатів не може бути самою початковою папкою або її підпапкою."
            )
            return
            
        try:
            os.makedirs(dest_path, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Помилка", f"Не вдалося створити папку результатів:\n{str(e)}")
            return
            
        self.set_ui_state('disabled')
        
        self.log_console.configure(state='normal')
        self.log_console.delete('1.0', tk.END)
        self.log_console.configure(state='disabled')
        
        self.worker_thread = threading.Thread(
            target=self.process_files_worker,
            args=(src_abs, dest_abs)
        )
        self.worker_thread.daemon = True
        self.worker_thread.start()

    def process_files_worker(self, src_dir, dest_dir):
        self.log("Розпочато сканування файлів...", "INFO")
        
        photo_exts = ('.jpg', '.jpeg', '.png', '.tiff', '.heic', '.heif')
        video_exts = ('.mp4', '.mov')
        audio_exts = ('.mp3',)
        supported_exts = photo_exts + video_exts + audio_exts
        
        files_to_process = []
        for root, dirs, filenames in os.walk(src_dir):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in supported_exts:
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, src_dir)
                    files_to_process.append((full_path, rel_path, ext))
                    
        total_files = len(files_to_process)
        if total_files == 0:
            self.log("У початковій папці не знайдено підтримуваних файлів.", "WARNING")
            self.root.after(0, self.processing_finished, 0, 0)
            return
            
        self.log(f"Знайдено файлів для обробки: {total_files}", "INFO")
        self.root.after(0, self.setup_progress, total_files)
        
        processed_count = 0
        success_count = 0
        
        for src_file, rel_path, ext in files_to_process:
            filename = os.path.basename(src_file)
            self.log(f"Аналіз: {rel_path}...", "INFO")
            
            date_found = None
            source_info = ""
            
            # 1. Filename (Priority)
            date_found = extract_date_from_filename(filename)
            if date_found:
                source_info = "ім'я файлу"
            
            # 2. Metadata EXIF / Containers (Fallback)
            if not date_found:
                if ext in photo_exts:
                    date_found = get_photo_creation_time(src_file)
                    if date_found:
                        source_info = "EXIF метадані фото"
                elif ext in video_exts:
                    date_found = get_mp4_creation_time(src_file)
                    if date_found:
                        source_info = "метадані відео (mvhd)"
                elif ext in audio_exts:
                    date_found = get_mp3_creation_time(src_file)
                    if date_found:
                        source_info = "метадані аудіо (ID3)"
            
            # 3. Oldest filesystem attribute (Final fallback)
            if not date_found:
                try:
                    mtime = os.path.getmtime(src_file)
                    ctime = os.path.getctime(src_file)
                    oldest = min(mtime, ctime)
                    date_found = datetime.datetime.fromtimestamp(oldest)
                    source_info = "найстаріший системний атрибут"
                except Exception:
                    date_found = datetime.datetime.now()
                    source_info = "поточний час (помилка зчитування атрибутів)"
            
            target_file = os.path.join(dest_dir, rel_path)
            target_dir = os.path.dirname(target_file)
            
            try:
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(src_file, target_file)
                
                # Apply attributes
                set_file_times(target_file, date_found)
                self.log(f"  -> Встановлено дату: {date_found.strftime('%Y-%m-%d %H:%M:%S')} ({source_info}).", "SUCCESS")
                success_count += 1
            except Exception as e:
                self.log(f"  -> Помилка: {str(e)}", "ERROR")
                
            processed_count += 1
            self.root.after(0, self.update_progress, processed_count, total_files)
            
        self.root.after(0, self.processing_finished, processed_count, success_count)


# Splash / Installer screen logic
class DependencyInstallerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Встановлення залежностей - PhotoCheckDate")
        self.root.geometry("450x180")
        self.root.resizable(False, False)
        
        # Center installer window on screen
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'+{x}+{y}')
        
        self.root.configure(bg="#1e1e2e")
        
        self.label = tk.Label(
            self.root, 
            text="Встановлення необхідних бібліотек...\n(Pillow, pillow-heif)\nЦе може зайняти до хвилини.",
            font=("Segoe UI", 11),
            bg="#1e1e2e",
            fg="#cdd6f4",
            justify="center"
        )
        self.label.pack(pady=30)
        
        self.progress_label = tk.Label(
            self.root,
            text="Встановлення через pip...",
            font=("Segoe UI", 9, "italic"),
            bg="#1e1e2e",
            fg="#a6adc8"
        )
        self.progress_label.pack()
        
        self.error_occurred = False
        self.install_thread = threading.Thread(target=self.run_install)
        self.install_thread.daemon = True
        self.install_thread.start()
        
        self.check_status()
        
    def run_install(self):
        try:
            # Run pip install using sys.executable to install into current python environment
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "pillow", "pillow-heif"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            self.error_occurred = True
            
    def check_status(self):
        if self.install_thread.is_alive():
            current_text = self.progress_label.cget("text")
            if current_text.endswith("..."):
                self.progress_label.configure(text="Встановлення через pip")
            else:
                self.progress_label.configure(text=current_text + ".")
            self.root.after(500, self.check_status)
        else:
            if self.error_occurred:
                messagebox.showerror(
                    "Помилка", 
                    "Не вдалося встановити залежності.\nБудь ласка, перевірте інтернет або запустіть команду:\npip install pillow pillow-heif\nвручну."
                )
                self.root.destroy()
                sys.exit(1)
            else:
                self.root.destroy()
                run_main_app()

def run_main_app():
    """Initializes and runs the main application after dependencies check/installation."""
    global Image, pillow_heif
    from PIL import Image
    import pillow_heif
    from pillow_heif import register_heif_opener
    register_heif_opener()
    
    root = tk.Tk()
    app = PhotoCheckDateApp(root)
    root.mainloop()

if __name__ == "__main__":
    if check_dependencies():
        run_main_app()
    else:
        # Launch splash installer if dependencies are missing
        root = tk.Tk()
        installer = DependencyInstallerApp(root)
        root.mainloop()
