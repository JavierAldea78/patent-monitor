# claude-codespaces-template

Plantilla oficial para crear proyectos nuevos con un entorno de desarrollo reproducible, basado en GitHub Codespaces y Claude Code. Sin AWS, sin secretos en el repo, sin dependencias externas más allá de GitHub.

---

## Qué es

Un repositorio plantilla (`Use this template`) que provisiona en segundos un entorno Linux remoto con:

- **Node.js 20** + **Python 3.12** preinstalados
- **Claude Code** instalado automáticamente al crear el Codespace
- **GitHub CLI** disponible
- Extensiones VS Code configuradas
- Estructura de proyecto lista (`src/`, `tests/`, `docs/`)
- GitHub Actions para validar la plantilla en cada push

## Para qué sirve

Cualquier proyecto nuevo parte de aquí. Se abre un Codespace, se conecta VS Code local, y Claude Code está disponible desde el primer segundo para planear, implementar y revisar código — todo dentro del Codespace, con GitHub como única fuente de verdad.

---

## Arquitectura del flujo

```
VS Code (local)
    │
    │  Remote SSH / Codespaces extension
    ▼
GitHub Codespaces  ←─────────────────────────────┐
  Linux remoto                                    │
  /workspaces/<repo>                              │
    │                                             │
    │  Claude Code CLI                            │  git push
    ▼                                             │
  Claude (Anthropic API) ─── edita archivos ─────┘
                                    │
                                    ▼
                              GitHub (origin)
```

**No interviene AWS, EC2, SSM, NAT Gateway ni ningún servicio cloud propio.**

---

## Estructura del repo

```
.
├── .devcontainer/
│   ├── devcontainer.json      # Imagen, features, extensiones VS Code
│   └── post-create.sh         # Instala Claude Code y configura PATH
├── .github/
│   └── workflows/
│       └── validate.yml       # CI: valida JSON, shell, archivos requeridos, secretos
├── docs/
│   ├── devex-codespaces-claude.md
│   ├── creating-new-projects.md
│   ├── troubleshooting-claude-codespaces.md
│   └── prompts/
│       └── new-project-with-claude.md
├── src/                       # Código fuente del proyecto
├── tests/                     # Tests del proyecto
├── hello.py                   # Verificación rápida del entorno
├── .gitignore
├── LICENSE
├── SECURITY.md
└── README.md
```

---

## Cómo crear un repo nuevo desde esta plantilla

1. Abre [github.com/JavierAldea78/claude-codespaces-template](https://github.com/JavierAldea78/claude-codespaces-template)
2. Pulsa **Use this template → Create a new repository**
3. Elige nombre, visibilidad y propietario
4. Pulsa **Create repository**

El repo nuevo hereda toda la configuración. No es un fork — tiene historial limpio.

---

## Cómo abrir un Codespace

Desde el repo nuevo en GitHub:

1. Pulsa **Code → Codespaces → Create codespace on main**
2. GitHub provisiona la máquina Linux (~1-2 min)
3. `post-create.sh` se ejecuta automáticamente: instala Claude Code
4. El entorno queda listo

Para ver los Codespaces activos: [github.com/codespaces](https://github.com/codespaces)

---

## Cómo conectar VS Code local

**Opción A — extensión GitHub Codespaces (recomendada):**

1. Instala la extensión [GitHub Codespaces](https://marketplace.visualstudio.com/items?itemName=GitHub.codespaces) en VS Code local
2. `Ctrl+Shift+P` → `Codespaces: Connect to Codespace`
3. Selecciona el Codespace activo

**Opción B — desde el navegador:**

1. Abre el Codespace en browser
2. Pulsa el icono de VS Code en la esquina inferior izquierda → `Open in VS Code Desktop`

Una vez conectado, el terminal integrado de VS Code corre **dentro** del Codespace.

---

## Cómo verificar el entorno

Abre el terminal del Codespace y ejecuta:

```bash
python3 hello.py
```

Salida esperada:

```
Hello from Claude Code Codespaces template
Python : 3.12.x
Node   : v20.x.x
npm    : 10.x.x
Git    : git version 2.x.x
Claude : x.x.x (Claude Code)
```

Si `claude` no aparece o da `not found`:

```bash
bash .devcontainer/post-create.sh
source ~/.bashrc
```

---

## Cómo ejecutar Claude Code

```bash
claude
```

La primera vez pedirá login. Sigue el flujo OAuth en el navegador.

Para verificar la versión instalada:

```bash
claude --version
```

### Si el login muestra una URL de localhost

El Codespace no tiene acceso directo a `localhost` desde el navegador local. Solución:

1. En VS Code: **View → Ports**
2. Busca el puerto que Claude Code está escuchando (normalmente `44123` o similar)
3. Pulsa **Forward a Port** si no está ya en la lista
4. Haz clic en **Open in Browser** en la columna Local Address

Esto redirige el OAuth a través del túnel de Codespaces y completa el login correctamente.

---

## Cómo parar el Codespace

**Desde VS Code:**
`Ctrl+Shift+P` → `Codespaces: Stop Current Codespace`

**Desde GitHub:**
[github.com/codespaces](https://github.com/codespaces) → `...` → **Stop codespace**

Los Codespaces se detienen automáticamente tras 30 min de inactividad (configurable). Los archivos persisten hasta que se eliminan explícitamente.

---

## Reglas de seguridad

- **Nunca** commits de `.env`, API keys, tokens, contraseñas o certificados privados
- Usar **GitHub Codespaces Secrets** para `ANTHROPIC_API_KEY` y cualquier credencial
- El `post-create.sh` detecta si `ANTHROPIC_API_KEY` está como secret y lo indica; si no, Claude Code usa login interactivo
- El workflow de CI incluye un **secret scan** que bloquea el merge si detecta patrones de claves conocidas
- Si un secreto se expone accidentalmente: **revocarlo de inmediato** en el proveedor, luego limpiar el historial

Ver [SECURITY.md](SECURITY.md) para más detalle.

---

## No forma parte del flujo

Los siguientes servicios **no se usan, no se necesitan y no deben añadirse**:

- AWS (EC2, SSM, CloudShell, NAT Gateway, S3, IAM...)
- Servidores propios o VMs
- PAT de GitHub en código
- Secretos hardcodeados en cualquier archivo del repo

---

## Licencia

[MIT](LICENSE)
