# Modifier Sync (Líder / Seguidores)

Addon para **Blender** (3.6+, testado no **5.1**) que sincroniza **modificadores** de um objeto **líder** para vários **seguidores**, com fluxo não destrutivo.

**Repositório:** [github.com/NowardEthan/Modifiers-Sync](https://github.com/NowardEthan/Modifiers-Sync)  
**Versão actual:** **0.8.5**  
**Autor:** Ethan ([@NowardEthan](https://github.com/NowardEthan))

---

## Instalação

### A partir do ZIP (recomendado)

1. Clica em **Code → Download ZIP** neste repositório (ou comprime tu a pasta `modifier_sync` com todos os `.py` **e** o `blender_manifest.toml` dentro).
2. No Blender: **Edit → Preferences → Add-ons → Install…** (ou **Extensions** no 4.2+) e escolhe o ZIP.
3. Activa **Modifier Sync (Líder/Seguidores)**.

**Blender Extensions** ([extensions.blender.org](https://extensions.blender.org/)): o ZIP tem de incluir **`blender_manifest.toml`** na raiz do addon (junto do `__init__.py`). Para validar/empacotar com o Blender: na pasta `modifier_sync`, corre `blender --command extension validate` e `blender --command extension build`.

### A partir do Git

```bash
git clone https://github.com/NowardEthan/Modifiers-Sync.git
```

Depois comprime a pasta `modifier_sync` (dentro do clone) num ZIP e instala como acima, ou aponta o Blender para a pasta em **Preferences → Add-ons → Install…** (se o teu fluxo usar pasta em vez de ZIP).

### Actualização do addon

Em cada nova versão o addon pode mostrar um aviso nas **Preferências** até confirmares. Para código novo carregar bem:

1. **Desactiva** o Modifier Sync nas Preferências → Add-ons.  
2. **Volta a activar** (ou reinicia o Blender para garantia total).  
3. Opcional: usa **«Instalar ZIP de actualização»** nas preferências do próprio addon.

---

## Onde está a interface

- **Vista 3D → painel lateral (N) → separador «Modifier Sync»**
- Menus **Object** e **Object Modifiers** (entrada **Modifier Sync**)

---

## Utilização rápida

1. Modo **Object**; escolhe o **líder** e os **seguidores**.
2. **Criar grupo** ou **Duplicar com sync** (atalhos abaixo).
3. Com **Sincronizar em tempo real** ligado (por defeito), os seguidores acompanham alterações ao líder (timer + grafo + msgbus opcional). **Sincronizar agora** força um push imediato.

**Preferências do addon:** intervalo do timer, reagir ao grafo (líder), msgbus na pilha e nos valores — ajusta entre fluidez e CPU.

---

## Atalhos (Vista 3D)

| Acção | Atalho padrão |
|--------|----------------|
| Duplicar com sync | **Ctrl+Shift+D** ou **Alt+Shift+D** |
| Sincronizar agora (grupo activo) | **Ctrl+Shift+S** ou **Alt+Shift+S** |

Alterações em **Edit → Preferences → Keymap** (mapa **3D View** do addon).

---

## Opções principais

| Opção | Efeito |
|--------|--------|
| **Mesma pilha que o líder** | Alinha a pilha de modificadores dos seguidores à do líder. |
| **Parear por nome** | Emparelha por nome; se falhar, usa índice. |
| **Não copiar referências a Object** | Evita copiar ponteiros (ex. Boolean com outro mesh); pode exigir reatribuição manual. |

---

## Limitações conhecidas

- Tipos de modificador exóticos ou limitações do RNA podem exigir **Sincronizar agora** pontualmente.
- Referências a **outros objetos** podem precisar de ajuste manual com a opção de não copiar ponteiros activa.

---

## Estrutura do repositório

```
modifier_sync/
  blender_manifest.toml  # Extensions (extensions.blender.org)
  __init__.py      # bl_info, register / unregister
  properties.py    # dados na Scene, preferências do addon
  operators.py     # operadores (grupo, push, duplicar, etc.)
  sync_engine.py   # cópia RNA, pilha, pareamento
  auto_sync.py     # timer (persistent), depsgraph, msgbus, load_post
  ui.py            # painel N, menus
  keymap.py        # atalhos
  README.md        # resumo (duplicado; este ficheiro é a documentação principal)
```

---

## Histórico de versões

Ver **[CHANGELOG.md](CHANGELOG.md)**.

---

## Licença

Este projeto está licenciado sob a **GNU General Public License v3.0** — ver o ficheiro **[LICENSE](LICENSE)**. Esta escolha alinha-se ao licenciamento do **Blender** (GPL) e é habitual em addons da comunidade.
