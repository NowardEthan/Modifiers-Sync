"""
Auto-sync: timer (fingerprint) + ``depsgraph_update_post`` filtrado ao **líder**
+ msgbus opcional na coleção ``modifiers``.

- **Timer** — compara fingerprint dos valores RNA; intervalo configurável nas preferências.
- **Depsgraph** — quando o Blender avalia mudanças no **objeto líder**, agenda um poll com debounce;
  ajuda a sentir «tempo real» nos sliders sem depender só do timer. Seguidores são ignorados
  para evitar o loop sync → depsgraph no seguidor → sync outra vez.
- **msgbus** em ``path_resolve("modifiers", False)`` — pilha add/remove/reorder.
- **msgbus** por campo ``modifiers[i].prop`` — sliders / campos RNA (Bevel amount, etc.).

Desliga msgbus ou depsgraph nas preferências se algum build se comportar mal.

Com tempo real ligado, um **auto-reparo** (~75 s, opcional nas prefs) volta a chamar
``refresh_subscriptions()`` para repor msgbus quando o Blender «silencia» subscrições.

Handlers ``load_post``, ``depsgraph_update_post`` e undo/redo usam ``@persistent`` para não
serem removidos ao abrir outro .blend.

**Importante:** ``bpy.app.timers.register`` sem ``persistent=True`` **remove o timer ao carregar
outro .blend**. O poll principal ``_auto_sync_poll`` deve usar ``persistent=True``; caso contrário,
após abrir um projeto o timer morre e só voltaria com desligar/ligar o addon.

Blender 5.x: o arranque frio pode deixar msgbus inútil até haver interacção; por isso
``heal_if_file_context_changed()`` corre no painel N, no menu Modifier Sync e no início de
cada operador do addon (incremento de ``on_blend_context_changed`` em load/register).

Documentação oficial: *todas* as subscrições ``bpy.msgbus`` são removidas ao carregar outro
.blend; repostas em ``load_post`` e curas adiadas. Além disso, após load/register pede-se um
redraw da View3D e regista-se um ``draw_handler`` de uma só vez — quando o viewport desenha,
corre ``_heal_subscriptions_tick`` (alguns builds 5.x só estabilizam msgbus/timers nesse loop).
"""

from __future__ import annotations

import time

import bpy
from bpy.app.handlers import persistent

from . import sync_engine

_CACHE_H: dict[tuple[int, int], tuple] = {}
_CACHE_FP: dict[tuple[int, int], tuple] = {}
_SKIP_IDS = frozenset({"rna_type", "name", "type"})
_addon_active = False
_sync_in_progress = False

_MSG_OWNER = object()
_MSG_DEBOUNCE: dict[int, float] = {}

_DG_FLUSH_ARMED = False
_dg_scene_ref: bpy.types.Scene | None = None
_last_scene_cleanup_ts: float = 0.0
_SCENE_CLEANUP_INTERVAL = 2.5
_last_msgbus_heal_ts: float = 0.0
_MSGBUS_HEAL_INTERVAL = 75.0

# Blender 5.x: após arranque ou novo .blend, msgbus pode ficar inactivo até haver interacção real.
_file_context_generation: int = 0
_last_heal_generation: int = -1
# Última geração em que correu a cura «no primeiro depsgraph» (ver _depsgraph_msgbus_context_heal).
_msgbus_heal_for_context_gen: int = -1

# Cura no primeiro redraw da View3D (Blender 5.x: msgbus/timer às vezes só «acordam» com o loop de desenho).
_viewport_msgbus_heal_handle = None

_FP_VALUE_TYPES = frozenset(
    {
        "BOOLEAN",
        "INT",
        "FLOAT",
        "STRING",
        "ENUM",
        "FLOAT_VECTOR",
    }
)


def _prefs_use_msgbus() -> bool:
    try:
        p = bpy.context.preferences.addons["modifier_sync"].preferences
        return bool(getattr(p, "autosync_use_msgbus", True))
    except Exception:
        return True


