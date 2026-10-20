"""Memoria del mercado.

El bot sigue los anuncios de los modelos que tratamos (aunque no sean chollos) y comprueba
de vez en cuando si siguen a la venta. Cuando uno se vende (o desaparece) apunta el último
precio y cuántos días tardó. Con eso sabe:
  * a qué precio se vende de verdad cada modelo (no lo que se pide),
  * cuántos días tarda en venderse (qué modelos rotan rápido),
  * cuánto conviene pagar como máximo.
También aprende de vuestras compras y ventas reales (registro.json de la web).
"""
import json
import re
import statistics
import time

import analisis
import config
import wallapop

DIA = 86400000
AJUSTE_VENTA = 1.0          # se recalcula con vuestras ventas reales


def _ahora():
    return int(time.time() * 1000)


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _cuartil(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if len(xs) < 4:
        return None
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


_CAJA = re.compile(r'\bcaja\b|factura', re.I)

# ------------------------------------------------------------------ estado del móvil
# Cuánto cambia el precio según la batería, las marcas y si trae caja/factura.
# Empiezan con valores razonables y se recalculan con las ventas reales (aprender_condicion).
CONDICION_DEFECTO = {'bat': {'90+': 1.03, '85-89': 1.0, '80-84': 0.95, '<80': 0.90, '?': 0.99},
                     'marcas': 0.96, 'caja': 1.02}
F = json.loads(json.dumps(CONDICION_DEFECTO))


def tramo_bat(b, averias=()):
    if 'batería' in (averias or ()):
        return '90+'                               # se le pone batería nueva al repararlo
    if not b:
        return '?'
    return '90+' if b >= 90 else '85-89' if b >= 85 else '80-84' if b >= 80 else '<80'


def factor(b=None, averias=(), marcas=False, caja=False):
    f = F['bat'][tramo_bat(b, averias)]
    if marcas and 'pantalla' not in (averias or ()) and 'trasera' not in (averias or ()):
        f *= F['marcas']
    if caja:
        f *= F['caja']
    return f


def _factor_v(v):
    return factor(v.get('b'), v.get('av'), v.get('mk'), v.get('cj'))


def aprender_condicion(ventas):
    """Calcula con las ventas reales cuánto vale de verdad cada tramo de batería, las marcas y la caja."""
    global F
    F = json.loads(json.dumps(CONDICION_DEFECTO))
    listos = [v for v in ventas if v['t'] == 'listo' and v['como'] != 'no']
    grupos = {}
    for v in listos:
        grupos.setdefault((v['m'], v.get('c')), []).append(v['p'])
    medianas = {k: statistics.median(ps) for k, ps in grupos.items() if len(ps) >= 4}
    ratios = [(v, v['p'] / medianas[(v['m'], v.get('c'))]) for v in listos if (v['m'], v.get('c')) in medianas]
    aprendido = {}
    base = [r for v, r in ratios]
    if len(base) < 30:
        return {'aprendido': False, 'factores': F}
    m0 = statistics.median(base)
    for t in F['bat']:
        rs = [r for v, r in ratios if tramo_bat(v.get('b'), v.get('av')) == t]
        if len(rs) >= 15:
            F['bat'][t] = round(max(0.75, min(1.15, statistics.median(rs) / m0)), 3)
            aprendido['bat_' + t] = len(rs)
    for clave, campo in (('marcas', 'mk'), ('caja', 'cj')):
        si = [r for v, r in ratios if v.get(campo)]
        no = [r for v, r in ratios if not v.get(campo)]
        if len(si) >= 15 and len(no) >= 15:
            F[clave] = round(max(0.85, min(1.1, statistics.median(si) / statistics.median(no))), 3)
            aprendido[clave] = len(si)
    return {'aprendido': aprendido, 'factores': F}


# ------------------------------------------------------------------ seguir anuncios
def seguir(seguidos, a):
    """Empieza a seguir un anuncio preparado por main.preparar (o actualiza su precio)."""
    est = a['est']
    if a['familia'] != 'iphone' or est['grave'] or est['roto_sin_precisar'] or a.get('tienda'):
        return
    x = seguidos.get(a['id'])
    if x:
        x['p'] = a['precio']
        return
    if len(seguidos) >= config.MERCADO_MAX_SEGUIDOS:
        return
    ahora = _ahora()
    if a.get('publicado_ms') and ahora - a['publicado_ms'] > (config.MERCADO_DIAS_SEGUIR - 2) * DIA:
        return                                   # lleva casi un mes sin venderse: no aporta
    seguidos[a['id']] = {
        'm': a['modelo'], 'f': a['familia'], 'g': a['gama'], 'c': a.get('capacidad'), 'b': a.get('bateria'),
        't': 'reparar' if (est['averias'] or est['extras']) else 'listo', 'av': est['averias'] + est['extras'],
        'p': a['precio'], 'p0': a['precio'], 'pub': a.get('publicado_ms') or ahora, 'vis': ahora, 'rev': ahora,
        'z': a.get('zona'), 'km': a.get('km'),
        'mk': bool(est.get('marcas')), 'cj': bool(_CAJA.search(a.get('descripcion') or '')),
    }


def _cerrar(seguidos, ventas, iid, como, fin):
    x = seguidos.pop(iid)
    fin = max(min(fin, _ahora()), x['vis'])
    ventas.append({'id': iid, **{k: x.get(k) for k in ('m', 'f', 'g', 'c', 'b', 't', 'av', 'p', 'p0', 'pub', 'z', 'km')},
                   'fin': fin, 'dias': round(max(0, fin - x['pub']) / DIA, 1), 'como': como})


def revisar(seguidos, ventas):
    """Comprueba un lote de anuncios seguidos. Devuelve cuántos se han vendido o retirado."""
    ahora, cerrados = _ahora(), 0
    lote = sorted(seguidos.items(), key=lambda kv: kv[1]['rev'])[:config.MERCADO_REVISAR_POR_VEZ]
    for iid, x in lote:
        if ahora - x['rev'] < 3600000:          # ya mirado hace menos de una hora
            continue
        det = wallapop.detalle(iid)
        if det == 'error':
            x['rev'] = ahora
            continue
        if det is None:                            # desapareció entre la última revisión y ahora
            _cerrar(seguidos, ventas, iid, 'retirado', (x['rev'] + ahora) // 2)
            cerrados += 1
        else:
            precio = ((det.get('price') or {}).get('cash') or {}).get('amount')
            if precio:
                x['p'] = float(precio)
            if wallapop.flag(det.get('sold')):
                fin = int((det.get('modified_date') or ahora / 1000) * 1000)
                _cerrar(seguidos, ventas, iid, 'vendido', fin)
                cerrados += 1
            elif ahora - x['pub'] > config.MERCADO_DIAS_SEGUIR * DIA:
                _cerrar(seguidos, ventas, iid, 'no', ahora)
            else:
                if wallapop.flag(det.get('reserved')) and not x.get('res'):
                    x['res'] = ahora
                x['rev'] = ahora
        time.sleep(0.25)
    corte = ahora - config.MERCADO_DIAS_ESTUDIO * DIA
    ventas[:] = [v for v in ventas if v['fin'] >= corte][-5000:]
    return cerrados


# ------------------------------------------------------------------ lo que se aprende
def _vendidos(ventas, modelo, tipo, dias, cap=None):
    desde = _ahora() - dias * DIA
    return [v for v in ventas if v['m'] == modelo and v['t'] == tipo and v['fin'] >= desde and v['como'] != 'no'
            and (cap is None or v.get('c') == cap)]


def _limpias(vs):
    """Quita lo que engaña: anuncios retirados a las pocas horas (suelen ser re-subidas) y precios absurdos."""
    vs = [v for v in vs if not (v['como'] == 'retirado' and v['dias'] < 0.3)]
    if len(vs) < 4:
        return vs
    m = statistics.median(v['p'] / _factor_v(v) for v in vs)
    return [v for v in vs if 0.55 * m <= v['p'] / _factor_v(v) <= 1.6 * m]


def _q(xs, q):
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    k = q * (len(xs) - 1)
    i = int(k)
    return xs[i] + (xs[min(i + 1, len(xs) - 1)] - xs[i]) * (k - i)


def rango(ventas, modelo, cap=None, tipo='listo'):
    """Rango real de venta de un modelo, en estado normal (batería 85-89 %, sin marcas, sin caja).

    Devuelve {'baja', 'media', 'alta', 'n', 'fiab', 'cap', 'dias'} o None si aún no hay bastantes ventas.
    Usa primero las ventas confirmadas de esa capacidad en 60 días y, si no llegan, amplía."""
    for dias in (60, config.MERCADO_DIAS_ESTUDIO):
        for c in ([cap, None] if cap else [None]):
            todos = _limpias(_vendidos(ventas, modelo, tipo, dias, c))
            seguros = [v for v in todos if v['como'] == 'vendido']
            for conj, minimo in ((seguros, config.MERCADO_MIN_VENTAS), (todos, config.MERCADO_MIN_VENTAS + 3)):
                if len(conj) >= minimo:
                    ps = [v['p'] / _factor_v(v) for v in conj]
                    return {'baja': _q(ps, .25), 'media': statistics.median(ps), 'alta': _q(ps, .75), 'n': len(conj),
                            'fiab': 'alta' if len(conj) >= 15 and dias == 60 else 'media', 'cap': c, 'dias': dias}
    return None


def venta_real(ventas, modelo, cap):
    """Precio normal de venta (estado normal). (precio, nº ventas) o (None, 0)."""
    r = rango(ventas, modelo, cap)
    return (r['media'], r['n']) if r else (None, 0)


def dias_venta(ventas, modelo, tipo='listo'):
    """Días que suele tardar en venderse. (días, nº ventas) o (None, 0)."""
    vs = [v['dias'] for v in _limpias(_vendidos(ventas, modelo, tipo, config.MERCADO_DIAS_ESTUDIO))
          if v['dias'] <= config.MERCADO_DIAS_SEGUIR]
    if len(vs) < 3:
        return None, 0
    return round(statistics.median(vs), 1), len(vs)


def velocidad(ventas, modelo, cap=None):
    """Precio para vender rápido y precio para sacar más, con los días que suele tardar cada uno."""
    vs = _limpias(_vendidos(ventas, modelo, 'listo', config.MERCADO_DIAS_ESTUDIO, cap))
    if len(vs) < 8 and cap:
        vs = _limpias(_vendidos(ventas, modelo, 'listo', config.MERCADO_DIAS_ESTUDIO))
    if len(vs) < 8:
        return None
    norm = [(v['p'] / _factor_v(v), v['dias']) for v in vs]
    m = statistics.median(p for p, _ in norm)
    rap = [(p, d) for p, d in norm if p <= m * 0.97]
    pac = [(p, d) for p, d in norm if p >= m * 1.03]
    if len(rap) < 3 or len(pac) < 3:
        return None
    return {'rapido': {'precio': round(statistics.median(p for p, _ in rap)), 'dias': round(statistics.median(d for _, d in rap), 1)},
            'paciente': {'precio': round(statistics.median(p for p, _ in pac)), 'dias': round(statistics.median(d for _, d in pac), 1)}}


def aprender(registro, estimar_venta):
    """Ajusta el bot con vuestras compras y ventas reales.

    estimar_venta(modelo, capacidad) -> lo que el bot cree que se vende ese modelo (sin ajuste).
    Devuelve un resumen de lo aprendido para la web.
    """
    global AJUSTE_VENTA
    compras = [c for c in (registro or {}).get('compras', []) if c.get('modelo')]
    ratios = []
    for c in compras:
        if not c.get('precio_venta'):
            continue
        est = estimar_venta(c['modelo'], c.get('capacidad'))
        if est:
            ratios.append(float(c['precio_venta']) / est)
    AJUSTE_VENTA = 1.0
    if len(ratios) >= config.APRENDER_MIN_VENTAS:
        AJUSTE_VENTA = max(0.8, min(1.15, statistics.median(ratios)))
    config.AJUSTE_VENTA = AJUSTE_VENTA
    piezas = {}
    for c in compras:
        for r in c.get('reparaciones') or []:
            if r.get('pieza') and r.get('coste') not in (None, ''):
                piezas.setdefault((c['modelo'], r['pieza']), []).append(float(r['coste']))
    config.COSTES_REALES = {k: round(statistics.median(v)) for k, v in piezas.items()}
    return {
        'ajuste_venta': round(AJUSTE_VENTA, 3), 'ventas_propias': len(ratios),
        'costes_reales': [{'modelo': k[0], 'pieza': k[1], 'coste': v, 'veces': len(piezas[k])}
                          for k, v in sorted(config.COSTES_REALES.items())],
    }


# ------------------------------------------------------------------ estudio para la web
def estudio(seguidos, ventas, venta_modelo, aprendido):
    """Resumen por modelo y lista de las últimas ventas, para el apartado Estudio de la web.

    venta_modelo(modelo, cap) -> (precio de venta que usa el bot, fuente)."""
    grupos = {}
    for v in ventas:
        grupos.setdefault((v['m'], v['t'], v['f'], v.get('g')), []).append(v)
    en_venta = {}
    for x in seguidos.values():
        en_venta.setdefault((x['m'], x['t']), []).append(x['p'])
    filas = []
    for (m, t, f, g), vs in grupos.items():
        ok = _limpias([v for v in vs if v['como'] != 'no'])
        if not ok:
            continue
        precios = [v['p'] for v in ok]
        dias = [v['dias'] for v in ok if v['dias'] <= config.MERCADO_DIAS_SEGUIR]
        fila = {
            'modelo': m, 'tipo': t, 'familia': f,
            'vendidos': len(ok), 'confirmados': sum(v['como'] == 'vendido' for v in ok),
            'no_vendidos': sum(v['como'] == 'no' for v in vs),
            'precio': round(statistics.median(precios)), 'p25': _cuartil(precios, .25), 'p75': _cuartil(precios, .75),
            'dias': round(statistics.median(dias), 1) if dias else None,
            'bateria': _med([v.get('b') for v in ok]),
            'en_venta': len(en_venta.get((m, t), [])), 'precio_en_venta': _med(en_venta.get((m, t), [])),
            'fiab': 'alta' if len(ok) >= 15 else 'media' if len(ok) >= config.MERCADO_MIN_VENTAS else 'baja',
        }
        if t == 'listo':
            r = rango(ventas, m)
            if r:
                fila.update({'precio': round(r['media']), 'p25': round(r['baja']), 'p75': round(r['alta']), 'fiab': r['fiab']})
            caps = sorted({v.get('c') for v in ok if v.get('c')}, key=lambda c: (len(c), c))
            fila['caps'] = []
            for c in caps:
                rc = rango(ventas, m, c)
                if rc and rc['cap'] == c:
                    fila['caps'].append({'cap': c, 'n': rc['n'], 'baja': round(rc['baja']), 'media': round(rc['media']), 'alta': round(rc['alta'])})
            fila['velocidad'] = velocidad(ventas, m)
        venta, fuente = venta_modelo(m, None)
        if venta:
            objetivo = config.BENEFICIO_MIN[(f, t)]
            r = rango(ventas, m)
            baja = r['baja'] * 0.97 * AJUSTE_VENTA if r else venta * 0.92
            if t == 'listo':
                coste, fijo = 0, config.COSTE_FIJO['listo']
            else:
                piezas, _ = analisis.coste_piezas(f, m, g)
                coste = _med([sum(piezas.get(a, 0) for a in v.get('av') or []) for v in ok]) or 0
                fila['coste_reparacion'] = round(coste)
                fijo = config.COSTE_FIJO['reparar']
            fila['compra_buena'] = round(baja - coste - fijo - objetivo)
            fila['compra_max'] = round(venta - coste - fijo - objetivo)
            fila['compra_limite'] = round(venta - coste - fijo)
            fila['venta_lista'] = round(venta)
            fila['venta_rango'] = [round(baja), round(r['alta'] * 0.97 * AJUSTE_VENTA) if r else round(venta * 1.06)]
            fila['fuente'] = fuente
        filas.append(fila)
    filas.sort(key=lambda r: (-r['vendidos'], r['modelo']))

    ultimas = []
    for v in sorted((v for v in ventas if v['como'] != 'no'), key=lambda v: -v['fin'])[:250]:
        piezas, _ = analisis.coste_piezas(v['f'], v['m'], v.get('g'))
        ultimas.append({'modelo': v['m'], 'cap': v.get('c'), 'tipo': v['t'], 'bateria': v.get('b'),
                        'averias': [{'pieza': a, 'coste': piezas.get(a)} for a in v.get('av') or []],
                        'precio': v['p'], 'precio_inicial': v.get('p0'), 'dias': v['dias'], 'como': v['como'],
                        'fin': v['fin'], 'zona': v.get('z')})

    modelos = sorted({r['modelo'] for r in filas if r['familia'] == 'iphone'},
                     key=lambda s: [(0, int(n), '') if n.isdigit() else (1, 0, n) for n in s.replace('iPhone ', '').split()])
    tabla = {}
    for m in modelos:
        piezas, _ = analisis.coste_piezas('iphone', m, None)
        tabla[m] = {k: piezas[k] for k in ('pantalla', 'batería', 'trasera')}
    return {
        'modelos': filas, 'ultimas': ultimas, 'piezas': tabla, 'extras': config.EXTRAS,
        'seguidos': len(seguidos), 'ventas_vistas': len(ventas),
        'reglas': {'beneficio_min': {f'{k[0]}_{k[1]}': v for k, v in config.BENEFICIO_MIN.items()},
                   'coste_fijo': config.COSTE_FIJO, 'venta_factor': config.VENTA_FACTOR},
        'aprendido': aprendido, 'condicion': aprendido.get('condicion'),
    }
