# -*- coding: utf-8 -*-
# (c) 2015 Richard Pobering <einsiedlerkrebs@netfrag.org>
# (c) 2015-2016 Andreas Motl, Elmyra UG <andreas.motl@elmyra.de>
import sys
import serial
from pprint import pprint
from mqtt import BERadioMQTTAdapter
from beradio.decoder import jobee_decode
from beradio.protocol import BencodeError
from beradio.network import protocol_factory
from beradio.util import last_error_and_traceback

"""
Read data in Bencode format from serial port, decode and publish via MQTT.

Based on code from
- Andy Piper http://andypiper.co.uk [2011/09/15]
- Didier Donsez [2014‎/11/22]
  http://air.imag.fr/index.php/Mosquitto#Publication_en_Python

Synopsis::

  python serial_to_mqtt.py /dev/ttyUSB0 localhost
  python serial_to_mqtt.py /dev/ttyACM0 localhost

"""

class SerialToMQTT(object):

    def __init__(self, serial_device, mqtt_broker, mqtt_topic='hiveeyes', protocol=2):
        self.serial_device = serial_device
        self.mqtt_broker = mqtt_broker
        self.mqtt_topic = mqtt_topic
        self.protocol_class = protocol_factory(protocol)

    def setup(self):

        try:
            # connect to serial port
            print 'INFO:  Connecting to serial port device "{}"'.format(self.serial_device)
            #self.serial = serial.Serial(serial_device, 9600, timeout=20)
            self.serial = serial.Serial(self.serial_device, 115200)
        except:
            print 'ERROR: Failed to connect to serial port device "{}"'.format(self.serial_device)
            raise

        try:
            print 'INFO:  Connecting to MQTT broker "{}"'.format(self.mqtt_broker)
            self.mqtt = BERadioMQTTAdapter(self.mqtt_broker, topic=self.mqtt_topic)
        except:
            print 'ERROR: Failed to connect to MQTT broker "{}"'.format(self.mqtt_broker)
            raise

        return self

    def forward(self):

        try:
            self.serial.flushInput()

            # remain connected to broker
            # read data from serial and publish
            #while self.mqtt.mqttc.loop() == 0:

            # use mqtt.loop_forever() in a separate thread, this will handle
            # automatic reconnecting if connection to broker got lost
            self.mqtt.mqttc.loop_start()

            while True:

                print '-' * 42

                # read line from serial port
                # li999ei99ei1ei2218ei2318ei2462ei2250ee\0\n
                # li999ei99ei1ei2231ei2325ei2443ei2262ee\0\n
                line = self.serial.readline()
                line = line.strip('\r\n\0 ')

                # debug: output line to stdout
                print 'line: "{}"'.format(line)

                if line.startswith('#'):
                    continue

                # Decode from CSV format
                if ',' in line:
                    line = line.strip()
                    record = line.split(',')

                    #print 'record:'; pprint(record)

                    # Pop node id from first list element
                    nodeid = record.pop(0)

                    # Ignore empty datetime field
                    datetime = record.pop(0)

                    # The other elements are the data values
                    values = record

                    data = None

                    # Weight,Outside Temp,Outside Humid,Inside Temp,Inside Humid,H1 Temp,H2 Temp,H3 Temp,H4 Temp,H5 Temp,Voltage
                    if nodeid == '2':
                        keys = [
                            'weight',
                            'temp-outside', 'humidity-outside', 'temp-inside', 'humidity-inside',
                            'temp-h1', 'temp-h2', 'temp-h3', 'temp-h4', 'temp-h5', 'voltage'
                        ]
                        data = dict(zip(keys, values))

                    # Weight,Outside Temp,Outside Humid,Inside Temp,Inside Humid,Brood Temp,Voltage
                    elif nodeid == '3':
                        keys = [
                            'weight',
                            'temp-outside', 'humidity-outside', 'temp-inside', 'humidity-inside',
                            'temp-brood', 'voltage',
                        ]
                        data = dict(zip(keys, values))

                    else:
                        print 'ERROR: Could not decode payload from nodeid:', nodeid


                    if data:
                        #print 'data:'; pprint(data)

                        for key, value in data.iteritems():
                            data[key] = float(data[key])

                        # Build an appropriate message from CSV data
                        message = {
                            'meta': {
                                'network': self.protocol_class.network_id,
                                'gateway':self.protocol_class.gateway_id,
                                'node': nodeid,
                            },
                            'data': data
                        }
                        self.mqtt.publish_flexible(message)

                    continue


                # Decode JobeeMonitor line format
                # id=Danvou;lux=13940.88;bmpP=997.03;bmpT=20.32;topT=0;entryT=0;h=70.55;siT=19.38;rainLevel=2.24;RainFall=466;milli=332143870;
                if line.startswith('id=') and ';' in line:
                    data = jobee_decode(line)
                    nodeid = data['id']
                    del data['id']

                    # Build an appropriate message from Jobee data
                    message = {
                        'meta': {
                            'network': self.protocol_class.network_id,
                            'gateway':self.protocol_class.gateway_id,
                            'node': nodeid,
                            },
                        'data': data
                    }
                    self.mqtt.publish_flexible(message)

                    continue


                # Decode from Bencode format
                try:
                    data = self.protocol_class.decode(line)
                except BencodeError:
                    continue

                #print 'data:', data

                # publish to MQTT
                if data:
                    raw_sanitized = self.protocol_class.sanitize(line)

                    if self.protocol_class.VERSION == 1:
                        data = self.protocol_class.to_v2(data)

                    self.mqtt.publish_flexible(data, bencode_raw=raw_sanitized)

                #time.sleep(1)

            self.mqtt.mqttc.loop_stop()


        # handle list index error (i.e. assume no data received)
        except (IndexError):
            print "No data received within serial timeout period"
            self.cleanup()

        # handle app closure
        except (KeyboardInterrupt):
            print "Interrupt received"
            self.cleanup()

        except (RuntimeError):
            print "uh-oh! time to die"
            self.cleanup()

        except Exception as ex:
            print last_error_and_traceback()


    # called on exit
    # close serial, disconnect MQTT
    def cleanup(self):
        print "Ending and cleaning up"
        self.serial.close()
        self.mqtt.close()


if __name__ == '__main__':
    SerialToMQTT(serial_device=sys.argv[1], mqtt_broker=sys.argv[2]).setup().forward()
