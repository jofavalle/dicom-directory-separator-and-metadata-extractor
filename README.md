# DICOM Directory Separator and Metadata Extractor

Herramienta en Python para:
- Separar y organizar estudios DICOM mezclados (de CD/DVD) por Prueba (Serie), incluyendo nombre de Paciente y Protocolo en la carpeta de salida.
- Copiar y renombrar secuencialmente las imágenes (0001.ext, 0002.ext, …) preservando la extensión, ideal para ImageJ.
- Exportar CSVs de metadatos (global, por paciente y por paciente/protocolo) y generar reportes básicos de QA.

Importante: nunca se cambia el tipo de archivo. Solo se renombra el nombre base en las copias organizadas; los originales no se modifican.

## Requisitos
- Python 3.9+
- Paquetes: `pydicom`, `pandas`, `pyyaml` (se instalan con `pip install -e .`)

## Uso en Linux
Dentro del directorio que contiene `dicomdir` y/o la carpeta `dicom/`:

```bash
# A) Usar el script directamente
python3 script/organize-dicom.py \
  --input . \
  --output organized_by_test \
  --config config.yaml

# B) Instalar el comando y usarlo
pip install -e .
organize-dicom --input . --output organized_by_test --config config.yaml
```

## Uso en Windows
En PowerShell, dentro del directorio que contiene `dicomdir` y/o la carpeta `dicom/`:

```powershell
# A) Instalar el comando (una sola vez en el entorno)
python -m pip install -e .

# B) Ejecutar con el comando
organize-dicom --input . --output organized_by_test --config config.yaml

# C) O ejecutar el script directamente
python script/organize-dicom.py --input . --output organized_by_test --config config.yaml
```

Notas para Windows:
- Mantén `--link-mode copy` (por defecto) salvo que necesites `hardlink` (mismo volumen NTFS) o `symlink` (requiere modo Desarrollador o consola con privilegios de admin).
- Si ves errores por rutas largas, habilita “long paths” en Windows o usa rutas de salida más cortas.
- El sistema de archivos es insensible a mayúsculas/minúsculas; usa `--on-collision rename` si sospechas colisiones.

## Comandos comunes
```bash
# Solo exportar metadatos (sin copiar imágenes)
organize-dicom --input . --output out --no-organize --export-metadata --qa

# Exportar todos los tags (CSV ancho) sin QA
organize-dicom --input . --output out_all --all-tags --no-organize --no-qa
```

## ¿Dónde deben estar los datos y la herramienta?
- No es necesario que el repositorio esté en la misma carpeta que las imágenes.
- Hay dos formas de uso:
	- Instalado como comando (`pip install -e .`): puedes ejecutar `organize-dicom` desde cualquier carpeta y apuntar `--input` al directorio donde están los DICOM.
	- Ejecutando el script directamente (sin instalar): ejecuta `python script/organize-dicom.py` desde dentro del repositorio, pero el `--input` puede ser cualquier ruta (no hace falta mover el repo junto a los datos).
- El parámetro `--input` debe apuntar a la raíz que contiene `dicomdir` o a una carpeta con subcarpeta `dicom/`.
- El `--output` puede ser una ruta absoluta o relativa al directorio donde ejecutas el comando; si no existe, se creará.

Ejemplos:
```bash
# Ejecutando desde tu home contra un CD montado en /media/CD
organize-dicom --input /media/CD --output ~/out --no-organize --export-metadata --qa

# Dentro del repo, procesando una carpeta fuera del repo
python3 script/organize-dicom.py --input /ruta/a/estudios --output ./organized
```

## Opciones principales
- `--organize/--no-organize`: copiar y renombrar por prueba (por defecto: sí)
- `--export-metadata/--no-export-metadata`: CSVs globales y por paciente (por defecto: sí)
- `--qa/--no-qa`: reportes de QA (por defecto: sí)
- `--config`: YAML para normalizar nombres de protocolo (ver ejemplo en `config.example.yaml`)
- `--all-tags`: exportar todos los tags a nivel instancia (CSV más grande)
- `--workers`: hilos para lectura de metadatos (por defecto: 8)

## Organización y copiado
- Carpeta de salida por Prueba (Serie):
	`Prueba_<PatientName>__<ProtocolNorm>__Series_<SeriesNumber>_<SeriesInstanceUID>/`
- Dentro: copias secuenciales `0001.ext`, `0002.ext`, … con la extensión original. También `manifest.csv` con el mapeo.
- Opciones avanzadas:
	- `--link-mode {copy,hardlink,symlink}` (default: `copy`)
	- `--on-collision {skip,overwrite,rename}` (default: `skip`)
	- `--pad-width N` (padding fijo; auto si 0)
	- `--copy-workers N` (concurrencia de copias)

## Filtros
- `--modality CT` (repetible)
- `--date-range YYYYMMDD:YYYYMMDD`
- `--patient-id <ID>` (repetible)
- `--protocol-include "regex"` / `--protocol-exclude "regex"`

## Salidas
- `global_index_instances.csv`: una fila por archivo con metadatos principales (o todos los tags si `--all-tags`).
- `global_index_series.csv`: resumen por serie (conteo, rangos de InstanceNumber).
- `csv/patients/…`: CSVs por paciente (instancias y series).
- `csv/patient_protocols/…`: CSVs por paciente/protocolo.
- `qa/*.csv`: jerarquía, gaps de InstanceNumber, duplicados SOP y tags críticos (según aplique).

## Configuración de protocolos
Ejemplo en `config.example.yaml`:
```yaml
protocol_map:
	"Senos Paranasales": "CT_Senos_Paranasales"
	"Cerebro mas de 10 anios": "CT_Cerebro_>10a"

protocol_regex:
	- pattern: "^cerebro.*anios$"
		replace: "CT_Cerebro"
```
Guárdalo como `config.yaml` en la raíz o pásalo con `--config ruta`.

## Contacto/Créditos
- Email: av18012@ues.edu.sv