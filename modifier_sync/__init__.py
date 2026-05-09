# Modifier Sync — líder/seguidores para pilhas de modificadores (fluxo não destrutivo).
#
# Autor: Ethan
# Entrega / uso académico: sincronização líder → seguidores; atalhos e preferências no painel do addon.
#
# Testes manuais sugeridos: dois MESH com Subdiv+Bevel; criar grupo; alterar níveis no líder;
# «Sincronizar agora» ou auto-sync; verificar seguidores. Boolean com objeto alvo: ponteiros
# Object não copiados por defeito (preferência do addon).

# bl_info em primeiro lugar (validador do Blender); versão em literal.
bl_info = {
    "name": "Modifier Sync (Líder/Seguidores)",
    "author": "Ethan",
    "version": (0, 8, 4),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar (N) > Modifier Sync",
    "description": (
        "Sincroniza modificadores de um objeto líder para vários seguidores; "
        "tempo real por defeito (timer + depsgraph), mesma pilha e pareamento por nome."
    ),
    "category": "Object",
}

ADDON_VERSION = bl_info["version"]
ADDON_VERSION_STR = ".".join(str(x) for x in ADDON_VERSION)

import bpy

from . import properties
from . import operators
from . import ui
from . import auto_sync
from . import keymap


def _purge_package_from_sys_modules() -> None:
    """Após actualizar ficheiros no disco, o Python pode manter módulos antigos em memória.
    Ao desactivar o addon, removemos o pacote de ``sys.modules`` para o próximo ``import``
    carregar o código novo — evita obrigar a reiniciar o Blender."""
    import sys

    root = __package__ or "modifier_sync"
    prefix = root + "."
    for name in list(sys.modules.keys()):
        if name == root or name.startswith(prefix):
            try:
                del sys.modules[name]
            except KeyError:
                pass


def register():
    properties.register()
    operators.register()
    ui.register()
    auto_sync.register()
    keymap.register_keymap()


def unregister():
    keymap.unregister_keymap()
    auto_sync.unregister()
    ui.unregister()
    operators.unregister()
    properties.unregister()
    _purge_package_from_sys_modules()


if __name__ == "__main__":
    register()
