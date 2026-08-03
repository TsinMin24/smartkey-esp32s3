# SmartKey BLE 传输层 v2 —— 基于 ESP32 原生 NimBLE + 自定义 GATT 服务
#
# 服务与特征（自定义 UUID，专为 SmartKey 设计，上位机 host_ble.py 同款）：
#   SMARTKEY_SERVICE  F000A001-B5A3-F393-E0A9-E50E24DCCA9E
#   KEY_EVENTS        F000A002-... （notify）板子→电脑："DOWN,n" / "UP,n"
#   DEVICE_STATUS     F000A003-... （read/notify）板子状态
#   CONTROL           F000A004-... （write）电脑→板子：STATUS/SLOT/PING/ICON
#
# ESP32 原生特性利用：
#   - 连接建立后立即停止广播（省电、降低掉电复位概率）
#   - 断开后自动恢复广播，等待重连
#   - 广播间隔可配（smartkey_config.BLE_ADV_INTERVAL_MS）
import bluetooth
import struct

from smartkey_config import (
    BLE_ADV_INTERVAL_MS,
    BLE_ADVERTISE,
)
from smartkey_protocol import (
    BLE_CONTROL_UUID,
    BLE_KEY_EVENTS_UUID,
    BLE_NAME,
    BLE_SERVICE_UUID,
    BLE_STATUS_UUID,
)

_IRQ_CENTRAL_CONNECT = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE = 3

_FLAG_READ = 0x0002
_FLAG_WRITE_NO_RESPONSE = 0x0004
_FLAG_WRITE = 0x0008
_FLAG_NOTIFY = 0x0010

_SVC = bluetooth.UUID(BLE_SERVICE_UUID)
_KEY_CHAR = (bluetooth.UUID(BLE_KEY_EVENTS_UUID), _FLAG_READ | _FLAG_NOTIFY)
_STATUS_CHAR = (bluetooth.UUID(BLE_STATUS_UUID), _FLAG_READ | _FLAG_NOTIFY)
_CTRL_CHAR = (
    bluetooth.UUID(BLE_CONTROL_UUID),
    _FLAG_WRITE | _FLAG_WRITE_NO_RESPONSE,
)
_SERVICE = (_SVC, (_KEY_CHAR, _STATUS_CHAR, _CTRL_CHAR))


class SmartKeyBLE:
    def __init__(self, on_conn=None, name=BLE_NAME):
        self._on_conn = on_conn
        self._conn_handle = None
        self._in_lines = []
        self._line_buf = bytearray()  # 跨包行缓冲（ICON 等长消息可能分片到达）
        self._name = name.encode()
        self._adv_interval_us = BLE_ADV_INTERVAL_MS * 1000

        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self._irq)
        (
            (self._key_handle, self._status_handle, self._ctrl_handle),
        ) = self._ble.gatts_register_services((_SERVICE,))
        self._ble.gatts_set_buffer(self._ctrl_handle, 512, True)
        self._ble.gatts_write(self._status_handle, b"READY")
        # 预构建广播数据：IRQ 里直接复用，避免中断回调中分配内存
        self._adv_data, self._adv_resp = self._build_adv()
        if BLE_ADVERTISE:
            self._advertise()

    def _build_adv(self):
        adv = bytearray()
        adv += struct.pack("BB", 3, 0x01) + b"\x06"  # flags: LE General Discoverable
        adv += struct.pack("BB", len(self._name) + 1, 0x09) + self._name
        sr = struct.pack("BB", 17, 0x07) + bytes(_SVC)  # 128 位服务 UUID
        return bytes(adv), bytes(sr)

    def _advertise(self):
        self._ble.gap_advertise(
            self._adv_interval_us,
            adv_data=self._adv_data,
            resp_data=self._adv_resp,
            connectable=True,
        )

    def _stop_advertise(self):
        self._ble.gap_advertise(None)

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self._conn_handle = data[0]
            self._stop_advertise()  # 已连接，停止广播省电
            if self._on_conn:
                self._on_conn(True)
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._conn_handle = None
            if self._on_conn:
                self._on_conn(False)
            self._advertise()  # 恢复广播，等待重连
        elif event == _IRQ_GATTS_WRITE:
            _, value_handle = data
            if value_handle == self._ctrl_handle:
                value = self._ble.gatts_read(self._ctrl_handle)
                # 保护：异常超长写入直接丢弃（防止缓冲被撑爆）
                if len(value) > 512:
                    return
                # 跨包拼行：一条完整命令可能被拆成多次 GATT 写入
                self._line_buf += value
                if len(self._line_buf) > 1024:  # 防异常堆积，只保留尾部
                    self._line_buf = self._line_buf[-512:]
                lines = []
                while True:
                    nl = self._line_buf.find(b"\n")
                    if nl < 0:
                        break
                    line = self._line_buf[:nl]
                    self._line_buf = self._line_buf[nl + 1:]
                    line = line.strip()
                    if line:
                        lines.append(line.decode("utf-8", "ignore"))
                if lines:
                    # 保护：消费端跟不上的时候丢弃最旧数据，避免内存无限增长
                    if len(self._in_lines) + len(lines) > 32:
                        drop = len(self._in_lines) + len(lines) - 32
                        self._in_lines = self._in_lines[drop:]
                    self._in_lines.extend(lines)

    # ---------- transport 接口（smartkey_protocol 约定） ----------
    def write(self, line):
        """向 KEY_EVENTS 特征发送通知（按键事件）"""
        if self._conn_handle is not None:
            try:
                # 注意：此固件的 gatts_write 不接受关键字参数，
                # send_update 必须按位置传 True（写 send_update=True 会抛 TypeError）
                self._ble.gatts_write(self._key_handle, line.encode(), True)
            except Exception:
                # 连接刚断开等瞬时错误：丢弃该事件，不让主程序崩溃
                print("BLE notify dropped:", line)
        else:
            print(line)  # 未连接时打印到控制台，便于调试

    def any(self):
        return bool(self._in_lines)

    def read_lines(self):
        lines = self._in_lines
        self._in_lines = []
        return lines

    def connected(self):
        return self._conn_handle is not None

    def set_status(self, text):
        try:
            self._ble.gatts_write(self._status_handle, text.encode())
        except Exception:
            pass
