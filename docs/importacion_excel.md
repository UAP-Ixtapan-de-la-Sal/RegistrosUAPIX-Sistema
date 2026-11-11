# Importación Excel en UAPIX

## Estado de integración

Proyecto destino: `C:\Users\BDigital_04\Documents\SistemaUAPIX\RegistrosUAPIX-Sistema`.
Referencia de solo lectura: `C:\Users\BDigital_04\Documents\PRUEBAS-EXCEL`.
Rama de trabajo: `feature/importacion-excel`.

Se integró el esquema institucional de la referencia, con la autorización
expresa de la nueva directiva. El importador procesa las siete hojas con
validación, vista previa, confirmación, detección de conflictos y auditoría.
Un archivo que incluya una fila bloqueante no se guarda parcialmente.

Se generó una migración nueva y se aplicó desde cero exclusivamente a
`uapix_importacion_5a206218e082`, creada vacía en MariaDB local. La configuración
habitual y `.env` siguen apuntando a `sistema_universidad`, como antes; esa base
no se migró, eliminó ni vació. Para usar el esquema nuevo en este equipo,
iniciar Django con `config.settings_integracion`, como se indica más abajo.

## Comparación exhaustiva de modelos

Se compararon los diez modelos declarados, sus campos, tipos, FK, M2M,
restricciones, métodos de validación y registros históricos. No hay modelos
nuevos en la referencia. No se detectaron diferencias adicionales de esquema
fuera de las cuatro operaciones siguientes.

| Modelo / aspecto | Original antes de integrar | PRUEBAS-EXCEL | Resultado integrado |
|---|---|---|---|
| Persona.grupo | No existía | FK a Grupo, nullable, opcional, SET_NULL, related_name='alumnos' | Incorporado con esos mismos atributos |
| Persona.clean | Sin esta validación | El grupo debe pertenecer a la carrera de Persona | Incorporada |
| Materia.semestre | No existía | IntegerField(null=True, blank=True) | Incorporado |
| Grupo.semestre | IntegerField obligatorio | IntegerField(null=True, blank=True) | Campo opcional como en la referencia |
| Grupo.turno | CharField(max_length=20) obligatorio | Mismo tipo y longitud, blank=True | Opcional; sigue sin aceptar NULL |
| Grupo.__str__ | Incluía semestre y turno siempre | Omite metadatos vacíos | Admite vacíos y conserva la presentación original cuando ambos datos existen |
| Clase.clean | Fechas y tolerancia con hora local | Usa timezone.now() | Se conserva la lógica local del original para no cambiar la agenda |
| Carrera | Campos y restricciones actuales | Mismos campos y restricciones | Sin cambios |
| UsuarioSistema | Usuario, roles y módulos actuales, M2M de autenticación | Misma estructura | Sin cambios de autenticación o privilegios |
| Externo | Campos actuales | Misma estructura | Sin cambios |
| Clase | FK a materia, grupo y docente | Mismas relaciones y campos | Sin cambios de esquema |
| EventoTallerConferencia | Campos, validaciones e historial actuales | Misma estructura | Sin cambios |
| Equipo | Bien patrimonial único, choices e historial | Misma estructura | Sin cambios |
| Registro | Relaciones, validaciones e historial | Misma estructura | Sin cambios |

Los nombres de carreras, grupos y materias siguen sin ser UNIQUE. Se mantienen
las claves únicas reales de matrícula y bien patrimonial. No se agregan
restricciones inventadas, relaciones M2M, modelos ni tablas de importación.
Los tres modelos históricos de django-simple-history conservan su estructura.

## Migración nueva y base de datos local

`inicio/migrations/0002_integrar_esquema_excel.py` fue generada con Django desde
el estado del original y depende de `inicio.0001_initial`. Contiene solamente:

1. AddField de `Materia.semestre`, nullable, sin valor predeterminado ficticio.
2. AddField de `Persona.grupo`, nullable, con ForeignKey y SET_NULL.
3. AlterField de `Grupo.semestre` para admitir NULL y formulario vacío.
4. AlterField de `Grupo.turno` para admitir formulario vacío.

No contiene RunSQL, RunPython, borrado de tablas ni migraciones de datos.
`Persona.clean` y `Grupo.__str__` no requieren operaciones de esquema.
`0001_initial.py` permanece intacta; no se copiaron ni renumeraron migraciones
de la referencia.

Conexión verificada: MariaDB 13.0.2, servicio local en `localhost:3306`. Tanto
el original como la referencia apuntaban a `sistema_universidad`. Se creó un
nombre aleatorio independiente y se comprobó que no existía antes de crearlo;
la introspección confirmó cero tablas antes de revisar y aplicar el plan.

