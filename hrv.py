from machine import UART, Pin, I2C, Timer, ADC
from ssd1306 import SSD1306_I2C
from piotimer import Piotimer
from fifo import Fifo
from led import Led
import time
import micropython
micropython.alloc_emergency_exception_buf(200)

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

class Sensor:
    def __init__(self, pin):
        self.fifo = Fifo(500)
        self.adc = ADC(Pin(pin, Pin.IN))
    def start(self):
        self.timer = Piotimer(period=4, mode=Piotimer.PERIODIC, callback=self.callback)
    def callback(self, skibidi): # skibidi = dummy argument to homogenise piotimer with default micropython timer
        self.fifo.put(self.adc.read_u16())
    def end(self):
        self.timer.deinit()
        
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
        self.sensor = Sensor(sensor_pin)
        self.screen = self.menu_setup
        self.data = []
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
        # Cursors
        self.cursor = Cursor()
        self.alt_cursor_1 = Cursor()
        self.alt_cursor_2 = Cursor()
        
    def analysis_setup(self):
        self.cursor.cap = (0, 1)
        self.screen = self.analysis
        
    def analysis(self):
        pass
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
        
        #print(self.pulse_sensor.read_u16())
        

        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.reset()
            if self.cursor.position == 0:
                self.screen = self.sensor_setup
            if self.cursor.position == 1:
                self.screen = self.analysis_setup
            if self.cursor.position == 2:
                self.screen = self.kubios
            if self.cursor.position == 3:
                self.screen = self.history
        

    def sensor_setup(self):
        self.sensor.start()
        threshold_count = 0
        while not self.sensor.fifo.has_data():
            pass
        min_point = max_point = self.sensor.fifo.get()
        while threshold_count <= 250:
            while self.sensor.fifo.has_data():
                point = self.sensor.fifo.get()
                threshold_count += 1
                # Update min-max values
                if point < min_point:
                    min_point = point
                if point > max_point:
                    max_point = point
        
        self.threshold = (min_point + max_point) / 2
                
                
        self.screen = self.heart_rate_screen
    def sensor_return(self):
        self.sensor.end()
        self.threshold = None
        
    def heart_rate_screen(self):
        oled.fill(0)
        i = 0
        avg = 0
        while self.sensor.fifo.has_data():
            data = self.sensor.fifo.get()
            avg+=data
            i+=1
            if i>=5:
                print(avg/5)
                avg = 0

class Peaks:
    def __init__(self, fileName):
        self.data = Filefifo(10, name = fileName)
        self.calculate_threshold()
    def get_dynamic_threshold(self, sample_count=500):
        samples = [self.data.get() for _ in range(sample_count)]
        return sum(samples) / len(samples)
    
    def calculate_threshold(self):
        self.min = self.max = self.data.get()
        for _ in range(499):
            point = self.data.get()
            print(f'point: {point}')
            if self.min > point:
                self.min = point
            if self.max < point:
                self.max = point
        
        return (self.min + self.max)/2
    def calculate(self):
        max = 0
        max_index_previous = None
        max_index = 0
        for i in range(2000):
            point = self.data.get()
            if self.min > point:
                self.min = point
            if self.max < point:
                self.max = point
#            print(point)
            self.threshold = (self.min + self.max) / 2
            print(f'point: {point}   threshold: {self.threshold}')
            if point > self.threshold:
                if point >= max:
                    max = point
                    max_index = i
            else:
                if (not max_index_previous is None) and not(max_index == max_index_previous):
                    diff = (max_index - max_index_previous)  # Erotus
                    sec = diff*4/1000 # 4 is the ammount of ms pass for every point retrieved and the division of 1000 is ms to seconds  # Seconds
                    freq = 1/sec   # Tajuus
                    
                    print("difference", diff)
                    print("seconds", sec, "s")
                    print("tajuus", freq, "Hz")
                    
                max = self.threshold
                max_index_previous = max_index
                
    def calculate(self):
        threshold = self.get_dynamic_threshold()
        print(f"Dynamic threshold: {threshold:.2f}")

        buffer = [self.data.get(), self.data.get(), self.data.get()]
        previous_peak_index = None
        cooldown = 0
        min_peak_distance = int(0.4 * self.sample_rate)  # ~250 ms

        for i in range(45000):
            buffer.pop(0)
            buffer.append(self.data.get())

            prev, curr, next_ = buffer

            if cooldown > 0:
                cooldown -= 1
                continue

            # Check if current point is a local max and above threshold
            if curr > threshold and curr > prev and curr > next_:
                if previous_peak_index is not None:
                    ppi = (i - 1 - previous_peak_index) * self.ts
                    if 250 <= ppi <= 2000:
                        hr = 60000 / ppi
                        print(f"PPI: {ppi:.1f} ms | HR: {hr:.1f} bpm")
                previous_peak_index = i - 1
                cooldown = min_peak_distance  # prevent double-counting too quickly
            

rot = Encoder(10, 11, 12)
ui = UI(rot, 27, 9, 7)
while True:
    ui.display()
    


