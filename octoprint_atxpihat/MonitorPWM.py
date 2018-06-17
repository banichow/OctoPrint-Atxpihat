# coding=utf-8
from __future__ import absolute_import
# *****************************************
# http://abyz.co.uk/rpi/pigpio/python.html
# Based on example: http://abyz.me.uk/rpi/pigpio/examples.html#Python code
# *****************************************
__author__ = "Brian Anichowski"
__license__ = "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
__copyright__ = "Copyright (C) 2018 Brian Anichowski http://www.baprojectworkshop.com"
__version__ = "1.1.4"

import time
import pigpio

class MonitorPWM:

	def __init__(self, pi, gpio, loghandler, weighting=0.0):

		self._logger = loghandler

		self.pi = pi
		self.gpio = gpio

		if weighting < 0.0:
			weighting = 0.0
		elif weighting > 0.99:
			weighting = 0.99

		self._new = 1.0 - weighting # Weighting for new reading.
		self._old = weighting       # Weighting for old reading.

		self._high_tick = None
		self._period = None
		self._high = None
		self.reset = False

		pi.set_mode(gpio, pigpio.INPUT)

		loghandler('MonitorPWM - Creating call back')
		self._cb = pi.callback(gpio, pigpio.EITHER_EDGE, self._cbf)

	def _cbf(self, gpio, level, tick):

		self.reset = True
		if level == 1:

			if self._high_tick is not None:
				t = pigpio.tickDiff(self._high_tick, tick)

				if self._period is not None:
					self._period = (self._old * self._period) + (self._new * t)
				else:
					self._period = t

			self._high_tick = tick

		elif level == 0:

			if self._high_tick is not None:
				t = pigpio.tickDiff(self._high_tick, tick)

				if self._high is not None:
					self._high = (self._old * self._high) + (self._new * t)
				else:
					self._high = t

	def rpm(self):
		if self._period is not None:
			if self.reset:
				self.reset = False
				return (1000000.0 / self._period * 60 ) /2.0
			else:
				return 0.0

	def cancel(self):
		self._logger('MonitorPWM - Cancel the callback')
		self._cb.cancel()
