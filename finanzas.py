"""Cuentas del negocio a partir de registro.json (lo que apuntáis en la web).

registro.json:
  compras:     [{id, modelo, capacidad, precio_compra, reparaciones, gasolina, otros, fecha_compra,
                 precio_venta, fecha_venta, publicado: {precio, url, fecha}, ...}]
  movimientos: [{id, fecha, quien, tipo: 'aporte'|'retirada', importe, nota}]
  meses:       {'2026-10': {'presupuesto': 600}}
  ajustes:     {'extra': 200}      # lo que podéis poner de más si sale un chollo caro
"""
import statistics
from datetime import date


def _n(v):
    try:
        return float(v) if v not in (None, '') else 0.0
    except (TypeError, ValueError):
        return 0.0


def coste(c):
    return (_n(c.get('precio_compra')) + sum(_n(r.get('coste')) for r in c.get('reparaciones') or [])
            + _n(c.get('gasolina')) + _n(c.get('otros')))


def vendida(c):
    return c.get('precio_venta') not in (None, '')


def resumen(registro):
    """Caja disponible, dinero total, aportado, beneficio... None si aún no habéis apuntado aportes."""
    registro = registro or {}
    movs = registro.get('movimientos') or []
    if not movs:
        return None
    compras = [c for c in registro.get('compras') or [] if c.get('modelo')]
    aportado = sum(_n(m.get('importe')) * (1 if m.get('tipo') == 'aporte' else -1) for m in movs)
    gastado = sum(coste(c) for c in compras)
    ingresado = sum(_n(c['precio_venta']) for c in compras if vendida(c))
    stock = [c for c in compras if not vendida(c)]
    caja = aportado - gastado + ingresado
    extra = _n((registro.get('ajustes') or {}).get('extra'))
    return {'caja': round(caja, 2), 'aportado': round(aportado, 2), 'en_stock': round(sum(coste(c) for c in stock), 2),
            'total': round(caja + sum(coste(c) for c in stock), 2), 'extra': extra, 'disponible': round(caja + extra, 2),
            'beneficio': round(sum(_n(c['precio_venta']) - coste(c) for c in compras if vendida(c)), 2)}


def objetivo(registro, mes=None):
    """Objetivo realista de beneficio para el mes, según el presupuesto y cómo os va."""
    registro = registro or {}
    mes = mes or date.today().strftime('%Y-%m')
    r = resumen(registro) or {}
    presupuesto = _n(((registro.get('meses') or {}).get(mes) or {}).get('presupuesto')) or r.get('total') or 0
    vend = [c for c in registro.get('compras') or [] if vendida(c) and c.get('modelo')]
    if len(vend) >= 3:
        margen = sum(_n(c['precio_venta']) - coste(c) for c in vend) / max(1, sum(coste(c) for c in vend))
        dias = [(date.fromisoformat(c['fecha_venta']) - date.fromisoformat(c['fecha_compra'])).days
                for c in vend if c.get('fecha_venta') and c.get('fecha_compra')]
        ciclo = (statistics.mean(dias) if dias else 10) + 4
    else:
        margen, ciclo = 0.15, 14
    vueltas = max(1.0, min(4.0, 30 / ciclo))
    teorico = presupuesto * max(margen, 0.05) * vueltas
    return {'mes': mes, 'presupuesto': presupuesto, 'margen': round(margen, 3), 'vueltas': round(vueltas, 1),
            'minimo': round(teorico * 0.5 / 5) * 5, 'realista': round(teorico * 0.8 / 5) * 5, 'ambicioso': round(teorico * 1.25 / 5) * 5}
