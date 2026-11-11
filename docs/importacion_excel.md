# Importación Excel en UAPIX

## Estado de integración

Proyecto destino: `C:\Users\BDigital_04\Documents\SistemaUAPIX\RegistrosUAPIX-Sistema`.
Referencia de solo lectura: `C:\Users\BDigital_04\Documents\PRUEBAS-EXCEL`.
Rama de trabajo: `feature/importacion-excel`.

Se integró el esquema institucional de la referencia, con la autorización
expresa de la nueva directiva. El importador procesa las siete hojas con
validación, vista previa, confirmación, detección de conflictos y auditoría.
Un archivo que incluya una fila bloqueante no se guarda parcialmente.

La base de trabajo es **`sistema_universidad`**, mediante la configuración
habitual `config.settings` y el `DATABASE_URL` del archivo `.env`. Se aplicaron
las migraciones `0002`, `0003` y `0004` de inicio a esa base conservando sus registros.
Puedes iniciar el proyecto con `python manage.py runserver`.

La ampliación aprobada permite que una sola persona tenga perfiles de Alumno,
Docente y Administrador simultáneamente. Se conserva una sola matrícula y el
mismo identificador de persona, con sus relaciones existentes.

Por solicitud expresa, se eliminó la base auxiliar
`uapix_importacion_5a206218e082`, junto con la configuración y el comando que
la preparaban. El proyecto ya no requiere esa base ni variables de integración.

## Comparación exhaustiva de modelos

Se compararon los diez modelos declarados, sus campos, tipos, FK, M2M,
restricciones, métodos de validación y registros históricos. No hay modelos
nuevos en la referencia. No se detectaron diferencias adicionales de esquema
fuera de las cuatro operaciones de la integración inicial. La ampliación de
perfiles múltiples es una regla nueva aprobada posteriormente.

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
| PersonaPerfil | No existía | No existe | FK a Persona, perfil y restricción única persona/perfil |
| HistoricalPersonaPerfil | No existía | No existe | Historial de altas y bajas de perfiles, con administrador responsable |

Los nombres de carreras, grupos y materias siguen sin ser UNIQUE. Se mantienen
las claves únicas reales de matrícula y bien patrimonial. No se agregan
restricciones nuevas en esos catálogos. No se crean tablas de importaciones.
Los tres modelos históricos anteriores conservan su estructura y se agrega
el historial de PersonaPerfil.

## Migraciones y base de datos local

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

La ampliación de perfiles agrega dos migraciones dependientes de 0002:

- `0003_perfiles_persona`: crea PersonaPerfil y su historial. La base impide
  repetir la combinación persona/perfil y admite solo los tres perfiles
  institucionales aprobados.
- `0004_migrar_perfiles_actuales`: incorpora el perfil principal actual de
  cada persona y registra su origen en el historial. Usa modelos históricos
  y ORM, es idempotente y no cambia los campos de Persona. La reversa de este
  paso no elimina asociaciones; volver a versiones anteriores que retiren
  las tablas requiere revisar previamente los perfiles nuevos acumulados.

Ambas migraciones ya están aplicadas en `sistema_universidad`. La persona
preexistente mantuvo su cuenta y su perfil principal; se creó su asociación
equivalente y su historial. Las 15 tablas de información del proyecto que
existían antes conservaron sus valores, comprobados por SHA-256. Django agregó
los metadatos y permisos normales de los modelos nuevos; no se otorgaron
permisos de autenticación a ninguna persona o usuario.

Conexión verificada: MariaDB 13.0.2, servicio local en `localhost:3306`, base
efectiva `sistema_universidad`. Antes de migrar solo faltaba
`inicio.0002_integrar_esquema_excel`; las tablas tenían el esquema original.
Se revisaron el plan y el SQL generado antes de aplicarlo.

La migración se aplicó correctamente a `sistema_universidad`. No fue necesario
vaciar tablas, eliminar registros ni restaurar respaldos SQL. Una comparación
por conteo y SHA-256 de los valores preexistentes verificó que los 106 registros
de las 21 tablas de datos permanecieron iguales. `django_migrations` se excluyó
de esa comparación porque recibió el registro normal de la migración aplicada.
Las columnas nuevas son opcionales y sus valores iniciales son NULL.

La estructura también se había validado desde cero en la base auxiliar, antes
de eliminarla por la nueva directiva. Esa base ya no existe. La base temporal
empleada por la suite MariaDB anterior también fue eliminada al finalizar
aquellas pruebas.

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
nueva: hojas opcionales, conservación de los datos existentes e incorporación
de perfiles adicionales. Las contradicciones de identidad o de relaciones
ya informadas bloquean la confirmación.

## Entorno y comandos

