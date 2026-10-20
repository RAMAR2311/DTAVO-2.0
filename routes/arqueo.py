from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Sale, SalePayment, ArqueoCaja, Expense, SobranteLog
from sqlalchemy.orm import joinedload
from decorators import admin_required
from datetime import datetime, date
from decimal import Decimal
import re
import pytz

arqueo_bp = Blueprint('arqueo_bp', __name__)

def obtener_hora_bogota():
    return datetime.now(pytz.timezone('America/Bogota')).replace(tzinfo=None)

def calcular_totales_dia(ventas_del_dia):
    """Calcula los totales de efectivo, transferencias y retomas del día.
    Usa SalePayment si está disponible, de lo contrario usa metodo_pago legacy."""
    total_efectivo = Decimal('0')
    total_transferencia = Decimal('0')
    total_retomas = Decimal('0')
    
    for v in ventas_del_dia:
        if v.pagos:  # Ventas nuevas con tabla sale_payments
            for pago in v.pagos:
                if pago.metodo_pago == 'efectivo':
                    total_efectivo += pago.monto
                elif pago.metodo_pago == 'retoma':
                    total_retomas += pago.monto
                else:  # nequi, bancolombia, daviplata, transferencia, etc
                    total_transferencia += pago.monto
        else:  # Retrocompatibilidad con ventas antiguas
            if v.metodo_pago == 'efectivo':
                total_efectivo += v.monto_total
            elif v.metodo_pago == 'retoma':
                total_retomas += v.monto_total
            elif v.metodo_pago in ['addi', 'sitecredito', 'bancolombia', 'davivienda', 'tarjeta_credito', 'transferencia']:
                total_transferencia += v.monto_total

        # Sumar retomas registradas en la nueva tabla (como descuento)
        if getattr(v, 'retomas_asociadas', None):
            for retoma in v.retomas_asociadas:
                total_retomas += retoma.valor_retoma
    
    return total_efectivo, total_transferencia, total_retomas

def calcular_desglose_metodos_dia(ventas_del_dia):
    """Calcula el total recaudado desglosado exactamente por cada método de pago individual."""
    desglose = {}
    for v in ventas_del_dia:
        if v.pagos:
            for p in v.pagos:
                metodo = p.metodo_pago.lower() if p.metodo_pago else 'efectivo'
                if metodo != 'retoma':
                    desglose[metodo] = desglose.get(metodo, Decimal('0')) + Decimal(str(p.monto or 0))
        else:
            metodo = v.metodo_pago.lower() if v.metodo_pago else 'efectivo'
            if metodo != 'retoma':
                desglose[metodo] = desglose.get(metodo, Decimal('0')) + Decimal(str(v.monto_total or 0))
    return desglose

def procesar_unidades_ch(ventas):
    desglose = []
    total_general_ch = Decimal('0')
    
    for v in ventas:
        for detalle in v.detalles:
            nombre = ""
            if detalle.producto:
                nombre = detalle.producto.nombre
            elif detalle.nombre_manual:
                nombre = detalle.nombre_manual
                
            subcategoria = ""
            if detalle.variante:
                subcategoria = detalle.variante.nombre_variante
            
            # Buscar el patrón 'CH', opcionalmente con espacio y/o 'x', seguido de un número
            match_nombre = re.search(r'CH\s*x?(\d+)', nombre, re.IGNORECASE)
            match_sub = re.search(r'CH\s*x?(\d+)', subcategoria, re.IGNORECASE)
            
            valor_extraido = None
            error_formato = False
            
            # Prioridad: nombre del producto
            if match_nombre:
                try:
                    valor_extraido = int(match_nombre.group(1))
                except ValueError:
                    error_formato = True
            elif match_sub:
                try:
                    valor_extraido = int(match_sub.group(1))
                except ValueError:
                    error_formato = True
            else:
                # Si se detecta 'CH' pero no hay un número válido después
                if re.search(r'CH', nombre, re.IGNORECASE) or re.search(r'CH', subcategoria, re.IGNORECASE):
                    error_formato = True
            
            if valor_extraido is not None:
                valor_unitario = valor_extraido * 1000
                cantidad = detalle.cantidad_vendida
                subtotal = Decimal(str(valor_unitario * cantidad))
                
                desglose.append({
                    'nombre': f"{nombre} ({subcategoria})" if subcategoria else nombre,
                    'cantidad': cantidad,
                    'valor_unitario': valor_unitario,
                    'subtotal': subtotal,
                    'error': False
                })
                total_general_ch += subtotal
            elif error_formato:
                desglose.append({
                    'nombre': f"{nombre} ({subcategoria})" if subcategoria else nombre,
                    'cantidad': detalle.cantidad_vendida,
                    'valor_unitario': 0,
                    'subtotal': Decimal('0'),
                    'error': 'Error de formato en descripción'
                })
                
    return desglose, total_general_ch

