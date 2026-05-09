"""
Atalhos em keyconfigs.addon — padrão Blender 5.1:
https://docs.blender.org/api/5.1/bpy.types.KeyMaps.html
Um único KeyMap «3D View» / VIEW_3D; o Blender reutiliza o mesmo mapa se já existir.
"""

import bpy

addon_keymaps: list[tuple] = []


def _prefs():
    try:
        return bpy.context.preferences.addons["modifier_sync"].preferences
    except Exception:
        return None


def register_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return

    prefs = _prefs()
    use_dup = bool(getattr(prefs, "enable_duplicate_sync_shortcut", True)) if prefs else True
    use_push = bool(getattr(prefs, "enable_push_sync_shortcut", True)) if prefs else True

    if not use_dup and not use_push:
        return

    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")

    def add_item(idname, letter, *, shift, ctrl=False, alt=False):
        try:
            kmi = km.keymap_items.new(
                idname,
                letter,
                "PRESS",
                shift=shift,
                ctrl=ctrl,
                alt=alt,
                head=True,
            )
        except TypeError:
            kmi = km.keymap_items.new(
                idname,
                letter,
                "PRESS",
                shift=shift,
                ctrl=ctrl,
                alt=alt,
            )
        addon_keymaps.append((km, kmi))

    if use_dup:
        add_item("modifier_sync.duplicate_with_modifier_sync", "D", shift=True, ctrl=True)
        add_item("modifier_sync.duplicate_with_modifier_sync", "D", shift=True, alt=True)
    if use_push:
        add_item("modifier_sync.push_sync", "S", shift=True, ctrl=True)
        add_item("modifier_sync.push_sync", "S", shift=True, alt=True)


def unregister_keymap():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    addon_keymaps.clear()
