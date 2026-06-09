# Clients QR

Plataforma de registro de compras por QR en Python.

La aplicacion esta pensada para un uso simple en un local:

- un QR fijo apunta siempre al mismo enlace;
- el cliente entra, completa sus datos y recibe solo un mensaje de exito o fallo;
- el administrador ve clientes, compras, filtros y estadisticas;
- la informacion se guarda en una base relacional para soportar consultas y reportes.

## Objetivo funcional

El sistema registra personas y compras asociadas a cada cliente.
Cada cliente puede tener muchas compras y cada compra conserva su fecha y estado.
No se guarda monto, ni usuario que confirma la compra, ni beneficios en esta version.

## Stack

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL en NeonDB como base de produccion
- SQLite para desarrollo local
- Google Sign-In para acceso administrativo

## Estructura del proyecto

- `app/main.py`: aplicacion principal y rutas base
- `app/routes/public.py`: flujo publico del QR
- `app/routes/admin.py`: panel y endpoints administrativos
- `app/routes/auth.py`: autenticacion con Google
- `app/models.py`: modelo de datos
- `app/services.py`: logica de negocio y consultas
- `app/core/session.py`: sesiones firmadas
- `tests/test_app.py`: pruebas automatizadas

## Archivo `.env`

El proyecto incluye un archivo `.env` en la raiz para que completes los valores antes de ejecutar la app.

Variables disponibles:

- `DATABASE_ENV`: seleccion del entorno de base de datos.
  - `local` usa SQLite.
  - `neon` usa la base declarada en `DATABASE_URL_NEON`.
- `DATABASE_URL`: override explicito de la base activa. Si esta definido, tiene prioridad sobre todo lo demas.
- `DATABASE_URL_LOCAL`: direccion de la base local.
  - por defecto: `sqlite:///./clients_qr.db`
- `DATABASE_URL_NEON`: direccion de NeonDB para produccion.
- `SECRET_KEY`: clave privada para firmar sesiones.
- `PUBLIC_TOKEN`: token fijo que usa el QR publico.
- `SESSION_COOKIE_SECURE`: `true` en produccion, `false` en local.
- `APP_ENV`: `development`, `test` o `production`.
- `APP_NAME`: nombre visible de la aplicacion.
- `ADMIN_EMAIL_ALLOWLIST`: emails permitidos para ingresar al panel.
- `ADMIN_LOCAL_ACCOUNTS`: credenciales locales permitidas en formato `mail:telefono` separadas por coma.
- `GOOGLE_CLIENT_ID`: id de cliente OAuth de Google.
- `GOOGLE_CLIENT_SECRET`: secreto OAuth de Google.
- `GOOGLE_REDIRECT_PATH`: ruta de callback para login admin.
- `PUBLIC_GOOGLE_REDIRECT_PATH`: ruta de callback para login publico.

## Como usarlo en local

### 1. Crear entorno virtual

```bash
python -m venv .venv
```

### 2. Activar el entorno

En Windows PowerShell:

```bash
. .venv/Scripts/activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Completar el archivo `.env`

Definilo con tus valores reales.
Para pruebas locales, podes dejar `DATABASE_ENV=local` y usar la SQLite por defecto.
Si queres apuntar a Neon, definí `DATABASE_ENV=neon` y `DATABASE_URL_NEON`.

### 5. Levantar la aplicacion

```bash
uvicorn app.main:app --reload
```

### 6. Abrir la app

- Registro publico: `http://127.0.0.1:8000/r/qr-local`
- Panel admin: `http://127.0.0.1:8000/admin`
- Salud: `http://127.0.0.1:8000/health`

## Manual de uso para el usuario final

Este flujo es para la persona que escanea el QR.

### Paso a paso

1. Escanear el QR del local.
2. Abrir el enlace que lleva a la pantalla de registro.
3. Completar:
   - nombre,
   - apellido,
   - telefono,
   - mail si corresponde.
4. Si quiere usar Google, puede iniciar sesion con Google desde la misma pantalla.
5. Confirmar el envio.
6. El sistema muestra solo uno de estos resultados:
   - `Registro exitoso`
   - `Registro fallido`

### Importante

- El usuario final no tiene panel.
- El usuario final no ve historial.
- El usuario final no necesita navegar por otras pantallas.
- El objetivo es registrar la compra o el intento de registro de la forma mas simple posible.