def _prefs_use_depsgraph() -> bool:
    try:
        p = bpy.context.preferences.addons["modifier_sync"].preferences
        return bool(getattr(p, "autosync_use_depsgraph", True))
    except Exception:
        return True


def _prefs_poll_interval() -> float:
    try:
        p = bpy.context.preferences.addons["modifier_sync"].preferences
        v = float(getattr(p, "autosync_poll_interval", 0.02))
    except Exception:
        v = 0.02
    return max(0.01, min(0.25, v))


def _prefs_periodic_heal() -> bool:
    try:
        p = bpy.context.preferences.addons["modifier_sync"].preferences
        return bool(getattr(p, "autosync_periodic_heal", True))
    except Exception:
        return True


def _prefs_msgbus_modifier_props() -> bool:
    """Subscrições por propriedade (sliders); independente do msgbus só na coleção."""
    try:
        p = bpy.context.preferences.addons["modifier_sync"].preferences
        return bool(getattr(p, "autosync_msgbus_modifier_props", True))
    except Exception:
        return True


def _fp_cache_key(scene: bpy.types.Scene, group_index: int) -> tuple[int, int]:
    """Evita colidir índice 0 entre cenas diferentes (cache/msgbus ficavam incoerentes)."""
    return (scene.as_pointer(), group_index)


def _stack_hash(obj: bpy.types.Object) -> tuple:
    """Ordem + nome + tipo por modificador (reorder e novos mods detetados; só tipos não bastam)."""
    if not obj:
        return ()
    return tuple((m.name, m.type) for m in obj.modifiers)


def _normalize_for_hash(v):
    if v is None:
        return None
    try:
        import mathutils
    except ImportError:
        mathutils = None

    if isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        return round(v, 9)
    if isinstance(v, str):
        return v
    if mathutils is not None:
        if isinstance(v, mathutils.Vector):
            return tuple(round(c, 9) for c in v)
        if isinstance(v, mathutils.Euler):
            return tuple(round(c, 9) for c in v)
        if isinstance(v, mathutils.Color):
            return tuple(round(c, 9) for c in v)
        if isinstance(v, mathutils.Matrix):
            return tuple(tuple(round(c, 9) for c in row) for row in v)
    if not isinstance(v, (str, bytes)):
        try:
            ln = len(v)
            if ln > 0 and ln < 64:
                return tuple(round(float(v[i]), 9) for i in range(ln))
        except Exception:
            pass
    if isinstance(v, bpy.types.ID):
        try:
            return v.as_pointer()
        except ReferenceError:
            return None
    try:
        return v.value
    except Exception:
        pass
    try:
        return int(v)
    except Exception:
        pass
    try:
        return str(v)
    except Exception:
        return None


def _modifier_fingerprint(leader: bpy.types.Object) -> tuple:
    if not leader:
        return ()
    blocks: list[tuple] = []
    for m in leader.modifiers:
        row: list = [m.name, m.type]
        try:
            bl_rna = getattr(m, "bl_rna", None)
            if bl_rna is None:
                blocks.append((m.name, m.type, None))
                continue
            pairs: list[tuple] = []
            for prop in bl_rna.properties:
                ident = prop.identifier
                if ident in _SKIP_IDS:
                    continue
                if prop.type in ("POINTER", "COLLECTION"):
                    continue
                if prop.type not in _FP_VALUE_TYPES:
                    continue
                try:
                    val = getattr(m, ident)
                except (AttributeError, ReferenceError):
                    continue
                pairs.append((ident, _normalize_for_hash(val)))
            pairs.sort(key=lambda x: x[0])
            row.append(tuple(pairs))
            blocks.append(tuple(row))
        except Exception:
            blocks.append((m.name, m.type, "err"))
    return tuple(blocks)


def _full_fingerprint(leader: bpy.types.Object) -> tuple:
    return ("m", _stack_hash(leader), _modifier_fingerprint(leader))


