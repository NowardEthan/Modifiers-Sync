# Changelog

Todas as alterações notáveis ao **Modifier Sync** são documentadas aqui.  
O formato segue ideias de [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [0.8.3] — 2026-05-09

### Corrigido
- **Timer principal do auto-sync deixava de correr ao abrir outro `.blend`.** O Blender remove timers registados com `bpy.app.timers.register` **sem** `persistent=True` quando carrega um novo ficheiro. O poll `_auto_sync_poll` não era voltado a registar no `load_post`, pelo que o tempo real «morria» até desligar e ligar o addon nas Preferências. Agora o timer usa **`persistent=True`** e é correctamente **`unregister`** ao desactivar o addon.

---

## [0.8.2] — 2026-05-09

### Adicionado
- Cura de msgbus no **primeiro redraw** da View3D (`draw_handler` one-shot + `tag_redraw`).
- Timer com `first_interval=0` após `load_post` / `register` para correr cura **depois** da cadeia de handlers do load.
- Reordenação segura dos handlers no `register()` (remove + append) para evitar duplicados.

### Alterado
- Callback do msgbus: fallback se o timer aninhado falhar (`0.02` → `0.0` → execução directa).
- Removida a opção `PERSISTENT` nas subscrições msgbus (só afecta remap de ID, não load; reduz variáveis entre builds).

### Corrigido
- `draw_handler_remove` alinhado à API actual (handler + `region_type`).

---

## [0.8.1] — 2026-05-09

### Adicionado
- Handler em `depsgraph_update_post` para **uma cura de msgbus** por «geração» de ficheiro (`_file_context_generation`).
- Uso de `PERSISTENT` nas subscrições msgbus (revertido na 0.8.2).

---

## [0.8.0] — 2026-05-09

### Adicionado
- Contador **`_file_context_generation`** e **`heal_if_file_context_changed()`** para repor subscrições quando o contexto de ficheiro muda.
- Chamadas de cura no **painel N**, **menu Modifier Sync** e **operadores** do addon.
- Timers de cura adicionais no arranque e após load de ficheiro.

### Corrigido
- Melhorias para **Blender 5.x** onde msgbus/timers podiam ficar inactivos até haver interacção.

---

## [0.7.x] e anteriores

- Base do addon: grupos na Scene, motor de sync (pilha, valores RNA, pareamento por nome/índice), UI, keymaps, preferências.  
- Para detalhes finos de versões antigas, consulta o histórico de commits no GitHub.
