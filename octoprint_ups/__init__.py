# coding=utf-8
from __future__ import absolute_import

__author__ = "Edilson Corea <edilsoncorrea117@gmail.com>"
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = "Copyright (C) 2021 Shawn Bruce - Released under terms of the AGPLv3 License"

import octoprint.plugin
from octoprint.events import Events
import time
import threading
from flask import make_response, jsonify
import requests
import os

try:
    from octoprint.access.permissions import Permissions
except Exception:
    from octoprint.server import user_permission

from .esphome_ups_client import EsphomeUPSClient

class UPS(octoprint.plugin.StartupPlugin,
          octoprint.plugin.TemplatePlugin,
          octoprint.plugin.AssetPlugin,
          octoprint.plugin.SettingsPlugin,
          octoprint.plugin.SimpleApiPlugin,
          octoprint.plugin.EventHandlerPlugin):

    def __init__(self):
        self.config = dict()
        self.ups = None
        self.vars = dict()

        self._pause_event = threading.Event()


    def get_settings_defaults(self):
        return dict(
            ha_url = 'http://homeassistant.local:8123',
            ha_token = '', # ha_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkMjU0MjcyNDg2NDg0YzkyODI0MjVlZjg4ZmQ4YmE2ZSIsImlhdCI6MTc1MTE1NDg1NiwiZXhwIjoyMDY2NTE0ODU2fQ.wQyB8O-j__HXpmfKEsoe15ixT7APLp3tYI0HEi0wcbk',
            entity_power = 'binary_sensor.ups_monitor_c3_01_ups_sem_energia_bateria',
            entity_critical = 'binary_sensor.ups_monitor_c3_01_ups_bateria_cr_tica',
            entity_shutdown = 'switch.ups_monitor_c3_01_comando_desligar_ups',
            pause = True
        )


    def on_settings_initialized(self):
        self.reload_settings()


    def on_after_startup(self):
        self._logger.setLevel("DEBUG")
        self._thread = threading.Thread(target=self._loop)
        self._thread.daemon = True
        self._thread.start()


    def reload_settings(self):
        for k, v in self.get_settings_defaults().items():
            if isinstance(v, str):
                v = self._settings.get([k])
            elif isinstance(v, bool):
                v = self._settings.get_boolean([k])
            self.config[k] = v

        self.ups = EsphomeUPSClient(
            base_url=self.config['ha_url'],
            entity_power=self.config['entity_power'],
            entity_critical=self.config['entity_critical'],
            entity_shutdown=self.config['entity_shutdown'],
            token=self.config['ha_token']
        )


    def _loop(self):
        prev_status = {}

        while True:
            time.sleep(1)
            status = self.ups.get_status()

            if not status:
                self.vars = {
                            'ups.status': 'OFFLINE',
                            'battery.charge': 0,
                            'battery.runtime': 3600,
                            'battery.critical': False
                        }                     

            else:
                on_battery = status.get('on_battery', False)
                critical = status.get('critical', False)

                if on_battery:
                    if critical:
                        battery_charge = 20
                        battery_runtime = 120
                    else:
                        battery_charge = 80
                        battery_runtime = 420
                    ups_status = 'OB'
                else:
                    battery_charge = 100
                    battery_runtime = 3600
                    ups_status = 'OL'

                self.vars = {
                            'ups.status': ups_status,
                            'battery.charge': battery_charge,
                            'battery.runtime': battery_runtime,
                            'battery.critical': critical
                        }                     

            if on_battery and not prev_status.get('on_battery', False):
                self._logger.info("Power lost. Running on battery.")

            if not on_battery and prev_status.get('on_battery', False):
                self._logger.info("Power restored.")

            if on_battery and critical:
                self._logger.info("Battery critical.")
                if (self.config["pause"] and
                    self._printer.is_printing() and
                    not (self._printer.is_paused() or self._printer.is_pausing())):

                    self._logger.info("Battery critical. Pausing job.")
                    self._pause_event.set()
                    self._printer.pause_print(tag={"source:plugin", "plugin:ups"})

            self._plugin_manager.send_plugin_message(self._identifier, dict(vars=self.vars))
            prev_status = status


    def _hook_comm_protocol_scripts(self, comm_instance, script_type, script_name, *args, **kwargs):
        if not script_type == "gcode":
            return None

        if script_name in ['afterPrintPaused', 'beforePrintResumed']:
            d = dict(initiated_pause=self._pause_event.is_set())
        else:
            return None

        if script_name == "beforePrintResumed":
            self._pause_event.clear()

        return (None, None, d)


    def on_event(self, event, payload):
        if event == Events.CLIENT_OPENED:
            self._plugin_manager.send_plugin_message(self._identifier, dict(vars=self.vars))
        if event == Events.PRINT_PAUSED and self._pause_event.is_set():
            self._logger.info("Impressão pausada. Enviando comando de shutdown para o UPS.")
            self.ups.shutdown()


    def get_api_commands(self):
        return dict(
            shutdown_ups=[]
        )


    def on_api_get(self, request):
        return self.on_api_command("getUPSVars", [])


    def on_api_command(self, command, data):
        if command == "shutdown_ups":
            resultado = self.ups.shutdown()
            return jsonify({"shutdown": resultado})


    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self.reload_settings()


    def get_settings_version(self):
        return 1


    def on_settings_migrate(self, target, current=None):
        if current is None:
            current = 0


    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=True)
        ]


    def get_assets(self):
        return {
            "js": ["js/ups.js"],
            "less": ["less/ups.less"],
            "css": ["css/ups.min.css"]
        }


    def get_update_information(self):
        return dict(
            ups=dict(
                displayName="UPS",
                displayVersion=self._plugin_version,
                type="github_release",
                user="edilsoncorrea",
                repo="OctoPrint-UPS",
                current=self._plugin_version,
                pip="https://github.com/edilsoncorrea/OctoPrint-UPS/archive/{target_version}.zip"
            )
        )


    def _hook_events_register_custom_events(self):
        return ["status_changed"]


__plugin_name__ = "UPS"
__plugin_pythoncompat__ = ">=3,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = UPS()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.events.register_custom_events": __plugin_implementation__._hook_events_register_custom_events,
        "octoprint.comm.protocol.scripts": __plugin_implementation__._hook_comm_protocol_scripts
    }

import os
if os.environ.get("OCTOPRINT_DEBUGPY", "0") == "1":
    import debugpy
    debugpy.listen(("0.0.0.0", 5678))
    print("Aguardando debugger conectar...")
    debugpy.wait_for_client()
