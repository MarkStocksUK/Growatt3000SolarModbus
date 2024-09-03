#!/usr/bin/env python
# -*- coding: utf-8 -*-

# python code to poll a (VERY old) GroWatt inverter in the background and publish the data to a mqtt broker
# lots of the inverter polling code was lifted wholesale from code created by Andrew Elwell <Andrew.Elwell@gmail.com> in 2013
# I've updated the code for any newer versions of the libraries
# added in the MQTT client/broker code so that it can be picked up by a MQTT broker running in Home Assistant
# added in testing for network connection so that it doesn't start running until it's connected to the net
# added in error handling for 'Serial Read Error' message. This was returned very occasionally but was fine by the next poll.
# so it's just a shady error handling method of telling it to sleep for 10secs


import time
import configparser
from pymodbus.client import ModbusSerialClient as ModbusClient
import requests
import paho.mqtt.client as mqtt
import json
import socket

errcodes = {24: 'Auto Test Failed', 25:'No AC Connection', 26: 'PV Isolation Low', 27:'Residual Current High',
		28:'DC Current High', 29: 'PV Voltage High', 30: 'AV V Outrange', 31: 'AC Freq Outrange', 32: 'Module Hot'}
# errcodes 1-23 are 'Error: (errorcode+99)

def connectedtointernet(host="8.8.8.8", port=53, timeout=3):
    """
    Host: 8.8.8.8 (google-public-dns-a.google.com)
    OpenPort: 53/tcp
    Service: domain (DNS/TCP)
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as ex:
        print(ex)
        return False

while not connectedtointernet():
    time.sleep(30)

# read settings from config file
print ("Reading config file")
config = configparser.ConfigParser()
config.read('/home/solarpi/solarhome/solarmon/solarmon.cfg')
port = config.get('inverter','port')

check = time.time()
interval = 300
com_str='None'


# connect to MQTT Broker
print ("Connecting to MQTT Broker")

mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
mqttc.username_pw_set(username="solarpi", password="ipralos76")
mqttc.connect(config.get('mqtt','broker'))
topic = config.get('mqtt','topic')
mqttc.loop_start()


# default state at poweron will be 'waiting'
laststate = 0
statetxt = {0: "Waiting", 1: "Normal", 3: "Fault"}


# Read data from inverter
# Growatt pdf says that we can't read more than 45 registers in one go.
inverter = ModbusClient(method='rtu', port=port, baudrate=9600, stopbits=1, parity='N', bytesize=8, timeout=1)
inverter.connect()

while True:
  try:
    now = time.time()
    info = {} # we'll build this up with the parsed output from the registers
    rr = inverter.read_input_registers(0,33)
    # print rr.registers
    invstate=rr.registers[0]
    info["Status"] = statetxt[invstate]
    # mqttc.publish(topic + '/status', statetxt[invstate])

    if (invstate != laststate):
        print ("Changed state from %s to %s" % (laststate, invstate))

        if invstate == 3:
            EC = inverter.read_input_registers(40,1)
            if 1 <= EC <= 23: # No specific text defined
                errstr = "Error Code " + str(99+EC)
            else:
                errstr = errcodes[EC.registers[0]]
            print ("Inverter FAULT: %s" % errstr)

        laststate = invstate

    info["Ppv"] = float((rr.registers[1]<<16) + rr.registers[2])/10 # Input Power

    info["Vpv1"] = float(rr.registers[3])/10 # PV1 Voltage
    info["PV1Curr"] = float(rr.registers[4])/10 # PV1 Input Current
    info["PV1Watt"] = float((rr.registers[5]<<16) + rr.registers[6])/10 # PV1 input watt

    # PV2 would be the same, but I only have one string connected
    #info['Vpv2'] = float(rr.registers[7])/10
    #info['PV2Curr'] = float(rr.registers[8])/10
    #info['PV2Watt'] = float((rr.registers[9]<<16) + rr.registers[10])/10

    # Total outputs for the inverter
    info["Pac"] = float((rr.registers[11]<<16) + rr.registers[12])/10 # Output Power
    info["Fac"] = float(rr.registers[13])/100 # Grid Frequency

    # Single phase users just see the 1st set of these
    info["Vac1"] = float(rr.registers[14])/10 # Single Phase (L1) grid voltage
    info["Iac1"] = float(rr.registers[15])/10 # Single Phase (L1) grid output current
    info["Pac1"] = float((rr.registers[16]<<16) + rr.registers[17])/10 # Single Phase (L1) grid output watt

    #info['Vac2'] = float(rr.registers[18])/10 # L2 grid voltage
    #info['Iac2'] = float(rr.registers[19])/10 # L2 grid output current
    #info['Pac2'] = float((rr.registers[20]<<16) + rr.registers[21])/10 # L2 grid output watt

    #info['Vac3'] = float(rr.registers[22])/10 # L3 grid voltage
    #info['Iac3'] = float(rr.registers[23])/10 # L3 grid output current
    #info['Pac3'] = float((rr.registers[24]<<16) + rr.registers[25])/10 # L3 grid output watt

    info["Etoday"] = float((rr.registers[26]<<16) + rr.registers[27])/10 #electricity generated today
    info["Etotal"] = float((rr.registers[28]<<16) + rr.registers[29])/10 #electricity generated all time
    info["ttotal"] = float((rr.registers[30]<<16) + rr.registers[31])/2 # seconds
    info["Tinverter"] = float(rr.registers[32])/10  # Inverter temp

    #info["DateTime"] = datetime.datetime.now()

    #print (info)
    json_out=json.dumps(info)
    #mqttc.publish(topic + '/json', str(info))
    mqttc.publish(topic + '/json', json_out)
    #print (json_out)


  #except SerialException:
  except:
     print ('Serial Read Error?')
     #sleep for 10secs to avoid the error
     time.sleep(10)


  #sleep for 10 secs befiore repolling
  time.sleep(10)


# stop the mqtt client
mqttc.loop_stop()

# close the connection with the inverter
inverter.close()