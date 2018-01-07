/*
author - "Brian Anichowski"
license - "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
copyright - "Copyright (C) 2018 Brian Anichowski http://www.baprojectworkshop.com"

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

*/

$(function () {
    function ProcessLEDColors(red, green, blue, bright) {

        // This is a fail safe to stop partial processing of the javascript
        if (red == undefined || green == undefined || blue == undefined || bright == undefined)
            return;

        var RGBColors = red + ',' + green + ',' + blue;
        $('#LEDFinalRGBCell').css('backgroundColor', 'rgb(' + RGBColors + ')');
        $('#LEDFinalRGB').text(RGBColors);

        $.ajax({
            url: API_BASEURL + "plugin/atxpihat",
            type: "POST",
            dataType: "json",
            data: JSON.stringify({
                command: "updateLED",
                LEDRed: red,
                LEDGreen: green,
                LEDBlue: blue,
                LEDBrightness: bright
            }),
            contentType: "application/json; charset=UTF-8"
        });
    }

    function ResetLEDSlider(LEDSliderTag, percent) {
        $(LEDSliderTag).find("div.slider-selection").css('width', percent + '%');
        $(LEDSliderTag).find("div.slider-handle").css('left', percent + '%');
    }

    function ATXPiHatViewModel(parameters) {
        var self = this;

        self.global_settings = parameters[0];
        self.settings = undefined;
        self.loginState = parameters[1];
        self.cvm = parameters[2];
        self.poweroff_dialog = undefined;


        self.LEDRed = ko.observable();
        self.LEDGreen = ko.observable();
        self.LEDBlue = ko.observable();
        self.LEDBrightness = ko.observable();
        self.FanRPMText = ko.observable();
        self.ATXVoltage = ko.observable();
        self.ATXAmperage = ko.observable();

        self.StartATXHat = function ()  {
            $.ajax({
                url: API_BASEURL + "plugin/atxpihat",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "turnATXPSUOn"
                }),
                contentType: "application/json; charset=UTF-8"
            });
        };

        self.CallToShutdownATXHat = function() {
            $.ajax({
                url: API_BASEURL + "plugin/atxpihat",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "turnATXPSUOff"
                }),
                contentType: "application/json; charset=UTF-8"
            })

            self.poweroff_dialog.modal("hide");
        };

        self.ShutdownATXHat = function() {
            if (self.settings.PowerOffWarning()) {
                self.poweroff_dialog.modal("show");
            } else {
                self.CallToShutdownATXHat();
            }
        };

        self.ResetLEDColors =
            function () {
                ResetLEDSlider("#LEDBlueSlider",0);
                ResetLEDSlider("#LEDRedSlider",0);
                ResetLEDSlider("#LEDGreenSlider",0);
                ResetLEDSlider("#LEDBrightnessSlider",100);
                self.LEDBlue(0);
                self.LEDRed(0);
                self.LEDGreen(0);
                self.LEDBrightness(100);
                ProcessLEDColors(0, 0, 0, 100);
            };


        self.LEDRGBText = ko.computed(function () {
            return self.LEDRed() + ", " + self.LEDGreen() + ", " + self.LEDBlue();
        });

        self.LEDBrightness.subscribe(function()
        {
            ProcessLEDColors(self.LEDRed(), self.LEDGreen(), self.LEDBlue(), self.LEDBrightness());
        });

        self.LEDRGBText.subscribe(function ()
        {
            ProcessLEDColors(self.LEDRed(), self.LEDGreen(), self.LEDBlue(), self.LEDBrightness());
        });

        self.onDataUpdaterPluginMessage = function (plugin, data) {

            if (plugin != "atxpihat") {
                return;
            }

            if ((data != undefined) && (data.msg != undefined)) {

                // Update Fan RPM
                if (data.msg.toLowerCase() == "fanrpm") {
                    self.FanRPMText(Math.round(data.field1));
                    return;
                }
                                // Update Fan RPM
                if (data.msg.toLowerCase() == "atxvolts") {
                    self.ATXVoltage(data.field2);
                    self.ATXAmperage(data.field1);
                    return;
                }

                // Faulted if fan is not running
                if (data.msg.toLowerCase() == "fanrpmfault") {
                    var fanrpmdialog = $('#fan_rpm_shutdown_dialog');
                    if (data.field1.toLowerCase() == 'true') {
                        fanrpmdialog.modal("show");
                    }
                }

                //If power on and EPO engaged fault
                if (data.msg.toLowerCase() == "csepoengaged") {
                    $('#cannotstart_epo_engaged_dialog').modal("show");
                }

                // Refresh printer connections
                if (data.msg.toLowerCase() == "refreshconnection") {
                    self.cvm.requestData();
                    return;
                }

                // Update the power status
                if (data.msg.toLowerCase() == "pwrstatus") {
                    var onbutton = $('#atxpihat_pwronbutton');
                    var offbutton = $('#atxpihat_pwroffbutton');
                    var psu_indicator = $('#atxpihat_pwrstatus');

                    if (data.field1.toLowerCase() == 'true') {
                        psu_indicator.css('color', 'lightgreen');
                        onbutton.hide();
                        offbutton.show();
                    }
                    else {
                        psu_indicator.css('color', 'black');
                        offbutton.hide();
                        onbutton.show();
                    }
                    return;
                }

                // Handle EPO engaged/disengaged
                if (data.msg.toLowerCase() == "epoengaged") {
                    var epostatus = $('#atxpihat_epostatus');
                    var epoengaged = $('#epo_engaged_dialog');
                    if (data.field1.toLowerCase() == 'true') {
                        epoengaged.modal("show");
                        epostatus.css('color', 'red');
                    }
                    else {
                        epostatus.css('color', 'black');
                    }
                    return;
                }
            }
        };


       self.onBeforeBinding = function () {
            self.atxsettings = self.global_settings.settings.plugins.atxpihat;
            self.LEDRed(self.atxsettings.LEDRed());
            self.LEDGreen(self.atxsettings.LEDGreen());
            self.LEDBlue(self.atxsettings.LEDBlue());
            self.LEDBrightness(self.atxsettings.LEDBrightness());

            ProcessLEDColors(self.LEDRed(), self.LEDGreen(), self.LEDBlue(), self.LEDBrightness());
        };

        self.onAfterBinding = function() {
            self.settings = self.global_settings.settings.plugins.atxpihat;
            self.poweroff_dialog = $("#ATXHatpoweroffconfirmation");
        }

    }

    ADDITIONAL_VIEWMODELS.push([
        ATXPiHatViewModel,
        ["settingsViewModel", "loginStateViewModel","connectionViewModel"],
        ["#tab_plugin_atxpihat","#navbar_plugin_atxpihat","#navbar_plugin_atxpihat_2"]
    ]);

});
