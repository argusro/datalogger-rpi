"""Userspace USB driver for the National Instruments USB-6008.

Talks to the device directly over libusb (via pyusb); no NI-DAQmx required,
which is what makes it usable on ARM/Raspberry Pi.

Protocol (reverse-engineered from a USB capture of NI-DAQmx):

  Command channel: EP 0x01 (out) / 0x81 (in)   frame:
      00 01 | u16 total_len | u16 (total_len - 4) | u16 opcode | params...
  Data channel:    EP 0x82 (in) / 0x02 (out)

  Analog single sample: run the AI config sequence, then send opcode 0x0014
  with params 02 03 00 00 00 00 00 01 and read 2 bytes from EP 0x82. The value
  is a 12-bit sample left-justified in 16 bits, offset binary (2048 == 0 V).

Run on the device:

    python3 usb6008.py            # dump descriptors
    python3 usb6008.py --read     # configure AI and print a few samples
"""

import struct
import sys
import time

try:
    import usb.core
    import usb.util
except ImportError:  # pragma: no cover - only relevant on the target device
    usb = None


VENDOR_ID = 0x3923
PRODUCT_IDS = (0x717A, 0x0000)

READ_TIMEOUT_MS = 1000

EP_CMD_OUT = 0x01
EP_CMD_IN = 0x81
EP_DATA_IN = 0x82
EP_DATA_OUT = 0x02

AI_ADC_MID = 2048
AI_ADC_COUNTS = 2048


class USB6008Error(Exception):
    pass


def _require_pyusb():
    if usb is None:
        raise USB6008Error(
            "pyusb is not installed (pip install pyusb) or libusb-1.0 is missing"
        )


def find_device(id_product=None):
    _require_pyusb()
    products = (id_product,) if id_product else PRODUCT_IDS
    for pid in products:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=pid)
        if dev is not None:
            return dev
    return None


def _safe_string(dev, index):
    if not index:
        return None
    try:
        return usb.util.get_string(dev, index)
    except Exception:
        return None


def build_message(opcode, params=b""):
    total = 8 + len(params)
    return struct.pack("<HHHH", 0x0001, total, total - 4, opcode) + params


INIT_SEQUENCE = [
    (0x0114, "02040000000001f000010000"),
    (0x0114, "02040000000001f100010000"),
]

AI_READ = (0x0014, "0203000000000001")

DI_READ = (0x010E, "0210000000030000")

AI_CHANNELS = 8
DI_CHANNELS = 8


def ai_config_commands(channel):
    bank = "02" if channel >= 4 else "00"
    ch = "%02x" % (channel & 0xFF)
    return [
        (0x010F, "02020000000400" + ch),
        (0x010E, "020200000003" + bank + "00"),
        (0x0110, "0202000000002710ffffd8f0fdfd000400000000"),
        (0x010E, "0200000000000000"),
        (0x010F, "0200000000000001"),
        (0x0113, "02000000"),
        (0x0115, "02000000"),
        (0x0118, "02000000"),
        (0x010F, "02030000"),
        (0x0109, "02030000"),
        (0x0109, "02000000"),
    ]

AI_STOP_SEQUENCE = [
    (0x010B, "02000000"),
    (0x010C, "02000000"),
    (0x010C, "02030000"),
    (0x010D, "02000000"),
]


