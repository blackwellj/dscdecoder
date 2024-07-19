# ATISrx-v05b.py (11-01-2024)
# pa2ohh

import math
import wave
import sys
import struct
import time
import pyaudio
import os
import numpy as np
import fcntl
import threading
import fileinput


from tkinter import *
from tkinter import messagebox
from tkinter import filedialog
from tkinter import simpledialog
from tkinter import font


############################################################################################################################################
# Configuration

DEBUG = True               # If True, print debug information. Can also be activated with the "Test" button
AUTOscroll = True           # Auto scroll text boxes to last messages
SAMPLErate = 44100          # Sample rate of soundcard
CENTERfrequency = 1700      # 1700 for VHF, center frequency for MF - HF (for example 800 or 1000)
SHIFTfrequency = 800        # 800 for VHF
BITrate = 1200.0            # Bitrate 1200 for VHF


chunkbuffer = 0
signals = None

############################################################################################################################################
# Initialisation of global variables required in various routines (DO NOT MODIFY THEM!)

CC = []                     # Country Code list
AUDIOsignal1 = []           # Audio trace channel 1

RUNstatus = 0               # 0 stopped, 1 start, 2 running, 3 stop now, 4 stop and restart
RXbuffer = 0.0              # Data contained in input buffer in %

NextBitTime = float(0)      # The next bit sample time moment in samples
YBYt1 = float(0)            # The four zero crossings, time in fractional audio samples
YBYt2 = float(1)
YBYt3 = float(2)
YBYt4 = float(3)

YBYv1 = float(1)            # The value of the previous sample
YBYv2 = float(1)            # The value of the next sample

YBYprsample = "P"           # the previous audio sample is positive part of period
YBYcusample = "N"           # current sample is negative 

strYBY = ""                 # the YBY string from the YBY decoding process
MSGdata = []                # The message data
EXPMSGdata = []             # Extension message data
MSG = 0                     # Start of message position
MSGstatus = 0               # 0=Search Phasing;
                            # 1=Decode Data;
                            # 2=Decode data to Message;
                            # 3=Error in Message decoding, continue with next Phasing search

HLINE = "------------------------------------------------"

############################################################################################################################################

# =============== The Mainloop =====================
def MAINloop():             # The Mainloop
    global AUDIOsignal1
    global SAMPLErate
    global RUNstatus

    while(True): 
        MakeYBY()           # Decode audio data in AUDIOsignal1[] to YBY...
        FINDphasing()       # Search for the phasing signal and the start of a message
        MAKEdata()          # Make the data and call the message decoders
        SELECTdecoder()     # Select and call the decoder depending on the format specifier

# Initialize PyAudio
PA = pyaudio.PyAudio()
FORMAT = pyaudio.paInt16
TRACESopened = 1



# ======================= Read audio from stdin ==================================
def AUDIOin():   # Read the audio from stdin and store the data into the arrays
    global DEBUG
    global AUDIOsignal1
    global RUNstatus
    global SAMPLErate
    global RXbuffer
    global signals, readsamples

    RUNstatus = 1

    # RUNstatus == 1: Initializing the input stream from stdin
    if RUNstatus == 1:
        print(RUNstatus)
        TRACESopened = 1
        AUDIOsignal1 = []

        try:
            chunkbuffer = int(SAMPLErate * 4)  # Fixed at xx seconds
            readsamples = SAMPLErate           # Samples to read

            RUNstatus = 2

            PrintInfo("Reading audio from stdin")
            txt = "Sample rate: " + str(SAMPLErate) + " samples/s"
            PrintInfo(txt)
        except Exception as e:
            RUNstatus = 0
       
            PrintInfo("Cannot open Audio Stream")
            txt = f"Error: {str(e)}"
            messagebox.showerror("Cannot open Audio Stream", txt)

    if RUNstatus == 2:
        print(RUNstatus)
        try:
            # Read samples from stdin
            #signals = fileinput.input()
            signals = sys.stdin.buffer.read(readsamples * 2)  # 2 bytes per sample

            print(signals)

            if signals:
                AUDIOsignal1.extend(np.frombuffer(signals, np.int16))

                if DEBUG:
                    txt = f"Audio buffer: Level (-32000 to +32000): {np.amin(AUDIOsignal1)} to {np.amax(AUDIOsignal1)}"
                    PrintInfo(txt)
            else:
                RUNstatus = 4
                PrintInfo("No audio data received from stdin")
        except IOError:
            pass  # Ignore the IOError exception that arises when no data is available
        except Exception as e:
            RUNstatus = 4
            PrintInfo(f"Audio buffer reset! Error: {str(e)}")


    # RUNstatus == 3: Stop; RUNstatus == 4: Stop and restart
    if RUNstatus == 3 or RUNstatus == 4:
        print(RUNstatus)
        PA.terminate()
        PrintInfo("Audio Stream stopped!")
        if RUNstatus == 3:
            RUNstatus = 0  # Status is stopped
        if RUNstatus == 4:
            RUNstatus = 1  # Status is (re)start

        AUDIOsignal1 = []  # Clear audio buffer

    root.update_idletasks()
    root.update()

# ============= Convert AUDIOsignal1[] audio data to strYBY =======================
def MakeYBY():              # Read the audio and make strYBY
    global RUNstatus
    global strYBY
    global AUDIOsignal1
    global SAMPLErate
    global SAMPLEoffset
    global NextBitTime      # The next bit sample time moment in samples
    global YBYt1            # The four zero crossings, time in fractional audio samples
    global YBYt2
    global YBYt3
    global YBYt4
    global YBYv1            # The value of the sample before the zero crossing
    global YBYv2            # The value of the sample after the zero crossing
    global YBYprsample      # The previous audio sample is positive "P" or negative "N"
    global YBYcusample      # The current audio sample is positive "P" or negative "N"
    global CENTERfrequency
    global SHIFTfrequency
    global BITrate

    lowfrequency = CENTERfrequency - SHIFTfrequency / 2.0               # low shift
    highfrequency = CENTERfrequency + SHIFTfrequency / 2.0              # high shift

    lowsamples = float(SAMPLErate) / lowfrequency                       # number of audio samples low frequency period
    highsamples = float(SAMPLErate) / highfrequency                     # number of audio samples high frequency period
    Decision = float(highsamples + (lowsamples - highsamples) / 4.25)   # below this value a high tone 6.0 and 3.0 were okay, 6.5 and 2.5 not

    BitTimeStep = float(SAMPLErate) / BITrate   # The step in samples 

    AddYBY = 0                                  # Counts the number of YBY's that have been added
    i = 0
    while AddYBY < 50:                          # Add maximal xx YBY's
        while len(AUDIOsignal1) <= i:           # If buffer too small, call the audio read routine
            AUDIOin()
            
        v = AUDIOsignal1[i]
        # v = AUDIOsignal1[i] + OFFSET
        if (v >= 0):
            YBYcusample = "P"
        else:
            YBYcusample = "N"

        if (YBYcusample != YBYprsample):        # A zero crossing
            YBYprsample = YBYcusample
            YBYv2 = float(abs(v))
            y = YBYv2 / (YBYv1 + YBYv2)         # Fraction of fractional sample

            YBYt1 = YBYt2
            YBYt2 = YBYt3
            YBYt3 = YBYt4
            YBYt4 = float(i) - y                # Fractional sample

            if (YBYt3-YBYt1) >= Decision and (YBYt4-YBYt2) < Decision:      # Synchronisation 
                if (NextBitTime-YBYt2) < BitTimeStep / 2.0:                 # Should be 2.0, min 1.4 max 2.5 so correct
                    NextBitTime = NextBitTime + BitTimeStep * 0.025
                else:
                    NextBitTime = NextBitTime - BitTimeStep * 0.025

            while NextBitTime < YBYt3:
                AddYBY = AddYBY + 1
                NextBitTime = NextBitTime + BitTimeStep
                if (YBYt3-YBYt1) < Decision or (YBYt4-YBYt2) < Decision:
                    strYBY = strYBY + "B"                                   # Add "B" for 0 for high tone
                else:
                    strYBY = strYBY + "Y"                                   # Add "Y" for 1 for low tone

        YBYv1 = abs(float(v))                                               # store in previous memory for fractional calculation of zero crossing

        if i > (NextBitTime + 2*BitTimeStep):                               # If no signal, add "Y"
            AddYBY = AddYBY + 1
            NextBitTime = float(i) + BitTimeStep
            strYBY = strYBY + "Y"
            YBYt4 = float(i)
            YBYt3 = YBYt4 - BitTimeStep
            YBYt2 = YBYt3 - BitTimeStep
            YBYt1 = YBYt2 - BitTimeStep

        i = i + 1

    AUDIOsignal1 = AUDIOsignal1[i:]             # Delete the used samples
    NextBitTime = NextBitTime - float(i)        # The next bit sample time moment in samples set to the begin of the next decoding
    YBYt4 = YBYt4 - float(i)
    YBYt3 = YBYt3 - float(i)
    YBYt2 = YBYt2 - float(i)
    YBYt1 = YBYt1 - float(i)
    
    
