# epd_mhetlive_154.py A 1-bit monochrome display driver for the Waveshare / MH-ET-LIVE
# ePaper 1.54" display.
# Based on Waveshare epd1in54_V2.py by Waveshare Team
# and pico_epaper_42.py by Peter Hinch Sept 2022.
# Adaptated by Daniel Quadros - feb/23

# *****************************************************************************
# * | File        :	  epd1in54_V2.py
# * | Author      :   Waveshare team
# * | Function    :   Electronic paper driver
# * | Info        :
# *----------------
# * | This version:   V1.1
# * | Date        :   2022-08-10
# # | Info        :   python demo
# -----------------------------------------------------------------------------
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

from machine import Pin, SPI
import framebuf
import time
import uasyncio as asyncio
from drivers.boolpalette import BoolPalette

# Display resolution
_EPD_WIDTH = const(200)
_BWIDTH = _EPD_WIDTH // 8
_EPD_HEIGHT = const(200)

# Default connections
BUSY_PIN = 10
CS_PIN = 17
SCK_PIN = 18
MOSI_PIN = 19
DC_PIN = 20
RST_PIN = 21

# Commands
_DRIVER_OUTPUT_CONTROL = const(0x01)
_SET_GATE_VOLTAGE = const(0x03)
_SET_SOURCE_VOLTAGE = const(0x04)
_DEEP_SLEEP_MODE = const(0x10)
_DATA_ENTRY_MODE = const(0x11)
_SWRESET = const(0x12)
_UNDOC_1 = const(0x18)
_MASTER_ACTIVATION = const(0x20)
_DISPLAY_UPDATE_CONTROL_2 = const(0x22)
_WRITE_RAM_BLACK = const(0x24)
_VCOM_VOLTAGE = const(0x2C)
_WRITE_LUT_REGISTER = const(0x32)
_BORDER_WAVEFORM = const(0x3C)
_DRIVE_OUTPUT_CONTROL = const(0x3F)
_SET_RAM_X_ADDRESS = const(0x44)
_SET_RAM_Y_ADDRESS = const(0x45)
_SET_RAM_X_CURSOR = const(0x4E)
_SET_RAM_Y_CURSOR = const(0x4F)

# LUT
_LUT = (
    b"\x80\x48\x40\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x40\x48\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x80\x48\x40\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x40\x48\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x0a\x00\x00\x00\x00\x00\x00"
    b"\x08\x01\x00\x08\x01\x00\x02"
    b"\x0a\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00"
    b"\x22\x22\x22\x22\x22\x22\x00\x00\x00"
)