Resultado en `uapix_importacion_5a206218e082`: 22 tablas, 20 migraciones
aplicadas, FK de Persona a Grupo verificada y cero registros en Carrera,
Grupo, Persona, Materia y Equipo. No hay operaciones de migración pendientes
ni cambios de modelos sin migración.

La suite MariaDB utilizó otra base nueva:
`test_uapix_importacion_5a206218e082`. Se verificó que no existía antes de
ejecutarla y Django la eliminó al terminar. La base de integración con su
esquema vacío permanece disponible. No se restauraron respaldos SQL.

## Referencia y adaptaciones

Se reutilizaron los encabezados, orden de dependencias, `normalize_header`,
`cell_text`, concatenación de apellidos, perfiles y alias de lugares de:

- `inicio/management/commands/importar_excel.py`.
- `inicio/management/commands/_importar_catalogos.py`.

También se consultaron `inicio/models.py`, `inicio/tests.py`,
`inicio/test_importar_catalogos.py`, `requirements.txt`, `README.md`,
configuración, admin, formularios, vistas, rutas y estructura de plantillas.

La referencia tiene un comando de gestión; no tiene un botón global ni un
flujo web de vista previa y confirmación que pueda trasladarse. Esas partes
se agregaron al original. La referencia actualiza registros, exige las siete
hojas y admite precedencias entre perfiles. Aquí se aplica la instrucción
nueva: hojas opcionales, ningún dato existente se actualiza y todo conflicto
bloquea la confirmación.

## Entorno y comandos

La inspección encontró Python 3.14.7, Django 6.1.1, Pandas 3.1.0 y openpyxl
3.1.5 ya instalados en `.venv` del original. `pip check` no reportó conflictos.
No fue necesario instalar ni actualizar paquetes. Se agregó
`pandas>=3.0,<4` a `requirements.txt`, con el rango utilizado en la referencia.

En otro equipo, desde la raíz del original, con MariaDB local y `.env` propio
configurado para ese servidor (la cuenta debe poder crear bases nuevas):

```powershell
py -3.14 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Preparar .env con la configuración propia del equipo; no copiar secretos.
& .\.venv\Scripts\python.exe manage.py check
& .\.venv\Scripts\python.exe manage.py test --settings=config.settings_test --noinput

# Elegir una base nueva y aislada; no reutilizar una base compartida.
$integrationSuffix = [guid]::NewGuid().ToString('N').Substring(0,12)
$env:UAPIX_INTEGRATION_DB = "uapix_importacion_$integrationSuffix"
& .\.venv\Scripts\python.exe manage.py preparar_bd_importacion --settings=config.settings_integracion
& .\.venv\Scripts\python.exe manage.py migrate --plan --settings=config.settings_integracion
& .\.venv\Scripts\python.exe manage.py migrate --settings=config.settings_integracion --noinput
& .\.venv\Scripts\python.exe manage.py showmigrations --settings=config.settings_integracion
& .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings_integracion
& .\.venv\Scripts\python.exe manage.py test --settings=config.settings_integracion --noinput

# Crear la cuenta local elegida por el desarrollador y abrir el administrador.
& .\.venv\Scripts\python.exe manage.py createsuperuser --settings=config.settings_integracion
& .\.venv\Scripts\python.exe manage.py runserver --settings=config.settings_integracion
```

Comprobar el código de salida de cada comando antes de continuar. El comando
de preparación rechaza nombres existentes: no los reutiliza ni los vacía.
La configuración de integración rechaza servidores remotos, nombres sin el
prefijo/formato previsto y el nombre de la base configurada en DATABASE_URL.
No modifica `.env` ni exige instalar dependencias globales.

Para reabrir la base ya preparada en este equipo, sin volver a crearla:

```powershell
$env:UAPIX_INTEGRATION_DB = 'uapix_importacion_5a206218e082'
& .\.venv\Scripts\python.exe manage.py createsuperuser --settings=config.settings_integracion
& .\.venv\Scripts\python.exe manage.py runserver --settings=config.settings_integracion
```

No se creó una cuenta persistente automáticamente. Después de crear tu cuenta,
abrir `http://127.0.0.1:8000/admin/`. Para una base institucional o compartida,
la aplicación de estas migraciones sigue requiriendo su procedimiento propio;
los comandos anteriores actúan solamente sobre la nueva base local.

## Acceso en Django Admin

1. Iniciar sesión en `/admin/` con un superusuario activo o usuario staff con
   los permisos `add_carrera`, `add_grupo`, `add_persona`, `add_materia` y
   `add_equipo` de la aplicación `inicio`.
2. Elegir **Importar Excel** en el encabezado global de Jazzmin.
3. Seleccionar un `.xlsx` y pulsar **Cargar y validar**.
4. Revisar nuevos, existentes/repetidos, errores, hojas ignoradas y muestras.
5. Si no hay errores, pulsar **Confirmar importación** antes de 15 minutos.
6. Revisar el resumen real. Ante un error, cargar nuevamente el archivo.