# ================== Start Decoding routines =====================================================
# ============= Find the phasing signal and the start of the message MSG =======================
def FINDphasing():          
    global DEBUG
    global strYBY
    global MSG                              # Start of message in strYBY
    global MSGstatus

    if MSGstatus != 0 and MSGstatus != 3:   # Exit if MSGstatus not 0 or 3 (not necessary)
        return()

    # ... Find Phasing ...

    MinBits = 50                            # The minimum of bits in the YBY string (> 20)
    Starti = 100                            # Start to search from this pointer, so that the data before this pointer can also be read
        
    if MSGstatus == 3:                      # Start of new search, skip the old part upto the format specifier
        strYBY = strYBY[(MSG+120-Starti):]  # Ready for next search of phasing signal
        MSGstatus = 0                       # And set the status to search

    while len(strYBY) < (Starti+MinBits+21): # If strYBY is too short, call MakeYBY
        MakeYBY()
      
    se1 = TENunit(108) + TENunit(125)       # Define search string 1 for phasing
    se2 = TENunit(107) + TENunit(125)       # Define search string 2 for phasing

    i = Starti
    L = len(strYBY)
    while i < (L - MinBits):
        if strYBY[i:(i+20)] == se1:
            MSG = i - 70
            MSGstatus = 1
            break

        if strYBY[i:(i+20)] == se2:
            MSG = i - 90
            MSGstatus = 1
            break

        i = i + 1

    if MSGstatus == 0:
        strYBY= strYBY[(L - MinBits - Starti):]
        return()

    if DEBUG == True:
        PrintDSCresult("\n=== DEBUG DATA message ===")
        PrintDSCresult("Message found at " + str(MSG))
  
        DATAerror = 0
        strDATA = ""
        i = 1
        while DATAerror < 5:
            strDATA = strDATA +"(" + str(GETvalsymbol(i)) +")"
            if i > 16:                                          # End of phasing and start of data
                if GETvalsymbol(i) < 0:
                    DATAerror = DATAerror + 1
            i = i + 1

        PrintDSCresult(strDATA)
        PrintDSCresult(HLINE)

           
# ============= MAKEdata, set the data into MSGdata[]=======================
def MAKEdata():
    global DEBUG
    global strYBY
    global MSGdata
    global EXPMSGdata
    global MSG              # Start of message in strYBY
    global MSGstatus

    if MSGstatus != 1:      # Exit if MSGstatus not 1
        return()

    # ... Check if the double transmission of the format specifier is identical ...

    FS1 = -1                # The 1st format specifier
    FS2 = -1                # The 2nd format specifier

    FS1 = GETvalsymbol(13)
    if FS1 < 100:           # If incorrect error check bits (below -1) or not valid (below 100)
        FS1 = GETvalsymbol(18)

    FS2 = GETvalsymbol(15)
    if FS2 < 100:           # If incorrect error check bits (below -1) or not valid (below 100)
        FS2 = GETvalsymbol(20)
    
    if FS1 != FS2:
        MSGstatus = 3       # Initialize next search as both Format specifiers have to be identical
        if DEBUG == True:
            PrintInfo("Format specifiers not identical")
        return()

    # ... Make the message data and store in MSGdata ...
    Vprevious = -1
    L3Berror = False                    # True if the initial and retransmission do have a wrong 3 bits error check value
    MSGdata = []                        # Clear the data
    MSGdata.append(FS1)                 # Append the format specifier
    i = 17                              # The message starts at position 17
    while(1):                           # Loop until a break occurs
        V = GETvalsymbol(i)
        if V < 0:
            V = GETvalsymbol(i+5)       # If 3 bits error check value incorrect, take the RTX signal 5 symbols later
        if V >= 0:
            MSGdata.append(V)           # If the value has a correct CRC value, add it to the data
        else:
            L3Berror = True             # Both the initial and retransmission do have the wrong 3 bits error check value
            break
        if Vprevious == 117:            # EOS sign for Acknowledgement required, end of message
            break
        if Vprevious == 122:            # EOS sign for Acknowledgement given, end of message
            break
        if Vprevious == 127:            # EOS sign for Non acknowledgements, end of message
            break
        Vprevious = V                   # Store previous value
        
        i = i + 2

    STARTEXPMSG = i + 6                 # The possible start of the extension message

    if L3Berror == True:
        txt = time.strftime("<%Y%b%d-%H:%M:%S> ", time.gmtime())
        PrintInfo(txt + "Error Character Check 3 last bits (2x)")
        MSGstatus = 3                   # Initialize next search as there was an error that could not be corrected
        return()

    # ... Check errors with error check character ...
    ECC = MSGrdta(0) 
    i = 1
    while i < (len(MSGdata) - 1):
        ECC = ECC ^ MSGrdta(i)
        i = i + 1
    if MSGrdta(len(MSGdata)-1) != ECC:  # The last value in the array MSGdata is the Error check symbol
        txt = time.strftime("<%Y%b%d-%H:%M:%S> ", time.gmtime())
        PrintInfo(txt + "Data does not match with Error Check Character")
        MSGstatus = 3                   # Initialize next search as there was an error in the error check
        return()

    MSGstatus = 2                       # Status for decoding the data in MSGdata to a message
 
    # ... Search for extension message ...
    V = GETvalsymbol(STARTEXPMSG)

    NOEXPmessage = False                # True if no expansion message 
    
    if V < 100 or V > 106:              # Then no expansion message
        NOEXPmessage = True
        EXPMSGdata = []                 # Clear the EXPMSGdata[] array
        return()

    # ... Start to fill the EXPMSGdata ....
    Vprevious = -1
    EXPMSGdata = []                     # Clear the EXPMSGdata[] array
    L3Berror = False                    # True if the initial and retransmission do have a wrong 3 bits error check value
    i = STARTEXPMSG                     # The possible extension message starts at this position
    while(1):                           # Loop until a break occurs
        V = GETvalsymbol(i)
            
        if V < 0:
            V = GETvalsymbol(i+5)       # If 3 bits error check value incorrect, take the RTX signal 5 symbols later
           
        if V >= 0:
            EXPMSGdata.append(V)        # If the value has a correct CRC value, add it to the data
        else:
            L3Berror = True             # Both the initial and retransmission do have the wrong 3 bits error check value
            break

        if Vprevious == 117:            # EOS sign for Acknowledgement required, end of message
            break
        if Vprevious == 122:            # EOS sign for Acknowledgement given, end of message
            break
        if Vprevious == 127:            # EOS sign for Non acknowledgements, end of message
            break
        Vprevious = V                   # Store previous value
        
        i = i + 2
    
    if L3Berror == True:
        PrintInfo("Error expansion msg, Error Character Check 3 last bits (2x)")
        EXPMSGdata = []                 # Clear the EXPMSGdata
        return()

    # ... Check errors with error check character ...
    ECC = EXPMSGrdta(0) 
    i = 1
    while i < (len(EXPMSGdata) - 1):
        ECC = ECC ^ EXPMSGrdta(i)
        i = i + 1
    if EXPMSGrdta(len(EXPMSGdata)-1) != ECC:  # The last value in the array EXPMSGdata is the Error check symbol
        PrintInfo("Data expansion message does not match with Error Check Character")
        EXPMSGdata = []
        return()


# ============================ Select the decoder depending on the Format specifier ==============================
def SELECTdecoder():
    global DEBUG
    global MSGdata
    global MSG          # Start of message in strYBY
    global MSGstatus
    global EXPMSGdata

    if MSGstatus != 2:                  # Exit if MSGstatus not 2
        return()
    
    if MSGrdta(0) == 121:               # Format specifier 121 (ATIS)
        DEC121()
    
    if MSGrdta(0) == 102:               # Format specifier 102
        DEC102()

    if MSGrdta(0) == 112:               # Format specifier 112
        DEC112()

    if MSGrdta(0) == 114:               # Format specifier 114
        DEC114()

    if MSGrdta(0) == 116:               # Format specifier 116
        DEC116()

    if MSGrdta(0) == 120:               # Format specifier 120
        DEC120()

    if MSGrdta(0) == 123:               # Format specifier 123
        DEC123()

    if MSGstatus != 3:                  # The MSGstatus is not reset to 3, so no valid or supported format specifier
        PrintInfo("Error or no supported format specifier: " + str(MSGrdta(0)))

    if len(EXPMSGdata) != 0:            # Decode the extension message
        DSCExpansion821()
        
    MSGstatus = 3                       # Continue with the next search, messages have been decoded


# ============================ Decode format specifier 102 (Selective Geographic Area) ==============================
def DEC102():
    global DEBUG
    global MSGdata
    global MSG          # Start of message in strYBY
    global MSGstatus

    PrintDSCresult(HLINE)
    txt = time.strftime("<%Y%b%d-%H:%M:%S> ", time.gmtime())         # The time
    txt = txt + "Format specifier 102: Selective geographic area"
    PrintDSCresult(txt)

    DSC_ZONE(1)
    PrintDSCresult(DSC_CAT(MSGrdta(6)))
    PrintDSCresult("Self ID:")
    DSC_MMSI(7)
    PrintDSCresult(DSC_TC1(MSGrdta(12)))
    PrintDSCresult("Distress ID:")
    DSC_MMSI(13)
    PrintDSCresult(DSC_NOD(MSGrdta(18)))
    DSC_POS(19)
    DSC_UTC(24)
    PrintDSCresult(DSC_TC1(MSGrdta(26)))
    PrintDSCresult(DSC_EOS(MSGrdta(len(MSGdata)-2)))
     
    MSGstatus = 3       # Continue with the next search, messages have been decoded