def procesar_celulares(ventas):
    total_celulares = Decimal('0')
    for v in ventas:
        for detalle in v.detalles:
            if detalle.producto and detalle.producto.tipo_inventario == 'celulares':
                if detalle.variant_id and detalle.variante:
                    costo = detalle.variante.precio_costo or 0
                else:
                    costo = detalle.producto.precio_costo or 0
                total_celulares += Decimal(str(costo * detalle.cantidad_vendida))
    return total_celulares

@arqueo_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo():
    # Obtener fecha de la URL o usar hoy
    fecha_str = request.args.get('fecha', obtener_hora_bogota().strftime('%Y-%m-%d'))
    try:
        fecha_seleccionada = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        fecha_seleccionada = obtener_hora_bogota().date()
        fecha_str = fecha_seleccionada.strftime('%Y-%m-%d')

    # Determinar la sucursal a arqueár
    sucursal_actual = current_user.sucursal
    if current_user.rol == 'admin':
        sucursal_actual = request.values.get('sucursal', current_user.sucursal)

    # Calcular ventas del día de la sucursal actual
    ventas_del_dia = Sale.query.filter(
        db.func.date(Sale.fecha_venta) == fecha_seleccionada,
        Sale.tipo_venta.in_(['general', 'celulares']),
        Sale.sucursal == sucursal_actual
    ).order_by(Sale.fecha_venta.asc()).all()
    total_efectivo, total_transferencia, total_retomas = calcular_totales_dia(ventas_del_dia)

    # Calcular gastos automáticos del día
    gastos_diarios_registros = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) == fecha_seleccionada,
        Expense.tipo_gasto == 'Gasto Diario',
        Expense.sucursal == sucursal_actual
    ).all()
    gastos_automaticos = float(sum(g.monto for g in gastos_diarios_registros))

    # Calcular gastos por productos externos del día
    gastos_externos_registros = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) == fecha_seleccionada,
        Expense.categoria == 'Pago Prod. Externo',
        Expense.sucursal == sucursal_actual
    ).all()
    gastos_externos = float(sum(g.monto for g in gastos_externos_registros))

    # Verificar si ya existe un arqueo para esa sucursal en esa fecha
    arqueo_existente = ArqueoCaja.query.filter_by(fecha_arqueo=fecha_seleccionada, tipo_arqueo='general', sucursal=sucursal_actual).first()

    if request.method == 'POST':
        # Doble verificación en el backend para evitar duplicados por concurrencia
        if ArqueoCaja.query.filter_by(fecha_arqueo=fecha_seleccionada, tipo_arqueo='general', sucursal=sucursal_actual).first():
            flash('Ya existe un arqueo cerrado para esta fecha y sucursal. No se puede duplicar.', 'warning')
            return redirect(url_for('arqueo_bp.reporte', fecha_inicio=fecha_str, fecha_fin=fecha_str))

        base_inicial = float(request.form.get('base_inicial', 0.0))
        efectivo_fisico_val = float(request.form.get('efectivo_fisico', 0.0) or 0.0)
        observacion_diferencia = request.form.get('observacion_diferencia', '').strip()
        
        # Recalcular gastos automáticos por seguridad en el backend
        gastos_recalculados = Expense.query.filter(
            db.func.date(Expense.fecha_gasto) == fecha_seleccionada,
            Expense.tipo_gasto == 'Gasto Diario',
            Expense.sucursal == sucursal_actual
        ).all()
        gastos_del_dia = float(sum(g.monto for g in gastos_recalculados))
        
        observaciones_gastos = request.form.get('observaciones_gastos', '').strip()

        # Calcular monto esperado en efectivo y diferencia (Sobrante / Faltante)
        esperado_efectivo = float(base_inicial) + float(total_efectivo) - float(gastos_del_dia)
        diferencia_val = efectivo_fisico_val - esperado_efectivo

        nuevo_arqueo = ArqueoCaja(
            vendedor_id=current_user.id,
            fecha_arqueo=fecha_seleccionada,
            base_inicial=base_inicial,
            gastos_del_dia=gastos_del_dia,
            observaciones_gastos=observaciones_gastos,
            total_efectivo_sistema=total_efectivo,
            total_transferencia_sistema=total_transferencia,
            total_unidades_ch=Decimal('0.00'),
            total_celulares=Decimal('0.00'),
            total_retomas_sistema=total_retomas,
            tipo_arqueo='general',
            sucursal=sucursal_actual,
            efectivo_fisico=efectivo_fisico_val,
            diferencia=diferencia_val,
            observacion_diferencia=observacion_diferencia
        )

        try:
            db.session.add(nuevo_arqueo)
            db.session.flush()

            # Si hay un SOBRANTE de caja (diferencia a favor > 0), registrar en el Log de Sobrantes
            if diferencia_val > 0:
                log_sobrante = SobranteLog(
                    arqueo_id=nuevo_arqueo.id,
                    vendedor_id=current_user.id,
                    sucursal=sucursal_actual,
                    fecha_arqueo=fecha_seleccionada,
                    monto_esperado=Decimal(str(esperado_efectivo)),
                    efectivo_fisico=Decimal(str(efectivo_fisico_val)),
                    monto_sobrante=Decimal(str(diferencia_val)),
                    justificacion=observacion_diferencia
                )
                db.session.add(log_sobrante)

            # --- INTEGRACIÓN CON MÓDULO BANCOS ---
            # Sumar lo recaudado por cada método de pago individual a su respectiva cuenta bancaria
            from services.bank_service import registrar_movimiento_banco
            desglose_bancos = calcular_desglose_metodos_dia(ventas_del_dia)
            for metodo_cod, monto_metodo in desglose_bancos.items():
                if monto_metodo > 0:
                    registrar_movimiento_banco(
                        codigo_metodo=metodo_cod,
                        monto=monto_metodo,
                        tipo_movimiento='INGRESO',
                        origen='ARQUEO_CIERRE',
                        descripcion=f'Cierre de Arqueo #{nuevo_arqueo.id} ({sucursal_actual} - {fecha_seleccionada})',
                        referencia_id=nuevo_arqueo.id,
                        usuario_id=current_user.id
                    )

            db.session.commit()
            flash('Arqueo de caja guardado exitosamente y acreditado al Módulo de Bancos.', 'success')
            return redirect(url_for('arqueo_bp.reporte', fecha_inicio=fecha_str, fecha_fin=fecha_str))
        except Exception as e:
            db.session.rollback()
            flash(f'Ocurrió un error al guardar el arqueo de caja: {str(e)}', 'danger')

    return render_template(
        'arqueo/form.html',
        fecha=fecha_str,
        total_efectivo=total_efectivo,
        total_transferencia=total_transferencia,
        arqueo_existente=arqueo_existente,
        gastos_automaticos=gastos_automaticos,
        gastos_externos=gastos_externos,
        ventas_del_dia=ventas_del_dia,
        sucursal_seleccionada=sucursal_actual
    )

