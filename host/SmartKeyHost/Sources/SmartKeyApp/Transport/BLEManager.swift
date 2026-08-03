//
//  BLEManager.swift
//  CoreBluetooth 传输层实现 —— 负责 BLE 扫描、连接、收发原始字节
//  SmartKey 自定义 GATT 服务（ESP32 原生 NimBLE + MicroPython）
//
import Foundation
import CoreBluetooth
import Combine

final class BLEManager: NSObject, DeviceTransportProtocol {
    // MARK: - DeviceTransportProtocol
    let connectionStateSubject = CurrentValueSubject<ConnectionState, Never>(.idle)
    let receivedDataSubject = PassthroughSubject<Data, Never>()
    let discoveredDevicesSubject = CurrentValueSubject<[ScannedDevice], Never>([])

    // MARK: - SmartKey GATT UUIDs（与下位机 smartkey_ble.py / smartkey_protocol.py 保持一致）
    private let serviceUUID = CBUUID(string: "F000A001-B5A3-F393-E0A9-E50E24DCCA9E")
    private let keyEventsUUID = CBUUID(string: "F000A002-B5A3-F393-E0A9-E50E24DCCA9E") // notify：板子→电脑
    private let statusUUID = CBUUID(string: "F000A003-B5A3-F393-E0A9-E50E24DCCA9E")     // read：板子状态
    private let controlUUID = CBUUID(string: "F000A004-B5A3-F393-E0A9-E50E24DCCA9E")    // write：电脑→板子

    /// 设备显示名：macOS 上报的 GAP 设备名是固件默认的 "MPY ESP32"，
    /// 固定显示 "SmartKey" 避免混淆，也让"按名称自动重连"稳定生效
    private let displayName = "SmartKey"

    // MARK: - 内部状态
    private var central: CBCentralManager!
    private var connectedPeripheral: CBPeripheral?
    private var keyEventsChar: CBCharacteristic?
    private var statusChar: CBCharacteristic?
    private var controlChar: CBCharacteristic?
    private var discovered: [UUID: ScannedDevice] = [:]
    private var scanTimer: Timer?
    /// 用户主动断开标记（区分"自动重连"与"手动断开"）
    private var userInitiatedDisconnect = false
    /// 传输就绪回调：连接且特征就绪后调用
    var onReady: (() -> Void)?
    /// 非主动断连回调：连接意外断开时触发（用于自动重连）
    var onUnexpectedDisconnect: (() -> Void)?

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
        AppLog.log("BLEManager 初始化，bluetooth state: \(central.state.rawValue)")
    }

    // MARK: - DeviceTransportProtocol
    func scan() {
        AppLog.log("开始扫描")
        connectionStateSubject.send(.scanning)
        discovered.removeAll()
        discoveredDevicesSubject.send([])
        guard central.state == .poweredOn else {
            AppLog.log("扫描失败: 蓝牙未开启 (state=\(central.state.rawValue))")
            connectionStateSubject.send(.error("蓝牙未开启"))
            return
        }
        // 按服务 UUID 过滤：只显示带 SmartKey 服务的设备（不会混进无关设备）
        central.scanForPeripherals(
            withServices: [serviceUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
        )
        // 12 秒后自动停止
        scanTimer?.invalidate()
        scanTimer = Timer.scheduledTimer(withTimeInterval: 12.0, repeats: false) { [weak self] _ in
            self?.stopScan()
        }
    }

    func stopScan() {
        central.stopScan()
        scanTimer?.invalidate()
        scanTimer = nil
    }

    func connect(to device: ScannedDevice) {
        guard let peripheral = device.peripheral as? CBPeripheral else {
            AppLog.log("连接失败: 设备句柄无效")
            connectionStateSubject.send(.error("设备句柄无效"))
            return
        }
        AppLog.log("连接 \(device.name) (\(peripheral.identifier.uuidString))")
        connectionStateSubject.send(.connecting)
        connectedPeripheral = peripheral
        peripheral.delegate = self
        userInitiatedDisconnect = false
        central.connect(peripheral, options: nil)
    }

    func disconnect() {
        userInitiatedDisconnect = true
        if let peripheral = connectedPeripheral {
            central.cancelPeripheralConnection(peripheral)
        }
        connectedPeripheral = nil
        keyEventsChar = nil
        statusChar = nil
        controlChar = nil
        connectionStateSubject.send(.idle)
    }

    func send(data: Data) {
        guard let ctrl = controlChar, let peripheral = connectedPeripheral, peripheral.state == .connected else {
            connectionStateSubject.send(.error("未连接，无法发送"))
            return
        }
        // 超过 MTU 分块（取保守 180，CONTROL 特征按值写入会分片）
        let chunkSize = 180
        if data.count <= chunkSize {
            peripheral.writeValue(data, for: ctrl, type: .withResponse)
            AppLog.log("send: \(data.count)B 写→control")
        } else {
            var offset = 0
            while offset < data.count {
                let end = min(offset + chunkSize, data.count)
                let chunk = data.subdata(in: offset..<end)
                peripheral.writeValue(chunk, for: ctrl, type: .withResponse)
                AppLog.log("send: chunk \(offset)..<\(end) 写→control")
                offset = end
            }
        }
    }
}

