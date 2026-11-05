"""Dedicated VK browser: restrict HTTP(S)/WebSocket destinations, block service workers."""
import os
from urllib.parse import urlsplit
from .privacy import audit

VK_DOMAINS=('vk.com','vk.ru','vk.me','vkuser.net','vkuseraudio.net','vkuseraudio.ru','vkuserphoto.ru','userapi.com','vk-cdn.net','vk-cdn.me','vkvideo.ru')
VK_EXACT_HOSTS={'stacks.vk-portal.net'} # VK ID's documented static dependency; not the analytics subdomains.

def allowed(url):
    parsed=urlsplit(url)
    if parsed.scheme in {'about','data','blob'}:return True
    host=parsed.hostname or ''
    try:return parsed.scheme in {'https','wss'} and not parsed.username and not parsed.password and parsed.port in (None,443) and (host in VK_EXACT_HOSTS or any(host==domain or host.endswith('.'+domain) for domain in VK_DOMAINS))
    except ValueError:return False

def environment():
    return {k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ('API_KEY','API_HASH','TOKEN','PASSWORD','SECRET','AUTH','COOKIE','SESSION'))}

def protect(context,*,blocked_domains=None):
    def diagnostic(url):
        if blocked_domains is not None:
            host=urlsplit(url).hostname or ''
            blocked_domains.add('.'.join(host.split('.')[-2:]))
    def http(route):
        if allowed(route.request.url):route.fallback()
        else:
            diagnostic(route.request.url)
            audit('blocked','vk_browser_http','unapproved_host')
            route.abort('blockedbyclient')
    def websocket(route):
        if allowed(route.url):route.connect_to_server()
        else:
            diagnostic(route.url)
            audit('blocked','vk_browser_websocket','unapproved_host')
            route.close(code=1008,reason='Jarvis destination policy')
    context.route('**/*',http)
    context.route_web_socket('**/*',websocket)
    # No response bodies, cookies or WebSocket frames are copied into the audit.
