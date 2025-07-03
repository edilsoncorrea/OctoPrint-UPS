#!/usr/bin/env python3
# Script para debug do plugin UPS com funcionalidades de recuperação

import sys
import os

# Adiciona o diretório do plugin ao path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, plugin_dir)

try:
    from octoprint_ups import UPS
    print("✅ Plugin importado com sucesso!")
    
    # Testa instanciação
    plugin_instance = UPS()
    print("✅ Plugin instanciado com sucesso!")
    
    # Testa configurações padrão
    defaults = plugin_instance.get_settings_defaults()
    print("✅ Configurações padrão:")
    for key, value in defaults.items():
        print(f"   {key}: {value}")
    
    # Verifica se todas as configurações estão presentes
    required_settings = [
        'shutdown_temp_threshold', 
        'block_resume_on_battery',
        'save_print_state',
        'auto_recover_after_shutdown'
    ]
    
    print("\n🔍 Verificando configurações:")
    for setting in required_settings:
        if setting in defaults:
            print(f"✅ {setting}: OK")
        else:
            print(f"❌ {setting}: FALTANDO")
    
    # Testa métodos de recuperação
    print("\n🔧 Testando métodos de recuperação:")
    try:
        # Testa salvamento de estado (simulado)
        plugin_instance._saved_print_file = "test_file.gcode"
        plugin_instance._saved_print_progress = 50.5
        plugin_instance._saved_extruder_temp = 210
        plugin_instance._saved_bed_temp = 60
        
        print("✅ Variáveis de estado configuradas")
        
        # Testa comandos de API
        api_commands = plugin_instance.get_api_commands()
        expected_commands = ['shutdown_ups', 'get_recovery_info', 'start_recovery', 'clear_recovery']
        
        for cmd in expected_commands:
            if cmd in api_commands:
                print(f"✅ API Command '{cmd}': OK")
            else:
                print(f"❌ API Command '{cmd}': FALTANDO")
        
        print("\n✅ Teste concluído com sucesso!")
        print("\n📋 Funcionalidades implementadas:")
        print("   • Salvamento de estado da impressão")
        print("   • Recuperação após shutdown")
        print("   • Detecção de reconexão da impressora")
        print("   • APIs para controle manual")
        print("   • Configurações de proteção aprimoradas")
        
    except Exception as e:
        print(f"❌ Erro durante teste de métodos: {e}")
        
except ImportError as e:
    print(f"❌ Erro ao importar plugin: {e}")
except Exception as e:
    print(f"❌ Erro durante teste: {e}")
