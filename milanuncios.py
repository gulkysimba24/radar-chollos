"""Lectura de anuncios de Milanuncios (la API de búsqueda que usa su propia web).

La web de Milanuncios bloquea a los bots, pero su buscador interno responde sin problema.
No da coordenadas, solo el pueblo: se convierte a coordenadas con OpenStreetMap y se guarda
en municipios.json para no volver a preguntarlo.
"""
import calendar
import json
import os
import subprocess
import sys
import time
import urllib.parse

import config

API = 'https://searchapi.gw.milanuncios.com/v3/classifieds'
UA = 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/128 Mobile Safari/537.36'
RAIZ = os.path.dirname(os.path.abspath(__file__))
CATEGORIA_IPHONE = 1270
CATEGORIA_MOVILES = 112
_municipios = None


def _get(url):
    out = subprocess.run(['curl', '-s', '-m', '25', '-w', '\n%{http_code}', '-A', UA, '-H', 'Accept-Language: es-ES', url],
                         capture_output=True, text=True)
    body, _, code = out.stdout.rpartition('\n')
    try:
        return int(code or 0), json.loads(body) if body else {}
    except ValueError:
        return int(code or 0), {}


def _municipio(nombre):
    """Coordenadas aproximadas de un pueblo de la Comunidad de Madrid (con caché)."""
    global _municipios
    ruta = os.path.join(RAIZ, 'municipios.json')
    if _municipios is None:
        try:
            with open(ruta) as f:
                _municipios = json.load(f)
        except Exception:
            _municipios = {}
    if not nombre:
        return None
    if nombre in _municipios:
        return _municipios[nombre]
    q = urllib.parse.urlencode({'format': 'json', 'limit': 1, 'countrycodes': 'es', 'q': f'{nombre}, Comunidad de Madrid'})
    out = subprocess.run(['curl', '-s', '-m', '20', '-A', 'radar-chollos/1.0 (uso personal)',
                          f'https://nominatim.openstreetmap.org/search?{q}'], capture_output=True, text=True).stdout
    time.sleep(1.1)                             # norma de uso de OpenStreetMap: 1 consulta por segundo
    try:
        j = json.loads(out)
        punto = [float(j[0]['lat']), float(j[0]['lon'])] if j else None
    except Exception:
        return None                             # error de red: se intentará otro día
    _municipios[nombre] = punto
    tmp = ruta + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(_municipios, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, ruta)
    return punto


def a_item(ad):
    """Convierte un anuncio de Milanuncios al formato de Wallapop para analizarlo igual."""
    loc = ad.get('location') or {}
    ciudad = ((loc.get('city') or {}).get('name') or '').strip()
    geo = loc.get('geolocation') or {}
    punto = [geo.get('latitude'), geo.get('longitude')] if geo.get('latitude') else _municipio(ciudad)
    pub = ad.get('publicationDate') or ad.get('sortDate')
    try:
        pub_ms = calendar.timegm(time.strptime(pub[:19], '%Y-%m-%dT%H:%M:%S')) * 1000 if pub else None
    except ValueError:
        pub_ms = None
    attrs = {(x.get('field') or {}).get('raw'): (x.get('value') or {}).get('raw') for x in ad.get('attributes') or []}
    return {
        'id': 'ma-' + str(ad['id']), 'title': ad.get('title') or '', 'description': ad.get('description') or '',
        'price': {'amount': float(((ad.get('price') or {}).get('cash') or {}).get('value') or 0)},
        'images': [], 'location': {'city': ciudad, 'latitude': punto[0] if punto else None, 'longitude': punto[1] if punto else None},
        'web_slug': None, 'url': 'https://www.milanuncios.com' + (ad.get('url') or ''), 'created_at': pub_ms,
        'reserved': None, 'is_refurbished': None, 'has_warranty': None,
        'is_top_profile': {'flag': ad.get('type') not in (None, 'private')},
        'origen': 'milanuncios', 'condicion_ma': attrs.get('itemCondition'),
    }


def buscar(texto, cuantos=100, categoria=CATEGORIA_IPHONE):
    """Los anuncios más nuevos de la Comunidad de Madrid (de 100 en 100)."""
    items = []
    for offset in range(0, cuantos, 100):
        q = urllib.parse.urlencode({'text': texto, 'province': 28, 'category': categoria, 'sort': 'date',
                                    'limit': 100, 'offset': offset})
        code, j = _get(f'{API}?{q}')
        if code != 200:
            print(f'aviso: Milanuncios respondió {code} buscando "{texto}"', file=sys.stderr)
            break
        ads = j.get('ads') or []
        items += [a_item(ad) for ad in ads if ad.get('transaction', 'supply') == 'supply']
        if len(ads) < 100:
            break
        time.sleep(0.5)
    return [i for i in items if i['price']['amount'] >= config.PRECIO_MIN]


def detalle(item_id):
    """Ficha de un anuncio en el formato de Wallapop. None si ya no está publicado."""
    code, j = _get(f"{API}?ids={item_id.replace('ma-', '')}")
    if code != 200:
        return 'error'
    ads = j.get('ads') or []
    if not ads:
        return None
    ad = ads[0]
    return {'id': item_id, 'title': {'original': ad.get('title')}, 'description': {'original': ad.get('description')},
            'price': {'cash': {'amount': ((ad.get('price') or {}).get('cash') or {}).get('value')}},
            'sold': None, 'reserved': None, 'type_attributes': {}, 'counters': {}, 'user': {}, 'images': [],
            'location': {'city': ((ad.get('location') or {}).get('city') or {}).get('name')},
            'slug': None, 'url': 'https://www.milanuncios.com' + (ad.get('url') or '')}
