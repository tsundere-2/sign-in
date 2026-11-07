#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日全自动签到统一入口：TRAE CN / WorkBuddy / 商汤小浣熊 / Qoder CN。

用 pythonw.exe 运行即可完全隐形（无控制台窗口）：
    pythonw.exe "D:\\qiandao\\sign in\\checkin.py"

也可用 python 运行观察日志：
    python "D:\\qiandao\\sign in\\checkin.py" --force
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(BASE, "logs")
STATE = os.path.join(BASE, "state.json")
CDP_MJS = os.path.join(BASE, "cdp.mjs")
os.makedirs(LOGDIR, exist_ok=True)

# ---------------------------------------------------------------- 日志 / 状态

def log(msg):
    line = f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        with open(os.path.join(LOGDIR, "checkin.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        if sys.stdout is not None:
            print(line, flush=True)
    except Exception:
        pass


def load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"[state] 保存失败: {e}")


def today():
    return dt.date.today().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- Win32 基础

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
SW_RESTORE = 9
SW_SHOW = 5
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001

kernel32.GetCurrentThreadId.restype = wt.DWORD
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = wt.BOOL
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
user32.BringWindowToTop.argtypes = [wt.HWND]
user32.BringWindowToTop.restype = wt.BOOL

try:
    user32.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


def list_processes():
    """pid -> image name（中文 Windows 需 mbcs 解码）。"""
    try:
        out = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"],
                                      encoding="mbcs", errors="replace")
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


def proc_running(substr):
    pmap = list_processes()
    return any(substr.lower() in name.lower() for name in pmap.values())


def kill_proc(image):
    try:
        subprocess.run(["taskkill", "/IM", image, "/F"],
                       capture_output=True, timeout=20)
    except Exception:
        pass


def launch(exe, args=None, cwd=None):
    cmd = [exe] + (args or [])
    return subprocess.Popen(cmd, cwd=cwd or os.path.dirname(exe))


def wait_process(substr, timeout=60, interval=1.0):
    end = time.time() + timeout
    while time.time() < end:
        if proc_running(substr):
            return True
        time.sleep(interval)
    return False


def wait_port(port, timeout=60, interval=1.0):
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read()
            return True
        except Exception:
            time.sleep(interval)
    return False


# ---------------------------------------------------------------- 窗口 / 点击

def find_main_window(proc_substr, min_w=800, min_h=600):
    """按进程名找最大主窗口（含隐藏到托盘、不可见但尺寸正常者），返回 (hwnd, rect) 或 None。"""
    pmap = list_processes()
    best = None
    best_area = 0
    EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        nonlocal best, best_area
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = pmap.get(int(pid.value), "")
        if proc_substr.lower() not in name.lower():
            return True
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < min_w or h < min_h:
            return True
        # 跳过屏幕外的占位/辅助窗口（坐标 -32000 之类）
        if rect.left <= -30000 and rect.top <= -30000:
            return True
        area = w * h
        if area > best_area:
            best_area = area
            best = (int(hwnd), rect)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return best


def force_foreground(hwnd):
    """可靠地把窗口带到前台：恢复 + 临时置顶 + AttachThreadInput 绕过前台锁。"""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if not user32.IsWindowVisible(hwnd):
        user32.ShowWindow(hwnd, SW_SHOW)
    # 临时置顶再取消，绕开 SetForegroundWindow 的前台锁定
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.05)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    fg = user32.GetForegroundWindow()
    cur = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    attached = bool(fg_tid) and fg_tid != cur
    if attached:
        user32.AttachThreadInput(cur, fg_tid, True)
    try:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(cur, fg_tid, False)
    time.sleep(0.3)


def restore(hwnd):
    force_foreground(hwnd)
    time.sleep(0.4)


def click_abs(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.1)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


def click_ratio(hwnd, rx, ry):
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    click_abs(rect.left + int(w * rx), rect.top + int(h * ry))


def capture_window(hwnd):
    """PrintWindow 抓取窗口内容（即使被遮挡），返回 (w, h, BGRA bytes)。"""
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
    user32.PrintWindow(hwnd, hdc_mem, 0x00000002)  # PW_RENDERFULLCONTENT
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


