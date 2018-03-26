# coding=utf-8
from __future__ import absolute_import

# **************** Contribution libraries and exampled **********************************
# ATXPiHat Hardware - Steve Smith - Xygax - https://www.facebook.com/Xygax
# PSUControl - Shawn Bruce - https://github.com/kantlivelong/
# LEDStripControl - https://github.com/google/OctoPrint-LEDStripControl
# pigpio - joan@abyz.me.uk - http://abyz.co.uk/rpi/pigpio/python.html
# Octoprint-ETA - Pablo Ventura - https://github.com/pablogventura/Octoprint-ETA
# ***************************************************************************************

__author__ = "Brian Anichowski"
__license__ = "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
__plugin_license__ = "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
__copyright__ = "Copyright (C) 2018 Brian Anichowski http://www.baprojectworkshop.com"
__plugin_name__ = "ATXPiHat"
__plugin_version__ = "1.0.6"
__plugin_description__ = "ATXPiHat - http://www.baprojectworkshop.com"

import RPi.GPIO as GPIO
import logging
import octoprint.plugin
from octoprint.server import user_permission
import pigpio
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
			 octoprint.plugin.SimpleApiPlugin):

	def __init__(self):
		self._settings = None
		self._pigpiod = None

		revision = GPIO.RPI_REVISION

		loop = 0
		# this whole thing is to deal with pigpiod not starting up in the correct order
		# no matter what I did, update-rc.d would not give it to me in the right order.
		while True:
			loop += 1
			try:
				self._pigpiod = pigpio.pi()
				if not self._pigpiod.connected:
					raise SystemError
				version = self._pigpiod.get_hardware_revision()

				if revision <> 2 and revision <> 3:
					self._mylogger('ATXPiHat only supports Type 3 boards', forceinfo=True)
					raise EnvironmentError('ATXPiHat only supports Type 3 boards')
				else:
					self._mylogger('ATXPiHat BCM board is type - {}'.format(version), forceinfo=True)

				break
			except EnvironmentError:
				raise
			except:
				self._mylogger('ATXPiHat - pigpiod is not started yet', forceinfo=True)
				time.sleep(1)

			if loop > 60:
				self._mylogger('ATXPiHat - timed out waiting on pigpiod', forceinfo=True)
				break

		self._ledcolors = dict(LEDRed=None, LEDGreen=None, LEDBlue=None)
		self._fanmonitor = None
		self._adc = None
		self._eporisecallback = None
		self._checkPSUTimer = None
		self._checkFanTimer = None
		self._checkVoltageTimer = None
		self._checkExtSwitchTimer = None
		self._currentExtSwitchState = False
		self._ampbaseline = 0.0
		self._smartboard = False

	def _mylogger(self,message, forceinfo=False):			# this is to be able to change the logging without a large change

		if self._settings is not None:
			if self._settings.getBoolean(['debuglogging']) or forceinfo:
				self._logger.info(message)
			else:
				self._logger.debug(message)
		else:
			print(message)

	def setLEDSvalues(self, workingleds, brightness):
		self._mylogger("ATXPiHat setLEDSvalues() - {} - {}".format(workingleds,brightness))

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
			self._mylogger('ATXPiHat setLEDSvalues() {0} - {1} - {2} - {3}'.format(key, newkey, value, pin))

			if not ledon or value < 0:
				keyval = 0
				realBrightness = 0
			else:
				realBrightness = int((float(value) * float(brightness)) / 100)

			self._mylogger('LED pwmcycle {}'.format(realBrightness))
			self._pigpiod.set_PWM_dutycycle(pin, realBrightness)

	def initialize_leds(self):
		self._mylogger(u"ATXPiHat initialize_leds()")
		if not self._smartboard:
			self._mylogger("ATXPiHat initialize_leds() - not smartboard exit")
			return

		if not self.ispowered():
			self._mylogger("ATXPiHat initialize_leds - not powered exiting")
			return

		workleds = dict()

		for key, value in self._ledcolors.iteritems():
			workleds[key] = self._settings.getInt([key])

		self.setLEDSvalues(workleds,self._settings.getInt(['LEDBrightness']))

	#def on_print_progress(self, storage, path, progress):
	#	self._mylogger("ATXPiHat - on_print_progress called")

	# this is needed to shutdown the driver fet TC4427 so that voltage leakage would not overheat the chips
	def shutdown_driverfets(self):
		self._mylogger(u"ATXPiHat shutdown_driverfets()")
		if not self._smartboard:
			self._mylogger("ATXPiHat shutdown_driverfets - not smartboard exit")
			return

		# shutdown the external switch
		self.toggle_extswitch(True)

		#shutdown the LEDs
		workleds = dict()

		for key, value in self._ledcolors.iteritems():
			workleds[key] = 0

		self.setLEDSvalues(workleds, 0)

	def turnon(self):
		self._mylogger("ATXPiHat - turnon called")
		epopin = self._settings.getInt(['EPOPin'])
		useepo = self._settings.getBoolean(['UseEPO'])
		onoffpin = self._settings.getInt(['OnOffSwitchPin'])

		if not self.ispowered():
			self._pigpiod.write(onoffpin, 1)  # Turn on ps

			count = 0		# this is to wait until we have power applied and we can sense this.
			while True:
				if self.ispowered() or count > 20:
					break
				count = count + 1
				time.sleep(.2)

			if useepo and not self._pigpiod.read(epopin):
				self._mylogger('ATXPiHat - turnon called - EPO is pressed')
				self._pigpiod.write(onoffpin, 0)  # Turn off ps
				self.setepostatus(True)
				return
			else:
				self.setepostatus(False)

			# these are called when things are running
			self.initialize_fan()
			if self._smartboard:
				self.initialize_extswitch()
				self.initialize_leds()

			time.sleep(5)	# this is used to make sure that Marlin has started and the connection can
							# sense the change to refresh the connection
			self._plugin_manager.send_plugin_message(self._identifier, dict(msg="refreshconnection"))

	def turnoff(self, forceoff=False):
		self._mylogger('ATXPiHat - turnoff called')

		if not self._pigpiod.connected:
			self._mylogger(u"ATXPiHat turnoff - pigpio is no longer connected", forceinfo=True)
			self._pigpiod = pigpio.pi()

		if self.ispowered() == 1:
			self.shutdown_driverfets()

			if self._printer.is_printing():
				self._printer.cancel_print()
				if not forceoff:
					time.sleep(2)

			if self._printer.is_operational():
				self._printer.disconnect();
				if not forceoff:
					time.sleep(1)

			self._pigpiod.write(self._settings.getInt(['OnOffSwitchPin']), 0)  # Turn off ps
			time.sleep(2)
			self.initialize_power()

		self._plugin_manager.send_plugin_message(self._identifier, dict(msg="refreshconnection"))

	def check_psu_state(self):
		self._mylogger("ATXPiHat check_psu_state called")

		if not self._pigpiod.connected:
			self._mylogger("ATXPiHat - pigpio is no longer connected", forceinfo=True)
			self._pigpiod = pigpio.pi()

		retval = "true" if self.ispowered() else "false"
		self._mylogger("ATXPiHat - check_psu_state - {}".format(retval))
		self._plugin_manager.send_plugin_message(self._identifier, dict(msg="pwrstatus", field1=retval))

	def ispowered(self):
		if not self._pigpiod.connected:
			self._mylogger(u"ATXPiHat - pigpio is no longer connected", forceinfo=True)
			self._pigpiod = pigpio.pi()

		sensepwrpin = self._pigpiod.read(self._settings.getInt(['SenseOnOffPin']))
		return True if sensepwrpin == 1 else False

	def initialize_extswitch(self):
		self._mylogger("ATXPiHat initialize_extswitch")
		if not self._smartboard:
			self._mylogger("ATXPiHat initialize_extswitch - not smartboard exit")
			return

		if not self.ispowered():
			self._mylogger("ATXPiHat initialize_extswitch - not powered exiting")
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

				self._mylogger(u"Ext Switch pwmcycle %s " % pwmvalue)
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
		self._mylogger("ATXPiHat toggle_extswitch called",True)
		if not self._smartboard:
			self._mylogger("ATXPiHat toggle_extswitch - not smartboard exit")
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

				self._mylogger(u"Ext Switch pwmcycle %s " % pwmvalue)
				self._pigpiod.set_PWM_dutycycle(extswtpin, pwmvalue)

	def update_extswitchstate(self):
		self._mylogger("ATXPiHat update_extswitchstate called")
		if not self._smartboard:
			self._mylogger("ATXPiHat update_extswitchstate - not smartboard exit")
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

		self._plugin_manager.send_plugin_message(self._identifier,
												 dict(msg="extswitchpinstate",
													  field1='true' if self._currentExtSwitchState else 'false',
													  field2=""))

	def initialize_epo(self):
		# due to design, I cannot sense the EPO pin properly until 12v is applied to the board
		# this is just setting the port up
		self._mylogger("ATXPiHat initialize_epo")
		epopin = self._settings.getInt(['EPOPin'])
		if self._eporisecallback is not None:
			self._eporisecallback.cancel()

		self._pigpiod.set_mode(epopin, pigpio.INPUT)
		self._pigpiod.set_glitch_filter(epopin, 400)
		self._pigpiod.set_pull_up_down(epopin, pigpio.PUD_UP)
		self.setepostatus(False)  # go set the default status of the EPO to on and "black"
		self._eporisecallback = self._pigpiod.callback(epopin, pigpio.EITHER_EDGE, self.epostatechange)

	def epostatechange(self, gpio, level, tick):
		self._mylogger("ATXPiHat epostatechange")

		sensepwrpin = self._settings.getInt(['SenseOnOffPin'])
		if self._pigpiod.read(sensepwrpin) == 0:
			return

		currentepostate = self._pigpiod.read(gpio)

		if self._settings.getInt(['UseEPO']):
			if currentepostate == 0:
				self._mylogger("ATXPiHat - EPO Pressed", forceinfo=True)
				if self._pigpiod.read(sensepwrpin) == 1:
					self.setepostatus(True)
					self.turnoff(True)

			elif currentepostate == 1:
				self._mylogger("ATXPiHat - EPO released", forceinfo=True)
				self.setepostatus(False)

	def setepostatus(self, currentstate):
		#true = engaged or 0
		#false = normal or 1
		self._mylogger("ATXPiHat set_epo_status %s" % currentstate)
		self._plugin_manager.send_plugin_message(self._identifier,
												 dict(msg="epoengaged",
													  field1='true' if currentstate else 'false',
													  field2=""))

	def initialize_fan(self):
		self._mylogger("ATXPiHat Initialize_fan called")
		self._fanworking = 0
		if self._fanmonitor is not None:			# failsafe to make sure that everything is good.
			self._fanmonitor.cancel()

		self._fanmonitor = MonitorPWM.MonitorPWM(self._pigpiod, self._settings.getInt(['FanRPMPin']), self._mylogger)

	def check_fan_state(self):
		self._mylogger("ATXPiHat check_fan_state called")
		rpm = 0.0

		if not self._pigpiod.connected:
			return

		if not self.ispowered():			#if no power move on
			self._plugin_manager.send_plugin_message(self._identifier, dict(msg="fanrpm", field1=0))
			return 0

		if self._settings.getBoolean(['MonitorFanRPM']):
			rpm = 0
			if self._fanmonitor is not None:
				rpm = self._fanmonitor.rpm()
				self._mylogger("ATXPiHat check_fan_state - rpm %s" % rpm)
				self._plugin_manager.send_plugin_message(self._identifier, dict(msg="fanrpm", field1=rpm))

				self._mylogger('fan rpm - %s ' % rpm)

				if rpm < 1:						# This allows for three cycles before actually checking the fan
					self._mylogger('Tripped 0 fan rpm')
					self._fanworking = self._fanworking + 1
				else:
					self._fanworking = 0

				self._mylogger('Fan fault count %s' % self._fanworking)

				if self._settings.getBoolean(['FanRPMFault']) and rpm == 0 and self._fanworking > 2:
					self._mylogger('Fan fault detected', forceinfo=True)
					self._plugin_manager.send_plugin_message(self._identifier, dict(msg="fanrpmfault", field1='true'))
					self.turnoff()

	def initialize_power(self):
		self._mylogger("ATXPiHat initialize_power")

		if self._checkVoltageTimer is not None:
			self._checkVoltageTimer.cancel()

		if not self._smartboard:
			self._mylogger("ATXPiHat initialize_power - not smartboard exit")
			return

		self._pigpiod.set_mode(self._settings.getInt(['OnOffSwitchPin']), pigpio.OUTPUT)  	# on/off
		self._pigpiod.set_mode(self._settings.getInt(['SenseOnOffPin']), pigpio.INPUT)  	# is supply on

		if self._adc is None:
			self._adc = ADCProcessor.ADCProcessor(self._mylogger, int(self._settings.get(['i2cAddress']), 16), self._settings.getInt(['i2cBus']))

		if not self.ispowered():
			self._adc.resetchip()

			sample = []
			for i in range(0,6):
				sample.append(self._adc.read_amperage_baseline())

			self._mylogger("ATXPiHat ampbaseline - {}".format(sample))
			self._ampbaseline = ATXPiHat._processsamples(sample)
			self._mylogger('ATXPiHat Amperage Baseline {}'.format(self._ampbaseline))

		self._checkVoltageTimer = ATXPiHat._settimer(self._checkVoltageTimer, self._settings.getInt(['ProcessTimer']), self.process_voltage)

	@staticmethod
	def _processsamples(listobj):

		cleanlist = []
		for i in range(len(listobj)):
			cleanlist.append(abs(listobj[i]))

		cleanlist.remove(max(cleanlist))
		cleanlist.remove(min(cleanlist))
		return sum(cleanlist) / float(len(cleanlist))

	def process_voltage(self):
		self._mylogger("ATXPiHat process_voltage - called")
		if not self._smartboard:
			self._mylogger("ATXPiHat process_voltage - not smartboard exit")
			return

		amperage = self._adc.read_amperage(self._ampbaseline)
		self._mylogger("ATXPiHat process_voltage - amp sample {}".format(amperage))

		if self.ispowered():
			if amperage > self._settings.getInt(['MaxAmperage']):
				self._mylogger('Amperage fault detected - {}'.format(amperage), forceinfo=True)
				self._ampfault = self._ampfault + 1
			else:
				self._ampfault = 0

			if self._ampfault > 3:			# if it sees the fault 3 times, things are bad, forces printer shutdown
				self._mylogger('Amperage fault detected - shutting down', forceinfo=True)
				self._plugin_manager.send_plugin_message(self._identifier, dict(msg="amperagefault", field1='true'))
				self.turnoff(True)
				self._ampfault = 0
				self.initialize_power()
				return
		else:
			self._ampfault = 0

		voltage =  self._adc.read_voltage(self._settings.getFloat(['ReferenceVoltage']))
		self._mylogger("ATXPiHat process_voltage - volt sample %s " % voltage)

		self._plugin_manager.send_plugin_message(self._identifier, dict(msg="atxvolts", field1=amperage, field2=voltage))

	def on_after_startup(self):
		self._mylogger("Starting ATXPiHatPlugin", forceinfo=True)

		if not self._pigpiod.connected:
			self._pigpiod = pigpio.pi()

		self.detectsmartboard()
		self.initialize_all()

	def detectsmartboard(self):
		addr = int(self._settings.get(['i2cAddress']),16)
		busaddr = self._settings.getInt(['i2cBus'])

		if addr != 0x68:
			self._mylogger("Starting ATXPiHatPlugin - default i2cAddress is not 0x68", forceinfo=True)

		if busaddr != 1:
			self._mylogger("Starting ATXPiHatPlugin - default i2cBus is not 1", forceinfo=True)

		self._smartboard = ADCProcessor.detectaddress(self._mylogger,  addr, busaddr)

		if not self._smartboard:			# force the extra ports off
			self._settings.set(['BoardVersion'],"1.00Z")
			self._settings.set(['UseLEDS'], False)
			self._settings.set(['UseExtSwitch'], False)
		else:  # future look at registry to detect board type
			self._settings.set(['BoardVersion'], "1.00")

		self._mylogger('ATXPiHat - smart device {}'.format('False' if self._smartboard else 'True'))

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

		processtimer = self._settings.getInt(['ProcessTimer'])
		# Power status monitor
		self._checkPSUTimer = ATXPiHat._settimer(self._checkPSUTimer,processtimer, self.check_psu_state)

		self.initialize_fan()
		self.initialize_epo()

		# Fan status processing
		self._checkFanTimer = ATXPiHat._settimer(self._checkFanTimer, processtimer, self.check_fan_state, self._settings.getBoolean(['MonitorFanRPM']))

		if self._smartboard:
			self._mylogger("initialize_all - enabling smart devices")

			if self.ispowered():
				# external LEDS and switch setup
				self.initialize_leds()
				self.initialize_extswitch()

			# External Switch State processing
			self._checkExtSwitchTimer = ATXPiHat._settimer(self._checkExtSwitchTimer, processtimer, self.update_extswitchstate,self._settings.getBoolean(['UseExtSwitch']))

			# Amperage and voltage detection
			self.initialize_power()

	def get_settings_defaults(self):
		self._mylogger("ATXPiHat get_settings_default()")
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
					ReferenceVoltage=12.289,
					ProcessTimer = 2,
					MaxAmperage=19,
					RemoveLogo=False)

	def on_settings_save(self, data):
		self._mylogger(u"ATXPiHat on_settings_save()")
		# Cannot update the screen faster than every 2 seconds
		# The amperage and voltage readings can take some time to come back
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		self._mylogger(u"ATXPiHat on_settings_save() before - Processtimer %s" % self._settings.getInt(['ProcessTimer']))
		if self._settings.getInt(['ProcessTimer']) < 2:
			self._settings.setInt(['ProcessTimer'],2)
		self._mylogger(u"ATXPiHat on_settings_save() after - Processtimer %s" % self._settings.getInt(['ProcessTimer']))

		# with newer board variations we will have to figure out how to detect this to set the upper limit
		if self._settings.getInt(['MaxAmperage']) > 19:
			self._settings.setInt(['MaxAmperage'], 19)

		self.detectsmartboard()
		self.initialize_all()
		self._mylogger(u"ATXPiHat on_settings_save() - calling updatestatusbox")
		self._plugin_manager.send_plugin_message(self._identifier, dict(msg="updatestatusbox"))
		self._mylogger(u"ATXPiHat on_settings_save() - calling backgroundimage")
		self._plugin_manager.send_plugin_message(self._identifier, dict(msg="backgroundimage",
																		field1='true' if self._settings.getBoolean(['RemoveLogo']) else 'false'))

	def get_template_configs(self):
		self._mylogger(u"ATXPiHat get_template_configs()")
		return [
			dict(type='settings', custom_bindings=False),
			dict(type='navbar', custom_bindings=True, template='atxpihat_navbar_epo.jinja2'),
			dict(type='navbar', custom_bindings=True, template='atxpihat_navbar_pwr.jinja2', classes=['dropdown']),
			dict(type='tab', custom_bindings=True)
		]

	def get_api_commands(self):
		self._mylogger(u"ATXPiHat get_api_command()")
		return dict(
			updateLED=['LEDRed', 'LEDGreen', 'LEDBlue', 'LEDBrightness'],
			updateExtSwitch=['ExternalSwitchValue'],
			turnATXPSUOn=[],
			turnATXPSUOff=[],
			ToggleExtSwitch=[],
			IsSmartBoard=[]
		)

	def on_api_command(self, command, data):
		self._mylogger(u"ATXPiHat on_api_command() - %s" % command, forceinfo=True)

		if not user_permission.can():
			return make_response("Insufficient rights", 403)

		if command.lower() == 'turnatxpsuoff':
			self._mylogger("Turned Off Supply")
			self.turnoff()

		if command.lower() == 'turnatxpsuon':
			self._mylogger("Turned On Supply")
			self.turnon()

		if command.lower() == 'issmartboard':
			smartflag = 'true' if self._smartboard else 'false'
			self._mylogger("sending IsSmartBoard {} ".format(smartflag), forceinfo=True)
			return make_response(smartflag)

		if not self._smartboard:
			return

		if command.lower() == "toggleextswitch":
			self._mylogger("Toggle External Switch")
			self.toggle_extswitch()

		if command.lower() == 'updateextswitch':
			self._mylogger("Update External Switch PWM value")
			data.pop('command', 0)
			self._settings.set(['ExternalSwitchValue'], int(data['ExternalSwitchValue']))
			self._settings.save()
			self.initialize_extswitch()

		if command.lower() == 'updateled' and self._settings.getBoolean(['UseLEDS']):
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
		self._mylogger(u"ATXPiHat shutdown", forceinfo=True)

		self.turnoff(True)
		self._pigpiod.stop()

	def get_assets(self):
		self._mylogger(u"ATXPiHat get_assets()")
		return dict(
			js=["js/atxpihat.js"],
			css=["css/atxpihat.css"]
		)

	def get_settings_version(self):
		self._mylogger(u"ATXPiHat get_settings_version()")
		return 2

	def HandleMarlin(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		name = 'ATXPiHat HandleMarlin'
		self._mylogger('{} - called'.format(name))
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