# ============================ Decode format specifier 112 (Disstress) ==============================
def DEC112():
    global DEBUG
    global MSGdata
    global MSG          # Start of message in strYBY
    global MSGstatus
  
    PrintDSCresult(HLINE)
    txt = time.strftime("<%Y%b%d-%H:%M:%S> ", time.gmtime())         # The time
    txt = txt + "Format specifier 112: Distress"
    PrintDSCresult(txt)
    
    PrintDSCresult("Distress ID:")
    DSC_MMSI(1)
    PrintDSCresult(DSC_NOD(MSGrdta(6)))
    DSC_POS(7)
    DSC_UTC(12)
    PrintDSCresult(DSC_EOS(MSGrdta(len(MSGdata)-2)))
    
    MSGstatus = 3       # Continue with the next search, messages have been decoded


# ============================ Decode format specifier 114 (Selective Group Call) ==============================
def DEC114():
    global DEBUG
    global MSGdata
    global MSG          # Start of message in strYBY
    global MSGstatus
  
    PrintDSCresult(HLINE)
    txt = time.strftime("<%Y%b%d-%H:%M:%S> ", time.gmtime())         # The time
    txt = txt + "Format specifier 114: Selective group call"
    PrintDSCresult(txt)

    PrintDSCresult("Address:")
    DSC_MMSI(1)
    PrintDSCresult(DSC_CAT(MSGrdta(6)))
    PrintDSCresult("Self ID:")
    DSC_MMSI(7)
    PrintDSCresult(DSC_TC1(MSGrdta(12)))
    PrintDSCresult(DSC_TC2(MSGrdta(13)))
    PrintDSCresult("Called station receive frequency:")
    DSC_FREQ(14)
    PrintDSCresult("Called station transmit frequency:")
    DSC_FREQ(17)
    PrintDSCresult(DSC_EOS(MSGrdta(len(MSGdata)-2)))
    
    MSGstatus = 3       # Continue with the next search, messages have been decoded


# ============================ Decode format specifier 116 (All Ships Call) ==============================
def DEC116():
    global DEBUG
    global MSGdata
    global MSG          # Start of message in strYBY
    global MSGstatus
  
    PrintDSCresult(HLINE)
    txt = time.strftime("<%Y%b%d-%H:%M:%S> ", time.gmtime())         # The time
    txt = txt + "Format specifier 116: All ships call"
    PrintDSCresult(txt)

    PrintDSCresult(DSC_CAT(MSGrdta(1)))

    if MSGrdta(1) == 112:
        PrintDSCresult("Self ID:")
        DSC_MMSI(2)
        PrintDSCresult(DSC_TC1(MSGrdta(7)))
        PrintDSCresult("Distress ID:")
        DSC_MMSI(8)
        PrintDSCresult(DSC_NOD(MSGrdta(13)))
        DSC_POS(14)
        DSC_UTC(19)
        PrintDSCresult(DSC_TC1(MSGrdta(21)))

    if MSGrdta(1) == 108 or MSGrdta(1) == 110:
        PrintDSCresult("Self ID:")
        DSC_MMSI(2)
        PrintDSCresult(DSC_TC1(MSGrdta(7)))
        PrintDSCresult(DSC_TC2(MSGrdta(8)))
        PrintDSCresult("Called station receive frequency:")
        DSC_FREQ(9)
        PrintDSCresult("Called station transmit frequency:")
        DSC_FREQ(12)

    PrintDSCresult(DSC_EOS(MSGrdta(len(MSGdata)-2)))

    MSGstatus = 3       # Continue with the next search, messages have been decoded


# ============================ Decode format specifier 120 (Selective Individual Call) ==============================
def DEC120():
    global DEBUG
    global MSGdata
    global MSG          # Start of message in strYBY
    global MSGstatus
  
    PrintDSCresult(HLINE)
    txt = time.strftime("<%Y%b%d-%H:%M:%S> ", time.gmtime())         # The time
    txt = txt + "Format specifier 120: Selective individual call"
    PrintDSCresult(txt)

    PrintDSCresult("Address:")
    DSC_MMSI(1)
    PrintDSCresult(DSC_CAT(MSGrdta(6)))

    if MSGrdta(6) == 112:   # Category 112
        PrintDSCresult("Self ID:")
        DSC_MMSI(7)
        PrintDSCresult(DSC_TC1(MSGrdta(12)))
        PrintDSCresult("Distress ID:")
        DSC_MMSI(13)
        PrintDSCresult(DSC_NOD(MSGrdta(18)))
        DSC_POS(19)
        DSC_UTC(24)
        PrintDSCresult(DSC_TC1(MSGrdta(25)))
        PrintDSCresult(DSC_EOS(MSGrdta(26)))
    else:
        PrintDSCresult("Self ID:")
        DSC_MMSI(7)
        PrintDSCresult(DSC_TC1(MSGrdta(12)))
        PrintDSCresult(DSC_TC2(MSGrdta(13)))

        if MSGrdta(12) == 121: # Position update
            DSC_POS(14)
            if MSGdata == 122: # EOS for Acknowledgement
                DSC_UTC(20)
        else:
            PrintDSCresult("Called station receive frequency:")
            DSC_FREQ(14)
            PrintDSCresult("Called station transmit frequency:")
            DSC_FREQ(17)

    PrintDSCresult(DSC_EOS(MSGrdta(len(MSGdata)-2)))
    
    MSGstatus = 3       # Continue with the next search, messages have been decoded


# ============================ Decode format specifier 123 (Selective Individual Automatic Call) ==============================
def DEC123():
    global DEBUG
    global MSGdata
    global MSG          # Start of message in strYBY
    global MSGstatus
  
    PrintDSCresult(HLINE)
    txt = time.strftime("<%Y%b%d-%H:%M:%S> ", time.gmtime())         # The time
    txt = txt + "Format specifier 120: Selective individual automatic call"
    PrintDSCresult(txt)

    PrintDSCresult("Address:")
    DSC_MMSI(1)
    PrintDSCresult(DSC_CAT(MSGrdta(6)))
    PrintDSCresult("Self ID:")
    DSC_MMSI(7)
    PrintDSCresult(DSC_TC1(MSGrdta(12)))
    PrintDSCresult(DSC_TC2(MSGrdta(13)))
    PrintDSCresult("Frequency:")
    DSC_FREQ(14)
    DSC_NUMBER(17)
    
    MSGstatus = 3       # Continue with the next search, messages have been decoded