El enlace se configura mediante `JAZZMIN_SETTINGS['topmenu_links']` y conserva
menús y registros de admin existentes. La ruta usa `admin.site.admin_view`,
CSRF y comprobación de permisos tanto en la vista como en la confirmación.
Los perfiles de Persona no crean cuentas de UsuarioSistema ni privilegios.

## Plantilla y relaciones

| Hoja | Encabezados |
|---|---|
| Carreras | Carrera |
| Grupos | Grupo, Carrera, Semestre, Turno |
| Alumnos | Cuenta, Nombre, Apellido Paterno, Apellido Materno, Grupo |
| Docentes | Cuenta, Nombre, Apellido Paterno, Apellido Materno |
| Administrativos | Cuenta, Nombre, Apellido Paterno, Apellido Materno |
| Materias | Materia, Carrera, Semestre |
| Equipos | No. Equipo, No. Bien Patrimonial, Lugar |

Se procesan en este orden, aunque las pestañas estén ordenadas de otra manera.
Las hojas ausentes, completamente vacías o solo con encabezados se omiten.
Las filas vacías se ignoran; se conservan sus números originales para informar
errores. Una hoja desconocida con registros o encabezados duplicados bloquea
el archivo para evitar omisiones accidentales.

Una relación se resuelve en las filas previas del Excel o en datos existentes.
Carreras se resuelven por nombre y grupos por código, sin suponer que esos
campos tengan restricción UNIQUE. Si hay varias coincidencias, se bloquea.
No se crean relaciones ficticias. El alumno recibe el grupo y su carrera.
La validación de Persona comprueba la coherencia de esa relación. El esquema
permite grupos sin semestre/turno, como la referencia; la hoja Grupos del
formato de siete hojas sigue requiriendo ambos valores, igual que el importador
de catálogos de referencia. Las materias conservan su semestre en el modelo.

## Identidad y conservación

- Carrera: nombre normalizado, exigiendo una coincidencia inequívoca.
- Grupo: código inequívoco; carrera, semestre y turno deben coincidir.
- Persona: matrícula; todos los datos incluidos y su perfil deben coincidir.
- Materia: combinación nombre/carrera/semestre, como la referencia; permite
  semestres distintos y bloquea varias coincidencias del mismo conjunto. Si
  existe una materia antigua sin semestre, se informa la ambigüedad en vez de
  actualizarla o crear un posible duplicado.
- Equipo: bien patrimonial único; número y lugar deben coincidir. Estado,
  condición e historial existentes se conservan.

Textos equivalentes por mayúsculas/minúsculas o espacios sobrantes no crean
duplicados ni modifican el texto almacenado. No se eliminan acentos del
contenido. Los identificadores textuales conservan ceros iniciales; un número
Excel `123.0` se lee como `123`. Si Excel ya almacenó una cuenta como número,
sus ceros iniciales no se pueden recuperar: guardar las cuentas como texto.
Las celdas vacías no se convierten en la cadena `NaN`.

Repeticiones idénticas se contabilizan como existentes/repetidas; los datos
contradictorios dentro del archivo, entre perfiles o contra la base bloquean
todo el archivo. Nunca se usa `update_or_create` para sobrescribir datos.

La plantilla `BASEDEDATOS.xlsx` de referencia y la plantilla de auditoría del
original no contienen fórmulas. Conforme a la instrucción, no se añadió un
subsistema especial de evaluación/detección de fórmulas. Pandas/openpyxl leen
valores guardados y no calculan fórmulas; un resultado vacío en un campo
obligatorio se rechaza por la validación normal.

## Integridad y temporales

La vista previa ejecuta exclusivamente consultas de lectura sobre los modelos.
No crea objetos ni historial para simular la importación. La autenticación y
persistencia normal de sesiones de Django conservan su comportamiento previo.

El Excel válido se guarda con nombre aleatorio en `.importaciones/`, fuera de
las rutas públicas y excluido de Git. El navegador recibe un token firmado
con usuario, huella de sesión, huella del archivo y caducidad de 15 minutos;
no envía registros confiables. Al confirmar, un renombrado atómico consume el
archivo una sola vez, se verifica su huella y se vuelve a validar todo contra
el estado actual de la base. La copia consumida se elimina incluso si falla
la confirmación. Los archivos vencidos se purgan al cargar el siguiente
archivo. `EXCEL_IMPORT_TEMP_DIR` permite configurar un directorio privado
compartido entre procesos del mismo servidor; debe protegerse con los permisos
de la cuenta del servicio y nunca publicarse como contenido estático.

