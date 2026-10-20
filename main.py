"""Una revisión completa del radar: buscar, analizar, avisar, vigilar y publicar el mapa."""
import html
import json
import os
import re
import statistics
import sys
import time
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

from . import analisis, config, telegram, wallapop

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, 'data')
WEB = os.path.join(RAIZ, 'docs')
MADRID = ZoneInfo('Europe/Madrid')
CONDICION = {'new': 'nuevo', 'as_good_as_new': 'como nuevo', 'good': 'buen estado',
             'fair': 'aceptable', 'has_given_it_all': 'lo ha dado todo'}


def cargar(nombre, defecto):
    try:
        with open(os.path.join(DATOS, nombre)) as f:
            return json.load(f)
    except Exception:
        return defecto


def guardar(nombre, datos, carpeta=DATOS):
    os.makedirs(carpeta, exist_ok=True)
    tmp = os.path.join(carpeta, nombre + '.tmp')
    with open(tmp, 'w') as f:
        json.dump(datos, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, os.path.join(carpeta, nombre))


def ahora_ms():
    return int(time.time() * 1000)


def hace(ms):
    if not ms:
        return ''
    m = max(1, round((ahora_ms() - ms) / 60000))
    if m < 60:
        return f'hace {m} min'
    h = round(m / 60)
    return f'hace {h} h' if h < 48 else f'hace {round(h / 24)} días'


# ------------------------------------------------------------------ referencia de precios
def anotar_precio(precios, nombre, item_id, precio, cap):
    lista = precios.setdefault(nombre, [])
    if any(x[0] == item_id for x in lista):
        return
    lista.append([item_id, precio, ahora_ms(), cap])
    corte = ahora_ms() - 45 * 86400000
    precios[nombre] = [x for x in lista if x[2] >= corte][-150:]


def referencia(precios, nombre, cap):
    lista = precios.get(nombre, [])
    if cap:
        misma = [x[1] for x in lista if x[3] == cap]
        m = analisis.mediana(misma, 6)
        if m:
            return m
    return analisis.mediana([x[1] for x in lista], 6)


# ------------------------------------------------------------------ mensajes
def tema_de(a):
    return f"{a['familia']}_{a['eval']['tipo']}"


def botones(a):
    filas = [[{'text': '📲 Abrir anuncio', 'url': a['url']}]]
    fila2 = []
    mapa = os.environ.get('MAPA_URL')
    if mapa:
        fila2.append({'text': '🗺️ Ver en el mapa', 'url': f"{mapa.rstrip('/')}/#{a['id']}"})
    if a.get('lat') is not None:
        destino = f"{a['lat']:.5f},{a['lng']:.5f}"
        fila2.append({'text': '🚗 Cómo llegar', 'url': 'https://www.google.com/maps/dir/?api=1&' + urllib.parse.urlencode(
            {'origin': f'{config.ORIGEN_NOMBRE}, Madrid', 'destination': destino, 'travelmode': 'driving'})})
    if fila2:
        filas.append(fila2)
    return filas


