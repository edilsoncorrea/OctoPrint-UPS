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
        # Adicione estas variáveis para armazenar as temperaturas
        self._saved_extruder_temp = 0
        self._saved_bed_temp = 0
        self._pending_shutdown = False


    def get_settings_defaults(self):
        return dict(
            ha_url = 'http://homeassistant.local:8123',
            ha_token = '', # ha_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkMjU0MjcyNDg2NDg0YzkyODI0MjVlZjg4ZmQ4YmE2ZSIsImlhdCI6MTc1MTE1NDg1NiwiZXhwIjoyMDY2NTE0ODU2fQ.wQyB8O-j__HXpmfKEsoe15ixT7APLp3tYI0HEi0wcbk',
            entity_power = 'binary_sensor.ups_monitor_c3_01_ups_sem_energia_bateria',
            entity_critical = 'binary_sensor.ups_monitor_c3_01_ups_bateria_cr_tica',
            entity_shutdown = 'switch.ups_monitor_c3_01_comando_desligar_ups',
            pause = True,
            shutdown_temp_threshold = 50,
            block_resume_on_battery = True
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
            elif isinstance(v, int):
                v = self._settings.get_int([k])
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

            # Inicializa as variáveis padrão
            on_battery = False
            critical = False

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
                # Cancela shutdown pendente se a energia foi restaurada
                if self._pending_shutdown:
                    self._logger.info("Energia restaurada. Cancelando shutdown pendente do UPS.")
                    self._pending_shutdown = False

            if on_battery and critical:
                self._logger.info("Battery critical.")
                if (self.config["pause"] and
                    self._printer.is_printing() and
                    not (self._printer.is_paused() or self._printer.is_pausing())):

                    self._logger.info("Battery critical. Pausing job.")
                    self._pause_event.set()
                    self._pending_shutdown = True
                    self._printer.pause_print(tag={"source:plugin", "plugin:ups"})

            # Verifica se devemos desligar o UPS após pausar
            if self._pending_shutdown and self._printer.is_paused():
                self._check_and_shutdown_ups()

            self._plugin_manager.send_plugin_message(self._identifier, dict(vars=self.vars))
            prev_status = status


    def _check_and_shutdown_ups(self):
        """Verifica se as condições para desligar o UPS foram atendidas"""
        try:
            # Verifica o status atual do UPS
            ups_status = self.ups.get_status()
            if not ups_status:
                self._logger.warning("Não foi possível obter status do UPS. Cancelando shutdown.")
                self._pending_shutdown = False
                return
            
            on_battery = ups_status.get('on_battery', False)
            critical = ups_status.get('critical', False)
            
            # Verifica se o UPS ainda está na bateria e em condição crítica
            if not (on_battery and critical):
                self._logger.info("UPS não está mais na bateria ou não está mais em condição crítica. Cancelando shutdown.")
                self._pending_shutdown = False
                return
            
            # Verifica a temperatura do hotend
            current_temps = self._printer.get_current_temperatures()
            extruder_temp = current_temps.get('tool0', {}).get('actual', 0)
            
            threshold_temp = self.config.get('shutdown_temp_threshold', 50)
            
            if extruder_temp <= threshold_temp:
                self._logger.info(f"Todas as condições atendidas - UPS na bateria: {on_battery}, Crítico: {critical}, Temperatura: {extruder_temp}°C ≤ {threshold_temp}°C. Desligando UPS.")
                self.ups.shutdown()
                self._pending_shutdown = False
            else:
                self._logger.debug(f"Aguardando temperatura diminuir. UPS na bateria: {on_battery}, Crítico: {critical}, Temperatura atual: {extruder_temp}°C, Limite: {threshold_temp}°C")
                
        except Exception as e:
            self._logger.error(f"Erro ao verificar condições para shutdown: {e}")
            # Em caso de erro, verifica se ainda estamos em condição crítica antes do shutdown
            try:
                ups_status = self.ups.get_status()
                if ups_status and ups_status.get('on_battery', False) and ups_status.get('critical', False):
                    self._logger.info("Erro ao verificar temperatura, mas UPS ainda em condição crítica. Fazendo shutdown por segurança.")
                    self.ups.shutdown()
                else:
                    self._logger.info("Erro ao verificar temperatura, mas UPS não está mais crítico. Cancelando shutdown.")
            except:
                self._logger.error("Erro adicional ao verificar status do UPS. Cancelando shutdown por segurança.")
            self._pending_shutdown = False


    def _hook_comm_protocol_scripts(self, comm_instance, script_type, script_name, *args, **kwargs):
        if not script_type == "gcode":
            return None

        if script_name == 'afterPrintPaused':
            # Sempre salva as temperaturas atuais quando pausar
            try:
                current_temps = self._printer.get_current_temperatures()
                self._saved_extruder_temp = current_temps.get('tool0', {}).get('target', 0)
                self._saved_bed_temp = current_temps.get('bed', {}).get('target', 0)
                
                self._logger.info(f"Temperaturas salvas - Extrusor: {self._saved_extruder_temp}°C, Mesa: {self._saved_bed_temp}°C")
            except Exception as e:
                self._logger.error(f"Erro ao salvar temperaturas: {e}")
            
            return (None, None, dict(initiated_pause=self._pause_event.is_set()))
        
        elif script_name == 'beforePrintResumed':
            # Verifica se deve bloquear retomar impressão sem energia da rede
            if self.config.get('block_resume_on_battery', True):
                try:
                    ups_status = self.ups.get_status()
                    if not ups_status:
                        self._logger.warning("Tentativa de retomar impressão bloqueada: UPS desligado ou indisponível.")
                        # Retorna comandos que mostram mensagem de erro no terminal
                        error_commands = [
                            "M117 ERRO: UPS offline",  # Mensagem no display da impressora
                            "; ERRO: Não é possível retomar a impressão - UPS desligado ou indisponível",
                            "; Verifique a conexão e status do UPS antes de retomar"
                        ]
                        return (error_commands, None, dict(initiated_pause=False))
                    
                    on_battery = ups_status.get('on_battery', False)
                    if on_battery:
                        self._logger.warning("Tentativa de retomar impressão bloqueada: UPS está na bateria (sem energia da rede).")
                        # Retorna comandos que mostram mensagem de erro no terminal
                        error_commands = [
                            "M117 ERRO: UPS na bateria",  # Mensagem no display da impressora
                            "; ERRO: Não é possível retomar a impressão - UPS está na bateria",
                            "; Aguarde a energia da rede ser restaurada antes de retomar"
                        ]
                        return (error_commands, None, dict(initiated_pause=False))
                        
                except Exception as e:
                    self._logger.error(f"Erro ao verificar status do UPS para retomar: {e}")
                    self._logger.warning("Erro ao verificar UPS. Bloqueando retomar por segurança.")
                    error_commands = [
                        "M117 ERRO: Falha UPS",  # Mensagem no display da impressora
                        "; ERRO: Falha ao verificar status do UPS",
                        "; Verifique a conexão antes de retomar"
                    ]
                    return (error_commands, None, dict(initiated_pause=False))
                    
                # UPS ligado e com energia da rede, pode retomar normalmente
                self._logger.info("UPS ligado e com energia da rede. Permitindo retomar impressão.")
            else:
                self._logger.info("Proteção de retomar sem energia da rede está desabilitada.")
            
            # Reestabelece as temperaturas antes de retomar
            gcode_commands = []
            
            try:
                # Aquece extrusor e cama simultaneamente (sem esperar)
                if self._saved_extruder_temp > 0:
                    gcode_commands.append(f"M104 S{self._saved_extruder_temp}")  # Aquece extrusor
                    
                if self._saved_bed_temp > 0:
                    gcode_commands.append(f"M140 S{self._saved_bed_temp}")  # Aquece cama

                # Agora espera atingir as temperaturas
                if self._saved_extruder_temp > 0:
                    gcode_commands.append(f"M109 S{self._saved_extruder_temp}")  # Espera extrusor

                if self._saved_bed_temp > 0:
                    gcode_commands.append(f"M190 S{self._saved_bed_temp}")  # Espera cama
                
                self._logger.info(f"Reestabelecendo temperaturas - Extrusor: {self._saved_extruder_temp}°C, Cama: {self._saved_bed_temp}°C")
                
            except Exception as e:
                self._logger.error(f"Erro ao reestabelecer temperaturas: {e}")
            
            # Limpa o evento de pausa e pending shutdown após processar
            self._pause_event.clear()
            self._pending_shutdown = False
            
            # Retorna os comandos G-code para serem executados
            return (gcode_commands, None, dict(initiated_pause=True))
        
        return None


    def on_event(self, event, payload):
        if event == Events.CLIENT_OPENED:
            self._plugin_manager.send_plugin_message(self._identifier, dict(vars=self.vars))
        elif event in [Events.PRINT_CANCELLED, Events.PRINT_DONE]:
            # Limpa pending shutdown se a impressão for cancelada ou finalizada
            self._pending_shutdown = False
            self._pause_event.clear()
        elif event == Events.PRINT_RESUMED:
            # Verifica se a impressão foi retomada sem energia da rede
            if self.config.get('block_resume_on_battery', True):
                try:
                    ups_status = self.ups.get_status()
                    if not ups_status:
                        self._logger.error("ALERTA: Impressão foi retomada com UPS desligado/indisponível!")
                        # Pausa novamente imediatamente
                        self._logger.info("Pausando impressão novamente por segurança.")
                        self._printer.pause_print(tag={"source:plugin", "plugin:ups", "reason:ups_offline"})
                    elif ups_status.get('on_battery', False):
                        self._logger.error("ALERTA: Impressão foi retomada enquanto UPS está na bateria!")
                        # Pausa novamente imediatamente
                        self._logger.info("Pausando impressão novamente por segurança.")
                        self._printer.pause_print(tag={"source:plugin", "plugin:ups", "reason:ups_on_battery"})
                except Exception as e:
                    self._logger.error(f"Erro ao verificar status do UPS após retomar: {e}")
                    # Em caso de erro, pausa por segurança
                    self._logger.info("Erro ao verificar UPS. Pausando impressão por segurança.")
                    self._printer.pause_print(tag={"source:plugin", "plugin:ups", "reason:ups_check_error"})
        # Removido o shutdown automático - agora é controlado por temperatura


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
        return 2


    def on_settings_migrate(self, target, current=None):
        if current is None:
            current = 0
        
        if current < 2:
            # Migração para versão 2 - adiciona novas configurações
            self._logger.info("Migrando configurações do UPS para versão 2")
            
            # Força recarregamento das configurações padrão
            if not self._settings.has(['shutdown_temp_threshold']):
                self._settings.set(['shutdown_temp_threshold'], 50)
                
            if not self._settings.has(['block_resume_on_battery']):
                self._settings.set(['block_resume_on_battery'], True)
                
            self._settings.save()
            self._logger.info("Migração concluída - novas configurações adicionadas")


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

# Código de debug comentado
# import os
# if os.environ.get("OCTOPRINT_DEBUGPY", "0") == "1":
#     try:
#         import debugpy
#         debugpy.listen(("0.0.0.0", 5678))
#         print("Aguardando debugger conectar...")
#         debugpy.wait_for_client()
#     except ImportError:
#         print("debugpy não está disponível")
