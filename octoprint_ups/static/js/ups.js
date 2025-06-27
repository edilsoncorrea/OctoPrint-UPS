/* global OCTOPRINT_VIEWMODE_SETTINGS */
$(function() {
    function UPSViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0];

        self.onBeforeBinding = function() {
            self.settings = self.settingsViewModel.settings.plugins.ups;
        };
    }

    OCTOPRINT_VIEWMODE_SETTINGS.push({
        id: "ups",
        name: "UPS (ESPHome)",
        template: "/plugin/ups/ups_settings.jinja2",
        getViewModel: function() {
            return [UPSViewModel];
        }
    });
});
