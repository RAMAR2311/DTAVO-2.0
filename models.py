from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import pytz

db = SQLAlchemy()

def obtener_hora_bogota():
    """Inyecta el uso de red horario en Colombia a nivel de sistema operativo."""
    return datetime.now(pytz.timezone('America/Bogota')).replace(tzinfo=None)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    telefono = db.Column(db.String(20)) # Nuevo Campo de Contacto (Nullable por Defecto)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.String(50), nullable=False, default='vendedor')
    sucursal = db.Column(db.String(100), nullable=False, default='LOCAL 136')
    
    ventas = db.relationship('Sale', backref='vendedor', lazy=True)
    ajustes_stock = db.relationship('StockAdjustment', backref='admin', lazy=True)
    arqueos = db.relationship('ArqueoCaja', backref='cajero', lazy=True)

    def __init__(self, nombre=None, email=None, telefono=None, password_hash=None, rol=None, **kwargs):
        if nombre is not None: kwargs['nombre'] = nombre
        if email is not None: kwargs['email'] = email
        if telefono is not None: kwargs['telefono'] = telefono
        if password_hash is not None: kwargs['password_hash'] = password_hash
        if rol is not None: kwargs['rol'] = rol
        if 'sucursal' in kwargs: pass
        super(User, self).__init__(**kwargs)

class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False, index=True)
    tipo_inventario = db.Column(db.String(50), nullable=False, server_default='tienda') # 'tienda' o 'bodega'
    cantidad_stock = db.Column(db.Integer, nullable=False, default=0)
    precio_costo = db.Column(db.Numeric(10, 2), nullable=False, default=0.00) # El Costo de Bodega
    precio_minimo = db.Column(db.Numeric(10, 2), nullable=False)
    precio_sugerido = db.Column(db.Numeric(10, 2), nullable=False)
    imagen = db.Column(db.String(255), nullable=True) # Nombre de la foto subida
    observacion = db.Column(db.Text, nullable=True) # Nota descriptiva
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)
    
    # Campos específicos para módulo de celulares (tipo_inventario='celulares')
    imei = db.Column(db.String(50), unique=True, nullable=True, index=True)
    imei2 = db.Column(db.String(50), nullable=True)
    marca = db.Column(db.String(100), nullable=True)
    modelo_celular = db.Column(db.String(100), nullable=True)
    estado_celular = db.Column(db.String(50), nullable=True, default='Nuevo') # Nuevo, Usado
    color = db.Column(db.String(50), nullable=True)
    bateria = db.Column(db.String(20), nullable=True) # % o descripción
    memoria = db.Column(db.String(50), nullable=True) # Capacidad (Ej: 128GB)
    proveedor = db.Column(db.String(150), nullable=True)
    inventario = db.Column(db.String(100), nullable=True)
    
    detalles_venta = db.relationship('SaleDetail', backref='producto', lazy=True)
    ajustes_stock = db.relationship('StockAdjustment', backref='producto_rel', lazy=True, cascade="all, delete-orphan")
    variantes = db.relationship('ProductVariant', backref='producto', lazy=True, cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super(Product, self).__init__(**kwargs)

    @property
    def total_stock(self):
        if self.variantes:
            return sum(v.cantidad_stock for v in self.variantes)
        return self.cantidad_stock

    @property
    def rango_precios(self):
        if not self.variantes:
            return None
        precios = [v.precio_sugerido for v in self.variantes if v.precio_sugerido is not None]
        if not precios:
            return None
        min_p = min(precios)
        max_p = max(precios)
        if min_p == max_p:
            return min_p
        return (min_p, max_p)

    @property
    def rango_costos(self):
        if not self.variantes:
            return None
        precios = [v.precio_costo for v in self.variantes if v.precio_costo is not None]
        if not precios:
            return None
        min_p = min(precios)
        max_p = max(precios)
        if min_p == max_p:
            return min_p
        return (min_p, max_p)

    @property
    def rango_minimos(self):
        if not self.variantes:
            return None
        precios = [v.precio_minimo for v in self.variantes if v.precio_minimo is not None]
        if not precios:
            return None
        min_p = min(precios)
        max_p = max(precios)
        if min_p == max_p:
            return min_p
        return (min_p, max_p)

    @property
    def maneo_activo(self):
        if not self.maneos:
            return None
        for m in self.maneos:
            if m.estado == 'PENDIENTE':
                return m
        return None

class ProductVariant(db.Model):
    __tablename__ = 'product_variants'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    nombre_variante = db.Column(db.String(100), nullable=False)
    cantidad_stock = db.Column(db.Integer, nullable=False, default=0)
    
    # Nuevos precios específicos para variantes
    precio_costo = db.Column(db.Numeric(10, 2), nullable=True) 
    precio_minimo = db.Column(db.Numeric(10, 2), nullable=True)
    precio_sugerido = db.Column(db.Numeric(10, 2), nullable=True)

    def __init__(self, **kwargs):
        super(ProductVariant, self).__init__(**kwargs)

class Sale(db.Model):
    __tablename__ = 'sales'
    
    id = db.Column(db.Integer, primary_key=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fecha_venta = db.Column(db.DateTime, default=obtener_hora_bogota)
    monto_total = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    tipo_venta = db.Column(db.String(50), nullable=False, server_default='general') # 'general' o 'celulares'
    sucursal = db.Column(db.String(100), nullable=False, default='LOCAL 136')
    
    detalles = db.relationship('SaleDetail', backref='venta', lazy=True, cascade="all, delete-orphan")
    pagos = db.relationship('SalePayment', backref='venta', lazy=True, cascade="all, delete-orphan")
    cliente = db.relationship('SaleClient', backref='venta', lazy=True, cascade="all, delete-orphan", uselist=False)
    asesor_id = db.Column(db.Integer, db.ForeignKey('asesores.id'), nullable=True)
    asesor = db.relationship('Asesor', backref=db.backref('ventas', lazy=True))
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=True)
    provider = db.relationship('Provider', backref=db.backref('ventas', lazy=True))

    def __init__(self, **kwargs):
        super(Sale, self).__init__(**kwargs)

    @property
    def metodo_pago_display(self):
        """Retorna un resumen legible del método de pago.
        Si es pago único, retorna el nombre del método.
        Si es mixto, retorna 'Pago Mixto' con desglose."""
        if not self.pagos:
            # Retrocompatibilidad con ventas antiguas que solo tienen metodo_pago
            return self.metodo_pago.capitalize() if self.metodo_pago else 'Efectivo'
        if len(self.pagos) == 1:
            return self.pagos[0].metodo_pago.capitalize()
        return 'Pago Mixto'

class SalePayment(db.Model):
    """Modelo para soportar pagos mixtos/parciales por venta.
    Permite registrar múltiples métodos de pago en una sola venta.
    Ej: $50.000 en efectivo + $30.000 por Nequi = $80.000 total."""
    __tablename__ = 'sale_payments'

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False)  # efectivo, nequi, bancolombia, daviplata
    monto = db.Column(db.Numeric(10, 2), nullable=False)

    def __init__(self, **kwargs):
        super(SalePayment, self).__init__(**kwargs)