La inspección encontró Python 3.14.7, Django 6.1.1, Pandas 3.1.0 y openpyxl
3.1.5 ya instalados en `.venv` del original. `pip check` no reportó conflictos.
No fue necesario instalar ni actualizar paquetes. Se agregó
`pandas>=3.0,<4` a `requirements.txt`, con el rango utilizado en la referencia.

En otro equipo, desde la raíz del original, con MariaDB y un `.env` propio
cuyo `DATABASE_URL` apunte a su base local `sistema_universidad`:

```powershell
py -3.14 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Preparar .env con la configuración propia del equipo; no copiar secretos.
& .\.venv\Scripts\python.exe manage.py check
& .\.venv\Scripts\python.exe manage.py migrate --plan
& .\.venv\Scripts\python.exe manage.py migrate --noinput
& .\.venv\Scripts\python.exe manage.py showmigrations inicio
& .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
& .\.venv\Scripts\python.exe manage.py test --settings=config.settings_test --noinput
& .\.venv\Scripts\python.exe manage.py runserver
```

Comprobar el código de salida de cada comando antes de continuar. No copiar
credenciales de otros equipos. Si la base local no existe todavía, prepararla
en MariaDB con el nombre `sistema_universidad` antes de ejecutar `migrate`.
Las migraciones crean las tablas desde cero o actualizan las existentes,
según el historial de cada equipo; no necesitan un respaldo SQL de la prueba.

En este equipo la migración ya está aplicada; basta con:

```powershell
& .\.venv\Scripts\python.exe manage.py runserver
```

Abrir `http://127.0.0.1:8000/admin/` con la cuenta existente. Si un compañero
prepara una base vacía y necesita su primera cuenta, ejecutar
`python manage.py createsuperuser`. Las cuentas y registros existentes de
este equipo se conservaron.

## Acceso en Django Admin

1. Iniciar sesión en `/admin/` con un superusuario activo o usuario staff con
   los permisos `add_carrera`, `add_grupo`, `add_persona`, `add_materia` y
   `add_equipo` de la aplicación `inicio`.
2. Elegir **Importar Excel** en el encabezado global de Jazzmin.
3. Pulsar **Descargar plantilla Excel** para obtener la plantilla aprobada,
   completar las hojas necesarias y guardar una copia de trabajo.
4. Seleccionar ese `.xlsx` y pulsar **Cargar y validar**.
5. Revisar nuevos, existentes/repetidos, perfiles por agregar, relaciones
   académicas ausentes por incorporar, errores, hojas ignoradas y muestras.
6. Si no hay errores, pulsar **Confirmar importación** antes de 15 minutos.
7. Revisar el resumen real. Ante un error, cargar nuevamente el archivo.

La descarga entrega `inicio/plantillas/Plantilla.xlsx`, copia binaria exacta de
`C:\Users\BDigital_04\Documents\Plantilla.xlsx`, sin reescribir celdas, estilos
ni nombres de hojas. La ruta `/admin/importar-excel/plantilla/` requiere la
misma autenticación y permisos del importador. Se sirve como adjunto privado;
el proyecto no depende de que el archivo permanezca en Documentos del equipo.

El enlace se configura mediante `JAZZMIN_SETTINGS['topmenu_links']` y conserva
menús y registros de admin existentes. La ruta usa `admin.site.admin_view`,
CSRF y comprobación de permisos tanto en la vista como en la confirmación.
Los perfiles de Persona no crean cuentas de UsuarioSistema ni privilegios.

En **Personas**, la edición permite marcar varios **Perfiles institucionales**.
El **Perfil principal** se conserva por compatibilidad y siempre forma parte
de la selección. Para quitarlo debe elegirse otro principal y desmarcar el
anterior. Guardar a una persona mantiene sincronizado ese perfil principal y
conserva los adicionales; cambiar solo sus datos no elimina perfiles.
Los filtros administrativos y las consultas de docentes/ponentes consideran
todos los perfiles. `Persona.objects.con_perfiles(...)` evita resultados
duplicados y `persona.tiene_perfil(...)` comprueba sus perfiles efectivos.

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
- Persona: matrícula única; nombre, apellidos y relaciones ya informadas deben
  coincidir. Los perfiles se acumulan según las hojas, sin sustituir el
  principal. Si se incorpora el perfil Alumno a una persona que no tenía
  grupo/carrera, se pueden completar esas relaciones ausentes. Una carrera
  o grupo diferente ya informado sigue bloqueando el archivo.
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
contradictorios dentro del archivo o contra la base bloquean todo el archivo.
Una misma cuenta en Docentes y Administrativos se guarda como una persona con
ambos perfiles, siempre que sus datos coincidan. No se requiere columna Perfil.
Reimportar no duplica personas, asociaciones ni historial. Nunca se usa
`update_or_create` para sobrescribir datos.

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
Cada desplegable indica, por ejemplo, "muestra de 100 de 1101 registros válidos".
La confirmación procesa todas las filas; el tamaño de la muestra no limita
los registros guardados.

