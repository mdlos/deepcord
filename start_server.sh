#!/bin/bash

echo "========================================"
echo "  SISTEMA DE CHAT - SERVIDOR PYTHON"
echo "========================================"
echo

# Cores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configurações (mesmas do sistema anterior)
PORT=${1:-8081}
DB_HOST=${2:-172.18.0.2}
DB_USER=${3:-redes2}
DB_PASS=${4:-r3d3s321}
DB_NAME=${5:-chat_system}

# Verificar Python
echo -e "${YELLOW}Verificando Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 não encontrado${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python3 encontrado${NC}"

# Verificar dependências
echo -e "${YELLOW}Verificando dependências...${NC}"
if ! python3 -c "import aiohttp" &> /dev/null; then
    echo -e "${YELLOW}Instalando dependências...${NC}"
    pip3 install -r server/requirements.txt
fi

# Verificar MySQL
echo -e "${YELLOW}Verificando MySQL...${NC}"
if docker ps | grep -q mysql-server; then
    echo -e "${GREEN}✅ MySQL Docker rodando${NC}"
    MYSQL_IP=$(docker inspect mysql-server | grep IPAddress | tail -1 | grep -oP '\d+\.\d+\.\d+\.\d+')
    echo -e "${GREEN}✅ MySQL IP: $MYSQL_IP${NC}"
else
    echo -e "${YELLOW}⚠️ Iniciando MySQL...${NC}"
    docker start mysql-server
    sleep 3
    MYSQL_IP=$(docker inspect mysql-server | grep IPAddress | tail -1 | grep -oP '\d+\.\d+\.\d+\.\d+')
fi

# Obter IP do servidor
SERVER_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v 127.0.0.1 | head -n1)
[ -z "$SERVER_IP" ] && SERVER_IP="localhost"

echo
echo "========================================"
echo -e "${GREEN}✅ SERVIDOR INICIADO${NC}"
echo "========================================"
echo -e "📡 ${YELLOW}Acesso local:${NC} http://localhost:$PORT"
echo -e "📡 ${YELLOW}Acesso rede:${NC} http://$SERVER_IP:$PORT"
echo -e "🛢️  ${YELLOW}MySQL:${NC} $DB_USER@$DB_HOST/$DB_NAME"
echo -e "👤 ${YELLOW}Admin:${NC} admin / admin123"
echo "========================================"
echo -e "\n${GREEN}Para acessar de QUALQUER computador na rede:${NC}"
echo -e "  ${YELLOW}http://$SERVER_IP:$PORT${NC}"
echo ""

cd server
python3 server.py -p $PORT --host 0.0.0.0 --db-host $DB_HOST -u $DB_USER -P $DB_PASS -d $DB_NAME
