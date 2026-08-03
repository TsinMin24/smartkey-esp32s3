#!/usr/bin/env python3
"""SmartKey 上位机 BLE 客户端（macOS / Linux，依赖 bleak）

用法:
    pip install bleak
    python host_ble.py                     # 扫描并连接 SmartKey，实时打印按键事件
    python host_ble.py --status 00FF00     # 连接后把状态条设为绿色
    python host_ble.py --ping              # 只发 PING 测试链路

特性:
    - 按设备名扫描（SmartKey）
    - 订阅 KEY_EVENTS 通知，实时打印 DOWN/UP
    - 通过 CONTROL 特征下发 STATUS/SLOT/PING 指令
    - 意外断开自动重连
"""
import argparse
import asyncio

from bleak import BleakClient, BleakScanner

from smartkey_protocol import (
    BLE_CONTROL_UUID,
    BLE_KEY_EVENTS_UUID,
    BLE_NAME,
    BLE_SERVICE_UUID,
)


def on_key_event(_client, data: bytearray):
    print("<<", data.decode("utf-8", "ignore").strip())


async def find_device(name: str, timeout: float = 12.0):
    print(f"扫描 {name} ...")
    device = None

    def _match(d, adv):
        nonlocal device
        n = d.name or ""
        an = adv.local_name if adv else None
        uuids = [u.lower() for u in (adv.service_uuids if adv else [])]
        # macOS 上部分设备 local_name 上报为 None，需按服务 UUID 兜底匹配
        if (
            name in n
            or (an and name in an)
            or BLE_SERVICE_UUID.lower() in uuids
        ):
            device = d

    scanner = BleakScanner(detection_callback=_match)
    await scanner.start()
    try:
        await asyncio.sleep(timeout)
    finally:
        await scanner.stop()
    return device


async def run(name: str, status_hex: str | None, ping: bool):
    while True:
        device = await find_device(name)
        if device is None:
            print("未找到设备，5 秒后重试 ...")
            await asyncio.sleep(5)
            continue
        print(f"连接 {device.name} ({device.address}) ...")
        try:
            async with BleakClient(device, timeout=15) as client:
                print("已连接，Ctrl-C 退出")
                await client.start_notify(BLE_KEY_EVENTS_UUID, on_key_event)
                if ping:
                    await client.write_gatt_char(BLE_CONTROL_UUID, b"PING")
                if status_hex:
                    await client.write_gatt_char(
                        BLE_CONTROL_UUID, f"STATUS,{status_hex}".encode()
                    )
                while True:
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print("连接中断:", exc)
            await asyncio.sleep(3)
            continue


def main():
    ap = argparse.ArgumentParser(description="SmartKey BLE 上位机")
    ap.add_argument("--name", default=BLE_NAME)
    ap.add_argument("--status", default=None, help="状态条颜色，如 00FF00")
    ap.add_argument("--ping", action="store_true")
    args = ap.parse_args()
    try:
        asyncio.run(run(args.name, args.status, args.ping))
    except KeyboardInterrupt:
        print("\n退出")


if __name__ == "__main__":
    main()
