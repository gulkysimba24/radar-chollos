"""Lectura de anuncios de Wallapop (API pública que usa su propia web)."""
import json
import subprocess
import sys
import time
import urllib.parse

from . import config

API = 'https://api.wallapop.com/api/v3'
HEADERS = ['-H', 'X-DeviceOS: 0', '-H', 'Accept-Language: es-ES,es;q=0.9',
           '-H', 'User-Agent: Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/128 Mobile Safari/537.36']


def _get(url):
    out = subprocess.run(['curl', '-s', '-m', '25', '-w', '\n%{http_code}', *HEADERS, url],
                         capture_output=True, text=True)
    body, _, code = out.stdout.rpartition('\n')
    return int(code or 0), body


def buscar(palabras, paginas, radio_km=None, orden='newest', precio_max=None):
    """Devuelve los anuncios más nuevos de la categoría de móviles dentro del radio."""
    lat, lng = config.ORIGEN
    params = {
        'source': 'search_box', 'category_id': 24200, 'keywords': palabras,
        'latitude': lat, 'longitude': lng, 'order_by': orden,
        'distance_in_km': radio_km or config.RADIO_KM,
        'min_sale_price': config.PRECIO_MIN, 'max_sale_price': precio_max or config.PRECIO_MAX_BUSQUEDA,
    }
    url = f'{API}/search?' + urllib.parse.urlencode(params)
    items = []
    for _ in range(paginas):
        code, body = _get(url)
        if code != 200:
            print(f'aviso: Wallapop respondió {code} buscando "{palabras}"', file=sys.stderr)
            break
        try:
            j = json.loads(body)
        except ValueError:
            break
        items += j.get('data', {}).get('section', {}).get('payload', {}).get('items', [])
        nxt = j.get('meta', {}).get('next_page')
        if not nxt:
            break
        url = f'{API}/search?next_page={urllib.parse.quote(nxt)}'
        time.sleep(0.5)
    return items


def detalle(item_id):
    """Ficha completa de un anuncio. None si ya no existe (vendido o retirado)."""
    code, body = _get(f'{API}/items/{item_id}')
    if code in (404, 410):
        return None
    if code != 200:
        return 'error'
    try:
        return json.loads(body)
    except ValueError:
        return 'error'


def flag(v):
    return bool(v.get('flag')) if isinstance(v, dict) else bool(v)
