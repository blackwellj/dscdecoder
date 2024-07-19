import sys
import time
import pyaudio
import numpy as np
import json

############################################################################################################################################
# Configuration

SAMPLE_RATE = 44100          # Sample rate of soundcard
CENTER_FREQUENCY = 1700      # 1700 for VHF, center frequency for MF - HF (for example 800 or 1000)
SHIFT_FREQUENCY = 800        # 800 for VHF
BIT_RATE = 1200.0            # Bitrate 1200 for VHF

############################################################################################################################################
# Global Variables
AUDIO_SIGNAL = []           # Audio trace channel 1

RUN_STATUS = 1              # 0 stopped, 1 start, 2 running, 3 stop now, 4 stop and restart
RX_BUFFER = 0.0             # Data contained in input buffer in %
NEXT_BIT_TIME = 0.0         # The next bit sample time moment in samples
YBY_TIMES = [0.0, 1.0, 2.0, 3.0]  # Zero crossing times
YBY_VALUES = [1.0, 1.0]     # Sample values for zero crossings
YBY_STATES = ["P", "N"]     # Sample states for positive/negative period
STR_YBY = ""                # The YBY string from the YBY decoding process
MSG_DATA = []               # The message data
EXP_MSG_DATA = []           # Extension message data
MSG = 0                     # Start of message position
MSG_STATUS = 0              # 0=Search Phasing; 1=Decode Data; 2=Decode to Message; 3=Error in Message decoding

############################################################################################################################################
# Initialize PyAudio
PA = pyaudio.PyAudio()
FORMAT = pyaudio.paInt16

# =============== The Main Loop =====================
def main_loop():
    global MSG_DATA
    while True:
        make_yby()          # Decode audio data in AUDIO_SIGNAL to YBY
        find_phasing()      # Search for the phasing signal and the start of a message
        make_data()         # Create data and call message decoders
        print(MSG_DATA)        
        if MSG_STATUS == 2:
            json_message = decode_dsc_message(MSG_DATA)
            print(json_message)

# ======================= Read audio from stdin ==================================
def audio_in():
    global AUDIO_SIGNAL, RUN_STATUS, SAMPLE_RATE

    if RUN_STATUS == 1:
        AUDIO_SIGNAL = []
        chunkbuffer = SAMPLE_RATE * 4  # Fixed at xx seconds
        readsamples = SAMPLE_RATE      # Samples to read
        RUN_STATUS = 2
        print(f"Reading audio from stdin\nSample rate: {SAMPLE_RATE} samples/s")

    if RUN_STATUS == 2:
        try:
            signals = sys.stdin.buffer.read(SAMPLE_RATE * 2)  # 2 bytes per sample
            if signals:
                AUDIO_SIGNAL.extend(np.frombuffer(signals, np.int16))
            else:
                RUN_STATUS = 4
                print("No audio data received from stdin")
        except IOError:
            pass  # Ignore IOError if no data available
        except Exception as e:
            RUN_STATUS = 4
            print(f"Audio buffer reset! Error: {e}")

    if RUN_STATUS in [3, 4]:
        PA.terminate()
        print("Audio Stream stopped!")
        RUN_STATUS = 1 if RUN_STATUS == 4 else 0
        AUDIO_SIGNAL = []  # Clear audio buffer

# ============= Convert AUDIO_SIGNAL audio data to STR_YBY =======================
def make_yby():
    global STR_YBY, AUDIO_SIGNAL, NEXT_BIT_TIME, YBY_TIMES, YBY_VALUES, YBY_STATES
    low_frequency = CENTER_FREQUENCY - SHIFT_FREQUENCY / 2.0
    high_frequency = CENTER_FREQUENCY + SHIFT_FREQUENCY / 2.0
    low_samples = SAMPLE_RATE / low_frequency
    high_samples = SAMPLE_RATE / high_frequency
    decision = high_samples + (low_samples - high_samples) / 4.25
    bit_time_step = SAMPLE_RATE / BIT_RATE

    add_yby = 0
    i = 0
    while add_yby < 50:
        while len(AUDIO_SIGNAL) <= i:
            audio_in()

        v = AUDIO_SIGNAL[i]
        current_sample = "P" if v >= 0 else "N"

        if current_sample != YBY_STATES[0]:  # A zero crossing
            YBY_STATES[0] = current_sample
            YBY_VALUES[1] = abs(v)
            y = YBY_VALUES[1] / (YBY_VALUES[0] + YBY_VALUES[1])

            YBY_TIMES = YBY_TIMES[1:] + [i - y]

            if (YBY_TIMES[2] - YBY_TIMES[0]) >= decision and (YBY_TIMES[3] - YBY_TIMES[1]) < decision:
                if (NEXT_BIT_TIME - YBY_TIMES[1]) < bit_time_step / 2.0:
                    NEXT_BIT_TIME += bit_time_step * 0.025
                else:
                    NEXT_BIT_TIME -= bit_time_step * 0.025

            while NEXT_BIT_TIME < YBY_TIMES[2]:
                add_yby += 1
                NEXT_BIT_TIME += bit_time_step
                STR_YBY += "B" if (YBY_TIMES[2] - YBY_TIMES[0]) < decision or (YBY_TIMES[3] - YBY_TIMES[1]) < decision else "Y"

        YBY_VALUES[0] = abs(v)

        if i > (NEXT_BIT_TIME + 2 * bit_time_step):
            add_yby += 1
            NEXT_BIT_TIME = i + bit_time_step
            STR_YBY += "Y"
            YBY_TIMES = [i - bit_time_step * x for x in range(4)]

        i += 1

    AUDIO_SIGNAL = AUDIO_SIGNAL[i:]  # Delete used samples
    NEXT_BIT_TIME -= i
    YBY_TIMES = [x - i for x in YBY_TIMES]
    print(f"make_yby() called, STR_YBY extended: {STR_YBY}")
    