# ============================ Decode format specifier 121 (ATIS) ==============================
def DEC121():
    global DEBUG
    global MSGdata
    global MSG          # Start of message in strYBY
    global MSGstatus
    global ATISlog
    global ATISlogdir
    global ATISdatadir
   
    # ... Callsign information ...
    strX = ""
    i = 1
    while i < 6:
        s = str(MSGrdta(i))
        s = Lzeroes(s, 2)       # if 1 digit, make 2
        strX = strX + s
        i = i + 1

    CallSign = strX[0:4] + chr(64 + MSGrdta(3)) + strX[6:] 
    
    if CallSign[0:1] != "9":
        txt = "ERROR!! MMSI does not start with 9 for Inland Waterways"
        PrintInfo(txt)
        return()
    
    if MSGrdta(3) > 26:
        txt = "ERROR: Callsign does not start with a letter (1 - 26)"
        PrintInfo(txt)
        return()

    ATIStxt = time.strftime("<%Y%b%d-%H:%M:%S>", time.gmtime())          # The time

    strCC = "unknown"           # Country name
    strPR = "?"                 # Prefix character initialise with ?
    cc = int(CallSign[1:4])

    # T1 = time.time()
    if cc == 201:strCC = "Albania";strPR = "Z"
    if cc == 202:strCC = "Andorra";strPR = "C"
    if cc == 203:strCC = "Austria";strPR = "O"
    if cc == 204:strCC = "Azores";strPR = "?"
    if cc == 205:strCC = "Belgium";strPR = "O"
    if cc == 206:strCC = "Belarus";strPR = "E"
    if cc == 207:strCC = "Bulgaria";strPR = "L"
    if cc == 208:strCC = "Vatican City";strPR = "H"
    if cc == 209:strCC = "Cyprus";strPR = "C"
    if cc == 210:strCC = "Cyprus";strPR = "C"
    if cc == 211:strCC = "Germany";strPR = "D"
    if cc == 212:strCC = "Cyprus";strPR = "C"
    if cc == 213:strCC = "Georgia";strPR = "4"
    if cc == 214:strCC = "Moldova";strPR = "E"
    if cc == 215:strCC = "Malta";strPR = "9"
    if cc == 216:strCC = "Armenia";strPR = "E"
    if cc == 218:strCC = "Germany";strPR = "D"           # 218 from former German Democratic Republic
    if cc == 219:strCC = "Denmark";strPR = "O"
    if cc == 220:strCC = "Denmark";strPR = "O"
    if cc == 224:strCC = "Spain";strPR = "E"
    if cc == 225:strCC = "Spain";strPR = "E"
    if cc == 226:strCC = "France";strPR = "F"
    if cc == 227:strCC = "France";strPR = "F"
    if cc == 228:strCC = "France";strPR = "F"
    if cc == 229:strCC = "Malta";strPR = "9"
    if cc == 230:strCC = "Finland";strPR = "O"
    if cc == 231:strCC = "Faroe Islands";strPR = "?"
    if cc == 232:strCC = "United Kingdom";strPR = "G"
    if cc == 233:strCC = "United Kingdom";strPR = "G"
    if cc == 234:strCC = "United Kingdom";strPR = "G"
    if cc == 235:strCC = "United Kingdom";strPR = "G"
    if cc == 236:strCC = "Gibraltar";strPR = "?"
    if cc == 237:strCC = "Greece";strPR = "S"
    if cc == 238:strCC = "Croatia";strPR = "9"
    if cc == 239:strCC = "Greece";strPR = "S"
    if cc == 240:strCC = "Greece";strPR = "S"
    if cc == 241:strCC = "Greece";strPR = "S"
    if cc == 242:strCC = "Morocco";strPR = "C"
    if cc == 243:strCC = "Hungary";strPR = "H"
    if cc == 244:strCC = "Netherlands";strPR = "P"        
    if cc == 245:strCC = "Netherlands";strPR = "P"        
    if cc == 246:strCC = "Netherlands";strPR = "P"
    if cc == 247:strCC = "Italy";strPR = "I"
    if cc == 248:strCC = "Malta";strPR = "9"
    if cc == 249:strCC = "Malta";strPR = "9"
    if cc == 250:strCC = "Ireland";strPR = "E"
    if cc == 251:strCC = "Iceland";strPR = "T"
    if cc == 252:strCC = "Liechtenstein";strPR = "H"        
    if cc == 253:strCC = "Luxembourg";strPR = "L"
    if cc == 254:strCC = "Monaco";strPR = "3"
    if cc == 255:strCC = "Madeira";strPR = "?"
    if cc == 256:strCC = "Malta";strPR = "9"
    if cc == 257:strCC = "Norway";strPR = "L"
    if cc == 258:strCC = "Norway";strPR = "L"
    if cc == 259:strCC = "Norway";strPR = "L"
    if cc == 261:strCC = "Poland";strPR = "S"
    if cc == 262:strCC = "Montenegro";strPR = "4"
    if cc == 263:strCC = "Portugal";strPR = "C"
    if cc == 264:strCC = "Romania";strPR = "Y"
    if cc == 265:strCC = "Sweden";strPR = "S"
    if cc == 266:strCC = "Sweden";strPR = "S"
    if cc == 267:strCC = "Slovakia";strPR = "O"
    if cc == 268:strCC = "San Marino";strPR = "T"
    if cc == 269:strCC = "Switzerland";strPR = "H"
    if cc == 270:strCC = "Czech Republic";strPR = "O"
    if cc == 271:strCC = "Turkey";strPR = "T"
    if cc == 272:strCC = "Ukraine";strPR = "U"
    if cc == 273:strCC = "Russia";strPR = "U"
    if cc == 274:strCC = "Macedonia";strPR = "Z"
    if cc == 275:strCC = "Latvia";strPR = "Y"
    if cc == 276:strCC = "Estonia";strPR = "E"
    if cc == 277:strCC = "Lithuania";strPR = "L"
    if cc == 278:strCC = "Slovenia";strPR = "S"
    if cc == 279:strCC = "Serbia";strPR = "Y"
    # T2 = time.time();print(T2-T1)
    
    ATIStxt = ATIStxt + " " + strPR + CallSign[4:] + "  Country: " + CallSign[1:4] + " (" + strCC + ")"
    PrintResult(ATIStxt)

    MSGstatus = 3

    if ATISlog == False:
        return()

    if strPR == "?":    # Unknown country
        filename = "-" + CallSign[1:4] + "-" + CallSign[4:] + ".txt"
    else:               # Known country
        filename = strPR + CallSign[4:] + ".txt"

    try:
        filename = ATISdatadir + filename
        Wfile = open(filename,'a')          # output file setting
        Wfile.write(ATIStxt + "\n")
        Wfile.close()                       # Close the file
    except:
        PrintInfo("File append error: " + filename)

    try:
        filename = time.strftime("%Y%m%d", time.gmtime())          # The time
        filename = ATISlogdir + filename + "-ATISlog.txt"
        Wfile = open(filename,'a')          # output file setting
        Wfile.write(ATIStxt + "\n")
        Wfile.close()                       # Close the file
    except:
        PrintInfo("File append error: " + filename)


