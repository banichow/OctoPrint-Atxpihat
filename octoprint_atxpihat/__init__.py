# coding=utf-8
from __future__ import absolute_import

# **************** Contribution libraries and exampled **********************************
# ATXPiHat Hardware - Steve Smith - Xygax - https://www.facebook.com/Xygax
# PSUControl - Shawn Bruce - https://github.com/kantlivelong/
# LEDStripControl - https://github.com/google/OctoPrint-LEDStripControl
# pigpio - joan@abyz.me.uk - http://abyz.co.uk/rpi/pigpio/python.html
# ***************************************************************************************

__author__ = "Brian Anichowski"
__license__ = "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
__plugin_license__ = "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
__copyright__ = "Copyright (C) 2018 Brian Anichowski http://www.baprojectworkshop.com"
__plugin_name__ = "ATXPiHat"
__plugin_version__ = "1.0.5"
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
			 octoprint.plugin.TemplatePlugin,
			 octoprint.plugin.SimpleApiPlugin):

	def __init__(self):
		self._pigpiod = pigpio.pi()
		self._settings = None

		revision = GPIO.RPI_REVISION

		if revision <> 2 and revision <> 3:
			self._mylogger('ATXPiHat does not support Type 1 boards', forceinfo=True)
			raise EnvironmentError('ATXPiHat does not support Type 1 boards')
		else:
			self._mylogger('ATXPiHat BCM board is type - %s' % self._pigpiod.get_hardware_revision(), forceinfo=True)

		self._ampbaseline = None
		self._ledcolors = dict(LEDRed=None, LEDGreen=None, LEDBlue=None)
		self._fanmonitor = None
		self._adc = None
		self._eporisecallback = None
		self._checkPSUTimer = None
		self._checkFanTimer = None
		self._checkVoltageTimer = None
		self._checkExtSwitchTimer = None
		self._currentExtSwitchState = False
		self._ampbaseline = 2.048

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

		workleds = dict()

		for key, value in self._ledcolors.iteritems():
			workleds[key] = self._settings.getInt([key])

		self.setLEDSvalues(workleds,self._settings.getInt(['LEDBrightness']))


	def turnon(self):
		self._mylogger('ATXPiHat - turnon called')
		epopin = self._settings.getInt(['EPOPin'])
		useepo = self._settings.getBoolean(['UseEPO'])
		pwrsensepin = self._settings.getInt(['SenseOnOffPin'])
		onoffpin = self._settings.getInt(['OnOffSwitchPin'])

		# if the EPO is enable and the pin is 0 and pwrsensepin is 0
		# if EPO is disabled and pwrsensepin is 0
		if not self._pigpiod.read(pwrsensepin):
			self._pigpiod.write(onoffpin, 1)  # Turn on ps

			count = 0		# this is to wait until we have power applied and we can sense this.
			while True:
				if self._pigpiod.read(pwrsensepin) or count > 20:
					break
				count = count + 1
				time.sleep(.2)

			if useepo:
				if not self._pigpiod.read(epopin):
					self._pigpiod.write(onoffpin, 0)  # Turn off ps
					self.setepostatus(True)
					return

			time.sleep(5)	# this is used to make sure that Marlin has started and the connection can
							# sense the change to refresh the connection
			self._plugin_manager.send_plugin_message(self._identifier, dict(msg="refreshconnection"))
			self.initialize_fan()
			self.initialize_extswitch()

	def turnoff(self):
		self._mylogger('ATXPiHat - turnoff called')

		if not self._pigpiod.connected:
			self._mylogger(u"ATXPiHat turnoff - pigpio is no longer connected", forceinfo=true)
			self._pigpiod = pigpio.pi()

		sensepwrpin = self._pigpiod.read(self._settings.getInt(['SenseOnOffPin']))
		self._mylogger('ATXPiHat - Current sense pin %s ' % sensepwrpin)

		if sensepwrpin == 1:
			self.toggle_extswitch(True)

			if self._printer.is_printing():
				self._printer.cancel_print(self._printer)
				time.sleep(2)

			if self._printer.is_operational():
				self._printer.disconnect();
				time.sleep(1)

			self._pigpiod.write(self._settings.getInt(['OnOffSwitchPin']), 0)  # Turn off ps
			time.sleep(4)

		self._plugin_manager.send_plugin_message(self._identifier, dict(msg="refreshconnection"))

	def check_psu_state(self):
		self._mylogger("ATXPiHat check_psu_state called")
		if not self._pigpiod.connected:
			self._mylogger(u"ATXPiHat - pigpio is no longer connected", forceinfo=True)
			self._pigpiod = pigpio.pi()

		sensepwrpin = self._pigpiod.read(self._settings.getInt(['SenseOnOffPin']))
		retval = "true" if sensepwrpin == 1 else "false"
		self._plugin_manager.send_plugin_message(self._identifier, dict(msg="pwrstatus", field1=retval))

	def initialize_extswitch(self):
		self._mylogger("ATXPiHat initialize_extswitch")
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
		sensepwrpin = self._pigpiod.read(self._settings.getInt(['SenseOnOffPin']))

		if sensepwrpin == 1 or forceoff:
			extswtpin = self._settings.getInt(['ExternalSwitchPin'])
			pwmvalue = self._settings.getInt(['ExternalSwitchValue'])

			if self._settings.getBoolean(['UseExtSwitch']):
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

		extswtpin = self._settings.getInt(['ExternalSwitchPin'])
		sensepwrpin = self._pigpiod.read(self._settings.getInt(['SenseOnOffPin']))

		if sensepwrpin == 1:
			if self._settings.getBoolean(['UseExtSwitch']):
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
					self.turnoff()

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

		pwrsensepin = self._settings.getInt(['SenseOnOffPin'])
		if not self._pigpiod.connected:
			return

		if not self._pigpiod.read(pwrsensepin):			#if no power move on
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
		self._pigpiod.set_mode(self._settings.getInt(['OnOffSwitchPin']), pigpio.OUTPUT)  	# on/off
		self._pigpiod.set_mode(self._settings.getInt(['SenseOnOffPin']), pigpio.INPUT)  	# is supply on
		pwrsensepin = self._settings.getInt(['SenseOnOffPin'])

		if self._adc is None:
			self._adc = ADCProcessor.ADCProcessor(self._mylogger, int(self._settings.get(['i2cAddress']), 16), self._settings.getInt(['i2cBus']))

		if self._pigpiod.read(pwrsensepin):  # if powered on return, do not set the baseline
			return

		sample = []
		for i in range(0,6):
			sample.append(self._adc.read_amperage_baseline())

		self._ampbaseline = ATXPiHat._processsamples(sample)
		self._mylogger('ATXPiHat Amperage Baseline {}'.format(self._ampbaseline))

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
		pwrsensepin = self._settings.getInt(['SenseOnOffPin'])
		amperage = self._adc.read_amperage(self._ampbaseline)
		self._mylogger("ATXPiHat process_voltage - amp sample {}".format(amperage))

		if amperage > self._settings.getInt(['MaxAmperage']):
			self._mylogger('Amperage fault detected - {}'.format(amperage), forceinfo=True)
			self._ampfault = self._ampfault + 1
		else:
			self._ampfault = 0

		if self._ampfault > 3 and self._pigpiod.read(pwrsensepin):			# if it sees the fault 3 times, things are bad, forces printer shutdown
			self._mylogger('Amperage fault detected - shutting down', forceinfo=True)
			self._plugin_manager.send_plugin_message(self._identifier, dict(msg="amperagefault", field1='true'))
			self.turnoff()
			self._ampfault = 0
			return

		voltage =  self._adc.read_voltage(self._settings.getFloat(['ReferenceVoltage']))
		self._mylogger("ATXPiHat process_voltage - volt sample %s " % voltage)

		self._plugin_manager.send_plugin_message(self._identifier, dict(msg="atxvolts", field1=amperage, field2=voltage))

	def on_after_startup(self):
		self._mylogger("Starting ATXPiHatPlugin", forceinfo=True)

		if not self._pigpiod.connected:
			self._pigpiod = pigpio.pi()

		self.initialize_all()

	@staticmethod
	def _settimer(timervar, timeval, methodcall):

		if timervar is not None:
			timervar.cancel()

		worktimer = RepeatedTimer(timeval, methodcall, None, None, True)
		worktimer.start()

		return worktimer

	def initialize_all(self):
		self.initialize_power()
		self.initialize_leds()
		self.initialize_fan()
		self.initialize_epo()
		self.initialize_extswitch()

		processtimer = self._settings.getInt(['ProcessTimer'])

		#Multiple timers to get some multithreading out of it.
		# Power status monitor
		self._checkPSUTimer = ATXPiHat._settimer(self._checkPSUTimer,processtimer, self.check_psu_state)

		# Fan status processing
		self._checkFanTimer = ATXPiHat._settimer(self._checkFanTimer,processtimer, self.check_fan_state)

		# Voltage/Amp status processing
		self._checkVoltageTimer = ATXPiHat._settimer(self._checkVoltageTimer, processtimer, self.process_voltage)

		# External Switch State
		self._checkExtSwitchTimer = ATXPiHat._settimer(self._checkExtSwitchTimer, processtimer, self.update_extswitchstate)

	def get_settings_defaults(self):
		self._mylogger(u"ATXPiHat get_settings_default()")
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
					ExternalSwitchTriggerOff='M355 S0',
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
					MaxAmperage=19)

	def on_settings_save(self, data):
		self._mylogger(u"ATXPiHat on_settings_save()")
		# Cannot update the screen faster than every 2 seconds
		# The amperage and voltage readings can take some time to come back
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		self._mylogger(u"ATXPiHat on_settings_save() before - Processtimer %s" % self._settings.getInt(['ProcessTimer']))
		if self._settings.getInt(['ProcessTimer']) < 2:
			self._settings.setInt(['ProcessTimer'],2)

		if self._settings.getInt(['MaxAmperage']) > 19:
			self._settings.setInt(['MaxAmperage'], 2)

		self.initialize_all()
		self._mylogger(u"ATXPiHat on_settings_save() after - Processtimer %s" % self._settings.getInt(['ProcessTimer']))

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
			ToggleExtSwitch=[]
		)

	def on_api_command(self, command, data):
		self._mylogger(u"ATXPiHat on_api_command() - %s" % command, forceinfo=True)

		if not user_permission.can():
			return make_response("Insufficient rights", 403)

		if command.lower() == "toggleextswitch":
			self._mylogger("Toggle External Switch")
			self.toggle_extswitch()

		if command.lower() == 'turnatxpsuoff':
			self._mylogger("Turned Off Supply")
			self.turnoff()

		elif command.lower() == 'turnatxpsuon':
			self._mylogger("Turned On Supply")
			self.turnon()

		elif command.lower() == 'updateextswitch':
			self._mylogger("Update External Switch PWM value")
			data.pop('command', 0)
			self._settings.set(['ExternalSwitchValue'], int(data['ExternalSwitchValue']))
			self._settings.save()
			self.initialize_extswitch()

		elif command.lower() == 'updateled' and self._settings.getBoolean(['UseLEDS']):
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

		self.turnoff()
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
		self._mylogger('ATXPiHat HandleMarlin')

		workcmd = cmd.upper()

		if gcode:
			if workcmd.startswith("M150"):
				self._mylogger('ATXPiHat HandleMarlin LED command encounter - {}'.format(cmd),forceinfo=True)

				workleds = dict()
				workval = workcmd.split()
				self._mylogger(workval, forceinfo=True)
				for i in workval:
					firstchar = str(i[0].upper())
					leddata = str(i[1:].strip())
					self._mylogger("{} {}".format(firstchar,leddata ), forceinfo=True)
					if not leddata.isdigit():
						self._mylogger("LED command encounter a badly formatted value {} - {}".format(cmd, leddata), forceinfo=True)
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
						self._mylogger("LED command encounter wrong value {}".format(leddata), forceinfo=True)

				if len(workleds) is not 3:
					self._mylogger("LED command encounter missing value {}".format(workleds), forceinfo=True)
					return

				self.setLEDSvalues(workleds, self._settings.getInt(['LEDBrightness']))

			if workcmd.startswith(self._settings.get(['ExternalSwitchTriggerOn']).upper()):
				self._mylogger("Ext Switch On command encounter - {}".format(cmd),forceinfo=True)

			if workcmd.startswith(self._settings.get(['ExternalSwitchTriggerOff']).upper()):
				self._mylogger("Ext Switch Off command encounter - {}".format(cmd),forceinfo=True)

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
