
import smbus2 as smbus
import time
from enum import Enum

__author__ = 'Brian Anichowski'
__license__ = "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
__copyright__ = "Copyright (C) 2018 Brian Anichowski http://www.baprojectworkshop.com"
__version__ = "1.1.2"

class SampleType(Enum):
	Voltage = 1,
	Amperage = 2,
	AmpBaseLine = 3

class ADCProcessor(object):

	_lsb = {3: 62.5e-6, 4: 15.625e-6}
	_debug = False
	_delayread = .4
	_resetchipcounter = 0

	def __init__(self, logger, address = 0x68, busaddress = 1, debug = False):
		self._ampconfig = 0b10001001			# Channel 0
		self._voltconfig = 0b10101001			# Channel 1
		self._resetcall = 0b00000110			# 06h
		self._null = 0b00000000
		self._readbytes = 3
		self._mcpaddress = address
		self._busaddress = busaddress
		self._logger = logger
		self._debug = debug

	def resetchip(self):
		self._logger("ADC.resetchip called",self._debug)
		localsmbus = smbus.SMBus(self._busaddress)
		localsmbus.write_i2c_block_data(self._mcpaddress, 0x0, [self._resetcall])
		localsmbus.close()
		time.sleep(1)


	def readbus(self, config, sampletype):
		if not isinstance(sampletype, SampleType):
			raise TypeError('sample type for readbus is invalid!')

		self._logger("ADC.readbus called - {} config {}".format(sampletype.name,config),self._debug)

		localsmbus = smbus.SMBus(self._busaddress)
		localsmbus.write_byte(0, 4)  # Clears the bus
		localsmbus.write_byte(self._mcpaddress, config)
		time.sleep(self._delayread)		# this is to wait for the read to complete

		while True:
			v = localsmbus.read_i2c_block_data(self._mcpaddress, config, self._readbytes)
			self._logger("ADC.readbus {} value {}".format(sampletype.name, v), self._debug)
			if v[-1] == config:
				break
			else:
				self._logger("ADC.readbus {} RETRY did not get back correct config".format(sampletype.name), self._debug)
				time.sleep(self._delayread)

		localsmbus.close()

		count = 0
		for i in range(self._readbytes - 1):
			if sampletype == SampleType.Voltage:  # this is the deal with issues of the chip reading - for voltage
				if (i == 0 or i == 1) and v[i] == 255:
					self._resetchipcounter += 1
					v[i] = 0
			count <<= 8
			count |= v[i]

		self._logger("ADC.readbus {} byte shifted {}".format(sampletype.name,count),self._debug)
		retval = (count * self._lsb[self._readbytes]) / 2
		self._logger("ADC.readbus {} final {}".format(sampletype.name,retval),self._debug)
		return retval

	def read_voltage(self, offset = 12.289):
		self._logger("ADC.read_voltage called - (offset) {}".format(offset),self._debug)
		retval = self.readbus(self._voltconfig,SampleType.Voltage) * offset

		self._logger("ADC.read_voltage complete - %s" % retval,self._debug)
		return round(retval, 3)

	def read_amperage_baseline(self):
		self._logger("ADC.read_amperage_baseline called",self._debug)
		retval = abs(self.readbus(self._ampconfig, SampleType.AmpBaseLine))

		self._logger("ADC.read_amperage_baseline complete - %s" % retval,self._debug)
		return retval

	def read_amperage(self, baseline = 0):
		self._logger("ADC.read_amperage called - (baseline) %s" % baseline,self._debug)

		retval = abs(self.readbus(self._ampconfig, SampleType.Amperage) - baseline) * 2000

		self._logger("ADC.read_amperage complete - %s" % retval,self._debug)
		return round(retval,3)


def detectaddress(logger, address = 0x68 , busaddress = 1):

	try:
		logger("detectaddress - after try")
		localsmbus = None
		logger("detectaddress - after localsmbus = None")
		localsmbus = smbus.SMBus(busaddress)
		logger("detectaddress - after smbus.SMBus(busaddress)")
		localsmbus.read_byte(address)
		logger("detectaddress - smartboard - True")
		return True
	except:
		logger("detectaddress - smartboard - False")
		return False
	finally:
		if localsmbus is not None:
			localsmbus.close()

