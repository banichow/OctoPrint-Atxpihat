# OctoPrint-Atxpihat

Initial software release to support the v1.0 ATXPiHat. A lot of the features below come disabled and are easily enabled on the settings tab. Here is the hardware/software features;

* Supports Raspberry Pi v3
* Direct 24 pin ATX connection to the Pi
* Powers the Pi from the ATX supply in standby
* Remote printer power On/Off
* Graceful handles Octoprint connection reset and shutdown, dynamic UI updating
* Emergency Power Off
* 12v RGB LED control
* Monitor 12v amperage and voltage
* Available 5v for other external power requirements
* Emergency Amperage overflow shutdown (Not fully implemented at this time)
* 12v cooling fan control and monitoring
* Switchable 12v or 5v - static, dimmable(pwm)

## Setup

Install via the bundled [Plugin Manager](https://github.com/foosel/OctoPrint/wiki/Plugin:-Plugin-Manager)
or manually using this URL:

    https://github.com/banichow/OctoPrint-Atxpihat/archive/master.zip

This plugin requires the pigpio library from joan@abyz.me.uk - http://abyz.co.uk/rpi/pigpio/python.html . Currently there is no pip installer for this library on the pi. Additionally, the standard installation does not setup pigpiod as a service. There are several available install scripts to do this, here is one implementation that I recommend. https://github.com/banichow/pigpioinstall 

This has to be **installed prior** to installing this plugin. smbus2 and RPi.GPIO are installed normally as a part of the plugin installation. 

This plugin is only supported on the Raspberry Pi 3, and has been tested on the Model B. At the time of development, we were unable to get any older version 3 boards for testing.

## Credits and Contributions

* ATXPiHat Hardware - Steve Smith - Xygax - https://www.facebook.com/Xygax
* PSUControl - Shawn Bruce - https://github.com/kantlivelong/
* LEDStripControl - https://github.com/google/OctoPrint-LEDStripControl
* pigpio - joan@abyz.me.uk - http://abyz.co.uk/rpi/pigpio/python.html
* mcp342x - s.marple@lancaster.ac.uk - Steve Marple - https://github.com/stevemarple/python-MCP342x
* Gina Häußge <gina@octoprint.org>

## Licensing
Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/
