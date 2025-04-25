from machine import UART, Pin, I2C, Timer, ADC
from ssd1306 import SSD1306_I2C
from piotimer import Piotimer
from fifo import Fifo
from led import Led
import time

i2c = I2C(1, scl=Pin(15), sda=Pin(14), freq=400000)
oled_width = 128
oled_height = 64
oled = SSD1306_I2C(oled_width, oled_height, i2c)

def transform(y, scale, offset):
    y -= offset
    y *= scale
    y = int(y)
    y = 63 - y
    return y

class Encoder:
    def __init__(self, rot_a, rot_b, rot_c):
        self.a = Pin(rot_a, mode = Pin.IN)
        self.b = Pin(rot_b, mode = Pin.IN)
        self.c = Pin(rot_c, mode = Pin.IN, pull = Pin.PULL_UP)
        self.time = time.ticks_ms()
        self.btn_fifo = Fifo(10)
        self.fifo = Fifo(50, typecode = 'i')
        self.a.irq(handler = self.handler, trigger = Pin.IRQ_RISING, hard = True)
        self.c.irq(handler = self.btn_handler_falling, trigger = Pin.IRQ_FALLING, hard = True)
        self.min = 0
        self.max = 0
        self.normalization_value = 0
    def handler(self, pin):
        if self.b():
            self.fifo.put(-1)
        else:
            self.fifo.put(1)
    def btn_handler_falling(self, pin):
        ms = time.ticks_ms()
        if time.ticks_diff(ms, self.time) > 150:
            self.btn_fifo.put(1)
        self.time = ms
class Cursor:
    def __init__(self, cap = (0, 0), increment = 1, position = 0):
        self.position = position
        self.cap = cap
        self.increment = increment
    def move(self, amount):
        if ((self.position + amount) <= self.cap[1]) and ((self.postion + amount) >= self.cap[0]):
            self.position += amount
    def directional_move(self, direction: int):
        if direction <= 0:
            self.decrease()
            return
        self.increase()
    def increase(self):
        if (self.position + self.increment) <= self.cap[1]:
            self.position += self.increment
    def decrease(self):
        if (self.position - self.increment) >= self.cap[0]:
            self.position -= self.increment

class UI:
    def __init__(self, encoder, sensor_pin, pin_sw_0, pin_sw_2):
        self.SW_0 = Pin(pin_sw_0, mode = Pin.IN, pull = Pin.PULL_UP)
        self.SW_2 = Pin(pin_sw_2, mode = Pin.IN, pull = Pin.PULL_UP)
        self.rot = encoder
        self.pulse_sensor = ADC(Pin(sensor_pin, Pin.IN))
        self.screen = self.menu_setup
        self.data = []
        self.cursor = Cursor()
        self.alt_cursor_1 = Cursor()
        self.alt_cursor_2 = Cursor()
        self.input_scale = 1
        self.input_offset = 0
        self.reset()
        
    def display(self):
        while self.rot.fifo.has_data():
            y = self.rot.fifo.get()
            btn_input = int(f'{self.SW_2()}{self.SW_0()}',2)
            if btn_input == 3:
                self.cursor.directional_move(y)
            if btn_input == 2:
                self.alt_cursor_1.directional_move(y)
            if btn_input == 1:
                self.alt_cursor_2.directional_move(y)
        self.screen()
        oled.show()
#    def move(self, cursor):
    def reset(self):
        oled.fill(0)
        self.cursor = Cursor()
        self.alt_cursor_1 = Cursor()
        self.alt_cursor_2 = Cursor()
        
    def menu_setup(self):
        self.cursor.cap = (0, 3)
        self.screen = self.menu
        
    def menu(self):
        oled.fill(0)
        oled.text("1.Heart rate", 0, 0, 1)
        oled.text("2.Basic HRV analysis", 0, 10, 1)
        oled.text("3.Kubios", 0, 20, 1)
        oled.text("4.History", 0, 30, 1)
        oled.rect(0, self.cursor.position*10, 12, 8, 0, True)
        oled.text("->", 0, self.cursor.position*10, 1)
        
        print(self.pulse_sensor.read_u16())
        

        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.reset()
            if self.cursor.position == 0:
                self.screen = self.sensor_setup
            if self.cursor.position == 1:
                self.screen = self.analysis
            if self.cursor.position == 2:
                self.screen = self.kubios
            if self.cursor.position == 3:
                self.screen = self.history
        

    def sensor_setup(self):
        self.data = []
        avg = 0
        for _ in range(5):
            avg += self.reader.get()
        avg = int(avg)
        avg /= 5
        self.min = avg
        self.max = avg
        self.data.append(avg)
        # Calibrating sensor
        for _ in range(359):
            # The average of 5 points
            avg = 0
            for _ in range(5):
                avg += self.reader.get()
            avg = int(avg)
            avg /= 5
            # Calibrate the min-max
            if self.min > avg:
                self.min = avg
            if self.max < avg:
                self.max = avg
            self.data.append(avg)
        self.normalization_value = (oled_height-1)/(self.max-self.min)
        # Cursors
        self.cursor.cap = (0, 359-oled_width)
        self.alt_cursor_1 = Cursor( (0.1, 2), 0.1, 1)
        self.alt_cursor_2 = Cursor( (-(2**12), 2**12), 250)
        self.screen = self.sensor_reading_screen
    def sensor_reading_screen(self):
        oled.fill(0)
        for i in range(oled_width):
            current_y = self.data[i+self.cursor.position]
            next_y = self.data[i+1+self.cursor.position]
            scale = self.normalization_value*self.alt_cursor_1.position
            offset = self.min - self.alt_cursor_2.position
            oled.line(i, transform(current_y, scale, offset), i+1, transform(next_y, scale, offset), 1)

            

rot = Encoder(10, 11, 12)
ui = UI(rot, 27, 9, 7)
while True:
    ui.display()
    