def find_black_blob_center(crop_w, crop_h, buf, dark=70, min_area=300):
    """在裁剪缓冲里按从上到下顺序找第一个足够大的深色连通域。
    领取按钮位于「查看详情」上方，取最上方者即领取按钮。返回 (cx, cy, minx, miny, maxx, maxy) 或 None。"""
    seen = bytearray(crop_w * crop_h)
    stack = []
    for y in range(crop_h):
        row = y * crop_w
        for x in range(crop_w):
            if seen[row + x]:
                continue
            i = (row + x) * 4
            if buf[i + 2] < dark and buf[i + 1] < dark and buf[i] < dark:
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
                        if 0 <= nx < crop_w and 0 <= ny < crop_h:
                            p = ny * crop_w + nx
                            if not seen[p]:
                                seen[p] = 1
                                q = p * 4
                                if buf[q + 2] < dark and buf[q + 1] < dark and buf[q] < dark:
                                    stack.append((nx, ny))
                if area >= min_area:
                    return ((minx + maxx) // 2, (miny + maxy) // 2, minx, miny, maxx, maxy)
    return None


# ---------------------------------------------------------------- CDP（node 原生 WebSocket）

def cdp_eval(expr, port, timeout=25):
    r = subprocess.run(["node", CDP_MJS, expr, str(port), ""],
                       capture_output=True, text=True, timeout=timeout, cwd=BASE)
    return r.stdout.strip(), r.returncode


def cdp_poll(port, js, expect, timeout=40, interval=1.0):
    """轮询 CDP，直到返回 expect 集合中的某个值。返回 (最终输出, 是否命中)。"""
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        out, _ = cdp_eval(js, port)
        last = out
        if out in expect:
            return out, True
        time.sleep(interval)
    return last, False


# ---------------------------------------------------------------- 各平台流程

def do_raccoon(force):
    key = "raccoon"
    exe = r"D:\raccoon\raccoon-ai\商汤小浣熊.exe"
    img = "商汤小浣熊.exe"
    st = load_state()
    if not force and st.get(key) == today():
        log("[小浣熊] 今日已完成，跳过")
        return "already"
    if not os.path.isfile(exe):
        log(f"[小浣熊] 未找到 {exe}")
        return "failed"
    was_running = proc_running(img)
    log("[小浣熊] 启动客户端（打开即自动签到）...")
    try:
        launch(exe)
    except Exception as e:
        log(f"[小浣熊] 启动失败: {e}")
        return "failed"
    if not wait_process(img, 30):
        log("[小浣熊] 30 秒内未检测到进程，可能启动即退出")
        return "failed"
    time.sleep(15)  # 等客户端完全打开并完成自动签到
    if not was_running:
        kill_proc(img)
        time.sleep(1)
    st[key] = today()
    save_state(st)
    log("[小浣熊] 完成")
    return "claimed"


def workbuddy_claimed_today():
    """WorkBuddy 今日是否已发出 daily-checkin 领取请求（读客户端日志）。"""
    dlog = os.path.join(os.path.expanduser("~"), ".workbuddy", "logs",
                        dt.date.today().strftime("%Y-%m-%d"))
    if not os.path.isdir(dlog):
        return False
    pat = re.compile(r"check-in outgoing path=/v2/billing/meter/daily-checkin")
    for fn in os.listdir(dlog):
        if not fn.endswith(".log"):
            continue
        try:
            with open(os.path.join(dlog, fn), "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if pat.search(line):
                        return True
        except Exception:
            continue
    return False


def do_workbuddy(force):
    key = "workbuddy"
    exe = r"D:\workbuddy\WorkBuddy.exe"
    img = "WorkBuddy.exe"
    port = 9222
    st = load_state()
    if not force and st.get(key) == today():
        log("[WorkBuddy] 今日已完成，跳过")
        return "already"
    if not force and workbuddy_claimed_today():
        log("[WorkBuddy] 日志显示今日已领取（daily-checkin），跳过")
        st[key] = today()
        save_state(st)
        return "already"
    if not os.path.isfile(exe):
        log(f"[WorkBuddy] 未找到 {exe}")
        return "failed"
    was_running = proc_running(img)
    try:
        if not was_running:
            log("[WorkBuddy] 启动（--remote-debugging-port）...")
            launch(exe, ["--remote-debugging-port=" + str(port)])
        if not wait_port(port, 60):
            log("[WorkBuddy] CDP 端口未就绪")
            return "failed"

        claim_js = (
            "(()=>{const hits=[];(function walk(r){let els;try{els=r.querySelectorAll('*')}catch(e){return}"
            "for(const e of els){if(e.shadowRoot)walk(e.shadowRoot);"
            "if(e.childElementCount===0&&(e.textContent||'').trim()==='立即领取')hits.push(e)}})(document);"
            "if(!hits.length)return 'NOT_FOUND';hits[0].click();return 'CLICKED'})()"
        )
        check_js = (
            "(()=>{let n=0;(function walk(r){let els;try{els=r.querySelectorAll('*')}catch(e){return}"
            "for(const e of els){if(e.shadowRoot)walk(e.shadowRoot);"
            "if(e.childElementCount===0&&(e.textContent||'').trim()==='立即领取')n++}})(document);"
            "return n===0?'GONE':'STILL:'+n})()"
        )

        out, hit = cdp_poll(port, claim_js, {"CLICKED"}, timeout=45)
        if hit:
            # 按钮消失可能要几秒，轮询确认；若按钮迟迟不消失，以日志 daily-checkin 为准
            gone = False
            end = time.time() + 15
            while time.time() < end:
                time.sleep(2)
                out2, _ = cdp_eval(check_js, port)
                if out2 == "GONE":
                    gone = True
                    break
            if gone or workbuddy_claimed_today():
                log("[WorkBuddy] 领取成功")
                st[key] = today()
                save_state(st)
                return "claimed"
            log("[WorkBuddy] 点击后既未见按钮消失也未记录到领取请求，视为失败")
            return "failed"
        # 轮询超时未出现「立即领取」按钮：再确认一次，按钮确实不存在则视为今日已领
        out2, _ = cdp_eval(check_js, port)
        if out2 == "GONE":
            log("[WorkBuddy] 未出现「立即领取」按钮，视为今日已领取")
            st[key] = today()
            save_state(st)
            return "already"
        log(f"[WorkBuddy] 未能领取（最终状态 {out2}）")
        return "failed"
    except Exception as e:
        log(f"[WorkBuddy] 异常: {e!r}")
        return "failed"
    finally:
        if not was_running:
            kill_proc(img)
            time.sleep(1)


def do_trae(force):
    key = "trae"
    exe = r"C:\Users\14976\AppData\Local\Programs\Trae CN\Trae CN.exe"
    img = "Trae CN.exe"
    port = 9223
    st = load_state()
    if not force and st.get(key) == today():
        log("[TRAE CN] 今日已完成，跳过")
        return "already"
    if not os.path.isfile(exe):
        log(f"[TRAE CN] 未找到 {exe}")
        return "failed"
    was_running = proc_running(img)
    try:
        if not was_running:
            log("[TRAE CN] 启动（--remote-debugging-port）...")
            launch(exe, ["--remote-debugging-port=" + str(port)])
        if not wait_port(port, 60):
            log("[TRAE CN] CDP 端口未就绪")
            return "failed"

        user_check_js = (
            "(()=>{let el=null;(function walk(r){let els;try{els=r.querySelectorAll('*')}catch(e){return}"
            "for(const e of els){if(e.shadowRoot)walk(e.shadowRoot);"
            "if(!el&&e.childElementCount===0&&/^用户\\d+$/.test((e.textContent||'').trim()))el=e}})(document);"
            "return el?'FOUND':'NO_USER'})()"
        )
        open_user_js = (
            "(()=>{let el=null;(function walk(r){let els;try{els=r.querySelectorAll('*')}catch(e){return}"
            "for(const e of els){if(e.shadowRoot)walk(e.shadowRoot);"
            "if(!el&&e.childElementCount===0&&/^用户\\d+$/.test((e.textContent||'').trim()))el=e}})(document);"
            "if(!el)return 'NO_USER';el.click();return 'CLICKED_USER'})()"
        )
        claim_js = (
            "(()=>{let done=null,claim=null;(function walk(r){let els;try{els=r.querySelectorAll('*')}catch(e){return}"
            "for(const e of els){if(e.shadowRoot)walk(e.shadowRoot);if(e.childElementCount!==0)continue;"
            "const t=(e.textContent||'').trim();if(t==='已签到'&&!done)done=e;else if(t==='签到'&&!claim)claim=e}})(document);"
            "if(done)return 'ALREADY';if(!claim)return 'NO_BUTTON';claim.click();return 'CLICKED'})()"
        )

        # 1) 等界面加载出账号入口
        out, hit = cdp_poll(port, user_check_js, {"FOUND"}, timeout=45)
        if not hit:
            log(f"[TRAE CN] 45 秒内未找到账号入口: {out}")
            return "failed"
        # 2) 打开账号菜单
        out, _ = cdp_eval(open_user_js, port)
        if out != "CLICKED_USER":
            log(f"[TRAE CN] 打开账号菜单失败: {out}")
            return "failed"
        time.sleep(1.5)
        # 3) 菜单内找「签到」（未签）或「已签到」（已签）
        out, hit = cdp_poll(port, claim_js, {"CLICKED", "ALREADY"}, timeout=20)
        if out == "ALREADY":
            log("[TRAE CN] 已签到，跳过")
            st[key] = today()
            save_state(st)
            return "already"
        if not hit:
            log(f"[TRAE CN] 菜单内未找到签到按钮: {out}")
            return "failed"
        # 4) 已点击「签到」，确认变为「已签到」
        out3, hit3 = cdp_poll(port, claim_js, {"ALREADY"}, timeout=12)
        if not hit3:
            log(f"[TRAE CN] 签到后未确认到「已签到」: {out3}")
            return "failed"
        log("[TRAE CN] 签到成功")
        st[key] = today()
        save_state(st)
        return "claimed"
    except Exception as e:
        log(f"[TRAE CN] 异常: {e!r}")
        return "failed"
    finally:
        if not was_running:
            kill_proc(img)
            time.sleep(1)


def qoder_campaign_status():
    """读取今日 Qoder 领取状态：claimed / claimable / none / unknown。"""
    logs_dir = os.path.join(os.environ.get("APPDATA", ""), "com.qodercn.app.stable", "logs")
    if not os.path.isdir(logs_dir):
        return "unknown"
    today_local = dt.date.today()
    pat = re.compile(r"\[(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2}\.\d+)Z\].*hasClaimableCampaign\":(true|false)")
    statuses = []
    for root, _dirs, files in os.walk(logs_dir):
        for fn in files:
            if fn != "main.log":
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        m = pat.search(line)
                        if not m:
                            continue
                        d = dt.datetime.strptime(m.group(1), "%Y-%m-%d").date()
                        t = dt.datetime.strptime(m.group(2), "%H:%M:%S.%f").time()
                        local_dt = dt.datetime.combine(d, t) + dt.timedelta(hours=8)
                        if local_dt.date() == today_local:
                            statuses.append((local_dt, m.group(3) == "true"))
            except Exception:
                continue
    if not statuses:
        return "none"
    statuses.sort()
    latest_true = statuses[-1][1]
    saw_true = any(s for _, s in statuses)
    if latest_true is False and saw_true:
        return "claimed"
    if latest_true is True:
        return "claimable"
    return "none"


def qoder_exe():
    base = r"D:\Qoder\Qoder CN\.qoder-versions"
    if not os.path.isdir(base):
        return None
    cands = []
    for d in os.listdir(base):
        p = os.path.join(base, d, "Qoder CN.exe")
        if os.path.isfile(p):
            cands.append((d, p))
    if not cands:
        return None
    def key(pair):
        nums = re.findall(r"\d+", pair[0])
        return [int(n) for n in nums] or [0]
    cands.sort(key=key)
    return cands[-1][1]


def do_qoder(force):
    key = "qoder"
    img = "Qoder CN.exe"
    st = load_state()
    if not force and st.get(key) == today():
        log("[Qoder CN] 今日已完成，跳过")
        return "already"

    status = qoder_campaign_status()
    if not force and status == "claimed":
        log("[Qoder CN] 日志显示今日已领取（hasClaimableCampaign true→false），跳过")
        st[key] = today()
        save_state(st)
        return "already"

    if not force and dt.datetime.now().hour < 10:
        log("[Qoder CN] 未到 10:00 领取窗口，跳过（由每日 10:05 任务处理）")
        return "skip"

    win = find_main_window(img)
    if win is None:
        exe = qoder_exe()
        if not exe:
            log("[Qoder CN] 找不到主窗口且无法定位 exe")
            return "failed"
        log("[Qoder CN] 启动客户端...")
        try:
            launch(exe)
        except Exception as e:
            log(f"[Qoder CN] 启动失败: {e}")
            return "failed"
        if not wait_process(img, 45):
            log("[Qoder CN] 客户端未启动")
            return "failed"
        # 冷启动可能要几十秒，且窗口可能先隐藏到托盘，轮询等待主窗口出现
        end = time.time() + 90
        while time.time() < end:
            win = find_main_window(img)
            if win is not None:
                break
            time.sleep(2)
        if win is None:
            log("[Qoder CN] 90 秒内未找到主窗口")
            return "failed"

    hwnd, rect = win
    restore(hwnd)

    if status == "none" and not force:
        log("[Qoder CN] 今日日志无领取记录（可能未到 10:00 或刚启动），仍尝试点击")

    # 1) 左下角账号/设置入口 -> 打开菜单
    click_ratio(hwnd, 0.0999, 0.9777)
    time.sleep(1.5)
    # 2) 菜单内「权益中心」
    click_ratio(hwnd, 0.0475, 0.6315)
    time.sleep(4.0)  # 等 campaign surface 加载

    # 3) 定位黑色「领取」按钮：先按比例裁一块找深色连通域，找不到则用固定比例兜底
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    cx = int(w * 0.6557)
    cy = int(h * 0.5672)
    crop_x = max(0, cx - 400)
    crop_y = max(0, cy - 150)
    crop_w = min(800, w - crop_x)
    crop_h = min(300, h - crop_y)
    clicked = False
    try:
        ww, hh, buf = capture_window(hwnd)
        crop = bytearray(crop_w * crop_h * 4)
        for yy in range(crop_h):
            src = (crop_y + yy) * ww * 4
            dst = yy * crop_w * 4
            crop[dst:dst + crop_w * 4] = buf[src + crop_x * 4:src + (crop_x + crop_w) * 4]
        blob = find_black_blob_center(crop_w, crop_h, crop, dark=70, min_area=2000)
        if blob:
            bx = crop_x + blob[0]
            by = crop_y + blob[1]
            click_abs(rect.left + bx, rect.top + by)
            clicked = True
            log(f"[Qoder CN] 定位到黑色按钮 @({bx},{by}) 并点击")
    except Exception as e:
        log(f"[Qoder CN] 截图定位失败: {e}")
    if not clicked:
        click_ratio(hwnd, 0.6557, 0.5672)
        log("[Qoder CN] 用固定比例点击领取按钮")

    # 4) 轮询日志确认 true->false
    end = time.time() + 15
    while time.time() < end:
        if qoder_campaign_status() == "claimed":
            log("[Qoder CN] 领取成功（hasClaimableCampaign true→false）")
            st[key] = today()
            save_state(st)
            return "claimed"
        time.sleep(1.5)

    log("[Qoder CN] 15 秒内未确认到领取成功")
    return "failed"


PLATFORMS = {
    "raccoon": do_raccoon,
    "workbuddy": do_workbuddy,
    "trae": do_trae,
    "qoder": do_qoder,
}


def main():
    ap = argparse.ArgumentParser(description="四平台每日自动签到")
    ap.add_argument("--only", help="只跑某个平台: raccoon/workbuddy/trae/qoder")
    ap.add_argument("--force", action="store_true", help="忽略今日已完成状态强制重跑")
    args = ap.parse_args()

    names = [args.only] if args.only else list(PLATFORMS)
    log("=" * 60)
    log(f"开始签到：{', '.join(names)}  force={args.force}")
    results = {}
    for name in names:
        try:
            results[name] = PLATFORMS[name](args.force)
        except Exception as e:
            log(f"[{name}] 异常: {e!r}")
            results[name] = "failed"
    ok = sum(1 for v in results.values() if v in ("claimed", "already", "skip"))
    fail = sum(1 for v in results.values() if v == "failed")
    log(f"本次完成：成功/已签 {ok}，失败 {fail}  " +
        " ".join(f"{k}={v}" for k, v in results.items()))
    log("=" * 60)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"致命异常: {e!r}")
        sys.exit(1)
