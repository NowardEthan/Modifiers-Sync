import bpy
from bpy.types import Menu, Panel, UIList


class VIEW3D_MT_modifier_sync(Menu):
    """Submenu no menu Objeto / barra da vista 3D — bl_idname com prefixo VIEW3D_MT_."""

    bl_label = "Modifier Sync"
    bl_idname = "VIEW3D_MT_modifier_sync"

    def draw(self, context):
        from . import auto_sync

        auto_sync.heal_if_file_context_changed()
        layout = self.layout
        layout.operator("modifier_sync.duplicate_with_modifier_sync", icon="DUPLICATE")
        layout.operator("modifier_sync.link_selection_auto_sync", icon="LINKED")
        layout.separator()
        layout.operator("modifier_sync.create_group", icon="ADD")
        layout.operator("modifier_sync.add_followers_from_selection", icon="RESTRICT_SELECT_OFF")
        layout.operator("modifier_sync.push_sync", icon="FILE_REFRESH")
        layout.operator("modifier_sync.refresh_autosync", icon="FILE_CACHE")
        layout.operator("modifier_sync.cleanup_scene", icon="GHOST_DISABLED")


def _menu_modifier_sync(layout) -> None:
    """layout.menu com fallback se a API não aceitar icon=."""
    try:
        layout.menu("VIEW3D_MT_modifier_sync", text="Modifier Sync", icon="MODIFIER")
    except TypeError:
        layout.menu("VIEW3D_MT_modifier_sync", text="Modifier Sync")


def _draw_modifier_sync_in_object_menu(self, context):
    layout = self.layout
    layout.separator()
    _menu_modifier_sync(layout)


def _draw_modifier_sync_in_object_modifiers(self, context):
    layout = self.layout
    layout.separator()
    _menu_modifier_sync(layout)


def _draw_modifier_sync_in_editor_menus(self, context):
    if context.mode != "OBJECT":
        return
    _menu_modifier_sync(self.layout)


class MODIFIER_SYNC_UL_groups(UIList):
    bl_idname = "MODIFIER_SYNC_UL_groups"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            if item:
                row.label(text=item.name, icon="LINKED")
                if item.leader:
                    row.label(text=item.leader.name, icon="OBJECT_DATA")
                else:
                    row.label(text="(sem líder)", icon="ERROR")
            else:
                row.label(text="", icon="BLANK1")


class MODIFIER_SYNC_UL_followers(UIList):
    bl_idname = "MODIFIER_SYNC_UL_followers"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            if item and item.object:
                row.label(text=item.object.name, icon="DUPLICATE")
            else:
                row.label(text="(vazio)", icon="ERROR")


