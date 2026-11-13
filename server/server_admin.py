#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import base64
import os
import uuid
import aiohttp
import secrets
from datetime import datetime
from aiohttp import web, WSMsgType
from pathlib import Path

from database import Database
from orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ChatServer:
    def __init__(self):
        # WebSocket ativos (em memória — não podem ir para o BD)
        self.clients = {}
        # Sessões admin HTTP (em memória)
        self.sessions = {}

        # IA
        self.ollama_host = "http://localhost:11434"
        self.ollama_model = "phi3"
        self.ai_username = "🤖 IA DeepCord"
        self.orchestrator_username = "🧠 Orquestrador"
        self.ollama_available = False

        # Banco de dados
        self.db = Database()
        if not self.db.connect():
            logger.error("❌ Falha ao conectar ao MySQL.")
            raise SystemExit(1)

        # Garantir usuários IA e Orquestrador
        self.db.ensure_user_exists(self.ai_username, 'ai@chat.com', 'IA DeepCord', False)
        self.db.ensure_user_exists(self.orchestrator_username, 'orq@chat.com', 'Orquestrador DeepCord', False)

        # Orquestrador multi-agente + RAG
        self.orchestrator = Orchestrator(
            ollama_host=self.ollama_host,
            model="refinedneuro/refinedtoolcallv5-3b",
            knowledge_base="conhecimento"
        )
        os.makedirs('conhecimento', exist_ok=True)
        logger.info("🧠 Orquestrador inicializado")

        # Rotas
        self.app = web.Application(client_max_size=50 * 1024 * 1024)
        self.setup_routes()
        os.makedirs('uploads', exist_ok=True)

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
        self.app.router.add_get('/api/debug/clients', self.handle_debug_clients)
        self.app.router.add_get('/api/users', self.handle_get_users)
        self.app.router.add_get('/api/rooms', self.handle_get_rooms)
        self.app.router.add_get('/api/rooms/public', self.handle_get_rooms_public)
        self.app.router.add_post('/api/admin/rooms', self.handle_admin_rooms)
        self.app.router.add_post('/api/admin/rooms/delete', self.handle_admin_delete_room)
        self.app.router.add_get('/api/ollama/models', self.handle_ollama_models)
        self.app.router.add_get('/api/folders', self.handle_get_folders)
        self.app.router.add_get('/api/materials', self.handle_get_materials)
        self.app.router.add_get('/api/materials/file/{path:.*}', self.handle_get_material_file)
        self.app.router.add_post('/api/orq/upload', self.handle_orq_upload)
        self.app.router.add_get('/uploads/{filename}', self.handle_upload)
        self.app.router.add_post('/api/login', self.handle_login_api)
        self.app.router.add_post('/api/register', self.handle_register)
        self.app.router.add_post('/api/admin/users', self.handle_admin_users)
        self.app.router.add_post('/api/admin/password', self.handle_admin_password)
        self.app.router.add_post('/api/admin/delete', self.handle_admin_delete)
        self.app.router.add_post('/api/reset-password', self.handle_reset_password)
        self.app.router.add_get('/{path}', self.handle_static)

    # ============================================
    # OLLAMA
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
    # MATERIAIS (acesso aos arquivos da pasta conhecimento/)
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
                    if not f.is_file():
                        continue
                    if f.suffix.lower() not in supported_exts:
                        continue

                    # Caminho relativo (seguro, sem ..)
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

            return web.json_response({
                'success': True,
                'materials': materials
            })
        except Exception as e:
            logger.error(f"Erro ao listar materiais: {e}")
            return web.json_response({
                'success': False,
                'materials': [],
                'message': str(e)
            })
    # ============================================
    # UPLOAD PARA O ORQUESTRADOR
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

            if not username or not self.db.user_exists(username):
                return web.json_response({'success': False, 'message': 'Usuário inválido'})

            if not self.orchestrator:
                return web.json_response({'success': False, 'message': 'Orquestrador indisponível'})

            # Salva o arquivo temporariamente
            ext = Path(arquivo.filename).suffix.lower()
            tmp_name = f"orq_{uuid.uuid4().hex[:8]}{ext}"
            tmp_path = Path('uploads') / tmp_name

            with open(tmp_path, 'wb') as f:
                f.write(arquivo.file.read())

            logger.info(f"📎 Upload para orquestrador: {arquivo.filename} ({tmp_path.stat().st_size} bytes, tipo: {ext})")

            # Extrai conteúdo (texto, áudio, imagem)
            conteudo = await self._extract_content_from_file(tmp_path, pergunta)

            # Para imagem, não precisa ter conteudo — o modelo de visão cuida
            if not conteudo and ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
                return web.json_response({
                    'success': False,
                    'message': f'Não foi possível extrair conteúdo do arquivo {ext}'
                })

            # Envia para o orquestrador
            await self.broadcast({
                'type': 'typing',
                'from': self.orchestrator_username,
                'is_typing': True
            }, room)

            try:
                if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
                    # Imagem: usa modelo de visão
                    resposta = await self.orchestrator.processar_imagem(
                        imagem_path=str(tmp_path),
                        pergunta=pergunta,
                        nome_arquivo=arquivo.filename
                    )
                else:
                    # PDF/texto/áudio/vídeo: texto já extraído
                    resposta = await self.orchestrator.processar_texto_direto(
                        texto=conteudo,
                        pergunta=pergunta,
                        nome_arquivo=arquivo.filename
                    )
            finally:
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

            # Salva no banco (MySQL) e envia
            msg_id = self.db.save_message(
                self.orchestrator_username, None, room, resposta
            )

            if msg_id:
                msg = {
                    'id': str(msg_id),
                    'type': 'message',
                    'from': self.orchestrator_username,
                    'content': resposta,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'room': room,
                    'attachment': arquivo.filename
                }
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
                    'type': 'typing',
                    'from': self.orchestrator_username,
                    'is_typing': False
                }, room)
            except Exception:
                pass

    async def _extract_content_from_file(self, path: Path, pergunta: str = "") -> str:
        """Extrai conteúdo de um arquivo baseado na extensão (texto, áudio, imagem)."""
        try:
            ext = path.suffix.lower()

            # TEXTO E DOCUMENTOS
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

            # ÁUDIO E VÍDEO → TRANSCRIÇÃO
            elif ext in ('.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.wma',
                         '.mp4', '.webm', '.mkv', '.mov', '.avi'):
                return await self._transcribe_audio_video(path)

            # IMAGEM → placeholder (o orquestrador usa modelo de visão)
            elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
                return f"[IMAGEM:{path}]"

        except Exception as e:
            logger.error(f"Erro ao extrair conteúdo: {e}")
        return ""

    async def _transcribe_audio_video(self, path: Path) -> str:
        """Transcreve áudio ou vídeo usando faster-whisper."""
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.error("faster-whisper não instalado. Rode: pip install faster-whisper")
            return ""

        try:
            logger.info(f"🎙️ Transcrevendo: {path.name}")
            model = WhisperModel("small", device="cpu", compute_type="int8")
            segments, info = model.transcribe(
                str(path),
                language="pt",
                vad_filter=True,
                beam_size=5
            )
            texto = " ".join(seg.text.strip() for seg in segments)
            logger.info(f"✅ Transcrição concluída ({len(texto)} chars)")
            return texto
        except Exception as e:
            logger.error(f"Erro na transcrição: {e}")
            return ""

    async def handle_get_material_file(self, request):
        """Serve um arquivo da pasta conhecimento/ para download/visualização."""
        try:
            rel_path = request.match_info.get('path', '')

            # Segurança: bloqueia path traversal
            if not rel_path or '..' in rel_path:
                return web.Response(status=400, text='Caminho inválido')

            base_path = Path('conhecimento').resolve()
            file_path = (base_path / rel_path).resolve()

            # Garante que o arquivo está dentro de conhecimento/
            if not str(file_path).startswith(str(base_path)):
                return web.Response(status=403, text='Acesso negado')

            if not file_path.exists() or not file_path.is_file():
                return web.Response(status=404, text='Arquivo não encontrado')

            # Define Content-Type e força download quando for seguro
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
    # ADMIN - AUTH
    # ============================================
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
        if not self.db.user_exists(username):
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'}, status=401)
        if not self.db.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        if not self.db.authenticate_user(username, password):
            return web.json_response({'success': False, 'message': 'Senha incorreta'}, status=401)

        token = secrets.token_hex(32)
        self.sessions[token] = username
        response = web.json_response({'success': True, 'message': 'Login realizado', 'username': username})
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
        if username and self.db.is_admin(username):
            return web.json_response({'authenticated': True, 'username': username})
        return web.json_response({'authenticated': False}, status=401)

    async def handle_admin(self, request):
        username = self.get_session_user(request)
        if not username or not self.db.is_admin(username):
            return web.Response(status=302, headers={'Location': '/admin/login'})
        return web.FileResponse('public/admin.html')

    # ============================================
    # ADMIN - API
    # ============================================
    async def handle_get_users(self, request):
        username = self.get_session_user(request)
        if not username or not self.db.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        users = self.db.get_all_users(exclude=[self.ai_username, self.orchestrator_username])
        return web.json_response({'success': True, 'users': users})

    async def handle_get_rooms(self, request):
        username = self.get_session_user(request)
        if not username or not self.db.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        rooms = self.db.get_all_rooms()
        # Enriquecer com message_count
        for r in rooms:
            msgs = self.db.get_room_messages(r['name'], limit=10000)
            r['message_count'] = len(msgs)
        return web.json_response({'success': True, 'rooms': rooms})


    async def handle_get_rooms_public(self, request):
        """Lista pública de salas (sem exigir admin). Usada pelo index.html e chat.html."""
        try:
            rooms = self.db.get_all_rooms()
            for r in rooms:
                r['members'] = self.db.get_room_members(r['name'])
                try:
                    r['message_count'] = len(self.db.get_room_messages(r['name'], limit=10000))
                except Exception:
                    r['message_count'] = 0
            return web.json_response({'success': True, 'rooms': rooms})
        except Exception as e:
            logger.error(f"Erro ao listar salas públicas: {e}")
            return web.json_response({'success': False, 'rooms': [], 'message': str(e)})

    async def handle_admin_rooms(self, request):
        username = self.get_session_user(request)
        if not username or not self.db.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        data = await request.post()
        action = data.get('action', '')
        room_name = data.get('name', '')
        if action == 'create':
            if not room_name or self.db.get_room_details(room_name):
                return web.json_response({'success': False, 'message': 'Sala já existe'})
            self.db.create_room(room_name, username, is_private=False)
            await self.broadcast({'type': 'system', 'content': f'🏠 Sala "{room_name}" criada pelo admin'})
            await self.send_room_list()
            return web.json_response({'success': True, 'message': f'Sala "{room_name}" criada'})
        return web.json_response({'success': False, 'message': 'Ação inválida'})

    async def handle_admin_delete_room(self, request):
        username = self.get_session_user(request)
        if not username or not self.db.is_admin(username):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        data = await request.post()
        room_name = data.get('name', '')
        if not self.db.get_room_details(room_name):
            return web.json_response({'success': False, 'message': 'Sala não encontrada'})
        if room_name == 'geral':
            return web.json_response({'success': False, 'message': 'Não é possível apagar a sala geral'})
        members = self.db.get_room_members(room_name)
        self.db.delete_room(room_name)
        await self.send_room_list()
        for m in members:
            if m in self.clients:
                try:
                    await self.clients[m].send_json({'type': 'system', 'content': f'🗑️ A sala "{room_name}" foi removida'})
                except Exception:
                    pass
        return web.json_response({'success': True, 'message': 'Sala removida'})

    async def handle_admin_users(self, request):
        admin_user = self.get_session_user(request)
        if not admin_user or not self.db.is_admin(admin_user):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        data = await request.post()
        action = data.get('action', '')
        username = data.get('username', '')

        if action == 'list':
            return web.json_response({'success': True, 'users': self.db.get_all_users(exclude=[self.ai_username, self.orchestrator_username])})
        elif action == 'create':
            password = data.get('password', '')
            email = data.get('email', '')
            is_admin = data.get('is_admin', 'false') == 'true'
            if not password or len(password) < 6:
                return web.json_response({'success': False, 'message': 'Senha mínimo 6 caracteres'})
            if not self.db.register_user(username, password, email, is_admin=is_admin):
                return web.json_response({'success': False, 'message': 'Usuário já existe'})
            return web.json_response({'success': True, 'message': 'Usuário criado'})
        return web.json_response({'success': False, 'message': 'Ação inválida'})

    async def handle_admin_password(self, request):
        admin_user = self.get_session_user(request)
        if not admin_user or not self.db.is_admin(admin_user):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        data = await request.post()
        username = data.get('username', '')
        new_password = data.get('new_password', '')
        if not self.db.user_exists(username):
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        if len(new_password) < 6:
            return web.json_response({'success': False, 'message': 'Senha mínimo 6 caracteres'})
        self.db.update_password_by_username(username, new_password)
        if username in self.clients:
            try:
                await self.clients[username].send_json({'type': 'system', 'content': '🔐 Sua senha foi alterada'})
            except Exception:
                pass
        return web.json_response({'success': True, 'message': 'Senha alterada'})

    async def handle_admin_delete(self, request):
        admin_user = self.get_session_user(request)
        if not admin_user or not self.db.is_admin(admin_user):
            return web.json_response({'success': False, 'message': 'Acesso negado'}, status=403)
        data = await request.post()
        username = data.get('username', '')
        if not self.db.user_exists(username):
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        if username == admin_user or username == 'admin':
            return web.json_response({'success': False, 'message': 'Não é possível apagar este usuário'})
        self.db.delete_user(username)
        if username in self.clients:
            try:
                await self.clients[username].send_json({'type': 'system', 'content': '🗑️ Conta removida'})
                await self.clients[username].close()
            except Exception:
                pass
        return web.json_response({'success': True, 'message': 'Usuário removido'})

    async def handle_reset_password(self, request):
        data = await request.post()
        username = data.get('username', '')
        if not self.db.user_exists(username):
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        notified = False
        for admin_name in list(self.clients.keys()):
            if self.db.is_admin(admin_name):
                try:
                    await self.clients[admin_name].send_json({
                        'type': 'system',
                        'content': f'🔔 "{username}" solicitou alteração de senha.'
                    })
                    notified = True
                except Exception:
                    pass
        if notified:
            return web.json_response({'success': True, 'message': 'Solicitação enviada'})
        return web.json_response({'success': False, 'message': 'Nenhum admin disponível'})

    # ============================================
    # ARQUIVOS ESTÁTICOS
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

    async def handle_status(self, request):
        return web.json_response({
            'status': 'online',
            'clients': len(self.clients),
            'ollama': {'available': self.ollama_available, 'model': self.ollama_model}
        })

    # ============================================
    # LOGIN/REGISTER HTTP
    # ============================================
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

    async def handle_login_api(self, request):
        data = await request.post()
        username = data.get('username', '')
        password = data.get('password', '')
        if not username or not password:
            return web.json_response({'success': False, 'message': 'Credenciais inválidas'})
        if not self.db.user_exists(username):
            return web.json_response({'success': False, 'message': 'Usuário não encontrado'})
        ok, is_admin = self.db.authenticate_user_ex(username, password)
        if not ok:
            return web.json_response({'success': False, 'message': 'Senha incorreta'})
        return web.json_response({
            'success': True, 'message': 'Login realizado',
            'username': username, 'is_admin': is_admin
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
            return web.json_response({'success': False, 'message': 'Usuário mínimo 3'})
        if len(password) < 6:
            return web.json_response({'success': False, 'message': 'Senha mínimo 6'})
        if username in (self.ai_username, self.orchestrator_username):
            return web.json_response({'success': False, 'message': 'Nome reservado'})
        if not self.db.register_user(username, password, email, is_admin=is_admin):
            return web.json_response({'success': False, 'message': 'Usuário já existe'})
        return web.json_response({'success': True, 'message': 'Registrado', 'is_admin': is_admin})
        
       # ============================================
    # LEMBRETES / NOTIFICAÇÕES
    # ============================================
    async def _check_reminders_loop(self):
        """Verifica a cada 60s se algum evento precisa de notificação."""
        while True:
            try:
                await asyncio.sleep(60)  # verifica a cada 1 minuto
                await self._check_reminders()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erro no verificador de lembretes: {e}")

    async def _check_reminders(self):
        """Verifica todos os eventos de todos os usuários e envia notificações."""
        from datetime import datetime, timedelta

        agora = datetime.now()

        # Pega usuários com eventos no BANCO
        try:
            self.db._reconnect_if_needed()
            self.db.cursor.execute("SELECT DISTINCT username FROM user_events")
            usernames = [row['username'] for row in self.db.cursor.fetchall()]
        except Exception as e:
            logger.error(f"Erro ao buscar usuários com eventos: {e}")
            return

        for username in usernames:
            try:
                eventos = self.db.get_events(username)
            except Exception as e:
                logger.error(f"Erro ao buscar eventos de {username}: {e}")
                continue

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

                    dt_evento = datetime.strptime(
                        f"{data_str} {hora_str}",
                        "%Y-%m-%d %H:%M"
                    )
                except ValueError:
                    continue

                dt_notificar = dt_evento - timedelta(minutes=reminder)

                if dt_notificar <= agora < dt_evento:
                    if not hasattr(self, '_reminders_sent'):
                        self._reminders_sent = set()

                    chave = f"{username}:{ev.get('id')}"
                    if chave in self._reminders_sent:
                        continue

                    await self._send_reminder(username, ev, dt_evento)
                    self._reminders_sent.add(chave)
                    logger.info(f"⏰ Lembrete enviado: {username} → {ev.get('title')}")

    async def _send_reminder(self, username, evento, dt_evento):
        """Envia a notificação de lembrete para o usuário."""
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

    # ============================================
    # WEBSOCKET
    # ============================================
    async def handle_websocket(self, request):
        logger.info("=" * 60)
        logger.info("🔌 1. Nova conexão WebSocket recebida")
        logger.info(f"🔌    Query: {dict(request.query)}")
        logger.info(f"🔌    Remote: {request.remote}")

        # ============================================
        # Criação do WebSocket
        # ============================================
        try:
            ws = web.WebSocketResponse(
                heartbeat=30,
                autoping=True,
                max_msg_size=0,
                timeout=300
            )
            logger.info("🔌 2. WebSocketResponse criada")
        except Exception as e:
            logger.error(f"🔌 2. ERRO ao criar WebSocketResponse: {e}", exc_info=True)
            return web.Response(status=500, text="Erro interno")

        try:
            await ws.prepare(request)
            logger.info("🔌 3. WebSocket preparado")
        except Exception as e:
            logger.error(f"🔌 3. ERRO ao preparar WebSocket: {e}", exc_info=True)
            return ws

        # ============================================
        # Validação do usuário
        # ============================================
        username = request.query.get('username', 'anonimo')
        logger.info(f"🔌 4. Username recebido: '{username}'")

        if not username or username == 'anonimo':
            logger.warning("🔌 5. Username inválido — fechando")
            try:
                await ws.close(1008, "Username obrigatório")
            except Exception:
                pass
            return ws

        try:
            existe = self.db.user_exists(username)
            logger.info(f"🔌 5. Usuário '{username}' existe? {existe}")
            if not existe:
                try:
                    await ws.close(1008, "Usuário desconhecido")
                except Exception:
                    pass
                return ws
        except Exception as e:
            logger.error(f"🔌 5. ERRO ao verificar usuário: {e}", exc_info=True)
            try:
                await ws.close(1011, "Erro interno")
            except Exception:
                pass
            return ws

        logger.info(f"🔌 6. Usuário '{username}' validado")

        # ============================================
        # CORREÇÃO: Fecha conexão anterior do mesmo usuário
        # ============================================
        if username in self.clients:
            old_ws = self.clients[username]
            logger.warning(f"🔌 6.1. ATENÇÃO: '{username}' já estava conectado. Fechando conexão antiga.")
            try:
                await old_ws.close(1000, "Nova conexão aberta em outro dispositivo")
            except Exception as e:
                logger.warning(f"🔌 6.1. Erro ao fechar conexão antiga: {e}")

        # Registra o novo
        self.clients[username] = ws
        logger.info(f"🔌 7. Cliente registrado. Total conectado: {len(self.clients)}")
        logger.info(f"🔌 7.1. Clientes ativos: {list(self.clients.keys())}")

        # ============================================
        # Status no banco
        # ============================================
        try:
            self.db.update_user_status(username, True, request.remote)
            logger.info(f"🔌 8. Status atualizado no banco")
        except Exception as e:
            logger.error(f"🔌 8. ERRO ao atualizar status: {e}", exc_info=True)

        # ============================================
        # Membresia na sala geral
        # ============================================
        try:
            if not self.db.is_room_member('geral', username):
                self.db.add_room_member('geral', username, 'member')
                logger.info(f"🔌 9. Adicionado à sala geral")
            else:
                logger.info(f"🔌 9. Já é membro da sala geral")
        except Exception as e:
            logger.error(f"🔌 9. ERRO na membresia: {e}", exc_info=True)

        # ============================================
        # Histórico
        # ============================================
        try:
            await self.send_history(ws, username, 'geral')
            logger.info(f"🔌 10. Histórico enviado")
        except Exception as e:
            logger.error(f"🔌 10. ERRO ao enviar histórico: {e}", exc_info=True)

        # ============================================
        # Boas-vindas
        # ============================================
        try:
            profile = self.db.get_profile(username)
            nome = profile.get("display_name", username)
            await ws.send_json({
                'type': 'system',
                'content': f'Bem-vindo {nome}!'
            })
            logger.info(f"🔌 11. Boas-vindas enviadas")
        except Exception as e:
            logger.error(f"🔌 11. ERRO nas boas-vindas: {e}", exc_info=True)

        # ============================================
        # Avisos
        # ============================================
        try:
            if self.ollama_available:
                await ws.send_json({
                    'type': 'system',
                    'content': '🤖 IA disponível! Use /ia ou /orq'
                })
            if self.db.is_admin(username):
                await ws.send_json({
                    'type': 'system',
                    'content': '👑 Você é admin! Use /admin'
                })
            logger.info(f"🔌 12. Avisos enviados")
        except Exception as e:
            logger.error(f"🔌 12. ERRO nos avisos: {e}", exc_info=True)

        # ============================================
        # Eventos e disciplinas
        # ============================================
        try:
            await self.send_user_events(username)
            await self.send_user_disciplines(username)
            logger.info(f"🔌 13. Eventos e disciplinas enviados")
        except Exception as e:
            logger.error(f"🔌 13. ERRO em eventos/disciplinas: {e}", exc_info=True)

        # ============================================
        # Broadcast e listas
        # ============================================
        try:
            await self.broadcast({
                'type': 'system',
                'content': f'{username} entrou'
            })
            logger.info(f"🔌 14.1. Broadcast enviado")
        except Exception as e:
            logger.error(f"🔌 14.1. ERRO no broadcast: {e}", exc_info=True)

        try:
            await self.send_user_list()
            logger.info(f"🔌 14.2. Lista de usuários enviada para {len(self.clients)} clientes")
        except Exception as e:
            logger.error(f"🔌 14.2. ERRO na lista de usuários: {e}", exc_info=True)

        try:
            await self.send_room_list()
            logger.info(f"🔌 14.3. Lista de salas enviada")
        except Exception as e:
            logger.error(f"🔌 14.3. ERRO na lista de salas: {e}", exc_info=True)

        logger.info(f"🔌 15. Entrando no loop de mensagens")

        # ============================================
        # Loop principal
        # ============================================
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.process_message(username, data)
                    except json.JSONDecodeError:
                        await self.process_text_message(username, msg.data)
                    except Exception as e:
                        logger.error(f"🔌 Erro ao processar mensagem: {e}", exc_info=True)
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"🔌 WebSocket erro: {ws.exception()}")
                    break
                elif msg.type == WSMsgType.CLOSE:
                    logger.info(f"🔌 Cliente solicitou fechamento")
                    break
        except Exception as e:
            logger.error(f'🔌 ERRO no loop de mensagens: {e}', exc_info=True)
        finally:
            # Remove apenas se for a conexão ATUAL deste usuário
            # (evita que a conexão antiga remova a nova)
            if self.clients.get(username) is ws:
                self.clients.pop(username, None)
                logger.info(f"🔌 16. Cliente '{username}' desconectado. Total restante: {len(self.clients)}")
            else:
                logger.info(f"🔌 16. Conexão antiga de '{username}' fechada (novo cliente ativo)")

            try:
                if self.clients.get(username) is None:
                    self.db.update_user_status(username, False)
            except Exception:
                pass

            try:
                if self.clients.get(username) is None:
                    await self.broadcast({
                        'type': 'system',
                        'content': f'{username} saiu'
                    })
                    await self.send_user_list()
            except Exception:
                pass

            logger.info("=" * 60)

        return ws

    async def process_text_message(self, username, text):
        lower = text.lower()

        # ============================================
        # Orquestrador
        # ============================================
        if lower.startswith('/orq '):
            # Suporta formato: /orq pasta:docs Qual é a pergunta?
            # ou: /orq Qual é a pergunta?
            resto = text[5:].strip()
            pasta = None

            # Detecta "pasta:xxx" no início
            if resto.lower().startswith('pasta:'):
                # Extrai até o primeiro espaço
                partes = resto.split(' ', 1)
                pasta_spec = partes[0]  # "pasta:docs"
                pasta = pasta_spec[6:].strip()  # "docs"
                resto = partes[1] if len(partes) > 1 else ''

            if not resto:
                await self.send_error(username, 'Digite sua pergunta após /orq')
                return

            await self._handle_orchestrator_request(username, resto, pasta, 'geral')
            return

        # ============================================
        # IA direta
        # ============================================
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


        # Handlers que não exigem ser membro
        loose = ['create_room', 'join_room', 'get_rooms', 'get_users',
                 'create_private_room', 'join_private_room',
                 'add_event', 'delete_event', 'toggle_event', 'get_events',
                 'add_discipline', 'delete_discipline', 'get_disciplines',
                 'update_profile', 'logout']
        if msg_type not in loose:
            if not self.db.get_room_details(room):
                await self.send_error(username, 'Sala não existe')
                return
            if not self.db.is_room_member(room, username):
                await self.send_error(username, 'Você não é membro desta sala')
                return

        # ============================================
        # AGENDA
        # ============================================
        if msg_type == 'add_event':
            eid = uuid.uuid4().hex[:8]
            ok = self.db.add_event(
                username, eid,
                data.get('title', ''), data.get('date', ''), data.get('time', ''),
                data.get('discipline', ''), data.get('description', ''),
                data.get('reminder', 0)
            )
            if ok:
                await self.send_user_events(username)
            else:
                await self.send_error(username, 'Erro ao salvar evento')

        elif msg_type == 'delete_event':
            self.db.delete_event(username, data.get('id', ''))
            await self.send_user_events(username)

        elif msg_type == 'toggle_event':
            self.db.toggle_event(username, data.get('id', ''))
            await self.send_user_events(username)

        elif msg_type == 'get_events':
            await self.send_user_events(username)

        # ============================================
        # DISCIPLINAS
        # ============================================
        elif msg_type == 'add_discipline':
            did = uuid.uuid4().hex[:8]
            ok = self.db.add_discipline(
                username, did,
                data.get('name', ''), data.get('professor', ''),
                data.get('color', '#4facfe'), data.get('schedule', '')
            )
            if ok:
                await self.send_user_disciplines(username)
            else:
                await self.send_error(username, 'Erro ao salvar disciplina')

        elif msg_type == 'delete_discipline':
            self.db.delete_discipline(username, data.get('id', ''))
            await self.send_user_disciplines(username)

        elif msg_type == 'get_disciplines':
            await self.send_user_disciplines(username)

        # ============================================
        # GRUPOS FECHADOS
        # ============================================
        elif msg_type == 'create_private_room':
            room_name = data.get('name', '').strip()
            password = data.get('password', '').strip()
            if not room_name or len(password) < 4:
                await self.send_error(username, 'Nome e senha (mín 4) obrigatórios')
                return
            if self.db.get_room_details(room_name):
                await self.send_error(username, 'Já existe uma sala com esse nome')
                return
            if self.db.create_room(room_name, username, is_private=True, password=password):
                await self.send_room_list()
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': f'🔒 Grupo "{room_name}" criado com sucesso!'
                })
            else:
                await self.send_error(username, 'Erro ao criar grupo')

        elif msg_type == 'join_private_room':
            room_name = data.get('name', '').strip()
            password = data.get('password', '').strip()
            room_data = self.db.get_room_details(room_name)
            if not room_data:
                await self.send_error(username, 'Grupo não encontrado')
                return
            if room_data['is_private']:
                if not self.db.verify_room_password(room_name, password):
                    await self.send_error(username, '❌ Senha incorreta')
                    return
            if self.db.is_room_member(room_name, username):
                await self.send_history(self.clients[username], username, room_name)
                return
            self.db.add_room_member(room_name, username, 'member')
            await self.send_history(self.clients[username], username, room_name)
            await self.send_room_list()
            await self.broadcast({
                'type': 'system',
                'content': f'🔓 {username} entrou no grupo "{room_name}"'
            }, room_name)

        elif msg_type == 'add_room_member':
            owner = self.db.get_room_owner(room)
            if owner != username:
                await self.send_error(username, 'Apenas o criador pode adicionar')
                return
            target = data.get('target', '')
            if not self.db.user_exists(target):
                await self.send_error(username, f'Usuário "{target}" não existe')
                return
            if self.db.is_room_member(room, target):
                await self.send_error(username, f'{target} já é membro')
                return
            self.db.add_room_member(room, target, 'member')
            await self.send_room_list()
            if target in self.clients:
                try:
                    await self.clients[target].send_json({
                        'type': 'system',
                        'content': f'✅ Você foi adicionado ao grupo "{room}"'
                    })
                except Exception:
                    pass

        # ============================================
        # DELETAR / LIMPAR
        # ============================================
        elif msg_type == 'delete':
            msg_id_str = data.get('id', '')
            try:
                msg_id = int(msg_id_str)
            except (ValueError, TypeError):
                await self.send_error(username, 'ID inválido')
                return
            row = self.db.get_message_by_id(msg_id)
            if not row:
                await self.send_error(username, 'Mensagem não encontrada')
                return
            if row['from_user'] != username:
                await self.send_error(username, 'Você só pode apagar suas mensagens')
                return
            room_name = row['room_name'] or 'geral'
            self.db.delete_message_by_id(msg_id)
            await self.broadcast({
                'type': 'message_deleted',
                'id': msg_id_str,
                'room': room_name
            }, room_name)

        elif msg_type == 'delete_file':
            msg_id_str = data.get('msg_id', '')
            try:
                msg_id = int(msg_id_str)
            except (ValueError, TypeError):
                await self.send_error(username, 'ID inválido')
                return
            row = self.db.get_message_by_id(msg_id)
            if not row:
                await self.send_error(username, 'Arquivo não encontrado')
                return
            if row['from_user'] != username:
                await self.send_error(username, 'Sem permissão')
                return
            if row['file_path']:
                try:
                    disk = row['file_path'].lstrip('/')
                    if os.path.exists(disk):
                        os.remove(disk)
                except Exception as e:
                    logger.error(f"Erro ao apagar arquivo: {e}")
            room_name = row['room_name'] or 'geral'
            self.db.delete_message_by_id(msg_id)
            await self.broadcast({
                'type': 'file_deleted',
                'id': msg_id_str,
                'room': room_name
            }, room_name)

        elif msg_type == 'clear_room':
            owner = self.db.get_room_owner(room)
            if owner != username:
                await self.send_error(username, 'Apenas o criador pode limpar')
                return
            hours = int(data.get('clear_older_than', 0) or 0)
            n = self.db.clear_room_messages(room, hours)
            await self.broadcast({
                'type': 'system',
                'content': f'🧹 {n} mensagens removidas'
            }, room)

        # ============================================
        # MENSAGEM NORMAL (+ ORQUESTRADOR)
        # ============================================
        elif msg_type == 'message':
            content = data.get('content', '')
            if not content:
                return
            lower = content.lower()

            # ============================================
            # Comando /orq → Orquestrador
            # ============================================
            if lower.startswith('/orq '):
                pergunta = content[5:].strip()
                pasta = data.get('pasta', None)  # ← vem do frontend
                logger.info(f"🧠 /orq recebido de {username}: pergunta='{pergunta[:60]}' pasta={pasta}")
                await self._handle_orchestrator_request(username, pergunta, pasta, room)
                return

            # ============================================
            # Comando /ia → IA direta
            # ============================================
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

        # ============================================
        # LISTAS
        # ============================================
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

        # ============================================
        # SALA PÚBLICA
        # ============================================
        elif msg_type == 'create_room':
            room_name = data.get('name', '').strip()
            if not room_name:
                return
            if self.db.get_room_details(room_name):
                await self.send_error(username, 'Sala já existe')
                return
            if self.db.create_room(room_name, username, is_private=False):
                await self.send_room_list()
                await self.broadcast({
                    'type': 'system',
                    'content': f'🏠 Sala "{room_name}" criada por {username}'
                })

        elif msg_type == 'join_room':
            room_name = data.get('room', '')
            room_data = self.db.get_room_details(room_name)
            if not room_data:
                await self.send_error(username, 'Sala não existe')
                return
            if room_data['is_private'] and not self.db.is_room_member(room_name, username):
                await self.send_error(username, 'Sala privada — use a senha')
                return
            if not self.db.is_room_member(room_name, username):
                self.db.add_room_member(room_name, username, 'member')
                await self.broadcast({
                    'type': 'system',
                    'content': f'{username} entrou na sala'
                }, room_name)
                await self.send_room_list()
            await self.send_history(self.clients[username], username, room_name)

        # ============================================
        # PRIVADO
        # ============================================
        elif msg_type == 'private':
            to_user = data.get('to', '')
            content = data.get('content', '')
            if not to_user or not content:
                return
            msg_id = self.db.save_message(username, to_user, None, content)
            msg = {
                'id': str(msg_id),
                'type': 'private',
                'from': username,
                'to': to_user,
                'content': content,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            }
            if to_user in self.clients:
                try:
                    await self.clients[to_user].send_json(msg)
                except Exception:
                    pass
            try:
                await self.clients[username].send_json({**msg, 'sent': True})
            except Exception:
                pass

        # ============================================
        # EXPULSAR / DELETAR
        # ============================================
        elif msg_type == 'kick_member':
            owner = self.db.get_room_owner(room)
            if owner != username:
                await self.send_error(username, 'Apenas o criador pode expulsar')
                return
            target = data.get('target', '')
            if not target or target == username:
                return
            self.db.remove_room_member(room, target)
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
            owner = self.db.get_room_owner(room)
            if owner != username:
                await self.send_error(username, 'Apenas o criador pode apagar')
                return
            members = self.db.get_room_members(room)
            self.db.delete_room(room)
            for m in members:
                if m in self.clients:
                    try:
                        await self.clients[m].send_json({
                            'type': 'system',
                            'content': f'🗑️ A sala "{room}" foi removida'
                        })
                    except Exception:
                        pass
            await self.send_room_list()

        # ============================================
        # PERFIL
        # ============================================
        elif msg_type == 'update_profile':
            display_name = data.get('display_name', '').strip()
            if display_name:
                self.db.update_profile(username, display_name=display_name)
            await self.send_user_list()

        elif msg_type == 'change_password':
            new_pwd = data.get('new_password', '')
            if len(new_pwd) >= 6:
                self.db.update_password_by_username(username, new_pwd)
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
            messages = self.db.get_private_messages(username, other, limit=100)
            try:
                await self.clients[username].send_json({
                    'type': 'private_history',
                    'with': other,
                    'messages': messages
                })
            except Exception:
                pass

        elif msg_type == 'logout':
            if username in self.clients:
                await self.clients[username].close()
        # ============================================
        # AGENDA
        # ============================================
        if msg_type == 'add_event':
            eid = uuid.uuid4().hex[:8]
            ok = self.db.add_event(
                username, eid,
                data.get('title', ''), data.get('date', ''), data.get('time', ''),
                data.get('discipline', ''), data.get('description', ''),
                data.get('reminder', 0)
            )
            if ok:
                await self.send_user_events(username)
            else:
                await self.send_error(username, 'Erro ao salvar evento')

        elif msg_type == 'delete_event':
            self.db.delete_event(username, data.get('id', ''))
            await self.send_user_events(username)

        elif msg_type == 'toggle_event':
            self.db.toggle_event(username, data.get('id', ''))
            await self.send_user_events(username)

        elif msg_type == 'get_events':
            await self.send_user_events(username)

        # ============================================
        # DISCIPLINAS
        # ============================================
        elif msg_type == 'add_discipline':
            did = uuid.uuid4().hex[:8]
            ok = self.db.add_discipline(
                username, did,
                data.get('name', ''), data.get('professor', ''),
                data.get('color', '#4facfe'), data.get('schedule', '')
            )
            if ok:
                await self.send_user_disciplines(username)
            else:
                await self.send_error(username, 'Erro ao salvar disciplina')

        elif msg_type == 'delete_discipline':
            self.db.delete_discipline(username, data.get('id', ''))
            await self.send_user_disciplines(username)

        elif msg_type == 'get_disciplines':
            await self.send_user_disciplines(username)

        # ============================================
        # GRUPOS FECHADOS
        # ============================================
        elif msg_type == 'create_private_room':
            room_name = data.get('name', '').strip()
            password = data.get('password', '').strip()
            if not room_name or len(password) < 4:
                await self.send_error(username, 'Nome e senha (mín 4) obrigatórios')
                return
            if self.db.get_room_details(room_name):
                await self.send_error(username, 'Já existe uma sala com esse nome')
                return
            if self.db.create_room(room_name, username, is_private=True, password=password):
                await self.send_room_list()
                await self.clients[username].send_json({
                    'type': 'system',
                    'content': f'🔒 Grupo "{room_name}" criado com sucesso!'
                })
            else:
                await self.send_error(username, 'Erro ao criar grupo')

        elif msg_type == 'join_private_room':
            room_name = data.get('name', '').strip()
            password = data.get('password', '').strip()
            room_data = self.db.get_room_details(room_name)
            if not room_data:
                await self.send_error(username, 'Grupo não encontrado')
                return
            if room_data['is_private']:
                if not self.db.verify_room_password(room_name, password):
                    await self.send_error(username, '❌ Senha incorreta')
                    return
            if self.db.is_room_member(room_name, username):
                await self.send_history(self.clients[username], username, room_name)
                return
            self.db.add_room_member(room_name, username, 'member')
            await self.send_history(self.clients[username], username, room_name)
            await self.send_room_list()
            await self.broadcast({
                'type': 'system',
                'content': f'🔓 {username} entrou no grupo "{room_name}"'
            }, room_name)

        elif msg_type == 'add_room_member':
            owner = self.db.get_room_owner(room)
            if owner != username:
                await self.send_error(username, 'Apenas o criador pode adicionar')
                return
            target = data.get('target', '')
            if not self.db.user_exists(target):
                await self.send_error(username, f'Usuário "{target}" não existe')
                return
            if self.db.is_room_member(room, target):
                await self.send_error(username, f'{target} já é membro')
                return
            self.db.add_room_member(room, target, 'member')
            await self.send_room_list()
            if target in self.clients:
                try:
                    await self.clients[target].send_json({
                        'type': 'system',
                        'content': f'✅ Você foi adicionado ao grupo "{room}"'
                    })
                except Exception:
                    pass

        # ============================================
        # DELETAR / LIMPAR
        # ============================================
        elif msg_type == 'delete':
            msg_id_str = data.get('id', '')
            try:
                msg_id = int(msg_id_str)
            except (ValueError, TypeError):
                await self.send_error(username, 'ID inválido')
                return
            row = self.db.get_message_by_id(msg_id)
            if not row:
                await self.send_error(username, 'Mensagem não encontrada')
                return
            if row['from_user'] != username:
                await self.send_error(username, 'Você só pode apagar suas mensagens')
                return
            room_name = row['room_name'] or 'geral'
            self.db.delete_message_by_id(msg_id)
            await self.broadcast({
                'type': 'message_deleted',
                'id': msg_id_str,
                'room': room_name
            }, room_name)

        elif msg_type == 'delete_file':
            msg_id_str = data.get('msg_id', '')
            try:
                msg_id = int(msg_id_str)
            except (ValueError, TypeError):
                await self.send_error(username, 'ID inválido')
                return
            row = self.db.get_message_by_id(msg_id)
            if not row:
                await self.send_error(username, 'Arquivo não encontrado')
                return
            if row['from_user'] != username:
                await self.send_error(username, 'Sem permissão')
                return
            if row['file_path']:
                try:
                    disk = row['file_path'].lstrip('/')
                    if os.path.exists(disk):
                        os.remove(disk)
                except Exception as e:
                    logger.error(f"Erro ao apagar arquivo: {e}")
            room_name = row['room_name'] or 'geral'
            self.db.delete_message_by_id(msg_id)
            await self.broadcast({
                'type': 'file_deleted',
                'id': msg_id_str,
                'room': room_name
            }, room_name)

        elif msg_type == 'clear_room':
            owner = self.db.get_room_owner(room)
            if owner != username:
                await self.send_error(username, 'Apenas o criador pode limpar')
                return
            hours = int(data.get('clear_older_than', 0) or 0)
            n = self.db.clear_room_messages(room, hours)
            await self.broadcast({
                'type': 'system',
                'content': f'🧹 {n} mensagens removidas'
            }, room)

        # ============================================
        # MENSAGEM NORMAL
        elif msg_type == 'file':
            await self.handle_file_upload(username, data)

        elif msg_type == 'ai_request':
            prompt = data.get('prompt', '')
            model = data.get('model', self.ollama_model)
            if model != self.ollama_model:
                self.ollama_model = model
            if prompt:
                await self.handle_ai_request(username, prompt, room)

        # ============================================
        # LISTAS
        # ============================================
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

        # ============================================
        # SALA PÚBLICA
        # ============================================
        elif msg_type == 'create_room':
            room_name = data.get('name', '').strip()
            if not room_name:
                return
            if self.db.get_room_details(room_name):
                await self.send_error(username, 'Sala já existe')
                return
            if self.db.create_room(room_name, username, is_private=False):
                await self.send_room_list()
                await self.broadcast({
                    'type': 'system',
                    'content': f'🏠 Sala "{room_name}" criada por {username}'
                })

        elif msg_type == 'join_room':
            room_name = data.get('room', '')
            room_data = self.db.get_room_details(room_name)
            if not room_data:
                await self.send_error(username, 'Sala não existe')
                return
            if room_data['is_private'] and not self.db.is_room_member(room_name, username):
                await self.send_error(username, 'Sala privada — use a senha')
                return
            if not self.db.is_room_member(room_name, username):
                self.db.add_room_member(room_name, username, 'member')
                await self.broadcast({
                    'type': 'system',
                    'content': f'{username} entrou na sala'
                }, room_name)
                await self.send_room_list()
            await self.send_history(self.clients[username], username, room_name)

        # ============================================
        # PRIVADO
        # ============================================
        elif msg_type == 'private':
            to_user = data.get('to', '')
            content = data.get('content', '')
            if not to_user or not content:
                return
            msg_id = self.db.save_message(username, to_user, None, content)
            msg = {
                'id': str(msg_id),
                'type': 'private',
                'from': username,
                'to': to_user,
                'content': content,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            }
            if to_user in self.clients:
                try:
                    await self.clients[to_user].send_json(msg)
                except Exception:
                    pass
            try:
                await self.clients[username].send_json({**msg, 'sent': True})
            except Exception:
                pass

        # ============================================
        # EXPULSAR / DELETAR
        # ============================================
        elif msg_type == 'kick_member':
            owner = self.db.get_room_owner(room)
            if owner != username:
                await self.send_error(username, 'Apenas o criador pode expulsar')
                return
            target = data.get('target', '')
            if not target or target == username:
                return
            self.db.remove_room_member(room, target)
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
            owner = self.db.get_room_owner(room)
            if owner != username:
                await self.send_error(username, 'Apenas o criador pode apagar')
                return
            members = self.db.get_room_members(room)
            self.db.delete_room(room)
            for m in members:
                if m in self.clients:
                    try:
                        await self.clients[m].send_json({
                            'type': 'system',
                            'content': f'🗑️ A sala "{room}" foi removida'
                        })
                    except Exception:
                        pass
            await self.send_room_list()

        # ============================================
        # PERFIL
        # ============================================
        elif msg_type == 'update_profile':
            display_name = data.get('display_name', '').strip()
            if display_name:
                self.db.update_profile(username, display_name=display_name)
            await self.send_user_list()

        elif msg_type == 'change_password':
            new_pwd = data.get('new_password', '')
            if len(new_pwd) >= 6:
                self.db.update_password_by_username(username, new_pwd)
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
            messages = self.db.get_private_messages(username, other, limit=100)
            try:
                await self.clients[username].send_json({
                    'type': 'private_history',
                    'with': other,
                    'messages': messages
                })
            except Exception:
                pass

        elif msg_type == 'logout':
            if username in self.clients:
                await self.clients[username].close()

    # ============================================
    # ORQUESTRADOR
    # ============================================
    async def _handle_orchestrator_request(self, username, pergunta, pasta, room):
        """Processa uma requisição para o orquestrador multi-agente."""
        if not pergunta:
            await self.send_error(username, 'Digite sua pergunta após /orq')
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
            msg_id = self.db.save_message(self.orchestrator_username, None, room, content_final)

            if msg_id:
                msg = {
                    'id': str(msg_id),
                    'type': 'message',
                    'from': self.orchestrator_username,
                    'content': content_final,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'room': room
                }
                await self.broadcast(msg, room)
            else:
                await self.broadcast({
                    'type': 'message',
                    'from': self.orchestrator_username,
                    'content': content_final,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'room': room
                }, room)

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
    # SALVAR / BROADCAST
    # ============================================
    async def save_and_broadcast_text(self, username, content, room):
        import time as _time
        t0 = _time.time()
        
        msg_id = self.db.save_message(username, None, room, content)
        t1 = _time.time()
        
        if not msg_id:
            await self.send_error(username, 'Erro ao salvar mensagem')
            return
        msg = {
            'id': str(msg_id),
            'type': 'message',
            'from': username,
            'content': content,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'room': room
        }
        
        await self.broadcast(msg, room)
        t2 = _time.time()
        
        logger.info(f"⏱️ save_message: {(t1-t0)*1000:.0f}ms | broadcast: {(t2-t1)*1000:.0f}ms")

    async def handle_file_upload(self, username, data):
        filename = data.get('file_name', '')
        file_data = data.get('data', '')
        room = data.get('room', 'geral')

        if not filename or not file_data:
            return
        if not self.db.is_room_member(room, username):
            await self.send_error(username, 'Você não é membro desta sala')
            return

        unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        disk_path = f"uploads/{unique_name}"
        web_path = f"/uploads/{unique_name}"

        if file_data.startswith('data:'):
            file_data = file_data.split(',', 1)[1]

        try:
            with open(disk_path, 'wb') as f:
                f.write(base64.b64decode(file_data))
            size = os.path.getsize(disk_path)

            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
                mtype = 'image'
            elif ext in ('mp4', 'webm', 'mov'):
                mtype = 'video'
            elif ext in ('mp3', 'wav', 'ogg'):
                mtype = 'audio'
            else:
                mtype = 'file'

            msg_id = self.db.save_message(
                username, None, room, filename,
                file_path=web_path, file_name=filename,
                file_size=size, mime_type='application/octet-stream',
                message_type=mtype
            )
            if not msg_id:
                await self.send_error(username, 'Erro ao salvar arquivo')
                return

            msg = {
                'id': str(msg_id),
                'type': 'file',
                'from': username,
                'file_name': filename,
                'file_path': web_path,
                'file_size': size,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'room': room
            }
            await self.broadcast(msg, room)
            logger.info(f"📎 Arquivo enviado: {filename} por {username}")
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo: {e}")
            await self.send_error(username, 'Erro ao enviar arquivo')

    # ============================================
    # IA DIRETA
    # ============================================
    async def handle_ai_request(self, username, prompt, room):
        logger.info(f"🤖 IA request de {username}: {prompt[:80]}")
        await self.broadcast({'type': 'typing', 'from': self.ai_username, 'is_typing': True}, room)

        system = 'Você é um assistente útil e amigável chamado "IA DeepCord". Responda de forma clara e concisa.'
        response = await self.call_ollama(prompt, system)

        await self.broadcast({'type': 'typing', 'from': self.ai_username, 'is_typing': False}, room)

        if response:
            content = f'🤖 {response}'
            msg_id = self.db.save_message(self.ai_username, None, room, content)
            if msg_id:
                msg = {
                    'id': str(msg_id),
                    'type': 'message',
                    'from': self.ai_username,
                    'content': content,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'room': room
                }
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

    # ============================================
    # ENVIO
    # ============================================
    async def send_history(self, ws, username, room):
        messages = self.db.get_room_messages(room, limit=50)
        owner = self.db.get_room_owner(room)
        try:
            await ws.send_json({
                'type': 'history',
                'room': room,
                'messages': messages,
                'owner': owner,
                'ai_username': self.ai_username
            })
        except Exception as e:
            logger.error(f"Erro ao enviar histórico: {e}")

    async def send_room_list(self):
        rooms = self.db.get_all_rooms()
        for r in rooms:
            r['members'] = self.db.get_room_members(r['name'])
        message = {'type': 'room_list', 'rooms': rooms}
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
        display_names = self.db.get_all_display_names()
        message = {
            'type': 'user_list',
            'users': users,
            'display_names': display_names,
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
            events = self.db.get_events(username)
            try:
                await self.clients[username].send_json({
                    'type': 'user_events',
                    'events': events
                })
            except Exception:
                pass

    async def send_user_disciplines(self, username):
        if username in self.clients:
            discs = self.db.get_disciplines(username)
            try:
                await self.clients[username].send_json({
                    'type': 'user_disciplines',
                    'disciplines': discs
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
        """Envia para TODOS os clientes conectados (ignora salas)."""
        import time as _time
        t0 = _time.time()
        
        data = json.dumps(message)
        
        enviados = 0
        falhas = 0
        disconnected = []
        
        # Envia para TODOS os clientes conectados (não filtra por sala)
        for username, ws in list(self.clients.items()):
            try:
                await ws.send_str(data)
                enviados += 1
            except Exception as e:
                logger.error(f"❌ Erro ao enviar para '{username}': {e}")
                falhas += 1
                disconnected.append(username)
        
        # Remove clientes mortos
        for u in disconnected:
            self.clients.pop(u, None)
        
        t1 = _time.time()
        logger.info(f"⏱️ broadcast: {(t1-t0)*1000:.1f}ms | clientes={len(self.clients)} | enviados={enviados} | falhas={falhas}")


    async def run(self, host='0.0.0.0', port=8081):
        await self.check_ollama()

        # ============================================
        # NOVO: Inicia a tarefa de verificação de lembretes
        # ============================================
        # ⚠️ TEMPORARIAMENTE DESATIVADO PARA DEBUG
        # self.reminder_task = asyncio.create_task(self._check_reminders_loop())
        logger.info("⏰ Verificador de lembretes DESATIVADO (modo debug)")

        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        print("\n" + "=" * 60)
        print("  DeepCord — MySQL Edition + Orquestrador")
        print("=" * 60)
        print(f"📍 http://localhost:{port}")
        print(f"👤 Admin: admin / admin123")
        print(f"🗄️  MySQL: {self.db.host}/{self.db.database}")
        print(f"🤖 Ollama: {'✅' if self.ollama_available else '❌'}")
        print(f"🧠 Orquestrador: refinedneuro/refinedtoolcallv5-3b")
        print(f"📚 Base de conhecimento: ./conhecimento/")
        print("=" * 60)
        print("\n📝 COMANDOS NO CHAT:")
        print("  /ia <pergunta>   — IA direta (modelo único)")
        print("  /orq <pergunta>  — Orquestrador multi-agente + RAG")
        print("=" * 60 + "\n")

        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Desligando...")
            self.db.disconnect()
            await runner.cleanup()


if __name__ == '__main__':
    server = ChatServer()
    asyncio.run(server.run())
