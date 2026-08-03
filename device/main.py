# SmartKey 下位机主程序（ESP32-S3 + LVGL + MicroPython）
# 5 个按键触发槽位动作并上报 DOWN/UP；
# EC12 编码器旋转选择槽位、按下触发选中槽位；
# 顶部状态条颜色由上位机通过 STATUS 指令控制。
import sys
import time

import machine
import lvgl as lv

from smartkey_config import BLE_ENABLE, BTN_PINS, ENC_A, ENC_B, ENC_SW, SLOT_NAMES
from smartkey_display import COL_STATUS_OFF, COL_STATUS_ON, DEFAULT_SYMBOLS, SmartKeyUI
from smartkey_encoder import Encoder
from smartkey_keys import Keys
from smartkey_protocol import Protocol

# ---------------- 看门狗：主循环超过 20s 未喂狗 → 自动重启（防卡死） ----------------
WDT_TIMEOUT_MS = 20_000
wdt = machine.WDT(timeout=WDT_TIMEOUT_MS)

# 降频省电：80MHz 对本 UI 完全够用，电流显著下降（此板供电偏弱）
machine.freq(80_000_000)


def run():
    try:
        from smartkey_ble import SmartKeyBLE

        _HAS_BLE = True
    except Exception:
        _HAS_BLE = False

    # ---------------- 初始化 ----------------
    ui = SmartKeyUI()
    print("RST_CAUSE", machine.reset_cause())
    for i, name in enumerate(SLOT_NAMES):
        ui.set_icon(i, DEFAULT_SYMBOLS[i])
        ui.set_name(i, name)

    enc = Encoder(ENC_A, ENC_B, ENC_SW)
    keys = Keys(BTN_PINS)

    # BLE 传输层：连接状态由主循环轮询更新（不在 IRQ 回调里碰 LVGL）
    ble = None
    if _HAS_BLE and BLE_ENABLE:
        ble = SmartKeyBLE()
        proto = Protocol(ui, transport=ble)
        print("SMARTKEY BLE READY")
    else:
        proto = Protocol(ui)  # 无 BLE 时回退到控制台打印
        print("SMARTKEY NO BLE (console mode)")

    sel = 0
    was_connected = False

    # ---------------- 主循环 ----------------
    _last_ms = time.ticks_ms()
    while True:
        wdt.feed()  # 喂狗：任何一帧卡死超过 20s 都会自动重启

        now = time.ticks_ms()
        dt = time.ticks_diff(now, _last_ms)
        _last_ms = now

        # 连接状态轮询（替代 IRQ 回调里的 UI 操作）
        if ble is not None:
            is_conn = ble.connected()
            if is_conn != was_connected:
                ui.set_status(COL_STATUS_ON if is_conn else COL_STATUS_OFF)
                was_connected = is_conn

        # 输入轮询（软件方式，不使用 machine.Timer，避免与 BLE 冲突）
        enc.poll()
        keys.poll(now)

        # 5 个按键：按下高亮并上报 DOWN，松开恢复并上报 UP
        for idx, ev in keys.get_events():
            if ev == "down":
                ui.set_pressed(idx, True)
                proto.down(idx)
            else:
                ui.set_pressed(idx, False)
                proto.up(idx)

        # 编码器旋转：移动选中槽位
        d = enc.read_delta()
        if d:
            sel = (sel + (1 if d > 0 else -1)) % 5
            ui.set_selected(sel)

        # 编码器按键：触发选中的槽位
        if enc.sw_clicked():
            ui.set_pressed(sel, True)
            proto.down(sel)
            time.sleep_ms(80)
            ui.set_pressed(sel, False)
            proto.up(sel)

        # 上位机指令
        proto.poll()

        # LVGL 手动驱动（替代 task_handler 的硬件定时器）
        lv.tick_inc(dt)
        lv.task_handler()

        time.sleep_ms(2)


# 顶层异常保护：任何未捕获异常 → 打印回溯并立即重启，
# 避免脚本退出导致屏幕冻结在最后一帧（配合看门狗双保险）
try:
    run()
except Exception as e:
    print("FATAL: main loop exception, rebooting...")
    sys.print_exception(e)
    time.sleep_ms(1000)
    machine.reset()