def texto_aviso(a, cabecera=None):
    e, d = html.escape, a['eval']
    icono = '🍏' if a['familia'] == 'iphone' else '🤖'
    titulo = f"{icono} <b>{e(a['modelo'])}</b>" + (f" · {e(a['capacidad'])}" if a.get('capacidad') else '')
    if d['tipo'] == 'listo':
        tipo = '✅ Listo para comprar y vender'
    else:
        tipo = f"🔧 Reparación {d['nivel']}: {e(', '.join(d['reparacion']))}"
    ya = '⚡ Ya está por debajo del máximo' if a['precio'] <= d['max_pagar'] else '🤝 Hay que regatear para que salga'
    riesgo = {
        'alto': f"⚠️ <b>Muy barato ({d.get('pct_mercado')} % del precio normal).</b> Puede ser estafa, robado, financiado o tener algo oculto. "
                "Pide factura y comprueba el IMEI antes de ir. Nunca pagues por adelantado.",
        'medio': f"⚠️ Bastante por debajo de mercado ({d.get('pct_mercado')} %). Pide factura y comprueba el IMEI.",
    }.get(d.get('riesgo'))
    ben = d['beneficio_precio_pedido']
    lineas = []
    if cabecera:
        lineas += [cabecera, '']
    lineas += [titulo, tipo] + ([riesgo] if riesgo else []) + [
        '',
        f"💶 Piden <b>{a['precio']:.0f} €</b> → ofrece <b>{d['oferta']} €</b> · máximo <b>{d['max_pagar']} €</b>",
        f"📈 Se vende por ~{d['venta']} € · ganas <b>{'+' if d['beneficio_oferta'] > 0 else ''}{d['beneficio_oferta']} €</b> con tu oferta"
        f" ({'+' if ben > 0 else ''}{ben} € pagando lo que piden)",
        ya,
        f"📍 {e(a.get('zona') or 'Madrid')} · <b>~{a['km']} km</b> de {config.ORIGEN_NOMBRE}" if a.get('km') is not None
        else f"📍 {e(a.get('zona') or 'Madrid')}",
        f"🔎 {e(a['resumen'])}",
    ]
    cont = a.get('contadores') or {}
    actividad = f"🕒 Publicado {hace(a.get('publicado_ms'))}"
    if cont:
        actividad += f" · 👀 {cont.get('views', 0)} visitas · ❤️ {cont.get('favorites', 0)} · 💬 {cont.get('conversations', 0)} chats"
    lineas += [actividad, '', '<b>Pregunta antes de ir:</b>']
    lineas += [f'• {e(p)}' for p in a['preguntas']]
    lineas += ['', f"<b>Regateo:</b> {e(a['regateo'])}", '', '<b>Mensaje para copiar:</b>', f"<code>{e(a['mensaje'])}</code>"]
    return '\n'.join(lineas)


def silencio():
    h = datetime.now(MADRID).hour
    ini, fin = config.SILENCIO
    return ini <= h < fin


# ------------------------------------------------------------------ revisión
def preparar(item):
    """Datos básicos de un anuncio de la búsqueda, o None si no es un móvil que tratemos."""
    titulo = item.get('title') or ''
    if analisis.es_accesorio(titulo):
        return None
    m = analisis.modelo(titulo)
    if not m:
        return None
    if wallapop.flag(item.get('reserved')) or wallapop.flag(item.get('is_refurbished')) or wallapop.flag(item.get('has_warranty')):
        return None
    desc = item.get('description') or ''
    loc = item.get('location') or {}
    texto = f'{titulo} {desc}'
    return {
        'id': item['id'], 'familia': m[0], 'modelo': m[1], 'gama': m[2], 'titulo': titulo, 'descripcion': desc[:2000],
        'precio': float(item['price']['amount']), 'capacidad': analisis.capacidad(texto), 'bateria': analisis.bateria(texto),
        'zona': loc.get('city'), 'lat': loc.get('latitude'), 'lng': loc.get('longitude'),
        'km': analisis.km(loc.get('latitude'), loc.get('longitude')),
        'url': f"https://es.wallapop.com/item/{item.get('web_slug')}", 'publicado_ms': item.get('created_at'),
        'tienda': wallapop.flag(item.get('is_top_profile')),
        'est': analisis.estado(titulo, desc),
    }


def completar(a):
    """Añade datos de la ficha completa: estado según Wallapop, capacidad, visitas."""
    det = wallapop.detalle(a['id'])
    if det is None:
        return False
    if isinstance(det, dict):
        ta = det.get('type_attributes') or {}
        cond = (ta.get('condition') or {}).get('value')
        a['condicion'] = CONDICION.get(cond, '')
        cap = (ta.get('storage_capacity') or {}).get('text')
        if cap and not a.get('capacidad'):
            a['capacidad'] = cap
        a['contadores'] = det.get('counters') or {}
        if cond == 'has_given_it_all' and a['eval']['tipo'] == 'listo':
            return False               # el propio vendedor dice que está muy gastado
    return True