class MODIFIER_SYNC_PT_panel(Panel):
    bl_label = "Modifier Sync"
    bl_idname = "MODIFIER_SYNC_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Modifier Sync"

    def draw(self, context):
        from . import ADDON_VERSION_STR, auto_sync

        auto_sync.heal_if_file_context_changed()
        layout = self.layout
        scene = context.scene
        groups = scene.modifier_sync_groups
        idx = scene.modifier_sync_active_group

        if "modifier_sync" in context.preferences.addons:
            prefs = context.preferences.addons["modifier_sync"].preferences
            if (prefs.last_acknowledged_version or "") != ADDON_VERSION_STR:
                tip = layout.box()
                tip.alert = True
                tip.label(text="Addon actualizado — passos obrigatórios:", icon="ERROR")
                tip.label(text="Preferências → Add-ons → Modifier Sync: desliga e volta a ligar.")
                tip.label(text="Recomendado: fecha o Blender e abre de novo.")
                tip.operator(
                    "modifier_sync.acknowledge_version",
                    text="Já fiz (esconder aviso)",
                    icon="CHECKMARK",
                )
                layout.separator()

        quick = layout.column(align=True)
        quick.operator(
            "modifier_sync.duplicate_with_modifier_sync",
            text="Duplicar com sync",
            icon="DUPLICATE",
        )
        quick.operator(
            "modifier_sync.link_selection_auto_sync",
            text="Ligar seleção",
            icon="LINKED",
        )

        layout.separator()
        layout.label(text="Grupos", icon="MODIFIER")

        row = layout.row()
        row.template_list(
            MODIFIER_SYNC_UL_groups.bl_idname,
            "groups",
            scene,
            "modifier_sync_groups",
            scene,
            "modifier_sync_active_group",
            rows=4,
        )
        col = row.column(align=True)
        col.operator("modifier_sync.create_group", text="", icon="ADD")
        op = col.operator("modifier_sync.remove_group", text="", icon="REMOVE")
        op.index = -1

        layout.separator()
        if idx >= 0 and idx < len(groups):
            g = groups[idx]
            box = layout.box()
            box.label(text="Grupo ativo", icon="SETTINGS")
            row = box.row()
            row.prop(g, "auto_sync", text="")
            sub = row.column()
            sub.label(text="Tempo real (timer + grafo)")
            sub.label(text="Ctrl+Shift+S força sync se precisares", icon="INFO")
            box.separator()
            box.prop(g, "name", text="Nome")
            box.prop(g, "leader", text="Líder")
            box.prop(g, "sync_stack", text="Mesma pilha (novos mods em todos os seguidores)")
            box.prop(g, "use_name_mapping")

            box.label(text="Seguidores:")
            frow = box.row()
            frow.template_list(
                MODIFIER_SYNC_UL_followers.bl_idname,
                "followers",
                g,
                "followers",
                g,
                "followers_index",
                rows=3,
            )
            fcol = frow.column(align=True)
            opf = fcol.operator("modifier_sync.remove_follower", text="", icon="REMOVE")
            opf.group_index = idx
            opf.follower_index = g.followers_index
            box.operator(
                "modifier_sync.add_followers_from_selection",
                text="Adicionar seguidores da seleção",
                icon="RESTRICT_SELECT_OFF",
            )
        else:
            layout.label(text="Cria um grupo ou duplica com sync.")

        layout.separator()
        layout.operator("modifier_sync.push_sync", icon="FILE_REFRESH")
        layout.operator("modifier_sync.refresh_autosync", icon="FILE_CACHE")
        layout.operator("modifier_sync.cleanup_scene", icon="GHOST_DISABLED")

        if "modifier_sync" in context.preferences.addons:
            prefs = context.preferences.addons["modifier_sync"].preferences
            layout.separator()
            layout.label(text="Preferências")
            layout.prop(prefs, "skip_object_pointers")
            layout.prop(prefs, "enable_duplicate_sync_shortcut")


classes = (
    VIEW3D_MT_modifier_sync,
    MODIFIER_SYNC_UL_groups,
    MODIFIER_SYNC_UL_followers,
    MODIFIER_SYNC_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    # prepend: aparece no topo do menu Objeto (append ficava no fim, por vezes fora do ecrã)
    bpy.types.VIEW3D_MT_object.prepend(_draw_modifier_sync_in_object_menu)
    bpy.types.VIEW3D_MT_object_modifiers.append(_draw_modifier_sync_in_object_modifiers)
    if hasattr(bpy.types, "VIEW3D_MT_editor_menus"):
        bpy.types.VIEW3D_MT_editor_menus.append(_draw_modifier_sync_in_editor_menus)


def unregister():
    if hasattr(bpy.types, "VIEW3D_MT_editor_menus"):
        try:
            bpy.types.VIEW3D_MT_editor_menus.remove(_draw_modifier_sync_in_editor_menus)
        except ValueError:
            pass
    try:
        bpy.types.VIEW3D_MT_object_modifiers.remove(_draw_modifier_sync_in_object_modifiers)
    except ValueError:
        pass
    try:
        bpy.types.VIEW3D_MT_object.remove(_draw_modifier_sync_in_object_menu)
    except ValueError:
        pass
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
