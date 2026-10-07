---
tipo: guia
area: internos
proyecto: crm
actualizado: 2026-10-07
---

# Despliegue en Azure Container Apps

El CRM corre como **un contenedor en Azure Container Apps** (plan de consumo: no usa cuota de máquinas virtuales). La base de datos SQLite vive en un **recurso compartido de Azure Files** montado en `/data`, y Claude Code se conecta al MCP por HTTPS en `/mcp` con un token.

```
Navegador / móvil ──HTTPS──▶ Container App "crm" (1 réplica como máximo)
Claude Code (PC) ──HTTPS + token──▶   ├─ /      web
                                      └─ /mcp   MCP
                                           │
                                     /data/crm.db  ← Azure Files (persistente)
```

Comandos para **PowerShell** en tu PC, desde la carpeta del proyecto. No hace falta Docker: la imagen se construye en Azure.

## Reglas que no se tocan

- **Máximo 1 réplica.** SQLite sobre un disco de red solo aguanta un proceso escribiendo. Con dos réplicas, la base de datos se puede corromper.
- **Región en la UE** (RGPD: hay teléfonos y emails de contactos reales).
- **Secretos como *secrets* de Container Apps**, nunca en el código, la imagen ni el repositorio.

## 0. Requisitos (una vez)

```powershell
winget install -e --id Microsoft.AzureCLI     # cierra y vuelve a abrir PowerShell después
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
```

## 1. Variables

Cámbialas si quieres otros nombres. El de la cuenta de almacenamiento tiene que ser único en todo Azure (solo minúsculas y números).

```powershell
$RG = "rg-crm"
$LOC = "westeurope"          # Países Bajos. Si tu suscripción no lo permite: swedencentral, germanywestcentral, francecentral…
$ENV_NAME = "crm-env"
$APP = "crm"
$ST = "crmdatos$(Get-Random -Maximum 99999)"
$SHARE = "crm-data"
$MOUNT = "crmdata"
```

Si cierras PowerShell a mitad, vuelve a definirlas (y apunta el valor de `$ST`: `echo $ST`).

## 2. Grupo de recursos y entorno de Container Apps

```powershell
az group create --name $RG --location $LOC
az containerapp env create --name $ENV_NAME --resource-group $RG --location $LOC
```

## 3. Almacenamiento para la base de datos

```powershell
az storage account create --resource-group $RG --name $ST --location $LOC `
  --kind StorageV2 --sku Standard_LRS
az storage share-rm create --resource-group $RG --storage-account $ST --name $SHARE `
  --quota 1 --enabled-protocols SMB
$ST_KEY = az storage account keys list -n $ST -g $RG --query "[0].value" -o tsv
az containerapp env storage set --name $ENV_NAME --resource-group $RG `
  --storage-name $MOUNT --storage-type AzureFile `
  --azure-file-account-name $ST --azure-file-account-key $ST_KEY `
  --azure-file-share-name $SHARE --access-mode ReadWrite
```

**Opcional: subir la base de datos de tu PC** (si ya tienes datos reales). Hazlo ahora, antes de que la app exista, y con `crm serve` parado en tu PC:

```powershell
az storage file upload --account-name $ST --account-key $ST_KEY `
  --share-name $SHARE --source data/crm.db --path crm.db
```

Si no subes nada, la app crea una base de datos vacía al arrancar (aplica las migraciones sola).

## 4. Generar los dos secretos

```powershell
$SECRET_KEY = uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
$MCP_TOKEN = uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Guarda `$MCP_TOKEN` en tu gestor de contraseñas: lo necesitas en el paso 8.

## 5. Construir y crear la app

```powershell
az containerapp up --name $APP --resource-group $RG --environment $ENV_NAME `
  --location $LOC --source . --ingress external --target-port 8000
```

Este comando crea un **Azure Container Registry** (ACR), construye la imagen allí con el `Dockerfile`, la sube y crea la app. Tarda unos minutos.

Después, los secretos, las variables que los usan y el límite de réplicas:

```powershell
az containerapp secret set -n $APP -g $RG --secrets "secret-key=$SECRET_KEY" "mcp-token=$MCP_TOKEN"
az containerapp update -n $APP -g $RG `
  --set-env-vars "SECRET_KEY=secretref:secret-key" "CRM_MCP_TOKEN=secretref:mcp-token" `
  --min-replicas 0 --max-replicas 1
```

## 6. Montar el volumen `/data`

Montar un volumen solo se puede hacer con un YAML:

```powershell
$YAML = "$env:TEMP\crm-app.yaml"     # fuera del repositorio
az containerapp show -n $APP -g $RG -o yaml > $YAML
notepad $YAML
```

Haz tres cambios en el archivo:

1. **Borra todo el bloque `secrets:`** (dentro de `configuration`). Exportado viene sin valores; si lo dejas, borraría los secretos. Sin el bloque, se mantienen.
2. En `template` → `containers` → el contenedor `crm`, añade:
   ```yaml
       volumeMounts:
       - volumeName: datos
         mountPath: /data
   ```
3. En `template`, cambia `volumes: null` por:
   ```yaml
     volumes:
     - name: datos
       storageType: AzureFile
       storageName: crmdata
       mountOptions: nobrl
   ```
   `nobrl` evita los errores "database is locked" de SQLite sobre SMB. Es seguro porque solo hay un proceso.

Aplica los cambios, borra el YAML y **comprueba que los secretos siguen ahí**:

```powershell
az containerapp update -n $APP -g $RG --yaml $YAML
Remove-Item $YAML
az containerapp secret list -n $APP -g $RG -o table
```

