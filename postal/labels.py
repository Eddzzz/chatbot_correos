"""Spanish display labels; result keys and evidence remain unchanged."""
import re


COLUMN_LABELS = {
    'id': 'Identificador', 'codigo': 'Código', 'origen': 'Origen', 'destino': 'Destino',
    'ciudad': 'Ciudad', 'cuidad': 'Ciudad', 'peso': 'Peso', 'precio': 'Precio',
    'cantidad': 'Cantidad', 'tipo': 'Tipo', 'pais': 'País',
    'tipo_correspondencia': 'Tipo de correspondencia',
    'created_at': 'Fecha de creación', 'updated_at': 'Fecha de actualización',
    'fecha_recojo': 'Fecha de recojo', 'fechaEvento': 'Fecha del evento',
    'fechaActualizacion': 'Fecha de actualización',
    'name': 'Nombre', 'nombre': 'Nombre', 'nombre_estado': 'Estado',
    'nombre_evento': 'Evento', 'nombre_servicio': 'Servicio', 'activo': 'Activo',
    'codigoSucursal': 'Código de sucursal', 'puntoVenta': 'Punto de venta',
    'nombre_sucursal': 'Sucursal',
    'telefono': 'Teléfono',
    'municipio': 'Municipio', 'departamento': 'Departamento', 'rol': 'Rol',
    'estado_id': 'Identificador del estado', 'estados_id': 'Identificador del estado',
    'fk_estado': 'Identificador del estado', 'fk_ventanilla': 'Identificador de ventanilla',
    'user_id': 'Identificador del usuario', 'role_id': 'Identificador del rol',
    'sucursal_id': 'Identificador de sucursal', 'servicio_id': 'Identificador del servicio',
    'destino_id': 'Identificador del destino', 'evento_id': 'Identificador del evento',
    'paquete_ems_id': 'Identificador del paquete EMS',
    'count': 'Cantidad', 'sum': 'Suma', 'avg': 'Promedio', 'min': 'Mínimo', 'max': 'Máximo',
    'total': 'Total', 'total_envios': 'Total de envíos', 'total_paquetes': 'Total de paquetes',
    'total_movimientos': 'Total de movimientos', 'codigos_con_movimientos': 'Códigos con movimientos',
    'promedio_peso': 'Peso promedio', 'promedio_precio': 'Precio promedio',
    'total_precio': 'Precio total', 'total_peso': 'Peso total',
    'consulta_permitida': 'Consulta permitida', 'relacion_declarada': 'Relación declarada',
}
LABEL_WORDS = {
    'id': 'identificador', 'name': 'nombre', 'code': 'código', 'city': 'ciudad',
    'country': 'país', 'origin': 'origen', 'destination': 'destino', 'weight': 'peso',
    'price': 'precio', 'quantity': 'cantidad', 'count': 'cantidad', 'shipments': 'envíos',
    'shipment': 'envío', 'packages': 'paquetes', 'package': 'paquete',
    'status': 'estado', 'service': 'servicio', 'user': 'usuario', 'role': 'rol',
    'branch': 'sucursal', 'date': 'fecha', 'month': 'mes', 'year': 'año',
    'average': 'promedio', 'avg': 'promedio', 'sum': 'suma', 'min': 'mínimo', 'max': 'máximo',
    'codigo': 'código', 'pais': 'país', 'anio': 'año', 'ano': 'año',
    'ultimo': 'último', 'ultima': 'última', 'actualizacion': 'actualización',
    'creacion': 'creación', 'envio': 'envío', 'envios': 'envíos', 'minimo': 'mínimo', 'maximo': 'máximo',
}


def column_label(column):
    if column in COLUMN_LABELS:
        return COLUMN_LABELS[column]
    words = re.sub(r'([a-z])([A-Z])', r'\1 \2', column).replace('_', ' ').split()
    label = ' '.join(LABEL_WORDS.get(word.lower(), word) for word in words)
    return label[:1].upper() + label[1:]
