#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file server_admin2.py
@brief Servidor DeepCord com persistência em JSON (sem MySQL) + Orquestrador multi-agente + RAG
"""

import asyncio
import json
import logging
import base64
import os
import uuid
import hashlib
import secrets
import aiohttp
from datetime import datetime, timedelta
from aiohttp import web, WSMsgType
from pathlib import Path

# ============================================
# ORQUESTRADOR (módulo externo)
# ============================================
try:
    from orchestrator import Orchestrator
    ORCHESTRATOR_AVAILABLE = True
except ImportError:
    ORCHESTRATOR_AVAILABLE = False
    Orchestrator = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ChatServer:
    def __init__(self, data_file='user_data.json'):
        # WebSocket ativos (memória)
        self.clients = {}
        # Sessões HTTP admin (memória)
        self.sessions = {}

        # Arquivo de persistência
        self.data_file = data_file

        # Estruturas de dados
        self.users = {}
        self.rooms = {}
        self.room_messages = {}
        self.message_ids = {}
        self.file_messages = {}
        self.user_events = {}
        self.user_disciplines = {}
        self.display_names = {}
        self.profile_photos = {}
        self.private_messages = {}   # {key: [msg, ...]}

        # IA
        self.ollama_host = "http://localhost:11434"
        self.ollama_model = "phi3"
        self.ai_username = "🤖 IA DeepCord"
        self.orchestrator_username = "🧠 Orquestrador"
        self.ollama_available = False

        # Setup
        self.app = web.Application(client_max_size=50 * 1024 * 1024)
        self.setup_routes()
        os.makedirs('uploads', exist_ok=True)
        os.makedirs('conhecimento', exist_ok=True)

        # Carrega dados OU cria defaults
        if not self.load_data():
            self.create_defaults()
            self.save_data()

        # ============================================
        # ORQUESTRADOR
        # ============================================
        if ORCHESTRATOR_AVAILABLE:
            try:
                self.orchestrator = Orchestrator(
                    ollama_host=self.ollama_host,
                    model="refinedneuro/refinedtoolcallv5-3b",
                    knowledge_base="conhecimento"
                )
                logger.info("🧠 Orquestrador inicializado")
            except Exception as e:
                logger.error(f"❌ Falha ao inicializar orquestrador: {e}")
                self.orchestrator = None
        else:
            self.orchestrator = None
            logger.warning("⚠️ orchestrator.py não encontrado — /orq desabilitado")

        # Garantir usuário do orquestrador no JSON
        self.ensure_orchestrator_user()

    # ============================================
    # GARANTIR USUÁRIO ORQUESTRADOR
    # ============================================
    def ensure_orchestrator_user(self):
        """Garante que o usuário orquestrador existe no JSON."""
        if self.orchestrator_username not in self.users:
            self.users[self.orchestrator_username] = {
                'password': hashlib.sha256('no_login_orq'.encode()).hexdigest(),
                'is_admin': False,
                'email': 'orq@chat.com',
                'created_at': datetime.now().isoformat()
            }
            # Adiciona à sala geral
            if 'geral' in self.rooms:
                self.rooms['geral']['members'].add(self.orchestrator_username)
            self.save_data()
            logger.info(f"✅ Usuário '{self.orchestrator_username}' garantido")

    # ============================================
    # PERSISTÊNCIA (JSON)
    # ============================================
    def load_data(self) -> bool:
        if not os.path.exists(self.data_file):
            logger.info(f"📁 {self.data_file} não existe. Criando...")
            return False
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                d = json.load(f)

            self.users = d.get('users', {})

            self.rooms = {}
            for rname, rdata in d.get('rooms', {}).items():
                self.rooms[rname] = {
                    **rdata,
                    'members': set(rdata.get('members', []))
                }

            self.room_messages = d.get('room_messages', {})
            self.message_ids = d.get('message_ids', {})
            self.file_messages = d.get('file_messages', {})
            self.user_events = d.get('user_events', {})
            self.user_disciplines = d.get('user_disciplines', {})
            self.display_names = d.get('display_names', {})
            self.profile_photos = d.get('profile_photos', {})
            self.private_messages = d.get('private_messages', {})

            logger.info(f"💾 Dados carregados de {self.data_file}")
            logger.info(f"   👥 {len(self.users)} usuários")
            logger.info(f"   🏠 {len(self.rooms)} salas")
            logger.info(f"   📅 {sum(len(v) for v in self.user_events.values())} eventos")
            logger.info(f"   📚 {sum(len(v) for v in self.user_disciplines.values())} disciplinas")
            return True
        except Exception as e:
            logger.error(f"Erro ao carregar dados: {e}")
            return False

    def save_data(self):
        try:
            rooms_serializable = {}
            for rname, rdata in self.rooms.items():
                rooms_serializable[rname] = {
                    **{k: v for k, v in rdata.items() if k != 'members'},
                    'members': list(rdata.get('members', set()))
                }
            data = {
                'users': self.users,
                'rooms': rooms_serializable,
                'room_messages': self.room_messages,
                'message_ids': self.message_ids,
                'file_messages': self.file_messages,
                'user_events': self.user_events,
                'user_disciplines': self.user_disciplines,
                'display_names': self.display_names,
                'profile_photos': self.profile_photos,
                'private_messages': self.private_messages,
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"Erro ao salvar dados: {e}")

    def create_defaults(self):
        admin_password = hashlib.sha256("admin123".encode()).hexdigest()
        self.users['admin'] = {
            'password': admin_password,
            'is_admin': True,
            'email': 'admin@chat.com',
            'created_at': datetime.now().isoformat()
        }

        demo_password = hashlib.sha256("demo123".encode()).hexdigest()
        self.users['demo'] = {
            'password': demo_password,
            'is_admin': False,
            'email': 'demo@chat.com',
            'created_at': datetime.now().isoformat()
        }

        # Usuário IA
        self.users[self.ai_username] = {
            'password': hashlib.sha256('no_login_ai'.encode()).hexdigest(),
            'is_admin': False,
            'email': 'ai@chat.com',
            'created_at': datetime.now().isoformat()
        }

        # Usuário Orquestrador
        self.users[self.orchestrator_username] = {
            'password': hashlib.sha256('no_login_orq'.encode()).hexdigest(),
            'is_admin': False,
            'email': 'orq@chat.com',
            'created_at': datetime.now().isoformat()
        }

        self.rooms['geral'] = {
            'members': {'admin', 'demo', self.ai_username, self.orchestrator_username},
            'owner': 'admin',
            'created_at': datetime.now().isoformat(),
            'password': None,
            'is_private': False
        }
        self.room_messages['geral'] = []

        logger.info("✅ Defaults criados (admin, demo, IA, Orquestrador, sala geral)")

    # ============================================
    # ROTAS
    # ============================================
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
        self.app.router.add_get('/api/folders', self.handle_get_folders)
        self.app.router.add_get('/api/materials', self.handle_get_materials)
        self.app.router.add_get('/api/materials/file/{path:.*}', self.handle_get_material_file)
        self.app.router.add_post('/api/orq/upload', self.handle_orq_upload)
        self.app.router.add_get('/api/debug/clients', self.handle_debug_clients)
        self.app.router.add_get('/uploads/{filename}', self.handle_upload)
        self.app.router.add_post('/api/login', self.handle_login_api)
        self.app.router.add_post('/api/register', self.handle_register)
        self.app.router.add_post('/api/admin/users', self.handle_admin_users)
        self.app.router.add_post('/api/admin/password', self.handle_admin_password)
        self.app.router.add_post('/api/admin/delete', self.handle_admin_delete)
        self.app.router.add_post('/api/reset-password', self.handle_reset_password)
        self.app.router.add_get('/{path}', self.handle_static)

    # ============================================
    # IA
    # ============================================
    async def check_ollama(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_host}/api/tags", timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = data.get('models', [])
                        if models:
                            names = [m.get('name') for m in models]
                            if self.ollama_model not in names:
                                self.ollama_model = names[0]
                            self.ollama_available = True
                            logger.info(f"✅ IA disponível: {self.ollama_model}")
                            logger.info(f"📦 Modelos: {', '.join(names)}")
                        else:
                            logger.warning("⚠️ Ollama sem modelos")
                    else:
                        logger.warning(f"⚠️ Ollama status {resp.status}")
        except Exception as e:
            logger.warning(f"⚠️ Ollama indisponível: {e}")
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
        except Exception:
            pass
        return web.json_response({'success': False, 'available': False})

    # ============================================
    # NOVO: LISTAR PASTAS DE CONHECIMENTO
    # ============================================
    async def handle_get_materials(self, request):
        """Lista todos os materiais disponíveis na pasta conhecimento/."""
        try:
            base_path = Path('conhecimento')
            base_path.mkdir(parents=True, exist_ok=True)
            supported_exts = {'.md', '.txt', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp'}
            materials = []
            for pasta in sorted(base_path.iterdir()):
                if not pasta.is_dir() or pasta.name.startswith('.'):
                    continue
                arquivos = []
                for f in sorted(pasta.rglob('*')):
                    if not f.is_file() or f.suffix.lower() not in supported_exts:
                        continue
                    rel = f.relative_to(base_path)
                    rel_str = str(rel).replace('\\', '/')
                    arquivos.append({
                        'name': f.name,
                        'path': rel_str,
                        'size': f.stat().st_size,
                        'ext': f.suffix.lower(),
                        'modified': datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                    })
                materials.append({
                    'folder': pasta.name,
                    'file_count': len(arquivos),
                    'files': arquivos
                })
            return web.json_response({'success': True, 'materials': materials})
        except Exception as e:
            logger.error(f"Erro ao listar materiais: {e}")
            return web.json_response({'success': False, 'materials': [], 'message': str(e)})

    async def handle_get_material_file(self, request):
        """Serve um arquivo da pasta conhecimento/ para download/visualização."""
        try:
            rel_path = request.match_info.get('path', '')
            if not rel_path or '..' in rel_path:
                return web.Response(status=400, text='Caminho inválido')
            base_path = Path('conhecimento').resolve()
            file_path = (base_path / rel_path).resolve()
            if not str(file_path).startswith(str(base_path)):
                return web.Response(status=403, text='Acesso negado')
            if not file_path.exists() or not file_path.is_file():
                return web.Response(status=404, text='Arquivo não encontrado')
            return web.FileResponse(file_path)
        except Exception as e:
            logger.error(f"Erro ao servir material: {e}")
            return web.Response(status=500, text=str(e))

    async def handle_get_folders(self, request):
        """Lista pastas da base de conhecimento disponíveis para o orquestrador."""
        try:
            base_path = Path('conhecimento')
            base_path.mkdir(parents=True, exist_ok=True)

            supported_exts = {'.md', '.txt', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp'}
            folders = []

            for item in sorted(base_path.iterdir()):
                if item.is_dir() and not item.name.startswith('.'):
                    file_count = sum(
                        1 for f in item.rglob('*')
                        if f.is_file() and f.suffix.lower() in supported_exts
                    )
                    folders.append({'name': item.name, 'file_count': file_count})

            return web.json_response({'success': True, 'folders': folders})
        except Exception as e:
            logger.error(f"Erro ao listar pastas: {e}")
            return web.json_response({'success': False, 'folders': [], 'message': str(e)})

    async def call_ollama(self, prompt, system_prompt=""):
        if not self.ollama_available:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.7, "top_p": 0.9, "num_predict": 500}
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
        except Exception as e:
            logger.error(f"❌ Erro Ollama: {e}")
        return None

    # ============================================
    # ADMIN AUTH
    # ============================================
    def is_admin(self, username):
        return username in self.users and self.users[username].get('is_admin', False)

    def get_session_user(self, request):
        token = request.cookies.get('admin_token', '')
        return self.sessions.get(token)

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
        if not self.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)

        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if self.users[username]['password'] != password_hash:
            return web.json_response({'success': False, 'message': 'Senha incorreta'}, status=401)

        token = secrets.token_hex(32)
        self.sessions[token] = username
        response = web.json_response({'success': True, 'message': 'Login', 'username': username})
        response.set_cookie('admin_token', token, max_age=3600, httponly=True, samesite='Lax')
        return response

    async def handle_admin_api_logout(self, request):
        token = request.cookies.get('admin_token', '')
        self.sessions.pop(token, None)
        response = web.json_response({'success': True})
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
    # ADMIN API
    # ============================================
    async def handle_get_users(self, request):
        username = self.get_session_user(request)
        if not username or not self.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        users_list = []
        for uname, info in self.users.items():
            if uname in (self.ai_username, self.orchestrator_username):
                continue
            users_list.append({
                'username': uname,
                'is_admin': info.get('is_admin', False),
                'email': info.get('email', ''),
                'created_at': info.get('created_at', ''),
                'is_online': uname in self.clients
            })
        return web.json_response({'success': True, 'users': users_list})

    async def handle_get_rooms(self, request):
        username = self.get_session_user(request)
        if not username or not self.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        rooms_list = []
        for rname, rdata in self.rooms.items():
            rooms_list.append({
                'name': rname,
                'owner': rdata.get('owner', ''),
                'member_count': len(rdata.get('members', set())),
                'members': list(rdata.get('members', set())),
                'created_at': rdata.get('created_at', ''),
                'message_count': len(self.room_messages.get(rname, [])),
                'is_private': rdata.get('is_private', False)
            })
        return web.json_response({'success': True, 'rooms': rooms_list})

    async def handle_admin_rooms(self, request):
        username = self.get_session_user(request)
        if not username or not self.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        data = await request.post()
        action = data.get('action', '')
        room_name = data.get('name', '')
        if action == 'create':
            if not room_name or room_name in self.rooms:
                return web.json_response({'success': False, 'message': 'Sala já existe'})
            self.rooms[room_name] = {
                'members': set(),
                'owner': username,
                'created_at': datetime.now().isoformat(),
                'password': None,
                'is_private': False
            }
            self.room_messages[room_name] = []
            self.save_data()
            await self.send_room_list()
            await self.broadcast({
                'type': 'system',
                'content': f'🏠 Sala "{room_name}" criada pelo admin'
            })
            return web.json_response({'success': True, 'message': f'Sala criada'})
        return web.json_response({'success': False, 'message': 'Ação inválida'})

    async def handle_admin_delete_room(self, request):
        username = self.get_session_user(request)
        if not username or not self.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        data = await request.post()
        room_name = data.get('name', '')
        if room_name not in self.rooms:
            return web.json_response({'success': False, 'message': 'Sala não encontrada'})
        if room_name == 'geral':
            return web.json_response({'success': False, 'message': 'Não pode apagar a sala geral'})
        for member in list(self.rooms[room_name].get('members', set())):
            if member in self.clients:
                try:
                    await self.clients[member].send_json({
                        'type': 'system',
                        'content': f'🗑️ A sala "{room_name}" foi removida'
                    })
                except Exception:
                    pass
        del self.rooms[room_name]
        self.room_messages.pop(room_name, None)
        self.save_data()
        await self.send_room_list()
        return web.json_response({'success': True, 'message': 'Sala removida'})

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
                if uname in (self.ai_username, self.orchestrator_username):
                    continue
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
                return web.json_response({'success': False, 'message': 'Senha mín 6'})
            if username in self.users:
                return web.json_response({'success': False, 'message': 'Já existe'})
            self.users[username] = {
                'password': hashlib.sha256(password.encode()).hexdigest(),
                'is_admin': is_admin,
                'email': email,
                'created_at': datetime.now().isoformat()
            }
            if 'geral' in self.rooms:
                self.rooms['geral']['members'].add(username)
            self.save_data()
            return web.json_response({'success': True, 'message': 'Usuário criado'})

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
            return web.json_response({'success': False, 'message': 'Senha mín 6'})
        self.users[username]['password'] = hashlib.sha256(new_password.encode()).hexdigest()
        self.save_data()
        if username in self.clients:
            try:
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': '🔐 Sua senha foi alterada'
                })
            except Exception:
                pass
        return web.json_response({'success': True, 'message': 'Senha alterada'})

    async def handle_admin_delete(self, request):
        admin_user = self.get_session_user(request)
        if not admin_user or not self.is_admin(admin_user):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        data = await request.post()
        username = data.get('username', '')
        if username not in self.users:
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        if username == admin_user or username == 'admin':
            return web.json_response({'success': False, 'message': 'Não pode apagar'})
        del self.users[username]
        for room in self.rooms.values():
            room['members'].discard(username)
        self.user_events.pop(username, None)
        self.user_disciplines.pop(username, None)
        self.display_names.pop(username, None)
        self.profile_photos.pop(username, None)
        self.save_data()
        if username in self.clients:
            try:
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': '🗑️ Sua conta foi removida'
                })
                await self.clients[username].close()
            except Exception:
                pass
        return web.json_response({'success': True, 'message': 'Usuário removido'})

    async def handle_reset_password(self, request):
        data = await request.post()
        username = data.get('username', '')
        if username not in self.users:
            return web.json_response({'success': False, 'message': 'Não encontrado'})
        notified = False
        for uname in list(self.clients.keys()):
            if self.is_admin(uname):
                try:
                    await self.clients[uname].send_json({
                        'type': 'system',
                        'content': f'🔔 "{username}" solicitou alteração de senha'
                    })
                    notified = True
                except Exception:
                    pass
        if notified:
            return web.json_response({'success': True, 'message': 'Solicitação enviada'})
        return web.json_response({'success': False, 'message': 'Nenhum admin online'})

    # ============================================
    # ESTÁTICOS
    # ============================================
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

    async def handle_debug_clients(self, request):
        """DEBUG: mostra os clientes WebSocket conectados."""
        try:
            clients_info = []
            for u, ws in self.clients.items():
                clients_info.append({
                    'username': u,
                    'closed': getattr(ws, 'closed', None),
                    'id': id(ws)
                })
            return web.json_response({
                'total': len(self.clients),
                'users': list(self.clients.keys()),
                'clients': clients_info
            })
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_status(self, request):
        return web.json_response({
            'status': 'online',
            'clients': len(self.clients),
            'rooms': list(self.rooms.keys()),
            'users': len(self.users),
            'ollama': {'available': self.ollama_available, 'model': self.ollama_model},
            'orchestrator': {
                'available': self.orchestrator is not None,
                'model': 'refinedneuro/refinedtoolcallv5-3b'
            },
            'persistence': 'json'
        })

    # ============================================
    # LOGIN/REGISTER
    # ============================================
    async def handle_login_api(self, request):
        data = await request.post()
        username = data.get('username', '')
        password = data.get('password', '')
        if not username or not password:
            return web.json_response({'success': False, 'message': 'Credenciais inválidas'})
        if username not in self.users:
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        if self.users[username]['password'] != pw_hash:
            return web.json_response({'success': False, 'message': 'Senha incorreta'})
        return web.json_response({
            'success': True, 'message': 'Login',
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
            return web.json_response({'success': False, 'message': 'Obrigatório'})
        if len(username) < 3:
            return web.json_response({'success': False, 'message': 'Usuário mín 3'})
        if len(password) < 6:
            return web.json_response({'success': False, 'message': 'Senha mín 6'})
        if username in (self.ai_username, self.orchestrator_username):
            return web.json_response({'success': False, 'message': 'Nome reservado'})
        if username in self.users:
            return web.json_response({'success': False, 'message': 'Já existe'})

        self.users[username] = {
            'password': hashlib.sha256(password.encode()).hexdigest(),
            'is_admin': is_admin,
            'email': email,
            'created_at': datetime.now().isoformat()
        }
        if 'geral' in self.rooms:
            self.rooms['geral']['members'].add(username)
        self.save_data()
        return web.json_response({'success': True, 'message': 'Registrado', 'is_admin': is_admin})

    # ============================================
    # WEBSOCKET
    # ============================================
    async def _check_reminders_loop(self):
        """Loop que verifica lembretes a cada 60s."""
        while True:
            try:
                await asyncio.sleep(60)
                await self._check_reminders()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no verificador de lembretes: {e}")

    async def _check_reminders(self):
        """Verifica eventos do JSON e envia notificações."""
        from datetime import datetime, timedelta
        agora = datetime.now()

        if not hasattr(self, '_reminders_sent'):
            self._reminders_sent = set()

        for username, eventos in list(self.user_events.items()):
            for ev in eventos:
                if ev.get('done'):
                    continue
                reminder = int(ev.get('reminder', 0) or 0)
                if reminder <= 0:
                    continue
                try:
                    data_str = ev.get('date', '')
                    hora_str = ev.get('time', '') or '00:00'
                    if not data_str:
                        continue
                    dt_evento = datetime.strptime(f"{data_str} {hora_str}", "%Y-%m-%d %H:%M")
                except ValueError:
                    continue

                dt_notificar = dt_evento - timedelta(minutes=reminder)
                if dt_notificar <= agora < dt_evento:
                    chave = f"{username}:{ev.get('id')}"
                    if chave in self._reminders_sent:
                        continue
                    await self._send_reminder(username, ev, dt_evento)
                    self._reminders_sent.add(chave)
                    logger.info(f"⏰ Lembrete enviado: {username} → {ev.get('title')}")

    async def _send_reminder(self, username, evento, dt_evento):
        """Envia notificação de lembrete."""
        if username not in self.clients:
            return
        agora = datetime.now()
        delta = dt_evento - agora
        minutos = int(delta.total_seconds() / 60)
        if minutos < 1:
            tempo_str = "agora"
        elif minutos < 60:
            tempo_str = f"em {minutos} minuto{'s' if minutos != 1 else ''}"
        else:
            horas = minutos // 60
            tempo_str = f"em {horas} hora{'s' if horas != 1 else ''}"
        try:
            await self.clients[username].send_json({
                'type': 'reminder',
                'event': {
                    'id': evento.get('id'),
                    'title': evento.get('title'),
                    'date': evento.get('date'),
                    'time': evento.get('time'),
                    'discipline': evento.get('discipline', ''),
                    'description': evento.get('description', ''),
                    'time_until': tempo_str,
                },
                'message': f"⏰ Lembrete: '{evento.get('title')}' {tempo_str}"
            })
        except Exception as e:
            logger.error(f"Erro ao enviar lembrete: {e}")

    async def handle_websocket(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        username = request.query.get('username', 'anonimo')
        logger.info(f"=== CONEXÃO: {username} ===")

        if username not in self.users:
            await ws.close(1008, "Usuário desconhecido")
            return ws

        self.clients[username] = ws

        if 'geral' not in self.rooms:
            self.rooms['geral'] = {
                'members': set(), 'owner': 'admin',
                'created_at': datetime.now().isoformat(),
                'password': None, 'is_private': False
            }
            self.room_messages['geral'] = []
        self.rooms['geral']['members'].add(username)

        await self.send_history(ws, username, 'geral')

        display_name = self.display_names.get(username, username)
        await ws.send_json({'type': 'system', 'content': f'Bem-vindo {display_name}!'})

        if self.ollama_available:
            await ws.send_json({'type': 'system', 'content': '🤖 IA disponível! Use /ia ou /orq'})
        if self.orchestrator:
            await ws.send_json({'type': 'system', 'content': '🧠 Orquestrador disponível! Use /orq'})
        if self.is_admin(username):
            await ws.send_json({'type': 'system', 'content': '👑 Você é admin! Use /admin'})

        await self.send_user_events(username)
        await self.send_user_disciplines(username)

        await self.broadcast({'type': 'system', 'content': f'{username} entrou'})
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
            logger.error(f'Erro: {e}')
        finally:
            self.clients.pop(username, None)
            for room in self.rooms.values():
                room['members'].discard(username)
            await self.broadcast({'type': 'system', 'content': f'{username} saiu'})
            await self.send_user_list()
            logger.info(f"{username} desconectado")

        return ws

    async def process_text_message(self, username, text):
        lower = text.lower()

        # Orquestrador
        if lower.startswith('/orq '):
            await self._handle_orchestrator_request(username, text[5:].strip(), None, 'geral')
            return

        # IA direta
        if lower.startswith(('/ia', '@ia', '/ai', '@ai', '!ia', '!ai')):
            prompt = text
            for p in ['/ia ', '@ia ', '/ai ', '@ai ', '!ia ', '!ai ']:
                if lower.startswith(p):
                    prompt = text[len(p):]
                    break
            if prompt:
                await self.handle_ai_request(username, prompt, 'geral')
                return
        await self.save_and_broadcast_text(username, text, 'geral')

    # ============================================
    # PROCESSAMENTO
    # ============================================
    async def process_message(self, username, data):
        msg_type = data.get('type', '')
        room = data.get('room', 'geral')

        loose = ['create_room', 'join_room', 'get_rooms', 'get_users',
                 'create_private_room', 'join_private_room',
                 'add_event', 'delete_event', 'toggle_event', 'get_events',
                 'add_discipline', 'delete_discipline', 'get_disciplines',
                 'update_profile', 'logout']
        if msg_type not in loose:
            if room not in self.rooms:
                await self.send_error(username, 'Sala não existe')
                return
            if username not in self.rooms[room]['members']:
                await self.send_error(username, 'Você não é membro desta sala')
                return

        # AGENDA
        if msg_type == 'add_event':
            if username not in self.user_events:
                self.user_events[username] = []
            event = {
                'id': uuid.uuid4().hex[:8],
                'title': data.get('title', ''),
                'date': data.get('date', ''),
                'time': data.get('time', ''),
                'discipline': data.get('discipline', ''),
                'description': data.get('description', ''),
                'reminder': data.get('reminder', 0),
                'done': False,
                'created_at': datetime.now().isoformat()
            }
            self.user_events[username].append(event)
            self.save_data()
            await self.send_user_events(username)

        elif msg_type == 'delete_event':
            event_id = data.get('id', '')
            if username in self.user_events:
                self.user_events[username] = [
                    e for e in self.user_events[username] if e['id'] != event_id
                ]
            self.save_data()
            await self.send_user_events(username)

        elif msg_type == 'toggle_event':
            event_id = data.get('id', '')
            if username in self.user_events:
                for e in self.user_events[username]:
                    if e['id'] == event_id:
                        e['done'] = not e.get('done', False)
                        break
            self.save_data()
            await self.send_user_events(username)

        elif msg_type == 'get_events':
            await self.send_user_events(username)

        # DISCIPLINAS
        elif msg_type == 'add_discipline':
            if username not in self.user_disciplines:
                self.user_disciplines[username] = []
            disc = {
                'id': uuid.uuid4().hex[:8],
                'name': data.get('name', ''),
                'professor': data.get('professor', ''),
                'color': data.get('color', '#4facfe'),
                'schedule': data.get('schedule', ''),
                'created_at': datetime.now().isoformat()
            }
            self.user_disciplines[username].append(disc)
            self.save_data()
            await self.send_user_disciplines(username)

        elif msg_type == 'delete_discipline':
            disc_id = data.get('id', '')
            if username in self.user_disciplines:
                self.user_disciplines[username] = [
                    d for d in self.user_disciplines[username] if d['id'] != disc_id
                ]
            self.save_data()
            await self.send_user_disciplines(username)

        elif msg_type == 'get_disciplines':
            await self.send_user_disciplines(username)

        # GRUPOS FECHADOS
        elif msg_type == 'create_private_room':
            room_name = data.get('name', '').strip()
            password = data.get('password', '').strip()

            if not room_name or not password:
                await self.send_error(username, 'Nome e senha obrigatórios')
                return
            if len(password) < 4:
                await self.send_error(username, 'Senha mín 4 caracteres')
                return
            if room_name in self.rooms:
                await self.send_error(username, 'Já existe uma sala com esse nome')
                return

            self.rooms[room_name] = {
                'members': {username},
                'owner': username,
                'created_at': datetime.now().isoformat(),
                'password': password,
                'is_private': True
            }
            self.room_messages[room_name] = []
            self.save_data()
            await self.send_room_list()
            await self.clients[username].send_json({
                'type': 'system',
                'content': f'🔒 Grupo "{room_name}" criado! Compartilhe a senha.'
            })

        elif msg_type == 'join_private_room':
            room_name = data.get('name', '').strip()
            password = data.get('password', '').strip()

            if room_name not in self.rooms:
                await self.send_error(username, 'Grupo não encontrado')
                return

            room_data = self.rooms[room_name]
            if not room_data.get('is_private'):
                if username not in room_data['members']:
                    room_data['members'].add(username)
                    self.save_data()
                    await self.send_history(self.clients[username], username, room_name)
                    await self.send_room_list()
                return

            if room_data.get('password') != password:
                await self.send_error(username, '❌ Senha incorreta')
                return

            if username in room_data['members']:
                await self.send_history(self.clients[username], username, room_name)
                return

            room_data['members'].add(username)
            self.save_data()
            await self.send_history(self.clients[username], username, room_name)
            await self.send_room_list()
            await self.broadcast({
                'type': 'system',
                'content': f'🔓 {username} entrou no grupo'
            }, room_name)

        elif msg_type == 'add_room_member':
            if self.rooms.get(room, {}).get('owner') != username:
                await self.send_error(username, 'Apenas o criador pode adicionar')
                return
            target = data.get('target', '')
            if not target or target == username:
                return
            if target not in self.users:
                await self.send_error(username, f'Usuário "{target}" não existe')
                return
            if target in self.rooms[room]['members']:
                await self.send_error(username, f'{target} já é membro')
                return
            self.rooms[room]['members'].add(target)
            self.save_data()
            await self.send_room_list()
            if target in self.clients:
                try:
                    await self.clients[target].send_json({
                        'type': 'system',
                        'content': f'✅ Você foi adicionado ao grupo "{room}"'
                    })
                except Exception:
                    pass

        # DELETAR
        elif msg_type == 'delete':
            msg_id = data.get('id', '')
            if msg_id in self.message_ids:
                info = self.message_ids[msg_id]
                if info['username'] == username:
                    r = info['room']
                    self.room_messages[r] = [
                        m for m in self.room_messages.get(r, [])
                        if m.get('id') != msg_id
                    ]
                    if msg_id in self.file_messages:
                        try:
                            fp = self.file_messages[msg_id]
                            if os.path.exists(fp):
                                os.remove(fp)
                        except Exception:
                            pass
                        del self.file_messages[msg_id]
                    del self.message_ids[msg_id]
                    self.save_data()
                    await self.broadcast({
                        'type': 'message_deleted',
                        'id': msg_id,
                        'room': r
                    }, r)
                else:
                    await self.send_error(username, 'Você só pode apagar suas mensagens')
            else:
                await self.send_error(username, 'Mensagem não encontrada')

        elif msg_type == 'delete_file':
            msg_id = data.get('msg_id', '')
            if msg_id in self.message_ids:
                info = self.message_ids[msg_id]
                if info['username'] == username:
                    r = info['room']
                    self.room_messages[r] = [
                        m for m in self.room_messages.get(r, [])
                        if m.get('id') != msg_id
                    ]
                    if msg_id in self.file_messages:
                        try:
                            fp = self.file_messages[msg_id]
                            if os.path.exists(fp):
                                os.remove(fp)
                        except Exception:
                            pass
                        del self.file_messages[msg_id]
                    del self.message_ids[msg_id]
                    self.save_data()
                    await self.broadcast({
                        'type': 'file_deleted',
                        'id': msg_id,
                        'room': r
                    }, r)
                else:
                    await self.send_error(username, 'Sem permissão')

        elif msg_type == 'clear_room':
            if self.rooms[room]['owner'] != username:
                await self.send_error(username, 'Apenas o criador pode limpar')
                return
            hours = int(data.get('clear_older_than', 0) or 0)
            if hours > 0:
                cutoff = datetime.now() - timedelta(hours=hours)
                before = len(self.room_messages[room])
                self.room_messages[room] = [
                    m for m in self.room_messages[room]
                    if datetime.strptime(m['timestamp'], '%H:%M:%S').replace(
                        year=datetime.now().year, month=datetime.now().month, day=datetime.now().day
                    ) > cutoff
                ]
                removed = before - len(self.room_messages[room])
            else:
                removed = len(self.room_messages[room])
                self.room_messages[room] = []
            self.save_data()
            await self.broadcast({
                'type': 'system',
                'content': f'🧹 {removed} mensagens removidas'
            }, room)

        # ============================================
        # MENSAGEM NORMAL (+ ORQUESTRADOR)
        # ============================================
        elif msg_type == 'message':
            content = data.get('content', '')
            if not content:
                return
            lower = content.lower()

            # Comando /orq → Orquestrador
            if lower.startswith('/orq '):
                pergunta = content[5:].strip()
                pasta = data.get('pasta', None)
                await self._handle_orchestrator_request(username, pergunta, pasta, room)
                return

            # Comando /ia → IA direta
            if lower.startswith(('/ia', '@ia', '/ai', '@ai', '!ia', '!ai')):
                prompt = content
                for p in ['/ia ', '@ia ', '/ai ', '@ai ', '!ia ', '!ai ']:
                    if lower.startswith(p):
                        prompt = content[len(p):]
                        break
                if prompt:
                    await self.handle_ai_request(username, prompt, room)
                return

            await self.save_and_broadcast_text(username, content, room)

        elif msg_type == 'file':
            await self.handle_file_upload(username, data)

        elif msg_type == 'ai_request':
            prompt = data.get('prompt', '')
            model = data.get('model', self.ollama_model)
            if model != self.ollama_model:
                self.ollama_model = model
            if prompt:
                await self.handle_ai_request(username, prompt, room)

        # LISTAS
        elif msg_type == 'get_users':
            await self.send_user_list()

        elif msg_type == 'get_rooms':
            await self.send_room_list()

        elif msg_type == 'get_history':
            await self.send_history(self.clients[username], username, room)

        elif msg_type == 'typing':
            await self.broadcast({
                'type': 'typing',
                'from': username,
                'is_typing': data.get('is_typing', False)
            }, room)

        # SALA PÚBLICA
        elif msg_type == 'create_room':
            room_name = data.get('name', '').strip()
            if not room_name or room_name in self.rooms:
                await self.send_error(username, 'Sala já existe ou nome inválido')
                return
            self.rooms[room_name] = {
                'members': {username},
                'owner': username,
                'created_at': datetime.now().isoformat(),
                'password': None,
                'is_private': False
            }
            self.room_messages[room_name] = []
            self.save_data()
            await self.broadcast({
                'type': 'system',
                'content': f'🏠 Sala "{room_name}" criada por {username}'
            })
            await self.send_room_list()

        elif msg_type == 'join_room':
            room_name = data.get('room', '')
            if room_name not in self.rooms:
                await self.send_error(username, 'Sala não existe')
                return
            if self.rooms[room_name].get('is_private') and username not in self.rooms[room_name]['members']:
                await self.send_error(username, 'Sala privada — use a senha')
                return
            if username not in self.rooms[room_name]['members']:
                self.rooms[room_name]['members'].add(username)
                self.save_data()
                await self.broadcast({
                    'type': 'system',
                    'content': f'{username} entrou na sala'
                }, room_name)
                await self.send_room_list()
            await self.send_history(self.clients[username], username, room_name)

        # PRIVADO
        elif msg_type == 'private':
            to_user = data.get('to', '')
            content = data.get('content', '')
            if not to_user or not content:
                return
            msg_id = uuid.uuid4().hex[:8]
            msg = {
                'id': msg_id,
                'type': 'private',
                'from': username,
                'to': to_user,
                'content': content,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            }
            key = '_'.join(sorted([username, to_user]))
            if key not in self.private_messages:
                self.private_messages[key] = []
            self.private_messages[key].append(msg)
            if len(self.private_messages[key]) > 500:
                self.private_messages[key] = self.private_messages[key][-500:]
            self.save_data()
            if to_user in self.clients:
                try:
                    await self.clients[to_user].send_json(msg)
                except Exception:
                    pass
            try:
                await self.clients[username].send_json({**msg, 'sent': True})
            except Exception:
                pass

        # EXPULSAR / DELETAR
        elif msg_type == 'kick_member':
            if self.rooms[room]['owner'] != username:
                await self.send_error(username, 'Apenas o criador pode expulsar')
                return
            target = data.get('target', '')
            if target in self.rooms[room]['members'] and target != username:
                self.rooms[room]['members'].discard(target)
                self.save_data()
                await self.broadcast({
                    'type': 'system',
                    'content': f'🚫 {target} foi expulso'
                }, room)
                if target in self.clients:
                    try:
                        await self.clients[target].send_json({
                            'type': 'system',
                            'content': f'🚫 Você foi expulso de "{room}"'
                        })
                    except Exception:
                        pass
                await self.send_room_list()

        elif msg_type == 'delete_room':
            if self.rooms[room]['owner'] != username:
                await self.send_error(username, 'Apenas o criador pode apagar')
                return
            for m in list(self.rooms[room]['members']):
                if m in self.clients:
                    try:
                        await self.clients[m].send_json({
                            'type': 'system',
                            'content': f'🗑️ A sala "{room}" foi removida'
                        })
                    except Exception:
                        pass
            del self.rooms[room]
            self.room_messages.pop(room, None)
            self.save_data()
            await self.send_room_list()

        # PERFIL
        elif msg_type == 'update_profile':
            display_name = data.get('display_name', '').strip()
            if display_name:
                self.display_names[username] = display_name
                self.save_data()
                await self.send_user_list()

        elif msg_type == 'change_password':
            new_pwd = data.get('new_password', '')
            if len(new_pwd) >= 6:
                self.users[username]['password'] = hashlib.sha256(new_pwd.encode()).hexdigest()
                self.save_data()
                try:
                    await self.clients[username].send_json({
                        'type': 'system',
                        'content': '🔐 Senha alterada com sucesso'
                    })
                except Exception:
                    pass
            else:
                await self.send_error(username, 'Senha muito curta')

        elif msg_type == 'get_private_history':
            other = data.get('other', '').strip()
            if not other:
                return
            key = '_'.join(sorted([username, other]))
            history = self.private_messages.get(key, [])
            try:
                await self.clients[username].send_json({
                    'type': 'private_history',
                    'with': other,
                    'messages': history[-100:]
                })
            except Exception:
                pass

        elif msg_type == 'logout':
            if username in self.clients:
                await self.clients[username].close()

    # ============================================
    # ORQUESTRADOR
    # ============================================
    async def handle_orq_upload(self, request):
        """Recebe arquivo (PDF, texto, áudio, vídeo, imagem) e analisa com o orquestrador."""
        room = 'geral'
        try:
            data = await request.post()
            arquivo = data.get('file')
            pergunta = (data.get('question') or '').strip()
            room = data.get('room', 'geral')
            username = data.get('username', '')

            if not arquivo or not hasattr(arquivo, 'filename'):
                return web.json_response({'success': False, 'message': 'Arquivo não enviado'})
            if not pergunta:
                return web.json_response({'success': False, 'message': 'Digite uma pergunta'})
            if not username or username not in self.users:
                return web.json_response({'success': False, 'message': 'Usuário inválido'})
            if not self.orchestrator:
                return web.json_response({'success': False, 'message': 'Orquestrador indisponível'})

            ext = Path(arquivo.filename).suffix.lower()
            tmp_name = f"orq_{uuid.uuid4().hex[:8]}{ext}"
            tmp_path = Path('uploads') / tmp_name

            with open(tmp_path, 'wb') as f:
                f.write(arquivo.file.read())

            logger.info(f"📎 Upload para orquestrador: {arquivo.filename} ({tmp_path.stat().st_size} bytes, tipo: {ext})")

            conteudo = await self._extract_content_from_file(tmp_path, pergunta)

            if not conteudo and ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
                return web.json_response({'success': False, 'message': f'Não foi possível extrair conteúdo de {ext}'})

            await self.broadcast({
                'type': 'typing', 'from': self.orchestrator_username, 'is_typing': True
            }, room)

            try:
                if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
                    resposta = await self.orchestrator.processar_imagem(
                        imagem_path=str(tmp_path), pergunta=pergunta, nome_arquivo=arquivo.filename
                    )
                else:
                    resposta = await self.orchestrator.processar_texto_direto(
                        texto=conteudo, pergunta=pergunta, nome_arquivo=arquivo.filename
                    )
            finally:
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

            # Salva no JSON
            msg_id = uuid.uuid4().hex[:8]
            msg = {
                'id': msg_id,
                'type': 'message',
                'from': self.orchestrator_username,
                'content': resposta,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'room': room,
                'attachment': arquivo.filename
            }
            self.message_ids[msg_id] = {'username': self.orchestrator_username, 'room': room}
            if room not in self.room_messages:
                self.room_messages[room] = []
            self.room_messages[room].append(msg)
            self.save_data()
            await self.broadcast(msg, room)

            return web.json_response({
                'success': True,
                'response': resposta,
                'filename': arquivo.filename,
                'tipo': ext
            })

        except Exception as e:
            logger.error(f"Erro no upload para orquestrador: {e}")
            return web.json_response({'success': False, 'message': str(e)})
        finally:
            try:
                await self.broadcast({
                    'type': 'typing', 'from': self.orchestrator_username, 'is_typing': False
                }, room)
            except Exception:
                pass

    async def _extract_content_from_file(self, path: Path, pergunta: str = "") -> str:
        """Extrai conteúdo de arquivo (texto, áudio, imagem)."""
        try:
            ext = path.suffix.lower()
            if ext in ('.md', '.txt', '.csv', '.log', '.json', '.xml', '.html', '.py', '.js', '.css'):
                return path.read_text(encoding='utf-8', errors='ignore')
            elif ext == '.pdf':
                try:
                    import pymupdf4llm
                    return pymupdf4llm.to_markdown(str(path))
                except ImportError:
                    try:
                        import pypdf
                        reader = pypdf.PdfReader(str(path))
                        return "\n".join((p.extract_text() or '') for p in reader.pages)
                    except ImportError:
                        return ""
            elif ext in ('.docx', '.doc'):
                try:
                    import docx
                    doc = docx.Document(str(path))
                    return "\n".join(p.text for p in doc.paragraphs)
                except ImportError:
                    return ""
            elif ext in ('.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.wma',
                         '.mp4', '.webm', '.mkv', '.mov', '.avi'):
                return await self._transcribe_audio_video(path)
            elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
                return f"[IMAGEM:{path}]"
        except Exception as e:
            logger.error(f"Erro ao extrair conteúdo: {e}")
        return ""

    async def _transcribe_audio_video(self, path: Path) -> str:
        """Transcreve áudio/vídeo com faster-whisper."""
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.error("faster-whisper não instalado")
            return ""
        try:
            logger.info(f"🎙️ Transcrevendo: {path.name}")
            model = WhisperModel("small", device="cpu", compute_type="int8")
            segments, info = model.transcribe(str(path), language="pt", vad_filter=True, beam_size=5)
            texto = " ".join(seg.text.strip() for seg in segments)
            logger.info(f"✅ Transcrição concluída ({len(texto)} chars)")
            return texto
        except Exception as e:
            logger.error(f"Erro na transcrição: {e}")
            return ""

    async def _handle_orchestrator_request(self, username, pergunta, pasta, room):
        """Processa uma requisição para o orquestrador multi-agente."""
        if not pergunta:
            await self.send_error(username, 'Digite sua pergunta após /orq')
            return

        if not self.orchestrator:
            await self.send_error(username, '❌ Orquestrador não disponível (orchestrator.py ausente)')
            return

        logger.info(f"🧠 Orquestrador requisitado por {username}: {pergunta[:80]} (pasta={pasta})")

        # Indicador "digitando"
        await self.broadcast({
            'type': 'typing',
            'from': self.orchestrator_username,
            'is_typing': True
        }, room)

        try:
            resposta = await self.orchestrator.processar(pergunta, pasta)
            content_final = resposta

            # Salva no JSON e envia
            msg_id = uuid.uuid4().hex[:8]
            msg = {
                'id': msg_id,
                'type': 'message',
                'from': self.orchestrator_username,
                'content': content_final,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'room': room
            }
            self.message_ids[msg_id] = {'username': self.orchestrator_username, 'room': room}
            if room not in self.room_messages:
                self.room_messages[room] = []
            self.room_messages[room].append(msg)
            self.save_data()
            await self.broadcast(msg, room)

        except Exception as e:
            logger.error(f"❌ Erro no orquestrador: {e}")
            await self.send_error(username, f'Erro no orquestrador: {str(e)}')
        finally:
            await self.broadcast({
                'type': 'typing',
                'from': self.orchestrator_username,
                'is_typing': False
            }, room)

    # ============================================
    # HELPERS
    # ============================================
    async def save_and_broadcast_text(self, username, content, room):
        msg_id = uuid.uuid4().hex[:8]
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
        if len(self.room_messages[room]) > 500:
            self.room_messages[room] = self.room_messages[room][-500:]
        self.save_data()
        await self.broadcast(msg, room)

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
        disk_path = f"uploads/{unique_name}"

        if file_data.startswith('data:'):
            file_data = file_data.split(',', 1)[1]

        try:
            with open(disk_path, 'wb') as f:
                f.write(base64.b64decode(file_data))
            size = os.path.getsize(disk_path)

            msg_id = uuid.uuid4().hex[:8]
            msg = {
                'id': msg_id,
                'type': 'file',
                'from': username,
                'file_name': filename,
                'file_path': f'/uploads/{unique_name}',
                'file_size': size,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'room': room
            }
            self.message_ids[msg_id] = {'username': username, 'room': room}
            self.file_messages[msg_id] = disk_path
            if room not in self.room_messages:
                self.room_messages[room] = []
            self.room_messages[room].append(msg)
            self.save_data()
            await self.broadcast(msg, room)
            logger.info(f"📎 Arquivo: {filename} por {username}")
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo: {e}")
            await self.send_error(username, 'Erro ao enviar arquivo')

    async def handle_ai_request(self, username, prompt, room):
        logger.info(f"🤖 IA: {username} → {prompt[:80]}")
        await self.broadcast({'type': 'typing', 'from': self.ai_username, 'is_typing': True}, room)

        system = 'Você é um assistente útil chamado "IA DeepCord". Responda de forma clara e concisa.'
        response = await self.call_ollama(prompt, system)

        await self.broadcast({'type': 'typing', 'from': self.ai_username, 'is_typing': False}, room)

        if response:
            content = f'🤖 {response}'
            msg_id = uuid.uuid4().hex[:8]
            msg = {
                'id': msg_id,
                'type': 'message',
                'from': self.ai_username,
                'content': content,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'room': room
            }
            self.message_ids[msg_id] = {'username': self.ai_username, 'room': room}
            if room not in self.room_messages:
                self.room_messages[room] = []
            self.room_messages[room].append(msg)
            self.save_data()
            await self.broadcast(msg, room)
        else:
            if username in self.clients:
                try:
                    await self.clients[username].send_json({
                        'type': 'system',
                        'content': '❌ IA indisponível'
                    })
                except Exception:
                    pass

    async def send_history(self, ws, username, room):
        messages = self.room_messages.get(room, [])[-50:]
        owner = self.rooms.get(room, {}).get('owner', '')
        try:
            await ws.send_json({
                'type': 'history',
                'room': room,
                'messages': messages,
                'owner': owner,
                'ai_username': self.ai_username
            })
        except Exception as e:
            logger.error(f"Erro histórico: {e}")

    async def send_room_list(self):
        rooms_info = []
        for rname, rdata in self.rooms.items():
            rooms_info.append({
                'name': rname,
                'owner': rdata.get('owner', ''),
                'members': list(rdata.get('members', set())),
                'member_count': len(rdata.get('members', set())),
                'is_private': rdata.get('is_private', False)
            })
        message = {'type': 'room_list', 'rooms': rooms_info}
        data = json.dumps(message)
        disconnected = []
        for uname, ws in list(self.clients.items()):
            try:
                await ws.send_str(data)
            except Exception:
                disconnected.append(uname)
        for u in disconnected:
            self.clients.pop(u, None)

    async def send_user_list(self):
        users = list(self.clients.keys())
        message = {
            'type': 'user_list',
            'users': users,
            'display_names': self.display_names,
            'ai_user': self.ai_username if self.ollama_available else None
        }
        data = json.dumps(message)
        disconnected = []
        for uname, ws in list(self.clients.items()):
            try:
                await ws.send_str(data)
            except Exception:
                disconnected.append(uname)
        for u in disconnected:
            self.clients.pop(u, None)

    async def send_user_events(self, username):
        if username in self.clients:
            try:
                await self.clients[username].send_json({
                    'type': 'user_events',
                    'events': self.user_events.get(username, [])
                })
            except Exception:
                pass

    async def send_user_disciplines(self, username):
        if username in self.clients:
            try:
                await self.clients[username].send_json({
                    'type': 'user_disciplines',
                    'disciplines': self.user_disciplines.get(username, [])
                })
            except Exception:
                pass

    async def send_error(self, username, message):
        if username in self.clients:
            try:
                await self.clients[username].send_json({'type': 'error', 'message': message})
            except Exception:
                pass

    async def broadcast(self, message, room='geral'):
        """Envia para TODOS os clientes conectados."""
        data = json.dumps(message)
        enviados = 0
        falhas = 0
        disconnected = []
        for username, ws in list(self.clients.items()):
            try:
                await ws.send_str(data)
                enviados += 1
            except Exception as e:
                logger.error(f"❌ Erro ao enviar para '{username}': {e}")
                falhas += 1
                disconnected.append(username)
        for u in disconnected:
            self.clients.pop(u, None)
        logger.info(f"⏱️ broadcast: clientes={len(self.clients)} | enviados={enviados} | falhas={falhas}")


    async def run(self, host='0.0.0.0', port=8081):
        await self.check_ollama()
        
        # Inicia verificador de lembretes
        self.reminder_task = asyncio.create_task(self._check_reminders_loop())
        logger.info("⏰ Verificador de lembretes iniciado")
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        print("\n" + "=" * 60)
        print("  DeepCord — JSON Edition + Orquestrador")
        print("=" * 60)
        print(f"📍 http://localhost:{port}")
        print(f"👤 Admin: admin / admin123")
        print(f"👤 Demo:  demo / demo123")
        print(f"🗄️  Dados: {self.data_file}")
        print(f"🤖 Ollama: {'✅' if self.ollama_available else '❌'}")
        print(f"🧠 Orquestrador: {'✅' if self.orchestrator else '❌'}")
        print(f"📚 Base de conhecimento: ./conhecimento/")
        print("=" * 60)
        print("\n📝 COMANDOS NO CHAT:")
        print("  /ia <pergunta>   — IA direta (modelo único)")
        print("  /orq <pergunta>  — Orquestrador multi-agente + RAG")
        print("=" * 60 + "\n")

        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Salvando dados antes de sair...")
            self.save_data()
            await runner.cleanup()


if __name__ == '__main__':
    server = ChatServer()
    asyncio.run(server.run())
