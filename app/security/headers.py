"""
Cabeçalhos de segurança aplicados a TODAS as respostas.

`setdefault`: uma página que precise de uma CSP diferente pode defini-la e não será sobrescrita.
HSTS não é enviado aqui: quem termina o TLS (o proxy reverso) é quem deve enviá-lo.
"""
from __future__ import annotations

from starlette.responses import Response

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def aplicar_cabecalhos(response: Response, caminho: str) -> None:
    h = response.headers
    h.setdefault("Content-Security-Policy", _CSP)
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # API: nada de respostas em cache (evita dados/tokens ficarem no navegador ou no proxy).
    if caminho.startswith(("/api/", "/webhook/")):
        h.setdefault("Cache-Control", "no-store")
    # Telas: o navegador pode guardar, mas revalida sempre (uma versão nova aparece no próximo F5).
    elif caminho == "/" or caminho.startswith("/ui/"):
        h.setdefault("Cache-Control", "no-cache")