def _group_index(scene: bpy.types.Scene, group) -> int | None:
    for i, gg in enumerate(scene.modifier_sync_groups):
        if gg is group:
            return i
    return None


def _msgbus_modifiers_notify(*args):
    """Alteração na coleção RNA ``modifiers`` do objeto (pilha)."""
    group = args[0] if args else None
    if group is None or not group.auto_sync or group.leader is None:
        return

    gid = id(group)
    t = time.monotonic()
    if _MSG_DEBOUNCE.get(gid, 0.0) + 0.04 > t:
        return
    _MSG_DEBOUNCE[gid] = t

    def _flush():
        try:
            scene = bpy.context.scene
            if scene is None or not group.auto_sync or group.leader is None:
                return None
            idx = _group_index(scene, group)
            if idx is not None:
                _run_sync_for_group(scene, idx, group)
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_flush, first_interval=0.02)
    except Exception:
        try:
            bpy.app.timers.register(_flush, first_interval=0.0)
        except Exception:
            _flush()


def _leader_pointers_for_scene(scene: bpy.types.Scene) -> set[int]:
    out: set[int] = set()
    for g in scene.modifier_sync_groups:
        if not g.auto_sync or g.leader is None:
            continue
        try:
            out.add(g.leader.as_pointer())
        except ReferenceError:
            pass
    return out


def _scene_from_depsgraph(depsgraph) -> bpy.types.Scene | None:
    try:
        se = depsgraph.scene_eval
        if se is not None:
            orig = getattr(se, "original", None)
            if isinstance(orig, bpy.types.Scene):
                return orig
            if isinstance(se, bpy.types.Scene):
                return se
    except Exception:
        pass
    return None


def _dg_flush():
    global _DG_FLUSH_ARMED, _dg_scene_ref
    _DG_FLUSH_ARMED = False
    s = _dg_scene_ref
    _dg_scene_ref = None
    if not _addon_active or s is None:
        return None
    try:
        _poll_sync_scene(s)
    except Exception:
        pass
    return None


def _arm_depsgraph_flush(scene: bpy.types.Scene) -> None:
    global _DG_FLUSH_ARMED, _dg_scene_ref
    if _sync_in_progress:
        return
    _dg_scene_ref = scene
    if _DG_FLUSH_ARMED:
        return
    _DG_FLUSH_ARMED = True
    try:
        bpy.app.timers.register(_dg_flush, first_interval=0.008)
    except Exception:
        _DG_FLUSH_ARMED = False
        _dg_scene_ref = None


@persistent
def _depsgraph_msgbus_context_heal(_depsgraph) -> None:
    """Uma cura de msgbus na primeira passagem do depsgraph após register/load (RNA estável)."""
    global _msgbus_heal_for_context_gen
    if not _addon_active:
        return
    if _msgbus_heal_for_context_gen == _file_context_generation:
        return
    try:
        _heal_subscriptions_tick()
        _msgbus_heal_for_context_gen = _file_context_generation
    except Exception:
        pass


@persistent
def _depsgraph_update_post(depsgraph) -> None:
    if not _addon_active or _sync_in_progress:
        return
    if not _prefs_use_depsgraph():
        return
    scene = _scene_from_depsgraph(depsgraph)
    if scene is None:
        return
    leaders = _leader_pointers_for_scene(scene)
    if not leaders:
        return
    for u in depsgraph.updates:
        try:
            uid = u.id
        except ReferenceError:
            continue
        if isinstance(uid, bpy.types.Object) and uid.as_pointer() in leaders:
            _arm_depsgraph_flush(scene)
            return
    return


