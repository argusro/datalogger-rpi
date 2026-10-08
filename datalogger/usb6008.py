"""Userspace USB driver for the National Instruments USB-6008.

This module talks to the device directly over libusb (via pyusb); it does NOT
use NI-DAQmx, which has no ARM build. The USB command protocol is being
reverse-engineered, so the low-level transport (enumeration, interface claim,
control/bulk transfers) is implemented here while the exact command opcodes are
filled in as they are confirmed from USB captures.

Run this file directly on the device to dump descriptors and endpoints:

    python3 usb6008.py
"""

import sys

try:
    import usb.core
    import usb.util
except ImportError:  # pragma: no cover - only relevant on the target device
    usb = None


VENDOR_ID = 0x3923
PRODUCT_IDS = (0x717A, 0x0000)

READ_TIMEOUT_MS = 1000


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


class USB6008(object):
    name = "usb6008"

    def __init__(self, device=None, interface=0):
        _require_pyusb()
        self._dev = device or find_device()
        if self._dev is None:
            raise USB6008Error(
                "NI USB-6008 not found (VID 0x%04x, PID one of %s)"
                % (VENDOR_ID, ", ".join("0x%04x" % p for p in PRODUCT_IDS))
            )
        self._interface = interface
        self._claimed = False
        self._open()

    def _open(self):
        dev = self._dev
        try:
            dev.set_configuration()
        except usb.core.USBError as exc:
            # Already configured is fine.
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
                "class": iface.bInterfaceClass,
                "subclass": iface.bInterfaceSubClass,
                "protocol": iface.bInterfaceProtocol,
                "endpoints": [],
            }
            for ep in iface:
                entry["endpoints"].append({
                    "address": "0x%02x" % ep.bEndpointAddress,
                    "direction": "IN" if ep.bEndpointAddress & 0x80 else "OUT",
                    "type": ep.bmAttributes & 0x03,
                    "max_packet_size": ep.wMaxPacketSize,
                    "interval": getattr(ep, "bInterval", None),
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

    def read_analog(self, channel=0):
        raise USB6008Error(
            "analog read protocol not implemented yet; run the USB capture step"
        )

    def read_digital(self, line=0):
        raise USB6008Error(
            "digital read protocol not implemented yet; run the USB capture step"
        )

    def read_all(self):
        return {
            "analog": [self.read_analog(0)],
            "digital": [self.read_digital(0)],
        }

    def close(self):
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
    try:
        dev = find_device()
        if dev is None:
            print("NI USB-6008 not found.")
            return 1
        driver = USB6008(dev)
        import json
        print(json.dumps(driver.describe(), indent=2))
        print()
        print("Trying a 1-byte read on every IN endpoint (timeout %d ms):"
              % READ_TIMEOUT_MS)
        for iface in driver.describe()["interfaces"]:
            for ep in iface["endpoints"]:
                if ep["direction"] != "IN":
                    continue
                try:
                    data = driver.read_bulk(int(ep["address"], 16), 64)
                    print("  %s -> %s" % (ep["address"], data.hex()))
                except Exception as exc:
                    print("  %s -> no data (%s)" % (ep["address"], exc))
        driver.close()
        return 0
    except USB6008Error as exc:
        print("error: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
