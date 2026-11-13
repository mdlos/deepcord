#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@file orchestrator.py
@brief Orquestrador multi-agente com RAG para DeepCord
       - Usa refinedneuro/refinedtoolcallv5-3b como agente principal
       - Consulta subagentes: phi3, llava-phi3, qwen2.5-coder
       - Busca em arquivos .md, .pdf, .txt, imagens em pastas selecionadas
"""

import asyncio
import aiohttp
import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, ollama_host: str, model: str = "refinedneuro/refinedtoolcallv5-3b",
                 knowledge_base: str = "conhecimento"):
        self.ollama_host = ollama_host.rstrip('/')
        self.model = model
        self.knowledge_base = Path(knowledge_base)
        self.knowledge_base.mkdir(parents=True, exist_ok=True)

        self.system_prompt = (
            "/no_think\n"
            "Você é um orquestrador de IA. Analise a pergunta do usuário e escolha a ferramenta correta:\n"
            "1. Arquivos/documentos/políticas/manuais → buscar_arquivos\n"
            "2. Código de programação → consultar_especialista com 'qwen2.5-coder'\n"
            "3. Imagens/visão → consultar_especialista com 'llava-phi3'\n"
            "4. Conversa geral/saudação → responder_direto\n\n"
            "REGRAS OBRIGATÓRIAS:\n"
            "- Responda SEMPRE com uma chamada de ferramenta.\n"
            "- NUNCA responda com texto puro sem chamar uma ferramenta.\n"
            "- Se a busca envolver arquivos, use a ferramenta 'buscar_arquivos'.\n"
            "- Se a pergunta for sobre código, delegue para 'qwen2.5-coder'.\n"
        )
    async def processar_texto_direto(self, texto: str, pergunta: str,
                                      nome_arquivo: str = "documento") -> str:
        """Processa uma pergunta sobre um texto específico (RAG direto sem busca)."""
        logger.info(f"🧠 Orquestrador analisando '{nome_arquivo}' ({len(texto)} chars)")

        # Limita o texto para não estourar o contexto do modelo
        max_chars = 12000
        if len(texto) > max_chars:
            texto = texto[:max_chars] + f"\n\n[... texto truncado — original tem {len(texto)} caracteres ...]"

        prompt = (
            f"Você é um assistente especializado em análise de documentos.\n\n"
            f"📄 Arquivo: {nome_arquivo}\n\n"
            f"📋 Conteúdo do documento:\n"
            f"---\n{texto}\n---\n\n"
            f"❓ Pergunta do usuário: {pergunta}\n\n"
            f"Responda de forma clara e concisa em português, baseando-se APENAS no conteúdo "
            f"do documento acima. Se a informação não estiver no documento, diga que não encontrou."
        )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "top_p": 0.9,
                "num_predict": 700
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_host}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=240)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        resposta = data.get('response', '').strip()
                        return self._limpar_resposta(resposta)
        except Exception as e:
            logger.error(f"Erro ao processar texto: {e}")

        return "❌ Não foi possível analisar o documento. Tente novamente."

    async def processar_imagem(self, imagem_path: str, pergunta: str,
                                nome_arquivo: str = "imagem") -> str:
        """Analisa uma imagem usando o modelo de visão do Ollama."""
        logger.info(f"🖼️ Analisando imagem '{nome_arquivo}'")
        import base64

        try:
            with open(imagem_path, 'rb') as f:
                img_bytes = f.read()
                img_b64 = base64.b64encode(img_bytes).decode('utf-8')
            logger.info(f"   ✅ Imagem lida: {len(img_bytes)} bytes")
        except Exception as e:
            logger.error(f"   ❌ Erro ao ler imagem: {e}")
            return f"❌ Não foi possível ler a imagem: {e}"

        modelo_visao = "llava-phi3:latest"
        payload = {
            "model": modelo_visao,
            "prompt": pergunta,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 700}
        }

        logger.info(f"   📤 Enviando para Ollama ({modelo_visao})...")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_host}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=300)
                ) as resp:
                    logger.info(f"   📥 Resposta HTTP: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        resposta = data.get('response', '').strip()
                        logger.info(f"   ✅ Resposta recebida ({len(resposta)} chars)")
                        return self._limpar_resposta(resposta)
                    else:
                        erro_texto = await resp.text()
                        logger.error(f"   ❌ Erro {resp.status}: {erro_texto[:300]}")
                        return f"❌ Erro do Ollama ({resp.status}): {erro_texto[:200]}"
        except asyncio.TimeoutError:
            logger.error(f"   ❌ Timeout (300s)")
            return "❌ Tempo esgotado ao analisar a imagem. Tente uma imagem menor."
        except Exception as e:
            logger.error(f"   ❌ Erro: {e}", exc_info=True)
            return f"❌ Erro ao processar imagem: {e}"

    def _limpar_resposta(self, texto: str) -> str:
        """Remove blocos <think>...</think> do texto final."""
        if not texto:
            return texto
        texto_limpo = re.sub(r'<think>.*?</think>', '', texto, flags=re.DOTALL)
        if '<think>' in texto_limpo:
            texto_limpo = texto_limpo.split('<think>')[0]
        return texto_limpo.strip()
    # ============================================
    # API PRINCIPAL
    # ============================================
    async def processar(self, pergunta: str, pasta_alvo: Optional[str] = None) -> str:
        """Processa a pergunta do usuário e executa a tool call apropriada."""
        logger.info(f"🧠 Orquestrador recebendo: {pergunta[:80]}... (pasta={pasta_alvo})")

        tools = self._get_tools()

        pergunta_final = pergunta
        if pasta_alvo:
            pergunta_final = (
                f"[Contexto: O usuário selecionou a pasta '{pasta_alvo}'. "
                f"Use essa pasta na ferramenta 'buscar_arquivos'.] {pergunta}"
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": pergunta_final}
            ],
            "tools": tools,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "num_predict": 400
            }
        }

        tool_call = await self._chamar_ollama(payload)

        if not tool_call:
            return "❌ O orquestrador não conseguiu decidir uma ação. Tente reformular a pergunta."

        nome = tool_call.get('name', '')
        args = tool_call.get('arguments', {}) or {}
        logger.info(f"🔧 Tool call: {nome} → args: {args}")

        if nome == 'buscar_arquivos':
            pasta = args.get('pasta', pasta_alvo or 'conhecimento')
            query = args.get('query', pergunta)
            resultado = await self._ferramenta_buscar_arquivos(pasta, query)
        elif nome == 'consultar_especialista':
            agente = args.get('agente', 'phi3')
            sub_pergunta = args.get('pergunta', pergunta)
            resultado = await self._ferramenta_consultar_especialista(agente, sub_pergunta)
        elif nome == 'responder_direto':
            return args.get('resposta', 'Olá! Como posso ajudar?')
        else:
            return f"❌ Ferramenta desconhecida: {nome}"

        return await self._sintetizar_resposta(pergunta, nome, resultado)

    # ============================================
    # FERRAMENTAS
    # ============================================
    def _get_tools(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "buscar_arquivos",
                    "description": (
                        "Busca informações em arquivos (Markdown, PDF, TXT, imagens) "
                        "de uma pasta específica da base de conhecimento."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pasta": {
                                "type": "string",
                                "description": "Nome da pasta (ex: 'rh', 'docs', 'projetos', 'conhecimento')"
                            },
                            "query": {
                                "type": "string",
                                "description": "O que buscar nos arquivos"
                            }
                        },
                        "required": ["pasta", "query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "consultar_especialista",
                    "description": (
                        "Envia pergunta para subagente especialista. "
                        "Use 'qwen2.5-coder' para código, 'llava-phi3' para imagens, "
                        "'phi3' para conversa geral."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "agente": {
                                "type": "string",
                                "enum": ["phi3", "llava-phi3", "qwen2.5-coder"]
                            },
                            "pergunta": {"type": "string"}
                        },
                        "required": ["agente", "pergunta"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "responder_direto",
                    "description": "Responde diretamente sem ferramentas. Use apenas para saudações ou conversa trivial.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "resposta": {"type": "string"}
                        },
                        "required": ["resposta"]
                    }
                }
            }
        ]

    async def _ferramenta_buscar_arquivos(self, pasta: str, query: str) -> str:
        """Busca em .md, .pdf, .txt e imagens."""
        pasta = (pasta or '').strip().strip('/').strip('\\')
        if not pasta or '..' in pasta:
            pasta = 'conhecimento'

        candidates = [
            self.knowledge_base / pasta,
            Path(pasta),
        ]
        pasta_path = next((p for p in candidates if p.exists() and p.is_dir()), None)

        if not pasta_path:
            return f"A pasta '{pasta}' não foi encontrada."

        logger.info(f"📂 Buscando em: {pasta_path}")

        resultados = []
        termos = [t for t in query.lower().split() if len(t) > 2]

        supported_exts = {'.md', '.txt', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp'}

        for arquivo in pasta_path.rglob("*"):
            if not arquivo.is_file():
                continue
            if arquivo.suffix.lower() not in supported_exts:
                continue

            texto = await self._extrair_texto(arquivo)
            if not texto:
                continue

            texto_lower = texto.lower()
            if not termos or any(t in texto_lower for t in termos):
                trecho = self._extrair_trecho(texto, termos)
                resultados.append(f"--- 📄 {arquivo.name} ---\n{trecho}")

        if not resultados:
            return f"Nenhum resultado encontrado para '{query}' na pasta '{pasta}'."

        return "\n\n".join(resultados[:3])

    def _extrair_trecho(self, texto: str, termos: List[str], tamanho: int = 600) -> str:
        if not termos:
            return texto[:tamanho]

        texto_lower = texto.lower()
        posicoes = [texto_lower.find(t) for t in termos if texto_lower.find(t) >= 0]
        if not posicoes:
            return texto[:tamanho]

        pos = min(posicoes)
        inicio = max(0, pos - 200)
        fim = min(len(texto), pos + tamanho)
        return texto[inicio:fim].strip()

    async def _extrair_texto(self, arquivo: Path) -> str:
        """Extrai texto de .md, .txt, .pdf e imagens."""
        try:
            ext = arquivo.suffix.lower()

            if ext in ('.md', '.txt'):
                return arquivo.read_text(encoding='utf-8', errors='ignore')

            elif ext == '.pdf':
                try:
                    import pymupdf4llm
                    return pymupdf4llm.to_markdown(str(arquivo))
                except ImportError:
                    try:
                        import pypdf
                        reader = pypdf.PdfReader(str(arquivo))
                        return "\n".join((p.extract_text() or '') for p in reader.pages)
                    except ImportError:
                        logger.warning(f"⚠️ Nenhuma lib de PDF instalada. Ignorando {arquivo.name}")
                        return f"[PDF: {arquivo.name} — instale pymupdf4llm ou pypdf]"

            elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                return f"[Imagem: {arquivo.name}]"

        except Exception as e:
            logger.error(f"Erro ao ler {arquivo}: {e}")
        return ""

    async def _ferramenta_consultar_especialista(self, agente: str, pergunta: str) -> str:
        logger.info(f"🤖 Consultando especialista: {agente}")
        payload = {
            "model": agente,
            "prompt": pergunta,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 500}
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_host}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('response', '').strip()
                    logger.error(f"Erro {resp.status} ao consultar {agente}")
        except Exception as e:
            logger.error(f"Erro ao consultar {agente}: {e}")
        return f"O especialista '{agente}' não conseguiu responder no momento."

    # ============================================
    # CHAMADA AO OLLAMA
    # ============================================
    async def _chamar_ollama(self, payload: Dict) -> Optional[Dict]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_host}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=180)
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"❌ HTTP {resp.status} ao chamar orquestrador")
                        return None
                    data = await resp.json()

            message = data.get('message', {}) or {}
            tool_calls = message.get('tool_calls', []) or []

            if tool_calls:
                return self._extrair_tool_call(tool_calls[0])

            content = message.get('content', '') or ''
            return self._extrair_tool_call_do_texto(content)

        except asyncio.TimeoutError:
            logger.error("❌ Timeout ao chamar orquestrador")
        except Exception as e:
            logger.error(f"❌ Erro no orquestrador: {e}")
        return None

    def _extrair_tool_call(self, tc: Dict) -> Dict:
        func = tc.get('function', {}) or {}
        args = func.get('arguments', {}) or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        return {"name": func.get('name'), "arguments": args}

    def _extrair_tool_call_do_texto(self, content: str) -> Optional[Dict]:
        content_limpo = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        if '<think>' in content_limpo:
            content_limpo = content_limpo.split('<think>')[0]

        match = re.search(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', content_limpo, re.DOTALL)
        if match:
            try:
                d = json.loads(match.group(1))
                return {"name": d.get("name"), "arguments": d.get("arguments", {})}
            except Exception:
                pass

        match = re.search(
            r'\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
            content_limpo, re.DOTALL
        )
        if match:
            try:
                return {"name": match.group(1), "arguments": json.loads(match.group(2))}
            except Exception:
                pass

        match = re.search(
            r'\[\s*\{\s*"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}\s*\]',
            content_limpo, re.DOTALL
        )
        if match:
            try:
                return {"name": match.group(1), "arguments": json.loads(match.group(2))}
            except Exception:
                pass

        return None

    async def _sintetizar_resposta(self, pergunta: str, ferramenta: str, resultado: str) -> str:
        if ferramenta == 'responder_direto':
            return resultado

        prompt = (
            "Você é um assistente útil. Com base nas informações abaixo, responda à pergunta "
            "do usuário de forma clara e concisa em português.\n\n"
            f"📌 Pergunta: {pergunta}\n\n"
            f"📊 Informações obtidas ({ferramenta}):\n{resultado}\n\n"
            "Responda em no máximo 2 parágrafos:"
        )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.4, "num_predict": 500}
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_host}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        texto = data.get('response', '').strip()
                        if texto:
                            return texto
        except Exception as e:
            logger.error(f"Erro ao sintetizar: {e}")

        return resultado
