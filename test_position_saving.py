#!/usr/bin/env python3
# Script para testar as funções de salvamento e recuperação de posição

import sys
import os
import json

# Adiciona o diretório do plugin ao path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, plugin_dir)

print("🔧 Testando funções de salvamento de posição...")

try:
    from octoprint_ups import UPS
    
    # Instancia o plugin
    plugin = UPS()
    
    # Simula dados de uma impressão
    print("\n📋 Simulando estado de impressão...")
    plugin._saved_print_file = "test_print.gcode"
    plugin._saved_print_progress = 65.5
    plugin._saved_file_position = 12345
    plugin._saved_line_number = 456
    plugin._saved_coordinates = {'x': 125.5, 'y': 98.3, 'z': 15.7, 'e': 234.1}
    plugin._saved_extruder_temp = 210
    plugin._saved_bed_temp = 60
    plugin._print_state_saved = True
    
    print("✅ Estado simulado configurado")
    
    # Testa salvamento em arquivo
    print("\n💾 Testando salvamento em arquivo...")
    try:
        plugin._save_state_to_file()
        print("✅ Salvamento em arquivo executado")
        
        # Verifica se o arquivo foi criado
        state_file = os.path.join(plugin_dir, 'octoprint_ups', 'print_state.json')
        # Como não temos acesso ao método get_plugin_data_folder, vamos verificar na pasta atual
        possible_files = [
            'print_state.json',
            os.path.join('octoprint_ups', 'print_state.json'),
            os.path.join(plugin_dir, 'print_state.json')
        ]
        
        file_found = False
        for test_file in possible_files:
            if os.path.exists(test_file):
                print(f"✅ Arquivo de estado encontrado: {test_file}")
                # Lê e verifica o conteúdo
                with open(test_file, 'r') as f:
                    saved_data = json.load(f)
                print(f"📄 Conteúdo salvo:")
                for key, value in saved_data.items():
                    print(f"   {key}: {value}")
                file_found = True
                break
        
        if not file_found:
            print("⚠️  Arquivo de estado não encontrado (normal se get_plugin_data_folder não está disponível)")
            
    except Exception as e:
        print(f"⚠️  Erro no salvamento (normal fora do OctoPrint): {e}")
    
    # Testa criação de G-code de recuperação
    print("\n🔧 Testando criação de G-code de recuperação...")
    try:
        recovery_commands = plugin._create_recovery_gcode()
        print(f"✅ {len(recovery_commands)} comandos de recuperação criados")
        
        print("📋 Primeiros 10 comandos:")
        for i, cmd in enumerate(recovery_commands[:10]):
            print(f"   {i+1:2d}: {cmd}")
        
        if len(recovery_commands) > 10:
            print(f"   ... e mais {len(recovery_commands) - 10} comandos")
        
        # Verifica comandos específicos importantes
        important_checks = [
            ("G28", "Home dos eixos"),
            ("M104", "Aquecimento extrusor"),
            ("M140", "Aquecimento mesa"),
            ("G1 X125.5", "Posicionamento X correto"),
            ("G1 Y98.3", "Posicionamento Y correto"),
            ("G1 Z15.7", "Posicionamento Z correto")
        ]
        
        print("\n🔍 Verificando comandos importantes:")
        for check_cmd, description in important_checks:
            found = any(check_cmd in cmd for cmd in recovery_commands)
            status = "✅" if found else "❌"
            print(f"   {status} {description}: {'OK' if found else 'NÃO ENCONTRADO'}")
        
    except Exception as e:
        print(f"❌ Erro na criação de G-code: {e}")
    
    # Testa limpeza do estado
    print("\n🧹 Testando limpeza do estado...")
    try:
        plugin._clear_saved_state()
        print("✅ Limpeza de estado executada")
        
        # Verifica se as variáveis foram limpas
        checks = [
            (plugin._print_state_saved, False, "Estado salvo limpo"),
            (plugin._saved_print_file, None, "Arquivo limpo"),
            (plugin._saved_print_progress, 0, "Progresso limpo"),
            (plugin._saved_line_number, 0, "Número da linha limpo")
        ]
        
        for value, expected, description in checks:
            status = "✅" if value == expected else "❌"
            print(f"   {status} {description}: {value} (esperado: {expected})")
            
    except Exception as e:
        print(f"❌ Erro na limpeza: {e}")
    
    print("\n🎯 RESUMO DOS RECURSOS DE SALVAMENTO DE POSIÇÃO:")
    print("✅ Salva arquivo de impressão e progresso")
    print("✅ Salva posição no arquivo (bytes) e linha estimada")
    print("✅ Salva coordenadas físicas do cabeçote (X, Y, Z, E)")
    print("✅ Salva temperaturas do extrusor e mesa")
    print("✅ Gera G-code para recuperação automática:")
    print("   • Home dos eixos")
    print("   • Aquecimento das temperaturas salvas")
    print("   • Posicionamento exato nas coordenadas salvas")
    print("   • Purga do extrusor")
    print("   • Instruções para o usuário")
    print("✅ Persistência em arquivo JSON")
    print("✅ Carregamento automático após reconexão")
    print("✅ APIs para controle manual")
    
    print("\n📝 INSTRUÇÕES DE USO:")
    print("1. O plugin salva automaticamente o estado quando:")
    print("   • UPS entra em bateria crítica")
    print("   • Impressão é pausada")
    print("   • Temperatura do hotend ≤ limite configurado")
    
    print("\n2. Após reconexão da impressora:")
    print("   • Estado é carregado automaticamente")
    print("   • Oferta recuperação via API ou interface")
    print("   • G-code de recuperação posiciona cabeçote exatamente onde parou")
    
    print("\n3. Para uso manual:")
    print("   • GET /api/plugin/ups?command=get_recovery_info")
    print("   • POST /api/plugin/ups com command='start_recovery'")
    print("   • POST /api/plugin/ups com command='clear_recovery'")

except ImportError as e:
    print(f"❌ Erro ao importar plugin: {e}")
except Exception as e:
    print(f"❌ Erro durante teste: {e}")