def _subscribe_leader_modifier_props_bus(leader, group) -> None:
    """RNA path por índice (evita caracteres estranhos no nome); sliders disparam notify."""
    if not _prefs_msgbus_modifier_props():
        return
    n = len(leader.modifiers)
    for idx in range(n):
        try:
            m = leader.modifiers[idx]
            bl_rna = getattr(m, "bl_rna", None)
            if bl_rna is None:
                continue
            base = f"modifiers[{idx}]"
            for prop in bl_rna.properties:
                ident = prop.identifier
                if ident in _SKIP_IDS:
                    continue
                if prop.is_readonly:
                    continue
                if prop.type in ("POINTER", "COLLECTION"):
                    continue
                if prop.type not in _FP_VALUE_TYPES:
                    continue
                try:
                    key = leader.path_resolve(f"{base}.{ident}", False)
                except (ReferenceError, TypeError, ValueError, KeyError):
                    continue
                try:
                    bpy.msgbus.subscribe_rna(
                        key=key,
                        owner=_MSG_OWNER,
                        args=(group,),
                        notify=_msgbus_modifiers_notify,
                    )
                except (TypeError, ValueError, AttributeError, RuntimeError):
                    pass
        except (ReferenceError, RuntimeError):
            continue


def _subscribe_leader_modifiers_bus(group) -> None:
    leader = group.leader
    if not leader:
        return
    # Coleção da pilha (add/remove/reorder)
    if _prefs_use_msgbus():
        try:
            key = leader.path_resolve("modifiers", False)
        except (ReferenceError, TypeError, ValueError):
            key = None
        if key is not None:
            try:
                bpy.msgbus.subscribe_rna(
                    key=key,
                    owner=_MSG_OWNER,
                    args=(group,),
                    notify=_msgbus_modifiers_notify,
                )
            except (TypeError, ValueError, AttributeError, RuntimeError):
                pass
    # Cada campo escalar (Bevel width, Subdiv levels, etc.) — tempo real na UI
    _subscribe_leader_modifier_props_bus(leader, group)


def _run_sync_for_group(scene: bpy.types.Scene, i: int, g) -> None:
    global _sync_in_progress
    if _sync_in_progress:
        return
    leader = g.leader
    if leader is None:
        return
    ck = _fp_cache_key(scene, i)
    new_fp = _full_fingerprint(leader)
    cf = _CACHE_FP.get(ck)
    ch = _CACHE_H.get(ck)
    new_h = _stack_hash(leader)

    if cf is None:
        _CACHE_H[ck] = new_h
        _CACHE_FP[ck] = new_fp
        return

    if new_fp == cf:
        return

    _sync_in_progress = True
    try:
        if ch is None:
            ch = new_h
            _CACHE_H[ck] = new_h
        if ch != new_h:
            sync_engine.sync_group(g, scene, do_stack=bool(g.sync_stack))
        else:
            sync_engine.sync_group(g, scene, do_stack=False)
        _CACHE_H[ck] = new_h
        _CACHE_FP[ck] = _full_fingerprint(leader)
    finally:
        _sync_in_progress = False


def refresh_subscriptions(scene: bpy.types.Scene | None = None) -> None:
    """Limpa msgbus/cache e volta a subscrever **todas** as cenas (o parâmetro fica por compatibilidade)."""
    bpy.msgbus.clear_by_owner(_MSG_OWNER)
    _MSG_DEBOUNCE.clear()
    _CACHE_H.clear()
    _CACHE_FP.clear()
    try:
        scenes = list(bpy.data.scenes)
    except Exception:
        scenes = []
    if scene is not None and scene not in scenes:
        scenes.append(scene)
    for sc in scenes:
        try:
            for i, g in enumerate(sc.modifier_sync_groups):
                if g.auto_sync and g.leader:
                    ck = _fp_cache_key(sc, i)
                    _CACHE_H[ck] = _stack_hash(g.leader)
                    _CACHE_FP[ck] = _full_fingerprint(g.leader)
                    _subscribe_leader_modifiers_bus(g)
        except Exception:
            continue