Deben salir `secret-key`, `mcp-token` y el de la contraseña del registro (algo como `<registro>azurecrio-<registro>`). Si falta alguno:

- `secret-key` o `mcp-token`: repite el `az containerapp secret set` del paso 5 (con las mismas variables).
- El del registro: vuelve a conectarlo:
  ```powershell
  $ACR = az acr list -g $RG --query "[0].name" -o tsv
  az containerapp registry set -n $APP -g $RG --server "$ACR.azurecr.io" `
    --username (az acr credential show -n $ACR --query username -o tsv) `
    --password (az acr credential show -n $ACR --query "passwords[0].value" -o tsv)
  ```

## 7. Crear tu usuario y entrar

```powershell
$FQDN = az containerapp show -n $APP -g $RG --query properties.configuration.ingress.fqdn -o tsv
Start-Process "https://$FQDN"      # abre la web: despierta la app si estaba escalada a cero
az containerapp exec -n $APP -g $RG --command "crm crear-usuario raul"
```

- `exec` falla si no hay ninguna réplica viva. Por eso se abre antes la web: espera a que cargue la pantalla de login.
- Si `exec` no te deja escribir la contraseña, entra con `--command sh` y ejecuta `crm crear-usuario raul` dentro.
- **Contraseña larga (16 caracteres o más, o una frase).** La web ya es pública y el login no limita los intentos: lo que te protege es la longitud de la contraseña.

## 8. Conectar Claude Code al MCP de Azure

```powershell
claude mcp add --transport http --scope user crm-azure "https://$FQDN/mcp" `
  --header "Authorization: Bearer $MCP_TOKEN"
claude mcp list
```

- `--scope user` lo guarda en tu configuración de usuario (`~/.claude.json`), no en el repositorio, y funciona desde cualquier carpeta, también desde la bóveda.
- El servidor `crm` de `.mcp.json` sigue apuntando a la base de datos de tu PC: úsalo para desarrollo y demo. **La fuente de verdad pasa a ser Azure.**
- Prueba: en Claude Code, "¿qué seguimientos tengo vencidos en crm-azure?".

## Actualizar a una versión nueva del código

⚠️ Al actualizar, Azure arranca el contenedor nuevo **antes** de parar el viejo. Durante unos segundos hay dos procesos sobre `crm.db`, y el nuevo aplica las migraciones. Para no arriesgar la base de datos:

1. No uses el CRM (ni la web ni Claude) mientras actualizas.
2. Haz antes una instantánea (ver "Copias de seguridad").

Lo mismo vale para cualquier `az containerapp update` cuando ya tienes datos.

```powershell
$ACR = az acr list -g $RG --query "[0].loginServer" -o tsv
$TAG = Get-Date -Format "yyyyMMdd-HHmm"
az acr build --registry $ACR.Split(".")[0] --image "crm:$TAG" .
az containerapp update -n $APP -g $RG --image "$ACR/crm:$TAG"
```

Las migraciones se aplican solas al arrancar (`alembic upgrade head` en el `CMD` del `Dockerfile`).

## Copias de seguridad

Si abriste otra sesión de PowerShell, recupera primero el nombre y la clave del almacenamiento:

```powershell
$ST = az storage account list -g $RG --query "[0].name" -o tsv
$ST_KEY = az storage account keys list -n $ST -g $RG --query "[0].value" -o tsv
```

Instantánea del recurso compartido (mejor cuando no estés usando el CRM):

```powershell
az storage share snapshot --name $SHARE --account-name $ST --account-key $ST_KEY
```

O descarga una copia a tu PC:

```powershell
az storage file download --account-name $ST --account-key $ST_KEY `
  --share-name $SHARE --path crm.db --dest "data/backup-$(Get-Date -Format yyyyMMdd).db"
```

## Coste aproximado

Precios orientativos; compruébalos en la calculadora de Azure:

| Recurso | Coste |
|---|---|
| Container Apps (consumo, escala a 0, un usuario) | ~0 €: cabe en la capa gratuita mensual |
| Container Registry Basic | ~5 €/mes. Es lo que más pesa. |
| Azure Files (1 GiB) | céntimos |
| Log Analytics (logs) | céntimos con este volumen |

Con `--min-replicas 0`, la primera petición tras un rato sin uso tarda unos segundos (arranque en frío). Si te molesta: `az containerapp update -n $APP -g $RG --min-replicas 1`, a cambio de unos euros más al mes.

## Si algo falla

| Síntoma | Qué mirar |
|---|---|
| Error de política o región al crear recursos | Las suscripciones de estudiante limitan las regiones. Cambia `$LOC` por otra región de la UE. |
| La app no arranca | `az containerapp logs show -n $APP -g $RG --follow`. Típico: `CRM_MCP_TOKEN` corto, o falta el volumen. |
| Te echa del login a menudo | Falta `SECRET_KEY` (paso 5). |
| Claude recibe 401 | El token de `claude mcp add` no es igual al secret `mcp-token`. |
| "database is locked" | Más de una réplica, o falta `mountOptions: nobrl` (paso 6). |

## Borrarlo todo

```powershell
az group delete --name $RG
```

Borra **también la base de datos**. Descarga antes una copia.

## Fuentes

- [Azure Files en Container Apps (tutorial)](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts-azure-files)
- [Volúmenes y `mountOptions`](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)
- [`az containerapp up`](https://learn.microsoft.com/en-us/azure/container-apps/containerapp-up)
