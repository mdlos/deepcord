#!/bin/bash

echo "========================================"
echo "  INICIANDO SERVIDOR CHAT"
echo "========================================"
echo

# Verificar dependências
echo "Verificando dependências..."
pip3 install --user aiohttp mysql-connector-python 2>/dev/null

# Obter IP
IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v 127.0.0.1 | head -n1)
[ -z "$IP" ] && IP="localhost"

echo
echo "========================================"
echo "  SERVIDOR INICIADO"
echo "========================================"
echo "📍 Local: http://localhost:8081"
echo "🌐 Rede:  http://$IP:8081"
echo "👤 Admin: admin / admin123"
echo "========================================"
echo

python3 server.py -p 8081 --host 0.0.0.0 --db-host 172.18.0.2 -u redes2 -P r3d3s321 -d chat_system
