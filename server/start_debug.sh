#!/bin/bash

echo "========================================"
echo "  INICIANDO CHAT COM DEBUG"
echo "========================================"
echo

# Verificar Ollama
echo "🔍 Verificando Ollama..."
if curl -s http://localhost:11434/api/tags > /dev/null; then
    echo "✅ Ollama disponível"
    ollama list
else
    echo "❌ Ollama não disponível"
    echo "Inicie com: ollama serve"
    exit 1
fi

echo ""
echo "🚀 Iniciando servidor..."
cd ~/Documents/UESB/RCII/chat-system2/server
python3 server_fixed.py
