# Modifier Sync — pacote do addon

Esta pasta é o **addon** propriamente dito (instala no Blender como ZIP desta pasta ou via *Install…*).

- **Versão actual:** ver `__init__.py` → `bl_info["version"]` (em sincronia com a raiz do repositório).
- **Documentação completa, instalação e histórico:** [README.md](../README.md) e [CHANGELOG.md](../CHANGELOG.md) na raiz do repositório [Modifiers-Sync](https://github.com/NowardEthan/Modifiers-Sync).

---

## Estrutura

| Ficheiro | Função |
|----------|--------|
| `blender_manifest.toml` | Metadados para [Blender Extensions](https://extensions.blender.org/) |
| `__init__.py` | `bl_info`, `register` / `unregister` |
| `properties.py` | Grupos na Scene, preferências |
| `operators.py` | Operadores (criar grupo, push, duplicar, etc.) |
| `sync_engine.py` | Sincronização RNA / pilha / pareamento |
| `auto_sync.py` | Timer **persistent**, depsgraph, msgbus, `load_post` |
| `ui.py` | Painel N, menus |
| `keymap.py` | Atalhos |

---

## Nota para desenvolvimento

O timer principal do auto-sync **deve** usar `bpy.app.timers.register(..., persistent=True)` para sobreviver a **abrir outro .blend**; caso contrário o Blender remove o timer no load e o tempo real deixa de funcionar até reactivar o addon.