# ============================ Decode Expansion message ==============================
def DSCExpansion821():  # Expansion message decoder ITU-R M.821
    global MSG          # Start of message in strYBY
    global HLINE        # Dashed line
    global DEBUG
    global MSGdata
    global MSG          # Start of message in strYBY
    global MSGstatus
    global EXPMSGdata

    if len(EXPMSGdata) == 0:        # Return if no message
        return()
    
    PrintDSCresult(HLINE)
    PrintDSCresult("Expansion message ITU-R M.821")
    PrintDSCresult(HLINE)

    P = 0                               # The pointer in EXPMSGdata[]
    while(1):
        if P > len(EXPMSGdata):         # Stop if the end of EXPMSGdata[] has been reached
            break

        if EXPMSGrdta(P) == 117:        # Stop if one of the 3 EOS characters
            break

        if EXPMSGrdta(P) == 122:
            break

        if EXPMSGrdta(P) == 127:
            break

        if EXPMSGrdta(P) < 100 or EXPMSGrdta(P) > 106:      # Stop if not a known expansion data specifier
            PrintDSCresult(str(EXPMSGrdta(P)) + " Unknown expansion data specifier:")
            break

        # ... 100 Enhanced position resolution ...
        if EXPMSGrdta(P) == 100:
            P = P + 1
            PrintDSCresult("100 Enhanced position resolution:")
            if EXPMSGrdta(P) == 126 or EXPMSGrdta(P) == 110:
                if EXPMSGrdta(P) == 110:
                    PrintDSCresult("110 Enhanced position data request")
                if EXPMSGrdta(P) == 126:
                    PrintDSCresult("126 No enhanced position information")
                P = P + 1                               # Point to the next possible expansion data specifier
            else:
                strX = ""
                N = 0
                while N < 4:
                    if EXPMSGrdta(P+N) < 10:
                        strX = strX + "0" 
                    s = str(EXPMSGrdta(P+N))
                    strX = strX + s.strip()
                    N = N + 1
                P = P + N                               # Point to the next possible expansion data specifier

                PrintDSCresult("<" + strX + ">")
                PrintDSCresult("Latitude : " + "0." + strX[0:4])
                PrintDSCresult("Longitude: " + "0." + strX[4:9])

          
        # ... 101 Source and datum of position ...
        if EXPMSGrdta(P) == 101:
            P = P + 1
            PrintDSCresult("101 Source and datum of position:")
            if EXPMSGrdta(P) == 126 or EXPMSGrdta(P) == 110:
                if EXPMSGrdta(P) == 110:
                    PrintDSCresult("110 Source and datum of position data request")
                if EXPMSGrdta(P) == 126:
                    PrintDSCresult("126 No source and datum of position information")
                P = P + 1                               # Point to the next possible expansion data specifier
            else:
                strX = ""
                N = 0
                while N < 3:
                    if EXPMSGrdta(P+N) < 10:
                        strX = strX + "0" 
                    s = str(EXPMSGrdta(P+N))
                    strX = strX + s.strip()
                    N = N + 1
                P = P + N                               # Point to the next possible expansion data specifier
                
                PrintDSCresult("<" + strX + ">")
                TXT = "  ERROR!! INVALID SOURCE CHARACTER"
                intX = int(strX[0:2])
                if intX == 0:
                    TXT = "  Current position data invalid"
                if intX == 1:
                    TXT = "  Position data from differential GPS"
                if intX == 2:
                    TXT = "  Position data from uncorrected GPS"
                if intX == 3:
                    TXT = "  Position data from differential LORAN-C"
                if intX == 4:
                    TXT = "  Position data from uncorrected LORAN-C"
                if intX == 5:
                    TXT = "  Position data from GLONASS"
                if intX == 6:
                    TXT = "  Position data from radar fix"
                if intX == 7:
                    TXT = "  Position data from Decca"
                if intX == 8:
                    TXT = "  Position data from other source"
             
                PrintDSCresult("Source : " + strX[0:2] + TXT)
                PrintDSCresult("Fix    : " + strX[2] + "." + strX[3])
             
                TXT = "  ERROR!! INVALID DATE CHARACTER"
                intX = int(strX[4:6])
                if intX == 0:
                    TXT = "  WGS-84"
                if intX == 1:
                    TXT = "  WGS-72"
                if intX == 2:
                    TXT = "  Other"
                          
                PrintDSCresult("Date  : " + strX[4:6] + TXT)

              
        # ... 102 Vessel speed ...
        if EXPMSGrdta(P) == 102:
            P = P + 1
            PrintDSCresult("102 Vessel speed:")
            if EXPMSGrdta(P) == 126 or EXPMSGrdta(P) == 110:
                if EXPMSGrdta(P) == 110:
                    PrintDSCresult("110 Vessel speed data request")
                if EXPMSGrdta(P) == 126:
                    PrintDSCresult("126 No vessel speed information")
                P = P + 1                               # Point to the next possible expansion data specifier
            else:
                strX = ""
                N = 0
                while N < 2:
                    if EXPMSGrdta(P+N) < 10:
                        strX = strX + "0" 
                    s = str(EXPMSGrdta(P+N))
                    strX = strX + s.strip()
                    N = N + 1
                P = P + N                               # Point to the next possible expansion data specifier
                
                PrintDSCresult("<" + strX + ">")
                PrintDSCresult("Speed: " + strX[0:3] + "." + strX[3] + " knots")
             
      
        # ... 103 Current course of the vessel ...
        if EXPMSGrdta(P) == 103:
            P = P + 1
            PrintDSCresult("103 Current course of the vessel:")
            if EXPMSGrdta(P) == 126 or EXPMSGrdta(P) == 110:
                if EXPMSGrdta(P) == 110:
                    PrintDSCresult("110 Vessel course data request")
                if EXPMSGrdta(P) == 126:
                    PrintDSCresult("126 No vessel course information")
                P = P + 1                               # Point to the next possible expansion data specifier
            else:
                strX=""
                N = 0
                while N < 2:
                    if EXPMSGrdta(P+N) < 10:
                        strX = strX + "0" 
                    s = str(EXPMSGrdta(P+N))
                    strX = strX + s.strip()
                    N = N + 1
                P = P + N                               # Point to the next possible expansion data specifier
                
                PrintDSCresult("<" + strX + ">")
                PrintDSCresult("Course: " + strX[0:3] + "." + strX[3] + " Degrees")

             
        # ... 104 Additional station information ...
        strExpChar = "0123456789?ABCDEFGHIJKLMNOPQRSTUVWXYZ.,-/ "
      
        if EXPMSGrdta(P) == 104:
            P = P + 1
            PrintDSCresult("104 Additional station information:")
            if EXPMSGrdta(P) == 126 or EXPMSGrdta(P) == 110:
                if EXPMSGrdta(P) == 110:
                    PrintDSCresult("110 Additional station information data request")
                if EXPMSGrdta(P) == 126:
                    PrintDSCresult("126 No additional station information")
                P = P + 1                               # Point to the next possible expansion data specifier
            else:
                strX = ""
                N = 0
                while N < 99:                           # Limited to 99 characters but max 10 is allowed
                    if EXPMSGrdta(P+N) <= 41:
                        strX = strX + strExpChar[EXPMSGrdta(P+N)]
                    if EXPMSGrdta(P+N) > 41 and EXPMSGrdta(P+N) <= 99:
                        strX = strX + "?"
                    if EXPMSGrdta(P+N) > 99:            # It has to stop once...
                        break
                    N = N + 1
                P = P + N                               # Point to the next possible expansion data specifier
                
                PrintDSCresult("<" + strX + ">")

         
        # ... 105 Enhanced geographic area ...
        if EXPMSGrdta(P) == 105:
            P = P + 1
            PrintDSCresult("105 Enhanced geographic area position information:")
             
            strX = ""
            N = 0
            while N < 12:
                if EXPMSGrdta(P+N) < 10:
                    strX = strX + "0" 
                s = str(EXPMSGrdta(P+N))
                strX = strX + s.strip()
                N = N + 1
            P = P + N                               # Point to the possible speed information of the Enhanced geographic area

            PrintDSCresult("Latitude ref. point : " + "0." + strX[0:4])
            PrintDSCresult("Longitude ref. point: " + "0." + strX[4:8])
            PrintDSCresult("Latitude offset     : " + "0." + strX[8:12])
            PrintDSCresult("Longitude offset    : " + "0." + strX[12:16])
            PrintDSCresult(" ")
          
            # ... Speed information enhanced geographic area data ...
            if EXPMSGrdta(P) == 126 and EXPMSGrdta(P+1) == 126:
                PrintDSCresult("No speed information")
                P = P + 2
            else:
                strX = ""
                N = 0
                while N < 2:
                    if EXPMSGrdta(P+N) < 10:
                        strX = strX + "0" 
                    s = str(EXPMSGrdta(P+N))
                    strX = strX + s.strip()
                    N = N + 1
                P = P + N                           # Point to the possible course information of the Enhanced geographic area                    

                strX = "Speed : " + strX[0:3] + "." + strX[3:4] + " knots"
                PrintDSCresult(strX)
      
            # ... Course information enhanced geographic area data ...
            if EXPMSGrdta(P+10) == 126 and EXPMSGrdta(P+11) == 126:
                PrintDSCresult("No course information")
                P = P + 2
            else:
                strX = ""
                N = 0
                while N < 2:
                    if EXPMSGrdta(P+N) < 10:
                        strX = strX + "0" 
                    s = str(EXPMSGrdta(P+N))
                    strX = strX + s.strip()
                    N = N + 1
                P = P + N                               # Point to the next possible expansion data specifier

                strX = "Course: " + strX[0:3] + "." + strX[3:4] + " Degrees"
                PrintDSCresult(strX)

        # ... 106 Number of persons on board ...
        if EXPMSGrdta(P) == 106:
            P = P + 1
            PrintDSCresult("106 Number of persons on board:")
            if EXPMSGrdta(P) == 126 or EXPMSGrdta(P) == 110:
                if EXPMSGrdta(P) == 110:
                    PrintDSCresult("110 Number of persons on board data request")
                if EXPMSGrdta(P) == 126:
                    PrintDSCresult("126 No number of persons information")
                P = P + 1                               # Point to the next possible expansion data specifier
            else:
                strX = ""
                N = 0
                while N < 2:
                    if EXPMSGrdta(P+N) < 10:
                        strX = strX + "0" 
                    s = str(EXPMSGrdta(P+N))
                    strX = strX + s.strip()
                    N = N + 1
                P = P + N                               # Point to the next possible expansion data specifier

                strX = "Number of persons: " + strX
                PrintDSCresult(strX)
             
    EXPMSGdata = []         # Clear the expansion message data, otherwise it will be decoded again and again...
    PrintDSCresult(HLINE)      # Line for the end of the expansion message


# =========================== Various DSC subroutines like MMSI, position, UTC etc. ================== 

# ... Decode an MMSI address ...
def DSC_MMSI(P):
    # MMSI address
    global MSGdata
    global CC
    
    CallSign = ""
    
    N = 0
    while N <= 4:
        if MSGrdta(P + N) < 10:
            CallSign = CallSign + "0"
        s = str(MSGrdta(P + N))
        CallSign = CallSign + s.strip()
        N = N + 1
        
    TXT = "<" + CallSign + ">"
    if CallSign[-1:] != "0":
        TXT = TXT + " ERROR! MMSI SHOULD END WITH A ZERO"
        PrintDSCresult(TXT)
    else:
        if CallSign[0:1] != "0":
            TXT = "MID (Country): " + CallSign[0:3] + " Individual  MMSI: " + CallSign[3:9]
            x = int(CallSign[0:3])
            TXT = TXT + " " + CC[x]
        
        if CallSign[0:1] == "0" and CallSign[1:2] != "0":
            TXT = "MID (Country): " + CallSign[1:4] + " Group  MMSI: " + CallSign[4:9]
            x = int(CallSign[1:4])
            TXT = TXT + " " + CC[x]
         
        if CallSign[0:1] == "0" and CallSign[1:2] == "0":
            TXT = "MID (Country): " + CallSign[2:5] + " Coast station  MMSI: " + CallSign[5:9]
            x = int(CallSign[2:5])
            TXT = TXT + " " + CC[x]
             
        PrintDSCresult(TXT)


# ... Decode a frequency ...
def DSC_FREQ(P):
    global MSGdata
    
    intFreqErrFlag = 0

    Frequency = ""
    N = 0
    while N <= 2:
        if MSGrdta(P + N) < 10:
            Frequency = Frequency + "0" 
        s = str(MSGrdta(P + N))
        Frequency = Frequency + s.strip()
        N = N + 1

    TXT = "<" + Frequency + ">"
    # PrintDSCresult(TXT)
       
    N = P
    while N <= (P + 2):
        if MSGrdta(N) != 126 and MSGrdta(N) > 99:
            intFreqErrFlag = 1
        N = N + 1
          
    if intFreqErrFlag == 1:
        TXT = TXT + " ERROR!! in frequency value"
        PrintDSCresult(TXT)
        return()
    
    if MSGrdta(P) == 126:
        TXT = TXT + " No frequency information"
        PrintDSCresult(TXT)
        return()
   
    if Frequency[0] == "9":
        if Frequency[1] != "0":
            TXT = TXT + " Frequency error! HM (first two digits) should be 90!"
            PrintDSCresult(TXT)
            return()
     
        if int(Frequency[2]) > 2:
            TXT = TXT + " Frequency error! M (third character) should be < 3!"
            PrintDSCresult(TXT)
            return()
        
        if Frequency[2] == "0":     
            # "Frequency in accordance with RR Appendix 18 "
            pass
        
        if Frequency[2] == "1":
            # "This frequency is simplex for ship and coast station"
            pass
        
        if Frequency[2] == "2":
            # "Other frequency is simplex for ship and coast station"
            pass
        
        # ... Channel ...
        TXT = TXT + " VHF channel: " + Frequency[3:6]
        PrintDSCresult(TXT)
        return

    if Frequency[0] == "0":
        # ... Frequency ...
        TXT = TXT + " HF frequency: " + Frequency[0:6]
        PrintDSCresult(TXT)
        return

    if Frequency[0] == "1":
        # ... Frequency ...
        TXT = TXT + " HF frequency: " + Frequency[0:6]
        PrintDSCresult(TXT)
        return
      
    if Frequency[0] == "2":
        # ... Frequency ...
        TXT = TXT + " HF frequency: " + Frequency[0:6]
        PrintDSCresult(TXT)
        return

    if Frequency[0] == "3":
        # ... Frequency ...
        TXT = TXT + " HF working channel: " + Frequency[1:6]
        PrintDSCresult(TXT)
        return

    if Frequency[0] == "8":
        # ... Frequency ...
        TXT = TXT + " ITU-R M.586 frequency: " + Frequency[2:6]
        PrintDSCresult(TXT)
        return

    TXT = " Frequency error: " + Frequency[0:6]
    PrintDSCresult(TXT)

 
 
