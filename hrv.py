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
sample_interval = 4

def transform(y, scale, offset):
    y *= scale
    y -= offset
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
        self.fifo = Fifo(100)
        self.adc = ADC(Pin(pin, Pin.IN))
    def timer_start(self):
        self.timer = Piotimer(period=sample_interval, mode=Piotimer.PERIODIC, callback=self.callback)
    def callback(self, skibidi): # skibidi = dummy argument to homogenise piotimer with default micropython timer
        self.fifo.put(self.adc.read_u16())
    def timer_end(self):
        self.timer.deinit()
        self.fifo = Fifo(100)
        
class HRV:
    def __init__(self):
        # Data
        self.intervals = []
        self.threshold = None
        self.bpm = None
        self.ppi = None
        self.bpm_output = 0
        # Helpers
        self.current_peak = None
        self.last_bpm = 0
        # Counts
        self.threshold_count = 0
        self.bpm_update_count = 0
        # Index
        self.current_peak_index = 0
        self.peak_previous_index = None
        self.peak_i=0
        
        
    def calculate_threshold(self, point):
            # update min-max values
            if point < self.min_point:
                self.min_point = point
            if point > self.max_point:
                self.max_point = point
            if self.threshold_count >= 250: ## this number is how many sample between calculations of the threshold                    
                self.threshold = (self.min_point + self.max_point) / 2
                self.normalization_value = (oled_height-1)/(self.max_point-self.min_point) ## normalisation value to fit datapoint to oled screen
                self.threshold_count = 0
                self.min_point = self.max_point = point
                if self.current_peak is None:
                    self.current_peak = self.threshold
            self.threshold_count += 1
    def calculate_peaks(self, point):
        self.bpm_update_count += 1
        self.peak_i += 1
        if point > self.threshold:
            if point >= self.current_peak:
                # Update peak and index when current is higher
                self.current_peak = point
                self.current_peak_index = self.peak_i
        else:
            # When there are two peaks and they are not the same one then
            # Calculate ppi, and bpm 
            if not(self.peak_previous_index is None) and not(self.current_peak_index == self.peak_previous_index):
                interval = (self.current_peak_index - self.peak_previous_index)  # Erotus
#                   sec = interval*sample_interval/1000 # 4 is the ammount of ms pass for every point retrieved and the division of 1000 is ms to seconds  # Seconds
                ppi = interval*sample_interval #
                minutes = (interval*sample_interval/1000)/60 # 4 is the ammount of ms pass for every point retrieved and the division of 1000 is ms to seconds  # Seconds
                bpm = 1/minutes
                
                self.intervals.append(interval)
                                
                if self.bpm_update_count >= 250*5: ## 250 samples = 1 second, 5 seconds
                    total = 0
                    if self.intervals: ##check if list exists to avoid dividing by zero
                        print("total samples: ",len(self.intervals))
                        print("average heartrate pre_correction: ", (60 * 1000) / sample_interval / (sum(self.intervals) / len(self.intervals)))
                    
                    self.intervals = [i for i in self.intervals if 75 < i < 375] ## Make list out of all usable intervals (75-500*4 ms)
                    
                    print("Usable samples: ",len(self.intervals))
                    
                    if self.intervals: ##check if list exists to avoid dividing by zero
                        self.bpm_output = (60 * 1000) / sample_interval / (sum(self.intervals) / len(self.intervals)) ## one minute in ms divided by the average ppi
                        
                        print("average heartrate post_correction: ", (60 * 1000) / sample_interval / (sum(self.intervals) / len(self.intervals)))
                        print("")
                        
                    self.intervals = []
                    self.bpm_update_count = 0
                
            self.current_peak = self.threshold
            self.peak_previous_index = self.current_peak_index
        
        
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
        self.sample_interval = 4
        self.interval = []
        
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
                self.screen = self.heart_rate_start_screen
            if self.cursor.position == 1:
                self.screen = self.analysis_setup
            if self.cursor.position == 2:
                self.screen = self.kubios
            if self.cursor.position == 3:
                self.screen = self.history
        
    def heart_rate_start_screen(self):
        oled.text("Start measurment", 0, 10, 1)
        oled.text("by pressing the ", 0, 20, 1)
        oled.text("rotary button", 0, 30, 1)
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.screen = self.sensor_setup
    def sensor_setup(self):
        # setup of peak detection and graph and threshold calculation
        self.hrv = HRV()
        self.graph_helper = 0
        self.graph_i = 0
        self.graph_frequency = 5
        # hr graphic variables
        self.ypos_sum = 0
        self.ysum_i = 0
        self.xpos = 100
        self.lastpos = 0
        # Timer
        self.sensor.timer_start()
        while not self.sensor.fifo.has_data():
            pass
        self.hrv.min_point = self.hrv.max_point = self.sensor.fifo.get()
        
        while self.hrv.threshold is None:
            if self.sensor.fifo.has_data():
                self.hrv.calculate_threshold(self.sensor.fifo.get())   
        self.screen = self.heart_rate_screen
        oled.fill(0)
    def heart_rate_screen(self):
        while self.sensor.fifo.has_data():
            point = self.sensor.fifo.get()
            self.hrv.calculate_threshold(point)
            self.hrv.calculate_peaks(point)
            # Display
            oled.rect(102,0, 28, 20, 0, 1)
            oled.text(f"{int(self.hrv.bpm_output)}",102,0,1)
            oled.text("BPM",102,10,1)
            #oled.pixel( self.xpos, transform(point, self.hrv.normalization_value, 0), 1)
            self.ypos_sum += transform(point-self.hrv.min_point, self.hrv.normalization_value*0.6, -20)
            self.ysum_i += 1
            if self.ysum_i > 6:
                current_ypos = int((self.ypos_sum / 7))
                oled.line(self.xpos, 0,self.xpos, 64, 0)
                oled.line(self.xpos-1, 0,self.xpos-1, 64, 0)
                oled.line(self.xpos+1,self.lastpos,self.xpos,current_ypos, 1)
                self.lastpos = current_ypos
                self.ypos_sum = 0
                self.ysum_i = 0
                self.xpos -= 1
            if self.xpos < 0:
                self.xpos = 100
            
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.screen = self.heart_rate_screen_return
    def heart_rate_screen_return(self):
        self.sensor.timer_end()
        self.screen = self.menu


rot = Encoder(10, 11, 12)
ui = UI(rot, 27, 9, 7)
while True:
    ui.display()
    