@arqueo_bp.route('/reporte', methods=['GET'])
@login_required
def reporte():
    fecha_inicio_str = request.args.get('fecha_inicio', obtener_hora_bogota().strftime('%Y-%m-%d'))
    fecha_fin_str = request.args.get('fecha_fin', obtener_hora_bogota().strftime('%Y-%m-%d'))

    try:
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
    except ValueError:
        fecha_inicio = obtener_hora_bogota().date()
        fecha_fin = obtener_hora_bogota().date()

    # BLOQUEO DE SEGURIDAD: Los vendedores no pueden ver días anteriores
    if current_user.rol != 'admin':
        hoy = obtener_hora_bogota().date()
        fecha_inicio = hoy
        fecha_fin = hoy
        fecha_inicio_str = hoy.strftime('%Y-%m-%d')
        fecha_fin_str = hoy.strftime('%Y-%m-%d')

    # Arqueo unificado: los administradores ven todos los locales, los vendedores solo su local
    query = ArqueoCaja.query.filter(
        ArqueoCaja.fecha_arqueo >= fecha_inicio,
        ArqueoCaja.fecha_arqueo <= fecha_fin,
        ArqueoCaja.tipo_arqueo == 'general'
    )
    
    if current_user.rol != 'admin':
        query = query.filter(ArqueoCaja.sucursal == current_user.sucursal)

    arqueos = query.order_by(ArqueoCaja.fecha_arqueo.desc()).all()

    # Cálculos globales para el reporte
    resumen = {
        'total_base': sum(a.base_inicial for a in arqueos),
        'total_efectivo': sum(a.total_efectivo_sistema for a in arqueos),
        'total_transferencia': sum(a.total_transferencia_sistema for a in arqueos),
        'total_gastos': sum(a.gastos_del_dia for a in arqueos)
    }
    

    
    # Calcular los gastos por productos externos en este rango de fechas
    gastos_externos_query = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) >= fecha_inicio,
        db.func.date(Expense.fecha_gasto) <= fecha_fin,
        Expense.categoria == 'Pago Prod. Externo'
    )
    if current_user.rol != 'admin':
        gastos_externos_query = gastos_externos_query.filter(Expense.sucursal == current_user.sucursal)
    gastos_externos_query = gastos_externos_query.all()
    resumen['total_gastos_externos'] = sum(g.monto for g in gastos_externos_query)
    
    resumen['total_recaudado_bruto'] = resumen['total_efectivo'] + resumen['total_transferencia']
    resumen['total_recaudado_neto'] = resumen['total_recaudado_bruto'] - resumen['total_gastos']
    
    # Calcular los gastos que fueron pagados en EFECTIVO
    gastos_efectivo_query = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) >= fecha_inicio,
        db.func.date(Expense.fecha_gasto) <= fecha_fin,
        Expense.tipo_gasto == 'Gasto Diario',
        Expense.metodo_pago == 'efectivo'
    )
    if current_user.rol != 'admin':
        gastos_efectivo_query = gastos_efectivo_query.filter(Expense.sucursal == current_user.sucursal)
    gastos_efectivo_query = gastos_efectivo_query.all()
    resumen['total_gastos_efectivo'] = sum(g.monto for g in gastos_efectivo_query)

    # El efectivo esperado en caja descuenta gastos en EFECTIVO
    resumen['efectivo_esperado'] = (resumen['total_base'] + resumen['total_efectivo']) - resumen['total_gastos_efectivo']
    resumen['total_sobrantes'] = sum((Decimal(str(a.diferencia)) for a in arqueos if a.diferencia and a.diferencia > 0), Decimal('0.00'))
    resumen['total_faltantes'] = sum((Decimal(str(abs(a.diferencia))) for a in arqueos if a.diferencia and a.diferencia < 0), Decimal('0.00'))

    # Consolidado por Sucursal / Local
    resumen_por_sucursal = {}
    for a in arqueos:
        suc = a.sucursal or 'LOCAL 136'
        if suc not in resumen_por_sucursal:
            resumen_por_sucursal[suc] = {
                'total_base': Decimal('0.00'),
                'total_efectivo': Decimal('0.00'),
                'total_transferencia': Decimal('0.00'),
                'total_gastos': Decimal('0.00'),
                'total_sobrantes': Decimal('0.00'),
                'total_faltantes': Decimal('0.00'),
                'efectivo_fisico': Decimal('0.00'),
                'cierres': 0
            }
        resumen_por_sucursal[suc]['total_base'] += Decimal(str(a.base_inicial or 0))
        resumen_por_sucursal[suc]['total_efectivo'] += Decimal(str(a.total_efectivo_sistema or 0))
        resumen_por_sucursal[suc]['total_transferencia'] += Decimal(str(a.total_transferencia_sistema or 0))
        resumen_por_sucursal[suc]['total_gastos'] += Decimal(str(a.gastos_del_dia or 0))
        if a.efectivo_fisico:
            resumen_por_sucursal[suc]['efectivo_fisico'] += Decimal(str(a.efectivo_fisico))
        if a.diferencia and a.diferencia > 0:
            resumen_por_sucursal[suc]['total_sobrantes'] += Decimal(str(a.diferencia))
        elif a.diferencia and a.diferencia < 0:
            resumen_por_sucursal[suc]['total_faltantes'] += Decimal(str(abs(a.diferencia)))
        resumen_por_sucursal[suc]['cierres'] += 1

    # Obtener todas las ventas del periodo para el detalle en la "tirilla" (unificado)
    ventas_query = Sale.query.filter(
        db.func.date(Sale.fecha_venta) >= fecha_inicio,
        db.func.date(Sale.fecha_venta) <= fecha_fin,
        Sale.tipo_venta.in_(['general', 'celulares'])
    )
    if current_user.rol != 'admin':
        ventas_query = ventas_query.filter(Sale.sucursal == current_user.sucursal)
    
    ventas_periodo = ventas_query.order_by(Sale.fecha_venta.asc()).all()

    fecha_generacion = obtener_hora_bogota().strftime('%Y-%m-%d %H:%M')

    # Obtener todos los gastos del periodo para el reporte detallado
    gastos_query = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) >= fecha_inicio,
        db.func.date(Expense.fecha_gasto) <= fecha_fin
    )
    if current_user.rol != 'admin':
        gastos_query = gastos_query.filter(Expense.sucursal == current_user.sucursal)
    gastos_periodo = gastos_query.order_by(Expense.fecha_gasto.asc()).all()

    return render_template(
        'arqueo/reporte.html',
        arqueos=arqueos,
        resumen=resumen,
        resumen_por_sucursal=resumen_por_sucursal,
        fecha_inicio=fecha_inicio_str,
        fecha_fin=fecha_fin_str,
        fecha_generacion=fecha_generacion,
        ventas_periodo=ventas_periodo,
        gastos_periodo=gastos_periodo
    )

