#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebSocketHandler:
    def __init__(self, database):
        self.db = database
        self.clients = {}
        self.user_sockets = {}
        
    async def handle_connection(self, websocket, query_string):
        """Gerencia conexão WebSocket simplificada"""
        logger.info("=== NOVA CONEXÃO WEBSOCKET ===")
        
        # Extrair username
        username = None
        if query_string:
            for param in query_string.split('&'):
                if param.startswith('username='):
                    username = param.split('=')[1]
                    break
        
        logger.info(f"Username: {username}")
        
        if not username:
            logger.warning("Username não fornecido")
            await websocket.close(1008, "Username não fornecido")
            return
        
        # Registrar cliente
        self.user_sockets[username] = websocket
        logger.info(f"Usuário {username} conectado")
        
        try:
            # Enviar mensagem de boas-vindas
            await websocket.send(json.dumps({
                "type": "system",
                "content": f"Bem-vindo {username}!"
            }))
            
            # Manter conexão
            while True:
                try:
                    message = await websocket.receive()
                    if message.type == 1:  # Text message
                        text = message.data
                        logger.info(f"Mensagem de {username}: {text[:50]}...")
                        
                        try:
                            data = json.loads(text)
                            if data.get("type") == "message":
                                await self.broadcast_message(username, data.get("content", ""))
                            elif data.get("type") == "private":
                                await self.send_private_message(username, data.get("to", ""), data.get("content", ""))
                            elif data.get("type") == "heartbeat":
                                pass
                        except json.JSONDecodeError:
                            await self.broadcast_message(username, text)
                    elif message.type == 2:  # Binary
                        pass
                    elif message.type == 8:  # Close
                        logger.info(f"Cliente {username} fechou conexão")
                        break
                except Exception as e:
                    logger.error(f"Erro recebendo mensagem: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"Erro na conexão de {username}: {e}")
        finally:
            logger.info(f"Usuário {username} desconectado")
            self.user_sockets.pop(username, None)
    
    async def broadcast_message(self, username, content):
        """Envia mensagem para todos"""
        msg = {
            "type": "message",
            "from": username,
            "content": content,
            "timestamp": "Agora"
        }
        
        data = json.dumps(msg)
        disconnected = []
        
        for user, ws in self.user_sockets.items():
            try:
                await ws.send(data)
            except:
                disconnected.append(user)
        
        for user in disconnected:
            self.user_sockets.pop(user, None)
    
    async def send_private_message(self, from_user, to_user, content):
        """Envia mensagem privada"""
        if to_user not in self.user_sockets:
            return
        
        msg = {
            "type": "private",
            "from": from_user,
            "to": to_user,
            "content": content
        }
        
        try:
            await self.user_sockets[to_user].send(json.dumps(msg))
        except:
            pass
