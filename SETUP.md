# Patent Monitor — Guía de instalación paso a paso

> Sigue este documento en orden. No te saltes ningún paso.
> Tiempo estimado: 30-45 minutos la primera vez.

---

## Índice

1. [Requisitos previos](#1-requisitos-previos)
2. [Crear el repositorio en GitHub](#2-crear-el-repositorio-en-github)
3. [Subir el código](#3-subir-el-código)
4. [Obtener la API key de The Lens](#4-obtener-la-api-key-de-the-lens)
5. [Configurar Auth0 (login)](#5-configurar-auth0-login)
6. [Poner la config de Auth0 en el código](#6-poner-la-config-de-auth0-en-el-código)
7. [Añadir todos los secrets a GitHub](#7-añadir-todos-los-secrets-a-github)
8. [Activar GitHub Pages](#8-activar-github-pages)
9. [Primer lanzamiento manual](#9-primer-lanzamiento-manual)
10. [Verificar que todo funciona](#10-verificar-que-todo-funciona)
11. [Newsletter de email (opcional)](#11-newsletter-de-email-opcional)
12. [Errores frecuentes](#12-errores-frecuentes)

---

## 1. Requisitos previos

Antes de empezar, asegúrate de tener:

- [ ] Cuenta en **GitHub** (github.com)
- [ ] Cuenta en **Auth0** (auth0.com) — la misma que ya usas en paper-monitor vale
- [ ] Acceso al Codespace / terminal donde está `/workspaces/patent-monitor`

---

## 2. Crear el repositorio en GitHub

1. Ve a **github.com** → botón verde **"New"** (arriba a la izquierda).

2. Rellena el formulario:
   - **Repository name**: `patent-monitor`
   - **Visibility**: Private ← importante, la app tiene login Auth0 pero mejor privado
   - **NO** marques "Add a README file" ni nada de las opciones de abajo
   - Clic en **"Create repository"**

3. GitHub te mostrará una pantalla con instrucciones. **No hagas nada todavía**, la siguiente sección lo hace por ti.

---

## 3. Subir el código

En el terminal del Codespace, ejecuta estos comandos exactamente en este orden:

```bash
cd /workspaces/patent-monitor
```

```bash
git remote add origin https://github.com/TU_USUARIO/patent-monitor.git
```

> ⚠️ Cambia `TU_USUARIO` por tu nombre de usuario de GitHub (p.ej. `JavierAldea78`)

```bash
git push -u origin main
```

Te pedirá usuario y contraseña. Para la contraseña, **no uses tu contraseña de GitHub** — usa un **Personal Access Token**:

- Ve a github.com → tu avatar (arriba derecha) → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
- Clic en **"Generate new token (classic)"**
- Escribe un nombre (ej: `patent-monitor-push`)
- Marca el permiso **`repo`** (el primero de la lista)
- Clic **"Generate token"** → copia el token (empieza por `ghp_...`)
- Úsalo como contraseña en el terminal

Cuando termine, verifica que en github.com/TU_USUARIO/patent-monitor aparecen los archivos.

---

## 4. Obtener credenciales de EPO Open Patent Services

EPO OPS es la API oficial de la Oficina Europea de Patentes. Cubre EP, WO, GB, FR, DE y más de 50 oficinas nacionales. Es **gratuita** con registro — hasta 25.000 peticiones/semana.

1. Ve a **developers.epo.org** → clic en **"Sign Up"** y crea una cuenta gratuita.

2. Una vez dentro, clic en **"My Apps"** → **"Create new App"**.
   - Nombre: `patent-monitor`
   - Descripción: algo como "Internal patent vigilance tool"
   - Deja el resto por defecto

3. En tu nueva app verás:
   - **Consumer Key** (también llamado `client_id`)
   - **Consumer Secret** (también llamado `client_secret`)

4. Copia ambos valores — los necesitas en el paso 7.

> 💡 El Consumer Key tiene este aspecto: `aBcD1234eFgH5678`
> El Consumer Secret es más largo: `xYz9876...`

---

## 5. Configurar Auth0 (login)

### Opción A: Reutilizar la misma app Auth0 de paper-monitor (recomendado)

Si ya tienes Auth0 configurado para paper-monitor:

1. Ve a **manage.auth0.com** → tu tenant → **Applications** → selecciona la app que usas para paper-monitor.

2. En la pestaña **"Settings"**, busca estos campos y añade las URLs de patent-monitor:

   - **Allowed Callback URLs**: añade `, https://TU_USUARIO.github.io/patent-monitor`
   - **Allowed Logout URLs**: añade `, https://TU_USUARIO.github.io/patent-monitor`
   - **Allowed Web Origins**: añade `, https://TU_USUARIO.github.io`

   > ⚠️ Separa con coma las URLs existentes. No borres las de paper-monitor.

3. Clic en **"Save Changes"**.

4. Apunta el **Domain** y el **Client ID** de esta pantalla — los necesitas en el paso 6.

### Opción B: Crear una nueva app Auth0 para patent-monitor

1. En Auth0: **Applications** → **Create Application**.
2. Nombre: `Patent Monitor`, tipo: **Single Page Application**.
3. En Settings, rellena:
   - **Allowed Callback URLs**: `https://TU_USUARIO.github.io/patent-monitor`
   - **Allowed Logout URLs**: `https://TU_USUARIO.github.io/patent-monitor`
   - **Allowed Web Origins**: `https://TU_USUARIO.github.io`
4. **Save Changes**.
5. Apunta el **Domain** y **Client ID**.

---

## 6. Poner la config de Auth0 en el código

Abre el archivo `/workspaces/patent-monitor/index.html` y busca esta sección (está cerca del principio del `<script>`):

```javascript
const AUTH0_CONFIG = {
  domain:   "__AUTH0_DOMAIN__",
  clientId: "__AUTH0_CLIENT_ID__",
```

Reemplaza los valores:

- `__AUTH0_DOMAIN__` → el Domain de tu app Auth0, ej: `dev-abc123.us.auth0.com`
- `__AUTH0_CLIENT_ID__` → el Client ID, ej: `aBcDeFgH1234567890`

Resultado final (ejemplo):

```javascript
const AUTH0_CONFIG = {
  domain:   "dev-abc123.us.auth0.com",
  clientId: "aBcDeFgH1234567890",
```

Guarda el archivo y haz commit + push:

```bash
cd /workspaces/patent-monitor
git add index.html
git commit -m "config: add Auth0 credentials"
git push
```

---

## 7. Añadir todos los secrets a GitHub

Los secrets son variables privadas que el workflow usa sin exponerlas en el código.

Ve a: **github.com/TU_USUARIO/patent-monitor** → **Settings** → **Secrets and variables** → **Actions** → botón **"New repository secret"**.

Añade los siguientes (uno por uno):

### Obligatorio

| Name | Value |
|------|-------|
| `EPO_OPS_KEY` | El Consumer Key que copiaste del paso 4 |
| `EPO_OPS_SECRET` | El Consumer Secret que copiaste del paso 4 |

### Recomendado (cobertura global ampliada — Lens.org)

| Name | Value |
|------|-------|
| `LENS_TOKEN` | Token de acceso a la API de Lens.org (ver nota abajo) |

> **Cómo obtener LENS_TOKEN:**
> 1. Regístrate gratis en [lens.org](https://www.lens.org)
> 2. Ve a **Mi cuenta → Suscripciones** → sección **"Patent"**
> 3. Solicita acceso a la API (aprobación automática en el plan gratuito)
> 4. Copia el token de la pestaña **"API Access Token"**
>
> Lens.org amplía la cobertura con patentes US, EP, WO, CN, JP, KR y muchas más jurisdicciones, complementando a EPO y PatentsView.

### Opcionales (para newsletter de email)

| Name | Value |
|------|-------|
| `GMAIL_USER` | Tu cuenta Gmail, ej: `vigilancia@gmail.com` |
| `GMAIL_APP_PASSWORD` | Contraseña de aplicación de Gmail (ver nota abajo) |
| `NEWSLETTER_TO` | Destinatarios separados por coma, ej: `jaldea@mahou-sanmiguel.com` |

> **Cómo obtener GMAIL_APP_PASSWORD:**
> 1. En tu cuenta Gmail → Gestionar cuenta → Seguridad
> 2. Activa la **verificación en dos pasos** si no la tienes
> 3. Busca **"Contraseñas de aplicaciones"**
> 4. Crea una nueva con nombre `patent-monitor`
> 5. Copia la contraseña de 16 caracteres que genera

---

## 8. Activar GitHub Pages

1. En tu repo: **Settings** → sección **"Pages"** (menú izquierdo).

2. En **"Source"**, selecciona: **GitHub Actions**.

3. No hace falta tocar nada más. Al hacer el primer deploy (paso 9), GitHub Pages se activa solo.

---

## 9. Primer lanzamiento manual

El workflow se ejecuta automáticamente cada lunes a las 7:00 UTC, pero para probarlo ahora:

1. Ve a **github.com/TU_USUARIO/patent-monitor** → pestaña **"Actions"**.

2. En el panel izquierdo, clic en **"Weekly Patent Monitor"**.

3. Clic en el botón **"Run workflow"** (derecha) → **"Run workflow"** (botón verde).

4. Espera. El proceso tiene 3 fases:
   - **Fetch patents** (~15-30 min dependiendo de cuántos tags busca)
   - **Deploy to GitHub Pages** (~2 min)
   - **Send newsletter** (~30 seg, solo si configuraste Gmail)

5. Si todo va bien, los tres pasos aparecen con ✓ verde.

> 💡 Si algún paso falla, clic en él para ver el log. El error más frecuente es un secret mal escrito.

---

## 10. Verificar que todo funciona

Cuando el workflow haya terminado:

1. La URL de tu dashboard será:
   ```
   https://TU_USUARIO.github.io/patent-monitor
   ```

2. Abre esa URL. Deberías ver la pantalla de login de Auth0.

3. Haz login. Si ves la tabla/cards con patentes, **¡todo funciona!** 🎉

4. Si la tabla aparece vacía pero sin errores, espera al segundo run — la primera vez puede que The Lens devuelva menos resultados hasta que el índice se caliente.

> **Para ver el JSON directamente** (sin login):
> `https://TU_USUARIO.github.io/patent-monitor/patents.json`

---

## 11. Newsletter de email (opcional)

Si configuraste los secrets de Gmail, el email se envía automáticamente al terminar el fetch cada lunes.

Para probarlo manualmente:

```bash
cd /workspaces/patent-monitor
export GMAIL_USER="vigilancia@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export NEWSLETTER_TO="jaldea@mahou-sanmiguel.com"
# Necesitas tener patents.json en local (descárgalo del repo)
python scripts/send_newsletter.py
```

---

## 12. Errores frecuentes

### ❌ "EPO: Invalid credentials"
- Ve al paso 4 y verifica que copiaste bien el Consumer Key y Consumer Secret
- Asegúrate de que los secrets en GitHub se llaman exactamente `EPO_OPS_KEY` y `EPO_OPS_SECRET`
- En developers.epo.org, comprueba que la app está activa (no en estado "sandbox" sin activar)

### ❌ "Auth0: Login loop / redirect infinito"
- Las Allowed Callback URLs en Auth0 no incluyen la URL de GitHub Pages
- Comprueba que añadiste `https://TU_USUARIO.github.io/patent-monitor` (sin barra final)

### ❌ El workflow falla en "Commit updated data files"
- Suele ser un problema de permisos del repo
- Ve a: Settings → Actions → General → "Workflow permissions" → marca **"Read and write permissions"**

### ❌ GitHub Pages muestra 404
- En Settings → Pages → Source: asegúrate de que está en **"GitHub Actions"** (no en Branch)
- El deploy solo ocurre si el fetch termina con éxito

### ❌ patents.json está vacío después del fetch
- Sin `EPO_OPS_KEY`/`EPO_OPS_SECRET`, solo se busca en WIPO y PatentsView (resultados más limitados)
- Revisa el log del step "Fetch patents" — verás cuántos resultados devuelve cada fuente

### ❌ "PatentsView: rate limited"
- Normal si se lanza varias veces seguidas. El workflow lo gestiona automáticamente desactivando PatentsView para ese run y usando las otras fuentes.

### ❌ "Lens: Invalid token"
- Comprueba que el secret `LENS_TOKEN` está bien copiado (sin espacios)
- Verifica en lens.org → Mi cuenta → Suscripciones que el acceso API sigue activo
- El plan gratuito tiene cuota mensual; si se agota, Lens se desactiva para ese run y se usan las otras fuentes

---

## Resumen de URLs útiles tras la instalación

| Qué | URL |
|-----|-----|
| Dashboard | `https://TU_USUARIO.github.io/patent-monitor` |
| JSON de patentes | `https://TU_USUARIO.github.io/patent-monitor/patents.json` |
| CSV de patentes | `https://TU_USUARIO.github.io/patent-monitor/patents.csv` |
| Texto legible | `https://TU_USUARIO.github.io/patent-monitor/patents_readable.txt` |
| Workflows | `https://github.com/TU_USUARIO/patent-monitor/actions` |

---

## Calendario de ejecución

El sistema se ejecuta automáticamente:
- **Cada lunes a las 07:00 UTC** (08:00 CET invierno / 09:00 CEST verano)
- Busca en los **últimos 2 años** de patentes (vs 90 días en paper-monitor — las patentes se publican más lento)
- Solo patentes con score ≥ 40 se muestran en la web (el JSON completo está disponible igualmente)

Para lanzarlo manualmente cualquier día: Actions → Weekly Patent Monitor → Run workflow.
