# SmartKey EC12 旋转编码器模块：主循环软件轮询 + 正交查表解码
#
# 注意：不能使用 machine.Timer（与 BLE 同用会触发硬复位循环），
# 由 main.py 主循环每 ~2ms 调用 poll()。
from machine import Pin


_TABLE = {
    0: {1: 1, 2: -1},
    1: {3: 1, 0: -1},
    2: {0: 1, 3: -1},
    3: {2: 1, 1: -1},
}


class Encoder:
    def __init__(self, a_pin, b_pin, sw_pin=None):
        self._a = Pin(a_pin, Pin.IN, Pin.PULL_UP)
        self._b = Pin(b_pin, Pin.IN, Pin.PULL_UP)
        self._sw = None if sw_pin is None else Pin(sw_pin, Pin.IN, Pin.PULL_UP)
        self._prev = (self._a.value() << 1) | self._b.value()
        self._delta = 0
        self._sw_prev = 1
        self._sw_press = False
        self._sw_deb = 0

    def poll(self):
        """主循环中周期性调用（建议 2~5ms）"""
        ab = (self._a.value() << 1) | self._b.value()
        if ab != self._prev:
            d = _TABLE.get(self._prev, {}).get(ab, 0)
            self._delta += d
            self._prev = ab

        if self._sw is not None:
            v = self._sw.value()
            if self._sw_deb:
                self._sw_deb -= 1
            elif self._sw_prev == 1 and v == 0:
                self._sw_press = True
                self._sw_deb = 20  # 20 次轮询消抖
            self._sw_prev = v

    def read_delta(self):
        """返回自上次调用以来的正交增量（一格 = 4）"""
        d = self._delta
        self._delta = 0
        return d

    def sw_clicked(self):
        if self._sw_press:
            self._sw_press = False
            return True
        return False
