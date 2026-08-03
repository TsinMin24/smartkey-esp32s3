# SmartKey 5 按键模块：内部上拉 + 软件消抖
from machine import Pin


class Keys:
    def __init__(self, pins, debounce_ms=15):
        self._pins = [Pin(p, Pin.IN, Pin.PULL_UP) for p in pins]
        self._stable = [1] * len(pins)
        self._last = [1] * len(pins)
        self._t = [0] * len(pins)
        self._debounce_ms = debounce_ms
        self._events = []

    def poll(self, now_ms):
        for i, p in enumerate(self._pins):
            v = p.value()
            if v != self._stable[i]:
                self._stable[i] = v
                self._t[i] = now_ms
            elif now_ms - self._t[i] >= self._debounce_ms and v != self._last[i]:
                self._last[i] = v
                self._events.append((i, "down" if v == 0 else "up"))

    def get_events(self):
        ev = self._events
        self._events = []
        return ev
