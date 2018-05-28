# coding=utf-8

########################################################################################################################
plugin_identifier = "atxpihat"
plugin_package = "octoprint_atxpihat"
plugin_name = "OctoPrint-Atxpihat"
plugin_version = "1.1.2"
plugin_description = """Octoprint Plugin for the ATXPiHat board"""
plugin_author = "Brian Anichowski"
plugin_author_email = "banichow@hotmail.com"
plugin_url = "https://github.com/banichow/OctoPrint-Atxpihat"
plugin_license = "Creative Commons"
plugin_requires = ["RPi.GPIO", "pigpio","smbus2","enum34"]
plugin_additional_data = []
plugin_additional_packages = []
plugin_ignored_packages = []
additional_setup_parameters = {}

########################################################################################################################

from setuptools import setup

try:
	import octoprint_setuptools
except:
	print("Could not import OctoPrint's setuptools, are you sure you are running that under "
	      "the same python installation that OctoPrint is installed under?")
	import sys
	sys.exit(-1)

setup_parameters = octoprint_setuptools.create_plugin_setup_parameters(
	identifier=plugin_identifier,
	package=plugin_package,
	name=plugin_name,
	version=plugin_version,
	description=plugin_description,
	author=plugin_author,
	mail=plugin_author_email,
	url=plugin_url,
	license=plugin_license,
	requires=plugin_requires,
	additional_packages=plugin_additional_packages,
	ignored_packages=plugin_ignored_packages,
	additional_data=plugin_additional_data
)

if len(additional_setup_parameters):
	from octoprint.util import dict_merge
	setup_parameters = dict_merge(setup_parameters, additional_setup_parameters)

setup(**setup_parameters)