@arqueo_bp.route('/revertir/<int:id>', methods=['POST'])
@login_required
@admin_required
def revertir_arqueo(id):
    arqueo = ArqueoCaja.query.get_or_404(id)
    fecha_str = arqueo.fecha_arqueo.strftime('%Y-%m-%d')
    try:
        SobranteLog.query.filter_by(arqueo_id=arqueo.id).delete()
        db.session.delete(arqueo)
        db.session.commit()
        flash(f"El arqueo de caja del {fecha_str} en {arqueo.sucursal} ha sido revertido exitosamente.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Ocurrió un error al revertir el arqueo de caja.", "danger")
    return redirect(url_for('arqueo_bp.reporte'))

@arqueo_bp.route('/sobrantes', methods=['GET'])
@login_required
def log_sobrantes():
    fecha_inicio_str = request.args.get('fecha_inicio', '')
    fecha_fin_str = request.args.get('fecha_fin', '')
    sucursal = request.args.get('sucursal', '')
    q = request.args.get('q', '').strip()

    base_query = SobranteLog.query.options(
        joinedload(SobranteLog.vendedor),
        joinedload(SobranteLog.arqueo)
    )

    # Restricción por rol: Los usuarios no-admin solo ven su propia sucursal
    if current_user.rol != 'admin':
        base_query = base_query.filter(SobranteLog.sucursal == current_user.sucursal)
    elif sucursal:
        base_query = base_query.filter(SobranteLog.sucursal == sucursal)

    if fecha_inicio_str:
        try:
            f_ini = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            base_query = base_query.filter(SobranteLog.fecha_arqueo >= f_ini)
        except ValueError:
            pass

    if fecha_fin_str:
        try:
            f_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            base_query = base_query.filter(SobranteLog.fecha_arqueo <= f_fin)
        except ValueError:
            pass

    if q:
        from models import User
        base_query = base_query.join(User).filter(
            db.or_(
                SobranteLog.sucursal.ilike(f'%{q}%'),
                SobranteLog.justificacion.ilike(f'%{q}%'),
                User.nombre.ilike(f'%{q}%')
            )
        )

    sobrantes = base_query.order_by(SobranteLog.fecha_registro.desc()).all()

    # Cálculos KPIs
    total_sobrantes_monto = sum((s.monto_sobrante for s in sobrantes), Decimal('0.00')) if sobrantes else Decimal('0.00')
    total_registros = len(sobrantes)
    mayor_sobrante = max((s.monto_sobrante for s in sobrantes), default=Decimal('0.00'))

    # Sucursales únicas para filtro (Admin)
    sucursales = [res[0] for res in db.session.query(ArqueoCaja.sucursal).distinct().all()] if current_user.rol == 'admin' else [current_user.sucursal]

    return render_template('arqueo/sobrantes.html',
                           sobrantes=sobrantes,
                           total_sobrantes_monto=total_sobrantes_monto,
                           total_registros=total_registros,
                           mayor_sobrante=mayor_sobrante,
                           fecha_inicio=fecha_inicio_str,
                           fecha_fin=fecha_fin_str,
                           sucursal_sel=sucursal,
                           q=q,
                           sucursales=sucursales)

