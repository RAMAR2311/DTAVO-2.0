import json
from decimal import Decimal
from datetime import datetime
import pytz
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Product, ProductVariant, Provider, PurchaseOrder, PurchaseOrderItem, obtener_hora_bogota
from decorators import admin_required

purchases_bp = Blueprint('purchases_bp', __name__)

@purchases_bp.route('/')
@login_required
@admin_required
def index():
    compras = PurchaseOrder.query.order_by(PurchaseOrder.fecha_compra.desc()).all()
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    return render_template('compras/index.html', compras=compras, proveedores=proveedores)

@purchases_bp.route('/nueva')
@login_required
@admin_required
def nueva():
    tipo = request.args.get('tipo', 'accesorios')
    proveedores = Provider.query.order_by(Provider.nombre.asc()).all()
    return render_template('compras/nueva.html', tipo=tipo, proveedores=proveedores)

@purchases_bp.route('/detalle/<int:id>')
@login_required
@admin_required
def detalle(id):
    compra = PurchaseOrder.query.get_or_404(id)
    return render_template('compras/detalle.html', compra=compra)

@purchases_bp.route('/api/buscar_productos')
@login_required
@admin_required
def api_buscar_productos():
    tipo = request.args.get('tipo', 'accesorios')
    q = request.args.get('q', '').strip()

    query = Product.query
    if tipo == 'celulares':
        query = query.filter(Product.tipo_inventario == 'celulares')
    else:
        query = query.filter(Product.tipo_inventario.in_(['tienda', 'bodega', 'accesorios']))

    if q:
        query = query.filter(
            (Product.nombre.ilike(f'%{q}%')) |
            (Product.sku.ilike(f'%{q}%')) |
            (Product.imei.ilike(f'%{q}%')) |
            (Product.imei2.ilike(f'%{q}%')) |
            (Product.marca.ilike(f'%{q}%')) |
            (Product.modelo_celular.ilike(f'%{q}%'))
        )

    productos = query.order_by(Product.nombre.asc()).limit(30).all()

    resultados = []
    for p in productos:
        variantes_data = []
        for v in p.variantes:
            variantes_data.append({
                'id': v.id,
                'nombre': v.nombre_variante,
                'stock': v.cantidad_stock,
                'costo': float(v.precio_costo) if v.precio_costo else (float(p.precio_costo) if p.precio_costo else 0.0)
            })

        resultados.append({
            'id': p.id,
            'nombre': p.nombre,
            'sku': p.sku,
            'marca': p.marca or '',
            'modelo': p.modelo_celular or '',
            'imei': p.imei or '',
            'tipo_inventario': p.tipo_inventario,
            'stock': p.cantidad_stock,
            'costo': float(p.precio_costo) if p.precio_costo else 0.0,
            'variantes': variantes_data
        })

    return jsonify({'productos': resultados})

@purchases_bp.route('/guardar', methods=['POST'])
@login_required
@admin_required
def guardar():
    try:
        tipo_inventario = request.form.get('tipo_inventario', 'accesorios')
        provider_id = request.form.get('provider_id')
        provider_id = int(provider_id) if provider_id and provider_id.isdigit() else None
        numero_factura = request.form.get('numero_factura', '').strip()
        observaciones = request.form.get('observaciones', '').strip()
        items_json = request.form.get('items_json', '[]')

        items = json.loads(items_json)
        if not items:
            flash('Debes ingresar al menos un producto a la compra.', 'danger')
            return redirect(url_for('purchases_bp.nueva', tipo=tipo_inventario))

        total_costo = Decimal('0.00')

        # Crear orden de compra
        compra = PurchaseOrder(
            tipo_inventario=tipo_inventario,
            provider_id=provider_id,
            usuario_id=current_user.id,
            numero_factura=numero_factura,
            observaciones=observaciones,
            total_costo=Decimal('0.00'),
            fecha_compra=obtener_hora_bogota()
        )
        db.session.add(compra)
        db.session.flush()

        for it in items:
            prod_id = int(it.get('product_id'))
            var_id = it.get('variant_id')
            var_id = int(var_id) if var_id else None
            cantidad = int(it.get('cantidad', 1))
            costo_unitario = Decimal(str(it.get('costo_unitario', 0)))
            subtotal = costo_unitario * cantidad
            total_costo += subtotal

            producto = Product.query.get(prod_id)
            if not producto:
                continue

            # Actualizar stock y costos en producto/variante
            if var_id:
                variante = ProductVariant.query.get(var_id)
                if variante:
                    variante.cantidad_stock += cantidad
                    variante.precio_costo = costo_unitario
            else:
                producto.cantidad_stock += cantidad
                if costo_unitario > 0:
                    producto.precio_costo = costo_unitario

            # Si es celular y se provee nuevo IMEI
            imei = it.get('imei', '').strip() if it.get('imei') else None
            imei2 = it.get('imei2', '').strip() if it.get('imei2') else None
            if imei and not producto.imei:
                producto.imei = imei
            if imei2 and not producto.imei2:
                producto.imei2 = imei2

            # Crear item de compra
            item_compra = PurchaseOrderItem(
                purchase_order_id=compra.id,
                product_id=prod_id,
                variant_id=var_id,
                cantidad=cantidad,
                costo_unitario=costo_unitario,
                subtotal=subtotal,
                imei=imei,
                imei2=imei2
            )
            db.session.add(item_compra)

        compra.total_costo = total_costo
        db.session.commit()

        flash(f'Compra #{compra.id} registrada con éxito. Se incrementó el inventario correspondiente.', 'success')
        return redirect(url_for('purchases_bp.detalle', id=compra.id))

    except Exception as e:
        db.session.rollback()
        flash(f'Error al procesar la compra: {str(e)}', 'danger')
        return redirect(url_for('purchases_bp.nueva', tipo=request.form.get('tipo_inventario', 'accesorios')))
