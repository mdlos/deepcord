import os
import re

css = """
<style id="wpp-theme-final">
    html, body {
        background-color: #efeae2 !important;
        color: #111b21 !important;
        font-family: "Segoe UI", Helvetica, Arial, sans-serif !important;
    }
    .sidebar, .topbar, .chat-list, .chat-header, .input-area, .login-box, .admin-header, .admin-container {
        background-color: #ffffff !important;
        border-color: #e9edef !important;
    }
    .msg.own { background-color: #d9fdd3 !important; color: #111b21 !important; border: none !important; }
    .msg.other, .msg.ai { background-color: #ffffff !important; color: #111b21 !important; border: none !important; }
    .btn-primary, .btn-login, .send-btn, .btn-ai, .group-btn, .admin-actions button.primary {
        background-color: #00a884 !important;
        color: #ffffff !important;
        border: none !important;
    }
    .btn-primary:hover, .btn-login:hover, .send-btn:hover, .btn-ai:hover, .group-btn:hover, .admin-actions button.primary:hover {
        background-color: #008f6f !important;
    }
    .nav-item.active, .tabs button.active {
        background-color: #e7fce3 !important;
        color: #00a884 !important;
    }
    .stat-card, .hero, .group-card, .meetings-table, .table-container {
        background-color: #ffffff !important;
        border: 1px solid #e9edef !important;
        box-shadow: none !important;
    }
    h1, h2, h3, .stat-value, .section-title, .group-name, .name, th, td {
        color: #111b21 !important;
    }
    p, .label, .stat-label, .item-last, .time, .group-meta, .subtitle {
        color: #667781 !important;
    }
    #theme-btn, .theme-toggle, .server-status {
        display: none !important;
    }
</style>
"""

arquivos = ["login.html", "index.html", "chat.html", "admin.html", "admin_login.html"]

for arq in arquivos:
    if not os.path.exists(arq):
        print(f"⚠️ {arq} não encontrado")
        continue

    with open(arq, "r", encoding="utf-8") as f:
        html = f.read()

    # Remove o botão de tema antigo
    html = html.replace('<button class="topbar-icon-btn" onclick="toggleTheme()" id="theme-btn" title="Tema">🌙</button>', "")
    html = html.replace('<button class="topbar-icon-btn" onclick="toggleTheme()" title="Alternar tema" id="theme-btn">🌙</button>', "")
    html = html.replace('<button class="theme-toggle" id="theme-toggle" onclick="toggleTheme()" title="Alternar tema">🌙</button>', "")

    # Remove qualquer função JS de tema
    html = re.sub(r"function toggleTheme\(\)\s*\{.*?\}", "", html, flags=re.DOTALL)
    html = re.sub(r"function applyTheme\(.*?\)\s*\{.*?\}", "", html, flags=re.DOTALL)

    # Injeta o CSS antes do </head>
    if "</head>" in html and "wpp-theme-final" not in html:
        html = html.replace("</head>", css + "\n</head>")

    with open(arq, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ {arq} atualizado com o tema!")

print("\n🎉 Tema WhatsApp aplicado em todas as páginas!")
