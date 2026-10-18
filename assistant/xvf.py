"""XVF3800 の制御コマンド（USB のベンダー制御転送）。公式 python_control/xvf_host.py と同じ手順

USB に触るには udev ルールが要る（docs/c1-loopback.md）。
ここで変えた設定はフラッシュに保存しないので、デバイスを再起動すると元に戻る。
"""
import time
from contextlib import contextmanager

import usb.core
import usb.util

VID, PID = 0x2886, 0x001A
STATUS_OK, STATUS_RETRY = 0, 64

# (resid, cmdid, 値の個数)。値はすべて uint8
AUDIO_MGR_OP_R = (35, 19, 2)  # 右（ch2）に出す信号: <category>, <source>
RAW_MIC = (3, 0)  # 増幅済みマイク 0（エコーキャンセル前）


class XVF:
    def __init__(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise RuntimeError("XVF3800 が USB に見えない")

    def read(self, param: tuple[int, int, int]) -> tuple[int, ...]:
        resid, cmdid, count = param
        for _ in range(100):
            r = self.dev.ctrl_transfer(
                usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
                0, 0x80 | cmdid, resid, count + 1, 1000)
            if r[0] == STATUS_OK:
                return tuple(r[1:])
            if r[0] != STATUS_RETRY:
                raise RuntimeError(f"XVF3800 の制御が失敗した（status {r[0]}）")
            time.sleep(0.01)
        raise RuntimeError("XVF3800 の制御が応答しない")

    def write(self, param: tuple[int, int, int], values: tuple[int, ...]) -> None:
        resid, cmdid, count = param
        assert len(values) == count
        self.dev.ctrl_transfer(
            usb.util.CTRL_OUT | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
            0, cmdid, resid, bytes(values), 1000)


@contextmanager
def right_channel(source: tuple[int, int]):
    """右チャンネルの出力を一時的に切り替え、抜けるときに元へ戻す"""
    xvf = XVF()
    original = xvf.read(AUDIO_MGR_OP_R)
    xvf.write(AUDIO_MGR_OP_R, source)
    try:
        yield original
    finally:
        xvf.write(AUDIO_MGR_OP_R, original)
