"""Envío de avisos a Telegram (un tema por tipo de chollo) y, si está configurado, también a Discord.

Telegram: secretos TELEGRAM_TOKEN y TELEGRAM_CHAT_ID.
Discord:  secreto DISCORD_WEBHOOK (la URL del webhook de un canal). Si el canal es de tipo «Foro»,
          se crea un hilo por apartado (igual que los temas de Telegram); si es un canal normal, va todo ahí.
"""
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

TEMAS = {
    'iphone_listo': '🍏 iPhone · Listos para vender',
    'iphone_reparar': '🔧 iPhone · Para reparar',
    'android_listo': '🤖 Android · Listos para vender',
    'android_reparar': '🛠️ Android · Para reparar',
    'equipo': '⭐ Guardados, compras y resumen',
}
COLOR_TEMA = {'iphone_listo': 7322096, 'iphone_reparar': 16766590, 'android_listo': 9367192, 'android_reparar': 16749490, 'equipo': 16478047}

_estado = {}          # se rellena en preparar_temas: temas de Telegram + estado de Discord (se guarda en temas.json)


def activo():
    return bool(os.environ.get('TELEGRAM_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID'))


def discord_activo():
    return bool(os.environ.get('DISCORD_WEBHOOK'))


def _api(metodo, **params):
    token = os.environ['TELEGRAM_TOKEN']
    datos = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items() if v is not None}
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/{metodo}',
                                 data=urllib.parse.urlencode(datos).encode())
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {'ok': False, 'description': str(e)}
    except Exception as e:
        return {'ok': False, 'description': str(e)}


def preparar_temas(temas_guardados):
    """Crea los apartados de Telegram si el grupo tiene Temas activados y el bot es administrador.
    Devuelve el diccionario clave -> message_thread_id (más el estado de Discord en '_discord')."""
    global _estado
    _estado = temas_guardados
    _estado.setdefault('_discord', {'modo': None, 'hilos': {}, 'msgs': {}})
    if not activo():
        return _estado
    chat = os.environ['TELEGRAM_CHAT_ID']
    faltan = [k for k in TEMAS if k not in _estado]
    for k in faltan:
        r = _api('createForumTopic', chat_id=chat, name=TEMAS[k], icon_color=COLOR_TEMA[k])
        if r.get('ok'):
            _estado[k] = r['result']['message_thread_id']
            print(f'creado el apartado "{TEMAS[k]}"')
        else:
            print(f'aviso: no se pudo crear el apartado "{TEMAS[k]}": {r.get("description")}. '
                  'Los avisos irán al chat general.', file=sys.stderr)
            break
    return _estado


def _clave_tema(tema):
    """De un id de tema de Telegram a su clave ('iphone_listo'...)."""
    if tema in TEMAS:
        return tema
    if tema is None:
        return None
    for k in TEMAS:
        if _estado.get(k) == tema:
            return k
    return None


# ------------------------------------------------------------------ Discord
def _md(texto):
    """HTML de Telegram -> Markdown de Discord."""
    t = re.sub(r'<a href="([^"]+)">(.*?)</a>', r'[\2](\1)', texto, flags=re.S)
    t = re.sub(r'</?b>', '**', t)
    t = re.sub(r'</?i>', '*', t)
    t = re.sub(r'<code>(.*?)</code>', lambda m: '```\n' + m.group(1) + '\n```' if '\n' in m.group(1) or len(m.group(1)) > 60
               else '`' + m.group(1) + '`', t, flags=re.S)
    t = re.sub(r'<[^>]+>', '', t)
    return html.unescape(t)


def _color(texto):
    for marca, color in (('🔥', 0xFF4655), ('💚', 0x23C38A), ('🟣', 0xB184FF), ('🤝', 0x7A8BA3), ('🔵', 0x4C8DF0),
                         ('❌', 0x5B6673), ('📉', 0x23C38A), ('⭐', 0xFFC94A), ('💰', 0x23C38A), ('🛒', 0xF5A524), ('🌙', 0x4C8DF0)):
        if marca in texto[:60]:
            return color
    return 0x4C8DF0


def _discord(metodo, ruta='', params=None, cuerpo=None):
    url = os.environ['DISCORD_WEBHOOK'].strip().rstrip('/') + ruta
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=metodo, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                 headers={'Content-Type': 'application/json', 'User-Agent': 'DiscordBot (radar-chollos, 1.0)'})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            datos = r.read()
            return r.status, json.loads(datos) if datos else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {'message': str(e)}


def _mensaje_discord(texto, botones=None, foto=None):
    md = _md(texto)
    enlaces = ' · '.join(f"[{b['text']}]({b['url']})" for fila in (botones or []) for b in fila if b.get('url'))
    if enlaces:
        md += '\n\n' + enlaces
    embed = {'description': md[:4000], 'color': _color(texto)}
    if foto:
        embed['thumbnail'] = {'url': foto}     # foto pequeña al lado: el aviso ocupa menos
    return {'embeds': [embed], 'allowed_mentions': {'parse': []}}


