
import smbus2 as smbus
import time

__author__ = 'Brian Anichowski'
__version__ = '1.0.0'
__license__ = 'Creative Commons'

class ADCProcessor(object):

	_lsb = {3: 62.5e-6, 4: 15.625e-6}

	def __init__(self, logger, address = 0x68, busaddress = 1):
		self._ampconfig = 0b10001001			# Channel 0
		self._voltconfig = 0b10101001			# Channel 1
		self._readbytes = 3
		self._mcpaddress = address
		self._busaddress = busaddress
		self._logger = logger

	def readbus(self, config, measurename):
		self._logger("ADC.readbus called - {} config {}".format(measurename,config))
		localsmbus = smbus.SMBus(self._busaddress)
		localsmbus.write_byte(0, 4)  # Clears the bus
		localsmbus.write_byte(self._mcpaddress, config)
		time.sleep(.4)		# this is to wait for the read to complete

		while True:
			v = localsmbus.read_i2c_block_data(self._mcpaddress, config, self._readbytes)
			self._logger("ADC.readbus {} value {}".format(measurename, v))
			if v[-1] == config:
				break
			else:
				self._logger("ADC.readbus {} RETRY did not get back correct config".format(measurename))
				time.sleep(.4)

		localsmbus.close()

		count = 0
		for i in range(self._readbytes - 1):
			count <<= 8
			count |= v[i]

		self._logger("ADC.readbus {} byte shifted {}".format(measurename,count))
		retval = (count * self._lsb[self._readbytes]) / 2
		self._logger("ADC.readbus {} final {}".format(measurename,retval))
		return retval

	def read_voltage(self, offset = 12.289):
		self._logger("ADC.read_voltage called - (offset) %s" % offset)
		retval = self.readbus(self._voltconfig,"Voltage") * offset
		self._logger("ADC.read_voltage complete - %s" % retval)
		return round(retval, 3)

	def read_amperage_baseline(self):
		self._logger("ADC.read_amperage_baseline called")
		retval = abs(self.readbus(self._ampconfig, "Baseline"))

		self._logger("ADC.read_amperage_baseline complete - %s" % retval)
		return retval

	def read_amperage(self, baseline = 0):
		self._logger("ADC.read_amperage called - (baseline) %s" % baseline)
		retval = abs(self.readbus(self._ampconfig, "Amperage") - baseline) * 2000

		self._logger("ADC.read_amperage complete - %s" % retval)
		return round(retval,3)

