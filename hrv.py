from machine import UART, Pin, I2C, Timer, ADC
from umqtt.simple import MQTTClient
from ssd1306 import SSD1306_I2C
from piotimer import Piotimer
from fifo import Fifo
from led import Led
import micropython
import network
import time
import json

micropython.alloc_emergency_exception_buf(200)

i2c = I2C(1, scl=Pin(15), sda=Pin(14), freq=400000)
oled_width = 128
oled_height = 64
oled = SSD1306_I2C(oled_width, oled_height, i2c)
sample_interval = 4

SSID = "KMD652_Group_5"
PASSWORD = "T3am-5*4p"
BROKER_IP = "192.168.5.253"
BROKER_PORT = 21883

def connect_wlan():
    # Connecting to the group WLAN
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    nets = wlan.scan()               # returns list of tuples
    print("Nearby SSIDs:")
    for net in nets:
        ssid = net[0].decode()
        print("  ", ssid)
    
    wlan.connect(SSID, PASSWORD)
    print(wlan)

    # Attempt to connect once per second
    while wlan.isconnected() == False:
        print("Connecting... ")
        time.sleep(1)

    # Print the IP address of the Pico
    print("Connection successful. Pico IP:", wlan.ifconfig()[0])
    
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
        if time.ticks_diff(ms, self.time) > 200: ## minimum time between button signals to prevent bounceback signals 
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
        self.intervals = [] #temp list for live screen data
        self.total_intervals = [] #full list for variability calc
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
            
    def analyze_peaks(self, point):
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
                #ppi = interval*sample_interval #
                #minutes = (interval*sample_interval/1000)/60 # 4 is the ammount of ms pass for every point retrieved and the division of 1000 is ms to seconds  # Seconds
                #bpm = 1/minutes
                
                self.intervals.append(interval)
                self.total_intervals.append(interval)
                                
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
        
    def analyze_variability(self):
        self.total_intervals = [i for i in self.total_intervals if 75 < i < 375]
        
        if len(self.total_intervals) < 1:
            return True
        
        mean_ppi = (sum(self.total_intervals) * 4) / len(self.total_intervals)
        #mean_ppi = sample_interval / (sum(self.total_intervals) / len(self.total_intervals)) ## one minute in ms divided by the average ppi

        mean_hr = (60 * 1000) / sample_interval / (sum(self.total_intervals) / len(self.total_intervals)) ## one minute in ms divided by the average ppi

        #mean_hr = 0
        #for interval in self.total_intervals:
        #    mean_hr += (interval*4)/1000/60
        #mean_hr /= len(self.total_intervals)
        #mean_hr = sum(self.total_intervals) * 4 / 1000 / 60 / len(self.total_intervals)
        
        sdnn = 0 ##standard deviation of peak to peak interval length
        for interval in self.total_intervals:
            sdnn += (interval-mean_ppi)**2
        sdnn /= len(self.total_intervals)-1
        sdnn **= (1/2)
        
        rmssd = 0 #root mean square of successive differences of peak to 
        for i in range(len(self.total_intervals)-1):
            rmssd += (self.total_intervals[i+1]-self.total_intervals[i])**2
            
        rmssd /= len(self.total_intervals)-1
        
        rmssd **= (1/2)
        
        timestamp = time.localtime()
        
        self.analysis_results = {
            "id": time.time(),
            "timestamp": f"{timestamp[2]}.{timestamp[1]}.{timestamp[0]} {timestamp[3]}.{timestamp[4]}",
            "mean_ppi": int(mean_ppi),
            "mean_hr" : int(mean_hr),
            "sdnn" : int(sdnn),
            "rmssd" : int(rmssd)
        }
        print(self.analysis_results)
        try:
            mqtt_client=self.connect_mqtt()

        except Exception as e:
            print(f"Failed to connect to MQTT: {e}")

        try:
            # Sending a message every 5 seconds.
            topic = "hr-data"
            message = json.dumps(self.analysis_results)
            mqtt_client.publish(topic, message)
            print(f"Sending to MQTT: {topic} -> {message}")
            
        except Exception as e:
            print(f"Failed to send MQTT message: {e}")
        self.analysis_results["type"] = "local"
        
        #print(self.analysis_results["timestamp"])
    def kubios_analysis(self):
        self.total_intervals = [int(value*4) for value in self.total_intervals if 75 < value < 375]
        if len(self.total_intervals) < 10:
            return True
        print(self.total_intervals)

        kubios_request_id = time.time()
        
        self.kubios_analysis_results ={
            "id": kubios_request_id,
            "type" : "PPI",
            "data" : self.total_intervals,
            "analysis": {"type": "readiness"}
        }
        
        try:
            mqtt_client=self.connect_mqtt()

        except Exception as e:
            print(f"Failed to connect to MQTT: {e}")

        try:
            # Sending a message every 5 seconds.
            topic = "kubios-request"
            message = json.dumps(self.kubios_analysis_results)
            mqtt_client.publish(topic, message)
            received_kubios_message = ""
            print(f"Sending to MQTT: {topic} -> {message}")
            self.analysis_results = {}
            while not len(self.analysis_results):
                mqtt_client.check_msg()
                time.sleep_ms(25)
            self.analysis_results["type"] = "kubios"
            mqtt_client.publish("hr-data", json.dumps(self.analysis_results))
                
        except Exception as e:
            print(f"Failed to send MQTT message: {e}")
            
            
        mean_ppi = (sum(self.total_intervals) * 4) / len(self.total_intervals)
        

    def connect_mqtt(self):
        mqtt_client=MQTTClient("1", BROKER_IP, port=BROKER_PORT)
        mqtt_client.set_callback(self.message_callback)
        mqtt_client.connect(clean_session=True)
        mqtt_client.subscribe("kubios-response")
        return mqtt_client
    
    def message_callback(self, topic, msg):
        print("Received message on topic:", topic.decode())
        print("Message:", msg.decode())
        payload = json.loads(msg.decode())
        
        if not payload:
            return
        

        payload = json.loads(msg.decode())    # if msg is bytes

        # 2) Extract the top‐level id
        analysis_id = payload.get("id")

        # 3) Drill into the nested analysis object
        analysis = payload.get("data", {}) \
                          .get("analysis", {})
        
        timestamp = time.localtime()
        
        self.analysis_results = {
            "id": payload.get("id"),
            "timestamp": f"{timestamp[2]}.{timestamp[1]}.{timestamp[0]} {timestamp[3]}.{timestamp[4]}",
            #"timestamp": analysis.get("create_timestamp"),
            "mean_hr" : analysis.get("mean_hr_bpm"),
            "mean_ppi": analysis.get("mean_rr_ms"),
            "rmssd" : analysis.get("rmssd_ms"),
            "sdnn" : analysis.get("sdnn_ms"),
            "sns" : analysis.get("sns_index"),
            "pns" : analysis.get("pns_index")
        }
        
        
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
        self.history = []
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
        self.screen = self.next_screen
        oled.fill(0)
        
    def menu_setup(self):
        self.cursor.cap = (0, 3)
        self.screen = self.menu
        
    def menu(self):
        oled.fill(0)
        oled.text("1.Heart rate", 0, 0, 1)
        oled.text("2.HRV analysis", 0, 10, 1)
        oled.text("3.Kubios cloud", 0, 20, 1)
        oled.text("4.History", 0, 30, 1)
        oled.rect(0, self.cursor.position*10, 12, 8, 0, True)
        oled.text("->", 0, self.cursor.position*10, 1)
        
        #print(self.pulse_sensor.read_u16())
        

        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            print(f"{self.cursor.position}")
            if self.cursor.position == 0:
                self.screen = self.heart_rate_start_screen
            if self.cursor.position == 1:
                self.screen = self.analysis_start_screen
            if self.cursor.position == 2:
                self.screen = self.kubios_start_screen
            if self.cursor.position == 3:
                self.screen = self.history_setup
            self.reset()
        
    def heart_rate_start_screen(self):
        oled.text("Start measurment", 0, 10, 1)
        oled.text("by pressing the ", 0, 20, 1)
        oled.text("rotary button", 0, 30, 1)
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.next_screen = self.heart_rate_screen
            self.screen = self.sensor_setup
        
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
        self.screen = self.menu_setup

    def analysis_start_screen(self):
        oled.text("Start measurment", 0, 10, 1)
        oled.text("by pressing the ", 0, 20, 1)
        oled.text("rotary button", 0, 30, 1)
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.next_screen = self.analysis_setup
            self.screen = self.sensor_setup
            
    def analysis_setup(self):
        self.time = time.ticks_ms()
        self.screen = self.analysis_screen
        
    def analysis_screen(self):
        while self.sensor.fifo.has_data():
            point = self.sensor.fifo.get()
            self.hrv.calculate_threshold(point)
            self.hrv.analyze_peaks(point)
            # Display
            oled.rect(102,0, 28, 20, 0, 1)
                #Scrolling graph
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
                
                #text
            oled.text(f"{int(self.hrv.bpm_output)}",102,0,1)
            oled.text("Collecting data",5,50,1)
            
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.screen = self.heart_rate_screen_return
        
        ms = time.ticks_ms()
        if time.ticks_diff(ms, self.time) > 7000:
            self.screen = self.analysis_result_setup
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.sensor.timer_end()
            self.screen = self.menu_setup
    
    def analysis_result_setup(self):
        self.sensor.timer_end()
        if self.hrv.analyze_variability():
            self.screen = self.measurement_error
            return
        self.history.append(self.hrv.analysis_results)
        self.screen = self.analysis_result
    
    def analysis_result(self):
        oled.fill(0)
        oled.text(f"mean ppi: {self.hrv.analysis_results["mean_ppi"]:.2f}",2,0,1)
        oled.text(f"mean hr: {self.hrv.analysis_results["mean_hr"]:.2f}",2,10,1)
        oled.text(f"RMSSD: {self.hrv.analysis_results["rmssd"]:.2f}",2,20,1)
        oled.text(f"SDNN: {self.hrv.analysis_results["sdnn"]}",2,30,1)
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.screen = self.menu_setup

    def kubios_start_screen(self):
        oled.text("Start measurment", 0, 10, 1)
        oled.text("by pressing the ", 0, 20, 1)
        oled.text("rotary button", 0, 30, 1)
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.next_screen = self.kubios_setup
            self.screen = self.sensor_setup
            
    def kubios_setup(self):
        self.time = time.ticks_ms()
        self.screen = self.kubios_screen
        
    def kubios_screen(self):
        while self.sensor.fifo.has_data():
            point = self.sensor.fifo.get()
            self.hrv.calculate_threshold(point)
            self.hrv.analyze_peaks(point)
            # Display
            oled.rect(102,0, 28, 20, 0, 1)
                #Scrolling graph
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
                
                #text
            oled.text(f"{int(self.hrv.bpm_output)}",102,0,1)
            oled.text("Collecting data",5,50,1)
            
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.screen = self.heart_rate_screen_return
        
        ms = time.ticks_ms()
        if time.ticks_diff(ms, self.time) >30000:
            self.screen = self.kubios_result_setup
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.sensor.timer_end()
            self.screen = self.menu_setup

    def kubios_result_setup(self):
        self.sensor.timer_end()
        if self.hrv.kubios_analysis():
            self.screen = self.measurement_error
            return
        print(self.hrv.analysis_results)
        self.history.append(self.hrv.analysis_results)
        self.screen = self.kubios_result
    
    def kubios_result(self):
        oled.fill(0)
        oled.text(f"mean ppi: {int(self.hrv.analysis_results["mean_ppi"])}",2,0,1)
        oled.text(f"mean hr: {int(self.hrv.analysis_results["mean_hr"])}",2,10,1)
        oled.text(f"RMSSD: {int(self.hrv.analysis_results["rmssd"])}",2,20,1)
        oled.text(f"SDNN: {int(self.hrv.analysis_results["sdnn"])}",2,30,1)
        oled.text(f"SNS: {self.hrv.analysis_results["sns"]:.2f}",2,40,1)
        oled.text(f"PNS: {self.hrv.analysis_results["pns"]:.2f}",2,50,1)
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.screen = self.menu_setup

    def history_setup(self):
        self.cursor.cap = (0, len(self.history))
        self.screen = self.history_list
    def history_list(self):
        oled.fill(0)
        oled.text("  return", 0, 0, 1)
        for i in range(len(self.history)):
            oled.text(f"{i+1}.Analysis", 0, 10*(i+1), 1)
        
        oled.rect(0, self.cursor.position*10, 12, 8, 0, True)
        oled.text("->", 0, self.cursor.position*10, 1)
        print(self.cursor.position)
        self.analysis_selected = self.cursor.position-1
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            if self.analysis_selected == -1:
                self.screen = self.menu_setup
            else:
                self.screen = self.history_result

    def history_result(self):
        oled.fill(0)
        selected = self.history[self.analysis_selected]
        print(self.history[self.analysis_selected])
        oled.text(f"mean ppi: {int(selected["mean_ppi"])}",2,8,1)
        oled.text(f"mean hr: {int(selected["mean_hr"])}",2,16,1)
        oled.text(f"RMSSD: {int(selected["rmssd"])}",2,24,1)
        oled.text(f"SDNN: {int(selected["sdnn"])}",2,32,1)
        if selected["type"] == "kubios":
            oled.text(f"SNS: {selected["sns"]:<.2f}",2,40,1)
            oled.text(f"PNS: {selected["pns"]:.2f}",2,48,1)
            
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.screen = self.menu_setup
            
    def measurement_error(self):
        self.sensor.timer_end()
        oled.fill(0)
        oled.text("Measurement", 0, 10, 1)
        oled.text("error. ", 0, 20, 1)
        oled.text("Press the", 0, 30, 1)
        oled.text("rotary button", 0, 40, 1)
        
        while self.rot.btn_fifo.has_data():
            self.rot.btn_fifo.get()
            self.screen = self.menu_setup
            self.sensor.timer_end()

connect_wlan()
rot = Encoder(10, 11, 12)
ui = UI(rot, 27, 9, 7)
while True:
    ui.display()

