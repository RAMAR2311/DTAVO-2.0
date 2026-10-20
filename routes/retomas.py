import re
from flask import Blueprint, request, flash, redirect, render_template, url_for, jsonify
from flask_login import login_required, current_user
from models import db, Product, Retoma, obtener_hora_bogota
from decorators import admin_required
from decimal import Decimal
from sqlalchemy.orm import joinedload
from sqlalchemy import or_

retomas_bp = Blueprint('retomas_bp', __name__)

@retomas_bp.route('/cuarentena', methods=['GET'])
@login_required
@admin_required
def cuarentena():
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Base query: all retomas
    base_query = Retoma.query.options(
        joinedload(Retoma.venta),
        joinedload(Retoma.producto_generado).joinedload(Product.detalles_venta)
    )

    # Optional text search
    if q:
        base_query = base_query.filter(
            or_(
                Retoma.marca.ilike(f'%{q}%'),
                Retoma.modelo.ilike(f'%{q}%'),
                Retoma.imei1.ilike(f'%{q}%'),
                Retoma.imei2.ilike(f'%{q}%'),
            )
        )

    paginacion = base_query.order_by(Retoma.fecha_registro.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    for r_item in paginacion.items:
        r_item.es_reingreso = False
        if r_item.imei1:
            prod_previo = Product.query.filter(
                ((Product.imei == r_item.imei1) | (Product.imei2 == r_item.imei1)),
                Product.cantidad_stock == 0
            ).first()
            if prod_previo:
                r_item.es_reingreso = True

    return render_template('retomas/cuarentena.html',
                           retomas=paginacion.items,
                           paginacion=paginacion,
                           q=q)

@retomas_bp.route('/aprobar/<int:id>', methods=['POST'])
@login_required
@admin_required
def aprobar_retoma(id):
    retoma = Retoma.query.get_or_404(id)
    if retoma.estado != 'en_evaluacion':
        flash('Esta retoma ya fue procesada.', 'warning')
        return redirect(url_for('retomas_bp.cuarentena'))

    nombre_definitivo = request.form.get('nombre_definitivo')
    precio_sugerido = request.form.get('precio_sugerido')
    precio_minimo = request.form.get('precio_minimo', precio_sugerido)
    arreglos = request.form.get('arreglos', '0')
    bateria_input = request.form.get('bateria', retoma.bateria or '').strip()
    inventario_input = request.form.get('inventario', '').strip() or 'PRINCIPAL'
    
    if not nombre_definitivo or not precio_sugerido:
        flash('Faltan datos obligatorios para crear el producto.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    try:
        arreglos_val = Decimal(arreglos)
    except:
        arreglos_val = Decimal('0')

    # Guardar costo de arreglos y nueva batería en la retoma
    retoma.arreglos = arreglos_val
    if bateria_input:
        retoma.bateria = bateria_input

    nuevo_sku = f"RET-{retoma.id}-{obtener_hora_bogota().strftime('%Y%m%d%H%M%S')}"

    imei1_val = retoma.imei1.strip() if retoma.imei1 else None
    imei2_val = retoma.imei2.strip() if retoma.imei2 else None

    if imei1_val:
        prod_existente = Product.query.filter_by(imei=imei1_val).first()
        if prod_existente:
            if prod_existente.cantidad_stock == 0:
                # Reingreso de celular vendido previamente: actualizar su IMEI histórico para liberar el IMEI único
                prod_existente.imei = f"{imei1_val}-OLD-{prod_existente.id}"
            else:
                flash(f'El IMEI "{imei1_val}" ya está registrado y activo en el inventario ({prod_existente.nombre}).', 'danger')
                return redirect(url_for('retomas_bp.cuarentena'))

    nuevo_producto = Product(
        nombre=nombre_definitivo,
        sku=nuevo_sku,
        tipo_inventario='celulares',
        inventario=inventario_input,
        cantidad_stock=1,
        precio_costo=retoma.valor_retoma + arreglos_val,
        precio_minimo=Decimal(precio_minimo),
        precio_sugerido=Decimal(precio_sugerido),
        observacion=retoma.observaciones,
        imei=imei1_val,
        imei2=imei2_val,
        color=retoma.color,
        bateria=bateria_input or retoma.bateria,
        memoria=retoma.memoria,
        proveedor=retoma.proveedor or 'Cliente',
        marca=retoma.marca or '',
        modelo_celular=retoma.modelo,
        estado_celular='Usado'
    )
    
    try:
        db.session.add(nuevo_producto)
        db.session.flush()
        retoma.producto_generado_id = nuevo_producto.id
        retoma.estado = 'aprobado'
        db.session.commit()
        flash('Retoma aprobada y producto generado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al generar producto: {str(e)}', 'danger')
        
    return redirect(url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/eliminar/<int:id>', methods=['POST'])
@login_required
@admin_required
def eliminar_retoma(id):
    retoma = Retoma.query.get_or_404(id)
    try:
        # Si la retoma generó un producto que sigue sin venderse en stock, eliminarlo también
        if retoma.producto_generado and retoma.producto_generado.cantidad_stock > 0:
            db.session.delete(retoma.producto_generado)

        db.session.delete(retoma)
        db.session.commit()
        flash('Retoma eliminada correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar la retoma: {str(e)}', 'danger')

    return redirect(url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/editar/<int:id>', methods=['POST'])
@login_required
@admin_required
def editar_retoma(id):
    retoma = Retoma.query.get_or_404(id)

    marca = request.form.get('marca', '').strip()
    modelo = request.form.get('modelo', '').strip()
    memoria = request.form.get('memoria', '').strip()
    color = request.form.get('color', '').strip()
    bateria = request.form.get('bateria', '').strip()
    imei1 = request.form.get('imei1', '').strip()
    imei2 = request.form.get('imei2', '').strip() or None
    valor_retoma_raw = request.form.get('valor_retoma', '0')
    observaciones = request.form.get('observaciones', '').strip()

    if not modelo or not imei1:
        flash('El modelo y el IMEI 1 son obligatorios.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    # Verificar IMEI 1 duplicado en retomas (excluyendo la actual)
    existente = Retoma.query.filter(Retoma.imei1 == imei1, Retoma.id != id).first()
    if existente:
        flash(f'El IMEI 1 "{imei1}" ya está registrado en otra retoma.', 'danger')
        return redirect(url_for('retomas_bp.cuarentena'))

    try:
        clean_val = re.sub(r'[^\d.]', '', str(valor_retoma_raw))
        valor_retoma = Decimal(clean_val) if clean_val else retoma.valor_retoma
    except:
        valor_retoma = retoma.valor_retoma

    retoma.marca = marca
    retoma.modelo = modelo
    retoma.memoria = memoria
    retoma.color = color
    retoma.bateria = bateria
    retoma.imei1 = imei1
    retoma.imei2 = imei2
    retoma.valor_retoma = valor_retoma
    retoma.observaciones = observaciones

    # Si la retoma ya había generado un producto en el inventario, mantener el producto sincronizado
    if retoma.producto_generado:
        prod = retoma.producto_generado
        prod.marca = marca
        prod.modelo_celular = modelo
        prod.memoria = memoria
        prod.color = color
        prod.bateria = bateria
        prod.imei = imei1
        prod.imei2 = imei2
        prod.precio_costo = valor_retoma + (retoma.arreglos or Decimal('0.00'))
        prod.observacion = observaciones
        if prod.nombre:
            clean_marca = (marca or '').strip()
            clean_modelo = (modelo or '').strip()
            if clean_marca and clean_marca.lower() in clean_modelo.lower():
                nombre_base = clean_modelo
            else:
                nombre_base = f"{clean_marca} {clean_modelo}".strip() if clean_marca else clean_modelo
            prod.nombre = re.sub(r'\s*\([Uu]sado\)', '', nombre_base).strip()

    try:
        db.session.commit()
        flash('Retoma actualizada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar la retoma: {str(e)}', 'danger')

    return redirect(url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/toggle_ok_contabilidad/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle_ok_contabilidad(id):
    retoma = Retoma.query.get_or_404(id)
    retoma.ok_contabilidad = not retoma.ok_contabilidad
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'success': True,
            'ok_contabilidad': retoma.ok_contabilidad,
            'message': 'Estado de contabilidad actualizado.'
        })

    flash(f"Estado OK Contabilidad actualizado a {'Aprobado' if retoma.ok_contabilidad else 'Pendiente'}.", "success")
    return redirect(request.referrer or url_for('retomas_bp.cuarentena'))

@retomas_bp.route('/toggle_ok_venta/<int:id>', methods=['POST'])
@login_required
@admin_required
def toggle_ok_venta(id):
    retoma = Retoma.query.get_or_404(id)
    retoma.ok_venta = not retoma.ok_venta
    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'success': True,
            'ok_venta': retoma.ok_venta,
            'message': 'Estado de OK Venta actualizado.'
        })

    flash(f"Estado OK Venta actualizado a {'Aprobado' if retoma.ok_venta else 'Pendiente'}.", "success")
    return redirect(request.referrer or url_for('retomas_bp.cuarentena'))
