# SmartKey 行文本协议（与上位机约定一致，参考 smartkey_protocol.py）
#
#   板子 → 上位机: DOWN,<1..5> / UP,<1..5>
#   上位机 → 板子: PING / STATUS,<hex24> / SLOT,<n>,<名称> / ICON,...
#
# 传输层暂为控制台打印；后续接入 BLE/串口时替换 transport 即可。

# ---------------- 共享常量（设备端与上位机 host_ble.py 共用） ----------------
BLE_NAME = "SmartKey"
BLE_SERVICE_UUID = "F000A001-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_KEY_EVENTS_UUID = "F000A002-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_STATUS_UUID = "F000A003-B5A3-F393-E0A9-E50E24DCCA9E"
BLE_CONTROL_UUID = "F000A004-B5A3-F393-E0A9-E50E24DCCA9E"


class Protocol:
    def __init__(self, ui, transport=None):
        self._ui = ui
        self._transport = transport

    # ---------- 上报 ----------
    def down(self, idx):
        self._send("DOWN,%d" % (idx + 1))

    def up(self, idx):
        self._send("UP,%d" % (idx + 1))

    def _send(self, line):
        if self._transport is not None:
            self._transport.write(line + "\r\n")
        else:
            print(line)

    # ---------- 下发处理 ----------
    def poll(self):
        if self._transport is not None and self._transport.any():
            for line in self._transport.read_lines():
                self.handle(line)

    def handle(self, line):
        line = line.strip()
        if not line:
            return
        if line == "PING":
            self._send("PONG")
        elif line.startswith("STATUS,"):
            try:
                self._ui.set_status(int(line[7:].strip(), 16))
            except ValueError:
                pass
        elif line.startswith("SLOT,"):
            try:
                _, n, name = line.split(",", 2)
                self._ui.set_name(int(n) - 1, name)
            except (ValueError, IndexError):
                pass
        elif line.startswith("ICON"):
            # TODO: 图标同步机制（后续优化）
            pass
