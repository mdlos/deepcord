#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file server.py
@brief Servidor HTTP + WebSocket para o chat
"""

import asyncio
import json
import logging
import os
import sys
import argparse
from pathlib import Path
import socket

from aiohttp import web
from aiohttp.web import FileResponse

from database import Database
from websocket_handler import WebSocketHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_local_ip():
    """Obtém o IP local da máquina"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


class ChatServer:
    """Servidor de chat HTTP + WebSocket"""
    
    def __init__(self, host="0.0.0.0", port=8081, db_host="172.18.0.2",
                 db_user="redes2", db_password="r3d3s321", db_name="chat_system"):
        self.host = host
        self.port = port
        self.db_host = db_host
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        self.local_ip = get_local_ip()
        
        # Inicializar banco de dados
        self.db = Database(
            host=db_host,
            user=db_user,
            password=db_password,
            database=db_name
        )
        
        if not self.db.connect():
            logger.error("Falha ao conectar ao MySQL")
            sys.exit(1)
        
        self.ws_handler = WebSocketHandler(self.db)
        self.app = web.Application()
        self.setup_routes()
    
    def setup_routes(self):
        """Configura as rotas HTTP"""
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_post('/api/login', self.handle_login)
        self.app.router.add_post('/api/register', self.handle_register)
        self.app.router.add_post('/api/recovery-request', self.handle_recovery_request)
        self.app.router.add_post('/api/recovery-verify', self.handle_recovery_verify)
        self.app.router.add_post('/api/auto-login', self.handle_auto_login)
        self.app.router.add_get('/ws', self.handle_websocket)
        self.app.router.add_get('/{path:.*}', self.handle_static)
    
    async def handle_status(self, request):
        """Endpoint de status"""
        data = {
            "status": "online",
            "port": self.port,
            "server_ip": self.local_ip,
            "server_host": self.host,
            "uptime": "00:00:00",
            "clients": len(self.ws_handler.user_sockets),
            "available_ports": [8081, 8080, 3000, 5000, 8000],
            "db_host": self.db_host,
            "db_name": self.db_name
        }
        return web.json_response(data)
    
    async def handle_login(self, request):
        """Endpoint de login"""
        try:
            form = await request.post()
            username = form.get('username', '')
            password = form.get('password', '')
            remember = form.get('remember', 'false') == 'true'
            
            if self.db.authenticate_user(username, password):
                token = self.db.generate_auto_login_token(username) if remember else ""
                self.db.update_user_status(username, True, request.remote)
                self.db.log_security_event(username, "login_success", request.remote)
                
                return web.json_response({
                    "success": True,
                    "message": "Login realizado",
                    "username": username,
                    "token": token,
                    "server_ip": self.local_ip,
                    "port": self.port
                })
            else:
                self.db.log_security_event(username, "login_failed", request.remote)
                return web.json_response({
                    "success": False,
                    "message": "Credenciais inválidas"
                })
        except Exception as e:
            logger.error(f"Erro no login: {e}")
            return web.json_response({
                "success": False,
                "message": "Erro interno"
            })
    
    async def handle_register(self, request):
        """Endpoint de registro"""
        try:
            form = await request.post()
            username = form.get('username', '')
            password = form.get('password', '')
            email = form.get('email', '')
            
            if len(username) < 3:
                return web.json_response({
                    "success": False,
                    "message": "Usuário mínimo 3 caracteres"
                })
            
            if len(password) < 6:
                return web.json_response({
                    "success": False,
                    "message": "Senha mínimo 6 caracteres"
                })
            
            if self.db.register_user(username, password, email):
                self.db.log_security_event(username, "register", request.remote)
                return web.json_response({
                    "success": True,
                    "message": "Usuário registrado com sucesso"
                })
            else:
                return web.json_response({
                    "success": False,
                    "message": "Nome de usuário já existe"
                })
        except Exception as e:
            logger.error(f"Erro no registro: {e}")
            return web.json_response({
                "success": False,
                "message": "Erro interno"
            })
    
    async def handle_recovery_request(self, request):
        """Endpoint de solicitação de recuperação"""
        try:
            form = await request.post()
            email = form.get('email', '')
            
            if not self.db.user_exists_by_email(email):
                return web.json_response({
                    "success": False,
                    "message": "Email não encontrado"
                })
            
            import random
            code = ''.join(str(random.randint(0, 9)) for _ in range(6))
            
            if self.db.create_recovery_code(email, code):
                logger.info(f"Código de recuperação para {email}: {code}")
                return web.json_response({
                    "success": True,
                    "message": "Código enviado para seu email",
                    "email": email
                })
            else:
                return web.json_response({
                    "success": False,
                    "message": "Erro ao gerar código"
                })
        except Exception as e:
            logger.error(f"Erro na recuperação: {e}")
            return web.json_response({
                "success": False,
                "message": "Erro interno"
            })
    
    async def handle_recovery_verify(self, request):
        """Endpoint de verificação de recuperação"""
        try:
            form = await request.post()
            email = form.get('email', '')
            code = form.get('code', '')
            new_password = form.get('new_password', '')
            
            if len(new_password) < 6:
                return web.json_response({
                    "success": False,
                    "message": "Senha deve ter pelo menos 6 caracteres"
                })
            
            if self.db.verify_recovery_code(email, code):
                if self.db.update_password(email, new_password):
                    return web.json_response({
                        "success": True,
                        "message": "Senha redefinida com sucesso"
                    })
                else:
                    return web.json_response({
                        "success": False,
                        "message": "Erro ao atualizar senha"
                    })
            else:
                return web.json_response({
                    "success": False,
                    "message": "Código inválido ou expirado"
                })
        except Exception as e:
            logger.error(f"Erro na verificação: {e}")
            return web.json_response({
                "success": False,
                "message": "Erro interno"
            })
    
    async def handle_auto_login(self, request):
        """Endpoint de auto-login"""
        try:
            form = await request.post()
            username = form.get('username', '')
            token = form.get('token', '')
            
            if self.db.verify_auto_login_token(username, token):
                self.db.update_user_status(username, True, request.remote)
                return web.json_response({
                    "success": True,
                    "message": "Auto-login realizado",
                    "username": username
                })
            else:
                return web.json_response({
                    "success": False,
                    "message": "Token inválido ou expirado"
                })
        except Exception as e:
            logger.error(f"Erro no auto-login: {e}")
            return web.json_response({
                "success": False,
                "message": "Erro interno"
            })
    
    async def handle_websocket(self, request):
        """Endpoint WebSocket"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await self.ws_handler.handle_connection(ws, request.query_string)
        return ws
    
    async def handle_static(self, request):
        """Serve arquivos estáticos"""
        path = request.match_info.get('path', '')
        
        if not path or path == '/':
            path = 'index.html'
        
        static_path = Path('public') / path
        
        if not static_path.exists():
            if path == 'login' or path == 'chat':
                static_path = Path('public') / f'{path}.html'
        
        if static_path.exists():
            return FileResponse(static_path)
        
        return web.Response(status=404, text="404 - Página não encontrada")
    
    async def run(self):
        """Inicia o servidor"""
        print("\n" + "="*50)
        print("  SISTEMA DE CHAT - SERVIDOR PYTHON")
        print("="*50)
        print(f"📡 Servidor HTTP/WS: http://{self.local_ip}:{self.port}")
        print(f"🛢️  MySQL: {self.db_user}@{self.db_host}/{self.db_name}")
        print(f"👤 Admin: admin / admin123")
        print("="*50)
        print(f"\nPara acessar de qualquer computador na rede:")
        print(f"  http://{self.local_ip}:{self.port}")
        print(f"\nPressione Ctrl+C para parar\n")
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Desligando servidor...")
        finally:
            self.db.disconnect()


def main():
    parser = argparse.ArgumentParser(description='Servidor de Chat')
    parser.add_argument('-p', '--port', type=int, default=8081, help='Porta do servidor')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host do servidor')
    parser.add_argument('--db-host', type=str, default='172.18.0.2', help='Host do MySQL')
    parser.add_argument('-u', '--db-user', type=str, default='redes2', help='Usuário do MySQL')
    parser.add_argument('-P', '--db-password', type=str, default='r3d3s321', help='Senha do MySQL')
    parser.add_argument('-d', '--db-name', type=str, default='chat_system', help='Banco de dados')
    
    args = parser.parse_args()
    
    server = ChatServer(
        host=args.host,
        port=args.port,
        db_host=args.db_host,
        db_user=args.db_user,
        db_password=args.db_password,
        db_name=args.db_name
    )
    
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Servidor finalizado")


if __name__ == "__main__":
    main()
