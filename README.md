# SmartKey ESP32-S3 — BLE 无线按键板（LVGL + MicroPython）

基于 [TsinMin24/smartkey](https://github.com/TsinMin24/smartkey) 的架构，
把硬件从 nRF52840 换成 **ESP32-S3 N16R8**，下位机改用
**MicroPython + LVGL 9**，上位机沿用 macOS Swift 版并改为连接
ESP32 原生 NimBLE 自定义 GATT 服务。

```
ESP32-S3 (SmartKey)                  电脑端 Swift 上位机 (macOS)
┌──────────────────┐   BLE GATT   ┌──────────────────────────┐
│ 5 按键 + EC12      │ ──────────► │ 收到 "DOWN,3" / "UP,3"    │
│ 76×284 ST7789 屏  │             │ 执行快捷键/启动 App 动作   │
│ LVGL 界面          │ ◄────────── │ STATUS/SLOT/ICON 指令     │
└──────────────────┘              └──────────────────────────┘
```

## 硬件

- ESP32-S3 N16R8（16MB Flash / 8MB Octal PSRAM）
- 2.25" 76×284 ST7789P3 条形屏（SPI：SCLK=12, MOSI=11, DC=10, CS=9,
  RST=8, BL=7，**低电平点亮**）
- 5 个按键 GPIO13-17（内部上拉，按下读 0）
- EC12 旋转编码器：公共脚→GND，A→GPIO2，B→GPIO4，按键→GPIO5

## 目录结构

```
├── device/            # ESP32 下位机（MicroPython + LVGL）
│   ├── main.py            # 主程序：按键/编码器 → 界面 + BLE 上报
│   ├── smartkey_config.py # 引脚与槽位配置
│   ├── smartkey_display.py# LVGL 界面（状态条 + 5 槽位）
│   ├── smartkey_encoder.py# EC12 解码（软件轮询）
│   ├── smartkey_keys.py   # 5 按键消抖
│   ├── smartkey_protocol.py # 行文本协议 + BLE UUID 常量
│   └── smartkey_ble.py    # ESP32 原生 NimBLE 传输层（自定义 GATT）
├── host/
│   ├── host_ble.py        # Python CLI 上位机（bleak，Mac/Linux）
│   └── SmartKeyHost/      # macOS Swift/SwiftUI 上位机源码
└── firmware/              # 固件说明
```

## 固件

设备端固件是 lvgl_micropython 编译的：
MicroPython 1.27 + LVGL 9.4（`ESP32_GENERIC_S3 / SPIRAM_OCT / 16MB`，
内置 `lcd_bus` + `st7789` 驱动）。构建/烧录方式见 `firmware/README.md`。

## BLE 协议（自定义 GATT，ESP32 原生 NimBLE）

```
SMARTKEY_SERVICE  F000A001-B5A3-F393-E0A9-E50E24DCCA9E
KEY_EVENTS        F000A002-...  notify  板子→电脑  DOWN,1..5 / UP,1..5
DEVICE_STATUS     F000A003-...  read    板子状态（READY）
CONTROL           F000A004-...  write   电脑→板子  PING/STATUS/SLOT/ICON
```

连接后板子自动停止广播省电，断开后恢复广播等待重连。

图标同步走 `ICON,<slot>,<w>,<h>,<fg565hex>,<bg565hex>,<crc16hex>,<hex掩码>`
（2 色位掩码 + CRC16-CCITT 校验，当前 40×40，单包约 430B 一次传完）。

## 部署

### 下位机

1. 刷入固件（见 `firmware/README.md`）
2. 上传 `device/*.py` 到板子根目录
3. 上电后板子自动运行，开始广播 `SmartKey`

### macOS 上位机

```bash
cd host/SmartKeyHost
bash build_app.sh        # 生成 SmartKeyHost.app
open .build/release/SmartKeyHost.app
```

### Python CLI 上位机

```bash
pip install bleak
python host/host_ble.py                 # 自动连接，打印按键事件
python host/host_ble.py --status 00FF00 # 状态条变绿
```

## 已知要点

- ST7789 驱动框架不会自动释放屏幕 RST 脚、低电平背光有误判，
  `smartkey_display.py` 已手动处理。
- **颜色修复（76×284 ST7789P3 实测）**：该面板按大端读 RGB565，且不兼容
  驱动默认完整 init 序列（INVON 反相 + 寄存器导致红蓝互换）。当前配置：
  `color_space=RGB565_SWAPPED`（LVGL 直接产出大端字节）、
  `color_byte_order=RGB`（不设 BGR），并在 `init()` 后软复位走最小初始化
  （SWRESET/SLPOUT/MADCTL=0/COLMOD=0x55/DISPON）。
- **此固件的 `gatts_write` 不接受关键字参数**：必须写
  `gatts_write(handle, data, True)`（`send_update=True` 会抛 TypeError，
  曾导致按键时主程序崩溃、上位机收不到事件）。
- 主循环软件轮询 + 手动 `lv.tick_inc()/lv.task_handler()`，不使用
  `machine.Timer`，与 BLE 共存稳定。
- 看门狗 20 秒 + 主循环异常保护：任何卡死/异常都会自动重启自愈。
- 内置字体无中文字形，槽位名暂用英文；图标已支持 BLE 同步
  （40×40 2 色掩码，上位机点"推送图标"即到屏）。
- 供电偏弱时 BLE 射频可能导致掉电复位，建议使用带供电的 USB Hub。
