# organize-dicom

Script único para:
- Organizar DICOM por prueba (serie) incluyendo nombre de paciente y protocolo en la carpeta.
- Copiar y renombrar secuencialmente las imágenes para su visualización ordenada en ImageJ, preservando la extensión (tipo de archivo).
- Exportar metadatos a CSV (global, por paciente, por paciente/protocolo) y generar reportes de QA.

## Uso rápido

Dentro del directorio que contiene `dicomdir` y/o la carpeta `dicom/`:

```bash
# Organizar (copiar + renombrar) y exportar metadatos + QA
/home/debstroyer/Documentos/DATA/BULLE/.venv/bin/python organize-dicom.py \
	--input . \
	--output organized_by_test \
	--config config.yaml

# Solo exportar metadatos (sin copiar)
/home/debstroyer/Documentos/DATA/BULLE/.venv/bin/python organize-dicom.py --input . --output out --no-organize --export-metadata --qa

# Exportar todos los tags a nivel instancia (CSV ancho)
/home/debstroyer/Documentos/DATA/BULLE/.venv/bin/python organize-dicom.py --input . --output out --all-tags --no-organize

### Instalación (opcional) del comando `organize-dicom`

```bash
# Instalar en modo editable (recomendado para desarrollo)
/home/debstroyer/Documentos/DATA/BULLE/.venv/bin/python -m pip install -e .

# Ejecutar como comando del sistema (dentro del venv)
/home/debstroyer/Documentos/DATA/BULLE/.venv/bin/organize-dicom --input . --output out --no-organize --export-metadata --qa
```

## Opciones útiles

- `--link-mode {copy,hardlink,symlink}`: modo de materialización al organizar (por defecto `copy`).
- `--on-collision {skip,overwrite,rename}`: política si el destino existe (por defecto `skip`).
- `--pad-width N`: padding fijo para 0001, 0002… (auto por defecto).
- `--copy-workers N`: concurrencia para copias/enlaces.
- Filtros: `--modality CT` (repetible), `--date-range 20250101:20251231`, `--patient-id P1` (repetible), `--protocol-include "regex"`, `--protocol-exclude "regex"`.
- Orden de imágenes: usa `InstanceNumber`; si falta, intenta `ImagePositionPatient` (eje Z) y luego `AcquisitionTime`.

## Publicar en GitHub

Este repositorio incluye un `.gitignore` que excluye medios DICOM y salidas generadas. Pasos sugeridos:

```bash
# Inicializar repo y primer commit
git init
git add .
git commit -m "Initial commit: organize-dicom tool"

# Crear remoto y hacer push (reemplaza la URL por la tuya)
git remote add origin https://github.com/<usuario>/<repo>.git
git branch -M main
git push -u origin main
```

```

Notas:
- Al organizar, se COPIAN los archivos y se renombran como 0001.ext, 0002.ext… conservando la extensión original; ideal para ImageJ.
- Requiere Python 3.9+ y paquetes: pydicom, pandas, pyyaml.

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

Guárdalo como `config.yaml` en la raíz o pasa `--config ruta`.