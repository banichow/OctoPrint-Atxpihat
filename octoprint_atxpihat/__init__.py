# coding=utf-8
from __future__ import absolute_import

# **************** Contribution libraries and exampled **********************************
# ATXPiHat Hardware - Steve Smith - Xygax - https://www.facebook.com/Xygax
# PSUControl - Shawn Bruce - https://github.com/kantlivelong/
# LEDStripControl - https://github.com/google/OctoPrint-LEDStripControl
# pigpio - joan@abyz.me.uk - http://abyz.co.uk/rpi/pigpio/python.html
# Octoprint-ETA - Pablo Ventura - https://github.com/pablogventura/Octoprint-ETA
# Octoprint-Filament-Reloaded - Connor Huffine - https://github.com/kontakt/Octoprint-Filament-Reloaded
# DS18B20 Temperature sensor - https://pimylifeup.com/raspberry-pi-temperature-sensor/
# ***************************************************************************************

__author__ = "Brian Anichowski"
__license__ = "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
__plugin_license__ = "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
__copyright__ = "Copyright (C) 2018 Brian Anichowski http://www.baprojectworkshop.com"
__plugin_name__ = "ATXPiHat"
__plugin_version__ = "1.1.5"
__plugin_description__ = "ATXPiHat - https://baprojectworkshop.com"

import RPi.GPIO as GPIO
import inspect
import sys

try:
	import Adafruit_DHT
except ImportError:
	print('ATXPiHat - not able to import/find Adafruit_DHT')

import octoprint.plugin
from octoprint.server import user_permission
from octoprint.events import Events

import pigpio
import glob
import time
import thread
from . import MonitorPWM, ADCProcessor
from threading import Thread
from flask import make_response
from octoprint.util import RepeatedTimer
from octoprint.printer import PrinterInterface

