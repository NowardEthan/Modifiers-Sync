import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)


def _group_leader_update(self, context):
    from . import auto_sync
    from . import sync_engine

    scene = context.scene
    if scene is None:
        return
    if self.leader is not None:
        try:
            sync_engine.sync_group(self, scene)
        except Exception:
            pass
    auto_sync.refresh_subscriptions(scene)


def _group_auto_sync_update(self, context):
    from . import auto_sync
    from . import sync_engine

    scene = context.scene
    if scene is None:
        return
    if self.auto_sync:
        try:
            sync_engine.sync_group(self, scene)
        except Exception:
            pass
    auto_sync.refresh_subscriptions(scene)


def _group_modifier_options_update(self, context):
    from . import auto_sync

    auto_sync.refresh_subscriptions(context.scene)


class ModifierSyncFollowerPG(bpy.types.PropertyGroup):
    object: PointerProperty(type=bpy.types.Object, name="Objeto")


class ModifierSyncGroupPG(bpy.types.PropertyGroup):
    name: StringProperty(name="Nome", default="Grupo")
    leader: PointerProperty(type=bpy.types.Object, name="Líder", update=_group_leader_update)
    followers: CollectionProperty(type=ModifierSyncFollowerPG, name="Seguidores")
    followers_index: IntProperty(name="Índice seguidor", default=0, min=0)

    sync_stack: BoolProperty(
        name="Mesma pilha que o líder",
        description=(
            "Quando ligado: ao adicionares, removeres ou reordenares modificadores no líder, "
            "os seguidores passam a ter a mesma pilha (recriada como no líder) ao sincronizar. "
            "Desliga só se quiseres copiar só valores e gerires a pilha à mão em cada objeto."
        ),
        default=True,
        update=_group_modifier_options_update,
    )
    use_name_mapping: BoolProperty(
        name="Parear por nome",
        description="Emparelhar modificadores pelo nome; se falhar, usa o índice",
        default=False,
        update=_group_modifier_options_update,
    )
    auto_sync: BoolProperty(
        name="Sincronizar em tempo real",
        description=(
            "Ligado por defeito: ao mudares modificadores no líder, os seguidores actualizam-se "
            "(timer + grafo de dependências; msgbus opcional na pilha). Ao activar, faz um push imediato. "
            "Desliga se notares lentidão em cenas muito grandes."
        ),
        default=True,
        update=_group_auto_sync_update,
    )


class ModifierSyncAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = "modifier_sync"

    last_acknowledged_version: StringProperty(
        name="Última versão confirmada",
        description="Usado para mostrar o aviso de reinício após cada actualização",
        default="",
        options={"HIDDEN"},
    )
    skip_object_pointers: BoolProperty(
        name="Não copiar referências a Object",
        description="Evita copiar ponteiros (ex.: objeto do Boolean)",
        default=True,
    )
    enable_duplicate_sync_shortcut: BoolProperty(
        name="Atalhos duplicar com sync (Ctrl+Shift+D, Alt+Shift+D)",
        description="Vista 3D. Podes mudar teclas em Edit > Preferences > Keymap > Modifier Sync.",
        default=True,
    )
    enable_push_sync_shortcut: BoolProperty(
        name="Atalho «Sincronizar agora» (Ctrl+Shift+S, Alt+Shift+S)",
        description="Sincroniza o grupo ativo no painel N. Vista 3D, modo Objeto recomendado.",
        default=True,
    )
    autosync_use_msgbus: BoolProperty(
        name="Auto-sync: msgbus na pilha de modificadores",
        description=(
            "Subscreve alterações à coleção «modifiers» do líder (add/remove/reorder). "
            "Complementa o timer; desliga se o Blender reportar erro com msgbus."
        ),
        default=True,
    )
    autosync_msgbus_modifier_props: BoolProperty(
        name="Auto-sync: msgbus nos valores dos modificadores",
        description=(
            "Subscreve cada slider/campo RNA do líder (ex. largura do Bevel) para sync imediato. "
            "Recomendado para tempo real; desliga só se notares erro ou muitas subscrições."
        ),
        default=True,
    )
    autosync_use_depsgraph: BoolProperty(
        name="Auto-sync: reagir ao grafo (líder)",
        description=(
            "Após mudanças avaliadas no líder (ex. sliders de modificadores), pede sincronização. "
            "Filtrado ao objeto líder para evitar loops com seguidores; desliga se notares anomalias."
        ),
        default=True,
    )
    autosync_poll_interval: FloatProperty(
        name="Intervalo do timer (s)",
        description=(
            "Quanto mais baixo, mais reactivo e mais CPU. Usa ~0.02–0.05 em cenas normais."
        ),
        default=0.02,
        min=0.01,
        max=0.25,
        precision=3,
    )
    autosync_periodic_heal: BoolProperty(
        name="Auto-reparo do tempo real (~75 s)",
        description=(
            "Com algum grupo em tempo real: a cada ~75 s repõe msgbus e cache. "
            "Ajuda quando o sync «morre» até desligares o addon — custo mínimo de CPU."
        ),
        default=True,
    )

    def draw(self, context):
        from . import ADDON_VERSION_STR

        layout = self.layout
        if (self.last_acknowledged_version or "") != ADDON_VERSION_STR:
            warn = layout.box()
            warn.alert = True
            warn.label(
                text=f"Modifier Sync {ADDON_VERSION_STR} — lê com atenção:",
                icon="ERROR",
            )
            warn.label(
                text=(
                    "Após cada actualização do addon: "
                    "desliga e volta a ligar o Modifier Sync nas Preferências → Add-ons."
                )
            )
            warn.label(
                text=(
                    "Para garantir 100% (tempo real, msgbus, código novo): "
                    "fecha o Blender completamente e abre outra vez."
                )
            )
            warn.label(
                text="Sem estes passos o Python pode continuar com a versão antiga em memória."
            )
            warn.operator("modifier_sync.acknowledge_version", icon="CHECKMARK")
            layout.separator()

        layout.label(
            text="Sincronização só de modificadores (líder → seguidores).",
            icon="INFO",
        )
        u = layout.box()
        u.label(text="Actualizar o addon", icon="IMPORT")
        u.operator("modifier_sync.install_update_zip", icon="FILE_FOLDER")
        u.label(text="Depois do ZIP: desliga/liga o addon; o aviso em vermelho resume o resto.")
        layout.prop(self, "skip_object_pointers")
        layout.prop(self, "enable_duplicate_sync_shortcut")
        layout.prop(self, "enable_push_sync_shortcut")
        layout.prop(self, "autosync_use_msgbus")
        layout.prop(self, "autosync_msgbus_modifier_props")
        layout.prop(self, "autosync_use_depsgraph")
        layout.prop(self, "autosync_poll_interval")
        layout.prop(self, "autosync_periodic_heal")


classes = (
    ModifierSyncFollowerPG,
    ModifierSyncGroupPG,
    ModifierSyncAddonPreferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.modifier_sync_groups = CollectionProperty(type=ModifierSyncGroupPG)
    bpy.types.Scene.modifier_sync_active_group = IntProperty(default=0, min=0)


def unregister():
    del bpy.types.Scene.modifier_sync_active_group
    del bpy.types.Scene.modifier_sync_groups
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
