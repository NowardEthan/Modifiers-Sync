import os
import zipfile

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from . import auto_sync
from . import sync_engine


def _touch_heal_context() -> None:
    """Blender 5.x: primeiro uso após arranque precisa de repor msgbus."""
    auto_sync.heal_if_file_context_changed()


def _active_group(scene: bpy.types.Scene):
    idx = scene.modifier_sync_active_group
    groups = scene.modifier_sync_groups
    if idx < 0 or idx >= len(groups):
        return None, idx
    return groups[idx], idx


def _find_group_with_leader(scene: bpy.types.Scene, leader: bpy.types.Object):
    for i, g in enumerate(scene.modifier_sync_groups):
        if g.leader == leader:
            return i, g
    return -1, None


def _ensure_follower_in_group(group, obj: bpy.types.Object) -> None:
    for f in group.followers:
        if f.object == obj:
            return
    e = group.followers.add()
    e.object = obj


def _duplicate_object_like_shift_d(obj: bpy.types.Object) -> bpy.types.Object:
    dup = obj.copy()
    if dup.data is not None:
        try:
            dup.data = dup.data.copy()
        except (RuntimeError, TypeError, AttributeError):
            pass
    return dup


def _link_dup_to_leader_collections(leader: bpy.types.Object, dup: bpy.types.Object, context) -> None:
    """Replica o comportamento do duplicar: mesmas coleções que o líder."""
    linked = False
    for coll in leader.users_collection:
        try:
            if dup.name not in coll.objects:
                coll.objects.link(dup)
                linked = True
        except Exception:
            continue
    if not linked and context.collection is not None:
        try:
            if dup.name not in context.collection.objects:
                context.collection.objects.link(dup)
        except Exception:
            pass


def _add_followers_for_leader(scene: bpy.types.Scene, leader: bpy.types.Object, follower_objs: list) -> int:
    idx, g = _find_group_with_leader(scene, leader)
    if g is None:
        g = scene.modifier_sync_groups.add()
        g.name = f"Sync {leader.name}"
        g.leader = leader
        idx = len(scene.modifier_sync_groups) - 1
    for follower in follower_objs:
        if follower is None or follower == leader:
            continue
        _ensure_follower_in_group(g, follower)
    scene.modifier_sync_active_group = idx
    return idx


def _deselect_all_view_layer(context):
    for ob in context.view_layer.objects:
        ob.select_set(False)


class MODIFIER_SYNC_OT_create_group(Operator):
    bl_idname = "modifier_sync.create_group"
    bl_label = "Criar grupo da seleção"
    bl_description = "Objeto ativo = líder; resto da seleção = seguidores"
    bl_options = {"REGISTER", "UNDO"}

    group_name: bpy.props.StringProperty(name="Nome", default="Grupo")

    def execute(self, context):
        _touch_heal_context()
        scene = context.scene
        leader = context.active_object
        if leader is None:
            self.report({"ERROR"}, "Nenhum objeto ativo (líder).")
            return {"CANCELLED"}
        selected = list(context.selected_objects)
        if leader not in selected:
            selected.append(leader)
        followers = [o for o in selected if o != leader]

        g = scene.modifier_sync_groups.add()
        g.name = self.group_name.strip() or f"Grupo {len(scene.modifier_sync_groups)}"
        g.leader = leader
        for o in followers:
            e = g.followers.add()
            e.object = o
        scene.modifier_sync_active_group = len(scene.modifier_sync_groups) - 1
        auto_sync.refresh_subscriptions(scene)
        self.report({"INFO"}, f'Grupo "{g.name}" criado: 1 líder, {len(followers)} seguidores.')
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)


