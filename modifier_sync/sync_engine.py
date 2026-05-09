"""
Motor de sincronização: apenas modificadores (valores RNA, pilha, pareamento por índice ou nome).
"""

from __future__ import annotations

import bpy

_INTERNAL_SKIP = frozenset(
    {
        "rna_type",
        "name",
        "type",
    }
)


def _prefs_skip_pointers():
    try:
        prefs = bpy.context.preferences.addons[__package__].preferences
        return bool(prefs.skip_object_pointers)
    except Exception:
        return True


def _should_skip_prop(prop, skip_object_pointers: bool) -> bool:
    if prop.identifier in _INTERNAL_SKIP:
        return True
    if prop.is_readonly:
        return True
    if prop.type == "COLLECTION":
        return True
    if prop.type == "POINTER":
        if skip_object_pointers:
            return True
        ft = getattr(prop, "fixed_type", None)
        if ft and getattr(ft, "identifier", "") == "Object":
            return skip_object_pointers
    return False


def copy_modifier_rna_values(src_mod, dst_mod, skip_object_pointers: bool | None = None) -> list[str]:
    """Copia propriedades editáveis de src_mod para dst_mod (mesmo type). Retorna avisos."""
    if skip_object_pointers is None:
        skip_object_pointers = _prefs_skip_pointers()
    warnings: list[str] = []
    try:
        props_iter = tuple(src_mod.bl_rna.properties)
    except (AttributeError, RuntimeError, TypeError):
        return warnings
    for prop in props_iter:
        ident = prop.identifier
        if _should_skip_prop(prop, skip_object_pointers):
            continue
        if ident not in dst_mod.bl_rna.properties:
            continue
        try:
            setattr(dst_mod, ident, getattr(src_mod, ident))
        except Exception as ex:
            warnings.append(f"{ident}: {ex}")
    return warnings


def _resolve_follower_modifier(leader_mod, follower, index: int, use_name_mapping: bool):
    if follower is None or leader_mod is None:
        return None
    mods = follower.modifiers
    if use_name_mapping and leader_mod.name in mods:
        cand = mods.get(leader_mod.name)
        if cand and cand.type == leader_mod.type:
            return cand
    if index < len(mods) and mods[index].type == leader_mod.type:
        return mods[index]
    return None


def sync_values_for_follower(leader, follower, use_name_mapping: bool, reports: list[str]) -> None:
    if not leader or not follower:
        return
    if len(leader.modifiers) == 0:
        _remove_all_modifiers(follower)
        _sync_follower_mesh_data_from_leader(leader, follower)
        return
    skip_ptr = _prefs_skip_pointers()
    lm = leader.modifiers
    for i, lmod in enumerate(lm):
        fmod = _resolve_follower_modifier(lmod, follower, i, use_name_mapping)
        if fmod is None:
            reports.append(
                f'"{follower.name}": sem par para modificador [{i}] '
                f'"{lmod.name}" ({lmod.type})'
            )
            continue
        w = copy_modifier_rna_values(lmod, fmod, skip_ptr)
        for x in w:
            reports.append(f'"{follower.name}" / {lmod.name}: {x}')


def _remove_all_modifiers(obj: bpy.types.Object) -> None:
    if not obj or obj.modifiers is None:
        return
    while len(obj.modifiers) > 0:
        obj.modifiers.remove(obj.modifiers[0])


def _sync_follower_mesh_data_from_leader(leader: bpy.types.Object, follower: bpy.types.Object) -> None:
    """Depois de «Aplicar» no líder, a geometria fica no ``data``; copia para o seguidor alinhado.

    Se já partilham o mesmo datablock, não faz nada. Só ``MESH`` por agora.
    """
    if leader.type != "MESH" or follower.type != "MESH":
        return
    ld = leader.data
    if ld is None:
        return
    if follower.data is ld:
        return
    try:
        follower.data = ld.copy()
    except Exception:
        pass


def rebuild_follower_stack_like_leader(leader, follower, reports: list[str]) -> None:
    """Recria a pilha do seguidor com os mesmos nomes e tipos do líder; depois copia valores."""
    if not leader or not follower:
        return
    _remove_all_modifiers(follower)
    skip_ptr = _prefs_skip_pointers()
    for lmod in leader.modifiers:
        try:
            nmod = follower.modifiers.new(lmod.name, lmod.type)
        except Exception as ex:
            reports.append(f'"{follower.name}": não foi possível criar {lmod.type} — {ex}')
            continue
        w = copy_modifier_rna_values(lmod, nmod, skip_ptr)
        for x in w:
            reports.append(f'"{follower.name}" / {nmod.name}: {x}')
    _sync_follower_mesh_data_from_leader(leader, follower)


def sync_group(
    group,
    scene: bpy.types.Scene,
    *,
    do_stack: bool | None = None,
) -> list[str]:
    """Sincroniza modificadores dos seguidores com o líder."""
    reports: list[str] = []
    leader = group.leader
    if leader is None:
        reports.append("Líder inválido ou não definido.")
        return reports

    stack = bool(group.sync_stack) if do_stack is None else bool(do_stack)
    use_names = group.use_name_mapping

    for foll_item in group.followers:
        obj = foll_item.object
        if obj is None:
            reports.append("Entrada de seguidor com objeto vazio — remova na lista.")
            continue
        if obj == leader:
            continue
        if stack:
            rebuild_follower_stack_like_leader(leader, obj, reports)
        else:
            sync_values_for_follower(leader, obj, use_names, reports)
    return reports


def _object_alive(ob: bpy.types.Object | None) -> bool:
    """False se None, objecto apagado (ReferenceError) ou já não está em bpy.data."""
    if ob is None:
        return False
    try:
        return ob in bpy.data.objects
    except ReferenceError:
        return False


def cleanup_group_pointers(group) -> int:
    """Remove seguidores com pointer None ou objecto que já não existe no ficheiro."""
    removed = 0
    i = 0
    while i < len(group.followers):
        o = group.followers[i].object
        if o is None or not _object_alive(o):
            group.followers.remove(i)
            removed += 1
        else:
            i += 1
    return removed


def cleanup_scene_groups(scene: bpy.types.Scene) -> int:
    """Limpa ponteiros órfãos; líder inválido → None; remove grupos sem líder."""
    total = 0
    gidx = 0
    groups = scene.modifier_sync_groups
    while gidx < len(groups):
        g = groups[gidx]
        if g.leader is not None and not _object_alive(g.leader):
            try:
                g.leader = None
            except Exception:
                pass
        cleanup_group_pointers(g)
        if g.leader is None:
            groups.remove(gidx)
            total += 1
            if scene.modifier_sync_active_group >= len(groups):
                scene.modifier_sync_active_group = max(0, len(groups) - 1)
        else:
            gidx += 1
    return total
