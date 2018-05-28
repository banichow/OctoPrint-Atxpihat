/*
author - "Brian Anichowski"
license - "Creative Commons Attribution-ShareAlike 4.0 International License - http://creativecommons.org/licenses/by-sa/4.0/"
copyright - "Copyright (C) 2018 Brian Anichowski http://www.baprojectworkshop.com"
version 1.1.2 - 05/28/2018

# **************** Contribution libraries and exampled **********************************
# ATXPiHat Hardware - Steve Smith - Xygax - https://www.facebook.com/Xygax
# PSUControl - Shawn Bruce - https://github.com/kantlivelong/
# LEDStripControl - https://github.com/google/OctoPrint-LEDStripControl
# pigpio - joan@abyz.me.uk - http://abyz.co.uk/rpi/pigpio/python.html
# Octoprint-ETA - Pablo Ventura - https://github.com/pablogventura/Octoprint-ETA
# Octoprint-Filament-Reloaded - Connor Huffine - https://github.com/kontakt/Octoprint-Filament-Reloaded
# DS18B20 Temperature sensor - https://pimylifeup.com/raspberry-pi-temperature-sensor/
# ***************************************************************************************
*/

$(function () {

    var workingurl = API_BASEURL + "plugin/atxpihat";

    function ProcessLEDColors(red, green, blue, bright) {

        // This is a fail safe to stop partial processing of the javascript
        if (red == undefined || green == undefined || blue == undefined || bright == undefined)
            return;

        var RGBColors = red + ',' + green + ',' + blue;
        $('#LEDFinalRGBCell').css('backgroundColor', 'rgb(' + RGBColors + ')');
        $('#LEDFinalRGB').text(RGBColors);

        $.ajax({
            url: workingurl,
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

    function ProcessExtSwitchValue(pwmvalue)
    {
        if (pwmvalue == undefined)
            return;

        $.ajax({
            url: workingurl,
            type: "POST",
            dataType: "json",
            data: JSON.stringify({
                command: "updateExtSwitch",
                ExternalSwitchValue: pwmvalue
            }),
            contentType: "application/json; charset=UTF-8"
        });
    }

    function ToggleExtSwitch()
    {
        $.ajax({
            url: workingurl,
            type: "POST",
            dataType: "json",
            data: JSON.stringify({
                command: "ToggleExtSwitch"
            }),
            contentType: "application/json; charset=UTF-8"
        });
    }

    function RefreshFilamentStatus()
    {
        $.ajax({
            url: workingurl,
            type: "POST",
            dataType: "json",
            data: JSON.stringify({
                command: "RefreshFilamentStatus"
            }),
            contentType: "application/json; charset=UTF-8"
        });
    }


    function GetSmartBoardInfo()
    {
        var result = false;
           $.ajax({
                url: workingurl,
                type: "POST",
                dataType: "json",
                data: JSON.stringify({ command: "IsSmartBoard" }),
                async: false,
                success: function (data) {
                    result = String(data).toLowerCase();
                },
                contentType: "application/json; charset=UTF-8"
            });

            return result == "true" ? true : false;
    }


    function ResetLEDSlider(LEDSliderTag, percent) {
        $(LEDSliderTag).find("div.slider-selection").css('width', percent + '%');
        $(LEDSliderTag).find("div.slider-handle").css('left', percent + '%');
    }

    function ATXPiHatViewModel(parameters) {
        var self = this;

        self.global_settings = parameters[0];
        self.settings = ko.observable();
        self.loginState = parameters[1];
        self.cvm = parameters[2];
        self.term = parameters[4];
        self.poweroff_dialog = undefined;

        self.LEDRed = ko.observable();
        self.LEDGreen = ko.observable();
        self.LEDBlue = ko.observable();
        self.LEDBrightness = ko.observable();
        self.ExtSwitchValue = ko.observable();
        self.FanRPMText = ko.observable();
        self.ATXVoltage = ko.observable();
        self.ATXAmperage = ko.observable();
        self.ATXFilament = ko.observable();
        self.ATXTemperature = ko.observable();
        self.ATXHumidity = ko.observable();
        self.ATXTempHum = ko.observable();
        self.CurrentExtSwitchState = ko.observable();
        self.IsSmartBoard = ko.observable();
        self.backgroundimage = ko.observable();

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
            if (self.global_settings.settings.plugins.atxpihat.PowerOffWarning()) {
                self.poweroff_dialog.modal("show");
            } else {
                self.CallToShutdownATXHat();
            }
        };

        self.ResetExtSwitchValue = function () {
               ResetLEDSlider("#ExtSwitchSlider",100);
               self.ExtSwitchValue(255);
               ProcessExtSwitchValue(255);
            };

        self.ToggleExtSwitch = function() {
            ToggleExtSwitch();
        }

        self.ResetLEDColors = function () {
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

        self.ExtSwitchText = ko.computed(function() {
            return self.ExtSwitchValue();
        });

        self.ExtSwitchValue.subscribe(function () {
            ProcessExtSwitchValue(self.ExtSwitchValue());
        });

        self.LEDRGBText = ko.computed(function () {
            return self.LEDRed() + ", " + self.LEDGreen() + ", " + self.LEDBlue();
        });

        self.LEDBrightness.subscribe(function() {
            ProcessLEDColors(self.LEDRed(), self.LEDGreen(), self.LEDBlue(), self.LEDBrightness());
        });

        self.LEDRGBText.subscribe(function () {
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

                // Faulted if fan is not running
                if (data.msg.toLowerCase() == "fanrpmfault") {
                    var fanrpmdialog = $('#fan_rpm_shutdown_dialog');
                    if (data.field1.toLowerCase() == 'true') {
                        fanrpmdialog.modal("show");
                    }
                    return;
                }

                // Refresh printer connections
                if (data.msg.toLowerCase() == "refreshconnection") {
                    self.cvm.requestData();
                    return;
                }

                // Handle EPO engaged/disengaged
                if (data.msg.toLowerCase() == "epoengaged") {
                    var epostatus = $('#atxpihat_epostatus_icon');
                    var epoengaged = $('#epo_engaged_dialog');
                    if (data.field1.toLowerCase() == 'true') {

                        epoengaged.modal("show");
                        epostatus.removeClass("fa-circle-o");
                        epostatus.addClass("fa-times-circle");

                    }
                    else {
                        epostatus.removeClass("fa-times-circle");
                        epostatus.addClass("fa-circle-o");

                    }
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

                if (data.msg.toLowerCase() == "backgroundimage") {
                    if (data.field1.toLowerCase() == 'true') {
                        $("#temperature-graph").css({"background-image":"url('')"});
                    }
                    else {
                        $("#temperature-graph").css({"background-image":"url('" + self.backgroundimage() +"')"});
                    }
                    return;
                }

                if (data.msg.toLowerCase() == "filterterminal") {
                    var checkbox1 = $('#terminal-filterpanel > div > label:nth-child(1) > input');
                    var checkbox3 = $('#terminal-filterpanel > div > label:nth-child(3) > input');
                    var filter, tofilter = false;
                    if (data.field1.toLowerCase() == 'true') {
                        filter = ["Recv:\\s+(ok\\s+)?(B|T\\d*):\\d.*|Recv:\\s+wait|Send: M105"];
                        tofilter = true;
                    }
                    else {
                        filter = [""];
                    }
                    self.term.filterRegex(filter);
                    self.term.activeFilters();
                    setTimeout(function()
                        {
                            checkbox1.prop('checked',tofilter);
                            checkbox3.prop('checked',tofilter);
                        },
                    1000);

                    return;
                }

                // Update the status box when settings are saved
                if (data.msg.toLowerCase() == "updatestatusbox") {
                    self.renderstatusbox(self.global_settings.settings.plugins.atxpihat);
                    return;
                }

                if (data.msg.toLowerCase() == "removetemp"){
                    $('#showTempHum').hide();
                }

                if (data.msg.toLowerCase() == "filamentstatus") {
                    if (data.field1.toLowerCase().startsWith("out")) {
                        self.ATXFilament('Out');
                        if (data.field1.toLowerCase() == "out")
                            $('#filament_out_pausedialog').modal('show');
                        return;
                    }
                    if (data.field1.toLowerCase() == "na") {
                        self.ATXFilament('N/A');
                        return;
                    }
                    if (data.field1.toLowerCase() == "good") {
                        self.ATXFilament('Loaded');
                        return;
                    }
                    return;
                }

                // Update the temprature and humidity display
                if (data.msg.toLowerCase() == "updatetemp") {
                    var wrkstr = '';
                    if (data.field1 != undefined)
                    {
                        self.ATXTemperature(data.field1);
                        wrkstr = data.field1
                    }
                    if (data.field2 != undefined)
                    {
                        self.ATXHumidity(data.field2);
                        if (wrkstr.length > 0) {
                            wrkstr = wrkstr + ' / '
                        }
                        wrkstr = wrkstr + data.field2
                    }
                    self.ATXTempHum(wrkstr);
                    return;
                }

                // If a smartboard then look to process amp/volt/switch
                if (self.IsSmartBoard()) {

                    // Fault if the amperage exceeds max
                    if (data.msg.toLowerCase() == "amperagefault") {
                        var fanrpmdialog = $('#amp_exceed_shutdown_dialog');
                        if (data.field1.toLowerCase() == 'true') {
                            fanrpmdialog.modal("show");
                        }
                        return;
                    }

                    if (data.msg.toLowerCase() == "atxvolts") {
                        self.ATXVoltage(data.field2);
                        self.ATXAmperage(data.field1);
                        return;
                    }

                    if (data.msg.toLowerCase() == "ampbaseline") {
                        self.ATXAmperage('Base Lining.....');
                    }

                    if (data.msg.toLowerCase() == "ampbaselinecomp") {
                        self.ATXAmperage('Base Line Complete');
                    }

                    if (data.msg.toLowerCase() == "extswitchpinstate") {
                        var togglebutton = $('#atxpihat_toggleextswitch');
                        if (data.field1.toLowerCase() == 'true') {
                            self.CurrentExtSwitchState('ON')
                            togglebutton.text('Turn Off');
                        }
                        else {
                            self.CurrentExtSwitchState('OFF')
                            togglebutton.text('Turn On');
                        }
                        return;
                    }
                }
            }
        };

        self.renderstatusbox = function(atxsettings) {

            showPSUFan = $('#showPSUFan');
            showPSUVolt = $('#showPSUVolt');
            showPSUAmp = $('#showPSUAmp');
            ATXStatusBox = $("#ATXStatusBox");
            showPSUFilament = $('#showPSUFilament');
            showTempHum = $('#showTempHum');

            if (!atxsettings.DisplayFanOnStatusPanel() &&
                !atxsettings.DisplayPWROnStatusPanel() &&
                !atxsettings.DisplayFilamentStatusPanel() &&
                !atxsettings.DisplayTemperatureOnStatusPanel() &&
                !atxsettings.IO4Enabled)
            {
                ATXStatusBox.hide();
                return;
            }
            else
            {
                ATXStatusBox.show();
            }

            if (atxsettings.IO4Enabled() && !self.IsSmartBoard()) {
                // Display Filament sensor
                if (atxsettings.IO4Behaviour().startsWith('FILAMENT') && atxsettings.DisplayFilamentStatusPanel()) {
                    showPSUFilament.show();
                }
                else {
                    showPSUFilament.hide();
                }

                //DisplayTemperatureOnStatusPanel
                if ((atxsettings.IO4Behaviour().startsWith('DHT') || atxsettings.IO4Behaviour().startsWith('DS')) && atxsettings.DisplayTemperatureOnStatusPanel()) {
                    showTempHum.show();
                }
                else {
                    showTempHum.hide();
                }
            }
            else
            {
                showPSUFilament.hide();
                showTempHum.hide();
            }

            if (atxsettings.DisplayFanOnStatusPanel() && atxsettings.MonitorFanRPM()) {
                showPSUFan.show();
            }
            else
            {
                showPSUFan.hide();
            }

            if (self.IsSmartBoard() && atxsettings.DisplayPWROnStatusPanel() && atxsettings.MonitorPower()) {
                showPSUAmp.show();
                showPSUVolt.show();
            }
            else
            {
                showPSUAmp.hide();
                showPSUVolt.hide();
            }
        };

        self.onBeforeBinding = function () {
            self.IsSmartBoard(GetSmartBoardInfo());
            self.atxsettings = self.global_settings.settings.plugins.atxpihat;
            self.LEDRed(self.atxsettings.LEDRed());
            self.LEDGreen(self.atxsettings.LEDGreen());
            self.LEDBlue(self.atxsettings.LEDBlue());
            self.LEDBrightness(self.atxsettings.LEDBrightness());
            self.ExtSwitchValue(self.atxsettings.ExternalSwitchValue());

            // Add when the page is setup
            var element = $("#state").find(".accordion-inner .progress");
            if (element.length) {
                var toinsert = "<div id='ATXStatusBox' data-bind=\"visible: loginState.isUser()\"><hr>" +
                "<div id='showPSUFan'>Fan RPM: <strong id='PSUFanRPMstring' data-bind=\"html: FanRPMText\"></strong><br></div>" +
                "<div id='showPSUVolt'>Voltage: <strong id='PSUVoltstring' data-bind=\"html: ATXVoltage\"></strong><br></div>" +
                "<div id='showPSUAmp'>Amperage: <strong id='PSUAmpstring' data-bind=\"html: ATXAmperage\"></strong><br></div>" +
                "<div id='showPSUFilament'>Filament: <strong id='Filamentstring' data-bind=\"html: ATXFilament\"></strong><br></div>" +
                "<div id='showTempHum'>Temp/Hum: <strong id='Tempstring' data-bind=\"html: ATXTempHum\"></strong><br></div>" +
                "<hr></div>";
                element.before(toinsert);
            }

            self.renderstatusbox(self.atxsettings);

            ProcessLEDColors(self.LEDRed(), self.LEDGreen(), self.LEDBlue(), self.LEDBrightness());
            ProcessExtSwitchValue(self.ExtSwitchValue());
            RefreshFilamentStatus();
        };

        self.onAfterBinding = function() {
            self.settings(self.global_settings.settings.plugins.atxpihat);
            self.poweroff_dialog = $("#ATXHatpoweroffconfirmation");
            self.backgroundimage($("#temperature-graph").css("background-image").replace(/^url\(['"]?/,'').replace(/['"]?\)$/,''));

            if (self.settings.RemoveLogo)
                $("#temperature-graph").css({"background-image":"url('')"});

        };

        self.onUserLoggedIn = function(user) {
            // the only way to have this call work is to be logged in.
            // It only has to be called once.
            var logo = self.global_settings.settings.plugins.atxpihat.RemoveLogo();
            self.IsSmartBoard(GetSmartBoardInfo());
            self.renderstatusbox(self.global_settings.settings.plugins.atxpihat);
            RefreshFilamentStatus();

             if (logo)
                $("#temperature-graph").css({"background-image":"url('')"});
             else
                 $("#temperature-graph").css({"background-image":"url('" + self.backgroundimage() +"')"});
        }
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: ATXPiHatViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel", "connectionViewModel","printerStateViewModel","terminalViewModel"],
        elements: ["#tab_plugin_atxpihat", "#navbar_plugin_atxpihat", "#navbar_plugin_atxpihat_2","#PSUVoltstring",
                    "#PSUAmpstring","#PSUFanRPMstring","#Filamentstring","#Tempstring","#settings_plugin_atxpihat"]
    });

});

