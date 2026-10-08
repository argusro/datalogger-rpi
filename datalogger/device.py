import math
import os
import time

AI_COUNT = int(os.environ.get("AI_COUNT", "8"))
DI_COUNT = int(os.environ.get("DI_COUNT", "8"))
DEVICE_NAME = os.environ.get("NI_DEVICE", "Dev1")
AI_VOLTAGE_MAX = float(os.environ.get("AI_VOLTAGE_MAX", "10.0"))


class DeviceError(Exception):
    pass


class DeviceBase(object):
    name = "base"

    def read_all(self):
        raise NotImplementedError

    def close(self):
        pass


class MockDevice(DeviceBase):
    name = "mock"

    def __init__(self):
        self._t0 = time.time()

    def read_all(self):
        t = time.time() - self._t0
        analog = []
        for i in range(AI_COUNT):
            period = 2.0 + i
            offset = (i - AI_COUNT / 2.0) * 0.5
            value = offset + (AI_VOLTAGE_MAX * 0.6) * math.sin(t / period)
            analog.append(round(value, 4))
        counter = int(t)
        digital = [bool((counter >> i) & 1) for i in range(DI_COUNT)]
        return {"analog": analog, "digital": digital}


class NIDaqmxDevice(DeviceBase):
    name = "nidaqmx"

    def __init__(self):
        import nidaqmx

        self._nidaqmx = nidaqmx
        self._ai_task = nidaqmx.Task()
        self._ai_task.ai_channels.add_ai_voltage_chan(
            "%s/ai0:%d" % (DEVICE_NAME, AI_COUNT - 1),
            min_val=-AI_VOLTAGE_MAX,
            max_val=AI_VOLTAGE_MAX,
        )
        self._di_task = nidaqmx.Task()
        self._di_task.di_channels.add_di_chan(
            "%s/port0/line0:%d" % (DEVICE_NAME, DI_COUNT - 1)
        )

    def read_all(self):
        analog = self._to_list(self._ai_task.read(number_of_samples_per_channel=1))
        digital = self._to_list(self._di_task.read(number_of_samples_per_channel=1))
        return {
            "analog": [round(float(v), 4) for v in analog],
            "digital": [bool(v) for v in digital],
        }

    @staticmethod
    def _to_list(values):
        if isinstance(values, (list, tuple)):
            return list(values)
        return [values]

    def close(self):
        for task in (getattr(self, "_ai_task", None), getattr(self, "_di_task", None)):
            try:
                if task is not None:
                    task.close()
            except Exception:
                pass


def create_device(backend=None):
    backend = (backend or os.environ.get("DATALOGGER_BACKEND", "auto")).lower()
    if backend == "mock":
        return MockDevice()
    if backend == "nidaqmx":
        return NIDaqmxDevice()
    try:
        return NIDaqmxDevice()
    except Exception:
        return MockDevice()