class MODIFIER_SYNC_OT_remove_group(Operator):
    bl_idname = "modifier_sync.remove_group"
    bl_label = "Remover grupo"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        _touch_heal_context()
        scene = context.scene
        groups = scene.modifier_sync_groups
        idx = self.index if self.index >= 0 else scene.modifier_sync_active_group
        if idx < 0 or idx >= len(groups):
            self.report({"WARNING"}, "Índice de grupo inválido.")
            return {"CANCELLED"}
        groups.remove(idx)
        if scene.modifier_sync_active_group >= len(groups):
            scene.modifier_sync_active_group = max(0, len(groups) - 1)
        auto_sync.refresh_subscriptions(scene)
        self.report({"INFO"}, "Grupo removido.")
        return {"FINISHED"}


class MODIFIER_SYNC_OT_remove_follower(Operator):
    bl_idname = "modifier_sync.remove_follower"
    bl_label = "Remover seguidor"
    bl_options = {"REGISTER", "UNDO"}

    group_index: bpy.props.IntProperty(default=-1)
    follower_index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        _touch_heal_context()
        scene = context.scene
        gidx = self.group_index if self.group_index >= 0 else scene.modifier_sync_active_group
        groups = scene.modifier_sync_groups
        if gidx < 0 or gidx >= len(groups):
            self.report({"WARNING"}, "Grupo inválido.")
            return {"CANCELLED"}
        group = groups[gidx]
        fidx = self.follower_index
        if fidx < 0 or fidx >= len(group.followers):
            self.report({"WARNING"}, "Seguidor inválido.")
            return {"CANCELLED"}
        group.followers.remove(fidx)
        if group.followers_index >= len(group.followers):
            group.followers_index = max(0, len(group.followers) - 1)
        auto_sync.refresh_subscriptions(context.scene)
        self.report({"INFO"}, "Seguidor removido.")
        return {"FINISHED"}


