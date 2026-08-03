# SmartKey 显示模块：LVGL 界面（状态条 + 5 个按键槽位 + BLE 图标）
#
# 重要：本固件的 lvgl 绑定里，canvas/image 嵌套在容器内时渲染坐标会错乱
# （父级偏移被重复计算，实测 20x20 会画偏 16px、部分槽位干脆不画）。
# 因此所有图标 canvas 一律作为【屏幕级子对象】按绝对坐标定位，
# 名字条也提到屏幕级并创建在 canvas 之后，保证 z 序正确。
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
SLOT_GAP = 54
BORDER = 2
NAME_BAR_H = 16

# 图标显示区：槽位内容区内、名字条上方（避免与名字重叠）
ICON_AREA_X = SLOT_X + BORDER
ICON_AREA_Y0 = SLOT_Y0 + BORDER
ICON_AREA_W = SLOT_W - BORDER * 2
ICON_AREA_H = SLOT_H - BORDER * 2 - NAME_BAR_H

# 默认图标尺寸（与上位机 IconEncoder.size 保持一致）
DEFAULT_ICON_W = 20
DEFAULT_ICON_H = 20

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


# 默认槽位图标（BLE 位图图标到达前显示）
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

    # ---------------- 显示初始化 ----------------
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
        # 背光：PWM 限流，约 30% 亮度（低电平点亮，duty 反向）
        self._backlight = machine.PWM(
            machine.Pin(PIN_BL, machine.Pin.OUT), freq=38_000
        )
        self.set_backlight(BRIGHTNESS)

    def set_backlight(self, brightness):
        """brightness: 0.0 ~ 1.0"""
        self._backlight.duty_u16(int(65535 * (1.0 - brightness)))

    # ---------------- 构建界面 ----------------
    def _build(self):
        scr = lv.screen_active()
        scr.set_style_bg_color(lv.color_hex(COL_BG), 0)
        scr.remove_flag(lv.obj.FLAG.SCROLLABLE)
        scr.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

        # 顶部状态条
        self._status = lv.obj(scr)
        self._status.set_pos(0, 0)
        self._status.set_size(W, 4)
        self._status.set_style_bg_color(lv.color_hex(COL_STATUS_OFF), 0)
        self._status.set_style_border_width(0, 0)
        self._status.set_style_radius(0, 0)

        self._slots = []
        self._icons = []        # 默认符号 label（槽位子对象，canvas 隐藏时可见）
        self._caps = []         # 名字 caption 条（屏幕级，创建在 canvas 之后 → 最上层）
        self._names = []        # 名字 label（caption 子对象）
        self._icon_canvases = [None] * 5
        self._icon_bufs = [None] * 5
        self._icon_dims = [None] * 5

        for i in range(5):
            slot_y = SLOT_Y0 + i * SLOT_GAP

            # 槽位（屏幕级）
            s = lv.obj(scr)
            s.remove_flag(lv.obj.FLAG.SCROLLABLE)
            s.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
            s.set_pos(SLOT_X, slot_y)
            s.set_size(SLOT_W, SLOT_H)
            s.set_style_bg_color(lv.color_hex(COL_SLOT), 0)
            s.set_style_border_width(BORDER, 0)
            s.set_style_border_color(lv.color_hex(COL_BORDER_IDLE), 0)
            s.set_style_radius(6, 0)
            s.set_style_pad_all(0, 0)
            self._slots.append(s)

            # 默认符号 label（槽位内）
            ic = lv.label(s)
            ic.set_text(" ")
            ic.set_style_text_color(lv.color_hex(COL_ICON), 0)
            ic.set_style_text_font(lv.font_montserrat_14, 0)
            ic.align(lv.ALIGN.TOP_MID, 0, 5)
            self._icons.append(ic)

            # 图标 canvas（屏幕级！绕开嵌套渲染 bug），默认隐藏
            buf = bytearray(DEFAULT_ICON_W * DEFAULT_ICON_H * 2)
            cv = lv.canvas(scr)
            cv.set_buffer(buf, DEFAULT_ICON_W, DEFAULT_ICON_H, lv.COLOR_FORMAT.RGB565)
            cv.set_size(DEFAULT_ICON_W, DEFAULT_ICON_H)
            cv.set_pos(*self._icon_pos(i, DEFAULT_ICON_W, DEFAULT_ICON_H))
            cv.remove_flag(lv.obj.FLAG.SCROLLABLE)
            cv.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
            cv.add_flag(lv.obj.FLAG.HIDDEN)
            self._icon_canvases[i] = cv
            self._icon_bufs[i] = buf
            self._icon_dims[i] = (DEFAULT_ICON_W, DEFAULT_ICON_H)

            # 名字 caption 条（屏幕级，canvas 之后创建 → 永远盖在图标下缘）
            cap = lv.obj(scr)
            cap.remove_flag(lv.obj.FLAG.SCROLLABLE)
            cap.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
            cap.set_size(SLOT_W, NAME_BAR_H)
            cap.set_pos(SLOT_X, slot_y + SLOT_H - NAME_BAR_H - 1)
            cap.set_style_bg_color(lv.color_hex(COL_SLOT), 0)
            cap.set_style_border_width(0, 0)
            cap.set_style_radius(0, 0)
            nm = lv.label(cap)
            nm.set_pos(0, 0)
            nm.set_size(SLOT_W, NAME_BAR_H)
            nm.set_style_text_color(lv.color_hex(COL_NAME), 0)
            nm.set_style_text_font(lv.font_montserrat_12, 0)
            nm.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
            self._caps.append(cap)
            self._names.append(nm)

        self.set_selected(0)

    @staticmethod
    def _icon_pos(i, w, h):
        """图标显示区内的绝对坐标（屏幕级 canvas 用；不重叠名字条）"""
        x = ICON_AREA_X + (ICON_AREA_W - w) // 2
        y = ICON_AREA_Y0 + i * SLOT_GAP + (ICON_AREA_H - h) // 2
        return x, y

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
        """默认符号（仅当该槽没有位图图标时显示）"""
        cv = self._icon_canvases[i]
        if cv is not None and not cv.has_flag(lv.obj.FLAG.HIDDEN):
            return  # 已有 BLE 位图图标，忽略默认符号
        self._icons[i].set_text(symbol)

    def set_name(self, i, name):
        self._names[i].set_text(name)

    def set_icon_bitmap(self, i, w, h, fg565, bg565, mask):
        """BLE 同步图标：2 色掩码 → RGB565 缓冲 → 屏幕级 canvas 渲染"""
        if not (0 <= i < 5):
            return
        cv = self._icon_canvases[i]
        if cv is None or self._icon_dims[i] != (w, h):
            # 尺寸与预建不同才重建（屏幕级，避免嵌套渲染 bug）
            if cv is not None:
                cv.delete()
            buf = bytearray(w * h * 2)
            cv = lv.canvas(lv.screen_active())
            cv.set_buffer(buf, w, h, lv.COLOR_FORMAT.RGB565)
            cv.set_size(w, h)
            cv.set_pos(*self._icon_pos(i, w, h))
            cv.remove_flag(lv.obj.FLAG.SCROLLABLE)
            cv.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
            self._icon_canvases[i] = cv
            self._icon_bufs[i] = buf
            self._icon_dims[i] = (w, h)
            # 重建后确保名字条仍在最上层
            self._caps[i].move_foreground()

        buf = self._icon_bufs[i]
        pixels = w * h
        for p in range(pixels):
            c = fg565 if mask[p >> 3] & (0x80 >> (p & 7)) else bg565
            buf[p * 2] = c & 0xFF
            buf[p * 2 + 1] = c >> 8
        cv.remove_flag(lv.obj.FLAG.HIDDEN)  # 显示位图图标
        cv.invalidate()
        self._icons[i].set_text(" ")  # 隐藏默认符号