# ... Decode a position ...
def DSC_POS(P):
    global MSGdata
    
    intPosErrFlag = 0
    TXT = ""

    N = P
    while N <= (P + 5):
        if MSGrdta(N) != 126 and MSGrdta(N) > 99:
            intPosErrFlag = 1
        N = N + 1
          
    if MSGrdta(P) == 126:
        TXT = "Position information request"
        PrintDSCresult(TXT)
        return()
          
    if intPosErrFlag == 1:
        TXT = "ERROR!! in position value"
        PrintDSCresult(TXT)
        return()

    # ... Position ...
    Position = ""
    Frequency = ""
    N = 0
    while N <= 4:
        if MSGrdta(P + N) < 10:
            Position = Position + "0" 
        s = str(MSGrdta(P + N))
        Position = Position + s.strip()
        N = N + 1

    # TXT = "<" + Position + ">"
    # PrintDSCresult(TXT)
    if Position == "9999999999":
        TXT = "No position information"
        PrintDSCresult(TXT)
        return()
    
    TXT = "Quadrant:  " + Position[0:1]
    if int(Position[0:1]) > 3:
        TXT = TXT + " ERROR!! illegal quadrant value"
    else:
        if int(Position[0:1]) == 0:
            TXT = TXT + " (NE)"
        if int(Position[0:1]) == 1:
            TXT = TXT + " (NW)"
        if int(Position[0:1]) == 2:
            TXT = TXT + " (SE)"
        if int(Position[0:1]) == 3:
            TXT = TXT + " (SW)"
    
    PrintDSCresult(TXT)
    
    TXT = "Latitude:  " + Position[1:3] + ":" + Position[3:5]
    PrintDSCresult(TXT)
    TXT = "Longitude: " + Position[5:8] + ":" + Position[8:10]
    PrintDSCresult(TXT)
 
 
# ... Decode a Zone ...
def DSC_ZONE(P):
    # Zone / Area
    global MSGdata
    
    Position = ""
    N = 0
    while N <= 4:
        if MSGrdta(P + N) < 10:
            Position = Position + "0" 
        s = str(MSGrdta(P + N))
        Position = Position + s.strip()
        N = N + 1

    TXT = "<" + Position + ">"
    PrintDSCresult(TXT)
    
    TXT = "Quadrant:             " + Position[1:2]
    if int(Position[0:1]) > 3:
        TXT = TXT + " ERROR!! illegal quadrant value"
    else:
        if int(Position[0:1]) == 0:
            TXT = TXT + " (NE)"
        if int(Position[0:1]) == 1:
            TXT = TXT + " (NW)"
        if int(Position[0:1]) == 2:
            TXT = TXT + " (SE)"
        if int(Position[0:1]) == 3:
            TXT = TXT + " (SW)"
    
    PrintDSCresult(TXT)
    
    TXT = "Latitude ref. point : " + Position[1:3]
    PrintDSCresult(TXT)
    TXT = "Longitude ref. point: " + Position[3:6]
    PrintDSCresult(TXT)
    TXT = "Latitude N/S offset : " + Position[6:8]
    PrintDSCresult(TXT)
    TXT = "Longitude W/E offset: " + Position[8:10]
    PrintDSCresult(TXT)
 
 
# ... Decode a time in UTC ...
def DSC_UTC(P):
    global MSGdata
    
    strUTC = ""
    N = 0
    while N <= 1:
        if MSGrdta(P + N) < 10:
            strUTC = strUTC + "0" 
        s = str(MSGrdta(P + N))
        strUTC = strUTC + s.strip()
        N = N + 1
    
    if strUTC == "8888":
        TXT = "No time information"
    else:
        TXT = "UTC: " + strUTC

    PrintDSCresult(TXT)
 

# ... Decode a number ...
def DSC_NUMBER(P):
    global MSGdata
    
    if MSGrdta(P) != 105 and MSGrdta(P) != 106:     # Only if a number follows, 105 for odd and 106 for even
        return() 
        
    strNR = ""
    
    N = 1
    while MSGrdta(P + N) < 100:
        if MSGrdta(P + N) < 10:
            strNR = strNR + "0" 
        s = str(MSGrdta(P + N))
        strNR = strNR + s.strip()
        N = N + 1
        
    
    if MSGrdta(P) == 105 and len(strNR) > 0:        # Odd numbers
        strNR = strNR[1:]                           # Skip the first zero
    
    TXT = "Number: " + strNR
    PrintDSCresult(TXT)


# ... Decode a category ...
def DSC_CAT(T):
    
    Y = "NON EXISTING CATEGORY VALUE!"
    if T == 100:
        Y = "<Routine>"
    if T == 103:
        Y = "<Not used anymore>"
    if T == 106:
        Y = "<Not used anymore>"
    if T == 108:
        Y = "<Safety>"
    if T == 110:
        Y = "<Urgency>"
    if T == 112:
        Y = "<Distress>"
    return(Y)

     
# ... Decode a Nature of Distress ...
def DSC_NOD(T):

    Y = "NON EXISTING NATURE OF DISTRESS!"
    if T == 100:
        Y = "<Fire, Explosion>"
    if T == 101:
        Y = "<Flooding>"
    if T == 102:
        Y = "<Collision>"
    if T == 103:
        Y = "<Grounding>"
    if T == 104:
        Y = "<Listing, in danger of capsizing>"
    if T == 105:
        Y = "<Sinking>"
    if T == 106:
        Y = "<Disabled and adrift>"
    if T == 107:
        Y = "<Undesignated distress>"
    if T == 108:
        Y = "<Abandoning ship>"
    if T == 109:
        Y = "<Piracy/armed robbery attack>"
    if T == 110:
        Y = "<Man overboard>"
    if T == 112:
        Y = "<Epirb emission>"
    return(Y)
              

# ... Decode a Telecommand 1 ...
def DSC_TC1(T):

    Y = "ERROR!! NON EXISTING TELECOMMAND 1 VALUE"
    if T == 100:
        Y = "<F3E/G3E All modes TP>"
    if T == 101:
        Y = "<F3E/G3E Duplex TP>"
    if T == 103:
        Y = "<Polling>"
    if T == 104:
        Y = "<Unable to comply>"
    if T == 105:
        Y = "<End of call (semi-automatic service only)>"
    if T == 106:
        Y = "<Data>"
    if T == 109:
        Y = "<J3E TP>"
    if T == 110:
        Y = "<Distress acknowledgement>"
    if T == 112:
        Y = "<Distress relay>"
    if T == 113:
        Y = "<F1B/J2B TTY-FEC>"
    if T == 115:
        Y = "<F1B/J2B TTY-ARQ>"
    if T == 118:
        Y = "<Test>"
    if T == 121:
        Y = "<Ship position or location registration updating>"
    if T == 126:
        Y = "<No information>"
    return(Y)           

     
# ... Decode a Telecommand 2 ...
def DSC_TC2(T):

    Y = "ERROR!! NON EXISTING TELECOMMAND 2 VALUE"
    if T == 100:
        Y = "<No reason>"
    if T == 101:
        Y = "<Congestion at maritime switching centre>"
    if T == 102:
        Y = "<Busy>"
    if T == 103:
        Y = "<Queue indication>"
    if T == 104:
        Y = "<Station barred>"
    if T == 105:
        Y = "<No operator available>"
    if T == 106:
        Y = "<Operator temporarily unavailable>"
    if T == 107:
        Y = "<Equipment disabled>"
    if T == 108:
        Y = "<Unable to use proposed channel>"
    if T == 109:
        Y = "<Unable to use proposed mode>"
    if T == 110:
        Y = "<Ship according to Resolution 18>"
    if T == 111:
        Y = "<Medical transports>"
    if T == 112:
        Y = "<Phone call office>"
    if T == 113:
        Y = "<Faximile/data ITU-R M.1081>"
    if T == 126:
        Y = "<No information>"
    return(Y)


# ... Decode an EOS (End Of Sequence) ...
def DSC_EOS(T):
    # EOS?
    Y = "ERROR!! NON EXISTING EOS VALUE"
    if T == 117:
        Y = "<EOS for Acknowledgement required>"
    if T == 122:
        Y = "<EOS for Acknowledgement given>"
    if T == 127:
        Y = "<EOS for Non acknowledgements>"
    return(Y)


# ======================== Various general routines ========================

# ... Convert a value to a 10 unit string code (ybyby) ...
def TENunit(Vin):
    if (Vin > 127):
         return("ERROR TENunit > 127") # ERROR
    
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


