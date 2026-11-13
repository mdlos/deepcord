import os

css = """
<style id="wpp-final-theme">
    /* Fundo Geral */
    html, body {
        background-color: #f0f2f5 !important;
        color: #111b21 !important;
        font-family: "Segoe UI", Helvetica, Arial, sans-serif !important;
    }

    /* Menus, Sidebars e Cartões */
    .sidebar, .topbar, .chat-list, .chat-header, .input-area, .login-box, 
    .admin-header, .admin-container, .stat-card, .hero, .group-card, 
    .meetings-table, .table-container {
        background-color: #ffffff !important;
        border: 1px solid #e9edef !important;
        box-shadow: none !important;
    }

    /* Botões Verdes (Entrar, Enviar, Perguntar) */
    .btn-primary, .btn-login, .send-btn, .btn-ai, .group-btn, 
    .admin-actions button.primary, .group-card .group-btn {
        background-color: #00a884 !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 6px !important;
    }
    .btn-primary:hover, .btn-login:hover, .send-btn:hover, .btn-ai:hover, .group-btn:hover {
        background-color: #008f6f !important;
    }

    /* Inputs de Texto */
    input, select, textarea {
        background-color: #f8f9fa !important;
        border: 1px solid #e9edef !important;
        color: #111b21 !important;
        border-radius: 6px !important;
    }
    input:focus { border-color: #00a884 !important; background-color: #ffffff !important; }

    /* Chat e Mensagens */
    .chat-area, .messages { background-color: #efeae2 !important; }
    .msg.own { background-color: #d9fdd3 !important; color: #111b21 !important; border: none !important; }
    .msg.other, .msg.ai { background-color: #ffffff !important; color: #111b21 !important; border: none !important; }

    /* Textos e Avatares */
    h1, h2, h3, .stat-value, .section-title, .group-name, .name, th, td { color: #111b21 !important; }
    p, .label, .stat-label, .item-last, .time, .group-meta, .subtitle { color: #667781 !important; }
    .hero-avatar, .topbar-avatar, .item-avatar { border-radius: 50% !important; object-fit: cover !important; }

    /* Remover Botão de Tema e Status Antigo */
    #theme-btn, .theme-toggle, .server-status { display: none !important; }
</style>
"""

arquivos = ["login.html", "index.html", "chat.html", "admin.html", "admin_login.html"]

for arq in arquivos:
    if not os.path.exists(arq):
        continue

    with open(arq, "r", encoding="utf-8") as f:
        html = f.read()

    # Se já injetou antes, remove para não duplicar
    import re
    html = re.sub(r'<style id="wpp-final-theme">.*?</style>', '', html, flags=re.DOTALL)

    # Injeta o novo CSS antes do fechamento do </head>
    if "</head>" in html:
        html = html.replace("</head>", css + "\n</head>")

    with open(arq, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ {arq} atualizado com o tema WhatsApp!")
