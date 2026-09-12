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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChatServer:
    def __init__(self):
        self.clients = {}
        self.rooms = {'geral': {'members': set(), 'owner': 'admin', 'created_at': datetime.now()}}
        self.room_messages = {'geral': []}
        self.message_ids = {}
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
        """Verifica se o Ollama está disponível"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_host}/api/tags", timeout=3) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = data.get('models', [])
                        if models:
                            self.ollama_model = models[0].get('name', self.ollama_model)
                            self.ollama_available = True
                            logger.info(f"✅ Ollama disponível. Modelo: {self.ollama_model}")
                        else:
                            logger.warning("⚠️ Ollama disponível, mas nenhum modelo encontrado")
                    else:
                        logger.warning("⚠️ Ollama não está respondendo")
        except Exception as e:
            logger.warning(f"⚠️ Ollama não disponível: {e}")
            self.ollama_available = False
    
    async def handle_ollama_models(self, request):
        """Retorna a lista de modelos Ollama disponíveis"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_host}/api/tags") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return web.json_response({
                            'success': True,
                            'models': [m.get('name') for m in data.get('models', [])],
                            'current': self.ollama_model
                        })
        except Exception as e:
            logger.error(f"Erro ao buscar modelos: {e}")
        
        return web.json_response({
            'success': False,
            'message': 'Ollama não disponível'
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
        """Chama o Ollama para gerar uma resposta"""
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
                        "top_p": 0.9
                    }
                }
                if system_prompt:
                    payload["system"] = system_prompt
                
                async with session.post(
                    f"{self.ollama_host}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('response', '').strip()
                    else:
                        logger.error(f"Erro Ollama: {resp.status}")
                        return None
        except asyncio.TimeoutError:
            logger.error("Timeout ao chamar Ollama")
            return None
        except Exception as e:
            logger.error(f"Erro ao chamar Ollama: {e}")
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
                'content': '🤖 Assistente IA disponível! Pergunte algo digitando "/ia" ou "@ia"'
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
                    logger.error(f'Erro: {ws.exception()}')
                    break
        except Exception as e:
            logger.error(f'Erro: {e}')
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
        """Processa mensagem de texto simples com suporte a IA"""
        # Verificar se é um comando para IA
        is_ai_request = text.lower().startswith(('/ia', '@ia', '/ai', '@ai', '!ia', '!ai'))
        
        if is_ai_request:
            # Remover o prefixo do comando
            prompt = text
            for prefix in ['/ia ', '@ia ', '/ai ', '@ai ', '!ia ', '!ai ']:
                if text.lower().startswith(prefix):
                    prompt = text[len(prefix):]
                    break
            
            if not prompt:
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': '🤖 Digite sua pergunta após /ia ou @ia'
                })
                return
            
            # Enviar indicador de que a IA está pensando
            await self.broadcast({
                'type': 'typing',
                'from': self.ai_username,
                'is_typing': True
            }, 'geral')
            
            # Chamar Ollama
            system_prompt = """Você é um assistente útil e amigável chamado "Assistente IA". 
            Você responde perguntas de forma clara e concisa. 
            Se não souber algo, diga que não sabe, não invente informações.
            Mantenha respostas curtas (máximo 2 parágrafos) a menos que seja necessário mais detalhes.
            Seja educado e profissional."""
            
            response = await self.call_ollama(prompt, system_prompt)
            
            # Remover indicador de digitação
            await self.broadcast({
                'type': 'typing',
                'from': self.ai_username,
                'is_typing': False
            }, 'geral')
            
            if response:
                # Enviar resposta da IA
                msg_id = str(uuid.uuid4())[:8]
                msg = {
                    'id': msg_id,
                    'type': 'message',
                    'from': self.ai_username,
                    'content': f'🤖 {response}',
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'room': 'geral'
                }
                self.message_ids[msg_id] = {'username': self.ai_username, 'room': 'geral'}
                self.room_messages['geral'].append(msg)
                await self.broadcast(msg, 'geral')
            else:
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': '❌ Assistente IA indisponível no momento. Verifique se o Ollama está rodando.'
                })
        else:
            # Mensagem normal
            await self.broadcast({
                'type': 'message',
                'from': username,
                'content': text,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            }, 'geral')
    
    async def process_message(self, username, data):
        msg_type = data.get('type', '')
        room = data.get('room', 'geral')
        
        if room not in self.rooms:
            await self.send_error(username, 'Sala não existe')
            return
        
        if msg_type not in ['create_room', 'join_room', 'get_rooms']:
            if username not in self.rooms[room]['members']:
                await self.send_error(username, 'Você não é membro desta sala')
                return
        
        if msg_type == 'message':
            content = data.get('content', '')
            if content:
                # Verificar se é uma pergunta para IA
                is_ai = content.lower().startswith(('/ia', '@ia', '/ai', '@ai', '!ia', '!ai'))
                
                if is_ai:
                    # Processar como IA
                    prompt = content
                    for prefix in ['/ia ', '@ia ', '/ai ', '@ai ', '!ia ', '!ai ']:
                        if content.lower().startswith(prefix):
                            prompt = content[len(prefix):]
                            break
                    
                    if prompt:
                        await self.handle_ai_request(username, prompt, room)
                    return
                
                # Mensagem normal
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
        
        elif msg_type == 'ai_request':
            # Requisição direta para IA
            prompt = data.get('prompt', '')
            if prompt:
                await self.handle_ai_request(username, prompt, room)
        
        elif msg_type == 'delete':
            msg_id = data.get('id', '')
            if msg_id in self.message_ids:
                msg_info = self.message_ids[msg_id]
                if msg_info['username'] == username:
                    room_name = msg_info['room']
                    self.room_messages[room_name] = [m for m in self.room_messages[room_name] if m.get('id') != msg_id]
                    for msg in self.room_messages[room_name]:
                        if msg.get('id') == msg_id and msg.get('file_path'):
                            try:
                                os.remove(msg.get('file_path'))
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
                        'content': 'Mensagem apagada com sucesso'
                    })
                else:
                    await self.send_error(username, 'Você só pode apagar suas próprias mensagens')
        
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
        
        elif msg_type == 'file':
            await self.handle_file_upload(username, data)
        
        elif msg_type == 'delete_file':
            file_path = data.get('file_path', '')
            msg_id = data.get('msg_id', '')
            if msg_id in self.message_ids:
                msg_info = self.message_ids[msg_id]
                if msg_info['username'] == username:
                    try:
                        if file_path and os.path.exists(file_path):
                            os.remove(file_path)
                        await self.broadcast({
                            'type': 'file_deleted',
                            'file_path': file_path,
                            'room': room
                        }, room)
                        await self.clients[username].send_json({
                            'type': 'system',
                            'content': 'Arquivo apagado com sucesso'
                        })
                    except Exception as e:
                        logger.error(f"Erro ao apagar arquivo: {e}")
                else:
                    await self.send_error(username, 'Você só pode apagar seus próprios arquivos')
        
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
                        'content': f'Sala limpa! Mensagens mais antigas que {clear_older_than}h foram removidas.'
                    }, room)
                else:
                    self.room_messages[room] = []
                    await self.broadcast({
                        'type': 'system',
                        'content': f'Sala "{room}" foi completamente limpa pelo criador'
                    }, room)
            else:
                await self.send_error(username, 'Apenas o criador da sala pode limpar as mensagens')
        
        elif msg_type == 'kick_member':
            if self.rooms[room]['owner'] == username:
                target = data.get('target', '')
                if target in self.rooms[room]['members'] and target != username:
                    self.rooms[room]['members'].discard(target)
                    await self.broadcast({
                        'type': 'system',
                        'content': f'{target} foi expulso da sala "{room}" por {username}'
                    }, room)
                    if target in self.clients:
                        await self.clients[target].send_json({
                            'type': 'system',
                            'content': f'Você foi expulso da sala "{room}"'
                        })
                    await self.send_room_list()
                else:
                    await self.send_error(username, 'Usuário não encontrado na sala')
            else:
                await self.send_error(username, 'Apenas o criador da sala pode expulsar membros')
        
        elif msg_type == 'delete_room':
            if self.rooms[room]['owner'] == username:
                for member in list(self.rooms[room]['members']):
                    if member in self.clients:
                        await self.clients[member].send_json({
                            'type': 'system',
                            'content': f'A sala "{room}" foi removida pelo criador'
                        })
                del self.rooms[room]
                if room in self.room_messages:
                    del self.room_messages[room]
                await self.broadcast({
                    'type': 'system',
                    'content': f'Sala "{room}" foi removida pelo criador'
                })
                await self.send_room_list()
            else:
                await self.send_error(username, 'Apenas o criador da sala pode removê-la')
        
        elif msg_type == 'get_users':
            await self.send_user_list()
        
        elif msg_type == 'get_history':
            room = data.get('room', 'geral')
            await self.send_history(self.clients[username], username, room)
        
        elif msg_type == 'get_rooms':
            await self.send_room_list()
        
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
                    'content': f'Sala "{room_name}" criada por {username}'
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
        
        elif msg_type == 'typing':
            await self.broadcast({
                'type': 'typing',
                'from': username,
                'is_typing': data.get('is_typing', False)
            }, room)
        
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
            
            self.message_ids[msg_id] = {'username': username, 'room': room, 'file_path': filepath}
            
            if room not in self.room_messages:
                self.room_messages[room] = []
            self.room_messages[room].append(msg)
            
            await self.broadcast(msg, room)
            logger.info(f"Arquivo enviado: {filename} por {username}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo: {e}")
            await self.send_error(username, 'Erro ao enviar arquivo')
    
    async def handle_ai_request(self, username, prompt, room):
        """Processa uma requisição para a IA"""
        # Notificar que a IA está pensando
        await self.broadcast({
            'type': 'typing',
            'from': self.ai_username,
            'is_typing': True
        }, room)
        
        # Chamar Ollama
        system_prompt = """Você é um assistente útil e amigável chamado "Assistente IA" que ajuda no chat. 
        Você responde perguntas de forma clara, concisa e amigável.
        Se não souber algo, diga que não sabe, não invente informações.
        Mantenha respostas curtas e diretas.
        Seja educado e profissional."""
        
        response = await self.call_ollama(prompt, system_prompt)
        
        # Remover indicador de digitação
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
        else:
            await self.clients[username].send_json({
                'type': 'system',
                'content': '❌ Assistente IA indisponível. Verifique se o Ollama está rodando.'
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
                'owner': room_data['owner'],
                'members': list(room_data['members']),
                'member_count': len(room_data['members'])
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
            'ai_user': self.ai_username
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
        # Verificar Ollama antes de iniciar
        await self.check_ollama()
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        
        print("\n" + "="*60)
        print("  CHAT COM INTEGRAÇÃO OLLAMA - ASSISTENTE IA")
        print("="*60)
        print(f"📍 Local: http://localhost:{port}")
        print(f"🌐 Rede: http://10.0.39.24:{port}")
        print(f"👤 Admin: admin / admin123")
        print(f"🤖 Ollama: {self.ollama_host}")
        print(f"📦 Modelo: {self.ollama_model}")
        print(f"📊 Status: {'✅ Disponível' if self.ollama_available else '❌ Indisponível'}")
        print("="*60)
        print("\n📋 COMO USAR A IA:")
        print("  🔹 Digite /ia <pergunta> ou @ia <pergunta>")
        print("  🔹 Clique no botão 🤖 no chat")
        print("  🔹 A IA vai responder em segundos")
        print("  🔹 Disponível em qualquer sala")
        print("="*60 + "\n")
        
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Desligando servidor...")

if __name__ == '__main__':
    server = ChatServer()
    asyncio.run(server.run())
