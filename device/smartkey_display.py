# SmartKey 显示模块：LVGL 界面（状态条 + 5 个按键槽位）
import time

import lcd_bus
import lvgl as lv
import machine
import st7789

from smartkey_config import (
    BRIGHTNESS,
    W, H, OFFSET_X, OFFSET_Y,
    PIN_SCK, PIN_MOSI, PIN_DC, PIN_CS, PIN_RST, PIN_BL,
)

# ---------------- 布局（76x284，与原始 smartkey 一致） ----------------
SLOT_W = 44
SLOT_H = 44
SLOT_X = 10
SLOT_Y0 = 14
SLOT_GAP = 54  # 5*44 + 6*10 = 280，加状态条 4px 正好 284

# ---------------- 颜色 ----------------
COL_BG = 0x101418
COL_SLOT = 0x2A2A2A
COL_SLOT_PRESS = 0x3D3D3D
COL_BORDER_IDLE = 0x333333
COL_SELECT = 0xFFA500
COL_ICON = 0xDDDDDD
COL_NAME = 0x999999
COL_STATUS_OFF = 0xFFA500  # 断开
COL_STATUS_ON = 0x00FF00   # 连接


def _symbol(name, fallback):
    """安全取 LVGL 内置符号，取不到用文字兜底"""
    try:
        return getattr(lv.SYMBOL, name)
    except AttributeError:
        return fallback


# 默认槽位图标（后续图标同步机制会替换）
DEFAULT_SYMBOLS = (
    _symbol("COPY", "C"),
    _symbol("PASTE", "P"),
    _symbol("IMAGE", "S"),
    _symbol("SETTINGS", "G"),
    _symbol("WIFI", "U"),
)


