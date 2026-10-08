---
tipo: guia
area: internos
proyecto: crm
actualizado: 2026-10-08
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

Comandos para **PowerShell** en tu PC, desde la carpeta del proyecto. No hace falta Docker: la imagen se construye en GitHub Actions y se publica en `ghcr.io`.

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
az provider register --namespace Microsoft.Storage
```

El registro tarda uno o dos minutos. Comprueba que pone `Registered` antes de seguir:

```powershell
az provider show -n Microsoft.App --query registrationState -o tsv
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
az containerapp env create --name $ENV_NAME --resource-group $RG --location $LOC `
  --environment-mode WorkloadProfiles
```

Pon `--environment-mode WorkloadProfiles` sí o sí. Si no lo pones, la CLI puede crear un entorno *express* (modo nuevo, en preview), que **no admite volúmenes de Azure Files**. El paso 3 fallaría con `ExpressEnvironmentResourceNotSupported`. Con `WorkloadProfiles` se usa el perfil de consumo: escala a cero, sin cuota de VMs y con el mismo precio.

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

## 5. Construir la imagen (GitHub) y crear la app

La imagen **se construye en GitHub Actions** y se publica en `ghcr.io`. Azure solo la descarga. Motivo: en la suscripción de estudiante no se puede construir dentro de Azure (ACR Tasks está bloqueado y crear un registro choca con la política de regiones; ver `DECISIONES.md` 39).

**5.1. Subir el repositorio a GitHub** (una vez). Crea un repositorio vacío en github.com, sin README, y luego:

```powershell
git status                                   # nada de data/, .env ni secrets.md
git remote add origin https://github.com/<tu-usuario>/<repo>.git
git push -u origin master
```

Cada push a `master` o `main` lanza `.github/workflows/imagen.yml`. El workflow pasa los tests y `ruff` y, si van bien, publica `ghcr.io/<tu-usuario>/<repo>:<commit>` y `:latest`. Sigue el progreso en la pestaña **Actions** del repositorio.

**5.2. Hacer pública la imagen** (una vez, tras el primer build). En GitHub: tu perfil → **Packages** → el paquete → **Package settings** → **Change visibility** → **Public**. La imagen solo lleva el código, que ya es público: nada de datos ni secretos.

> Si prefieres la imagen privada, crea un token de GitHub (*classic*) con permiso `read:packages` y dáselo a Azure:
> `az containerapp registry set -n $APP -g $RG --server ghcr.io --username <tu-usuario> --password <token>`

**5.3. Crear la app** con la imagen, los secretos y como máximo 1 réplica:

```powershell
$IMAGE = "ghcr.io/<tu-usuario>/<repo>"       # en minúsculas
$TAG = git rev-parse --short=7 HEAD          # el commit que construyó Actions
az containerapp create --name $APP --resource-group $RG --environment $ENV_NAME `
  --image "${IMAGE}:$TAG" `
  --target-port 8000 --ingress external --min-replicas 0 --max-replicas 1 `
  --secrets "secret-key=$SECRET_KEY" "mcp-token=$MCP_TOKEN" `
  --env-vars "SECRET_KEY=secretref:secret-key" "CRM_MCP_TOKEN=secretref:mcp-token"
```

Si la app ya existe (por ejemplo, creada con una imagen de prueba), en vez de `create`:

```powershell
az containerapp update -n $APP -g $RG --image "${IMAGE}:$TAG"
az containerapp ingress update -n $APP -g $RG --target-port 8000
```

> No uses `az containerapp up --source .` ni `az acr build`: en esta suscripción fallan (*Cloud Build* da `ResourceNotFound`, ACR Tasks da `TasksOperationsNotAllowed` y crear un registro da `RequestDisallowedByAzure`).

## 6. Montar el volumen `/data`

Montar un volumen solo se puede hacer con un YAML:

```powershell
$YAML = "$env:TEMP\crm-app.yaml"     # fuera del repositorio
[IO.File]::WriteAllLines($YAML, (az containerapp show -n $APP -g $RG -o yaml))   # UTF-8
code $YAML                           # o cualquier editor de texto
```

No uses `> $YAML`: en PowerShell 5.1 guarda el archivo en UTF-16, y `az` puede no leerlo.

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

Deben salir `secret-key` y `mcp-token`. Con la imagen privada, sale también el de `ghcr.io`. Si falta alguno:

```powershell
az containerapp secret set -n $APP -g $RG --secrets "secret-key=$SECRET_KEY" "mcp-token=$MCP_TOKEN"
```

Si faltaba el de `ghcr.io`, repite el `az containerapp registry set` del paso 5.2.

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

## 9. Dominio propio (opcional, DonDominio)