# ------------------------------------------ General Class ------------------------------------------------
class ATXPiHat(octoprint.plugin.AssetPlugin,
			 octoprint.plugin.SettingsPlugin,
			 octoprint.plugin.ShutdownPlugin,
			 octoprint.plugin.StartupPlugin,
			 octoprint.plugin.ProgressPlugin,
			 octoprint.plugin.TemplatePlugin,
			 octoprint.plugin.EventHandlerPlugin,
			 octoprint.plugin.SimpleApiPlugin):

	IO4 = 4
	DEVICEDIR = '/sys/bus/w1/devices/'

	def __init__(self):
		self._settings = None
		self._pigpiod = None
		self._adafruitdhtavail = False
		self._ledcolors = dict(LEDRed=None, LEDGreen=None, LEDBlue=None)
		self._fanmonitor = None
		self._adc = None
		self._eporisecallback = None
		self._checkPSUTimer = None
		self._checkFanTimer = None
		self._checkVoltageTimer = None
		self._checkDHTTimer = None
		self._checkExtSwitchTimer = None
		self._currentExtSwitchState = False
		self._ampbaseline = 0.0
		self._smartboard = False
		self._rebaseline = 0
		self._filamentdetect = None
		self._checkDSTimer = None

	def _mylogger(self,message, forceinfo=False):			# this is to be able to change the logging without a large change

		outmsg = "{} {}".format(inspect.stack()[1][3],message)

		if self._settings is not None:
			if self._settings.getBoolean(['debuglogging']) or forceinfo:
				self._logger.info(outmsg)
			else:
				self._logger.debug(outmsg)
		else:
			print(message)

	def setLEDSvalues(self, workingleds, brightness):
		self._mylogger("called - {} - {}".format(workingleds,brightness))

		if self._settings.getBoolean(['UseLEDS']):
			ledon = True
		else:
			ledon = False

		for key, value in workingleds.iteritems():
			newkey = key + 'Pin'

			if brightness > 99:
				brightness = 100
			elif brightness < 1:
				brightness = 1

			pin = self._settings.getInt([newkey])
			self._mylogger('{} - {} - {} - {}'.format(key, newkey, value, pin))

			if not ledon or value < 0:
				keyval = 0
				realBrightness = 0
			else:
				realBrightness = int((float(value) * float(brightness)) / 100)

			self._mylogger('LED pwmcycle {}'.format(realBrightness))
			self._pigpiod.set_PWM_dutycycle(pin, realBrightness)

	def initialize_leds(self):
		self._mylogger("called")
		if not self._smartboard:
			self._mylogger("not smartboard exit")
			return

		if not self.ispowered():
			self._mylogger("not powered exiting")
			return

		workleds = dict()

		for key, value in self._ledcolors.iteritems():
			workleds[key] = self._settings.getInt([key])

		self.setLEDSvalues(workleds,self._settings.getInt(['LEDBrightness']))

	# this is needed to shutdown the driver fet TC4427 so that voltage leakage would not overheat the chips
	def shutdown_driverfets(self):
		self._mylogger("called")
		if not self._smartboard:
			self._mylogger("not smartboard exit")
			return

		# shutdown the external switch
		self.toggle_extswitch(True)

		#shutdown the LEDs
		workleds = dict()

		for key, value in self._ledcolors.iteritems():
			workleds[key] = 0

		self.setLEDSvalues(workleds, 0)

	def on_event(self, event, payload):
		self._mylogger("called {} {}".format(event,payload))

		if event is Events.PRINTER_STATE_CHANGED:
			if (payload["state_id"] == "OPEN_SERIAL" or payload["state_id"] == "DETECT_SERIAL") and not self.ispowered():
				self.turnon()
				return

			if (payload["state_id"] == "OPERATIONAL") and self._settings.getBoolean(['FilterTerminal']):
				self.sendmessage("filterterminal", 'true')
				return

		if self._settings.getBoolean(['IO4Enabled']) and \
				self._settings.get(['IO4Behaviour']).upper().startswith('FILAMENT') and \
				not self._printer.is_cancelling():
			if not self.hasfilament():
				self._mylogger("Printing aborted: no filament detected!")
				if event is Events.PRINT_STARTED:
					self._mylogger("Canceling print!")
					self._printer.cancel_print()
				elif event is Events.PRINT_RESUMED:
					self._mylogger("Pause print!")
					self._printer.pause_print()

				self.reportfilamentstate()

	def turnon(self):
		self._mylogger("called")
		epopin = self._settings.getInt(['EPOPin'])
		useepo = self._settings.getBoolean(['UseEPO'])
		onoffpin = self._settings.getInt(['OnOffSwitchPin'])

		if not self.ispowered():
			# this is for the new ATXPIHatZero
			if not self._smartboard:
				if useepo and not self._pigpiod.read(epopin):
					self.setepostatus(True)
					return

			if self._settings.getBoolean(['MonitorPower']) and self._smartboard:
				self.baseline()
				self._adc.resetchip()
			else:
				self._mylogger("Not monitoring power")

			self._pigpiod.write(onoffpin, 1)  # Turn on ps

			count = 0		# this is to wait until we have power applied and we can sense this.
			while True:
				if self.ispowered() or count > 20:
					break
				count = count + 1
				time.sleep(.2)

			# this is to support the ATXPiHatV1
			if useepo and not self._pigpiod.read(epopin):
				self._mylogger('EPO is pressed')
				self._pigpiod.write(onoffpin, 0)  # Turn off ps
				self.setepostatus(True)
				return
			else:
				self.setepostatus(False)

			self.reportfilamentstate(False)
			# these are called when things are running
			self.initialize_fan()
			if self._smartboard:
				self.initialize_extswitch()
				self.initialize_leds()

			time.sleep(5)	# this is used to make sure that Marlin has started and the connection can
							# sense the change to refresh the connection
			self.sendmessage("refreshconnection",None)

	def turnoff(self, forceoff=False):
		self._mylogger('called')

		if not self._pigpiod.connected:
			self._mylogger("pigpio is no longer connected", forceinfo=True)
			self._pigpiod = pigpio.pi()

		if self.ispowered() == 1:
			self.shutdown_driverfets()

			if self._printer.is_printing():
				self._printer.cancel_print()
				if not forceoff:
					time.sleep(2)

			if self._printer.is_operational():
				self._printer.disconnect()
				if not forceoff:
					time.sleep(1)

			self._pigpiod.write(self._settings.getInt(['OnOffSwitchPin']), 0)  # Turn off ps
			time.sleep(8)		#wait for the printer to come down before looking at the amperage results.
			self.initialize_power()
			self.reportfilamentstate()

		self.sendmessage("refreshconnection")

	def check_psu_state(self):
		#self._mylogger("check_psu_state called")

		if not self._pigpiod.connected:
			self._mylogger("pigpio is no longer connected", forceinfo=True)
			self._pigpiod = pigpio.pi()

		retval = "true" if self.ispowered() else "false"
		self.sendmessage("pwrstatus", retval)

	def ispowered(self):
		if not self._pigpiod.connected:
			self._mylogger("pigpio is no longer connected", forceinfo=True)
			self._pigpiod = pigpio.pi()

		sensepwrpin = self._pigpiod.read(self._settings.getInt(['SenseOnOffPin']))
		return True if sensepwrpin == 1 else False

	def initialize_extswitch(self):
		self._mylogger("called")
		if not self._smartboard:
			self._mylogger("not smartboard exit")
			return

		if not self.ispowered():
			self._mylogger("not powered exiting")
			return

		extswtpin = self._settings.getInt(['ExternalSwitchPin'])

		self._pigpiod.set_mode(extswtpin, pigpio.OUTPUT)
		actualstate = self._settings.getBoolean(['InitExtSwitchOn'])
		#UseExtSwitch
		if self._settings.getBoolean(['UseExtSwitch']):
			if self._settings.get(['ExternalSwitchBehaviour']).upper() == 'ONOFF':

				self._pigpiod.set_pull_up_down(extswtpin, pigpio.PUD_UP)
				if actualstate:
					self._pigpiod.write(extswtpin,1)
				else:
					self._pigpiod.write(extswtpin, 0)

			else:
				self._pigpiod.set_pull_up_down(extswtpin, pigpio.PUD_OFF)
				pwmvalue = self._settings.getInt(['ExternalSwitchValue'])

				if pwmvalue > 255:
					pwmvalue = 255
				elif pwmvalue < 0:
					pwmvalue = 0

				self._mylogger("Ext Switch pwmcycle %s " % pwmvalue)
				# InitExtSwitchOn
				if actualstate:
					self._pigpiod.set_PWM_dutycycle(extswtpin, pwmvalue)
				else:
					self._pigpiod.set_PWM_dutycycle(extswtpin, 0)
		else:

			self._pigpiod.set_PWM_dutycycle(extswtpin, 0)
			self._pigpiod.set_pull_up_down(extswtpin, pigpio.PUD_OFF)
			self._pigpiod.write(extswtpin, 0)

	def toggle_extswitch(self, forceoff=False):
		self._mylogger("called",True)
		if not self._smartboard:
			self._mylogger("not smartboard exit")
			return

		extswtpin = self._settings.getInt(['ExternalSwitchPin'])
		pwmvalue = self._settings.getInt(['ExternalSwitchValue'])

		if forceoff:  # this shuts everything down on the FET
			self._pigpiod.write(extswtpin, 0)
			self._pigpiod.set_PWM_dutycycle(extswtpin, 0)
			self._pigpiod.set_pull_up_down(extswtpin, pigpio.PUD_OFF)
			return

		if self.ispowered() == 1 and self._settings.getBoolean(['UseExtSwitch']):
			if self._settings.get(['ExternalSwitchBehaviour']).upper() == 'ONOFF':
				self._mylogger("Extswitchpin state %s " % self._pigpiod.read(extswtpin))
				if self._pigpiod.read(extswtpin) > 0:
					self._pigpiod.write(extswtpin,0)
					self._pigpiod.set_pull_up_down(extswtpin, pigpio.PUD_OFF)
				else:
					self._pigpiod.write(extswtpin, 1)
					self._pigpiod.set_pull_up_down(extswtpin, pigpio.PUD_UP)
			else:
				self._mylogger("Extswitchpin PWM duty cycle - %s " % self._pigpiod.get_PWM_dutycycle(extswtpin))
				if self._pigpiod.get_PWM_dutycycle(extswtpin) > 0:
					self._pigpiod.set_pull_up_down(extswtpin, pigpio.PUD_OFF)
					self._pigpiod.write(extswtpin, 0)
					pwmvalue = 0
				else:
					if pwmvalue > 255:
						pwmvalue = 255

				self._mylogger("Ext Switch pwmcycle %s " % pwmvalue)
				self._pigpiod.set_PWM_dutycycle(extswtpin, pwmvalue)

	def update_extswitchstate(self):
		self._mylogger("called")
		if not self._smartboard:
			self._mylogger("not smartboard exit")
			return

		extswtpin = self._settings.getInt(['ExternalSwitchPin'])

		if self.ispowered() == 1 and self._settings.getBoolean(['UseExtSwitch']):
			if self._settings.get(['ExternalSwitchBehaviour']).upper() == 'ONOFF':
				self._mylogger("ExtSwitch pin state {}".format(self._pigpiod.read(extswtpin)))
				if self._pigpiod.read(extswtpin) > 0:
					self._currentExtSwitchState = True
				else:
					self._currentExtSwitchState = False
			else:
				self._mylogger("ExtSwitch PWM duty cycle - {}".format(self._pigpiod.get_PWM_dutycycle(extswtpin)))
				if self._pigpiod.get_PWM_dutycycle(extswtpin) > 0:
					self._currentExtSwitchState = True
				else:
					self._currentExtSwitchState = False
		else:
			self._currentExtSwitchState = False

		self.sendmessage("extswitchpinstate",'true' if self._currentExtSwitchState else 'false',"")

	def initialize_epo(self):
		# due to design, I cannot sense the EPO pin properly until 12v is applied to the board
		# this is just setting the port up
		self._mylogger("called")
		epopin = self._settings.getInt(['EPOPin'])
		if self._eporisecallback is not None:
			self._eporisecallback.cancel()

		self._pigpiod.set_mode(epopin, pigpio.INPUT)
		self._pigpiod.set_glitch_filter(epopin, 400)
		self._pigpiod.set_pull_up_down(epopin, pigpio.PUD_UP)
		self.setepostatus(False)  # go set the default status of the EPO to on and "black"
		self._eporisecallback = self._pigpiod.callback(epopin, pigpio.EITHER_EDGE, self.epostatechange)

	def epostatechange(self, gpio, level, tick):
		self._mylogger("called")

		sensepwrpin = self._settings.getInt(['SenseOnOffPin'])
		if self._smartboard and self._pigpiod.read(sensepwrpin) == 0:
			return

		currentepostate = self._pigpiod.read(gpio)

		if self._settings.getInt(['UseEPO']):
			if currentepostate == 0:
				self._mylogger("EPO Pressed", forceinfo=True)
				self.setepostatus(True)

				if self._pigpiod.read(sensepwrpin) == 1:
					self.turnoff(True)

			elif currentepostate == 1:
				self._mylogger("EPO released", forceinfo=True)
				self.setepostatus(False)

	def setepostatus(self, currentstate):
		#true = engaged or 0
		#false = normal or 1
		self._mylogger("{}".format(currentstate))
		self.sendmessage("epoengaged",'true' if currentstate else 'false',"")

	def initialize_fan(self):
		self._mylogger("called")
		self._fanworking = 0
		if self._fanmonitor is not None:			# failsafe to make sure that everything is good.
			self._fanmonitor.cancel()

		self._fanmonitor = MonitorPWM.MonitorPWM(self._pigpiod, self._settings.getInt(['FanRPMPin']), self._mylogger)

	def check_fan_state(self):
		rpm = 0.0

		if not self._pigpiod.connected:
			return

		if not self.ispowered():			#if no power move on
			self.sendmessage("fanrpm", 0)
			return 0

		if self._settings.getBoolean(['MonitorFanRPM']):
			rpm = 0
			if self._fanmonitor is not None:
				rpm = self._fanmonitor.rpm()
				self._mylogger("rpm {}".format(rpm))
				self.sendmessage("fanrpm", rpm)

				if rpm < 1:						# This allows for three cycles before actually checking the fan
					self._mylogger('Tripped 0 fan rpm')
					self._fanworking = self._fanworking + 1
				else:
					self._fanworking = 0

				if self._fanworking > 0:
					self._mylogger('Fan fault count %s' % self._fanworking)

				if self._settings.getBoolean(['FanRPMFault']) and (rpm == 0 or rpm is None) and self._fanworking > 2:
					self._mylogger('Fan fault detected', forceinfo=True)
					self.sendmessage("fanrpmfault", 'true')
					self.turnoff()

	def baseline(self):
		self._mylogger("called")
		if not self._smartboard:
			return

		self.sendmessage("ampbaseline")
		if not self.ispowered() and self._settings.getBoolean(['MonitorPower']):
			self._adc.resetchip()

			sample = []
			for i in range(0, 6):
				sample.append(self._adc.read_amperage_baseline())

			self._mylogger("ampbaseline - {}".format(sample))
			self._ampbaseline = ATXPiHat._processsamples(sample)
			self._mylogger('Amperage Baseline {}'.format(self._ampbaseline))
		else:
			self._mylogger("Not monitoring power")

		self.sendmessage("ampbaselinecomp")

	def initialize_power(self):
		self._mylogger("called")

		if self._checkVoltageTimer is not None:
			self._checkVoltageTimer.cancel()

		if not self._smartboard:
			self._mylogger("not smartboard exit")
			return

		self._pigpiod.set_mode(self._settings.getInt(['OnOffSwitchPin']), pigpio.OUTPUT)  	# on/off
		self._pigpiod.set_mode(self._settings.getInt(['SenseOnOffPin']), pigpio.INPUT)  	# is supply on

		if self._adc is None:
			self._adc = ADCProcessor.ADCProcessor(self._mylogger, int(self._settings.get(['i2cAddress']), 16), self._settings.getInt(['i2cBus']))

		if not self.ispowered() and self._settings.getBoolean(['MonitorPower']):
			self.baseline()

		if self._settings.getBoolean(['MonitorPower']):
			self._checkVoltageTimer = ATXPiHat._settimer(self._checkVoltageTimer, self._settings.getInt(['ProcessTimer']), self.process_voltage)
		else:
			self._mylogger("Not monitoring power")

	@staticmethod
	def _processsamples(listobj):

		cleanlist = []
		for i in range(len(listobj)):
			cleanlist.append(abs(listobj[i]))

		cleanlist.remove(max(cleanlist))
		cleanlist.remove(min(cleanlist))
		return sum(cleanlist) / float(len(cleanlist))

	def process_voltage(self):
		self._mylogger("called")
		if not self._smartboard:
			self._mylogger("not smartboard exit")
			return

		self._adc.resetchip()
		sample = []

		for i in range(0, 6):
			sample.append(self._adc.read_amperage(self._ampbaseline))

		amperage = round(ATXPiHat._processsamples(sample),3)
		self._mylogger("amp sample {}".format(amperage))

		if self.ispowered():
			if amperage > self._settings.getInt(['MaxAmperage']):
				self._mylogger('Amperage fault detected - {}'.format(amperage), forceinfo=True)
				self._ampfault = self._ampfault + 1
			else:
				self._ampfault = 0

			if self._ampfault > 3:			# if it sees the fault 3 times, things are bad, forces printer shutdown
				self._mylogger('Amperage fault detected - shutting down', forceinfo=True)
				self.sendmessage("amperagefault", 'true')
				self.turnoff(True)
				self._ampfault = 0
				self.initialize_power()
				return
		else:
			if self._rebaseline > 200:
				self._mylogger("no power - rebaseline ")
				self.baseline()
				self._rebaseline = 0

			self._ampfault = 0
			self._rebaseline += 1

		voltage =  round(self._adc.read_voltage(self._settings.getFloat(['ReferenceVoltage'])),3)
		self._mylogger("volt sample %s " % voltage)

		self.sendmessage("atxvolts", amperage, voltage)

	def on_after_startup(self):
		self._mylogger("Starting ATXPiHatPlugin", forceinfo=True)

		if self._settings.getInt(['ProcessTimer']) < 4:
			self._settings.setInt(['ProcessTimer'],4)

		revision = GPIO.RPI_REVISION
		loop = 0
		self._mylogger('Connecting to pigpio......', forceinfo=True)
		# this whole thing is to deal with pigpiod not starting up in the correct order
		# no matter what I did, update-rc.d would not give it to me in the right order.
		while True:
			loop += 1
			try:
				self._pigpiod = pigpio.pi()
				if not self._pigpiod.connected:
					raise SystemError
				version = self._pigpiod.get_hardware_revision()
				self._mylogger('Connecting to pigpio complete', forceinfo=True)

				if revision != 2 and revision != 3:
					self._mylogger('ATXPiHat only supports Type 3 boards', forceinfo=True)
					raise EnvironmentError('ATXPiHat only supports Type 3 boards')
				else:
					self._mylogger('BCM board is type - {}'.format(version), forceinfo=True)

				break
			except EnvironmentError:
				raise
			except:
				self._mylogger('pigpiod is not started yet', forceinfo=True)
				time.sleep(1)

			if loop > 60:
				self._mylogger('timed out waiting on pigpiod', forceinfo=True)
				break

		# test for the ADAFruit Library
		self._mylogger('Looking for the ADAFruit Library', forceinfo=True)
		self._mylogger("loaded module {}".format(sys.modules));

		for key, value in sys.modules.items():

			if key.upper().startswith('ADAFRUIT'):
				self._mylogger('Found ADAFruit Library', forceinfo=True)
				self._adafruitdhtavail = True
				break

		if self._adafruitdhtavail is False:
			self._mylogger('ADAFruit Library is not found', forceinfo=True)


		self.detectsmartboard()
		self.initialize_all()

	def detectsmartboard(self):
		self._mylogger("called")
		addr = int(self._settings.get(['i2cAddress']),16)
		busaddr = self._settings.getInt(['i2cBus'])

		if addr != 0x68:
			self._mylogger("default i2cAddress is not 0x68", forceinfo=True)

		if busaddr != 1:
			self._mylogger("default i2cBus is not 1", forceinfo=True)

		self._smartboard = ADCProcessor.detectaddress(self._mylogger,  addr, busaddr)

		# this is used to swap between boards
		if not self._smartboard and self._settings.get(['BoardVersion']) != "1.00Z":			# force the extra ports off
			self._settings.set(['BoardVersion'],"1.00Z")
			self._settings.set(['UseLEDS'], False)
			self._settings.set(['UseExtSwitch'], False)
			self._settings.set(['MaxAmperage'],36)

		elif self._smartboard and self._settings.get(['BoardVersion']) != "1.00":				# future look at registry to detect board type
			self._settings.set(['BoardVersion'], "1.00")
			self._settings.set(['UseLEDS'], True)
			self._settings.set(['UseExtSwitch'], True)
			self._settings.set(['MaxAmperage'], 19)

		self._mylogger('smart device {}'.format('True' if self._smartboard else 'False'))

	@staticmethod
	def _settimer(timervar, timeval, methodcall, smartboard = True):
		worktimer = None

		if timervar is not None:
			timervar.cancel()

		if smartboard:
			worktimer = RepeatedTimer(timeval, methodcall, None, None, True)
			worktimer.start()

		return worktimer

	def initialize_all(self):
		self._mylogger("called")
		processtimer = self._settings.getInt(['ProcessTimer'])
		# Power status monitor
		self._checkPSUTimer = ATXPiHat._settimer(self._checkPSUTimer,processtimer, self.check_psu_state)

		self.initialize_fan()
		self.initialize_epo()

		# Fan status processing
		self._checkFanTimer = ATXPiHat._settimer(self._checkFanTimer, processtimer, self.check_fan_state, self._settings.getBoolean(['MonitorFanRPM']))

		if self._smartboard:
			self._mylogger("enabling smart devices")

			if self.ispowered():
				# external LEDS and switch setup
				self.initialize_leds()
				self.initialize_extswitch()

			# External Switch State processing
			self._checkExtSwitchTimer = ATXPiHat._settimer(self._checkExtSwitchTimer, processtimer, self.update_extswitchstate,self._settings.getBoolean(['UseExtSwitch']))

			# Amperage and voltage detection
			self.initialize_power()
		else:
			self.initializeIO4()

	def get_settings_defaults(self):
		self._mylogger("called")
		return dict(BoardVersion="1.00",
					LEDRed=0,
					LEDGreen=0,
					LEDBlue=0,
					LEDRedPin=23,
					LEDGreenPin=22,
					LEDBluePin=24,
					EPOPin=15,
					ExternalSwitchPin=27,
					ExternalSwitchValue=255,
					ExternalSwitchBehaviour='ONOFF',
					ExternalSwitchTriggerOn='M355 S1',
					ExternalSwitchTriggerOFF='M355 S0',
					DisplayPWROnStatusPanel=True,
					DisplayFanOnStatusPanel=True,
					InitExtSwitchOn=True,
					debuglogging=False,
					OnOffSwitchPin=17,
					SenseOnOffPin=18,
					LEDBrightness=100,
					UseEPO=False,
					UseLEDS=False,
					UseExtSwitch=False,
					PowerOffWarning=True,
					enablePowerOffWarningDialog=False,
					MonitorFanRPM=False,
					FanRPMPin=14,
					FanRPMFault=False,
					i2cAddress='0x68',
					i2cBus=1,					#we are using gpio pins 2 and 3
					MonitorPower=True,
					ReferenceVoltage=12.289,
					ProcessTimer = 2,
					MaxAmperage=19,
					RemoveLogo=False,
					FilamentEmptyState=1,			#0 = has filament, 1=does not
					FilamentSupressDialog=False,
					DisplayFilamentStatusPanel=True,
					DisplayTemperatureOnStatusPanel=True,
					TemperatureMeasurement="F",
					IO4Enabled=False,
					IO4Behaviour='FILAMENT2',
					#DHTHasResistor=True,
					#DHTResistorFactor=0.9387915,
					FilamentChangeScript='',
					FilterTerminal=False)

	def on_settings_save(self, data):
		self._mylogger("called")
		# Cannot update the screen faster than every 2 seconds
		# The amperage and voltage readings can take some time to come back
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		self._mylogger("before - Processtimer %s" % self._settings.getInt(['ProcessTimer']))
		if self._settings.getInt(['ProcessTimer']) < 4:
			self._settings.setInt(['ProcessTimer'],4)
		self._mylogger("after - Processtimer %s" % self._settings.getInt(['ProcessTimer']))

		# with newer board variations we will have to figure out how to detect this to set the upper limit
		maxamp = self._settings.getInt(['MaxAmperage'])
		if maxamp < 1:
			maxamp = 99

		if self._smartboard and maxamp > 19:
			self._settings.setInt(['MaxAmperage'], 19)
		elif not self._smartboard and maxamp > 36:
			self._settings.setInt(['MaxAmperage'], 36)

		self.detectsmartboard()
		self.initialize_all()
		self._mylogger("calling updatestatusbox")
		self.sendmessage("updatestatusbox")

		if self.ispowered():
			self._mylogger("calling FilterTerminal")
			self.sendmessage("filterterminal",'true' if self._settings.getBoolean(['FilterTerminal']) else 'false')

		if self._smartboard or not self._settings.getBoolean(['IO4Enabled']):
			self.sendmessage(self._identifier, "removetemp")

		self._mylogger("calling backgroundimage")
		self.sendmessage("backgroundimage",'true' if self._settings.getBoolean(['RemoveLogo']) else 'false')

	def sendmessage(self, message, extfield1=None, extfield2=None):
		self._plugin_manager.send_plugin_message(self._identifier,dict(msg=message,field1=extfield1,field2=extfield2))

	def get_template_configs(self):
		self._mylogger("called")
		return [
			dict(type='settings', custom_bindings=True, template='atxpihat_settings.jinja2'),
			dict(type='navbar', custom_bindings=True, template='atxpihat_navbar_epo.jinja2'),
			dict(type='navbar', custom_bindings=True, template='atxpihat_navbar_pwr.jinja2', classes=['dropdown']),
			dict(type='tab', custom_bindings=True)
		]

	def get_api_commands(self):
		self._mylogger("called")
		return dict(
			updateLED=['LEDRed', 'LEDGreen', 'LEDBlue', 'LEDBrightness'],
			updateExtSwitch=['ExternalSwitchValue'],
			turnATXPSUOn=[],
			turnATXPSUOff=[],
			ToggleExtSwitch=[],
			IsSmartBoard=[],
			RefreshFilamentStatus=[]
		)

	def on_api_command(self, command, data):
		self._mylogger("called - {}".format(command), forceinfo=True)

		if not user_permission.can():
			self._mylogger("Insufficient rights {}".format(command), forceinfo=True)
			return make_response("Insufficient rights", 403)

		cmd = command.lower()
		if cmd == 'refreshfilamentstatus' :
			self._mylogger("Filament status update call")
			self.reportfilamentstate()

		if cmd == 'turnatxpsuoff':
			self._mylogger("Turned Off Supply")
			self.turnoff()

		if cmd == 'turnatxpsuon':
			self._mylogger("Turned On Supply")
			self.turnon()

		if cmd == 'issmartboard':
			smartflag = 'true' if self._smartboard else 'false'
			self._mylogger("sending IsSmartBoard {} ".format(smartflag), forceinfo=True)
			return make_response(smartflag)

		if not self._smartboard:
			return

		if cmd == "toggleextswitch":
			self._mylogger("Toggle External Switch")
			self.toggle_extswitch()

		if cmd == 'updateextswitch':
			self._mylogger("Update External Switch PWM value")
			data.pop('command', 0)
			self._settings.set(['ExternalSwitchValue'], int(data['ExternalSwitchValue']))
			self._settings.save()
			self.initialize_extswitch()

		if cmd == 'updateled' and self._settings.getBoolean(['UseLEDS']):
			if data['LEDRed'] > -1 and data['LEDGreen'] > -1 and data['LEDBlue'] > -1:
				self._mylogger("Status Sent - {LEDRed} - {LEDGreen} - {LEDBlue}".format(**data))
				data.pop('command', 0)
				self._settings.set(['LEDRed'], int(data['LEDRed']))
				self._settings.set(['LEDGreen'], int(data['LEDGreen']))
				self._settings.set(['LEDBlue'], int(data['LEDBlue']))
				self._settings.set(['LEDBrightness'], int(data['LEDBrightness']))
				self._settings.save()
				self.initialize_leds()

	def on_shutdown(self):
		self._mylogger("called", forceinfo=True)

		self.turnoff(True)
		self._pigpiod.stop()

	def get_assets(self):
		self._mylogger("called")
		return dict(
			js=["js/atxpihat.js"],
			css=["css/atxpihat.css"]
		)

	def get_settings_version(self):
		self._mylogger("called")
		return 2

	def processfilamentevent(self, gpio, level, tick):
		self._mylogger("called result {} == OK state {}".format(level, self._settings.getInt(['FilamentEmptyState'])))
		if self._smartboard and self._filamentdetect is not None:
			self._filamentdetect.cancel()
			self._filamentdetect = None
			return

		if not self.hasfilament() and self._printer.is_printing():
			self._printer.pause_print()
			fogc = str(self._settings.get(["FilamentChangeScript"])).splitlines()
			if fogc:
				self._mylogger("Sending Gcode script to handle filament out {}".format(fogc))
				self._printer.commands(fogc)

		self.reportfilamentstate()

	def reportfilamentstate(self, dialog=True):
		self._mylogger("called")

		if self._smartboard or not self._settings.getBoolean(['IO4Enabled']):
			return

		ioporttype = self._settings.get(['IO4Behaviour']).upper()

		state = None

		if ioporttype.startswith('FILAMENT'):

			msg = None
			suppress = self._settings.getBoolean(['FilamentSupressDialog'])
			loadedfilament = True if self._settings.getInt(['FilamentEmptyState']) == self._pigpiod.read(ATXPiHat.IO4) else False;
			power = self.ispowered()

			if ioporttype == 'FILAMENT3' and not power:
				msg = "(NA)"
				state = "na"
			elif ((ioporttype == 'FILAMENT3' and power) or (ioporttype == 'FILAMENT2')) and loadedfilament:
				msg = "(GOOD)"
				state = "good"
			else:
				msg = "(OUT) - dialog {} - FilamentSupressDialog {}".format(dialog,suppress)
				if not self._printer.is_printing():
					state = "outnodialog"
				elif suppress:
					state = "outnodialog"
				elif dialog:
					state = "out"
				else:
					state = "outnodialog"

			self._mylogger("power ({}), msg ({}), suppress ({}), ioporttype ({})".format(power,msg,suppress,ioporttype))
			self.sendmessage("filamentstatus", state)

	def hasfilament(self):
		self._mylogger("called")
		ioporttype = self._settings.get(['IO4Behaviour']).upper()

		if self._smartboard or (not self._settings.getBoolean(['IO4Enabled']) and not ioporttype.startswith('FILAMENT')):
			return True

		if ioporttype == 'FILAMENT3' and not self.ispowered():
			return True

		try:
			if not self._pigpiod.connected:
				self._mylogger("pigpio is no longer connected", forceinfo=True)
				self._pigpiod = pigpio.pi()

			return True if self._settings.getInt(['FilamentEmptyState']) == self._pigpiod.read(ATXPiHat.IO4) else False
		except:
			self._mylogger("some sort of error {}".format(sys.exc_info()[0]), forceinfo=True)
			return True

	def initializeIO4(self):
		self._mylogger("called")

		if self._smartboard:
			self._mylogger("IO4 not supported on current 1.0 smartboard")
			return

		if self._filamentdetect is not None:
			self._filamentdetect.cancel()
		if self._checkDHTTimer is not None:
			self._checkDHTTimer.cancel()
		if self._checkDSTimer is not None:
			self._checkDSTimer.cancel()

		if self._adafruitdhtavail is False:
			self._settings.setBoolean(['IO4Enabled'],False)
			return

		if not self._settings.getBoolean(['IO4Enabled']):
			self._mylogger("IO4 is disabled")
			return

		behaviour = self._settings.get(['IO4Behaviour']).upper()
		self._mylogger("Configuration Type {}".format(behaviour))

		if behaviour.startswith('FILAMENT'):
			self._pigpiod.set_mode(ATXPiHat.IO4, pigpio.INPUT)
			self._pigpiod.set_glitch_filter(ATXPiHat.IO4, 400)
			self.reportfilamentstate()
			self._filamentdetect = self._pigpiod.callback(ATXPiHat.IO4, pigpio.EITHER_EDGE, self.processfilamentevent)
		elif behaviour.startswith('DHT'):
			if self._adafruitdhtavail:
				self._checkDHTTimer = ATXPiHat._settimer(self._checkDHTTimer, self._settings.getInt(['ProcessTimer']), self.process_dhttemp)
		elif behaviour.startswith('DS18B20'):
			self._checkDSTimer = ATXPiHat._settimer(self._checkDSTimer, self._settings.getInt(['ProcessTimer']), self.process_dstemp)

	def process_dhttemp(self):

		if not self._pigpiod.connected:
			return

		if not self.ispowered():			#if no power move on
			self.sendmessage("updatetemp", "N/A", "N/A")
			return

		if self._adafruitdhtavail is False:
			self._mylogger('checkonadafruitlib returned a false', forceinfo=True)
			return

		behaviour = self._settings.get(['IO4Behaviour']).upper()
		self._mylogger("behavior {}".format(behaviour))

		if behaviour == "DHT11":
			sensor = Adafruit_DHT.DHT11
		elif behaviour == "DHT22":
			sensor = Adafruit_DHT.DHT22
		else:
			self._mylogger("invalid type {}".format(behaviour))
			return

		if self.ispowered():
			humidity, temperature = Adafruit_DHT.read_retry(sensor, ATXPiHat.IO4)
		else:
			humidity = 0.0
			temperature = 0.0

		self._mylogger("temp {} humidity {}".format(temperature,humidity))

		forc = self._settings.get(['TemperatureMeasurement']).upper()
		if forc == "F" and temperature > 0.0:
			temperature = temperature * 1.8 + 32.0

		#if self._settings.getBoolean(['DHTHasResistor']):
		#	temperature = temperature * float(self._settings.get(['DHTResistorFactor']))

		if temperature > 0.0:
			if self._settings.getBoolean(['DHTHasResistor']):
				temperature = temperature - (temperature * .065)
			temp = "{0:.2f}".format(round(temperature,2))
		else:
			temp = "N/A"

		if humidity > 0.0:
			hum = "{0:.2f}%".format(round(humidity, 2))
		else:
			hum = "N/A"

		self._mylogger("final - temp {} humidity {}".format(temp, hum))
		self.sendmessage("updatetemp", temp, hum)

	@staticmethod
	def read_ds_temp_raw(device_file):
		try:
			f = open(device_file + '/w1_slave', 'r')
			lines = f.readlines()
			f.close()
			return lines
		except IOError:
			return None

	def process_dstemp(self):

		if self.ispowered():
			device = glob.glob( ATXPiHat.DEVICEDIR + '28*')
			if len(device) < 1:
				self._mylogger("Sensor is not found in {}".format(ATXPiHat.DEVICEDIR))
				return
			elif len(device) > 1:
				self._mylogger("more that one sensor was found {}".format(device))
				return

			self._mylogger("Processing data from {}".format(device[0]))
			lines = ATXPiHat.read_ds_temp_raw(device[0])
			if lines is None:
				self._mylogger("returned nothing from the {}".format(device[0]))
				return

			self._mylogger("temp raw {}".format(lines))

			try:
				equals_pos = -1
				count = 40
				while lines[0].strip()[-3:] != 'YES' and count > 0: # 8 seconds max loop to get value
					count = count - 1
					time.sleep(0.2)
					lines = ATXPiHat.read_ds_temp_raw(device[0])
			except:
				count = 0
				self._mylogger("Error during reading of 1 wire read")

			if count > 0:
				equals_pos = lines[1].find('t=')

			if equals_pos != -1:
				forc = self._settings.get(['TemperatureMeasurement']).upper()
				temperature = float(lines[1][equals_pos + 2:])
				self._mylogger("temp {}".format(temperature))
				temperature = (temperature / 1000.0)
				if forc == "F" and temperature > 0.0:
					temperature = temperature * 1.8 + 32.0

				self._mylogger("temp {}".format(temperature))
			else:
				temperature = 0.0
				self._mylogger("no value returned")

			if temperature > 0.0:
				temp = "{0:.2f}".format(round(temperature,2))
			else:
				temp = "N/A"

			self._mylogger("final - temp {}".format(temp))
		else:
			temp = 'N/A'

		self.sendmessage("updatetemp", temp, 'N/A')


	def HandleMarlin(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		name = 'ATXPiHat HandleMarlin'
		if not self._smartboard or not self.ispowered():
			return

		workcmd = cmd.upper()

		if gcode:
			if workcmd.startswith("M150"):
				self._mylogger('{} LED command encounter - {}'.format(name,cmd),forceinfo=True)

				workleds = dict()
				workval = workcmd.split()
				self._mylogger("{} - LED Command {}".format(name,workval), forceinfo=True)
				for i in workval:
					firstchar = str(i[0].upper())
					leddata = str(i[1:].strip())
					self._mylogger("{} {}".format(firstchar,leddata))
					if not leddata.isdigit():
						self._mylogger("{} - LED command encounter a badly formatted value {} - {}".format(name, cmd, leddata), forceinfo=True)
						return

					if firstchar == 'M':
						continue
					elif firstchar == 'R':
						workleds['LEDRed'] = int(leddata)
					elif firstchar == 'B':
						workleds['LEDBlue'] = int(leddata)
					elif firstchar == 'G' or firstchar == 'U':
						workleds['LEDGreen'] = int(leddata)
					else:
						self._mylogger("{} - LED command encounter wrong value {}".format(name, leddata), forceinfo=True)

				if len(workleds) is not 3:
					self._mylogger("{} - LED command encounter missing value {}".format(name, workleds), forceinfo=True)
					return

				self.setLEDSvalues(workleds, self._settings.getInt(['LEDBrightness']))

			if workcmd.startswith(self._settings.get(['ExternalSwitchTriggerOn']).upper()):
				self._mylogger("{} - Ext Switch On command encounter - {}".format(name, cmd),forceinfo=True)
				self.toggle_extswitch(True)
				self.toggle_extswitch()

			if workcmd.startswith(self._settings.get(['ExternalSwitchTriggerOFF']).upper()):
				self._mylogger("{} - Ext Switch Off command encounter - {}".format(name, cmd),forceinfo=True)
				self.toggle_extswitch(True)

	def get_update_information(self):
		return dict(
			psucontrol=dict(
				displayName="ATXPiHat",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="banichow",
				repo="OctoPrint-Atxpihat",
				current=self._plugin_version,

				# update method: pip w/ dependency links
				pip="https://github.com/banichow/OctoPrint-Atxpihat/archive/{target_version}.zip"
			)
		)


def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = ATXPiHat()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.HandleMarlin

	}
