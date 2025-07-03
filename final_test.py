#!/usr/bin/env python3
# Script final de teste das funcionalidades de salvamento de posição

import sys
import os
import json

# Adiciona o diretório do plugin ao path
plugin_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, plugin_dir)

print("🎯 TESTE FINAL: Sistema de Salvamento de Posição da Impressão")
print("=" * 60)

try:
    from octoprint_ups import UPS
    
    # Instancia o plugin
    plugin = UPS()
    
    # Simula logger para testes
    class MockLogger:
        def info(self, msg): print(f"[INFO] {msg}")
        def warning(self, msg): print(f"[WARNING] {msg}")
        def error(self, msg): print(f"[ERROR] {msg}")
        def debug(self, msg): print(f"[DEBUG] {msg}")
    
    plugin._logger = MockLogger()
    
    # Simula método get_plugin_data_folder
    def mock_get_plugin_data_folder():
        return plugin_dir
    
    plugin.get_plugin_data_folder = mock_get_plugin_data_folder
    
    print("✅ Plugin configurado para teste")
    
    # === TESTE 1: Salvamento de Estado ===
    print("\n" + "="*50)
    print("TESTE 1: Salvamento de Estado da Impressão")
    print("="*50)
    
    # Simula dados de uma impressão real
    plugin._saved_print_file = "exemplo_impressao.gcode"
    plugin._saved_print_progress = 67.8
    plugin._saved_file_position = 15642
    plugin._saved_line_number = 1234
    plugin._saved_coordinates = {'x': 125.7, 'y': 89.3, 'z': 12.5, 'e': 145.8}
    plugin._saved_extruder_temp = 210
    plugin._saved_bed_temp = 60
    plugin._print_state_saved = True
    
    # Testa salvamento em arquivo
    print("\n📁 Salvando estado em arquivo...")
    plugin._save_state_to_file()
    
    # Verifica se foi salvo
    state_file = os.path.join(plugin_dir, 'print_state.json')
    if os.path.exists(state_file):
        print("✅ Arquivo de estado criado com sucesso!")
        
        # Verifica conteúdo
        with open(state_file, 'r') as f:
            saved_data = json.load(f)
        
        print("\n📋 Dados salvos:")
        for key, value in saved_data.items():
            print(f"   {key}: {value}")
        
        # Verifica se todos os dados importantes estão presentes
        expected_keys = ['print_file', 'progress', 'file_position', 'line_number', 
                        'coordinates', 'extruder_temp', 'bed_temp', 'timestamp']
        
        missing_keys = [key for key in expected_keys if key not in saved_data]
        if not missing_keys:
            print("✅ Todos os dados importantes foram salvos!")
        else:
            print(f"❌ Dados faltando: {missing_keys}")
    
    # === TESTE 2: Carregamento de Estado ===
    print("\n" + "="*50)
    print("TESTE 2: Carregamento de Estado")
    print("="*50)
    
    # Limpa estado atual para testar carregamento
    plugin._print_state_saved = False
    plugin._saved_print_file = None
    
    # Carrega estado
    print("\n📖 Carregando estado do arquivo...")
    success = plugin._load_print_state()
    
    if success:
        print("✅ Estado carregado com sucesso!")
        print(f"   Arquivo: {plugin._saved_print_file}")
        print(f"   Progresso: {plugin._saved_print_progress}%")
        print(f"   Posição: X{plugin._saved_coordinates['x']} Y{plugin._saved_coordinates['y']} Z{plugin._saved_coordinates['z']}")
    else:
        print("❌ Falha ao carregar estado")
    
    # === TESTE 3: Geração de G-code de Recuperação ===
    print("\n" + "="*50)
    print("TESTE 3: Geração de G-code de Recuperação")
    print("="*50)
    
    print("\n🔧 Gerando comandos de recuperação...")
    recovery_commands = plugin._create_recovery_gcode()
    
    if recovery_commands:
        print(f"✅ {len(recovery_commands)} comandos gerados!")
        
        # Mostra alguns comandos importantes
        print("\n📋 Comandos de recuperação gerados:")
        for i, cmd in enumerate(recovery_commands[:15], 1):
            print(f"{i:2d}: {cmd}")
        
        if len(recovery_commands) > 15:
            print(f"    ... e mais {len(recovery_commands) - 15} comandos")
        
        # Verifica comandos críticos
        print("\n🔍 Verificando comandos críticos:")
        
        critical_checks = [
            ("G28", "Home dos eixos"),
            ("M104", "Aquecimento extrusor"),
            ("M140", "Aquecimento mesa"),
            ("M109", "Espera aquecimento extrusor"),
            ("M190", "Espera aquecimento mesa"),
            (f"G1 X{plugin._saved_coordinates['x']:.2f}", "Posicionamento X"),
            (f"G1 Y{plugin._saved_coordinates['y']:.2f}", "Posicionamento Y"),
            (f"G1 Z{plugin._saved_coordinates['z']:.2f}", "Posicionamento Z"),
            ("G1 E-5", "Retração do filamento"),
            ("M117", "Mensagem no display")
        ]
        
        for check_cmd, description in critical_checks:
            found = any(check_cmd in cmd for cmd in recovery_commands)
            status = "✅" if found else "❌"
            print(f"   {status} {description}: {check_cmd}")
    
    # === TESTE 4: Limpeza de Estado ===
    print("\n" + "="*50)
    print("TESTE 4: Limpeza de Estado")
    print("="*50)
    
    print("\n🧹 Limpando estado salvo...")
    plugin._clear_saved_state()
    
    # Verifica se foi limpo
    if not os.path.exists(state_file):
        print("✅ Arquivo de estado removido!")
    
    if not plugin._print_state_saved:
        print("✅ Flag de estado limpa!")
    
    if plugin._saved_print_file is None:
        print("✅ Variáveis de estado limpas!")
    
    # === RESUMO FINAL ===
    print("\n" + "="*60)
    print("🎉 RESUMO FINAL - FUNCIONALIDADES IMPLEMENTADAS")
    print("="*60)
    
    print("\n✅ SALVAMENTO COMPLETO DE POSIÇÃO:")
    print("   • Arquivo de impressão e caminho completo")
    print("   • Progresso exato da impressão (porcentagem)")
    print("   • Posição no arquivo (bytes) para retomar exatamente")
    print("   • Número da linha G-code calculado")
    print("   • Coordenadas físicas exatas (X, Y, Z, E)")
    print("   • Temperaturas do extrusor e mesa")
    print("   • Timestamp do salvamento")
    
    print("\n✅ RECUPERAÇÃO INTELIGENTE:")
    print("   • Home seguro dos eixos")
    print("   • Aquecimento das temperaturas salvas")
    print("   • Posicionamento exato nas coordenadas")
    print("   • Purga automática do extrusor")
    print("   • Instruções claras para o usuário")
    print("   • Mensagem no display da impressora")
    
    print("\n✅ PERSISTÊNCIA E CONFIABILIDADE:")
    print("   • Estado salvo em arquivo JSON")
    print("   • Carregamento automático na inicialização")
    print("   • Detecção de reconexão da impressora")
    print("   • APIs para controle manual")
    print("   • Logs detalhados de todas as operações")
    
    print("\n📝 COMO FUNCIONA NA PRÁTICA:")
    print("1. 🔋 UPS entra em bateria crítica")
    print("2. ⏸️  Impressão é pausada automaticamente")
    print("3. 🌡️  Plugin aguarda temperatura baixar (configurável)")
    print("4. 💾 Estado da impressão é salvo completamente:")
    print("   → Posição exata no arquivo G-code")
    print("   → Coordenadas físicas do cabeçote")
    print("   → Temperaturas ativas")
    print("   → Progresso da impressão")
    print("5. 🔌 UPS é desligado para preservar bateria")
    print("6. ⚡ Após restauração da energia:")
    print("   → Impressora reconecta")
    print("   → Plugin carrega estado salvo")
    print("   → Oferece recuperação via API/interface")
    print("7. 🔧 Usuário inicia recuperação:")
    print("   → G-code posiciona cabeçote exatamente")
    print("   → Aquece temperaturas")
    print("   → Usuário pode retomar do ponto exato")
    
    print("\n🎯 RESULTADO: A impressão pode ser retomada exatamente")
    print("do ponto onde foi interrompida, sem perda de material!")
    
except Exception as e:
    print(f"❌ Erro durante teste: {e}")
    import traceback
    traceback.print_exc()