# ================== Start Decoding routines =====================================================
# ============= Find the phasing signal and the start of the message MSG =======================
def find_phasing():          
    
    global STR_YBY
    global MSG                              # Start of message in STR_YBY
    global RUN_STATUS

    if RUN_STATUS != 0 and RUN_STATUS != 3:   # Exit if MSGstatus not 0 or 3 (not necessary)
        return()

    # ... Find Phasing ...

    MinBits = 50                            # The minimum of bits in the YBY string (> 20)
    Starti = 100                            # Start to search from this pointer, so that the data before this pointer can also be read
        
    if RUN_STATUS == 3:                      # Start of new search, skip the old part upto the format specifier
        STR_YBY = STR_YBY[(MSG+120-Starti):]  # Ready for next search of phasing signal
        RUN_STATUS = 0                       # And set the status to search

    while len(STR_YBY) < (Starti+MinBits+21): # If STR_YBY is too short, call MakeYBY
        make_yby()
      
    se1 = ten_unit(108) + ten_unit(125)       # Define search string 1 for phasing
    se2 = ten_unit(107) + ten_unit(125)       # Define search string 2 for phasing

    i = Starti
    L = len(STR_YBY)
    while i < (L - MinBits):
        if STR_YBY[i:(i+20)] == se1:
            MSG = i - 70
            RUN_STATUS = 1
            break

        if STR_YBY[i:(i+20)] == se2:
            MSG = i - 90
            RUN_STATUS = 1
            break

        i = i + 1

    if RUN_STATUS == 0:
        STR_YBY= STR_YBY[(L - MinBits - Starti):]
        return()

# ============= MAKEdata, set the data into MSG_DATA =======================
def make_data():
    global MSG_DATA, EXP_MSG_DATA, MSG, MSG_STATUS

    if MSG_STATUS != 1:
        return

    fs1 = get_val_symbol(13)
    if fs1 < 100:
        fs1 = get_val_symbol(18)
    fs2 = get_val_symbol(15)
    if fs2 < 100:
        fs2 = get_val_symbol(20)
    
    if fs1 != fs2:
        MSG_STATUS = 3
        print("Format specifiers not identical")
        return

    msg_data = [fs1]
    l3b_error = False
    v_previous = -1
    i = 17

    while True:
        v = get_val_symbol(i)
        if v < 0:
            v = get_val_symbol(i + 5)
        if v >= 0:
            msg_data.append(v)
        else:
            l3b_error = True
            break

        if v_previous in [117, 122, 127]:
            break
        v_previous = v
        i += 2

    start_exp_msg = i + 6
    if l3b_error:
        print("Error Character Check 3 last bits (2x)")
        MSG_STATUS = 3
        return

    ecc = msg_data[0]
    for symbol in msg_data[1:-1]:
        ecc ^= symbol

    if msg_data[-1] != ecc:
        print("Data does not match with Error Check Character")
        MSG_STATUS = 3
        return

    MSG_DATA = msg_data
    MSG_STATUS = 2

    v = get_val_symbol(start_exp_msg)
    if not (100 <= v <= 106):
        EXP_MSG_DATA = []
        return

    exp_msg_data = []
    l3b_error = False
    v_previous = -1
    i = start_exp_msg

    while True:
        v = get_val_symbol(i)
        if v < 0:
            v = get_val_symbol(i + 5)
        if v >= 0:
            exp_msg_data.append(v)
        else:
            l3b_error = True
            break

        if v_previous in [117, 122, 127]:
            break
        v_previous = v
        i += 2

    if l3b_error:
        print("Error in Extended Data, 3 last bits")
        EXP_MSG_DATA = []
        return

    ecc = exp_msg_data[0]
    for symbol in exp_msg_data[1:-1]:
        ecc ^= symbol

    if exp_msg_data[-1] != ecc:
        print("Error Check Character in Extended Data does not match")
        EXP_MSG_DATA = []
        return

    EXP_MSG_DATA = exp_msg_data

