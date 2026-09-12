#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import base64
import os
import uuid
import hashlib
import secrets
import aiohttp  # <-- IMPORTANTE: Esta importação estava faltando!
from datetime import datetime, timedelta
from aiohttp import web, WSMsgType
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ChatServer:
    def __init__(self):
        self.clients = {}
        self.users = {}
        self.sessions = {}
        self.rooms = {}  # room_name -> {'members': set(), 'owner': str, 'created_at': datetime}
        self.room_messages = {}
        self.message_ids = {}
        self.file_messages = {}
        self.ollama_host = "http://localhost:11434"
        self.ollama_model = "phi3"
        self.ai_username = "🤖 Assistente IA"
        self.ollama_available = False
        self.app = web.Application()
        self.setup_routes()
        os.makedirs('uploads', exist_ok=True)
        
        # Criar sala geral e admin
        self.create_default_admin()
        self.create_default_rooms()
    
    def create_default_admin(self):
        admin_password = hashlib.sha256("admin123".encode()).hexdigest()
        self.users['admin'] = {
            'password': admin_password,
            'is_admin': True,
            'email': 'admin@chat.com',
            'created_at': datetime.now().isoformat()
        }
        logger.info("✅ Usuário admin criado (senha: admin123)")
    
    def create_default_rooms(self):
        """Cria salas padrão"""
        self.rooms['geral'] = {
            'members': set(),
            'owner': 'admin',
            'created_at': datetime.now().isoformat()
        }
        self.room_messages['geral'] = []
        logger.info("✅ Sala geral criada")
    
    def setup_routes(self):
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/login', self.handle_login)
        self.app.router.add_get('/chat', self.handle_chat)
        self.app.router.add_get('/admin', self.handle_admin)
        self.app.router.add_get('/admin/login', self.handle_admin_login_page)
        self.app.router.add_post('/admin/api/login', self.handle_admin_api_login)
        self.app.router.add_post('/admin/api/logout', self.handle_admin_api_logout)
        self.app.router.add_get('/admin/api/verify', self.handle_admin_api_verify)
        self.app.router.add_get('/ws', self.handle_websocket)
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/api/users', self.handle_get_users)
        self.app.router.add_get('/api/rooms', self.handle_get_rooms)
        self.app.router.add_post('/api/admin/rooms', self.handle_admin_rooms)
        self.app.router.add_post('/api/admin/rooms/delete', self.handle_admin_delete_room)
        self.app.router.add_get('/api/ollama/models', self.handle_ollama_models)
        self.app.router.add_get('/uploads/{filename}', self.handle_upload)
        self.app.router.add_post('/api/login', self.handle_login_api)
        self.app.router.add_post('/api/register', self.handle_register)
        self.app.router.add_post('/api/admin/users', self.handle_admin_users)
        self.app.router.add_post('/api/admin/password', self.handle_admin_password)
        self.app.router.add_post('/api/admin/delete', self.handle_admin_delete)
        self.app.router.add_post('/api/reset-password', self.handle_reset_password)
        self.app.router.add_get('/{path}', self.handle_static)
    
    async def check_ollama(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_host}/api/tags", timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = data.get('models', [])
                        if models:
                            available_models = [m.get('name') for m in models]
                            if self.ollama_model not in available_models:
                                self.ollama_model = available_models[0] if available_models else self.ollama_model
                            self.ollama_available = True
                            logger.info(f"✅ Ollama disponível. Modelo: {self.ollama_model}")
                        else:
                            logger.warning("⚠️ Ollama disponível, mas nenhum modelo encontrado")
                    else:
                        logger.warning(f"⚠️ Ollama não está respondendo (status: {resp.status})")
        except Exception as e:
            logger.warning(f"⚠️ Ollama não disponível: {e}")
            self.ollama_available = False
    
    def is_admin(self, username):
        return username in self.users and self.users[username].get('is_admin', False)
    
    def get_session_user(self, request):
        token = request.cookies.get('admin_token', '')
        if token in self.sessions:
            return self.sessions[token]
        return None
    
    async def handle_admin_login_page(self, request):
        return web.FileResponse('public/admin_login.html')
    
    async def handle_admin_api_login(self, request):
        data = await request.post()
        username = data.get('username', '')
        password = data.get('password', '')
        
        if not username or not password:
            return web.json_response({'success': False, 'message': 'Credenciais inválidas'}, status=401)
        
        if username not in self.users:
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'}, status=401)
        
        if not self.users[username].get('is_admin', False):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if self.users[username]['password'] != password_hash:
            return web.json_response({'success': False, 'message': 'Senha incorreta'}, status=401)
        
        token = secrets.token_hex(32)
        self.sessions[token] = username
        
        response = web.json_response({'success': True, 'message': 'Login realizado', 'username': username})
        response.set_cookie('admin_token', token, max_age=3600, httponly=True, samesite='Lax')
        return response
    
    async def handle_admin_api_logout(self, request):
        token = request.cookies.get('admin_token', '')
        if token in self.sessions:
            del self.sessions[token]
        response = web.json_response({'success': True, 'message': 'Logout realizado'})
        response.del_cookie('admin_token')
        return response
    
    async def handle_admin_api_verify(self, request):
        username = self.get_session_user(request)
        if username and self.is_admin(username):
            return web.json_response({'authenticated': True, 'username': username})
        return web.json_response({'authenticated': False}, status=401)
    
    async def handle_admin(self, request):
        username = self.get_session_user(request)
        if not username or not self.is_admin(username):
            return web.Response(status=302, headers={'Location': '/admin/login'})
        return web.FileResponse('public/admin.html')
    
    # ============================================
    # ADMIN - SALAS
    # ============================================
    
    async def handle_get_rooms(self, request):
        """Retorna lista de todas as salas"""
        username = self.get_session_user(request)
        if not username or not self.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        
        rooms_list = []
        for room_name, room_data in self.rooms.items():
            rooms_list.append({
                'name': room_name,
                'owner': room_data.get('owner', ''),
                'member_count': len(room_data.get('members', set())),
                'members': list(room_data.get('members', set())),
                'created_at': room_data.get('created_at', ''),
                'message_count': len(self.room_messages.get(room_name, []))
            })
        return web.json_response({
            'success': True,
            'rooms': rooms_list
        })
    
    async def handle_admin_rooms(self, request):
        """Criar ou gerenciar salas"""
        username = self.get_session_user(request)
        if not username or not self.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        
        data = await request.post()
        action = data.get('action', '')
        room_name = data.get('name', '')
        
        if action == 'create':
            if not room_name or room_name in self.rooms:
                return web.json_response({
                    'success': False,
                    'message': 'Sala já existe ou nome inválido'
                })
            
            self.rooms[room_name] = {
                'members': set(),
                'owner': username,
                'created_at': datetime.now().isoformat()
            }
            self.room_messages[room_name] = []
            
            # Notificar todos
            await self.broadcast({
                'type': 'system',
                'content': f'🏠 Sala "{room_name}" criada pelo administrador {username}'
            })
            
            return web.json_response({
                'success': True,
                'message': f'Sala "{room_name}" criada com sucesso'
            })
        
        return web.json_response({
            'success': False,
            'message': 'Ação inválida'
        })
    
    async def handle_admin_delete_room(self, request):
        """Apagar sala"""
        username = self.get_session_user(request)
        if not username or not self.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        
        data = await request.post()
        room_name = data.get('name', '')
        
        if room_name not in self.rooms:
            return web.json_response({
                'success': False,
                'message': 'Sala não encontrada'
            })
        
        if room_name == 'geral':
            return web.json_response({
                'success': False,
                'message': 'Não é possível apagar a sala geral'
            })
        
        # Notificar membros
        for member in self.rooms[room_name].get('members', set()):
            if member in self.clients:
                await self.clients[member].send_json({
                    'type': 'system',
                    'content': f'🗑️ A sala "{room_name}" foi removida pelo administrador'
                })
        
        # Remover sala
        del self.rooms[room_name]
        if room_name in self.room_messages:
            del self.room_messages[room_name]
        
        await self.broadcast({
            'type': 'system',
            'content': f'🗑️ Sala "{room_name}" foi removida pelo administrador'
        })
        
        return web.json_response({
            'success': True,
            'message': f'Sala "{room_name}" removida com sucesso'
        })
    
    # ============================================
    # HANDLERS EXISTENTES (mantidos)
    # ============================================
    
    async def handle_ollama_models(self, request):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_host}/api/tags") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return web.json_response({
                            'success': True,
                            'models': [m.get('name') for m in data.get('models', [])],
                            'current': self.ollama_model,
                            'available': self.ollama_available
                        })
        except Exception as e:
            logger.error(f"Erro ao buscar modelos: {e}")
        
        return web.json_response({
            'success': False,
            'message': 'Ollama não disponível',
            'available': False
        })
    
    async def handle_index(self, request):
        return web.FileResponse('public/index.html')
    
    async def handle_login(self, request):
        return web.FileResponse('public/login.html')
    
    async def handle_chat(self, request):
        return web.FileResponse('public/chat.html')
    
    async def handle_upload(self, request):
        filename = request.match_info.get('filename', '')
        filepath = Path('uploads') / filename
        if filepath.exists():
            return web.FileResponse(filepath)
        return web.Response(status=404)
    
    async def handle_static(self, request):
        path = request.match_info.get('path', '')
        file_path = Path('public') / path
        if file_path.exists():
            return web.FileResponse(file_path)
        return web.Response(status=404)
    
    async def handle_status(self, request):
        return web.json_response({
            'status': 'online',
            'clients': len(self.clients),
            'rooms': list(self.rooms.keys()),
            'users': len(self.users),
            'ollama': {
                'available': self.ollama_available,
                'model': self.ollama_model
            }
        })
    
    async def handle_get_users(self, request):
        username = self.get_session_user(request)
        if not username or not self.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        
        users_list = []
        for uname, data in self.users.items():
            users_list.append({
                'username': uname,
                'is_admin': data.get('is_admin', False),
                'email': data.get('email', ''),
                'created_at': data.get('created_at', ''),
                'is_online': uname in self.clients
            })
        return web.json_response({'success': True, 'users': users_list})
    
    async def handle_login_api(self, request):
        data = await request.post()
        username = data.get('username', '')
        password = data.get('password', '')
        
        if not username or not password:
            return web.json_response({'success': False, 'message': 'Credenciais inválidas'})
        
        if username not in self.users:
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if self.users[username]['password'] != password_hash:
            return web.json_response({'success': False, 'message': 'Senha incorreta'})
        
        return web.json_response({
            'success': True,
            'message': 'Login realizado',
            'username': username,
            'is_admin': self.users[username].get('is_admin', False)
        })
    
    async def handle_register(self, request):
        data = await request.post()
        username = data.get('username', '')
        password = data.get('password', '')
        email = data.get('email', '')
        is_admin = data.get('is_admin', 'false') == 'true'
        
        if not username or not password:
            return web.json_response({'success': False, 'message': 'Usuário e senha são obrigatórios'})
        
        if len(username) < 3:
            return web.json_response({'success': False, 'message': 'Usuário mínimo 3 caracteres'})
        
        if len(password) < 6:
            return web.json_response({'success': False, 'message': 'Senha mínimo 6 caracteres'})
        
        if username in self.users:
            return web.json_response({'success': False, 'message': 'Usuário já existe'})
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        self.users[username] = {
            'password': password_hash,
            'is_admin': is_admin,
            'email': email,
            'created_at': datetime.now().isoformat()
        }
        
        return web.json_response({
            'success': True,
            'message': 'Usuário registrado com sucesso',
            'is_admin': is_admin
        })
    
    async def handle_admin_users(self, request):
        admin_user = self.get_session_user(request)
        if not admin_user or not self.is_admin(admin_user):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        
        data = await request.post()
        action = data.get('action', '')
        username = data.get('username', '')
        
        if action == 'list':
            users_list = []
            for uname, info in self.users.items():
                users_list.append({
                    'username': uname,
                    'is_admin': info.get('is_admin', False),
                    'email': info.get('email', ''),
                    'created_at': info.get('created_at', ''),
                    'is_online': uname in self.clients
                })
            return web.json_response({'success': True, 'users': users_list})
        
        elif action == 'create':
            password = data.get('password', '')
            email = data.get('email', '')
            is_admin = data.get('is_admin', 'false') == 'true'
            
            if not password or len(password) < 6:
                return web.json_response({'success': False, 'message': 'Senha mínimo 6 caracteres'})
            
            if username in self.users:
                return web.json_response({'success': False, 'message': 'Usuário já existe'})
            
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            self.users[username] = {
                'password': password_hash,
                'is_admin': is_admin,
                'email': email,
                'created_at': datetime.now().isoformat()
            }
            
            return web.json_response({'success': True, 'message': 'Usuário criado com sucesso'})
        
        return web.json_response({'success': False, 'message': 'Ação inválida'})
    
    async def handle_admin_password(self, request):
        admin_user = self.get_session_user(request)
        if not admin_user or not self.is_admin(admin_user):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        
        data = await request.post()
        username = data.get('username', '')
        new_password = data.get('new_password', '')
        
        if username not in self.users:
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        
        if len(new_password) < 6:
            return web.json_response({'success': False, 'message': 'Senha mínimo 6 caracteres'})
        
        password_hash = hashlib.sha256(new_password.encode()).hexdigest()
        self.users[username]['password'] = password_hash
        
        if username in self.clients:
            await self.clients[username].send_json({
                'type': 'system',
                'content': '🔐 Sua senha foi alterada pelo administrador.'
            })
        
        return web.json_response({
            'success': True,
            'message': f'Senha de {username} alterada com sucesso'
        })
    
    async def handle_admin_delete(self, request):
        admin_user = self.get_session_user(request)
        if not admin_user or not self.is_admin(admin_user):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        
        data = await request.post()
        username = data.get('username', '')
        
        if username not in self.users:
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        
        if username == admin_user or username == 'admin':
            return web.json_response({'success': False, 'message': 'Não é possível apagar este usuário'})
        
        del self.users[username]
        
        if username in self.clients:
            await self.clients[username].send_json({
                'type': 'system',
                'content': '🗑️ Sua conta foi removida pelo administrador.'
            })
            await self.clients[username].close()
        
        return web.json_response({
            'success': True,
            'message': f'Usuário {username} removido com sucesso'
        })
    
    async def handle_reset_password(self, request):
        data = await request.post()
        username = data.get('username', '')
        
        if username not in self.users:
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        
        admin_notified = False
        for admin_name, admin_data in self.users.items():
            if admin_data.get('is_admin', False) and admin_name in self.clients:
                await self.clients[admin_name].send_json({
                    'type': 'system',
                    'content': f'🔔 O usuário "{username}" solicitou alteração de senha.'
                })
                admin_notified = True
        
        if admin_notified:
            return web.json_response({
                'success': True,
                'message': 'Solicitação enviada para o administrador.'
            })
        else:
            return web.json_response({
                'success': False,
                'message': 'Nenhum administrador disponível no momento.'
            })
    
    async def call_ollama(self, prompt, system_prompt=""):
        if not self.ollama_available:
            return None
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_predict": 500
                    }
                }
                if system_prompt:
                    payload["system"] = system_prompt
                
                async with session.post(
                    f"{self.ollama_host}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('response', '').strip()
                    else:
                        return None
        except Exception as e:
            logger.error(f"❌ Erro ao chamar Ollama: {e}")
            return None
    
    async def handle_websocket(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        username = request.query.get('username', 'anonimo')
        logger.info(f"=== CONEXÃO: {username} ===")
        
        self.clients[username] = ws
        
        # Adicionar à sala geral
        if 'geral' not in self.rooms:
            self.rooms['geral'] = {'members': set(), 'owner': 'admin', 'created_at': datetime.now().isoformat()}
            self.room_messages['geral'] = []
        self.rooms['geral']['members'].add(username)
        
        await self.send_history(ws, username, 'geral')
        
        await ws.send_json({
            'type': 'system',
            'content': f'Bem-vindo {username}!'
        })
        
        if self.ollama_available:
            await ws.send_json({
                'type': 'system',
                'content': '🤖 Assistente IA disponível! Use /ia ou @ia para perguntar'
            })
        
        if self.is_admin(username):
            await ws.send_json({
                'type': 'system',
                'content': '👑 Você é um administrador! Use /admin para acessar o painel.'
            })
        
        await self.broadcast({
            'type': 'system',
            'content': f'{username} entrou no chat'
        })
        
        await self.send_user_list()
        await self.send_room_list()
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.process_message(username, data)
                    except json.JSONDecodeError:
                        await self.process_text_message(username, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    break
        except Exception as e:
            logger.error(f'Erro na conexão: {e}')
        finally:
            self.clients.pop(username, None)
            for room in self.rooms.values():
                room['members'].discard(username)
            await self.broadcast({
                'type': 'system',
                'content': f'{username} saiu do chat'
            })
            await self.send_user_list()
            logger.info(f"{username} desconectado")
        
        return ws
    
    async def process_text_message(self, username, text):
        logger.info(f"📩 Mensagem de {username}: {text[:100]}...")
        
        is_ai = text.lower().startswith(('/ia', '@ia', '/ai', '@ai', '!ia', '!ai'))
        
        if is_ai:
            prompt = text
            prefixes = ['/ia ', '@ia ', '/ai ', '@ai ', '!ia ', '!ai ']
            for prefix in prefixes:
                if text.lower().startswith(prefix):
                    prompt = text[len(prefix):]
                    break
            
            if not prompt:
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': '🤖 Digite sua pergunta após /ia ou @ia'
                })
                return
            
            await self.handle_ai_request(username, prompt, 'geral')
            return
        
        if text.lower() == '/admin':
            if self.is_admin(username):
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': '👑 Abrindo painel administrativo...'
                })
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': '📋 Acesse: http://' + request.host + '/admin'
                })
            else:
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': '❌ Acesso negado. Apenas administradores.'
                })
            return
        
        msg_id = str(uuid.uuid4())[:8]
        msg = {
            'id': msg_id,
            'type': 'message',
            'from': username,
            'content': text,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'room': 'geral'
        }
        self.message_ids[msg_id] = {'username': username, 'room': 'geral'}
        self.room_messages['geral'].append(msg)
        await self.broadcast(msg, 'geral')
    
    async def process_message(self, username, data):
        msg_type = data.get('type', '')
        room = data.get('room', 'geral')
        
        if room not in self.rooms:
            await self.send_error(username, 'Sala não existe')
            return
        
        if msg_type not in ['create_room', 'join_room', 'get_rooms', 'get_users']:
            if username not in self.rooms[room]['members']:
                await self.send_error(username, 'Você não é membro desta sala')
                return
        
        if msg_type == 'delete':
            msg_id = data.get('id', '')
            if msg_id in self.message_ids:
                msg_info = self.message_ids[msg_id]
                if msg_info['username'] == username:
                    room_name = msg_info['room']
                    self.room_messages[room_name] = [
                        m for m in self.room_messages[room_name] 
                        if m.get('id') != msg_id
                    ]
                    if msg_id in self.file_messages:
                        try:
                            if os.path.exists(self.file_messages[msg_id]):
                                os.remove(self.file_messages[msg_id])
                            del self.file_messages[msg_id]
                        except:
                            pass
                    del self.message_ids[msg_id]
                    await self.broadcast({
                        'type': 'message_deleted',
                        'id': msg_id,
                        'room': room_name
                    }, room_name)
                    await self.clients[username].send_json({
                        'type': 'system',
                        'content': '✅ Mensagem apagada'
                    })
                else:
                    await self.send_error(username, 'Você só pode apagar suas próprias mensagens')
            else:
                await self.send_error(username, 'Mensagem não encontrada')
        
        elif msg_type == 'delete_file':
            msg_id = data.get('msg_id', '')
            if msg_id in self.message_ids:
                msg_info = self.message_ids[msg_id]
                if msg_info['username'] == username:
                    room_name = msg_info['room']
                    self.room_messages[room_name] = [
                        m for m in self.room_messages[room_name] 
                        if m.get('id') != msg_id
                    ]
                    if msg_id in self.file_messages:
                        try:
                            if os.path.exists(self.file_messages[msg_id]):
                                os.remove(self.file_messages[msg_id])
                            del self.file_messages[msg_id]
                        except:
                            pass
                    del self.message_ids[msg_id]
                    await self.broadcast({
                        'type': 'file_deleted',
                        'id': msg_id,
                        'room': room_name
                    }, room_name)
                    await self.clients[username].send_json({
                        'type': 'system',
                        'content': '✅ Arquivo apagado'
                    })
                else:
                    await self.send_error(username, 'Você só pode apagar seus próprios arquivos')
            else:
                await self.send_error(username, 'Arquivo não encontrado')
        
        elif msg_type == 'clear_room':
            if self.rooms[room]['owner'] == username:
                clear_older_than = data.get('clear_older_than', 0)
                if clear_older_than > 0:
                    cutoff = datetime.now() - timedelta(hours=clear_older_than)
                    self.room_messages[room] = [
                        m for m in self.room_messages[room] 
                        if datetime.strptime(m['timestamp'], '%H:%M:%S').replace(year=datetime.now().year) > cutoff
                    ]
                    await self.broadcast({
                        'type': 'system',
                        'content': f'🧹 Mensagens mais antigas que {clear_older_than}h removidas.'
                    }, room)
                else:
                    removed_count = len(self.room_messages[room])
                    self.room_messages[room] = []
                    await self.broadcast({
                        'type': 'system',
                        'content': f'🧹 Sala "{room}" limpa! ({removed_count} mensagens removidas)'
                    }, room)
            else:
                await self.send_error(username, 'Apenas o criador pode limpar a sala')
        
        elif msg_type == 'message':
            content = data.get('content', '')
            if content:
                is_ai = content.lower().startswith(('/ia', '@ia', '/ai', '@ai', '!ia', '!ai'))
                if is_ai:
                    prompt = content
                    prefixes = ['/ia ', '@ia ', '/ai ', '@ai ', '!ia ', '!ai ']
                    for prefix in prefixes:
                        if content.lower().startswith(prefix):
                            prompt = content[len(prefix):]
                            break
                    if prompt:
                        await self.handle_ai_request(username, prompt, room)
                    return
                
                msg_id = str(uuid.uuid4())[:8]
                msg = {
                    'id': msg_id,
                    'type': 'message',
                    'from': username,
                    'content': content,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'room': room
                }
                self.message_ids[msg_id] = {'username': username, 'room': room}
                if room not in self.room_messages:
                    self.room_messages[room] = []
                self.room_messages[room].append(msg)
                await self.broadcast(msg, room)
        
        elif msg_type == 'file':
            await self.handle_file_upload(username, data)
        
        elif msg_type == 'ai_request':
            prompt = data.get('prompt', '')
            model = data.get('model', self.ollama_model)
            if model != self.ollama_model:
                self.ollama_model = model
            if prompt:
                await self.handle_ai_request(username, prompt, room)
        
        elif msg_type == 'get_users':
            await self.send_user_list()
        
        elif msg_type == 'get_rooms':
            await self.send_room_list()
        
        elif msg_type == 'get_history':
            room = data.get('room', 'geral')
            await self.send_history(self.clients[username], username, room)
        
        elif msg_type == 'typing':
            await self.broadcast({
                'type': 'typing',
                'from': username,
                'is_typing': data.get('is_typing', False)
            }, room)
        
        elif msg_type == 'create_room':
            room_name = data.get('name', '')
            if room_name and room_name not in self.rooms:
                self.rooms[room_name] = {
                    'members': {username},
                    'owner': username,
                    'created_at': datetime.now().isoformat()
                }
                self.room_messages[room_name] = []
                await self.broadcast({
                    'type': 'system',
                    'content': f'🏠 Sala "{room_name}" criada por {username}'
                })
                await self.send_room_list()
            else:
                await self.send_error(username, 'Sala já existe ou nome inválido')
        
        elif msg_type == 'join_room':
            room_name = data.get('room', '')
            if room_name in self.rooms:
                if username not in self.rooms[room_name]['members']:
                    self.rooms[room_name]['members'].add(username)
                    await self.broadcast({
                        'type': 'system',
                        'content': f'{username} entrou na sala "{room_name}"'
                    }, room_name)
                    await self.send_history(self.clients[username], username, room_name)
                    await self.send_room_list()
                else:
                    await self.send_error(username, 'Você já está nesta sala')
            else:
                await self.send_error(username, 'Sala não existe')
        
        elif msg_type == 'private':
            to_user = data.get('to', '')
            content = data.get('content', '')
            if to_user and content:
                msg_id = str(uuid.uuid4())[:8]
                msg = {
                    'id': msg_id,
                    'type': 'private',
                    'from': username,
                    'to': to_user,
                    'content': content,
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                }
                self.message_ids[msg_id] = {'username': username, 'room': 'private'}
                if to_user in self.clients:
                    await self.clients[to_user].send_json(msg)
                await self.clients[username].send_json({
                    **msg,
                    'sent': True
                })
        
        elif msg_type == 'kick_member':
            if self.rooms[room]['owner'] == username:
                target = data.get('target', '')
                if target in self.rooms[room]['members'] and target != username:
                    self.rooms[room]['members'].discard(target)
                    await self.broadcast({
                        'type': 'system',
                        'content': f'🚫 {target} foi expulso da sala "{room}" por {username}'
                    }, room)
                    if target in self.clients:
                        await self.clients[target].send_json({
                            'type': 'system',
                            'content': f'🚫 Você foi expulso da sala "{room}"'
                        })
                    await self.send_room_list()
                else:
                    await self.send_error(username, 'Usuário não encontrado')
            else:
                await self.send_error(username, 'Apenas o criador pode expulsar')
        
        elif msg_type == 'delete_room':
            if self.rooms[room]['owner'] == username:
                for member in list(self.rooms[room]['members']):
                    if member in self.clients:
                        await self.clients[member].send_json({
                            'type': 'system',
                            'content': f'🗑️ A sala "{room}" foi removida pelo criador'
                        })
                del self.rooms[room]
                if room in self.room_messages:
                    del self.room_messages[room]
                await self.broadcast({
                    'type': 'system',
                    'content': f'🗑️ Sala "{room}" foi removida'
                })
                await self.send_room_list()
            else:
                await self.send_error(username, 'Apenas o criador pode remover')
        
        elif msg_type == 'logout':
            await self.clients[username].close()
    
    async def handle_file_upload(self, username, data):
        filename = data.get('file_name', '')
        file_data = data.get('data', '')
        room = data.get('room', 'geral')
        
        if not filename or not file_data:
            return
        
        if room not in self.rooms or username not in self.rooms[room]['members']:
            await self.send_error(username, 'Você não é membro desta sala')
            return
        
        unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        filepath = f"uploads/{unique_name}"
        
        if file_data.startswith('data:'):
            file_data = file_data.split(',')[1]
        
        try:
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(file_data))
            
            file_size = os.path.getsize(filepath)
            msg_id = str(uuid.uuid4())[:8]
            
            msg = {
                'id': msg_id,
                'type': 'file',
                'from': username,
                'file_name': filename,
                'file_path': f'/uploads/{unique_name}',
                'file_size': file_size,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'room': room
            }
            
            self.message_ids[msg_id] = {'username': username, 'room': room}
            self.file_messages[msg_id] = filepath
            
            if room not in self.room_messages:
                self.room_messages[room] = []
            self.room_messages[room].append(msg)
            
            await self.broadcast(msg, room)
            logger.info(f"📎 Arquivo enviado: {filename} por {username}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo: {e}")
            await self.send_error(username, 'Erro ao enviar arquivo')
    
    async def handle_ai_request(self, username, prompt, room):
        logger.info(f"🤖 Requisição IA de {username}")
        
        await self.broadcast({
            'type': 'typing',
            'from': self.ai_username,
            'is_typing': True
        }, room)
        
        system_prompt = """Você é um assistente útil e amigável chamado "Assistente IA". 
        Responda de forma clara, concisa e amigável."""
        
        response = await self.call_ollama(prompt, system_prompt)
        
        await self.broadcast({
            'type': 'typing',
            'from': self.ai_username,
            'is_typing': False
        }, room)
        
        if response:
            msg_id = str(uuid.uuid4())[:8]
            msg = {
                'id': msg_id,
                'type': 'message',
                'from': self.ai_username,
                'content': f'🤖 {response}',
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'room': room
            }
            self.message_ids[msg_id] = {'username': self.ai_username, 'room': room}
            if room not in self.room_messages:
                self.room_messages[room] = []
            self.room_messages[room].append(msg)
            await self.broadcast(msg, room)
            logger.info(f"✅ Resposta IA enviada")
        else:
            await self.clients[username].send_json({
                'type': 'system',
                'content': '❌ Assistente IA indisponível no momento.'
            })
    
    async def send_history(self, ws, username, room):
        messages = self.room_messages.get(room, [])
        await ws.send_json({
            'type': 'history',
            'room': room,
            'messages': messages[-50:],
            'owner': self.rooms.get(room, {}).get('owner', ''),
            'ai_username': self.ai_username
        })
    
    async def send_room_list(self):
        rooms_info = []
        for room_name, room_data in self.rooms.items():
            rooms_info.append({
                'name': room_name,
                'owner': room_data.get('owner', ''),
                'members': list(room_data.get('members', set())),
                'member_count': len(room_data.get('members', set()))
            })
        await self.broadcast({
            'type': 'room_list',
            'rooms': rooms_info
        })
    
    async def send_user_list(self):
        users = list(self.clients.keys())
        await self.broadcast({
            'type': 'user_list',
            'users': users,
            'ai_user': self.ai_username if self.ollama_available else None
        })
    
    async def send_error(self, username, message):
        if username in self.clients:
            await self.clients[username].send_json({
                'type': 'error',
                'message': message
            })
    
    async def broadcast(self, message, room='geral'):
        data = json.dumps(message)
        disconnected = []
        
        for username, ws in self.clients.items():
            if room in self.rooms and username in self.rooms[room]['members']:
                try:
                    await ws.send_str(data)
                except Exception:
                    disconnected.append(username)
        
        for username in disconnected:
            self.clients.pop(username, None)
    
    async def run(self, host='0.0.0.0', port=8081):
        await self.check_ollama()
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        
        print("\n" + "="*60)
        print("  CHAT COM PAINEL ADMINISTRATIVO")
        print("="*60)
        print(f"📍 Local: http://localhost:{port}")
        print(f"🌐 Rede: http://seuip:{port}")
        print(f"👤 Admin: admin / admin123")
        print(f"📋 Painel Admin: http://seuip:{port}/admin")
        print("="*60)
        print("\n📋 FUNCIONALIDADES ADMIN:")
        print("  👥 Listar usuários")
        print("  🏠 Listar salas")
        print("  ➕ Criar salas")
        print("  🗑️ Apagar salas")
        print("  🔑 Alterar senhas")
        print("  🗑️ Apagar usuários")
        print("="*60 + "\n")
        
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Desligando servidor...")
            await runner.cleanup()

if __name__ == '__main__':
    server = ChatServer()
    asyncio.run(server.run())