class USB6008(object):
    name = "usb6008"

    def __init__(self, device=None, interface=0, voltage_max=10.0):
        _require_pyusb()
        self._dev = device or find_device()
        if self._dev is None:
            raise USB6008Error(
                "NI USB-6008 not found (VID 0x%04x, PID one of %s)"
                % (VENDOR_ID, ", ".join("0x%04x" % p for p in PRODUCT_IDS))
            )
        self._interface = interface
        self._voltage_max = voltage_max
        self._claimed = False
        self._ai_started = False
        self._ai_channel = None
        self._open()
        self._init()

    def _open(self):
        dev = self._dev
        try:
            dev.set_configuration()
        except usb.core.USBError as exc:
            if getattr(exc, "errno", None) not in (16, 22):
                raise USB6008Error("set_configuration failed: %s" % exc)
        iface = self._get_interface()
        try:
            if dev.is_kernel_driver_active(iface.bInterfaceNumber):
                dev.detach_kernel_driver(iface.bInterfaceNumber)
        except (NotImplementedError, usb.core.USBError):
            pass
        try:
            usb.util.claim_interface(dev, iface.bInterfaceNumber)
            self._claimed = True
        except usb.core.USBError as exc:
            raise USB6008Error("claim_interface failed: %s" % exc)

    def _get_interface(self, number=None):
        number = self._interface if number is None else number
        cfg = self._dev.get_active_configuration()
        for iface in cfg:
            if iface.bInterfaceNumber == number:
                return iface
        raise USB6008Error("interface %d not present" % number)

    def describe(self):
        dev = self._dev
        info = {
            "vendor_id": "0x%04x" % dev.idVendor,
            "product_id": "0x%04x" % dev.idProduct,
            "manufacturer": _safe_string(dev, dev.iManufacturer),
            "product": _safe_string(dev, dev.iProduct),
            "serial": _safe_string(dev, dev.iSerialNumber),
            "bus": getattr(dev, "bus", None),
            "address": getattr(dev, "address", None),
            "interfaces": [],
        }
        try:
            config = dev.get_active_configuration()
        except usb.core.USBError:
            config = dev[0]
        for iface in config:
            entry = {
                "number": iface.bInterfaceNumber,
                "alternate": iface.bAlternateSetting,
                "endpoints": [],
            }
            for ep in iface:
                entry["endpoints"].append({
                    "address": "0x%02x" % ep.bEndpointAddress,
                    "direction": "IN" if ep.bEndpointAddress & 0x80 else "OUT",
                    "type": ep.bmAttributes & 0x03,
                    "max_packet_size": ep.wMaxPacketSize,
                })
            info["interfaces"].append(entry)
        return info

    def _endpoint(self, address, direction):
        iface = self._get_interface()
        for ep in iface:
            if ep.bEndpointAddress == address:
                return ep
        for ep in iface:
            if (ep.bEndpointAddress & 0x80) == (direction << 7):
                return ep
        raise USB6008Error("no %s endpoint (0x%02x)" % (direction, address))

    def control_in(self, request_type, request, value, index, length,
                   timeout=READ_TIMEOUT_MS):
        return self._dev.ctrl_transfer(
            request_type, request, value, index, length, timeout=timeout)

    def control_out(self, request_type, request, value, index, data=b"",
                    timeout=READ_TIMEOUT_MS):
        return self._dev.ctrl_transfer(
            request_type, request, value, index, data, timeout=timeout)

    def read_bulk(self, address, length, timeout=READ_TIMEOUT_MS):
        ep = self._endpoint(address, direction=1)
        return bytes(ep.read(length, timeout=timeout))

    def write_bulk(self, address, data, timeout=READ_TIMEOUT_MS):
        ep = self._endpoint(address, direction=0)
        return ep.write(data, timeout=timeout)

    def _send(self, opcode, params=b""):
        self.write_bulk(EP_CMD_OUT, build_message(opcode, params))

    def _read_ack(self, timeout=300):
        try:
            return self.read_bulk(EP_CMD_IN, 64, timeout=timeout)
        except usb.core.USBError:
            return b""

    def _command(self, opcode, params=b""):
        self._send(opcode, params)
        return self._read_ack()

    def _init(self):
        for opcode, params in INIT_SEQUENCE:
            self._command(opcode, bytes.fromhex(params))

    def start_ai(self, channel=0):
        for opcode, params in ai_config_commands(channel):
            self._command(opcode, bytes.fromhex(params))
        self._ai_started = True
        self._ai_channel = channel

    def stop_ai(self):
        for opcode, params in AI_STOP_SEQUENCE:
            self._command(opcode, bytes.fromhex(params))
        self._ai_started = False

    def read_ai_raw(self):
        if not self._ai_started:
            self.start_ai()
        opcode, params = AI_READ
        self._send(opcode, bytes.fromhex(params))
        data = self.read_bulk(EP_DATA_IN, 2)
        if len(data) < 2:
            raise USB6008Error("short AI sample: %r" % data)
        return struct.unpack("<H", data)[0]

    def raw_to_volts(self, raw):
        counts = (raw & 0xFFFF) >> 4
        return round((counts - AI_ADC_MID) * self._voltage_max / AI_ADC_COUNTS, 4)

    def read_analog(self, channel=0):
        self.start_ai(channel)
        try:
            return self.raw_to_volts(self.read_ai_raw())
        finally:
            self.stop_ai()

    def read_digital_port(self):
        opcode, params = DI_READ
        ack = self._command(opcode, bytes.fromhex(params))
        if len(ack) < 2:
            raise USB6008Error("short DI response: %r" % ack)
        return struct.unpack("<H", ack[-2:])[0]

    def debug_ai(self, channel=0):
        print("== init ==")
        for opcode, params in INIT_SEQUENCE:
            self._send(opcode, bytes.fromhex(params))
            print("  %04x %s -> %s" % (opcode, params, self._read_ack().hex() or "<none>"))
        print("== ai config channel %d ==" % channel)
        for opcode, params in ai_config_commands(channel):
            self._send(opcode, bytes.fromhex(params))
            print("  %04x %s -> %s" % (opcode, params, self._read_ack().hex() or "<none>"))
        print("== read (0014) ==")
        opcode, params = AI_READ
        self._send(opcode, bytes.fromhex(params))
        for _ in range(3):
            try:
                print("  ep2:", self.read_bulk(EP_DATA_IN, 2, timeout=2000).hex())
            except Exception as exc:
                print("  ep2 error:", exc)
                break

    def read_digital(self, line=0):
        return bool((self.read_digital_port() >> line) & 1)

    def read_all(self):
        analog = [self.read_analog(c) for c in range(AI_CHANNELS)]
        port = self.read_digital_port()
        digital = [bool((port >> i) & 1) for i in range(DI_CHANNELS)]
        return {"analog": analog, "digital": digital}

    def close(self):
        try:
            if self._ai_started:
                self.stop_ai()
        except Exception:
            pass
        if self._claimed:
            try:
                usb.util.release_interface(self._dev, self._interface)
            except Exception:
                pass
            self._claimed = False
        try:
            usb.util.dispose_resources(self._dev)
        except Exception:
            pass


def main():
    _require_pyusb()
    try:
        dev = find_device()
        if dev is None:
            print("NI USB-6008 not found.")
            return 1
        driver = USB6008(dev)
    except USB6008Error as exc:
        print("error: %s" % exc)
        return 2

    if "--debug" in sys.argv:
        i = sys.argv.index("--debug")
        ch = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else 0
        driver.debug_ai(ch)
        driver.close()
        return 0

    if "--read" in sys.argv:
        try:
            print("Reading AI0-7 + DI0-7 (Ctrl+C to stop)...")
            while True:
                data = driver.read_all()
                print("AI " + " ".join("%8.4f" % v for v in data["analog"]) +
                      "   DI " + "".join("1" if b else "0" for b in data["digital"]))
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("stopping")
        finally:
            driver.close()
        return 0

    import json
    print(json.dumps(driver.describe(), indent=2))
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