def _enviar_discord(texto, tema, botones=None, foto=None, clave=None):
    d = _estado.setdefault('_discord', {'modo': None, 'hilos': {}, 'msgs': {}})
    clave = clave if clave in TEMAS else (_clave_tema(tema) or 'equipo')
    cuerpo = _mensaje_discord(texto, botones, foto)
    if d.get('modo') != 'foro':
        code, r = _discord('POST', params={'wait': 'true'}, cuerpo=cuerpo)
        if code in (200, 201):
            d['modo'] = 'canal'
            return r.get('id'), None
        if code == 400 and 'thread' in json.dumps(r).lower():
            d['modo'] = 'foro'                      # el canal es un foro: hace falta un hilo por apartado
        else:
            print(f'error enviando a Discord: {code} {r.get("message")}', file=sys.stderr)
            return None, None
    hilo = d['hilos'].get(clave)
    if hilo:
        code, r = _discord('POST', params={'wait': 'true', 'thread_id': hilo}, cuerpo=cuerpo)
        if code in (200, 201):
            return r.get('id'), hilo
        d['hilos'].pop(clave, None)                 # el hilo se borró: se crea otro
    code, r = _discord('POST', params={'wait': 'true'}, cuerpo={**cuerpo, 'thread_name': TEMAS[clave]})
    if code in (200, 201):
        d['hilos'][clave] = r.get('channel_id')
        return r.get('id'), r.get('channel_id')
    print(f'error enviando a Discord: {code} {r.get("message")}', file=sys.stderr)
    return None, None


def _guardar_id_discord(clave_msg, did, hilo):
    if not did or clave_msg is None:
        return
    msgs = _estado['_discord'].setdefault('msgs', {})
    msgs[str(clave_msg)] = [did, hilo]
    if len(msgs) > 600:                              # solo hace falta recordar los recientes
        for k in list(msgs)[:len(msgs) - 600]:
            msgs.pop(k)


# ------------------------------------------------------------------ envío a los dos
def _vista(foto):
    """Foto del anuncio encima del texto (vista previa grande). Sin foto, sin vista previa."""
    if foto:
        return {'link_preview_options': {'url': foto, 'prefer_large_media': True, 'show_above_text': True}}
    return {'link_preview_options': {'is_disabled': True}}


def enviar(texto, tema=None, botones=None, silencioso=False, foto=None, clave=None):
    """Manda el aviso a Telegram y a Discord. Devuelve un id para poder editarlo luego, o None si falló todo.
    Sin ninguno configurado, lo imprime (modo prueba)."""
    if not activo() and not discord_activo():
        if foto:
            print('[foto] ' + foto)
        print(texto)
        if botones:
            print('   [' + '] ['.join(b['text'] + ' → ' + b['url'] for fila in botones for b in fila) + ']')
        print('-' * 50)
        return 0
    tid = None
    if activo():
        comun = dict(chat_id=os.environ['TELEGRAM_CHAT_ID'], parse_mode='HTML', message_thread_id=tema,
                     disable_notification='true' if silencioso else None,
                     reply_markup={'inline_keyboard': botones} if botones else None)
        r = _api('sendPhoto', photo=foto, caption=texto, **comun) if foto and len(texto) <= 1024 else {'ok': False}
        if not r.get('ok'):
            r = _api('sendMessage', text=texto, **comun, **_vista(foto))
        if r.get('ok'):
            tid = r['result']['message_id']
        else:
            print(f'error enviando a Telegram: {r.get("description")}', file=sys.stderr)
    if discord_activo():
        did, hilo = _enviar_discord(texto, tema, botones, foto, clave)
        if tid is None and did:
            tid = f'd{did}'
        _guardar_id_discord(tid, did, hilo)
    return tid


def editar(message_id, texto, botones=None, foto=None):
    if not message_id:
        return
    if activo() and not str(message_id).startswith('d'):
        r = _api('editMessageText', chat_id=os.environ['TELEGRAM_CHAT_ID'], message_id=message_id, text=texto,
                 parse_mode='HTML', reply_markup={'inline_keyboard': botones} if botones else None, **_vista(foto))
        if not r.get('ok') and 'no text' in str(r.get('description', '')).lower():      # el aviso es una foto
            _api('editMessageCaption', chat_id=os.environ['TELEGRAM_CHAT_ID'], message_id=message_id, caption=texto[:1024],
                 parse_mode='HTML', reply_markup={'inline_keyboard': botones} if botones else None)
    if discord_activo():
        par = _estado.get('_discord', {}).get('msgs', {}).get(str(message_id))
        if par:
            did, hilo = par
            _discord('PATCH', f'/messages/{did}', {'thread_id': hilo} if hilo else None, _mensaje_discord(texto, botones, foto))


def responder(message_id, texto, tema=None, clave=None):
    if not activo() and not discord_activo():
        print('↳ ' + texto)
        return
    if activo() and message_id and not str(message_id).startswith('d'):
        _api('sendMessage', chat_id=os.environ['TELEGRAM_CHAT_ID'], text=texto, parse_mode='HTML',
             message_thread_id=tema, reply_parameters={'message_id': message_id, 'allow_sending_without_reply': True},
             **_vista(None))
    if discord_activo():
        _enviar_discord(texto, tema, clave=clave)
