"""Envío de avisos a un grupo de Telegram, con un tema (apartado) por tipo de chollo."""
import json
import os
import sys
import urllib.parse
import urllib.request

TEMAS = {
    'iphone_listo': '🍏 iPhone · Listos para vender',
    'iphone_reparar': '🔧 iPhone · Para reparar',
    'android_listo': '🤖 Android · Listos para vender',
    'android_reparar': '🛠️ Android · Para reparar',
}
COLOR_TEMA = {'iphone_listo': 7322096, 'iphone_reparar': 16766590, 'android_listo': 9367192, 'android_reparar': 16749490}


def activo():
    return bool(os.environ.get('TELEGRAM_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID'))


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
    """Crea los 4 apartados si el grupo tiene Temas activados y el bot es administrador.
    Devuelve el diccionario clave -> message_thread_id (vacío si no se puede: todo va al chat general)."""
    if not activo():
        return temas_guardados
    chat = os.environ['TELEGRAM_CHAT_ID']
    faltan = [k for k in TEMAS if k not in temas_guardados]
    for k in faltan:
        r = _api('createForumTopic', chat_id=chat, name=TEMAS[k], icon_color=COLOR_TEMA[k])
        if r.get('ok'):
            temas_guardados[k] = r['result']['message_thread_id']
            print(f'creado el apartado "{TEMAS[k]}"')
        else:
            print(f'aviso: no se pudo crear el apartado "{TEMAS[k]}": {r.get("description")}. '
                  'Los avisos irán al chat general.', file=sys.stderr)
            break
    return temas_guardados


def enviar(texto, tema=None, botones=None, silencioso=False):
    """Manda el aviso. Devuelve el message_id o None. Sin token, lo imprime (modo prueba)."""
    if not activo():
        print(texto)
        if botones:
            print('   [' + '] ['.join(b['text'] + ' → ' + b['url'] for fila in botones for b in fila) + ']')
        print('-' * 50)
        return 0
    r = _api('sendMessage', chat_id=os.environ['TELEGRAM_CHAT_ID'], text=texto, parse_mode='HTML',
             message_thread_id=tema, disable_web_page_preview='true', disable_notification='true' if silencioso else None,
             reply_markup={'inline_keyboard': botones} if botones else None)
    if r.get('ok'):
        return r['result']['message_id']
    print(f'error enviando a Telegram: {r.get("description")}', file=sys.stderr)
    return None


def editar(message_id, texto, botones=None):
    if not activo() or not message_id:
        return
    _api('editMessageText', chat_id=os.environ['TELEGRAM_CHAT_ID'], message_id=message_id, text=texto,
         parse_mode='HTML', disable_web_page_preview='true',
         reply_markup={'inline_keyboard': botones} if botones else None)


def responder(message_id, texto, tema=None):
    if not activo():
        print('↳ ' + texto)
        return
    _api('sendMessage', chat_id=os.environ['TELEGRAM_CHAT_ID'], text=texto, parse_mode='HTML',
         message_thread_id=tema, reply_parameters={'message_id': message_id, 'allow_sending_without_reply': True})
