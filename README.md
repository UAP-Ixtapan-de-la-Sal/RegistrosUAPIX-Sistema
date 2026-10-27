# RegistrosUAPIX

Aplicación Django para la gestión de registros de UAPIX. El código fuente de
estilos, JavaScript, imágenes y videos se conserva en `inicio/static/inicio/`.
`staticfiles/` es un directorio generado por `collectstatic` y no forma parte
del código fuente.

## Requisitos

- Python 3.14 (o la versión compatible con las dependencias de `requirements.txt`).
- MariaDB y una base de datos vacía creada para este proyecto.
- Git.

## Configuración local en Windows

Desde la carpeta del proyecto, en PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env` con una clave secreta nueva y los datos de **tu propia base de
datos**. No compartas ni subas ese archivo. Crea la base MariaDB antes de
continuar; no apuntes la aplicación a una base de datos con información
existente al preparar una instalación nueva.

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py runserver
```

Para recopilar los archivos estáticos en una instalación de despliegue:

```powershell
python manage.py collectstatic
```

El comando genera `staticfiles/`; no edites ni agregues allí recursos fuente.
Los cambios de CSS, JavaScript, imágenes y videos deben realizarse en
`inicio/static/inicio/`.

## Pruebas y migraciones

Las migraciones versionadas de `inicio/migrations/` describen el esquema que
se instala en una base nueva. Al cambiar los modelos, genera y revisa las
migraciones, agrégalas al control de versiones y pruébalas sobre una base de
pruebas vacía. No borres migraciones ni recrees una base que contenga datos para
resolver discrepancias.

```powershell
python manage.py makemigrations
python manage.py migrate --plan
python manage.py test
```

## Trabajo en equipo

Después de publicar el repositorio de la organización, clona la URL que esta
proporcione y prepara tu entorno siguiendo los pasos anteriores. Usa `dev` como
rama de integración; `frontend`, `backend` y `db` son ramas de trabajo basadas
en la misma versión inicial. Antes de empezar una tarea, actualiza tu rama:

```powershell
git switch dev
git pull
git switch -c feature/nombre-de-la-tarea
```

Envía los cambios mediante una rama de trabajo y una solicitud de cambios hacia
`dev`. Integra a `main` mediante el flujo de revisión acordado por el equipo.
No publiques `.env`, entornos virtuales, bases de datos, respaldos SQL ni el
contenido de `staticfiles/`.