Límites: 5 MB de archivo, 50 MB de contenido ZIP expandido, 5.000 miembros ZIP,
20.000 registros totales, 20.000 filas físicas después del encabezado por hoja
(incluidas las vacías) y 64 columnas. La vista previa muestra hasta 100 filas
válidas por hoja, pero valida todas las filas permitidas.

La confirmación usa Django ORM, `full_clean`, `save` y `transaction.atomic`.
Se bloquea la fila ContentType de Carrera mediante `select_for_update` para
serializar confirmaciones entre procesos del importador en MariaDB. Esta
consulta no modifica ContentType ni crea tablas. No coordina escrituras
ajenas al importador: al carecer varios catálogos de claves únicas de negocio,
se recomienda no editar esos mismos catálogos manualmente durante una
confirmación. El historial de Equipo se crea por sus señales normales con
`_history_user` y motivo de importación; no se usan `bulk_create` ni SQL de
inserción manual. Los modelos que no tenían historial no se alteran para
agregarlo.

## Validación automatizada

Resultados finales:

- MariaDB local: **74 pruebas aprobadas, sin omisiones**, incluida la prueba
  de confirmaciones simultáneas entre conexiones independientes.
- SQLite en memoria: 74 pruebas ejecutadas, 73 aprobadas y una omitida porque
  SQLite no implementa `select_for_update` (ese caso sí pasó en MariaDB).
- `manage.py check`: sin problemas, tanto en configuración habitual como en
  configuración de pruebas/integración.
- `makemigrations --check --dry-run`: no detecta cambios pendientes.
- `migrate --plan` después de aplicar: ninguna operación pendiente.
- `pip check` y `git diff --check`: sin errores.

También se comprobó el archivo real `PRUEBAS-EXCEL/BASEDEDATOS.xlsx` mediante
vista previa contra la nueva base vacía, sin guardar registros:

| Hoja | Registros leídos | Filas con errores |
|---|---:|---:|
| Carreras | 2 | 0 |
| Grupos | 4 | 0 |
| Alumnos | 104 | 0 |
| Docentes | 18 | 0 |
| Administrativos | 9 | 1 |
| Materias | 118 | 0 |
| Equipos | 50 | 0 |

**Dato pendiente de corregir en una copia del Excel:** la fila 10 de
Administrativos comparte una cuenta con otro perfil. La referencia resolvía
esa situación por precedencia; la regla nueva exige bloquear conflictos sin
sobrescribir. Por eso ese archivo no es confirmable hasta resolver el perfil.
No se modificó el archivo de referencia ni se importó parcialmente.

La huella SHA-256 agregada de archivos de la referencia (sin entorno virtual,
Git ni cachés Python) coincidió antes y después de la integración:
`d5050ea243ca1ed5db25011581e3dffae54a9c6d5779a114bcee668aab170166`.

`config.settings_test` sustituye completamente `DATABASES` por SQLite en
memoria antes de abrir conexiones. No usa el nombre ni el servidor de la
base institucional. Las pruebas aplican las migraciones existentes solamente
a esa base efímera. No ejecutar las pruebas del importador con configuración
institucional.

La suite incluye las pruebas previas de la aplicación y las nuevas de lectura,
hojas opcionales/vacías, encabezados, conflictos, identidad, relaciones,
reimportación, límites, archivos corruptos, permisos, CSRF, historial,
revalidación, reversión, caducidad y confirmación única. Se verifican las siete
hojas, materias por semestre, la coherencia carrera/grupo, SET_NULL y la
relación inversa `grupo.alumnos`. Una prueba de migración recorre 0001 → 0002
con datos previos y acredita su conservación. Las pruebas previas de login,
agenda, formularios y vistas siguen aprobadas en ambos motores.

## Archivos implementados

Modificados: `.gitignore`, `requirements.txt`, `config/settings.py`,
`config/urls.py`, `inicio/models.py`, `inicio/admin.py`.

Creados: `config/settings_test.py`, `config/settings_integracion.py`,
`inicio/migrations/0002_integrar_esquema_excel.py`,
`inicio/management/__init__.py`, `inicio/management/commands/__init__.py`,
`inicio/management/commands/preparar_bd_importacion.py`, `inicio/forms_importacion.py`,
`inicio/views_importacion.py`, `inicio/services/__init__.py`,
`inicio/services/importacion_excel.py`, `inicio/services/importacion_temporal.py`,
`inicio/templates/admin/inicio/importar_excel.html`,
`inicio/test_importacion_excel.py`, `inicio/test_migracion_excel.py` y este documento.

La implementación no cambia las vistas, formularios, rutas ni plantillas de
Sala de Cómputo, Auto Acceso o Biblioteca. No se hicieron commits, cambios de
rama, push, fusiones ni operaciones sobre el stash. La referencia permanece
como fuente de lectura; no se ejecuta código dentro de su entorno virtual.
