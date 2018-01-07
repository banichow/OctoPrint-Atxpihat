# coding=utf-8
from __future__ import absolute_import

# **************** Contribution libraries and exampled **********************************
# ATXPiHat Hardware - Steve Smith - Xygax - https://www.facebook.com/Xygax
# PSUControl - Shawn Bruce - https://github.com/kantlivelong/
# LEDStripControl - https://github.com/google/OctoPrint-LEDStripControl
# pigpio - joan@abyz.me.uk - http://abyz.co.uk/rpi/pigpio/python.html
# mcp342x - s.marple@lancaster.ac.uk - Steve Marple - https://github.com/stevemarple/python-MCP342x
#		    This is included with the plugin to handle an installation issue with what version of smbus
#		    we are using. We are using smbus2, not smbus-cffi. smbus2 as far as I can tell
#           the current library and has the best documentation
# ***************************************************************************************

__author__ = "Brian Anichowski"
__license__ = "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
__copyright__ = "Copyright (C) 2018 Brian Anichowski http://www.baprojectworkshop.com"
__plugin_name__ = "ATXPiHat"
__plugin_version__ = "1.0.0"
__plugin_description__ = "ATXPiHat - http://www.baprojectworkshop.com"

import RPi.GPIO as GPIO
import logging
import octoprint.plugin
from octoprint.server import user_permission
import pigpio
import smbus2 as smbus
import time
import thread
from . import MonitorPWM, MCP342x
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
			self._mylogger(u'ATXPiHat does not support Type 1 boards', forceinfo=True)
			raise EnvironmentError('ATXPiHat does not support Type 1 boards')
		else:
			self._mylogger(u'ATXPiHat BCM board is type - %s' % self._pigpiod.get_hardware_revision(), forceinfo=True)

		self._ledcolors = dict(LEDRed=None, LEDGreen=None, LEDBlue=None)
		self._fanmonitor = None
		self._i2cinterface = False
		self._smbus = None
		self._eporisecallback = None


	def _mylogger(self,message, forceinfo=False):			# this is to be able to change the logging without a large change

		if self._settings is not None:
			if self._settings.getBoolean(['debuglogging']) or forceinfo:
				self._logger.info(message)
			else:
				self._logger.debug(message)
		else:
			print(message)

	def initialize_leds(self):
		self._mylogger(u"ATXPiHat initialize_leds()")

		if self._settings.getBoolean(['UseLEDS']):
			ledon = True
		else:
			ledon = False

		for key, value in self._ledcolors.iteritems():
			newkey = key + 'Pin'
			keyval = self._settings.getInt([key])
			ledbrightness = self._settings.getInt(['LEDBrightness'])

			if ledbrightness > 99:
				ledbrightness = 100
			elif ledbrightness < 1:
				ledbrightness = 1

			self._mylogger(u"ATXPiHat _initialize_leds() {0} - {1} - {2}".format(key, newkey, keyval))
			pin = self._settings.getInt([newkey])

			if not ledon or keyval < 0:
				keyval = 0
				realBrightness = 0
			else:
				realBrightness = int((float(keyval) * float(ledbrightness)) / 100)

			self._mylogger(u"LED pwmcycle %s " % realBrightness)
			self._pigpiod.set_PWM_dutycycle(pin, realBrightness)

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

	def turnoff(self):
		self._mylogger('ATXPiHat - turnoff called')

		if not self._pigpiod.connected:
			self._mylogger(u"ATXPiHat turnoff - pigpio is no longer connected", forceinfo=true)
			self._pigpiod = pigpio.pi()

		sensepwrpin = self._pigpiod.read(self._settings.getInt(['SenseOnOffPin']))
		self._mylogger('ATXPiHat - Current sense pin %s ' % sensepwrpin)
		if sensepwrpin == 1:

			self.shutdown_fan_monitor()

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

	def initialize_epo(self):
		# due to design, I cannot sense the EPO pin properly until 12v is applied to the board
		# this is just setting the port up
		self._mylogger("ATXPiHat initialize_epo")
		epopin = self._settings.getInt(['EPOPin'])
		if self._eporisecallback is not None:
			self._eporisecallback.cancel()

		self._pigpiod.set_mode(epopin, pigpio.INPUT)
		self._pigpiod.set_pull_up_down(epopin, pigpio.PUD_UP)
		self._eporisecallback = self._pigpiod.callback(epopin, pigpio.EITHER_EDGE, self.epostatechange)
		self.setepostatus(False)  # go set the default status of the EPO to on and "black"

	def epostatechange(self, gpio, level, tick):
		self._mylogger("ATXPiHat epostatechange")

		sensepwrpin = self._pigpiod.read(self._settings.getInt(['SenseOnOffPin']))
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
		self._mylogger("ATXPiHat set_epo_status")
		self._plugin_manager.send_plugin_message(self._identifier,
												 dict(msg="epoengaged",
													  field1="true" if not currentstate else "false",
													  field2=""))

	def initialize_fan(self):
		self._mylogger("ATXPiHat Initialize_fan called")
		self._fanworking = 0
		if self._fanmonitor is not None:			# failsafe to make sure that everything is good.
			self._fanmonitor.cancel()

		self._fanmonitor = MonitorPWM.MonitorPWM(self._pigpiod, self._settings.getInt(['FanRPMPin']), self._mylogger)

	def shutdown_fan_monitor(self):
		self._mylogger("ATXPiHat shutdown_fan_monitor called")

		if self._fanmonitor is not None:
			self._plugin_manager.send_plugin_message(self._identifier, dict(msg="fanrpm", field1=0))
			self._fanmonitor.cancel()

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
				self._plugin_manager.send_plugin_message(self._identifier, dict(msg="fanrpm", field1=rpm))

				self._mylogger(U'fan rpm - %s ' % rpm)

				if rpm < 1:						# This allows for three cycles before actually checking the fan
					self._mylogger(u'Tripped 0 fan rpm')
					self._fanworking = self._fanworking + 1
				else:
					self._fanworking = 0

				self._mylogger(u'Fan fault count %s' % self._fanworking)

				if self._settings.getBoolean(['FanRPMFault']) and rpm == 0 and self._fanworking > 2:
					self._mylogger(u'Fan fault detected', forceinfo=True)
					self._plugin_manager.send_plugin_message(self._identifier, dict(msg="fanrpmfault", field1='true'))
					self.turnoff()


	def initialize_power(self):
		self._mylogger("ATXPiHat initialize_power")
		self._pigpiod.set_mode(self._settings.getInt(['OnOffSwitchPin']), pigpio.OUTPUT)  	# on/off
		self._pigpiod.set_mode(self._settings.getInt(['SenseOnOffPin']), pigpio.INPUT)  	# is supply on

		if self._i2cinterface is True:
			self._smbus = None
			self._amperage_ch0 = None
			self._voltage_ch1 = None

		addr = int(self._settings.get(['i2cAddress']), 16)
		self._smbus = smbus.SMBus(self._settings.getInt(['i2cBus']))
		self._amperage_ch0 = MCP342x.MCP342x(self._smbus, addr, device='MCP3422', gain=8, channel=0, resolution=18)
		self._voltage_ch1 = MCP342x.MCP342x(self._smbus, addr, device='MCP3422', gain=2, channel=1, resolution=18)
		self._i2cinterface = True

	def process_voltage(self):
		self._mylogger("process_voltage - called")
		resamp = MCP342x.MCP342x.convert_and_read(self._amperage_ch0, samples=8, sleep=False)
		amperage = round(((ATXPiHat._processsamples(resamp) - self._settings.getFloat(['AmperageBaseline'])) * 1000) * 2,3)

		resvolt = MCP342x.MCP342x.convert_and_read(self._voltage_ch1, samples=8, sleep=False)
		voltage =  round(( self._settings.getFloat(['ReferenceVoltage']) * ATXPiHat._processsamples(resvolt)), 2)

		self._plugin_manager.send_plugin_message(self._identifier, dict(msg="atxvolts", field1=amperage, field2=voltage))

	@staticmethod
	def _processsamples(listobj):

		cleanlist = []
		for i in range(len(listobj)):
			cleanlist.append(abs(listobj[i]))

		cleanlist.remove(max(cleanlist))
		cleanlist.remove(min(cleanlist))
		return sum(cleanlist) / float(len(cleanlist))

	def on_after_startup(self):
		self._mylogger("Starting ATXPiHatPlugin", forceinfo=True)

		if not self._pigpiod.connected:
			self._pigpiod = pigpio.pi()

		self.initialize_power()
		self.initialize_leds()
		self.initialize_fan()
		self.initialize_epo()

		# Power status monitor
		self._checkPSUTimer = RepeatedTimer(self._settings.getInt(['PSUTimer']), self.check_psu_state, None, None, True)
		self._checkPSUTimer.start()

		# Fan status processing
		self._checkFanTimer = RepeatedTimer(self._settings.getInt(['FanTimer']), self.check_fan_state, None, None, True)
		self._checkFanTimer.start()

		# Voltage/Amp status processing
		self._checkVoltageTimer = RepeatedTimer(self._settings.getInt(['VoltageTimer']), self.process_voltage, None, None, True)
		self._checkVoltageTimer.start()


	def get_settings_defaults(self):
		self._mylogger(u"ATXPiHat get_settings_default()")
		return dict(LEDRed=0,
					LEDGreen=0,
					LEDBlue=0,
					LEDRedPin=23,
					LEDGreenPin=22,
					LEDBluePin=24,
					EPOPin=15,
					debuglogging=False,
					OnOffSwitchPin=17,
					SenseOnOffPin=18,
					LEDBrightness=100,
					UseEPO=False,
					UseLEDS=False,
					PowerOffWarning=True,
					enablePowerOffWarningDialog=False,
					MonitorFanRPM=False,
					FanRPMPin=14,
					FanRPMFault=False,
					i2cAddress='0x68',
					i2cBus=1,					#we are using gpio pins 2 and 3
					ReferenceVoltage=12.289,
					AmperageBaseline=.001,
					PSUTimer = 5,
					FanTimer = 5,
					VoltageTimer = 2,
					MaxAmperage=15)

	def on_settings_save(self, data):
		self._mylogger(u"ATXPiHat on_settings_save()")
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

		self.initialize_power()
		self.initialize_leds()
		self.initialize_fan()
		self.initialize_epo()

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
			turnATXPSUOn=[],
			turnATXPSUOff=[]
		)

	def on_api_command(self, command, data):
		self._mylogger(u"ATXPiHat on_api_command() - %s" % command, forceinfo=True)

		if not user_permission.can():
			return make_response("Insufficient rights", 403)

		if command.lower() == 'turnatxpsuoff':
			self._mylogger("Turned Off Supply")
			self.turnoff()

		elif command.lower() == 'turnatxpsuon':
			self._mylogger("Turned On Supply")
			self.turnon()

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

	def hook_gcode_queuing(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
		return

	def get_update_information(self):
		return


#		return dict(
#			psucontrol=dict(
#				displayName="ATXPiHat Control",
#				displayVersion=self._plugin_version,
#
#				# version check: github repository
#				type="github_release",
#				user="kantlivelong",
#				repo="OctoPrint-ATXPiHatControl",
#				current=self._plugin_version,
#
#				# update method: pip w/ dependency links
#				pip="https://github.com/kantlivelong/OctoPrint-PSUControl/archive/{target_version}.zip"
#			)
#		)


def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = ATXPiHat()

	global __plugin_hooks__
	__plugin_hooks__ = {
		#"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
		"octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.hook_gcode_queuing

	}
