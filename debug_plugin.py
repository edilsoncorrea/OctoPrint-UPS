#!/usr/bin/env python3
# Script para debug do plugin UPS

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
    
    # Verifica se as novas configurações estão presentes
    required_settings = ['shutdown_temp_threshold', 'block_resume_on_battery']
    for setting in required_settings:
        if setting in defaults:
            print(f"✅ {setting}: OK")
        else:
            print(f"❌ {setting}: FALTANDO")
    
    print("\n✅ Teste concluído com sucesso!")
    
except ImportError as e:
    print(f"❌ Erro ao importar plugin: {e}")
except Exception as e:
    print(f"❌ Erro durante teste: {e}")