@persistent
def _undo_redo_post(*_args) -> None:
    """Undo/redo invalida caminhos RNA e o cache Python não volta atrás — repõe subscrições."""
    if not _addon_active:
        return
    try:
        refresh_subscriptions()
    except Exception:
        pass


def _poll_sync_scene(scene: bpy.types.Scene) -> None:
    for i, g in enumerate(scene.modifier_sync_groups):
        if not g.auto_sync or g.leader is None:
            continue
        _run_sync_for_group(scene, i, g)


def _auto_sync_poll():
    global _last_scene_cleanup_ts, _last_msgbus_heal_ts
    if not _addon_active:
        return None
    try:
        _ = bpy.context
    except Exception:
        return 0.1

    t = time.monotonic()
    if t - _last_scene_cleanup_ts >= _SCENE_CLEANUP_INTERVAL:
        _last_scene_cleanup_ts = t
        try:
            for sc in bpy.data.scenes:
                sync_engine.cleanup_scene_groups(sc)
        except Exception:
            pass

    has_auto = False
    try:
        for sc in bpy.data.scenes:
            if any(g.auto_sync and g.leader for g in sc.modifier_sync_groups):
                has_auto = True
                break
    except Exception:
        has_auto = False

    if not has_auto:
        return 0.25

    if _prefs_periodic_heal() and t - _last_msgbus_heal_ts >= _MSGBUS_HEAL_INTERVAL:
        _last_msgbus_heal_ts = t
        try:
            refresh_subscriptions()
        except Exception:
            pass

    try:
        for sc in bpy.data.scenes:
            _poll_sync_scene(sc)
    except Exception:
        pass

    return _prefs_poll_interval()


def on_blend_context_changed() -> None:
    """Chamar ao carregar .blend e no início de register() — invalida a última «cura»."""
    global _file_context_generation
    _file_context_generation += 1


def heal_if_file_context_changed() -> None:
    """Painel / operadores: repõe subscrições se o contexto de ficheiro mudou desde a última cura."""
    global _last_heal_generation, _file_context_generation
    if _last_heal_generation == _file_context_generation:
        return
    _heal_subscriptions_tick()


def _heal_subscriptions_tick():
    """Limpar grupos órfãos e repor msgbus/cache (arranque do Blender, load, ou cena ainda a estabilizar)."""
    global _last_heal_generation, _file_context_generation
    if not _addon_active:
        return None
    try:
        for sc in bpy.data.scenes:
            sync_engine.cleanup_scene_groups(sc)
    except Exception:
        pass
    try:
        refresh_subscriptions()
    except Exception:
        pass
    finally:
        _last_heal_generation = _file_context_generation
    return None


def _schedule_heal_timers(delays: tuple[float, ...]) -> None:
    for delay in delays:
        try:
            bpy.app.timers.register(_heal_subscriptions_tick, first_interval=delay)
        except Exception:
            pass


def _schedule_heal_after_handler_chain() -> None:
    """Uma cura no próximo tick (0 s) — corre depois dos outros ``load_post`` no mesmo ciclo."""

    def _deferred():
        if not _addon_active:
            return None
        try:
            _heal_subscriptions_tick()
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_deferred, first_interval=0.0)
    except Exception:
        pass


def _viewport_draw_heal_callback(*_args) -> None:
    """Executado uma vez no redraw da View3D; API actual: ``draw_handler_remove(handler, region_type)``."""
    global _viewport_msgbus_heal_handle
    h = _viewport_msgbus_heal_handle
    if h is None:
        return
    _viewport_msgbus_heal_handle = None
    try:
        bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
    except Exception:
        pass
    if _addon_active:
        try:
            _heal_subscriptions_tick()
        except Exception:
            pass