@arqueo_bp.route('/ticket', methods=['GET'])
@login_required
def imprimir_ticket_arqueo():
    fecha_str = request.args.get('fecha', obtener_hora_bogota().strftime('%Y-%m-%d'))
    sucursal = request.args.get('sucursal')
    
    try:
        fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        fecha_obj = obtener_hora_bogota().date()
        fecha_str = fecha_obj.strftime('%Y-%m-%d')
        
    query_arqueo = ArqueoCaja.query.filter_by(fecha_arqueo=fecha_obj, tipo_arqueo='general')
    if sucursal and sucursal != 'TODOS':
        query_arqueo = query_arqueo.filter_by(sucursal=sucursal)
    elif current_user.rol != 'admin':
        query_arqueo = query_arqueo.filter_by(sucursal=current_user.sucursal)
        
    arqueo = query_arqueo.first()
    
    ventas_query = Sale.query.filter(
        db.func.date(Sale.fecha_venta) == fecha_obj,
        Sale.tipo_venta.in_(['general', 'celulares'])
    )
    if sucursal and sucursal != 'TODOS':
        ventas_query = ventas_query.filter(Sale.sucursal == sucursal)
    elif current_user.rol != 'admin':
        ventas_query = ventas_query.filter(Sale.sucursal == current_user.sucursal)
        
    ventas = ventas_query.order_by(Sale.fecha_venta.asc()).all()
    
    gastos_query = Expense.query.filter(
        db.func.date(Expense.fecha_gasto) == fecha_obj
    )
    if sucursal and sucursal != 'TODOS':
        gastos_query = gastos_query.filter(Expense.sucursal == sucursal)
    elif current_user.rol != 'admin':
        gastos_query = gastos_query.filter(Expense.sucursal == current_user.sucursal)
        
    gastos = gastos_query.all()
    
    total_efectivo = 0
    total_transferencia = 0
    total_ventas = 0
    
    for v in ventas:
        total_ventas += float(v.monto_total or 0)
        if v.pagos and len(v.pagos) > 0:
            for p in v.pagos:
                if p.metodo_pago.lower() == 'efectivo':
                    total_efectivo += float(p.monto or 0)
                else:
                    total_transferencia += float(p.monto or 0)
        else:
            if v.metodo_pago and v.metodo_pago.lower() == 'efectivo':
                total_efectivo += float(v.monto_total or 0)
            else:
                total_transferencia += float(v.monto_total or 0)
                
    total_gastos = sum(float(g.monto or 0) for g in gastos)
    fecha_generacion = obtener_hora_bogota().strftime('%d/%m/%Y %I:%M %p')
    
    sucursal_nombre = sucursal if sucursal else (current_user.sucursal if current_user.rol != 'admin' else 'GENERAL')
    
    return render_template(
        'arqueo/ticket.html',
        fecha=fecha_obj.strftime('%d/%m/%Y'),
        fecha_str=fecha_str,
        fecha_generacion=fecha_generacion,
        arqueo=arqueo,
        ventas=ventas,
        gastos=gastos,
        total_efectivo=total_efectivo,
        total_transferencia=total_transferencia,
        total_ventas=total_ventas,
        total_gastos=total_gastos,
        sucursal=sucursal_nombre
    )
