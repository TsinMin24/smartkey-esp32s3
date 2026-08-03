# 固件说明

设备端固件由 [lvgl_micropython](https://github.com/lvgl/lvgl_micropython)
源码编译，配置：

- MicroPython 1.27（78ff170de）+ LVGL 9.4
- 目标：`ESP32_GENERIC_S3` / `SPIRAM_OCT` / 16MB Flash
- 内置 `lcd_bus` + `st7789` 驱动

编译命令：

```bash
python3 make.py esp32 BOARD=ESP32_GENERIC_S3 BOARD_VARIANT=SPIRAM_OCT \
  DISPLAY=st7789 --flash-size=16
```

产物：`build/lvgl_micropy_ESP32_GENERIC_S3-SPIRAM_OCT-16.bin`

烧录（BOOT+RESET 进下载模式）：

```bash
esptool.py --chip esp32s3 -p /dev/cu.usbserial-XXXX -b 460800 \
  --before default-reset --after hard-reset write-flash \
  --flash-mode dio --flash-size 16MB --flash-freq 80m --erase-all \
  0x0 lvgl_micropy_ESP32_GENERIC_S3-SPIRAM_OCT-16.bin
```