class SaleClient(db.Model):
    """Modelo para almacenar los datos del cliente, especialmente requerido en ventas de celulares."""
    __tablename__ = 'sale_clients'
    
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False, unique=True)
    nombre = db.Column(db.String(150), nullable=False)
    documento = db.Column(db.String(50), nullable=False, index=True)
    telefono = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    direccion = db.Column(db.String(200), nullable=True)
    
    # Relación configurada desde Sale

    def __init__(self, **kwargs):
        super(SaleClient, self).__init__(**kwargs)

class SaleDetail(db.Model):
    __tablename__ = 'sale_details'
    
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    cantidad_vendida = db.Column(db.Integer, nullable=False)
    precio_venta_final = db.Column(db.Numeric(10, 2), nullable=False)
    # Campos para productos manuales (prestados de otros locales)
    nombre_manual = db.Column(db.String(200), nullable=True)
    precio_costo_manual = db.Column(db.Numeric(10, 2), nullable=True)
    ok_contabilidad = db.Column(db.Boolean, default=False, nullable=False)
    ok_inventario = db.Column(db.Boolean, default=False, nullable=False)

    variante = db.relationship('ProductVariant', backref='ventas_rel', lazy=True)

    def __init__(self, **kwargs):
        super(SaleDetail, self).__init__(**kwargs)

class StockAdjustment(db.Model):
    __tablename__ = 'stock_adjustments'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tipo_movimiento = db.Column(db.String(100), nullable=True) # Ej: Creación Inicial, Ajuste Manual
    stock_anterior = db.Column(db.Integer, nullable=False)
    stock_nuevo = db.Column(db.Integer, nullable=False)
    fecha_ajuste = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(StockAdjustment, self).__init__(**kwargs)