# ... Return the value of symbol i (start at 1, only the first 7 bits are used) ...
def GETvalsymbol(i):
    global MSG                          # Start of message in strYBY
    global strYBY

    n = MSG + (i-1)*10                  # msg is start position in strYBY of message
    if n < 0:                           # If out of range of strYBY then return -1
        return(-1)
    while len(strYBY) <= n + 11:        # If strYBY is too short, call MakeYBY
        MakeYBY()

    s = strYBY[n: (n+10)]

    intB = 0
    v = 0
    if (s[0] == "Y"):
        v = v + 1
    else:
        intB = intB + 1
    if (s[1] == "Y"):
        v = v + 2
    else:
        intB = intB + 1
    if (s[2] == "Y"):
        v = v + 4
    else:
        intB = intB + 1
    if (s[3] == "Y"):
        v = v + 8
    else:
        intB = intB + 1
    if (s[4] == "Y"):
        v = v + 16
    else:
        intB = intB + 1
    if (s[5] == "Y"):
        v = v + 32
    else:
        intB = intB + 1
    if (s[6] == "Y"):
        v = v + 64
    else:
        intB = intB + 1

    Errchk = ""
    intY = 4
    n = 0
    while (n < 3):                     # Calculate the last 3 bits from intB (the number of "B"s), Msb(Y=1) first
        if ((int(intB) & int(intY)) != 0):
            Errchk = Errchk + "Y"
        else:
            Errchk = Errchk + "B"            

        intY = intY / 2
        n = n + 1

    if Errchk != s[7:]:
        v = -1 * v                      # If Error check bits wrong, return negative value

    return(v)


# ... Try to read from MSGdata[] and return that value or 127 (EOS) if not possible ...
def MSGrdta(i):
    try:
        v = MSGdata[i]
    except:
        v = 127                         # Out of range of MSGdata[], return EOS (=127)
    return(v)


# ... Try to read from EXPMSGdata[] and return that value or 127 (EOS) if not possible ...
def EXPMSGrdta(i):                      # Try to read from EXPMSGdata[]
    try:
        v = EXPMSGdata[i]
    except:
        v = 127                         # Out of range of EXPMSGdata[], return EOS (=127)
    return(v)
     

# ... If the string < s, insert spaces at the beginning ...
def Lspaces(s, k):
    while len(s) < k:
        s = " " + s
    return(s)


# ... If the string < s, add spaces at the end ...
def Rspaces(s, k):
    while len(s) < k:
        s = s + " "
    return(s)


# ... If the string < s, insert zeroes at the beginning (for making 02, 03 of 2, 3 etc.) ...
def Lzeroes(s, k):
    s = s.strip()       # remove spaces
    while len(s) < k:
        s = "0" + s
    return(s)


# ... Print a string to the Textbox 2 and add a line feed ...
def PrintResult(txt):
    global AUTOscroll
    txt = txt + "\n"
    text2.insert(END, txt)
    if AUTOscroll == True:
        text2.yview(END)


# ... Print a DSC message string to the Textbox 2 and add a line feed and save to the DSC logfile if enabled ...
def PrintDSCresult(txt):
    global DSClog
    global DSClogdir
    global AUTOscroll
   
    txt = txt + "\n"
    text2.insert(END, txt)
    print(f"{txt}")
   


# ... Print a string to the Info Textbox 1 and add a line feed ...
def PrintInfo(txt):
    global AUTOscroll
    txt = txt + "\n"
    text1.insert(END, txt)
    if AUTOscroll == True:
        text1.yview(END)