class EPD(framebuf.FrameBuffer):
    # A monochrome approach should be used for coding this. The rgb method ensures
    # nothing breaks if users specify colors.
    @staticmethod
    def rgb(r, g, b):
        return int((r > 127) or (g > 127) or (b > 127))

     # constructor
    def __init__(self, spi=None, cs=None, dc=None, rst=None, busy=None, asyn=False):
        self.reset_pin = Pin(RST_PIN, Pin.OUT) if rst is None else rst
        self.busy_pin = Pin(BUSY_PIN, Pin.IN, Pin.PULL_UP) if busy is None else busy
        self.cs_pin = Pin(CS_PIN, Pin.OUT) if cs is None else cs
        self.dc_pin = Pin(DC_PIN, Pin.OUT) if dc is None else dc
        self.spi = SPI(id=0, sck=Pin(SCK_PIN), mosi=Pin(MOSI_PIN)) if spi is None else spi
        self.spi.init(baudrate=4_000_000)
        self._asyn = asyn
        self._as_busy = False  # Set immediately on start of task. Cleared when busy pin is logically false (physically 1).
        self._updated = asyncio.Event()

        self.width = _EPD_WIDTH
        self.height = _EPD_HEIGHT
        self.buf = bytearray(_EPD_HEIGHT * _BWIDTH)
        self.mvb = memoryview(self.buf)
        mode = framebuf.MONO_HLSB
        self.palette = BoolPalette(mode)
        super().__init__(self.buf, _EPD_WIDTH, _EPD_HEIGHT, mode)
        self.init()
        time.sleep_ms(500)

    # Hardware reset
    def _reset(self):
        for v in (1, 0, 1):
            self.reset_pin(v)
            time.sleep_ms(200)  # originally 5m at 0

    # senda a command
    def _send_cmd(self, command):
        self.dc_pin(0)
        self.cs_pin(0)
        self.spi.write(bytearray([command]))
        self.cs_pin(1)

    # send data
    def _send_data(self, data):
        self.dc_pin(1)
        self.cs_pin(0)
        self.spi.write(data)
        self.cs_pin(1)

    # Turn on the display
    def _poweron(self):
        print ("power on")
        self._send_cmd(_DISPLAY_UPDATE_CONTROL_2)
        self._send_data(bytearray([0xc7]))
        self._send_cmd(_MASTER_ACTIVATION)
        self.wait_until_ready()
        
    # Turn off the display (sleep)
    def _poweroff(self):
        self._send_cmd(_DEEP_SLEEP_MODE)
        self._send_data(bytearray([0x01]))
        print ("power off")
        
    # Waveform setting
    def _set_lut(self):
        self._send_cmd(_WRITE_LUT_REGISTER)
        self._send_data(bytearray(_LUT))
        self._send_cmd(_DRIVE_OUTPUT_CONTROL)
        self._send_data(bytearray([0x22]))
        self._send_cmd(_SET_GATE_VOLTAGE)
        self._send_data(bytearray([0x17]))
        self._send_cmd(_SET_SOURCE_VOLTAGE)
        self._send_data(bytearray([0x41, 0x00, 0x32]))
        self._send_cmd(_VCOM_VOLTAGE)
        self._send_data(bytearray([0x20]))

     # initialize display controller
    def init(self):
        self._reset()
        self.wait_until_ready()
        self._send_cmd(_SWRESET)
        self.wait_until_ready()
        for (cmd, param) in (
            (_DRIVER_OUTPUT_CONTROL, (0xC7, 0x00, 0x01)),
            (_DATA_ENTRY_MODE, (0x01,)),
            (_SET_RAM_X_ADDRESS, (0, 24)),
            (_SET_RAM_Y_ADDRESS, (199, 0, 0, 0)),
            (_BORDER_WAVEFORM, (0x01,)),
            (_UNDOC_1, (0x80,)),
            (_DISPLAY_UPDATE_CONTROL_2, (0xB1,)),
            (_MASTER_ACTIVATION, ()),
            (_SET_RAM_X_CURSOR, (0,)),
            (_SET_RAM_Y_CURSOR, (199, 0)),
        ):
            self._send_cmd(cmd)
            if len(param) > 0:
                self._send_data(bytearray(param))
        self.wait_until_ready()
        self._set_lut() 

     # wait until controller ready for next command
    def wait_until_ready(self):
        print("Waiting")
        while(not self.ready()):
            time.sleep_ms(100)
        print("Ready")

    async def wait(self):
        await asyncio.sleep_ms(0)  # Ensure tasks run that might make it unready
        while not self.ready():
            await asyncio.sleep_ms(100)

    # Pause until framebuf has been copied to device.
    async def updated(self):
        await self._updated.wait()

    # For polling in asynchronous code. Just checks pin state.
    def ready(self):
        return not(self._as_busy or (self.busy_pin() == 1))  # 1 == busy

    # send a line (inverting bits, as 1 = white and 0 = black)
    def _send_line(self, n, buf=bytearray(_BWIDTH)):
        img = self.mvb
        s = n * _BWIDTH
        for x, b in enumerate(img[s : s + _BWIDTH]):
            buf[x] = b ^ 0xFF
        self._send_data(buf)

   # Assynchronous screen update
    async def _as_show(self):
        self._send_cmd(_WRITE_RAM_BLACK)
        for j in range(_EPD_HEIGHT):  # Loop would take ~300ms
            self._line(j)
            await asyncio.sleep_ms(0)
        self._poweron()
        while not self.busy_pin():
            await asyncio.sleep_ms(10)  # About 1.7s
        self._updated.set()
        self._updated.clear()
        self._as_busy = False

    # Update the screen
    # THERE MUST BE A MINIMUM OF 3 MINUTES (180 SECONDS) BETWEEN CALLS!!!
    def show(self):
        if self._asyn:
            if self._as_busy:
                raise RuntimeError('Cannot refresh: display is busy.')
            self._as_busy = True  # Immediate busy flag. Pin goes low much later.
            asyncio.create_task(self._as_show())
            return
        self.wait_until_ready()
        self._send_cmd(_WRITE_RAM_BLACK)
        for j in range(_EPD_HEIGHT):
            self._send_line(j)
        self._poweron()

    # Puts display to sleep
    # DO NOT LEAVE DISPLAY ON FOR LONG!!!
    def sleep(self):
        self._poweroff()

