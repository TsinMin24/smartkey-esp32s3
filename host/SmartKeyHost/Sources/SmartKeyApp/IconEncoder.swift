//
//  IconEncoder.swift
//  提取 macOS App 图标 → 16×16 RGB565 全色位图（2字节/像素）
//
import AppKit
import CoreGraphics

enum IconEncoder {
    static let size = 16

    /// 提取 App 图标 → RGB565 原始像素（16×16×2 = 512B）
    static func encode(appPath: String) -> Data? {
        guard let appUrl = URL(string: "file://\(appPath)"),
              let img = NSWorkspace.shared.icon(forFile: appUrl.path).cgImage(
                  forProposedRect: nil, context: nil, hints: nil
              ) else {
            return fallbackRGB()
        }
        return renderToRGB(cgImage: img)
    }

    /// 渲染 CGImage → 16×16 RGB565（全色，透明区域用槽位底色填充）
    private static func renderToRGB(cgImage: CGImage) -> Data? {
        let s = size
        guard let ctx = CGContext(
            data: nil, width: s, height: s,
            bitsPerComponent: 8, bytesPerRow: s * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return nil }
        ctx.interpolationQuality = .high
        ctx.draw(cgImage, in: CGRect(x: 0, y: 0, width: s, height: s))
        guard let data = ctx.data else { return nil }
        let pixels = data.bindMemory(to: UInt8.self, capacity: s * s * 4)
        let bgR: UInt8 = 26, bgG: UInt8 = 26, bgB: UInt8 = 26
        var out = Data(count: s * s * 2)
        for i in 0..<(s * s) {
            let off = i * 4
            let a = pixels[off + 3]
            let r = a > 32 ? pixels[off] : bgR
            let g = a > 32 ? pixels[off + 1] : bgG
            let b = a > 32 ? pixels[off + 2] : bgB
            let c = UInt16(r >> 3) << 11 | UInt16(g >> 2) << 5 | UInt16(b >> 3)
            out[i * 2] = UInt8(c & 0xFF)
            out[i * 2 + 1] = UInt8(c >> 8)
        }
        return out
    }

    /// 兜底：灰色方块
    private static func fallbackRGB() -> Data {
        let s = size
        var d = Data(count: s * s * 2)
        for i in 0..<(s * s) {
            d[i * 2] = 0xA2; d[i * 2 + 1] = 0x10
        }
        return d
    }

    /// 功能键图标：橙色圆角方块 + 白色 F（RGB565）
    static func keyIcon() -> Data {
        let s = size  // 16
        let orange: UInt16 = 0xFD20
        let white: UInt16 = 0xFFFF
        let bg: UInt16 = 0x10A2
        var d = Data(count: s * s * 2)
        let margin = 1, radius = 2
        let frame = s - margin * 2  // 14
        for y in 0..<s {
            for x in 0..<s {
                var color = bg
                let mx = x - margin, my = y - margin
                if mx >= 0 && mx < frame && my >= 0 && my < frame {
                    // 圆角检测
                    var inside = true
                    if mx < radius && my < radius {
                        inside = (mx-radius+1)*(mx-radius+1)+(my-radius+1)*(my-radius+1) <= radius*radius
                    } else if mx >= frame-radius && my < radius {
                        inside = (mx-frame+radius)*(mx-frame+radius)+(my-radius+1)*(my-radius+1) <= radius*radius
                    } else if mx < radius && my >= frame-radius {
                        inside = (mx-radius+1)*(mx-radius+1)+(my-frame+radius)*(my-frame+radius) <= radius*radius
                    } else if mx >= frame-radius && my >= frame-radius {
                        inside = (mx-frame+radius)*(mx-frame+radius)+(my-frame+radius)*(my-frame+radius) <= radius*radius
                    }
                    if inside {
                        // F键：竖线 + 上横 + 中横
                        let lx = mx - 3, ly = my - 2
                        let stem = (lx >= 0 && lx <= 2)
                        let top  = (ly >= 0 && ly <= 2 && lx >= 0 && lx <= 8)
                        let mid  = (ly >= 5 && ly <= 7 && lx >= 0 && lx <= 6)
                        color = (stem || top || mid) ? white : orange
                    }
                }
                let idx = (y * s + x) * 2
                d[idx] = UInt8(color & 0xFF); d[idx+1] = UInt8(color >> 8)
            }
        }
        return d
    }

    /// RGB565 全色位图 → 2 色掩码（1bit/像素）+ 前景/背景色
    /// 与板端 ICON 消息格式一致：fg565/bg565 + 位掩码（MSB 在前）
    static func twoColor(from rgb565: Data) -> (mask: Data, fg: UInt16, bg: UInt16)? {
        let count = size * size
        guard rgb565.count >= count * 2 else { return nil }
        var freq: [UInt16: Int] = [:]
        for i in 0..<count {
            let c = UInt16(rgb565[i * 2]) | UInt16(rgb565[i * 2 + 1]) << 8
            freq[c, default: 0] += 1
        }
        // 背景 = 出现最多的颜色
        guard let bg = freq.max(by: { $0.value < $1.value })?.key else { return nil }
        // 前景 = 与背景不同的颜色里出现最多的
        var fg = bg
        var fgCount = 0
        for (c, n) in freq where c != bg && n > fgCount {
            fg = c
            fgCount = n
        }
        if fg == bg { fg = (bg == 0xFFFF) ? 0x0000 : 0xFFFF }  // 单色兜底
        var mask = Data(count: (count + 7) / 8)
        for i in 0..<count {
            let c = UInt16(rgb565[i * 2]) | UInt16(rgb565[i * 2 + 1]) << 8
            if c != bg {
                mask[i / 8] |= UInt8(0x80 >> (i % 8))
            }
        }
        return (mask, fg, bg)
    }
}