# ... Fill the Country Code list ...
def FillCC():
    global CC

    n = 0
    while n <= 1000:
        CC.append("Unkown")
        n = n + 1

    CC[201]="Albania (Republic of)"
    CC[202]="Andorra (Principality of)"
    CC[203]="Austria"
    CC[204]="Portugal - Azores"
    CC[205]="Belgium"
    CC[206]="Belarus (Republic of)"
    CC[207]="Bulgaria (Republic of)"
    CC[208]="Vatican City State"
    CC[209]="Cyprus (Republic of)"
    CC[210]="Cyprus (Republic of)"
    CC[211]="Germany (Federal Republic of)"
    CC[212]="Cyprus (Republic of)"
    CC[213]="Georgia"
    CC[214]="Moldova (Republic of)"
    CC[215]="Malta"
    CC[216]="Armenia (Republic of)"
    CC[218]="Germany (Federal Republic of)"
    CC[219]="Denmark"
    CC[220]="Denmark"
    CC[224]="Spain"
    CC[225]="Spain"
    CC[226]="France"
    CC[227]="France"
    CC[228]="France"
    CC[229]="Malta"
    CC[230]="Finland"
    CC[231]="Denmark - Faroe Islands"
    CC[232]="United Kingdom of Great Britain and Northern Ireland"
    CC[233]="United Kingdom of Great Britain and Northern Ireland"
    CC[234]="United Kingdom of Great Britain and Northern Ireland"
    CC[235]="United Kingdom of Great Britain and Northern Ireland"
    CC[236]="United Kingdom - Gibraltar"
    CC[237]="Greece"
    CC[238]="Croatia (Republic of)"
    CC[239]="Greece"
    CC[240]="Greece"
    CC[241]="Greece"
    CC[242]="Morocco (Kingdom of)"
    CC[243]="Hungary"
    CC[244]="Netherlands (Kingdom of the)"
    CC[245]="Netherlands (Kingdom of the)"
    CC[246]="Netherlands (Kingdom of the)"
    CC[247]="Italy"
    CC[248]="Malta"
    CC[249]="Malta"
    CC[250]="Ireland"
    CC[251]="Iceland"
    CC[252]="Liechtenstein (Principality of)"
    CC[253]="Luxembourg"
    CC[254]="Monaco (Principality of)"
    CC[255]="Portugal - Madeira"
    CC[256]="Malta"
    CC[257]="Norway"
    CC[258]="Norway"
    CC[259]="Norway"
    CC[261]="Poland (Republic of)"
    CC[262]="Montenegro"
    CC[263]="Portugal"
    CC[264]="Romania"
    CC[265]="Sweden"
    CC[266]="Sweden"
    CC[267]="Slovak Republic"
    CC[268]="San Marino (Republic of)"
    CC[269]="Switzerland (Confederation of)"
    CC[270]="Czech Republic"
    CC[271]="Republic of Türkiye"
    CC[272]="Ukraine"
    CC[273]="Russian Federation"
    CC[274]="North Macedonia (Republic of)"
    CC[275]="Latvia (Republic of)"
    CC[276]="Estonia (Republic of)"
    CC[277]="Lithuania (Republic of)"
    CC[278]="Slovenia (Republic of)"
    CC[279]="Serbia (Republic of)"
    CC[301]="United Kingdom - Anguilla"
    CC[303]="United States of America - Alaska (State of)"
    CC[304]="Antigua and Barbuda"
    CC[305]="Antigua and Barbuda"
    CC[306]="Netherlands - Carribean Islands"
    CC[307]="Netherlands (Kingdom of the) - Aruba"
    CC[308]="Bahamas (Commonwealth of the)"
    CC[309]="Bahamas (Commonwealth of the)"
    CC[310]="United Kingdom - Bermuda"
    CC[311]="Bahamas (Commonwealth of the)"
    CC[312]="Belize"
    CC[314]="Barbados"
    CC[316]="Canada"
    CC[319]="United Kingdom - Cayman Islands"
    CC[321]="Costa Rica"
    CC[323]="Cuba"
    CC[325]="Dominica (Commonwealth of)"
    CC[327]="Dominican Republic"
    CC[329]="France - Guadeloupe (French Department of)"
    CC[330]="Grenada"
    CC[331]="Denmark - Greenland"
    CC[332]="Guatemala (Republic of)"
    CC[334]="Honduras (Republic of)"
    CC[336]="Haiti (Republic of)"
    CC[338]="United States of America"
    CC[339]="Jamaica"
    CC[341]="Saint Kitts and Nevis (Federation of)"
    CC[343]="Saint Lucia"
    CC[345]="Mexico"
    CC[347]="France - Martinique (French Department of)"
    CC[348]="United Kingdom - Montserrat"
    CC[350]="Nicaragua"
    CC[351]="Panama (Republic of)"
    CC[352]="Panama (Republic of)"
    CC[353]="Panama (Republic of)"
    CC[354]="Panama (Republic of)"
    CC[355]="Panama (Republic of)"
    CC[356]="Panama (Republic of)"
    CC[357]="Panama (Republic of)"
    CC[358]="United States of America - Puerto Rico"
    CC[359]="El Salvador (Republic of)"
    CC[361]="France - Saint Pierre and Miquelon"
    CC[362]="Trinidad and Tobago"
    CC[364]="United Kingdom - Turks and Caicos Islands"
    CC[366]="United States of America"
    CC[367]="United States of America"
    CC[368]="United States of America"
    CC[369]="United States of America"
    CC[370]="Panama (Republic of)"
    CC[371]="Panama (Republic of)"
    CC[372]="Panama (Republic of)"
    CC[373]="Panama (Republic of)"
    CC[374]="Panama (Republic of)"
    CC[375]="Saint Vincent and the Grenadines"
    CC[376]="Saint Vincent and the Grenadines"
    CC[377]="Saint Vincent and the Grenadines"
    CC[378]="United Kingdom - British Virgin Islands"
    CC[379]="United States of America - Virgin Islands"
    CC[401]="Afghanistan"
    CC[403]="Saudi Arabia (Kingdom of)"
    CC[405]="Bangladesh (Peoples Republic of)"
    CC[408]="Bahrain (Kingdom of)"
    CC[410]="Bhutan (Kingdom of)"
    CC[412]="China (Peoples Republic of)"
    CC[413]="China (Peoples Republic of)"
    CC[414]="China (Peoples Republic of)"
    CC[416]="China (Peoples Republic of) - Taiwan"
    CC[417]="Sri Lanka"
    CC[419]="India (Republic of)"
    CC[422]="Iran (Islamic Republic of)"
    CC[423]="Azerbaijan (Republic of)"
    CC[425]="Iraq (Republic of)"
    CC[428]="Israel (State of)"
    CC[431]="Japan"
    CC[432]="Japan"
    CC[434]="Turkmenistan"
    CC[436]="Kazakhstan (Republic of)"
    CC[437]="Uzbekistan (Republic of)"
    CC[438]="Jordan (Hashemite Kingdom of)"
    CC[440]="Korea (Republic of)"
    CC[441]="Korea (Republic of)"
    CC[443]="State of Palestine"
    CC[445]="Democratic Peoples Republic of Korea"
    CC[447]="Kuwait (State of)"
    CC[450]="Lebanon"
    CC[451]="Kyrgyz Republic"
    CC[453]="China (Peoples Republic of) - Macao"
    CC[455]="Maldives (Republic of)"
    CC[457]="Mongolia"
    CC[459]="Nepal (Federal Democratic Republic of)"
    CC[461]="Oman (Sultanate of)"
    CC[463]="Pakistan (Islamic Republic of)"
    CC[466]="Qatar (State of)"
    CC[468]="Syrian Arab Republic"
    CC[470]="United Arab Emirates"
    CC[471]="United Arab Emirates"
    CC[472]="Tajikistan (Republic of)"
    CC[473]="Yemen (Republic of)"
    CC[475]="Yemen (Republic of)"
    CC[477]="China (Peoples Republic of) - Hong Kong"
    CC[478]="Bosnia and Herzegovina"
    CC[501]="France - Adelie Land"
    CC[503]="Australia"
    CC[506]="Myanmar (Union of)"
    CC[508]="Brunei Darussalam"
    CC[510]="Micronesia (Federated States of)"
    CC[511]="Palau (Republic of)"
    CC[512]="New Zealand"
    CC[514]="Cambodia (Kingdom of)"
    CC[515]="Cambodia (Kingdom of)"
    CC[516]="Australia - Christmas Island (Indian Ocean)"
    CC[518]="New Zealand - Cook Islands"
    CC[520]="Fiji (Republic of)"
    CC[523]="Australia - Cocos (Keeling) Islands"
    CC[525]="Indonesia (Republic of)"
    CC[529]="Kiribati (Republic of)"
    CC[531]="Lao Peoples Democratic Republic"
    CC[533]="Malaysia"
    CC[536]="United States of America - Northern Mariana Islands"
    CC[538]="Marshall Islands (Republic of the)"
    CC[540]="France - New Caledonia"
    CC[542]="New Zealand - Niue"
    CC[544]="Nauru (Republic of)"
    CC[546]="France - French Polynesia"
    CC[548]="Philippines (Republic of the)"
    CC[550]="Timor-Leste (Democratic Republic of)"
    CC[553]="Papua New Guinea"
    CC[555]="United Kingdom - Pitcairn Island"
    CC[557]="Solomon Islands"
    CC[559]="United States of America - American Samoa"
    CC[561]="Samoa (Independent State of)"
    CC[563]="Singapore (Republic of)"
    CC[564]="Singapore (Republic of)"
    CC[565]="Singapore (Republic of)"
    CC[566]="Singapore (Republic of)"
    CC[567]="Thailand"
    CC[570]="Tonga (Kingdom of)"
    CC[572]="Tuvalu"
    CC[574]="Viet Nam (Socialist Republic of)"
    CC[576]="Vanuatu (Republic of)"
    CC[577]="Vanuatu (Republic of)"
    CC[578]="France - Wallis and Futuna Islands"
    CC[601]="South Africa (Republic of)"
    CC[603]="Angola (Republic of)"
    CC[605]="Algeria (Peoples Democratic Republic of)"
    CC[607]="France - Saint Paul and Amsterdam Islands"
    CC[608]="United Kingdom - Ascension Island"
    CC[609]="Burundi (Republic of)"
    CC[610]="Benin (Republic of)"
    CC[611]="Botswana (Republic of)"
    CC[612]="Central African Republic"
    CC[613]="Cameroon (Republic of)"
    CC[615]="Congo (Republic of the)"
    CC[616]="Comoros (Union of the)"
    CC[617]="Cabo Verde (Republic of)"
    CC[618]="France - Crozet Archipelago"
    CC[619]="Côte Ivoire (Republic of)"
    CC[620]="Comoros (Union of the)"
    CC[621]="Djibouti (Republic of)"
    CC[622]="Egypt (Arab Republic of)"
    CC[624]="Ethiopia (Federal Democratic Republic of)"
    CC[625]="Eritrea"
    CC[626]="Gabonese Republic"
    CC[627]="Ghana"
    CC[629]="Gambia (Republic of the)"
    CC[630]="Guinea-Bissau (Republic of)"
    CC[631]="Equatorial Guinea (Republic of)"
    CC[632]="Guinea (Republic of)"
    CC[633]="Burkina Faso"
    CC[634]="Kenya (Republic of)"
    CC[635]="France - Kerguelen Islands"
    CC[636]="Liberia (Republic of)"
    CC[637]="Liberia (Republic of)"
    CC[638]="South Sudan (Republic of)"
    CC[642]="Libya (State of)"
    CC[644]="Lesotho (Kingdom of)"
    CC[645]="Mauritius (Republic of)"
    CC[647]="Madagascar (Republic of)"
    CC[649]="Mali (Republic of)"
    CC[650]="Mozambique (Republic of)"
    CC[654]="Mauritania (Islamic Republic of)"
    CC[655]="Malawi"
    CC[656]="Niger (Republic of the)"
    CC[657]="Nigeria (Federal Republic of)"
    CC[659]="Namibia (Republic of)"
    CC[660]="France - Reunion (French Department of)"
    CC[661]="Rwanda (Republic of)"
    CC[662]="Sudan (Republic of the)"
    CC[663]="Senegal (Republic of)"
    CC[664]="Seychelles (Republic of)"
    CC[665]="United Kingdom - Saint Helena"
    CC[666]="Somalia (Federal Republic of)"
    CC[667]="Sierra Leone"
    CC[668]="Sao Tome and Principe (Democratic Republic of)"
    CC[669]="Eswatini (Kingdom of)"
    CC[670]="Chad (Republic of)"
    CC[671]="Togolese Republic"
    CC[672]="Tunisia"
    CC[674]="Tanzania (United Republic of)"
    CC[675]="Uganda (Republic of)"
    CC[676]="Democratic Republic of the Congo"
    CC[677]="Tanzania (United Republic of)"
    CC[678]="Zambia (Republic of)"
    CC[679]="Zimbabwe (Republic of)"
    CC[701]="Argentine Republic"
    CC[710]="Brazil (Federative Republic of)"
    CC[720]="Bolivia (Plurinational State of)"
    CC[725]="Chile"
    CC[730]="Colombia (Republic of)"
    CC[735]="Ecuador"
    CC[740]="United Kingdom - Falkland Islands (Malvinas)"
    CC[745]="France - Guiana (French Department of)"
    CC[750]="Guyana"
    CC[755]="Paraguay (Republic of)"
    CC[760]="Peru"
    CC[765]="Suriname (Republic of)"
    CC[770]="Uruguay (Eastern Republic of)"
    CC[775]="Venezuela (Bolivarian Republic of)"

# ================ Start Make Screen ======================================================

root=Tk()
root.title("DSCrx-v01.py")

root.minsize(100, 100)

frame1 = Frame(root, background="blue", borderwidth=5, relief=RIDGE)
frame1.pack(side=TOP, expand=1, fill=X)

frame1a = Frame(root, background="blue", borderwidth=5, relief=RIDGE)
frame1a.pack(side=TOP, expand=1, fill=X)

frame2 = Frame(root, background="black", borderwidth=5, relief=RIDGE)
frame2.pack(side=TOP, expand=1, fill=X)

frame3 = Frame(root, background="red", borderwidth=5, relief=RIDGE)
frame3.pack(side=TOP, expand=1, fill=X)

scrollbar1 = Scrollbar(frame1)
scrollbar1.pack(side=RIGHT, expand=NO, fill=BOTH)

text1 = Text(frame1, height=5, width=150, yscrollcommand=scrollbar1.set)
text1.pack(side=TOP, expand=1, fill=X)

scrollbar1.config(command=text1.yview)


scrollbar2 = Scrollbar(frame2)
scrollbar2.pack(side=RIGHT, expand=NO, fill=BOTH)

text2 = Text(frame2, height=30, width=150, yscrollcommand=scrollbar2.set)
text2.pack(side=TOP, expand=1, fill=X)

scrollbar2.config(command=text2.yview)




# ================ Main routine ================================================
root.update()                       # Activate updated screens

FillCC()                            # Make Country Code List

MAINloop()                          # Start the main  loop
