"""probe.py - DPI-aware window/screenshot/click probe for locating check-in buttons."""
import sys
import os
import time
import ctypes
import ctypes.wintypes as wt
import struct
import zlib
import subprocess

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SW_RESTORE = 9

try:
    user32.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


def screen_size():
    w = user32.GetSystemMetrics(SM_CXSCREEN)
    h = user32.GetSystemMetrics(SM_CYSCREEN)
    return w, h


def _pids():
    import subprocess as sp
    try:
        out = sp.check_output(["tasklist", "/FO", "CSV", "/NH"], encoding="mbcs", errors="replace")
    except Exception:
        return {}
    m = {}
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2:
            try:
                m[int(parts[1])] = parts[0]
            except ValueError:
                pass
    return m


def list_windows():
    pmap = _pids()
    result = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 60 or h < 60:
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        result.append({
            "hwnd": int(hwnd),
            "title": title.value,
            "class": cls.value,
            "pid": int(pid.value),
            "proc": pmap.get(int(pid.value), "?"),
            "rect": (rect.left, rect.top, rect.right, rect.bottom),
        })
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return result


def shot_full(path):
    w, h = screen_size()
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)
    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, 0, 0, SRCCOPY)
    _save_dib(hdc_mem, hbmp, w, h, path)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)


def shot_window(hwnd, path):
    w, h, buf = capture_window(hwnd)
    rows = []
    for y in range(h):
        row = bytearray(w * 3)
        base = y * w * 4
        for x in range(w):
            row[x * 3] = buf[base + x * 4 + 2]
            row[x * 3 + 1] = buf[base + x * 4 + 1]
            row[x * 3 + 2] = buf[base + x * 4]
        rows.append(bytes(row))
    _write_png(path, w, h, rows)