class SmartKeyUI:
    def __init__(self):
        self._init_display()
        self._build()

    def _init_display(self):
        spi_bus = machine.SPI.Bus(host=1, sck=PIN_SCK, mosi=PIN_MOSI, miso=-1)
        display_bus = lcd_bus.SPIBus(
            spi_bus=spi_bus, freq=20_000_000, dc=PIN_DC, cs=PIN_CS,
        )
        # 手动控制复位脚：驱动框架不会自动释放，必须自己来
        rst = machine.Pin(PIN_RST, machine.Pin.OUT)
        rst.value(0)
        time.sleep_ms(100)
        rst.value(1)
        time.sleep_ms(120)

        self._display = st7789.ST7789(
            data_bus=display_bus,
            display_width=W,
            display_height=H,
            reset_pin=None,
            backlight_pin=PIN_BL,
            backlight_on_state=st7789.STATE_LOW,
            offset_x=OFFSET_X,
            offset_y=OFFSET_Y,
            color_space=lv.COLOR_FORMAT.RGB565,
            rgb565_byte_swap=True,
        )
        self._display.set_power(True)
        self._display.init()
        # 背光：PWM 限流，约 45% 亮度（低电平点亮，duty 反向）。
        # 供电紧张时全亮背光容易触发掉电复位。
        self._backlight = machine.PWM(
            machine.Pin(PIN_BL, machine.Pin.OUT), freq=38_000
        )
        self.set_backlight(BRIGHTNESS)

    def set_backlight(self, brightness):
        """brightness: 0.0 ~ 1.0"""
        self._backlight.duty_u16(int(65535 * (1.0 - brightness)))

    def _build(self):
        scr = lv.screen_active()
        scr.set_style_bg_color(lv.color_hex(COL_BG), 0)

        # 顶部状态条
        self._status = lv.obj(scr)
        self._status.set_pos(0, 0)
        self._status.set_size(W, 4)
        self._status.set_style_bg_color(lv.color_hex(COL_STATUS_OFF), 0)
        self._status.set_style_border_width(0, 0)
        self._status.set_style_radius(0, 0)

        # 5 个槽位
        self._slots = []
        self._icons = []
        self._names = []
        self._icon_canvases = [None] * 5
        self._icon_bufs = [None] * 5
        self._icon_dims = [None] * 5
        for i in range(5):
            s = lv.obj(scr)
            s.set_pos(SLOT_X, SLOT_Y0 + i * SLOT_GAP)
            s.set_size(SLOT_W, SLOT_H)
            s.set_style_bg_color(lv.color_hex(COL_SLOT), 0)
            s.set_style_border_width(2, 0)
            s.set_style_border_color(lv.color_hex(COL_BORDER_IDLE), 0)
            s.set_style_radius(6, 0)
            s.set_style_pad_all(0, 0)
            self._slots.append(s)

            ic = lv.label(s)
            ic.set_text(" ")
            ic.set_style_text_color(lv.color_hex(COL_ICON), 0)
            ic.set_style_text_font(lv.font_montserrat_14, 0)
            ic.align(lv.ALIGN.TOP_MID, 0, 5)
            self._icons.append(ic)

            nm = lv.label(s)
            nm.set_text("")
            nm.set_style_text_color(lv.color_hex(COL_NAME), 0)
            nm.set_style_text_font(lv.font_montserrat_12, 0)
            # 名字做成底部 caption 条：不透明背景，压在 40x40 图标下缘
            nm.set_style_bg_color(lv.color_hex(COL_SLOT), 0)
            nm.set_style_bg_opa(lv.OPA.COVER, 0)
            nm.set_style_pad_top(1, 0)
            nm.set_style_pad_bottom(1, 0)
            nm.align(lv.ALIGN.BOTTOM_MID, 0, -3)
            self._names.append(nm)

        self.set_selected(0)

    # ---------------- 界面更新 ----------------
    def set_status(self, color24):
        """状态条颜色（0xFFA500 断开 / 0x00FF00 连接）"""
        self._status.set_style_bg_color(lv.color_hex(color24), 0)

    def set_selected(self, i):
        """编码器选中的槽位用橙色描边"""
        for idx, s in enumerate(self._slots):
            color = COL_SELECT if idx == i else COL_BORDER_IDLE
            s.set_style_border_color(lv.color_hex(color), 0)

    def set_pressed(self, i, pressed):
        """按键按下时槽位压暗"""
        color = COL_SLOT_PRESS if pressed else COL_SLOT
        self._slots[i].set_style_bg_color(lv.color_hex(color), 0)

    def set_icon(self, i, symbol):
        self._icons[i].set_text(symbol)

    def set_name(self, i, name):
        self._names[i].set_text(name)

    def set_icon_bitmap(self, i, w, h, fg565, bg565, mask):
        """BLE 同步图标：2 色掩码（1bit/像素，MSB 在前）→ RGB565 buffer → canvas 渲染"""
        if not (0 <= i < 5):
            return
        s = self._slots[i]
        cv = self._icon_canvases[i]
        if cv is None or self._icon_dims[i] != (w, h):
            if cv is not None:
                cv.delete()
            buf = bytearray(w * h * 2)
            cv = lv.canvas(s)
            cv.set_buffer(buf, w, h, lv.COLOR_FORMAT.RGB565)
            cv.set_pos(SLOT_X + (SLOT_W - w) // 2, SLOT_Y0 + i * SLOT_GAP + (SLOT_H - h) // 2)
            cv.set_style_border_width(0, 0)
            cv.set_style_radius(0, 0)
            cv.set_style_pad_all(0, 0)
            self._icon_canvases[i] = cv
            self._icon_bufs[i] = buf
            self._icon_dims[i] = (w, h)
            self._icons[i].set_text(" ")  # 有真实图标后隐藏默认符号
            self._names[i].move_foreground()  # 名字 caption 条压在图标上
        # 直接写 RGB565（小端 = LVGL 原生顺序），比逐像素 set_px 快且避开绑定差异
        buf = self._icon_bufs[i]
        pixels = w * h
        for p in range(pixels):
            c = fg565 if mask[p >> 3] & (0x80 >> (p & 7)) else bg565
            buf[p * 2] = c & 0xFF
            buf[p * 2 + 1] = c >> 8
        cv.invalidate()
