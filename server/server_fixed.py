#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import base64
import os
import uuid
import aiohttp
from datetime import datetime, timedelta
from aiohttp import web, WSMsgType
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ChatServer:
    def __init__(self):
        self.clients = {}
        self.rooms = {'geral': {'members': set(), 'owner': 'admin', 'created_at': datetime.now()}}
        self.room_messages = {'geral': []}
        self.message_ids = {}
        self.file_messages = {}  # msg_id -> file_path
        self.ollama_host = "http://localhost:11434"
        self.ollama_model = "phi3"
        self.ai_username = "🤖 Assistente IA"
        self.ollama_available = False
        self.app = web.Application()
        self.setup_routes()
        os.makedirs('uploads', exist_ok=True)
    
    def setup_routes(self):
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/login', self.handle_login)
        self.app.router.add_get('/chat', self.handle_chat)
        self.app.router.add_get('/ws', self.handle_websocket)
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/api/ollama/models', self.handle_ollama_models)
        self.app.router.add_get('/uploads/{filename}', self.handle_upload)
        self.app.router.add_post('/api/login', self.handle_login_api)
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
            'ollama': {
                'available': self.ollama_available,
                'model': self.ollama_model
            }
        })
    
    async def handle_login_api(self, request):
        data = await request.post()
        username = data.get('username', '')
        password = data.get('password', '')
        if username and password:
            return web.json_response({
                'success': True,
                'message': 'Login realizado',
                'username': username
            })
        return web.json_response({
            'success': False,
            'message': 'Credenciais inválidas'
        })
    
    async def call_ollama(self, prompt, system_prompt=""):
        if not self.ollama_available:
            logger.warning("Ollama não disponível")
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
                
                logger.info(f"🤖 Chamando Ollama com modelo: {self.ollama_model}")
                
                async with session.post(
                    f"{self.ollama_host}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        response = data.get('response', '').strip()
                        logger.info(f"✅ Resposta recebida")
                        return response
                    else:
                        logger.error(f"❌ Erro Ollama: {resp.status}")
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
        
        if 'geral' not in self.rooms:
            self.rooms['geral'] = {'members': set(), 'owner': 'admin', 'created_at': datetime.now()}
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
                    logger.error(f'Erro WebSocket: {ws.exception()}')
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
        
        logger.info(f"🔄 Processando: {msg_type} de {username}")
        
        if room not in self.rooms:
            await self.send_error(username, 'Sala não existe')
            return
        
        if msg_type not in ['create_room', 'join_room', 'get_rooms', 'get_users']:
            if username not in self.rooms[room]['members']:
                await self.send_error(username, 'Você não é membro desta sala')
                return
        
        # ============================================
        # DELETE MESSAGE
        # ============================================
        if msg_type == 'delete':
            msg_id = data.get('id', '')
            logger.info(f"🗑️ Tentando apagar mensagem: {msg_id} por {username}")
            
            if msg_id in self.message_ids:
                msg_info = self.message_ids[msg_id]
                
                if msg_info['username'] == username:
                    room_name = msg_info['room']
                    
                    # Remover do histórico
                    self.room_messages[room_name] = [
                        m for m in self.room_messages[room_name] 
                        if m.get('id') != msg_id
                    ]
                    
                    # Remover arquivo se existir
                    if msg_id in self.file_messages:
                        try:
                            file_path = self.file_messages[msg_id]
                            if os.path.exists(file_path):
                                os.remove(file_path)
                                logger.info(f"✅ Arquivo removido: {file_path}")
                            del self.file_messages[msg_id]
                        except Exception as e:
                            logger.error(f"Erro ao remover arquivo: {e}")
                    
                    del self.message_ids[msg_id]
                    
                    await self.broadcast({
                        'type': 'message_deleted',
                        'id': msg_id,
                        'room': room_name
                    }, room_name)
                    
                    await self.clients[username].send_json({
                        'type': 'system',
                        'content': '✅ Mensagem apagada com sucesso'
                    })
                    logger.info(f"✅ Mensagem {msg_id} apagada por {username}")
                else:
                    await self.send_error(username, 'Você só pode apagar suas próprias mensagens')
            else:
                await self.send_error(username, 'Mensagem não encontrada')
        
        # ============================================
        # DELETE FILE - CORRIGIDO
        # ============================================
        elif msg_type == 'delete_file':
            msg_id = data.get('msg_id', '')
            file_path = data.get('file_path', '')
            logger.info(f"🗑️ Tentando apagar arquivo: {msg_id} - {file_path} por {username}")
            
            if msg_id in self.message_ids:
                msg_info = self.message_ids[msg_id]
                logger.info(f"📋 Info: {msg_info}")
                
                if msg_info['username'] == username:
                    room_name = msg_info['room']
                    
                    # Remover do histórico
                    self.room_messages[room_name] = [
                        m for m in self.room_messages[room_name] 
                        if m.get('id') != msg_id
                    ]
                    
                    # Remover arquivo do disco
                    if msg_id in self.file_messages:
                        try:
                            file_to_delete = self.file_messages[msg_id]
                            if os.path.exists(file_to_delete):
                                os.remove(file_to_delete)
                                logger.info(f"✅ Arquivo removido: {file_to_delete}")
                            del self.file_messages[msg_id]
                        except Exception as e:
                            logger.error(f"Erro ao remover arquivo: {e}")
                    elif file_path:
                        # Fallback: tentar remover pelo caminho
                        full_path = Path('uploads') / Path(file_path).name
                        if full_path.exists():
                            os.remove(full_path)
                            logger.info(f"✅ Arquivo removido (fallback): {full_path}")
                    
                    del self.message_ids[msg_id]
                    
                    await self.broadcast({
                        'type': 'file_deleted',
                        'id': msg_id,
                        'room': room_name
                    }, room_name)
                    
                    await self.clients[username].send_json({
                        'type': 'system',
                        'content': '✅ Arquivo apagado com sucesso'
                    })
                    logger.info(f"✅ Arquivo {msg_id} apagado por {username}")
                else:
                    await self.send_error(username, 'Você só pode apagar seus próprios arquivos')
            else:
                await self.send_error(username, 'Arquivo não encontrado')
        
        # ============================================
        # CLEAR ROOM
        # ============================================
        elif msg_type == 'clear_room':
            logger.info(f"🧹 Limpando sala {room} por {username}")
            
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
                        'content': f'🧹 Sala limpa! Mensagens mais antigas que {clear_older_than}h foram removidas.'
                    }, room)
                else:
                    removed_count = len(self.room_messages[room])
                    self.room_messages[room] = []
                    await self.broadcast({
                        'type': 'system',
                        'content': f'🧹 Sala "{room}" foi completamente limpa pelo criador ({removed_count} mensagens removidas)'
                    }, room)
                
                logger.info(f"✅ Sala {room} limpa por {username}")
            else:
                await self.send_error(username, 'Apenas o criador da sala pode limpar as mensagens')
        
        # ============================================
        # MENSAGEM NORMAL
        # ============================================
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
        
        # ============================================
        # FILE UPLOAD
        # ============================================
        elif msg_type == 'file':
            await self.handle_file_upload(username, data)
        
        # ============================================
        # AI REQUEST
        # ============================================
        elif msg_type == 'ai_request':
            prompt = data.get('prompt', '')
            model = data.get('model', self.ollama_model)
            if model != self.ollama_model:
                self.ollama_model = model
            if prompt:
                await self.handle_ai_request(username, prompt, room)
        
        # ============================================
        # GET USERS
        # ============================================
        elif msg_type == 'get_users':
            logger.info(f"📋 Enviando lista de usuários para {username}")
            await self.send_user_list()
        
        # ============================================
        # GET ROOMS
        # ============================================
        elif msg_type == 'get_rooms':
            logger.info(f"📋 Enviando lista de salas para {username}")
            await self.send_room_list()
        
        # ============================================
        # GET HISTORY
        # ============================================
        elif msg_type == 'get_history':
            room = data.get('room', 'geral')
            await self.send_history(self.clients[username], username, room)
        
        # ============================================
        # TYPING
        # ============================================
        elif msg_type == 'typing':
            await self.broadcast({
                'type': 'typing',
                'from': username,
                'is_typing': data.get('is_typing', False)
            }, room)
        
        # ============================================
        # CREATE ROOM
        # ============================================
        elif msg_type == 'create_room':
            room_name = data.get('name', '')
            if room_name and room_name not in self.rooms:
                self.rooms[room_name] = {
                    'members': {username},
                    'owner': username,
                    'created_at': datetime.now()
                }
                self.room_messages[room_name] = []
                await self.broadcast({
                    'type': 'system',
                    'content': f'🏠 Sala "{room_name}" criada por {username}'
                })
                await self.send_room_list()
            else:
                await self.send_error(username, 'Sala já existe ou nome inválido')
        
        # ============================================
        # JOIN ROOM
        # ============================================
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
        
        # ============================================
        # PRIVATE MESSAGE
        # ============================================
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
        
        # ============================================
        # KICK MEMBER
        # ============================================
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
                    await self.send_error(username, 'Usuário não encontrado na sala')
            else:
                await self.send_error(username, 'Apenas o criador da sala pode expulsar membros')
        
        # ============================================
        # DELETE ROOM
        # ============================================
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
                    'content': f'🗑️ Sala "{room}" foi removida pelo criador'
                })
                await self.send_room_list()
            else:
                await self.send_error(username, 'Apenas o criador da sala pode removê-la')
        
        # ============================================
        # LOGOUT
        # ============================================
        elif msg_type == 'logout':
            await self.clients[username].close()
    
    async def handle_file_upload(self, username, data):
        filename = data.get('file_name', '')
        file_data = data.get('data', '')
        room = data.get('room', 'geral')
        
        if not filename or not file_data:
            return
        
        if room not in self.rooms:
            await self.send_error(username, 'Sala não existe')
            return
        
        if username not in self.rooms[room]['members']:
            await self.send_error(username, 'Você não é membro desta sala')
            return
        
        name_parts = filename.split('.')
        ext = name_parts[-1] if len(name_parts) > 1 else ''
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
            self.file_messages[msg_id] = filepath  # Guardar caminho do arquivo
            
            if room not in self.room_messages:
                self.room_messages[room] = []
            self.room_messages[room].append(msg)
            
            await self.broadcast(msg, room)
            logger.info(f"📎 Arquivo enviado: {filename} por {username} -> {filepath}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo: {e}")
            await self.send_error(username, 'Erro ao enviar arquivo')
    
    async def handle_ai_request(self, username, prompt, room):
        logger.info(f"🤖 Requisição IA de {username}: {prompt[:100]}...")
        
        await self.broadcast({
            'type': 'typing',
            'from': self.ai_username,
            'is_typing': True
        }, room)
        
        system_prompt = """Você é um assistente útil e amigável chamado "Assistente IA". 
        Responda de forma clara, concisa e amigável.
        Se não souber algo, diga que não sabe.
        Mantenha respostas curtas (máximo 2 parágrafos)."""
        
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
            logger.info(f"✅ Resposta IA enviada para {username}")
        else:
            await self.clients[username].send_json({
                'type': 'system',
                'content': '❌ Assistente IA indisponível no momento. Verifique se o Ollama está rodando.'
            })
            logger.warning(f"❌ Falha ao obter resposta da IA para {username}")
    
    async def send_history(self, ws, username, room):
        messages = self.room_messages.get(room, [])
        logger.info(f"📜 Enviando histórico para {username} na sala {room}: {len(messages)} mensagens")
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
                'owner': room_data['owner'],
                'members': list(room_data['members']),
                'member_count': len(room_data['members'])
            })
        logger.info(f"📋 Enviando lista de salas: {len(rooms_info)} salas")
        await self.broadcast({
            'type': 'room_list',
            'rooms': rooms_info
        })
    
    async def send_user_list(self):
        users = list(self.clients.keys())
        logger.info(f"👥 Enviando lista de usuários: {len(users)} usuários")
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
        print("  CHAT COM INTEGRAÇÃO OLLAMA")
        print("="*60)
        print(f"📍 Local: http://localhost:{port}")
        print(f"🌐 Rede: http://10.0.39.24:{port}")
        print(f"👤 Admin: admin / admin123")
        print(f"🤖 Ollama: {'✅ Disponível' if self.ollama_available else '❌ Indisponível'}")
        print(f"📦 Modelo: {self.ollama_model}")
        print("="*60)
        print("\n📋 COMANDOS:")
        print("  /ia <pergunta>  - Perguntar para IA")
        print("  @ia <pergunta>  - Perguntar para IA")
        print("  /lista          - Listar usuários")
        print("  /criar <nome>   - Criar sala")
        print("  /entrar <nome>  - Entrar em sala")
        print("  🗑️ Clique no ✕ da mensagem para apagar (apenas o dono)")
        print("  🧹 Criador pode limpar a sala (botão Limpar)")
        print("="*60 + "\n")
        
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Desligando servidor...")
            await runner.cleanup()

if __name__ == '__main__':
    server = ChatServer()
    asyncio.run(server.run())
