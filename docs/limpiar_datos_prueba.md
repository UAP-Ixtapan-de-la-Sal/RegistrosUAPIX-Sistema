# Limpieza completa de datos de prueba

`limpiar_datos_prueba` sustituye a `flush` en el entorno local de desarrollo.
Elimina **todos** los datos operativos de la base autorizada. No distingue datos
reales de datos de prueba por nombre, fecha ni usuario que los creó.

## Preparación y ejecución en PowerShell

Detén el servidor y los procesos de importación o captura que escriban en esa
base. Verifica que `DATABASE_URL` en tu configuración apunte a tu base local de
desarrollo y que `DEBUG=True`. Conserva un respaldo si necesitas recuperar datos.

Autoriza explícitamente la limpieza para la sesión actual de la terminal:

```powershell
$env:UAPIX_PERMITIR_LIMPIEZA_PRUEBA = "1"
$env:UAPIX_BD_PRUEBA_PERMITIDAS = "uapix_desarrollo"
```

Reemplaza `uapix_desarrollo` por el nombre **exacto** de tu base local, tal como
está configurado en `DATABASES['default']['NAME']`. La lista admite varios nombres
separados por comas. Para SQLite se utiliza el nombre o ruta exacta configurada;
las URI de archivo y rutas UNC se rechazan. Las variables también pueden
declararse en el `.env` que ya carga el proyecto, pero se recomienda una
autorización temporal en la terminal.

Primero consulta las cantidades, sin escribir ni solicitar confirmación:

```powershell
.\.venv\Scripts\python.exe manage.py limpiar_datos_prueba --dry-run
```

Para borrar, ejecuta desde una terminal interactiva:

```powershell
.\.venv\Scripts\python.exe manage.py limpiar_datos_prueba --confirmar
```

Después del detalle por modelo, escribe exactamente el nombre de la base cuando
el comando lo solicite. Una respuesta distinta, cancelación o entrada redirigida
cancela la operación. No existen `--noinput`, `--force` ni confirmación por variable
de entorno para omitir este paso. Hay que elegir exactamente uno de los dos modos.

Al terminar puedes verificar nuevamente con `--dry-run`: todos los modelos
operativos e históricos deben mostrar cero. Las cuentas protegidas seguirán
apareciendo en el resumen. Retira la autorización de esta terminal:

```powershell
Remove-Item Env:UAPIX_PERMITIR_LIMPIEZA_PRUEBA
Remove-Item Env:UAPIX_BD_PRUEBA_PERMITIDAS
```

## Inspección de modelos y alcance

Se revisaron los 18 modelos operativos actuales de `inicio/models.py`. No existe
una relación de identidad entre `UsuarioSistema` y `Persona`: `UsuarioSistema`
hereda de `AbstractUser` y representa las cuentas de acceso. `Persona` representa
personas institucionales; `PersonaPerfil` es su membresía institucional, con
`CASCADE` hacia `Persona`, y debe eliminarse junto con su historial.

| Modelo operativo | Dependencias principales | Historial simple-history |
| --- | --- | --- |
| Asistencia | Clase y Persona (`CASCADE`), Registro (`PROTECT`), Equipo (`SET_NULL`) | Sí |
| DetallePrestamo | Prestamo, ImplementoTecnologico, Persona y UsuarioSistema (`PROTECT`) | Sí |
| MovimientoInventario | Insumo, Persona y UsuarioSistema (`PROTECT`) | Sí |
| BitacoraFalla | Equipo, ImplementoTecnologico y UsuarioSistema (`PROTECT`) | Sí |
| Registro | Persona (`CASCADE`), Externo (`PROTECT`), Equipo, Clase, Evento y UsuarioSistema (`SET_NULL`) | Sí |
| EventoTallerConferencia | Clase (`SET_NULL`), Persona y Externo (`CASCADE`) | Sí |
| Prestamo | Persona y UsuarioSistema (`PROTECT`) | Sí |
| Clase | Materia, Grupo y Persona (`CASCADE`) | No |
| PersonaPerfil | Persona (`CASCADE`) | Sí |
| Persona | Grupo y Carrera (`SET_NULL`) | No |
| Materia | Carrera (`CASCADE`) | No |
| Grupo | Carrera (`CASCADE`) | No |
| Equipo | Sin padres operativos | Sí |
| Externo | Sin padres operativos | No |
| ImplementoTecnologico | Sin padres operativos | Sí |
| Insumo | CategoriaInsumo (`PROTECT`) | Sí |
| CategoriaInsumo | Sin padres operativos | No |
| Carrera | Sin padres operativos | No |

