# OctoPrint-Atxpihat
05/28/2018 - Version 1.1.2 - This version provides support for the new [ATXPiHat Zero](https://wp.me/p98gmw-bf). These are available for [sale at baprojectworkshop.com](https://baprojectworkshop.com/shop).

General Feature updates
* Fully compatible with Octoprint 1.3.8 or greater.
* Auto sense which board is installed and changes the driver to accommodate it.
* Refactored the ADC control software
* Initial testing on a Pi Zero W - More work is pending

At the time of development, we were unable to get the new Pi 3B+, this testing is pending.

ATXPiHat Zero updates - Please review all of the [feature differences](https://wp.me/p98gmw-bf)
* Added IO support – DHT11/22/AM2302/DS18B20/2 and 3 wire filament out sensors - These will be available for sale very soon.
* EPO support prior to power up

02/20/2018 - The boards are now available for [purchase at baprojectworkshop.com](https://baprojectworkshop.com/shop). 

Initial software release to support the [ATXPiHat](https://wp.me/p98gmw-7g) 1.0. A lot of the features below come disabled and are easily enabled on the settings tab. Here is the hardware/software features;

* Fully compatible with Octoprint 1.3.6 or greater.
* Directly power the Raspberry Pi 3B, no more external power source.
* ATX 24 Molex connector, no more cutting up the supply cables
* Amperage support to handle 19 amps at 12v for heat bed and hot end
* Screw connectors make easy connection to the main board, External Mosfet, etc
* Direct 12v RGB LED support, can also be controlled by GCODE
* Emergency power off (EPO)
* Power On/Off monitoring
* Visual indicator of the 12v supply being active and powering the external devices
* 12v monitored (RPM) cooling fan port
* Upon fan failure it can be configured to automatically shuts the printer down
* Auxiliary 5v support for external powered items
* Monitoring of the 12v rail, for amperage and voltage
* Automatic shutdown when an amperage threshold is reached. Meltdown protection
* Switchable 12 or 5 v connector for controlling external items via GCODE

This plugin is only supported on the Raspberry Pi 3, and has been tested on the Model B. At the time of development, we were unable to get any older version 3 boards for testing. Hardware setup images are/will be available on http://baprojectworkshop.com. Any requests for help, please use the [contact](https://baprojectworkshop.com/contact/) form for the quickest way to get help.

## Here is the standard disclaimer – you must understand and agree to this!
Understand this, this board has **not** been tested by an independent lab such as UL, or anyone else. **You use it at your own risk**. Each board is shipped tested and should work properly out of the box. They are designed to work with a Raspberry Pi 3b and Zero. However, all the work has been done on Pi 3b’s. I will work hard with the user to make sure that everything is good, however like anything in the RepRap space, you are responsible if you burn you house down. **Never, and I mean never, use this board and or your printer unsupervised. I will not be held accountable for anything that happens while using this board. Again, use it at your own risk.**

## Installation

Do not install the plugin until you have completed the installation steps below;
* After you backup the memory chip for the PI, **(Just do it)**
* It is always good to update the Raspbian image prior to any upgrade. From a terminal prompt;

        sudo apt-get update
        sudo apt-get dist-upgrade

* After completion, go ahead power down the PI and install the board. **Do not just power it off**,

         sudo shutdown now

* Plug the ATXPiHat in and connect the ATX power supply. Make sure that you **do not have any other power source plugged into the PI**, the board and power supply will take care of this. During the installation of the board to the PI, make sure that the board is plugged in to the pins properly and the board is supported on all of the screw holes. **Do not power the board if it is not plugged in properly to the PI. You will destroy the PI.** Check it twice.

* After turning on the ATX power supply, and the PI boots, you will need to [enable](https://learn.adafruit.com/adafruits-raspberry-pi-lesson-4-gpio-setup/configuring-i2c) the I2C interface on the PI. Adafruit has some great [instructions](https://learn.adafruit.com/adafruits-raspberry-pi-lesson-4-gpio-setup/configuring-i2c) on how to do this.

* This plugin requires the pigpio library from joan@abyz.me.uk - http://abyz.co.uk/rpi/pigpio/python.html . Currently there is no pip installer for this library on the PI, so Octoprint will not install it automatically or install it as a service. There are several available install scripts to do this, here is one [implementation](https://github.com/banichow/pigpioinstall) that I recommend. https://github.com/banichow/pigpioinstall 

* Make sure that there are no other plugins that would conflict with this plugin. PSUControl, LEDStripControl are two. With everything out there, I would review what I already have installed.

* Install via the bundled [Plugin Manager](https://github.com/foosel/OctoPrint/wiki/Plugin:-Plugin-Manager) or manually using this URL:

        https://github.com/banichow/OctoPrint-Atxpihat/archive/master.zip

* We found during our testing, it is a good idea to restart the Pi after installation or upgrade of the plugin. This will be the first thing that we will ask during any support requests.

* After this, sign into Octoprint and start working with the board.

## Credits and Contributions

* ATXPiHat Hardware - Steve Smith - Xygax - https://www.facebook.com/Xygax
* PSUControl - Shawn Bruce - https://github.com/kantlivelong/
* LEDStripControl - https://github.com/google/OctoPrint-LEDStripControl
* pigpio - joan@abyz.me.uk - http://abyz.co.uk/rpi/pigpio/python.html
* Octoprint-ETA - Pablo Ventura - https://github.com/pablogventura/Octoprint-ETA
* Gina Häußge <gina@octoprint.org>
* Octoprint-Filament-Reloaded - Connor Huffine - https://github.com/kontakt/Octoprint-Filament-Reloaded
* DS18B20 Temperature sensor - https://pimylifeup.com/raspberry-pi-temperature-sensor/
* https://learn.adafruit.com/adafruits-raspberry-pi-lesson-11-ds18b20-temperature-sensing/ds18b20
* https://www.modmypi.com/blog/am2302-temphumidity-sensor

## Licensing
Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/