class MODIFIER_SYNC_OT_add_followers_from_selection(Operator):
    bl_idname = "modifier_sync.add_followers_from_selection"
    bl_label = "Adicionar seguidores da seleção"
    bl_description = (
        "Adiciona ao grupo ativo todos os objetos selecionados (exceto o líder); "
        "sincroniza em seguida"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.mode != "OBJECT":
            return False
        scene = context.scene
        g, _ = _active_group(scene)
        return g is not None and g.leader is not None

    def execute(self, context):
        _touch_heal_context()
        scene = context.scene
        group, _ = _active_group(scene)
        if group is None or group.leader is None:
            self.report({"ERROR"}, "Escolhe um grupo válido na lista.")
            return {"CANCELLED"}
        leader = group.leader
        added = 0
        for ob in context.selected_objects:
            if ob is None or ob == leader:
                continue
            before = len(group.followers)
            _ensure_follower_in_group(group, ob)
            if len(group.followers) > before:
                added += 1
        if added == 0:
            self.report(
                {"WARNING"},
                "Nenhum seguidor novo: seleciona objetos (o líder é ignorado).",
            )
            return {"CANCELLED"}
        reps = sync_engine.sync_group(group, scene)
        for r in reps:
            self.report({"WARNING"}, r)
        auto_sync.refresh_subscriptions(scene)
        self.report({"INFO"}, f"{added} seguidor(es) adicionado(s); sincronizado.")
        return {"FINISHED"}


class MODIFIER_SYNC_OT_push_sync(Operator):
    bl_idname = "modifier_sync.push_sync"
    bl_label = "Sincronizar agora"
    bl_description = "Aplica valores (e pilha se ativado) do líder aos seguidores"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _touch_heal_context()
        scene = context.scene
        group, _ = _active_group(scene)
        if group is None:
            self.report({"ERROR"}, "Nenhum grupo selecionado na lista.")
            return {"CANCELLED"}
        if group.leader is None:
            self.report({"ERROR"}, "Líder inválido.")
            return {"CANCELLED"}
        reps = sync_engine.sync_group(group, scene)
        for r in reps:
            self.report({"WARNING"}, r)
        if not reps:
            self.report({"INFO"}, "Sincronização concluída.")
        else:
            self.report({"INFO"}, "Sincronização concluída com avisos.")
        auto_sync.refresh_subscriptions(context.scene)
        return {"FINISHED"}


class MODIFIER_SYNC_OT_duplicate_with_modifier_sync(Operator):
    bl_idname = "modifier_sync.duplicate_with_modifier_sync"
    bl_label = "Duplicar com sync"
    bl_description = "Duplica (dados independentes), adiciona ao grupo do líder e inicia mover"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and len(context.selected_objects) > 0

    def invoke(self, context, event):
        result = self.execute(context)
        if result != {"FINISHED"}:
            return result
        area = context.area
        region = context.region
        if area and area.type == "VIEW_3D" and region:
            try:
                ovr = dict(
                    window=context.window,
                    screen=context.screen,
                    area=area,
                    region=region,
                    scene=context.scene,
                    view_layer=context.view_layer,
                )
                if hasattr(context, "temp_override"):
                    with context.temp_override(**ovr):
                        return bpy.ops.transform.translate("INVOKE_DEFAULT")
                return bpy.ops.transform.translate("INVOKE_DEFAULT")
            except Exception as ex:
                self.report({"WARNING"}, f"Cópia criada; move com G. ({ex})")
                return {"FINISHED"}
        self.report({"INFO"}, "Cópia criada; usa G na vista 3D para mover.")
        return {"FINISHED"}

    def execute(self, context):
        _touch_heal_context()
        try:
            if context.mode != "OBJECT":
                self.report({"ERROR"}, "Modo Objeto necessário (Tab).")
                return {"CANCELLED"}
            leaders = list(context.selected_objects)
            if not leaders:
                self.report({"ERROR"}, "Seleciona pelo menos um objeto.")
                return {"CANCELLED"}

            scene = context.scene
            new_objs = []
            for leader in leaders:
                dup = _duplicate_object_like_shift_d(leader)
                _link_dup_to_leader_collections(leader, dup, context)
                new_objs.append(dup)

            _deselect_all_view_layer(context)
            for o in new_objs:
                o.select_set(True)
            if new_objs:
                context.view_layer.objects.active = new_objs[-1]

            for leader, follower in zip(leaders, new_objs):
                _add_followers_for_leader(scene, leader, [follower])
            auto_sync.refresh_subscriptions(scene)
            self.report({"INFO"}, "Duplicado com sync de modificadores.")
            return {"FINISHED"}
        except Exception as ex:
            self.report({"ERROR"}, f"Duplicar: {ex}")
            return {"CANCELLED"}


class MODIFIER_SYNC_OT_link_selection_auto_sync(Operator):
    bl_idname = "modifier_sync.link_selection_auto_sync"
    bl_label = "Ligar seleção"
    bl_description = "Ativo = líder; resto = cópias (útil após Shift+D normal)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.active_object is not None

    def execute(self, context):
        _touch_heal_context()
        scene = context.scene
        leader = context.active_object
        followers = [o for o in context.selected_objects if o != leader]
        if not followers:
            self.report({"ERROR"}, "Seleciona o líder por último (ativo) e as cópias.")
            return {"CANCELLED"}
        _add_followers_for_leader(scene, leader, followers)
        auto_sync.refresh_subscriptions(scene)
        self.report({"INFO"}, "Seguidores ligados ao grupo. Usa Ctrl+Shift+S para sincronizar.")
        return {"FINISHED"}


class MODIFIER_SYNC_OT_cleanup_scene(Operator):
    bl_idname = "modifier_sync.cleanup_scene"
    bl_label = "Limpar órfãos"
    bl_description = "Remove entradas vazias e grupos sem líder"

    def execute(self, context):
        _touch_heal_context()
        scene = context.scene
        n = sync_engine.cleanup_scene_groups(scene)
        auto_sync.refresh_subscriptions(scene)
        self.report({"INFO"}, f"Limpeza: {n} grupo(s) removido(s).")
        return {"FINISHED"}


def _zip_looks_like_modifier_sync(path: str) -> bool:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = [n.replace("\\", "/").strip("/") for n in zf.namelist()]
    except zipfile.BadZipFile:
        return False
    for n in names:
        if n == "modifier_sync/__init__.py" or n.endswith("/modifier_sync/__init__.py"):
            return True
    return False


class MODIFIER_SYNC_OT_install_update_zip(Operator):
    bl_idname = "modifier_sync.install_update_zip"
    bl_label = "Instalar ZIP de actualização"
    bl_description = (
        "Escolhe o .zip do Modifier Sync (pasta modifier_sync no arquivo). "
        "Substitui a instalação actual; depois desactiva e volta a activar o addon."
    )
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH", options={"SKIP_SAVE"})
    filter_glob: StringProperty(default="*.zip", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.preferences is not None

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        _touch_heal_context()
        path = bpy.path.abspath(self.filepath)
        if not path.lower().endswith(".zip"):
            self.report({"ERROR"}, "Selecciona um ficheiro .zip.")
            return {"CANCELLED"}
        if not os.path.isfile(path):
            self.report({"ERROR"}, "Ficheiro não encontrado.")
            return {"CANCELLED"}
        if not _zip_looks_like_modifier_sync(path):
            self.report(
                {"ERROR"},
                "ZIP inválido: deve conter modifier_sync/__init__.py (comprime a pasta modifier_sync).",
            )
            return {"CANCELLED"}
        try:
            bpy.ops.preferences.addon_install(filepath=path, overwrite=True)
        except Exception as ex:
            self.report({"ERROR"}, f"Instalação falhou: {ex}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            "ZIP instalado. Abre as Preferências do Modifier Sync: há um aviso vermelho com os passos "
            "(desligar/ligar o addon e, de preferência, reiniciar o Blender).",
        )
        try:
            bpy.ops.screen.userpref_show(section="ADDONS")
        except TypeError:
            try:
                bpy.ops.screen.userpref_show()
            except Exception:
                pass
        return {"FINISHED"}


class MODIFIER_SYNC_OT_acknowledge_version(Operator):
    bl_idname = "modifier_sync.acknowledge_version"
    bl_label = "Confirmar: já desliguei/liguei o addon"
    bl_description = (
        "Usa depois de desligar e voltar a ligar o Modifier Sync nas Preferências; "
        "idealmente também reinicia o Blender. Esconde o aviso desta versão."
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return "modifier_sync" in context.preferences.addons

    def execute(self, context):
        _touch_heal_context()
        from . import ADDON_VERSION_STR

        prefs = context.preferences.addons["modifier_sync"].preferences
        prefs.last_acknowledged_version = ADDON_VERSION_STR
        self.report({"INFO"}, "Versão marcada como vista. Se o tempo real falhar, reinicia o Blender.")
        for win in context.window_manager.windows:
            if win.screen:
                for area in win.screen.areas:
                    area.tag_redraw()
        return {"FINISHED"}


class MODIFIER_SYNC_OT_refresh_autosync(Operator):
    bl_idname = "modifier_sync.refresh_autosync"
    bl_label = "Refrescar tempo real"
    bl_description = (
        "Repõe msgbus e cache em todas as cenas. "
        "Se o auto-sync «morrer» após undo, aplicar mods ou mudanças grandes, usa isto em vez de reiniciar o Blender"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        _touch_heal_context()
        auto_sync.refresh_subscriptions(context.scene)
        self.report({"INFO"}, "Tempo real reposto.")
        return {"FINISHED"}


classes = (
    MODIFIER_SYNC_OT_create_group,
    MODIFIER_SYNC_OT_duplicate_with_modifier_sync,
    MODIFIER_SYNC_OT_link_selection_auto_sync,
    MODIFIER_SYNC_OT_remove_group,
    MODIFIER_SYNC_OT_remove_follower,
    MODIFIER_SYNC_OT_add_followers_from_selection,
    MODIFIER_SYNC_OT_push_sync,
    MODIFIER_SYNC_OT_cleanup_scene,
    MODIFIER_SYNC_OT_refresh_autosync,
    MODIFIER_SYNC_OT_install_update_zip,
    MODIFIER_SYNC_OT_acknowledge_version,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