La tabla sigue el orden de eliminación: primero hijos, después padres. Incluye
las visitas de Sala de Cómputo, Auto Acceso y Biblioteca, asistencias, préstamos y
devoluciones, movimientos y catálogos. También elimina las categorías iniciales
de insumos; no las recrea ni vuelve a ejecutar migraciones.

Los 11 modelos `Historical…` se limpian **después** de los objetos operativos,
incluidas entradas huérfanas y las entradas `-` creadas por `post_delete` de
simple-history. Las FK históricas de los objetos son copias con `DO_NOTHING`
y sin restricción física; `history_user` apunta a `UsuarioSistema` con
`SET_NULL`. `HistoricalBitacoraFalla` también conserva la referencia antigua
`registro`, que se contempla expresamente. El resumen distingue los históricos
existentes antes del borrado y el total eliminado, que incluye los nuevos.

## Información conservada y bloqueos

Se conservan exactamente todas las filas y columnas de `UsuarioSistema`, incluso
visualizadores, operadores y superusuarios: contraseñas cifradas, roles, banderas
de módulos, estado de acceso y demás datos. También se conservan:

- Las tablas intermedias de grupos y permisos de `UsuarioSistema`.
- `auth.Group`, `auth.Permission` y las asignaciones de permisos a grupos.
- `contenttypes.ContentType`, `admin.LogEntry` y `sessions.Session`.
- `django_migrations` y los identificadores de secuencia; no se reinician.

La bitácora administrativa de Django se conserva, aunque una entrada pueda
referirse a un objeto operativo ya eliminado. Los historiales de operaciones
atribuidas a operadores sí se eliminan; sus cuentas y permisos permanecen.

El comando exige simultáneamente `DEBUG=True`, autorización `=1`, pertenencia
exacta a la lista de bases y un motor contemplado. MariaDB/MySQL solo admite
`HOST` vacío, `localhost`, `127.0.0.1` o `::1`. Rechaza opciones que puedan
sustituir la conexión; admite únicamente `charset` y `use_unicode` en MySQL,
y `timeout` y `transaction_mode` en SQLite. No admite routers de bases de datos.
La lista declara qué bases locales son de desarrollo: no añadas bases con datos
que deban conservarse.

Comprueba modelos registrados, relaciones ORM, tablas y FK físicas antes de
borrar. Un modelo, tabla, relación, trigger o dependencia entre bases no
contemplados bloquea la operación, incluso sin registros. Se exige soporte de
transacciones; en MariaDB/MySQL **todas** las tablas contempladas deben ser InnoDB.

Después de la confirmación vuelve a validar el esquema y las cantidades. Dentro
de `transaction.atomic()` bloquea las filas protegidas, guarda su estado, borra
con el ORM y verifica que no queden registros operativos o históricos y que la
información protegida permanezca idéntica. Cualquier error revierte todo. No
utiliza `flush`, SQL destructivo ni desactiva restricciones. Estas comprobaciones
requieren acceso de lectura a los metadatos del esquema.

Ejecuta esta operación con los demás procesos detenidos: las verificaciones de
cantidades no sustituyen una ventana de mantenimiento ni impiden todas las
escrituras concurrentes de otros procesos.

Si se agregan modelos o cambian relaciones, hay que revisar las listas explícitas
y las pruebas del comando antes de habilitarlo de nuevo. No deshabilites los
bloqueos para resolver una discrepancia del esquema.

## Pruebas aisladas

```powershell
.\.venv\Scripts\python.exe manage.py test inicio.test_limpiar_datos_prueba --settings=config.settings_test --noinput
```

El runner crea SQLite en memoria, aplica las migraciones y destruye la base al
terminar. La clase de pruebas rechaza cualquier otra base. Las pruebas crean
datos en los 18 modelos, los 11 historiales, cuentas y permisos; cubren limpieza,
autenticación y sesiones, conservación exacta, simulación, rollback, dependencias
desconocidas y bloqueos de seguridad. Los escenarios de MariaDB se simulan sin
conectar a la base de trabajo. No constituyen una prueba de integración contra
un servidor MariaDB real.