Un subdominio (`crm.tudominio.es`) con certificado HTTPS gratuito que Azure renueva solo. La dirección `*.azurecontainerapps.io` sigue funcionando.

1. Saca los dos valores para el DNS:

```powershell
$DOMAIN = "crm.tudominio.es"
az containerapp show -n $APP -g $RG --query properties.configuration.ingress.fqdn -o tsv
az containerapp show -n $APP -g $RG --query properties.customDomainVerificationId -o tsv
```

2. En DonDominio, abre el dominio, entra en su **zona DNS** y añade dos registros. En el nombre se pone solo la parte de delante; DonDominio completa el resto.

| Tipo | Nombre | Valor |
|---|---|---|
| CNAME | `crm` | el `fqdn` del primer comando |
| TXT | `asuid.crm` | el identificador del segundo comando |

   - El dominio tiene que usar los **servidores DNS de DonDominio**. Si los delegaste a otro sitio (Cloudflare, por ejemplo), los registros se crean allí, y en Cloudflare con el proxy desactivado (nube gris).
   - Si la zona tiene un registro **CAA**, añade `0 issue "digicert.com"`.
   - Comprueba que ya se ven (de minutos a una hora): `Resolve-DnsName crm.tudominio.es` y `Resolve-DnsName asuid.crm.tudominio.es -Type TXT`.

3. Abre antes la web por la dirección de Azure para que haya una réplica viva, y añade el dominio con su certificado:

```powershell
az containerapp hostname add --hostname $DOMAIN -g $RG -n $APP
az containerapp hostname bind --hostname $DOMAIN -g $RG -n $APP `
  --environment $ENV_NAME --validation-method CNAME
```

   El certificado tarda unos minutos. Si falla por tiempo, sube a `--min-replicas 1`, repite el `bind` y vuelve a `--min-replicas 0`.

4. Cambia el MCP a la dirección nueva:

```powershell
claude mcp remove crm-azure --scope user
claude mcp add --transport http --scope user crm-azure "https://$DOMAIN/mcp" `
  --header "Authorization: Bearer $MCP_TOKEN"
```

El código no cambia. Solo tendrás que volver a iniciar sesión en la web, porque la cookie es de cada dominio.

## Actualizar a una versión nueva del código

⚠️ Al actualizar, Azure arranca el contenedor nuevo **antes** de parar el viejo. Durante unos segundos hay dos procesos sobre `crm.db`, y el nuevo aplica las migraciones. Para no arriesgar la base de datos:

1. No uses el CRM (ni la web ni Claude) mientras actualizas.
2. Haz antes una instantánea (ver "Copias de seguridad").

Lo mismo vale para cualquier `az containerapp update` cuando ya tienes datos.

1. `git push`. Espera a que el workflow salga en verde en **Actions**. Si fallan los tests, no se publica nada.
2. Pasa a Azure la imagen nueva:

```powershell
$IMAGE = "ghcr.io/<tu-usuario>/<repo>"
$TAG = git rev-parse --short=7 HEAD
az containerapp update -n $APP -g $RG --image "${IMAGE}:$TAG"
```

Usa la etiqueta del commit, no `:latest`. Con la misma etiqueta, Azure no siempre crea una revisión nueva, y así además sabes qué versión está desplegada.

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
| Imagen en `ghcr.io` + GitHub Actions | 0 € (repositorio y paquete públicos) |
| Azure Files (1 GiB) | céntimos |
| Log Analytics (logs) | céntimos con este volumen |

Con `--min-replicas 0`, la primera petición tras un rato sin uso tarda unos segundos (arranque en frío). Si te molesta: `az containerapp update -n $APP -g $RG --min-replicas 1`, a cambio de unos euros más al mes.

## Si algo falla

| Síntoma | Qué mirar |
|---|---|
| Error de política o región al crear recursos | Las suscripciones de estudiante limitan las regiones. Cambia `$LOC` por otra región de la UE. |
| La app no arranca | `az containerapp logs show -n $APP -g $RG --follow`. Típico: `CRM_MCP_TOKEN` corto, o falta el volumen. |
| Azure no puede descargar la imagen (`unauthorized`, `denied`, `manifest unknown`) | El paquete de `ghcr.io` sigue privado (paso 5.2), la ruta no está en minúsculas, o la etiqueta no existe (¿terminó el workflow de ese commit?). |
| El workflow de Actions falla | Abre el paso en rojo. Si falla en "Tests y lint", es lo mismo que `uv run pytest` / `uv run ruff check .` en local. |
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
- [Dominio propio con certificado gratuito](https://learn.microsoft.com/en-us/azure/container-apps/custom-domains-managed-certificates)
