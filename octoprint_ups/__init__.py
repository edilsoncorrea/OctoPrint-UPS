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
          octoprint.plugin.EventHandlerPlugin,
          octoprint.plugin.ProgressPlugin):

    def __init__(self):
        self.config = dict()
        self.ups = None
        self.vars = dict()
        
        self._pause_event = threading.Event()
        # Variáveis para armazenar as temperaturas
        self._saved_extruder_temp = 0
        self._saved_bed_temp = 0
        self._pending_shutdown = False
        
        # Variáveis para salvar estado da impressão antes do shutdown
        self._print_state_saved = False
        self._saved_print_file = None
        self._saved_print_position = None
        self._saved_print_progress = 0
        self._saved_file_position = 0  # Posição no arquivo (byte offset)
        self._saved_line_number = 0    # Número da linha no G-code
        self._saved_coordinates = {'x': 0, 'y': 0, 'z': 0, 'e': 0}  # Coordenadas físicas
        self._shutdown_occurred = False


    def get_settings_defaults(self):
        return dict(
            ha_url = 'http://homeassistant.local:8123',
            ha_token = '', # ha_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkMjU0MjcyNDg2NDg0YzkyODI0MjVlZjg4ZmQ4YmE2ZSIsImlhdCI6MTc1MTE1NDg1NiwiZXhwIjoyMDY2NTE0ODU2fQ.wQyB8O-j__HXpmfKEsoe15ixT7APLp3tYI0HEi0wcbk',
            entity_power = 'binary_sensor.ups_monitor_c3_01_ups_sem_energia_bateria',
            entity_critical = 'binary_sensor.ups_monitor_c3_01_ups_bateria_cr_tica',
            entity_shutdown = 'switch.ups_monitor_c3_01_comando_desligar_ups',
            pause = True,
            shutdown_temp_threshold = 50,
            block_resume_on_battery = True,
            save_print_state = True,
            auto_recover_after_shutdown = True
        )


    def on_settings_initialized(self):
        self.reload_settings()


    def on_after_startup(self):
        self._logger.setLevel("DEBUG")
        
        # Carrega estado salvo da impressão se houver
        if self._load_print_state():
            self._logger.info("Estado de impressão anterior encontrado após startup.")
        
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
                self._logger.info(f"Todas as condições atendidas - UPS na bateria: {on_battery}, Crítico: {critical}, Temperatura: {extruder_temp}°C ≤ {threshold_temp}°C. Preparando shutdown do UPS.")
                
                # Salva estado da impressão antes do shutdown
                if self.config.get('save_print_state', True):
                    self._save_print_state()
                
                # Executa shutdown do UPS
                self._logger.info("Executando shutdown do UPS...")
                self.ups.shutdown()
                self._pending_shutdown = False
                self._shutdown_occurred = True
                
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
            # Limpa estado salvo se impressão foi finalizada normalmente
            if event == Events.PRINT_DONE:
                self._clear_saved_state()
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
        elif event == Events.CONNECTED:
            # Impressora reconectada - oferece recuperação de impressão se disponível
            self._logger.info("Impressora reconectada.")
            if self._print_state_saved:
                # Aguarda um pouco para garantir que a conexão está estável
                def delayed_recovery():
                    time.sleep(5)  # Espera 5 segundos
                    self._offer_print_recovery()
                
                recovery_thread = threading.Thread(target=delayed_recovery)
                recovery_thread.daemon = True
                recovery_thread.start()
        elif event == Events.DISCONNECTED:
            # Impressora desconectada
            self._logger.info("Impressora desconectada.")
            if self._shutdown_occurred:
                self._logger.info("Desconexão detectada após shutdown do UPS.")
                self._shutdown_occurred = False
        # Removido o shutdown automático - agora é controlado por temperatura


    def get_api_commands(self):
        return dict(
            shutdown_ups=[],
            get_recovery_info=[],
            start_recovery=[],
            clear_recovery=[]
        )


    def on_api_get(self, request):
        return self.on_api_command("getUPSVars", [])


    def on_api_command(self, command, data):
        if command == "shutdown_ups":
            resultado = self.ups.shutdown()
            return jsonify({"shutdown": resultado})
        
        elif command == "get_recovery_info":
            if self._print_state_saved:
                return jsonify({
                    "available": True,
                    "file": self._saved_print_file,
                    "progress": self._saved_print_progress,
                    "extruder_temp": self._saved_extruder_temp,
                    "bed_temp": self._saved_bed_temp
                })
            else:
                return jsonify({"available": False})
        
        elif command == "start_recovery":
            if not self._print_state_saved:
                return jsonify({"success": False, "message": "Nenhum estado de recuperação disponível"})
            
            try:
                # Verifica se não há impressão ativa
                if self._printer.is_printing() or self._printer.is_paused():
                    return jsonify({"success": False, "message": "Há uma impressão ativa. Cancele antes de recuperar."})
                
                # Inicia processo de recuperação
                if self._saved_print_file:
                    self._logger.info(f"Iniciando recuperação exata da impressão: {self._saved_print_file}")
                    self._logger.info(f"Posição: {self._saved_file_position} bytes, Linha: {self._saved_line_number}")
                    
                    # Seleciona o arquivo
                    self._printer.select_file(self._saved_print_file, False)
                    
                    # Executa G-code de recuperação
                    recovery_commands = self._create_recovery_gcode()
                    if recovery_commands:
                        # Envia comandos de recuperação
                        for cmd in recovery_commands:
                            self._printer.commands(cmd)
                    
                    # Informa sobre a recuperação
                    recovery_info = {
                        "success": True,
                        "message": f"Recuperação iniciada na posição exata",
                        "details": {
                            "progress": f"{self._saved_print_progress:.1f}%",
                            "position": f"X{self._saved_coordinates['x']:.2f} Y{self._saved_coordinates['y']:.2f} Z{self._saved_coordinates['z']:.2f}",
                            "file_position": self._saved_file_position,
                            "line_number": self._saved_line_number,
                            "extruder_temp": self._saved_extruder_temp,
                            "bed_temp": self._saved_bed_temp
                        }
                    }
                    
                    # Nota importante para o usuário
                    self._logger.warning("ATENÇÃO: Após aquecimento, você precisa:")
                    self._logger.warning("1. Verificar se o cabeçote está na posição correta")
                    self._logger.warning("2. Iniciar impressão manualmente do ponto onde parou")
                    self._logger.warning(f"3. Use 'Restart print from line {self._saved_line_number}' se suportado")
                    
                    return jsonify(recovery_info)
                else:
                    return jsonify({"success": False, "message": "Arquivo de impressão não encontrado"})
                    
            except Exception as e:
                self._logger.error(f"Erro durante recuperação: {e}")
                return jsonify({"success": False, "message": f"Erro durante recuperação: {str(e)}"})
        
        elif command == "clear_recovery":
            self._clear_saved_state()
            return jsonify({"success": True, "message": "Estado de recuperação limpo"})


    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self.reload_settings()


    def get_settings_version(self):
        return 3


    def on_settings_migrate(self, target, current=None):
        if current is None:
            current = 0
        
        if current < 2:
            # Migração para versão 2 - adiciona configurações de temperatura e bloqueio
            self._logger.info("Migrando configurações do UPS para versão 2")
            
            if not self._settings.has(['shutdown_temp_threshold']):
                self._settings.set(['shutdown_temp_threshold'], 50)
                
            if not self._settings.has(['block_resume_on_battery']):
                self._settings.set(['block_resume_on_battery'], True)
                
            self._settings.save()
            self._logger.info("Migração v2 concluída - configurações de temperatura adicionadas")
        
        if current < 3:
            # Migração para versão 3 - adiciona configurações de recuperação
            self._logger.info("Migrando configurações do UPS para versão 3")
            
            if not self._settings.has(['save_print_state']):
                self._settings.set(['save_print_state'], True)
                
            if not self._settings.has(['auto_recover_after_shutdown']):
                self._settings.set(['auto_recover_after_shutdown'], True)
                
            self._settings.save()
            self._logger.info("Migração v3 concluída - configurações de recuperação adicionadas")


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

    def _save_print_state(self):
        """Salva o estado atual da impressão antes do shutdown"""
        try:
            self._logger.info("Salvando estado da impressão...")
            
            # Verifica se há uma impressão ativa
            if not self._printer.is_printing() and not self._printer.is_paused():
                self._logger.warning("Nenhuma impressão ativa para salvar estado.")
                return False
            
            # Obtém informações do trabalho atual
            current_job = self._printer.get_current_job()
            if not current_job or not current_job.get('file', {}).get('name'):
                self._logger.error("Não foi possível obter informações do trabalho atual.")
                return False
            
            # Salva informações básicas
            self._saved_print_file = current_job['file']['path']
            file_info = current_job['file']
            
            # Obtém progresso atual
            current_data = self._printer.get_current_data()
            if current_data and current_data.get('progress'):
                self._saved_print_progress = current_data['progress'].get('completion', 0)
                self._saved_file_position = current_data['progress'].get('filepos', 0)
            else:
                self._saved_print_progress = 0
                self._saved_file_position = 0
            
            # Obtém temperaturas atuais
            current_temps = self._printer.get_current_temperatures()
            self._saved_extruder_temp = current_temps.get('tool0', {}).get('target', 0)
            self._saved_bed_temp = current_temps.get('bed', {}).get('target', 0)
            
            # Obtém posição atual do cabeçote usando M114
            self._get_current_position()
            
            # Calcula número da linha aproximado baseado no progresso
            if file_info.get('size', 0) > 0 and self._saved_file_position > 0:
                # Lê o arquivo para determinar o número da linha
                try:
                    with open(file_info.get('path', ''), 'r') as f:
                        content = f.read(self._saved_file_position)
                        self._saved_line_number = content.count('\n') + 1
                except Exception as e:
                    self._logger.warning(f"Erro ao calcular número da linha: {e}")
                    # Estimativa baseada no progresso
                    estimated_total_lines = file_info.get('size', 0) // 50  # Assume ~50 chars por linha
                    self._saved_line_number = int(estimated_total_lines * (self._saved_print_progress / 100))
            else:
                self._saved_line_number = 0
            
            # Salva estado em arquivo persistente
            self._save_state_to_file()
            
            self._print_state_saved = True
            
            self._logger.info(f"Estado salvo com sucesso:")
            self._logger.info(f"  - Arquivo: {self._saved_print_file}")
            self._logger.info(f"  - Progresso: {self._saved_print_progress:.1f}%")
            self._logger.info(f"  - Posição arquivo: {self._saved_file_position} bytes")
            self._logger.info(f"  - Linha estimada: {self._saved_line_number}")
            self._logger.info(f"  - Coordenadas: X{self._saved_coordinates['x']:.2f} Y{self._saved_coordinates['y']:.2f} Z{self._saved_coordinates['z']:.2f}")
            self._logger.info(f"  - Temperaturas: Extrusor {self._saved_extruder_temp}°C, Mesa {self._saved_bed_temp}°C")
            
            return True
            
        except Exception as e:
            self._logger.error(f"Erro ao salvar estado da impressão: {e}")
            return False

    def _get_current_position(self):
        """Obtém a posição atual do cabeçote usando comando M114"""
        try:
            # Comando M114 para obter posição atual
            def position_callback(comm, line, *args, **kwargs):
                # Processa resposta do M114
                if line.startswith("X:") or "X:" in line:
                    try:
                        # Parse da linha: "X:123.45 Y:67.89 Z:1.23 E:45.67"
                        parts = line.strip().split()
                        for part in parts:
                            if part.startswith("X:"):
                                self._saved_coordinates['x'] = float(part[2:])
                            elif part.startswith("Y:"):
                                self._saved_coordinates['y'] = float(part[2:])
                            elif part.startswith("Z:"):
                                self._saved_coordinates['z'] = float(part[2:])
                            elif part.startswith("E:"):
                                self._saved_coordinates['e'] = float(part[2:])
                        
                        self._logger.debug(f"Posição atual obtida: {self._saved_coordinates}")
                    except Exception as e:
                        self._logger.warning(f"Erro ao interpretar posição M114: {e}")
            
            # Registra callback temporário e envia M114
            self._printer.commands("M114")
            
            # Como não temos acesso direto ao callback, vamos usar uma abordagem alternativa
            # Salva as coordenadas com valores padrão caso M114 falhe
            if not any(self._saved_coordinates.values()):
                self._logger.warning("Não foi possível obter posição atual, usando coordenadas padrão")
                self._saved_coordinates = {'x': 0, 'y': 0, 'z': 10, 'e': 0}
                
        except Exception as e:
            self._logger.error(f"Erro ao obter posição atual: {e}")
            # Coordenadas padrão de segurança
            self._saved_coordinates = {'x': 0, 'y': 0, 'z': 10, 'e': 0}

    def _save_state_to_file(self):
        """Salva o estado em um arquivo JSON para persistência"""
        try:
            import json
            
            state_data = {
                'print_file': self._saved_print_file,
                'progress': self._saved_print_progress,
                'file_position': self._saved_file_position,
                'line_number': self._saved_line_number,
                'coordinates': self._saved_coordinates,
                'extruder_temp': self._saved_extruder_temp,
                'bed_temp': self._saved_bed_temp,
                'timestamp': time.time()
            }
            
            # Salva no diretório de dados do plugin
            state_file = os.path.join(self.get_plugin_data_folder(), 'print_state.json')
            
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
            
            self._logger.debug(f"Estado salvo em arquivo: {state_file}")
            
        except Exception as e:
            self._logger.error(f"Erro ao salvar estado em arquivo: {e}")

    def _load_print_state(self):
        """Carrega o estado salvo da impressão"""
        try:
            import json
            
            state_file = os.path.join(self.get_plugin_data_folder(), 'print_state.json')
            
            if not os.path.exists(state_file):
                return False
            
            with open(state_file, 'r') as f:
                state_data = json.load(f)
            
            # Restaura variáveis
            self._saved_print_file = state_data.get('print_file')
            self._saved_print_progress = state_data.get('progress', 0)
            self._saved_file_position = state_data.get('file_position', 0)
            self._saved_line_number = state_data.get('line_number', 0)
            self._saved_coordinates = state_data.get('coordinates', {'x': 0, 'y': 0, 'z': 10, 'e': 0})
            self._saved_extruder_temp = state_data.get('extruder_temp', 0)
            self._saved_bed_temp = state_data.get('bed_temp', 0)
            
            self._print_state_saved = True
            
            self._logger.info(f"Estado carregado com sucesso:")
            self._logger.info(f"  - Arquivo: {self._saved_print_file}")
            self._logger.info(f"  - Progresso: {self._saved_print_progress:.1f}%")
            self._logger.info(f"  - Linha: {self._saved_line_number}")
            self._logger.info(f"  - Coordenadas: X{self._saved_coordinates['x']:.2f} Y{self._saved_coordinates['y']:.2f} Z{self._saved_coordinates['z']:.2f}")
            
            return True
            
        except Exception as e:
            self._logger.error(f"Erro ao carregar estado da impressão: {e}")
            return False

    def _offer_print_recovery(self):
        """Oferece recuperação de impressão após reconexão"""
        if not self._print_state_saved:
            return
        
        if not self.config.get('auto_recover_after_shutdown', True):
            self._logger.info("Recuperação automática está desabilitada.")
            return
        
        self._logger.info("=== RECUPERAÇÃO DE IMPRESSÃO DISPONÍVEL ===")
        self._logger.info(f"Arquivo: {self._saved_print_file}")
        self._logger.info(f"Progresso antes do shutdown: {self._saved_print_progress:.1f}%")
        self._logger.info(f"Posição: X{self._saved_coordinates['x']:.2f} Y{self._saved_coordinates['y']:.2f} Z{self._saved_coordinates['z']:.2f}")
        self._logger.info("Use a API '/api/plugin/ups' com comando 'start_recovery' para recuperar.")
        self._logger.info("Ou acesse as configurações do plugin UPS para recuperação manual.")
        
        # Envia notificação para o frontend se possível
        try:
            self._plugin_manager.send_plugin_message(self._identifier, {
                'type': 'recovery_available',
                'data': {
                    'file': self._saved_print_file,
                    'progress': self._saved_print_progress,
                    'position': f"X{self._saved_coordinates['x']:.2f} Y{self._saved_coordinates['y']:.2f} Z{self._saved_coordinates['z']:.2f}"
                }
            })
        except:
            pass  # Se falhar, não é crítico

    def _create_recovery_gcode(self):
        """Cria comandos G-code para recuperação da impressão"""
        try:
            commands = []
            
            # 1. Comentários informativos
            commands.append("; === RECUPERAÇÃO DE IMPRESSÃO UPS ===")
            commands.append(f"; Arquivo: {self._saved_print_file}")
            commands.append(f"; Progresso: {self._saved_print_progress:.1f}%")
            commands.append(f"; Linha aproximada: {self._saved_line_number}")
            
            # 2. Configuração inicial
            commands.append("G90 ; Modo absoluto")
            commands.append("M82 ; Extrusor absoluto")
            
            # 3. Home dos eixos
            commands.append("G28 X Y ; Home X e Y")
            
            # 4. Aquecimento (sem esperar inicialmente)
            if self._saved_extruder_temp > 0:
                commands.append(f"M104 S{self._saved_extruder_temp} ; Aquece extrusor para {self._saved_extruder_temp}°C")
            
            if self._saved_bed_temp > 0:
                commands.append(f"M140 S{self._saved_bed_temp} ; Aquece mesa para {self._saved_bed_temp}°C")
            
            # 5. Posicionamento Z seguro
            safe_z = max(self._saved_coordinates['z'], 10)  # Pelo menos 10mm
            commands.append(f"G1 Z{safe_z} F3000 ; Move Z para posição segura")
            
            # 6. Espera aquecimento
            if self._saved_extruder_temp > 0:
                commands.append(f"M109 S{self._saved_extruder_temp} ; Espera extrusor aquecer")
            
            if self._saved_bed_temp > 0:
                commands.append(f"M190 S{self._saved_bed_temp} ; Espera mesa aquecer")
            
            # 7. Purga do extrusor
            commands.append("G1 E-5 F1800 ; Retrai filamento")
            commands.append("G1 E5 F300 ; Purga lentamente")
            commands.append("G1 E-2 F1800 ; Retrai um pouco")
            
            # 8. Posicionamento final
            commands.append(f"G1 X{self._saved_coordinates['x']:.2f} Y{self._saved_coordinates['y']:.2f} F6000 ; Move para posição XY")
            commands.append(f"G1 Z{self._saved_coordinates['z']:.2f} F3000 ; Move para posição Z")
            
            # 9. Instruções finais
            commands.append("; === INSTRUÇÕES ===")
            commands.append(f"; 1. Verifique se o cabeçote está na posição correta")
            commands.append(f"; 2. Inicie a impressão manualmente a partir da linha {self._saved_line_number}")
            commands.append(f"; 3. Ou use 'Restart from line {self._saved_line_number}' se suportado")
            commands.append("M117 Pronto p/ recuperacao ; Mensagem no display")
            
            self._logger.info(f"Comandos de recuperação criados: {len(commands)} linhas")
            return commands
            
        except Exception as e:
            self._logger.error(f"Erro ao criar comandos de recuperação: {e}")
            return []

    def _clear_saved_state(self):
        """Limpa o estado salvo da impressão"""
        try:
            # Limpa variáveis na memória
            self._print_state_saved = False
            self._saved_print_file = None
            self._saved_print_position = None
            self._saved_print_progress = 0
            self._saved_file_position = 0
            self._saved_line_number = 0
            self._saved_coordinates = {'x': 0, 'y': 0, 'z': 0, 'e': 0}
            self._saved_extruder_temp = 0
            self._saved_bed_temp = 0
            
            # Remove arquivo de estado
            state_file = os.path.join(self.get_plugin_data_folder(), 'print_state.json')
            if os.path.exists(state_file):
                os.remove(state_file)
                self._logger.info("Arquivo de estado removido.")
            
            self._logger.info("Estado de recuperação limpo.")
            
        except Exception as e:
            self._logger.error(f"Erro ao limpar estado salvo: {e}")


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