def capture_window(hwnd):
    """Capture window content via PrintWindow (works even if obscured). Returns (w, h, bgra)."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.6)
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    hdc_win = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)
    PW_RENDERFULLCONTENT = 0x00000002
    ok = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
    if not ok:
        user32.PrintWindow(hwnd, hdc_mem, 0)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf = (ctypes.c_ubyte * (w * h * 4))()
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_win)
    return w, h, buf


def shot_window_crop(hwnd, x, y, w, h, path):
    ww, hh, buf = capture_window(hwnd)
    rows = []
    for yy in range(y, min(y + h, hh)):
        row = bytearray(w * 3)
        base = yy * ww * 4
        for xx in range(x, min(x + w, ww)):
            ox = xx - x
            row[ox * 3] = buf[base + xx * 4 + 2]
            row[ox * 3 + 1] = buf[base + xx * 4 + 1]
            row[ox * 3 + 2] = buf[base + xx * 4]
        rows.append(bytes(row))
    _write_png(path, w, h, rows)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


def _save_dib(hdc_mem, hbmp, w, h, path):
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf = (ctypes.c_ubyte * (w * h * 4))()
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
    # buf is BGRA top-down; convert to RGB rows
    rows = []
    for y in range(h):
        row = bytearray(w * 3)
        base = y * w * 4
        for x in range(w):
            row[x * 3] = buf[base + x * 4 + 2]      # R
            row[x * 3 + 1] = buf[base + x * 4 + 1]  # G
            row[x * 3 + 2] = buf[base + x * 4]      # B
        rows.append(bytes(row))
    _write_png(path, w, h, rows)


def _write_png(path, w, h, rgb_rows):
    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        c += struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        return c
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rgb_rows)
    idat = zlib.compress(raw, 6)
    with open(path, "wb") as f:
        f.write(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def shot_rect(left, top, w, h, path):
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)
    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, left, top, SRCCOPY)
    _save_dib(hdc_mem, hbmp, w, h, path)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


def cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def restore(hwnd):
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)


def launch(exe, cwd):
    return subprocess.Popen([exe], cwd=cwd)


def windows_by_proc(proc_substr):
    """Enumerate ALL top-level windows (incl. minimized/invisible) matching process name."""
    pmap = _pids()
    result = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pname = pmap.get(int(pid.value), "")
        if proc_substr.lower() not in pname.lower():
            return True
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        result.append({
            "hwnd": int(hwnd),
            "title": title.value,
            "class": cls.value,
            "pid": int(pid.value),
            "proc": pname,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "rect": (rect.left, rect.top, rect.right, rect.bottom),
        })
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return result


def capture_region(left, top, w, h):
    """Capture screen region as top-down BGRA bytes."""
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbmp)
    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, left, top, SRCCOPY)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0
    buf = (ctypes.c_ubyte * (w * h * 4))()
    gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)
    return w, h, buf


def find_black_blobs(w, h, buf, dark_threshold=70, min_area=400):
    """Find connected components of dark pixels. Returns list of (area, cx, cy, minx, miny, maxx, maxy)."""
    seen = bytearray(w * h)
    blobs = []
    stack = []
    for y in range(h):
        row = y * w
        for x in range(w):
            if seen[row + x]:
                continue
            idx = (row + x) * 4
            r = buf[idx + 2]
            g = buf[idx + 1]
            b = buf[idx]
            if r < dark_threshold and g < dark_threshold and b < dark_threshold:
                # flood fill
                stack.append((x, y))
                seen[row + x] = 1
                area = 0
                minx = maxx = x
                miny = maxy = y
                while stack:
                    cx, cy = stack.pop()
                    area += 1
                    if cx < minx: minx = cx
                    if cx > maxx: maxx = cx
                    if cy < miny: miny = cy
                    if cy > maxy: maxy = cy
                    for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                        if 0 <= nx < w and 0 <= ny < h:
                            p = ny * w + nx
                            if not seen[p]:
                                seen[p] = 1
                                q = p * 4
                                if buf[q + 2] < dark_threshold and buf[q + 1] < dark_threshold and buf[q] < dark_threshold:
                                    stack.append((nx, ny))
                if area >= min_area:
                    blobs.append((area, (minx + maxx) // 2, (miny + maxy) // 2, minx, miny, maxx, maxy))
    blobs.sort(reverse=True)
    return blobs


def find_color_blobs(w, h, buf, rmin, rmax, gmin, gmax, bmin, bmax, min_area=10):
    """Find connected components of pixels within a color range."""
    seen = bytearray(w * h)
    blobs = []
    stack = []

    def match(i):
        return (rmin <= buf[i + 2] <= rmax and gmin <= buf[i + 1] <= gmax and bmin <= buf[i] <= bmax)

    for y in range(h):
        row = y * w
        for x in range(w):
            if seen[row + x]:
                continue
            idx = (row + x) * 4
            if match(idx):
                stack.append((x, y))
                seen[row + x] = 1
                area = 0
                minx = maxx = x
                miny = maxy = y
                while stack:
                    cx, cy = stack.pop()
                    area += 1
                    minx = min(minx, cx); maxx = max(maxx, cx)
                    miny = min(miny, cy); maxy = max(maxy, cy)
                    for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                        if 0 <= nx < w and 0 <= ny < h:
                            p = ny * w + nx
                            if not seen[p]:
                                seen[p] = 1
                                if match(p * 4):
                                    stack.append((nx, ny))
                if area >= min_area:
                    blobs.append((area, (minx + maxx) // 2, (miny + maxy) // 2, minx, miny, maxx, maxy))
    blobs.sort(reverse=True)
    return blobs


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return
    cmd = argv[0]
    if cmd == "list":
        for w in list_windows():
            r = w["rect"]
            print(f"hwnd={w['hwnd']} proc={w['proc']} pid={w['pid']} title={w['title']!r} "
                  f"class={w['class']!r} rect=({r[0]},{r[1]})-({r[2]},{r[3]}) size={r[2]-r[0]}x{r[3]-r[1]}")
    elif cmd == "shot":
        shot_full(argv[1])
        print("saved", argv[1], "size", screen_size())
    elif cmd == "shotrect":
        shot_rect(int(argv[1]), int(argv[2]), int(argv[3]), int(argv[4]), argv[5])
        print("saved", argv[5])
    elif cmd == "shotwin":
        hwnd = int(argv[1])
        shot_window(hwnd, argv[2])
        print("saved", argv[2])
    elif cmd == "shotwincrop":
        hwnd = int(argv[1])
        shot_window_crop(hwnd, int(argv[2]), int(argv[3]), int(argv[4]), int(argv[5]), argv[6])
        print("saved", argv[6])
    elif cmd == "click":
        click(int(argv[1]), int(argv[2]))
        print("clicked", argv[1], argv[2])
    elif cmd == "cursor":
        print(cursor_pos())
    elif cmd == "restore":
        restore(int(argv[1]))
        print("restored", argv[1])
    elif cmd == "hwnds":
        for w in windows_by_proc(argv[1]):
            r = w["rect"]
            print(f"hwnd={w['hwnd']} proc={w['proc']} vis={w['visible']} title={w['title']!r} "
                  f"class={w['class']!r} rect=({r[0]},{r[1]})-({r[2]},{r[3]}) size={r[2]-r[0]}x{r[3]-r[1]}")
    elif cmd == "blackblobs":
        # args: hwnd x y w h  (window-relative crop)
        hwnd = int(argv[1])
        x, y, w, h = int(argv[2]), int(argv[3]), int(argv[4]), int(argv[5])
        ww, hh, buf = capture_window(hwnd)
        # crop the region into a dense buffer
        crop = bytearray(w * h * 4)
        for yy in range(h):
            src = (y + yy) * ww * 4
            dst = yy * w * 4
            crop[dst:dst + w * 4] = buf[src + x * 4:src + (x + w) * 4]
        for area, cx, cy, minx, miny, maxx, maxy in find_black_blobs(w, h, crop)[:12]:
            print(f"area={area} center=({x + cx},{y + cy}) bbox=({x + minx},{y + miny})-({x + maxx},{y + maxy}) "
                  f"size={maxx - minx}x{maxy - miny}")
    elif cmd == "launch":
        launch(argv[1], argv[2] if len(argv) > 2 else os.path.dirname(argv[1]))
        print("launched", argv[1])
    elif cmd == "clickwin":
        hwnd = int(argv[1]); x = int(argv[2]); y = int(argv[3])
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.6)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        ax, ay = rect.left + x, rect.top + y
        click(ax, ay)
        print(f"clicked hwnd={hwnd} win=({x},{y}) abs=({ax},{ay})")
    elif cmd == "greenblobs":
        hwnd = int(argv[1])
        x, y, w, h = int(argv[2]), int(argv[3]), int(argv[4]), int(argv[5])
        ww, hh, buf = capture_window(hwnd)
        crop = bytearray(w * h * 4)
        for yy in range(h):
            src = (y + yy) * ww * 4
            dst = yy * w * 4
            crop[dst:dst + w * 4] = buf[src + x * 4:src + (x + w) * 4]
        # teal/green active dot
        for area, cx, cy, minx, miny, maxx, maxy in find_color_blobs(w, h, crop, 0, 200, 120, 255, 0, 220, min_area=8)[:12]:
            print(f"area={area} center=({x + cx},{y + cy}) bbox=({x + minx},{y + miny})-({x + maxx},{y + maxy})")
    elif cmd == "size":
        print(screen_size())


if __name__ == "__main__":
    main()