def ficha_web(a, estado='activo'):
    d = a['eval']
    return {
        'id': a['id'], 'familia': a['familia'], 'tipo': d['tipo'], 'nivel': d['nivel'], 'modelo': a['modelo'],
        'capacidad': a.get('capacidad'), 'precio': a['precio'], 'oferta': d['oferta'], 'max': d['max_pagar'],
        'venta': d['venta'], 'beneficio': d['beneficio_oferta'], 'reparacion': d['reparacion'],
        'zona': a.get('zona'), 'km': a.get('km'), 'lat': a.get('lat'), 'lng': a.get('lng'), 'url': a['url'],
        'resumen': a['resumen'], 'preguntas': a['preguntas'], 'regateo': a['regateo'], 'mensaje': a['mensaje'],
        'publicado_ms': a.get('publicado_ms'), 'avisado_ms': a.get('avisado_ms'), 'estado': estado,
        'riesgo': d.get('riesgo'), 'pct_mercado': d.get('pct_mercado'),
        'precio_inicial': a.get('precio_inicial', a['precio']),
    }


def avisar(a, temas, activos, cabecera=None):
    a['resumen'], a['preguntas'], a['regateo'], a['mensaje'] = analisis.textos(a)
    a['avisado_ms'] = ahora_ms()
    msg = telegram.enviar(texto_aviso(a, cabecera), temas.get(tema_de(a)), botones(a), silencioso=silencio())
    if msg is None:
        return False
    a['msg_id'] = msg
    activos[a['id']] = {k: v for k, v in a.items() if k != 'est'} | {'est': a['est']}
    return True


def revisar_conocidos(activos, vigilar, temas, precios):
    """Comprueba si los chollos avisados siguen a la venta o han bajado, y si alguno vigilado ya es chollo."""
    avisos = 0
    limite = ahora_ms() - config.DIAS_ACTIVO * 86400000
    pendientes = sorted([a for a in activos.values() if a.get('estado', 'activo') == 'activo' and a['avisado_ms'] >= limite],
                        key=lambda a: a.get('revisado_ms', 0))[:40]
    for a in pendientes:
        det = wallapop.detalle(a['id'])
        a['revisado_ms'] = ahora_ms()
        if det == 'error':
            continue
        if det is None:
            a['estado'] = 'vendido'
            telegram.editar(a.get('msg_id'), '❌ <b>Ya no está a la venta</b> (vendido o retirado)\n\n' + texto_aviso(a))
            continue
        nuevo = float(((det.get('price') or {}).get('cash') or {}).get('amount') or a['precio'])
        if nuevo < a['precio'] - 0.5:
            antes = a['precio']
            a.setdefault('precio_inicial', antes)
            a['precio'] = nuevo
            ref = referencia(precios, a['modelo'], a.get('capacidad'))
            v, d = analisis.evaluar(a, ref or a['eval']['ref_mercado'])
            if d:
                a['eval'] = d
            a['resumen'], a['preguntas'], a['regateo'], a['mensaje'] = analisis.textos(a)
            telegram.editar(a.get('msg_id'), f'📉 <b>Ha bajado de {antes:.0f} € a {nuevo:.0f} €</b>\n\n' + texto_aviso(a), botones(a))
            telegram.responder(a.get('msg_id'), f'📉 {html.escape(a["modelo"])} ha bajado a <b>{nuevo:.0f} €</b>', temas.get(tema_de(a)))
            avisos += 1
        time.sleep(0.4)

    for vid, a in sorted(vigilar.items(), key=lambda kv: kv[1].get('revisado_ms', 0))[:30]:
        det = wallapop.detalle(vid)
        a['revisado_ms'] = ahora_ms()
        if det is None or a['avisado_ms_vigilar'] < ahora_ms() - 10 * 86400000:
            vigilar.pop(vid, None)
            continue
        if det == 'error':
            continue
        nuevo = float(((det.get('price') or {}).get('cash') or {}).get('amount') or a['precio'])
        if nuevo < a['precio'] - 0.5:
            antes = a['precio']
            a['precio'] = nuevo
            ref = referencia(precios, a['modelo'], a.get('capacidad')) or a.get('ref')
            veredicto, d = analisis.evaluar(a, ref)
            if veredicto == 'avisar':
                a['eval'] = d
                a['precio_inicial'] = antes
                if completar(a) and avisar(a, temas, activos, cabecera=f'📉 <b>Ha bajado de {antes:.0f} € a {nuevo:.0f} €</b>'):
                    avisos += 1
                vigilar.pop(vid, None)
        time.sleep(0.4)
    return avisos