def request_viewport_msgbus_heal() -> None:
    """Força ``_heal_subscriptions_tick`` no próximo desenho 3D (útil após abrir .blend)."""
    global _viewport_msgbus_heal_handle
    if _viewport_msgbus_heal_handle is not None:
        return
    try:
        _viewport_msgbus_heal_handle = bpy.types.SpaceView3D.draw_handler_add(
            _viewport_draw_heal_callback,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
    except Exception:
        _viewport_msgbus_heal_handle = None
        return
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass


def _drop_viewport_msgbus_heal() -> None:
    global _viewport_msgbus_heal_handle
    h = _viewport_msgbus_heal_handle
    if h is None:
        return
    _viewport_msgbus_heal_handle = None
    try:
        bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
    except Exception:
        pass


# Arranque frio: com o addon já activo nas prefs, o .blend por defeito pode carregar antes do RNA
# estar pronto — vários ticks cobrem o caso em que um único refresh no register() falha em silêncio.
_HEAL_DELAYS_COLD_START = (0.0, 0.02, 0.08, 0.2, 0.6, 1.5, 3.5, 6.0, 10.0, 15.0)
_HEAL_DELAYS_AFTER_FILE = (0.03, 0.15, 0.5, 1.2, 3.0, 8.0)


@persistent
def _load_post(_dummy, filepath=None):
    on_blend_context_changed()
    try:
        for sc in bpy.data.scenes:
            sync_engine.cleanup_scene_groups(sc)
            for g in sc.modifier_sync_groups:
                if g.auto_sync and g.leader:
                    try:
                        sync_engine.sync_group(g, sc)
                    except Exception:
                        pass
    except Exception:
        pass
    refresh_subscriptions()
    _schedule_heal_timers(_HEAL_DELAYS_AFTER_FILE)
    request_viewport_msgbus_heal()
    _schedule_heal_after_handler_chain()


def register():
    global _addon_active
    _addon_active = True
    on_blend_context_changed()
    try:
        if bpy.app.timers.is_registered(_auto_sync_poll):
            bpy.app.timers.unregister(_auto_sync_poll)
    except Exception:
        pass
    bpy.app.timers.register(_auto_sync_poll, first_interval=0.05, persistent=True)
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    bpy.app.handlers.load_post.append(_load_post)
    for _h in (_depsgraph_msgbus_context_heal, _depsgraph_update_post):
        if _h in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_h)
    bpy.app.handlers.depsgraph_update_post.append(_depsgraph_msgbus_context_heal)
    bpy.app.handlers.depsgraph_update_post.append(_depsgraph_update_post)
    if hasattr(bpy.app.handlers, "undo_post"):
        bpy.app.handlers.undo_post.append(_undo_redo_post)
    if hasattr(bpy.app.handlers, "redo_post"):
        bpy.app.handlers.redo_post.append(_undo_redo_post)
    try:
        refresh_subscriptions()
    except Exception:
        pass
    _schedule_heal_timers(_HEAL_DELAYS_COLD_START)
    request_viewport_msgbus_heal()
    _schedule_heal_after_handler_chain()


def unregister():
    global _addon_active, _DG_FLUSH_ARMED, _dg_scene_ref
    global _last_heal_generation, _file_context_generation, _msgbus_heal_for_context_gen
    _addon_active = False
    try:
        if bpy.app.timers.is_registered(_auto_sync_poll):
            bpy.app.timers.unregister(_auto_sync_poll)
    except Exception:
        pass
    _last_heal_generation = -1
    _file_context_generation = 0
    _msgbus_heal_for_context_gen = -1
    _drop_viewport_msgbus_heal()
    _DG_FLUSH_ARMED = False
    _dg_scene_ref = None
    if _depsgraph_msgbus_context_heal in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_msgbus_context_heal)
    if _depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_update_post)
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    if hasattr(bpy.app.handlers, "undo_post") and _undo_redo_post in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(_undo_redo_post)
    if hasattr(bpy.app.handlers, "redo_post") and _undo_redo_post in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.remove(_undo_redo_post)
    bpy.msgbus.clear_by_owner(_MSG_OWNER)
    _MSG_DEBOUNCE.clear()
    _CACHE_H.clear()
    _CACHE_FP.clear()
