import time
from machine import UART, Pin, I2C, Timer
from ssd1306 import SSD1306_I2C
from fifo import Fifo

rot_button = Pin(12, Pin.IN, Pin.PULL_UP)

i2c = I2C(1, scl=Pin(15), sda=Pin(14), freq=400000)
oled_width = 128
oled_height = 64
currentY=0
currentX=0
arrow_position=0
oled = SSD1306_I2C(oled_width, oled_height, i2c)

class Encoder:
    def __init__(self, rot_a, rot_b):
        self.a = Pin(rot_a, mode = Pin.IN, pull = Pin.PULL_UP)
        self.b = Pin(rot_b, mode = Pin.IN, pull = Pin.PULL_UP)
        self.fifo = Fifo(30, typecode = 'i')
        self.fifo_sensor = Fifo(50, typecode = 'i')
        self.a.irq(handler = self.handler, trigger = Pin.IRQ_RISING, hard = True)
    def handler(self, pin):
        if self.b():
            self.fifo.put(-1)
        else:
            self.fifo.put(1)
rot = Encoder(10, 11)

class UI:
    def __init__(self, rot_a, rot_b, rot_c):
        self.rot = Encoder(rot_a, rot_b)
        self.rot_button = Pin(rot_c, Pin.IN, Pin.PULL_UP)
        self.screen = self.menu
        self.arrow_position = 0
        self.reset_buttons = False
        
    def display(self):
        if self.reset_buttons:
            self.reset()
            self.reset_buttons = False
        self.move()
        self.screen()    
        oled.show()
    
    def reset(self):
        oled.fill(0)
        arrow_position = 0
    def move(self):
        if self.rot.fifo.has_data():
            y = self.rot.fifo.get()
            if y == -1 and (not self.arrow_position == 0):
                self.arrow_position-=1
            elif y == 1 and (not self.arrow_position == 3):
                self.arrow_position+=1
    def calculate_threshold(self):
        min = None
        max = None
        for _ in range(500):
            point = self.data.get()
            if ((min is None) and (max is None)):
                min = point
                max = point
            else:
                if min > point:
                    min = point
                if max < point:
                    max = point
        return (min + max)/2
    def menu(self):
        oled.fill(0)
        oled.text("1.Heart rate", 0, 0, 1)
        oled.text("2.Basic HRV analysis", 0, 10, 1)
        oled.text("3.Kubios", 0, 20, 1)
        oled.text("4.History", 0, 30, 1)
        oled.rect(0, self.arrow_position*10, 12, 8, 0, True)
        oled.text("->", 0, self.arrow_position*10, 1)

        if self.rot_button() == 0:
            time.sleep(0.1)
            if self.rot_button() == 0:
                self.reset_buttons = True
                if self.arrow_position == 0:
                    self.screen = self.heart_rate
                if self.arrow_position == 1:
                    self.screen = self.analysis
                if self.arrow_position == 2:
                    self.screen = self.kubios
                if self.arrow_position == 3:
                    self.screen = self.history
        
ui = UI(10, 11, 12)
while True:
    ui.display()
#    oled.fill(0)
#    oled.text("1.Heart rate", 0, 0, 1)
#    oled.text("2.Basic HRV analysis", 0, 10, 1)
#    oled.text("3.Kubios", 0, 20, 1)
#    oled.text("4.History", 0, 30, 1)
#    oled.rect(0, arrowY*10, 12, 8, 0, True)
#    oled.text("->", 0, arrowY*10, 1)


    
    
#	oled.rect(currentX, currentY, 128, 8, 1, True)
    

