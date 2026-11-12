# 每日全自动签到（Daily Auto Check-in）

一个跑在本机 Windows 上的全自动每日签到脚本，用 `pythonw.exe` 无窗口运行，覆盖四个桌面客户端的每日福利领取：

| 平台 | 签到方式 | 入口 |
|------|----------|------|
| 商汤小浣熊（SenseRaccoon） | 打开客户端即自动签到 | `D:\raccoon\raccoon-ai\商汤小浣熊.exe` |
| WorkBuddy | CDP 驱动点击「立即领取」 | `D:\workbuddy\WorkBuddy.exe`（`--remote-debugging-port=9222`） |
| TRAE CN | CDP 驱动点击「签到」 | `C:\Users\14976\AppData\Local\Programs\Trae CN\Trae CN.exe`（`--remote-debugging-port=9223`） |
| Qoder CN | 前台化 + 像素定位点击「领取」 | 自动解析最新 `D:\Qoder\Qoder CN\.qoder-versions\<版本>\Qoder CN.exe` |

## 目录结构

```
sign in/
├── checkin.py          # 主入口，四平台签到逻辑
├── cdp.mjs             # CDP 辅助（node 原生 WebSocket），供 WorkBuddy / TRAE 使用
├── install_task.ps1    # 注册/清理 Windows 计划任务（需管理员）
├── probe.py            # 调试探针工具（正常签到不依赖）
├── resolve_lnk.ps1     # 解析 .lnk 快捷方式路径（调试用）
├── uia_dump.ps1        # UI Automation 枚举窗口（调试用）
├── state.json          # 每日已签状态（运行期生成，按平台记录日期）
└── logs/
    └── checkin.log     # 运行日志
```

## 环境要求

- Windows 10/11
- Python 3.12（[python.org 下载](https://www.python.org/downloads/)）
- Node.js（供 `cdp.mjs` 使用，用于 WorkBuddy / TRAE 的 CDP 控制）
- 四个客户端已安装（路径见上表）

## 手动运行

```powershell
# 全部平台（无窗口）
pythonw.exe "D:\qiandao\sign in\checkin.py"

# 控制台观察日志
python "D:\qiandao\sign in\checkin.py"

# 只跑某个平台：raccoon / workbuddy / trae / qoder
python "D:\qiandao\sign in\checkin.py" --only qoder

# 忽略「今日已完成」强制重跑
python "D:\qiandao\sign in\checkin.py" --force
```

## 注册每日自动执行（计划任务）

用**管理员 PowerShell** 运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\qiandao\sign in\install_task.ps1"
```

脚本会：

1. 清理旧版本的残留任务 `QiandaoDaemon` / `QiandaoCatchup`（若存在）；
2. 注册单一任务 **`QiandaoAutoCheckin`**，触发器为：**登录时 / 每日 10:05 / 睡眠唤醒后**；
3. 以 `pythonw.exe` 无窗口方式运行 `checkin.py`。

> 说明：Qoder 的每日领取窗口在 **10:00（UTC+8）** 后开放，故每日定时设在 10:05；10:00 前的登录/唤醒触发只会处理其余三个平台，Qoder 会自动跳过。

卸载：

```powershell
Unregister-ScheduledTask -TaskName "QiandaoAutoCheckin" -Confirm:$false
```

## 运行逻辑

- **启动前自检**：程序先判断「今天是否已完整签到成功」（读 `state.json` 的 `last_success` + 当日日志中 `本次完成：… 失败 0` 且四平台齐全的记录），若是则直接退出，不再重复运行。
- **可用网络校验**：不以「已连网」为凭，而是发起真实 HTTP(S) 请求并校验响应（微软连通性探测文本 / baidu / qq 返回 200），确认网络确实可用后才开始签到；否则轮询等待（最多 180 秒）。
- **状态记录**：`state.json` 按平台记录「最近一次成功签到」的日期（`YYYY-MM-DD`），每个平台动手前都会先确认当天是否已签，已签则直接跳过。
- **WorkBuddy**：除 `state.json` 外，还会扫描 `~/.workbuddy/logs/<日期>/*.log` 中的 `daily-checkin` 请求记录，避免「点击成功但按钮未消失」的误判。
- **Qoder CN**：除 `state.json` 外，还会扫描 `%APPDATA%\com.qodercn.app.stable\logs\*\main.log` 中的 `[Campaign]` 日志——`hasClaimableCampaign`（是否还有可领取的福利渠道）与 `claimable`（活动 Surface 打开时是否可领）。启动后会先等客户端上报渠道状态：**无任何可领取渠道则直接退出取消操作**；有渠道才打开权益中心点击「领取」，并以日志翻转为准确认成功。
- **失败即退出**：每个平台独立 try/finally，启动的客户端在结束后清理，不残留进程。

## 关键实现说明

- **窗口查找**（`find_main_window`）：允许隐藏到托盘的窗口，并跳过屏幕外占位窗口。
- **前台化**（`force_foreground`）：临时置顶 + `AttachThreadInput` 绕过 Windows 前台锁，确保坐标点击落在目标窗口上（避免被其他窗口如抖音桌面版遮挡）。
- **Qoder 领取按钮定位**：权益中心弹窗内有两个黑色按钮——「领取」（上）与「查看详情」（下），脚本取「最上方」的深色连通域，即领取按钮。
- **Qoder 渲染校验**（`window_rendered`）：点击前先用 `PrintWindow` 抓一帧确认窗口已渲染出内容（被其他窗口遮挡或冷启动未绘制完成时几乎全黑），未渲染则重新前台化并等待重试，避免坐标点击落到别的窗口上。

## 常见问题

- **提示找不到 pythonw.exe / checkin.py**：检查 `install_task.ps1` 顶部的路径，或确认 Python 3.12 安装位置。
- **Qoder 没反应**：确认运行时间在 10:00 之后；若被其他窗口遮挡，脚本已自动处理前台化。
- **路径含空格**：项目目录名 `sign in` 含空格，`checkin.py` 全程用 `__file__` 相对定位，不受影响；计划任务参数已加引号处理。