La confirmación usa Django ORM, `full_clean`, `save` y `transaction.atomic`.
Se bloquea la fila ContentType de Carrera mediante `select_for_update` para
serializar confirmaciones entre procesos del importador en MariaDB. Esta
consulta no modifica ContentType ni crea tablas. Los registros existentes se
bloquean durante la revalidación y el guardado. Como varios catálogos carecen
de claves únicas de negocio, se recomienda evitar altas manuales simultáneas
de esos mismos catálogos. El historial de Equipo se crea por sus señales normales con
`_history_user` y motivo de importación; no se usan `bulk_create` ni SQL de
inserción manual. Los modelos que no tenían historial no se alteran para
agregarlo. Los perfiles nuevos sí tienen historial propio y conservan el
administrador responsable al importarlos o gestionarlos desde Django Admin.

## Validación automatizada

Resultados finales:

- Verificación MariaDB anterior: **74 pruebas aprobadas, sin omisiones**, incluida la prueba
  de confirmaciones simultáneas entre conexiones independientes.
- SQLite en memoria, con perfiles múltiples y descarga de plantilla: 98 pruebas ejecutadas, 97 aprobadas y una omitida porque
  SQLite no implementa `select_for_update` (ese caso sí pasó en MariaDB).
- `manage.py check`: sin problemas, tanto en configuración habitual como en
  configuración de pruebas.
- `makemigrations --check --dry-run`: no detecta cambios pendientes.
- `migrate --plan` después de aplicar: ninguna operación pendiente.
- `pip check` y `git diff --check`: sin errores.

Los casos nuevos cubren: perfiles simultáneos, incorporación a personas
existentes, los tres perfiles en una cuenta, conservación del perfil principal,
relaciones académicas ausentes, conflictos reales, restricciones de base,
reimportación, auditoría, reversión, edición y filtros de admin, consultas de
docentes y ponentes, y migración de los perfiles antiguos con historial.
Una prueba confirma 1.101 docentes mediante el flujo web y guarda los 1.101
aunque la muestra tenga 100; otra detecta un error en la fila 1.102 y bloquea
la carga completa. No se usó la base de trabajo para generar esos datos de prueba.

También se comprobó el archivo real `PRUEBAS-EXCEL/BASEDEDATOS.xlsx` mediante
vista previa contra la base auxiliar vacía durante la validación inicial,
antes de eliminarla, sin guardar registros:

| Hoja | Registros leídos | Filas con errores |
|---|---:|---:|
| Carreras | 2 | 0 |
| Grupos | 4 | 0 |
| Alumnos | 104 | 0 |
| Docentes | 18 | 0 |
| Administrativos | 9 | 1 |
| Materias | 118 | 0 |
| Equipos | 50 | 0 |

La tabla anterior documenta la comprobación inicial. Con los perfiles
múltiples, la fila 10 de Administrativos ya se reconoce como la misma persona
con un perfil adicional y no provoca error. En una vista previa actual contra
`sistema_universidad`, la referencia aún detecta el conflicto de carrera del
grupo C1 en Grupos, fila 2, que sigue requiriendo corregir los datos según su
significado institucional. No se modificó el Excel ni se confirmó su carga.

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
`config/urls.py`, `inicio/models.py`, `inicio/admin.py`, `inicio/forms.py`,
`inicio/views.py` (consulta de ponentes).

Creados: `config/settings_test.py`,
`inicio/migrations/0002_integrar_esquema_excel.py`,
`inicio/migrations/0003_perfiles_persona.py`,
`inicio/migrations/0004_migrar_perfiles_actuales.py`, `inicio/forms_persona_admin.py`,
`inicio/forms_importacion.py`,
`inicio/plantillas/Plantilla.xlsx`,
`inicio/views_importacion.py`, `inicio/services/__init__.py`,
`inicio/services/importacion_excel.py`, `inicio/services/importacion_temporal.py`,
`inicio/templates/admin/inicio/importar_excel.html`,
`inicio/test_importacion_excel.py`, `inicio/test_migracion_excel.py`,
`inicio/test_perfiles_persona.py` y este documento.

Retirados por la nueva directiva: `config/settings_integracion.py`,
`inicio/management/commands/preparar_bd_importacion.py` y los dos `__init__.py`
que solo daban soporte a ese comando.

El importador no reemplaza las vistas, formularios ni plantillas existentes
de los módulos. La actualización de la base no modifica ramas ni el stash.
Los archivos de PRUEBAS-EXCEL permanecen como fuente de lectura.
