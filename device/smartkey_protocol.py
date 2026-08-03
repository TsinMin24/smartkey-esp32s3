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
        elif line.startswith("ICON,"):
            self._handle_icon(line)

    # ---------------- ICON 图标同步（2 色掩码 + CRC16） ----------------
    @staticmethod
    def _crc16(data):
        """CRC16-CCITT-FALSE：与上位机 HostCommand.crc16 完全一致"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    def _handle_icon(self, line):
        """格式: ICON,<slot>,<w>,<h>,<fg565hex>,<bg565hex>,<crc16hex>,<hex掩码>"""
        try:
            parts = line.split(",")
            if len(parts) != 8:
                return
            _, slot_s, w_s, h_s, fg_s, bg_s, crc_s, mask_hex = parts
            slot = int(slot_s)
            w = int(w_s)
            h = int(h_s)
            if not (1 <= slot <= 5 and 1 <= w <= 64 and 1 <= h <= 64 and w * h <= 2048):
                return
            mask = bytes.fromhex(mask_hex)
            if len(mask) != (w * h + 7) // 8:
                self._send("ERR_CRC")
                return
            if self._crc16(mask) != (int(crc_s, 16) & 0xFFFF):
                self._send("ERR_CRC")
                return
            fg = int(fg_s, 16) & 0xFFFF
            bg = int(bg_s, 16) & 0xFFFF
            self._ui.set_icon_bitmap(slot - 1, w, h, fg, bg, mask)
            self._send("OK")
        except Exception:
            pass