// MARK: - CBCentralManagerDelegate
extension BLEManager: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            connectionStateSubject.send(.idle)
        case .poweredOff:
            connectionStateSubject.send(.error("蓝牙已关闭"))
        case .unauthorized:
            connectionStateSubject.send(.error("蓝牙未授权，请检查系统设置"))
        case .unsupported:
            connectionStateSubject.send(.error("此设备不支持蓝牙 BLE"))
        default:
            connectionStateSubject.send(.error("蓝牙状态未知"))
        }
    }

    func centralManager(_ central: CBCentralManager,
                        didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any],
                        rssi RSSI: NSNumber) {
        // 扫描按服务 UUID 过滤，能出现在这里的都是 SmartKey 设备
        let device = ScannedDevice(
            id: peripheral.identifier,
            name: displayName,
            peripheral: peripheral,
            rssi: RSSI.intValue,
            isSmartKey: true
        )
        discovered[peripheral.identifier] = device
        discoveredDevicesSubject.send(discovered.values.sorted { $0.rssi > $1.rssi })
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        AppLog.log("✅ didConnect: \(peripheral.name ?? "?")")
        connectionStateSubject.send(.connected)
        peripheral.discoverServices([serviceUUID])
    }

    func centralManager(_ central: CBCentralManager,
                        didFailToConnect peripheral: CBPeripheral,
                        error: Error?) {
        let msg = error?.localizedDescription ?? "连接失败"
        AppLog.log("❌ didFailToConnect: \(msg)")
        connectionStateSubject.send(.error(msg))
        // 连接失败（配对信息过期等）→ 重新扫描 + 触发自动重连
        if !userInitiatedDisconnect {
            onUnexpectedDisconnect?()
        }
    }

    func centralManager(_ central: CBCentralManager,
                        didDisconnectPeripheral peripheral: CBPeripheral,
                        error: Error?) {
        // 用户主动断开 error 为 nil；异常断开 error 非 nil
        let unexpected = !userInitiatedDisconnect
        if let error = error {
            AppLog.log("⚠️ didDisconnect with error: \(error.localizedDescription)")
        } else {
            AppLog.log("已主动断开")
        }
        userInitiatedDisconnect = false
        connectionStateSubject.send(.idle)
        keyEventsChar = nil
        statusChar = nil
        controlChar = nil
        if unexpected {
            AppLog.log("检测到意外断开，触发自动重连")
            onUnexpectedDisconnect?()
        }
    }
}

// MARK: - CBPeripheralDelegate
extension BLEManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error = error {
            AppLog.log("didDiscoverServices error: \(error.localizedDescription)")
        }
        guard let services = peripheral.services else {
            AppLog.log("未发现服务")
            connectionStateSubject.send(.error("未发现服务"))
            return
        }
        AppLog.log("发现 \(services.count) 个服务")
        for service in services where service.uuid == serviceUUID {
            AppLog.log("找到 SmartKey 服务，发现特征…")
            peripheral.discoverCharacteristics([keyEventsUUID, statusUUID, controlUUID], for: service)
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didDiscoverCharacteristicsFor service: CBService,
                    error: Error?) {
        if let error = error {
            AppLog.log("didDiscoverCharacteristics error: \(error.localizedDescription)")
        }
        guard let characteristics = service.characteristics else {
            connectionStateSubject.send(.error("未发现特征"))
            return
        }
        AppLog.log("发现 \(characteristics.count) 个特征")
        var foundControl = false
        var foundKeyEvents = false
        for char in characteristics {
            if char.uuid == keyEventsUUID {
                keyEventsChar = char
                foundKeyEvents = true
                AppLog.log("设置 KEY_EVENTS notify 监听")
                peripheral.setNotifyValue(true, for: char)
            } else if char.uuid == statusUUID {
                statusChar = char
                AppLog.log("读取 DEVICE_STATUS …")
                peripheral.readValue(for: char)
            } else if char.uuid == controlUUID {
                controlChar = char
                foundControl = true
                AppLog.log("CONTROL 特征就绪")
            }
        }
        if foundControl && foundKeyEvents {
            // 特征就绪，通知 ViewModel 可以开始发送
            AppLog.log("BLE 特征就绪，可以发送")
            onReady?()
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didUpdateValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        if let error = error {
            AppLog.log("didUpdateValue error: \(error.localizedDescription)")
            return
        }
        guard let value = characteristic.value else { return }
        if characteristic == keyEventsChar {
            // 按键事件原始字节流抛出，由协议层解析
            receivedDataSubject.send(value)
        } else if characteristic == statusChar {
            AppLog.log("DEVICE_STATUS: \(String(data: value, encoding: .utf8) ?? "?")")
        }
    }
}