# ======================= Decode the DSC MSG_DATA to a JSON message =======================
def decode_dsc_message(dsc_array):
    if len(dsc_array) < 22:
        raise ValueError("Array does not contain enough elements to decode a DSC message.")
    
    mmsi = ''.join([str(x) for x in dsc_array[0:9]])
    
    category_code = dsc_array[9]
    category_map = {
        100: "Routine",
        108: "Safety",
        110: "Urgency",
        112: "Distress"
    }
    category = category_map.get(category_code, "Unknown")
    
    # Decode nature of distress if category is Distress
    nature_of_distress = None
    if category == "Distress":
        nature_of_distress = dsc_array[10]
        nature_of_distress_map = {
            100: "Undesignated",
            101: "Fire, explosion",
            102: "Flooding",
            103: "Collision",
            104: "Grounding",
            105: "Listing, in danger of capsizing",
            106: "Sinking",
            107: "Disabled and adrift",
            108: "Abandoning ship",
            109: "Man overboard",
            110: "Piracy/armed attack",
            112: "Medical assistance"
        }
        nature_of_distress = nature_of_distress_map.get(nature_of_distress, "Unknown")
    
    # Decode Latitude
    lat_deg = dsc_array[11]
    lat_min = dsc_array[12]
    lat_dir = 'N' if dsc_array[13] <= 89 else 'S'
    latitude = f"{lat_deg}°{lat_min}'{lat_dir}"
    
    # Decode Longitude
    lon_deg = dsc_array[14]
    lon_min = dsc_array[15]
    lon_dir = 'E' if dsc_array[16] <= 179 else 'W'
    longitude = f"{lon_deg}°{lon_min}'{lon_dir}"
    
    # UT Time
    utc_hour = dsc_array[17]
    utc_minute = dsc_array[18]
    utc_time = f"{utc_hour:02}:{utc_minute:02}"
    
    # Additional Data (example, EOS, VHF channels etc.)
    eos = dsc_array[19]
    vhf_rx_channel = dsc_array[20]
    vhf_tx_channel = dsc_array[21]
    
    message = {
        "MMSI": mmsi,
        "Category": category,
        "Latitude": latitude,
        "Longitude": longitude,
        "UTC Time": utc_time,
        "EOS": eos,
        "VHF RX Channel": vhf_rx_channel,
        "VHF TX Channel": vhf_tx_channel
    }
    
    if nature_of_distress:
        message["Nature of Distress"] = nature_of_distress
    
    return json.dumps(message, indent=4)

# ========== Helper functions for decoding =================================
def get_val_symbol(pos):
    global STR_YBY
    try:
        return symbol_val(STR_YBY[pos:(pos + 10)])
    except IndexError:
        return -1

def symbol_val(x):
    if len(x) < 10:
        return -1
    bits = [1 if c == 'Y' else 0 for c in x]
    vals = [64, 32, 16, 8, 4, 2, 1]
    return sum([b * v for b, v in zip(bits[1:], vals)]) if bits[0] else -1

def ten_unit(Vin):
    if (Vin > 127):
         return("ERROR ten_unit > 127") # ERROR
    
    intB = 0
    intY = 1
    Vout = ""
    
    n = 0
    while (n < 7):                     # Calculate the first 7 bits, msb(Y=1) first
        if (int(Vin) & int(intY)) != 0:
            Vout = Vout + "Y"
        else:
            Vout = Vout + "B"            
            intB = intB + 1            #Counts the number of B's (B=0)
       
        intY = intY * 2
        n = n + 1
        
    intY = 4
    n = 0
    while (n < 3):                     # Calculate the last 3 bits from intB (the number of "B"s), Msb(Y=1) first
        if (int(intB) & int(intY)) != 0:
            Vout = Vout + "Y"
        else:
            Vout = Vout + "B"            

        intY = intY / 2
        n = n + 1
    
    return(Vout)
# ========== Start the main loop =====================
main_loop()