def exportar(activos):
    limite = ahora_ms() - config.DIAS_ACTIVO * 86400000
    lista = []
    for a in activos.values():
        if a['avisado_ms'] < limite:
            continue
        if a.get('estado') == 'vendido' and a.get('revisado_ms', 0) < ahora_ms() - 86400000:
            continue
        lista.append(ficha_web(a, a.get('estado', 'activo')))
    lista.sort(key=lambda x: -x['avisado_ms'])
    guardar('chollos.json', {'actualizado_ms': ahora_ms(), 'origen': {'nombre': config.ORIGEN_NOMBRE, 'lat': config.ORIGEN[0], 'lng': config.ORIGEN[1]},
                             'chollos': lista}, carpeta=WEB)


def ejecutar():
    precios = cargar('precios.json', {})
    vistos = cargar('vistos.json', {})
    activos = cargar('activos.json', {})
    vigilar = cargar('vigilar.json', {})
    temas = telegram.preparar_temas(cargar('temas.json', {}))

    vistos_items, nuevos = {}, []
    for palabras, paginas in config.BUSQUEDAS:
        for it in wallapop.buscar(palabras, paginas):
            if it['id'] in vistos_items:
                continue
            a = preparar(it)
            vistos_items[it['id']] = True
            if not a:
                continue
            est = a['est']
            limpio = not (est['grave'] or est['averias'] or est['extras'] or est['roto_sin_precisar'])
            if limpio and not a['tienda']:
                anotar_precio(precios, a['modelo'], a['id'], a['precio'], a['capacidad'])
            if a['id'] in vistos or a['id'] in activos or a['id'] in vigilar or a['tienda']:
                continue
            nuevos.append(a)

    avisados = 0
    candidatos = []
    for a in nuevos:
        ref = referencia(precios, a['modelo'], a['capacidad'])
        veredicto, d = analisis.evaluar(a, ref)
        if veredicto == 'vigilar':
            a['eval'], a['ref'], a['avisado_ms_vigilar'] = d, ref, ahora_ms()
            vigilar[a['id']] = {k: v for k, v in a.items()}
        elif veredicto == 'avisar':
            a['eval'] = d
            candidatos.append(a)
        if ref:                      # sin precio de referencia aún: se mirará otra vez cuando lo haya
            vistos[a['id']] = ahora_ms()

    candidatos.sort(key=lambda a: -a['eval']['beneficio_oferta'])
    for a in candidatos:
        if completar(a) and avisar(a, temas, activos):
            avisados += 1
        time.sleep(1)

    bajadas = revisar_conocidos(activos, vigilar, temas, precios)

    corte = ahora_ms() - 20 * 86400000
    vistos = {k: v for k, v in vistos.items() if v >= corte}
    activos = {k: v for k, v in activos.items() if v['avisado_ms'] >= corte}
    for nombre, datos in (('precios.json', precios), ('vistos.json', vistos), ('activos.json', activos),
                          ('vigilar.json', vigilar), ('temas.json', temas)):
        guardar(nombre, datos)
    exportar(activos)
    print(f'{len(vistos_items)} anuncios revisados · {len(nuevos)} nuevos de modelos que tratamos · '
          f'{avisados} avisos · {bajadas} bajadas de precio · {len(vigilar)} vigilados · '
          f'{sum(len(v) for v in precios.values())} precios de referencia en {len(precios)} modelos')


if __name__ == '__main__':
    ejecutar()