## Manual de uso para administracion

### Ingreso al panel

1. Abrir `/admin`.
2. Elegir una de las dos vias de acceso:
   - Google, con el correo incluido en `ADMIN_EMAIL_ALLOWLIST`.
   - Mail y telefono, con la combinacion exacta definida en `ADMIN_LOCAL_ACCOUNTS`.
3. En el acceso local:
   - el mail funciona como usuario,
   - el telefono funciona como contraseña,
   - ambos deben coincidir con una credencial permitida.

### Que puede hacer el panel

- buscar clientes por nombre, apellido, telefono o mail;
- filtrar compras por una fecha puntual;
- filtrar compras entre dos fechas;
- encontrar clientes que no compran desde una fecha dada hasta hoy;
- filtrar por estado de compra:
  - `pendiente`
  - `aprobada`
  - `rechazada`
  - `fallida`
- ver el detalle de cada cliente;
- ver el historial de compras;
- ver estadisticas generales del sistema;
- aprobar o rechazar compras pendientes.

## Flujo de datos

1. El cliente abre la pantalla publica.
2. El sistema crea o vincula el cliente.
3. Se registra una compra con estado inicial `pendiente` o un intento fallido.
4. El administrador revisa la compra desde el panel.
5. El estado de la compra cambia a `aprobada` o `rechazada` si corresponde.
6. Las estadisticas se calculan a partir de clientes, compras y registros de intento.

## Modelos principales

### Customer

- nombre
- apellido
- telefono
- mail
- identidad de Google opcional
- estado
- fechas de creacion y actualizacion

### Purchase

- cliente asociado
- fecha de compra
- estado
- token de origen del QR
- notas opcionales

### RegistrationAttempt

- cliente asociado o nulo
- estado del intento
- motivo de fallo
- fecha
- origen
- hashes anonimizados de IP y user agent

### AuditLog

- quien realizo la accion
- que accion hizo
- sobre que entidad
- valores antes y despues
- fecha

## Estados de compra

- `pending`: compra creada y pendiente de revision.
- `approved`: compra validada por administracion.
- `rejected`: compra descartada por administracion.
- `failed`: intento fallido de registro.

## Estadisticas incluidas

El panel expone y resume:

- total de personas que interactuaron;
- cantidad de registros exitosos;
- cantidad de registros fallidos;
- cantidad de compras pendientes;
- cantidad de compras aprobadas;
- cantidad de compras rechazadas;
- cantidad de compras fallidas;
- clientes unicos;
- actividad por dia;
- actividad por rango de fechas;
- clientes inactivos desde una fecha determinada;
- tasa de conversion entre intentos y compras aprobadas.

## Seguridad

El sistema usa estas medidas:

- acceso al panel restringido por allowlist de emails;
- acceso al panel por Google o por credenciales locales permitidas;
- sesiones firmadas;
- separacion de rutas publicas y privadas;
- validacion de inputs en el backend;
- salida HTML escapada para evitar inyeccion;
- auditoria de acciones de administracion;
- base de datos separada del acceso publico.

## Pruebas

El proyecto incluye pruebas automatizadas para verificar:

- alta de cliente y compra publica;
- proteccion del panel sin sesion valida;
- filtros de administracion;
- estadisticas basicas.

Ejecutar:

```bash
pytest -q -p no:cacheprovider
```

## Despliegue recomendado

Para produccion, la recomendacion es:

- desplegar la app en el host que se defina para produccion;
- usar NeonDB PostgreSQL como base de datos;
- guardar secretos y credenciales en el entorno de despliegue;
- dejar `SESSION_COOKIE_SECURE=true`;
- configurar Google OAuth con el dominio real del sistema.

## Cambio entre bases

El proyecto soporta dos bases con el mismo esquema logico:

- `DATABASE_ENV=local` -> SQLite local.
- `DATABASE_ENV=neon` -> NeonDB, usando `DATABASE_URL_NEON`.

Si queres forzar una base puntual sin importar el entorno, definí `DATABASE_URL` y va a tener prioridad.

## Notas operativas

- El QR debe apuntar siempre a la misma URL.
- Para el local conviene imprimir el enlace fijo una sola vez y reutilizarlo.
- Si el dominio cambia, el QR debera reimprimirse.
- Si queres, despues se puede agregar exportacion CSV, graficos mas avanzados o migraciones con Alembic.