class Retoma(db.Model):
    __tablename__ = 'retomas'
    
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    modelo = db.Column(db.String(150), nullable=False)
    marca = db.Column(db.String(100), nullable=True)
    proveedor = db.Column(db.String(150), nullable=True, default='Cliente')
    valor_retoma = db.Column(db.Numeric(10, 2), nullable=False)
    arreglos = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    imei1 = db.Column(db.String(50), nullable=False, unique=True)
    imei2 = db.Column(db.String(50), nullable=True)
    color = db.Column(db.String(50), nullable=True)
    bateria = db.Column(db.String(50), nullable=True)
    memoria = db.Column(db.String(50), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    estado = db.Column(db.String(50), nullable=False, default='en_evaluacion') # en_evaluacion, aprobado
    ok_contabilidad = db.Column(db.Boolean, default=False, nullable=False)
    ok_venta = db.Column(db.Boolean, default=False, nullable=False)
    producto_generado_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    fecha_registro = db.Column(db.DateTime, default=obtener_hora_bogota)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    venta = db.relationship('Sale', backref='retomas_asociadas', lazy=True)
    vendedor = db.relationship('User', backref='retomas_registradas', lazy=True)
    producto_generado = db.relationship('Product', backref='retoma_origen', lazy=True)

    def __init__(self, **kwargs):
        super(Retoma, self).__init__(**kwargs)

class ArqueoCaja(db.Model):
    __tablename__ = 'arqueo_caja'
    
    id = db.Column(db.Integer, primary_key=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fecha_arqueo = db.Column(db.Date, nullable=False)
    tipo_arqueo = db.Column(db.String(50), nullable=False, server_default='general') # 'general' o 'celulares'
    sucursal = db.Column(db.String(100), nullable=False, default='LOCAL 136')
    base_inicial = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    gastos_del_dia = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    observaciones_gastos = db.Column(db.String(255), nullable=True)
    total_efectivo_sistema = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    total_transferencia_sistema = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    total_unidades_ch = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    total_celulares = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    total_retomas_sistema = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    efectivo_fisico = db.Column(db.Numeric(14, 2), nullable=True, default=0.0)
    diferencia = db.Column(db.Numeric(14, 2), nullable=True, default=0.0)
    observacion_diferencia = db.Column(db.Text, nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)

    vendedor = db.relationship('User', backref='arqueos_registrados', lazy=True)

    def __init__(self, **kwargs):
        super(ArqueoCaja, self).__init__(**kwargs)


class SobranteLog(db.Model):
    __tablename__ = 'sobrantes_log'

    id = db.Column(db.Integer, primary_key=True)
    arqueo_id = db.Column(db.Integer, db.ForeignKey('arqueo_caja.id', ondelete='CASCADE'), nullable=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sucursal = db.Column(db.String(100), nullable=False)
    fecha_arqueo = db.Column(db.Date, nullable=False)
    monto_esperado = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    efectivo_fisico = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    monto_sobrante = db.Column(db.Numeric(14, 2), nullable=False, default=0.0)
    justificacion = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=obtener_hora_bogota)

    arqueo = db.relationship('ArqueoCaja', backref='sobrantes_rel', lazy=True)
    vendedor = db.relationship('User', backref='sobrantes_registrados', lazy=True)

    def __init__(self, **kwargs):
        super(SobranteLog, self).__init__(**kwargs)

class Maneo(db.Model):
    __tablename__ = 'maneos'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    local_vecino = db.Column(db.String(150), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(50), nullable=False, default='PENDIENTE') # PENDIENTE, FACTURADO, DEVUELTO
    fecha_prestamo = db.Column(db.DateTime, default=obtener_hora_bogota)
    fecha_resolucion = db.Column(db.DateTime, nullable=True)

    producto = db.relationship('Product', backref='maneos', lazy=True)
    variante = db.relationship('ProductVariant', backref='maneos_rel', lazy=True)

    def __init__(self, **kwargs):
        super(Maneo, self).__init__(**kwargs)

class Expense(db.Model):
    __tablename__ = 'expenses'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tipo_gasto = db.Column(db.String(50), nullable=False) # 'Gasto Diario' o 'Costo Indirecto'
    categoria = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    sucursal = db.Column(db.String(100), nullable=False, default='LOCAL 136')
    fecha_gasto = db.Column(db.DateTime, default=obtener_hora_bogota)

    usuario = db.relationship('User', backref='gastos', lazy=True)

    def __init__(self, **kwargs):
        super(Expense, self).__init__(**kwargs)

class Cliente(db.Model):
    __tablename__ = 'clientes'

    id = db.Column(db.Integer, primary_key=True)
    nombre_o_razon_social = db.Column(db.String(150), nullable=False)
    documento_o_nit = db.Column(db.String(50), unique=True, nullable=False, index=True)
    telefono = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    direccion = db.Column(db.String(255), nullable=True)
    creado_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # ID del vendedor/admin que lo creó
    fecha_registro = db.Column(db.DateTime, default=obtener_hora_bogota)

    facturas = db.relationship('FacturaBodega', backref='cliente', lazy=True)
    abonos = db.relationship('AbonoBodega', backref='cliente', lazy=True)

    def __init__(self, **kwargs):
        super(Cliente, self).__init__(**kwargs)

    @property
    def total_contado(self):
        return sum(f.monto_total for f in self.facturas if f.modalidad == 'contado')

    @property
    def total_credito(self):
        return sum(f.monto_total for f in self.facturas if f.modalidad == 'credito')

    @property
    def total_abonado(self):
        # Solo sumamos abonos que NO son de facturas de contado (los de contado ya se reflejan en total_contado)
        return sum(a.monto for a in self.abonos if not (a.factura and a.factura.modalidad == 'contado'))

    @property
    def deuda_total(self):
        # La deuda es el total de crédito menos lo abonado a crédito o a cuenta global
        return self.total_credito - self.total_abonado

    @property
    def estado_global(self):
        return "Con Deuda" if self.deuda_total > 0 else "Al Día"

class FacturaBodega(db.Model):
    __tablename__ = 'facturas_bodega'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    numero_factura = db.Column(db.String(100), nullable=False)
    archivo_ruta = db.Column(db.String(255), nullable=True)
    monto_total = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    modalidad = db.Column(db.String(50), nullable=False, default='credito') # contado o credito
    estado = db.Column(db.String(50), nullable=False, default='Pendiente') # Pendiente, Parcial, Pagado
    fecha_subida = db.Column(db.DateTime, default=obtener_hora_bogota)

    usuario = db.relationship('User', backref='facturas_subidas', lazy=True)
    abonos = db.relationship('AbonoBodega', backref='factura', lazy=True, cascade="all, delete-orphan")
    detalles = db.relationship('FacturaBodegaDetalle', backref='factura', lazy=True, cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super(FacturaBodega, self).__init__(**kwargs)

    @property
    def saldo_pendiente(self):
        # Esta propiedad se vuelve menos relevante con abonos globales, 
        # pero podemos mantenerla como una referencia teórica si no hay abonos.
        # Sin embargo, para no romper código existente, la dejamos así por ahora.
        total_abonado_factura = sum(abono.monto for abono in self.abonos) or 0
        return self.monto_total - total_abonado_factura

class FacturaBodegaDetalle(db.Model):
    __tablename__ = 'facturas_bodega_detalles'

    id = db.Column(db.Integer, primary_key=True)
    factura_id = db.Column(db.Integer, db.ForeignKey('facturas_bodega.id'), nullable=False)
    producto_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    cantidad = db.Column(db.Integer, nullable=False)
    precio_venta = db.Column(db.Numeric(10, 2), nullable=True) # Opcional para futuros análisis

    producto = db.relationship('Product', backref='detalles_factura_bodega', lazy=True)
    variante = db.relationship('ProductVariant', backref='detalles_factura_bodega_rel', lazy=True)

    def __init__(self, **kwargs):
        super(FacturaBodegaDetalle, self).__init__(**kwargs)

class AbonoBodega(db.Model):
    __tablename__ = 'abonos_bodega'

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    factura_id = db.Column(db.Integer, db.ForeignKey('facturas_bodega.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    observacion = db.Column(db.String(255), nullable=True)
    fecha_abono = db.Column(db.DateTime, default=obtener_hora_bogota)

    usuario = db.relationship('User', backref='abonos_registrados', lazy=True)

    def __init__(self, **kwargs):
        super(AbonoBodega, self).__init__(**kwargs)


class Provider(db.Model):
    __tablename__ = 'providers'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    empresa = db.Column(db.String(150), nullable=True)
    telefono = db.Column(db.String(50), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_bogota)

    # Relaciones en cascada
    facturas = db.relationship('ProviderInvoice', backref='provider', lazy=True, cascade='all, delete-orphan')
    pagos = db.relationship('ProviderPayment', backref='provider', lazy=True, cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super(Provider, self).__init__(**kwargs)

    @property
    def total_facturado(self):
        total_invoices = sum(f.monto_total for f in self.facturas)
        total_sales_cost = 0
        if self.ventas:
            for s in self.ventas:
                for d in s.detalles:
                    if d.producto and d.producto.precio_costo:
                        total_sales_cost += d.producto.precio_costo * d.cantidad_vendida
        from decimal import Decimal
        return Decimal(str(total_invoices or 0)) + Decimal(str(total_sales_cost or 0))
    
    @property
    def total_abonado(self):
        return sum(p.monto_abonado for p in self.pagos)
    
    @property
    def saldo_pendiente(self):
        return self.total_facturado - self.total_abonado

class ProviderInvoice(db.Model):
    __tablename__ = 'provider_invoices'

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=False)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    monto_total = db.Column(db.Numeric(12, 2), nullable=False)
    numero_factura = db.Column(db.String(100), nullable=True)
    descripcion = db.Column(db.String(255), nullable=True)
    comprobante = db.Column(db.String(255), nullable=True)
    fecha_factura = db.Column(db.DateTime, default=obtener_hora_bogota)

    sale = db.relationship('Sale', backref=db.backref('provider_invoices', lazy=True))

    def __init__(self, **kwargs):
        super(ProviderInvoice, self).__init__(**kwargs)

    @property
    def sale_id_detected(self):
        if self.sale_id:
            return self.sale_id
        if self.descripcion:
            import re
            match = re.search(r'(?:Venta\s*#?|#)?(\d+)', str(self.descripcion), re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    pass
        return None

    @property
    def producto_detectado(self):
        import re
        texto = f"{self.numero_factura or ''} {self.descripcion or ''}"
        match = re.search(r'\b(35\d{13,15}|\d{15})\b', texto)
        if match:
            imei_buscado = match.group(1)
            p = Product.query.filter((Product.imei == imei_buscado) | (Product.imei2 == imei_buscado)).first()
            if p:
                return p
        return None

class ProviderPayment(db.Model):
    __tablename__ = 'provider_payments'

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=False)
    monto_abonado = db.Column(db.Numeric(12, 2), nullable=False)
    metodo_pago = db.Column(db.String(50), nullable=False, default='efectivo')
    observacion = db.Column(db.String(255), nullable=True)
    fecha_pago = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(ProviderPayment, self).__init__(**kwargs)

class Warranty(db.Model):
    __tablename__ = 'warranties'
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    nombre_manual = db.Column(db.String(200), nullable=True)
    quantity = db.Column(db.Integer, default=1)
    reason = db.Column(db.Text, nullable=False)
    resolution = db.Column(db.String(50), default='Pendiente')
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=obtener_hora_bogota)

    # Relaciones
    sale = db.relationship('Sale', backref=db.backref('warranties', lazy=True))
    product = db.relationship('Product', backref=db.backref('warranties', lazy=True))

    @property
    def tiempo_transcurrido(self):
        tz = pytz.timezone('America/Bogota')
        now = datetime.now(tz).replace(tzinfo=None)
        
        diff = now - self.created_at
        days = diff.days
        seconds = diff.seconds
        
        if days > 0:
            return f"Hace {days} día{'s' if days > 1 else ''}"
        elif seconds >= 3600:
            hours = seconds // 3600
            return f"Hace {hours} hora{'s' if hours > 1 else ''}"
        elif seconds >= 60:
            minutes = seconds // 60
            return f"Hace {minutes} minuto{'s' if minutes > 1 else ''}"
        else:
            return "Hace un momento"
    @property
    def estado_actual(self):
        tz = pytz.timezone('America/Bogota')
        now = datetime.now(tz).replace(tzinfo=None)
        diff = now - self.created_at
        
        # Si sigue pendiente y pasaron más de 5 días, está demorado
        if self.resolution.lower() == 'pendiente' and diff.days > 5:
            return 'Demorado'
        return self.resolution

class PriceApproval(db.Model):
    __tablename__ = 'price_approvals'
    id = db.Column(db.Integer, primary_key=True)
    vendedor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, nullable=True) # opcional
    precio_original = db.Column(db.Numeric(10, 2), nullable=False)
    precio_solicitado = db.Column(db.Numeric(10, 2), nullable=False)
    precio_aprobado = db.Column(db.Numeric(10, 2), nullable=True)
    estado = db.Column(db.String(20), default='pendiente', index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    motivo_rechazo = db.Column(db.String(255), nullable=True)
    fecha_solicitud = db.Column(db.DateTime, default=obtener_hora_bogota)
    fecha_resolucion = db.Column(db.DateTime, nullable=True)

    # Relaciones
    vendedor = db.relationship('User', foreign_keys=[vendedor_id])
    admin = db.relationship('User', foreign_keys=[admin_id])
    product = db.relationship('Product')

class Asesor(db.Model):
    __tablename__ = 'asesores'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=obtener_hora_bogota)

    def __init__(self, **kwargs):
        super(Asesor, self).__init__(**kwargs)


class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'

    id = db.Column(db.Integer, primary_key=True)
    tipo_inventario = db.Column(db.String(50), nullable=False, default='accesorios') # 'celulares' o 'accesorios'
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    numero_factura = db.Column(db.String(100), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    total_costo = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)
    fecha_compra = db.Column(db.DateTime, default=obtener_hora_bogota)

    # Relaciones
    proveedor = db.relationship('Provider', backref=db.backref('compras', lazy=True))
    usuario = db.relationship('User', foreign_keys=[usuario_id])
    items = db.relationship('PurchaseOrderItem', backref='compra', lazy=True, cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super(PurchaseOrder, self).__init__(**kwargs)


class PurchaseOrderItem(db.Model):
    __tablename__ = 'purchase_order_items'

    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    costo_unitario = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0.00)

    # Para celulares con IMEI
    imei = db.Column(db.String(50), nullable=True)
    imei2 = db.Column(db.String(50), nullable=True)

    # Relaciones
    producto = db.relationship('Product')
    variante = db.relationship('ProductVariant')

    def __init__(self, **kwargs):
        super(PurchaseOrderItem, self).__init__(**kwargs)


class BankAccount(db.Model):
    """Modelo para representar los Métodos de Pago / Cuentas Bancarias y su saldo acumulado."""
    __tablename__ = 'bank_accounts'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False, index=True) # ej: efectivo, nequi, bancolombia, daviplata, addi, sitecredito, tarjeta_credito
    nombre = db.Column(db.String(100), nullable=False) # ej: Nequi, Bancolombia, Efectivo en Caja
    tipo = db.Column(db.String(50), nullable=False, default='banco') # 'efectivo', 'banco', 'credito_digital', 'tarjeta'
    icono = db.Column(db.String(50), nullable=True, default='fa-building-columns')
    saldo_actual = db.Column(db.Numeric(14, 2), nullable=False, default=0.00)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    fecha_actualizacion = db.Column(db.DateTime, default=obtener_hora_bogota, onupdate=obtener_hora_bogota)

    movimientos = db.relationship('BankTransaction', backref='cuenta', lazy=True, cascade='all, delete-orphan', order_by='desc(BankTransaction.fecha)')

    def __init__(self, **kwargs):
        super(BankAccount, self).__init__(**kwargs)


class BankTransaction(db.Model):
    """Historial completo de sumas (entradas) y descuentos (salidas) por cuenta bancaria/método de pago."""
    __tablename__ = 'bank_transactions'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=False)
    tipo_movimiento = db.Column(db.String(20), nullable=False) # 'INGRESO' o 'EGRESO' o 'AJUSTE'
    origen = db.Column(db.String(50), nullable=False) # 'ARQUEO_CIERRE', 'ABONO_PROVEEDOR', 'GASTO', 'AJUSTE_MANUAL'
    monto = db.Column(db.Numeric(14, 2), nullable=False)
    saldo_anterior = db.Column(db.Numeric(14, 2), nullable=False, default=0.00)
    saldo_nuevo = db.Column(db.Numeric(14, 2), nullable=False, default=0.00)
    descripcion = db.Column(db.String(255), nullable=True)
    referencia_id = db.Column(db.Integer, nullable=True) # ID de Arqueo, Abono o Gasto
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    fecha = db.Column(db.DateTime, default=obtener_hora_bogota, index=True)

    usuario = db.relationship('User', foreign_keys=[usuario_id])

    def __init__(self, **kwargs):
        super(BankTransaction, self).__init__(**kwargs)

