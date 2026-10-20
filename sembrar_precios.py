"""Rellena data/precios.json con precios de mercado actuales (ejecutar una vez al instalar,
o cuando quieras refrescar). Tarda unos minutos."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from radar import main, wallapop

CONSULTAS = ['iphone se', 'iphone xr', 'iphone xs', 'iphone 11', 'iphone 11 pro', 'iphone 11 pro max',
             'iphone 12', 'iphone 12 mini', 'iphone 12 pro', 'iphone 12 pro max',
             'iphone 13', 'iphone 13 mini', 'iphone 13 pro', 'iphone 13 pro max',
             'iphone 14', 'iphone 14 plus', 'iphone 14 pro', 'iphone 14 pro max',
             'iphone 15', 'iphone 15 plus', 'iphone 15 pro', 'iphone 15 pro max', 'iphone 16e', 'iphone 16', 'iphone 16 pro',
             'galaxy s21 fe', 'galaxy s22', 'galaxy s23', 'galaxy s23 fe', 'galaxy s24', 'galaxy s24 fe', 'galaxy s25',
             'galaxy s22 ultra', 'galaxy s23 ultra', 'galaxy s24 ultra',
             'galaxy a35', 'galaxy a36', 'galaxy a54', 'galaxy a55', 'galaxy a56',
             'pixel 7', 'pixel 7 pro', 'pixel 7a', 'pixel 8', 'pixel 8 pro', 'pixel 8a', 'pixel 9', 'pixel 9 pro',
             'redmi note 13 pro', 'redmi note 14 pro', 'xiaomi 13t', 'xiaomi 14t', 'poco x6 pro', 'poco f6']

precios = main.cargar('precios.json', {})
for q in CONSULTAS:
    n = 0
    for it in wallapop.buscar(q, 5, orden='most_relevance'):
        a = main.preparar(it)
        if not a or a['tienda']:
            continue
        est = a['est']
        if est['grave'] or est['averias'] or est['extras'] or est['roto_sin_precisar']:
            continue
        main.anotar_precio(precios, a['modelo'], a['id'], a['precio'], a['capacidad'])
        n += 1
    print(f'{q}: {n} precios')
    time.sleep(0.5)
main.guardar('precios.json', precios)
for k in sorted(precios):
    v = sorted(x[1] for x in precios[k])
    print(f'{k:22} n={len(v):3} mediana={v[len(v)//2]:.0f}')
