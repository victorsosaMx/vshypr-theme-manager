#!/usr/bin/env python3
# Cambia el tema del escritorio aplicando colores a múltiples aplicaciones
# sin reemplazar archivos completos — usa marcadores en los configs existentes.

import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Rutas ──────────────────────────────────────────────────────────────────────

SELF_DIR      = Path(__file__).parent
THEMES_DIR    = SELF_DIR / "themes"
TEMPLATES_DIR = SELF_DIR / "templates"
BACKUPS_DIR   = SELF_DIR / "backups"
ORIGINAL_DIR  = BACKUPS_DIR / "original"
STATE_FILE    = SELF_DIR / "current-theme.json"

HOME = Path.home()
CFG  = HOME / ".config"

KITTY_THEME   = CFG / "kitty"  / "theme.conf"
WAYBAR_STYLE  = CFG / "waybar" / "style.css"
SWAYNC_STYLE  = CFG / "swaync" / "style.css"
HYPR_THEME    = CFG / "hypr"   / "theme.conf"
HYPR_MAIN     = CFG / "hypr"   / "hyprland.conf"
HYPRLOCK_CONF = CFG / "hypr"   / "hyprlock.conf"
ROFI_CONFIG        = CFG / "rofi" / "config.rasi"
ROFI_SPOTLIGHT     = CFG / "rofi" / "spotlight.rasi"
ROFI_LAUNCHPAD     = CFG / "rofi" / "launchpad.rasi"
ROFI_KEYBINDS      = CFG / "rofi" / "config-keybinds.rasi"
ROFI_WALLPAPER     = CFG / "rofi" / "wallpaper-grid.rasi"
ROFI_WP_PICKER     = CFG / "rofi" / "wallpaper-picker.rasi"
VSFETCH_CONFIG     = CFG / "vsfetch" / "config.json"
EWW_CSS       = CFG / "eww"    / "eww.css"
WLOGOUT_STYLE = CFG / "wlogout"/ "style.css"
HYPRSWITCH_STYLE = CFG / "hyprswitch" / "style.css"
WALLPAPER_SH     = CFG / "hypr"       / "wallpaper.sh"
GTK4_CSS         = CFG / "gtk-4.0"   / "gtk.css"
GTK4_DARK_CSS    = CFG / "gtk-4.0"   / "gtk-dark.css"
GTK3_CSS         = CFG / "gtk-3.0"   / "gtk.css"
GTK3_SETTINGS    = CFG / "gtk-3.0"   / "settings.ini"
QT6CT_CONF       = CFG / "qt6ct"     / "qt6ct.conf"
QT5CT_CONF       = CFG / "qt5ct"     / "qt5ct.conf"
QT5CT_COLORS     = CFG / "qt5ct"     / "colors" / "ThemeChanger.conf"
QT_COLOR_SCHEME  = Path.home() / ".local/share/color-schemes/ThemeChanger.colors"
KDEGLOBALS       = CFG / "kdeglobals"
KVANTUM_DIR      = CFG / "Kvantum"
KVANTUM_CONF     = CFG / "Kvantum" / "kvantum.kvconfig"
KVANTUM_THEME_DIR = CFG / "Kvantum" / "ThemeChanger"
KVANTUM_THEME_KV  = KVANTUM_THEME_DIR / "ThemeChanger.kvconfig"

MARKER_BEGIN = "theme-changer: begin"
MARKER_END   = "theme-changer: end"

# ── Utilidades de color ────────────────────────────────────────────────────────

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    """Convierte #RRGGBB a (r, g, b)."""
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

def hex_to_hypr(h: str, alpha: str = "ff") -> str:
    """Convierte #RRGGBB a rgba(RRGGBBaa) para Hyprland."""
    return f"rgba({h.lstrip('#')}{alpha})"

def hex_to_rgba_css(h: str, alpha: float) -> str:
    """Convierte #RRGGBB a rgba(r,g,b,alpha) para CSS."""
    r, g, b = hex_to_rgb(h)
    return f"rgba({r},{g},{b},{alpha})"

def build_context(colors: dict) -> dict:
    """
    Construye el diccionario completo de variables disponibles en los templates.
    Incluye colores base + variantes computadas (rgba, hypr).
    """
    ctx = dict(colors)

    # Variantes para Hyprland: rgba(rrggbbff) y rgba(rrggbbaa)
    for name in ("accent", "accent_alt", "bg", "bg_alt", "surface",
                 "border_active", "border_inactive", "shadow"):
        if name in colors:
            ctx[f"{name}_hypr"]    = hex_to_hypr(colors[name], "ff")
            ctx[f"{name}_hypr_aa"] = hex_to_hypr(colors[name], "aa")

    # Variantes rgba para CSS
    rgba_variants: dict[str, list[float]] = {
        "accent":   [0.10, 0.15, 0.20, 0.28, 0.35, 0.40, 0.45, 0.50, 0.55],
        "teal":     [0.10, 0.20, 0.35],
        "bg":       [0.40, 0.50, 0.70, 0.80, 0.93, 0.95, 0.96, 0.98],
        "surface":  [0.40, 0.50, 0.60, 0.70, 0.92],
        "surface2": [0.80, 0.90, 0.98],
        "overlay":  [0.20, 0.22, 0.30, 0.35, 0.85],
        "red":      [0.12, 0.15, 0.25, 0.35, 0.40, 0.50],
        "fg":       [0.55],
        "shadow":   [0.40],
    }
    for name, alphas in rgba_variants.items():
        if name in colors:
            for a in alphas:
                key = f"{name}_rgba_{int(a * 100):02d}"
                ctx[key] = hex_to_rgba_css(colors[name], a)

    return ctx

# ── Lectura de temas ───────────────────────────────────────────────────────────

def read_theme(theme_name: str) -> tuple[dict, str]:
    """Lee colors.json y retorna (colores, variante) donde variante es 'dark' o 'light'."""
    path = THEMES_DIR / theme_name / "colors.json"
    if not path.exists():
        sys.exit(f"Error: no se encontró el tema '{theme_name}' en {THEMES_DIR}")
    with open(path) as f:
        data = json.load(f)
    variant = data.get("meta", {}).get("variant", "dark")
    return data["colors"], variant

def read_colors(theme_name: str) -> dict:
    """Lee colors.json para el tema dado y retorna solo el dict de colores."""
    colors, _ = read_theme(theme_name)
    return colors

def list_themes() -> list[str]:
    """Retorna lista de nombres de temas disponibles (excluyendo variantes dynamic)."""
    return sorted(
        d.name for d in THEMES_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("dynamic")
    )

# ── Sistema de backups ─────────────────────────────────────────────────────────

# Archivos que se modifican con marcadores
MARKER_FILES = [
    WAYBAR_STYLE, SWAYNC_STYLE, HYPRLOCK_CONF,
    ROFI_CONFIG, ROFI_SPOTLIGHT, ROFI_LAUNCHPAD,
    ROFI_KEYBINDS, ROFI_WALLPAPER, VSFETCH_CONFIG,
    HYPRSWITCH_STYLE,
]

# Archivos que se generan desde template (también se respaldan)
GENERATED_FILES = [EWW_CSS, WLOGOUT_STYLE]

# Todos los archivos que tocamos — se respaldan antes de cada apply
ALL_MANAGED = MARKER_FILES + GENERATED_FILES + [WALLPAPER_SH, GTK4_CSS, GTK4_DARK_CSS, GTK3_CSS, GTK3_SETTINGS, QT6CT_CONF, QT5CT_CONF, QT5CT_COLORS, QT_COLOR_SCHEME, KDEGLOBALS, KVANTUM_CONF, KVANTUM_THEME_KV]

WLOGOUT_ICONS = CFG / "wlogout" / "icons"

def _all_backup_targets() -> list[Path]:
    """Lista completa de archivos a respaldar, incluyendo SVGs de wlogout."""
    targets = list(ALL_MANAGED)
    if WLOGOUT_ICONS.exists():
        targets.extend(WLOGOUT_ICONS.glob("*.svg"))
    return targets

def backup_dest(base_dir: Path, p: Path) -> Path:
    """
    Retorna la ruta de destino del backup manteniendo estructura por app.
    Ej: ~/.config/rofi/config.rasi  →  base_dir/rofi/config.rasi
        ~/.config/wlogout/icons/x.svg → base_dir/wlogout/icons/x.svg
    """
    try:
        rel = p.relative_to(CFG)
    except ValueError:
        rel = Path(p.parent.name) / p.name
    return base_dir / rel

def backup_original():
    """
    Crea backup original de TODOS los archivos gestionados.
    Cada archivo se guarda UNA SOLA VEZ — si ya existe en original/ no se sobreescribe.
    Permite agregar nuevos archivos gestionados sin perder los ya guardados.
    """
    ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for p in _all_backup_targets():
        dest = backup_dest(ORIGINAL_DIR, p)
        if p.exists() and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            saved.append(str(dest.relative_to(ORIGINAL_DIR)))
    if saved:
        print(f"  [backup] Original → backups/original/ ({', '.join(saved)})")

def backup_timestamped():
    """Guarda snapshot de TODOS los archivos gestionados antes de cada apply."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    ts_dir = BACKUPS_DIR / ts
    ts_dir.mkdir(parents=True)
    for p in _all_backup_targets():
        if p.exists():
            dest = backup_dest(ts_dir, p)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)

# ── Inyección de marcadores ────────────────────────────────────────────────────

def inject_css(path: Path, block: str, suffix: str = ""):
    """
    Inyecta un bloque CSS con marcadores nombrados.
    - suffix permite tener múltiples bloques en el mismo archivo.
    - Si los marcadores ya existen: reemplaza el contenido entre ellos.
    - Si no existen: agrega al FINAL del archivo (el último gana en CSS).
    - Limpia @define-color duplicados fuera de marcadores (solo para el bloque principal).
    """
    if not path.exists():
        print(f"  [warn] No encontrado: {path}")
        return

    tag_begin = f"{MARKER_BEGIN}{(' ' + suffix) if suffix else ''}"
    tag_end   = f"{MARKER_END}{(' ' + suffix) if suffix else ''}"
    begin = f"/* {tag_begin} */"
    end   = f"/* {tag_end} */"
    replacement = f"{begin}\n{block}\n{end}"

    content = path.read_text()
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)

    if pattern.search(content):
        new_content = pattern.sub(replacement, content)
    else:
        new_content = content.rstrip() + f"\n\n{replacement}\n"

    # Solo para el bloque principal: limpiar @define-color duplicados fuera de marcadores
    if not suffix:
        end_pos = new_content.find(end)
        if end_pos >= 0:
            after = new_content[end_pos + len(end):]
            after = re.sub(r"\n@define-color\s+\S+[^\n]*", "", after)
            new_content = new_content[:end_pos + len(end)] + after

    path.write_text(new_content)

def inject_json(path: Path, colors_dict: dict):
    """
    Inyecta una paleta de colores en un archivo JSON que contenga una clave "palette".
    Busca los marcadores theme-changer: begin y theme-changer: end.
    Si no existen, intenta crear la estructura inicial.
    """
    if not path.exists():
        print(f"  [warn] No encontrado: {path}")
        return

    content = path.read_text()
    
    # Marcadores en JSON (como comentarios si el parser lo permite o simplemente marcas)
    # vsfetch parece ser un JSON estándar, pero algunos parsers permiten comentarios.
    # Si no, tendremos que ser creativos con las claves.
    # Dado que el objetivo es no reemplazar el archivo completo, usaremos una técnica de reemplazo de valores.
    
    try:
        data = json.loads(content)
        if "palette" not in data:
            data["palette"] = {}
        
        # Actualizamos la paleta con los nuevos colores
        for key, value in colors_dict.items():
            data["palette"][key] = value
            
        path.write_text(json.dumps(data, indent=2))
    except Exception as e:
        print(f"  [error] inject_json: {e}")

def inject_rasi(path: Path, block: str):
    """
    Inyecta variables de color en el bloque * {} de config.rasi.
    - Si los marcadores ya existen: reemplaza el contenido entre ellos.
    - Si no existen: inserta al FINAL del bloque * {} (el último gana en Rofi).
    No toca el contenido de otros bloques (window, element, etc.).
    """
    if not path.exists():
        print(f"  [warn] No encontrado: {path}")
        return

    begin = f"    /* {MARKER_BEGIN} */"
    end   = f"    /* {MARKER_END} */"
    replacement = f"{begin}\n{block}\n{end}"

    content = path.read_text()
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)

    if pattern.search(content):
        new_content = pattern.sub(replacement, content)
    else:
        # Primer apply: insertar al FINAL del bloque * {} (justo antes del cierre })
        new_content = re.sub(
            r"(\* \{[^}]*?)(\n\})",
            rf"\1\n{replacement}\2",
            content,
            count=1,
            flags=re.DOTALL
        )
        if new_content == content:
            new_content = content.rstrip() + f"\n\n* {{\n{replacement}\n}}\n"

    # Limpiar todo lo que quedó entre /* theme-changer: end */ y el cierre }
    # del bloque * {} — son duplicados del estado anterior que pisarían nuestros valores
    new_content = re.sub(
        re.escape(end) + r"[\s\S]*?(\n\})",
        end + r"\1",
        new_content,
        count=1
    )

    path.write_text(new_content)

def inject_hypr(path: Path, block: str):
    """
    Para hyprlock.conf: reemplaza todo el contenido entre marcadores.
    Si no existen marcadores, reemplaza el archivo completo.
    """
    if not path.exists():
        print(f"  [warn] No encontrado: {path}")
        return

    begin = f"# {MARKER_BEGIN}"
    end   = f"# {MARKER_END}"
    replacement = f"{begin}\n{block}\n{end}"

    content = path.read_text()
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)

    if pattern.search(content):
        new_content = pattern.sub(replacement, content)
    else:
        # Primer apply: envuelve todo el archivo
        new_content = f"{replacement}\n"

    path.write_text(new_content)

def apply_template(tpl_path: Path, out_path: Path, ctx: dict):
    """Aplica un template reemplazando {{variable}} con los valores del contexto."""
    if not tpl_path.exists():
        print(f"  [warn] Template no encontrado: {tpl_path}")
        return
    content = tpl_path.read_text()
    for key, value in ctx.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)

# ── Apply por aplicación ───────────────────────────────────────────────────────

def apply_kitty(ctx: dict):
    """
    Genera theme.conf para Kitty.
    Si no existe kitty.conf, crea uno mínimo con 'include theme.conf'.
    Si ya existe, verifica que incluya theme.conf y agrega la línea si falta.
    """
    kitty_conf = KITTY_THEME.parent / "kitty.conf"
    if kitty_conf.exists():
        text = kitty_conf.read_text()
        if "include theme.conf" not in text:
            with open(kitty_conf, "a") as f:
                f.write("\n# theme-changer\ninclude theme.conf\n")
    else:
        kitty_conf.write_text("# Kitty config — generado por theme-changer\ninclude theme.conf\n")

    content = f"""# Generado por theme-changer — no editar directamente
# Para personalizar colores: editar ~/.config/kitty/kitty.conf

foreground            {ctx['fg']}
background            {ctx['bg']}
selection_foreground  {ctx['bg']}
selection_background  {ctx['accent']}
cursor                {ctx['accent']}
cursor_text_color     {ctx['bg']}
url_color             {ctx['accent']}

# Terminal colors (0-7 normal, 8-15 bright)
color0   {ctx['bg_alt']}
color1   {ctx['red']}
color2   {ctx['green']}
color3   {ctx['yellow']}
color4   {ctx['blue']}
color5   {ctx['mauve']}
color6   {ctx['teal']}
color7   {ctx['fg_dim']}
color8   {ctx['surface2']}
color9   {ctx['red']}
color10  {ctx['green']}
color11  {ctx['yellow']}
color12  {ctx['accent']}
color13  {ctx['pink']}
color14  {ctx['teal']}
color15  {ctx['fg']}

# Bordes
active_border_color   {ctx['accent']}
inactive_border_color {ctx['border_inactive']}
bell_border_color     {ctx['red']}
"""
    KITTY_THEME.parent.mkdir(parents=True, exist_ok=True)
    KITTY_THEME.write_text(content)
    # Recargar instancias activas de kitty
    subprocess.run(["pkill", "-USR1", "kitty"], capture_output=True)


def apply_waybar(ctx: dict):
    """Actualiza variables de color en style.css de Waybar.

    Si vsWaybar Studio controla el archivo (detectado por /* vswaybar:modpad */),
    actualiza los @define-color en place — sin bloques extra ni duplicados.
    Si no existe el archivo o no hay tokens, usa inject_css como fallback.
    """
    if not WAYBAR_STYLE.exists():
        print(f"  [warn] No encontrado: {WAYBAR_STYLE}")
        return

    tokens = {
        "base":     ctx['bg'],
        "mantle":   ctx['surface3'],
        "crust":    ctx['bg_alt'],
        "surface0": ctx['surface'],
        "surface1": ctx['surface2'],
        "overlay0": ctx['overlay'],
        "text":     ctx['fg'],
        "subtext0": ctx['fg_dim'],
        "blue":     ctx['accent'],
        "mauve":    ctx['mauve'],
        "red":      ctx['red'],
        "green":    ctx['teal'],
        "yellow":   ctx['yellow'],
        "peach":    ctx['orange'],
    }

    content = WAYBAR_STYLE.read_text()
    vswaybar_managed = "/* vswaybar:modpad */" in content

    if vswaybar_managed:
        # Actualizar @define-color en place — sin agregar bloques extra.
        # Limpia cualquier bloque theme-changer previo (evita duplicados).
        for tag in ("", " modules", " keyframes"):
            begin = f"/* theme-changer: begin{tag} */"
            end   = f"/* theme-changer: end{tag} */"
            pat   = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
            content = pat.sub("", content)
        # Quitar líneas vacías extra dejadas por la limpieza
        content = re.sub(r'\n{3,}', '\n\n', content).rstrip() + "\n"
        # Actualizar cada token existente en place
        updated = set()
        for name, val in tokens.items():
            pat = rf'(@define-color\s+{re.escape(name)}\s+)(#[0-9a-fA-F]{{6}})'
            if re.search(pat, content):
                content = re.sub(pat, rf'\g<1>{val}', content)
                updated.add(name)
        # Agregar al principio los tokens que no existían
        missing = [f"@define-color {n} {v};" for n, v in tokens.items() if n not in updated]
        if missing:
            content = "\n".join(missing) + "\n" + content
        WAYBAR_STYLE.write_text(content)
    else:
        # Sin vsWaybar Studio: usar inject_css + modules/keyframes completos
        block = "\n".join(f"@define-color {n} {v};" for n, v in tokens.items())
        inject_css(WAYBAR_STYLE, block)

        modules_block = f""".modules-left,
.modules-center,
.modules-right {{
    background: {ctx['bg_rgba_95']};
    border-radius: 14px;
    padding: 2px 10px;
    border: 2px solid {ctx['surface']};
    min-height: 0;
}}"""
        inject_css(WAYBAR_STYLE, modules_block, suffix="modules")

        keyframes_block = f"""@keyframes ws-active {{
    0%   {{ background-color: {ctx['accent']}; }}
    50%  {{ background-color: {ctx['accent_alt']}; }}
    100% {{ background-color: {ctx['accent']}; }}
}}"""
        inject_css(WAYBAR_STYLE, keyframes_block, suffix="keyframes")

    subprocess.run(["pkill", "-x", "waybar"], capture_output=True)
    time.sleep(0.4)
    subprocess.Popen(["waybar"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply_swaync(ctx: dict):
    """
    Inyecta variables de color en style.css de SwayNC vía marcadores CSS.
    Si el archivo no existe, lo inicializa desde /etc/xdg/swaync/style.css.
    """
    if not SWAYNC_STYLE.exists():
        system_style = Path("/etc/xdg/swaync/style.css")
        if system_style.exists():
            SWAYNC_STYLE.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(system_style, SWAYNC_STYLE)
            print(f"  [swaync] Inicializado → {SWAYNC_STYLE}")
        else:
            print(f"  [warn] SwayNC no encontrado en {SWAYNC_STYLE} ni en /etc")
            return

    # --noti-bg se usa como rgba(var(--noti-bg), alpha) → necesita solo "r, g, b"
    r, g, b = hex_to_rgb(ctx['surface'])

    block = f""":root {{
  --cc-bg:               {ctx['bg_rgba_93']};
  --noti-border-color:   {ctx['overlay_rgba_35']};
  --noti-bg:             {r}, {g}, {b};
  --noti-bg-alpha:       0.85;
  --noti-bg-darker:      {ctx['bg']};
  --noti-bg-hover:       {ctx['surface2']};
  --noti-bg-focus:       {ctx['overlay_rgba_30']};
  --noti-close-bg:       {ctx['surface2']};
  --noti-close-bg-hover: {ctx['overlay']};
  --text-color:          {ctx['fg']};
  --text-color-disabled: {ctx['fg_dim']};
  --bg-selected:         {ctx['accent']};
}}"""

    inject_css(SWAYNC_STYLE, block)
    subprocess.run(["swaync-client", "--reload-css"], capture_output=True)



def apply_hyprland(ctx: dict):
    """
    Genera theme.conf para Hyprland con los colores del tema.
    Lo agrega como source al final de hyprland.conf (solo la primera vez).
    """
    content = f"""# Generado por theme-changer — no editar directamente

general {{
    col.active_border   = {ctx['border_active_hypr']} {ctx['accent_alt_hypr']} 45deg
    col.inactive_border = {ctx['border_inactive_hypr_aa']}
}}

decoration {{
    shadow {{
        color = {ctx['shadow_hypr_aa']}
    }}
}}

# Blur de capas
blurls = wlogout
blurls = rofi
"""
    HYPR_THEME.parent.mkdir(parents=True, exist_ok=True)
    HYPR_THEME.write_text(content)

    # Agregar source si no existe en hyprland.conf
    source_line = "source = $HOME/.config/hypr/theme.conf"
    if HYPR_MAIN.exists():
        main_content = HYPR_MAIN.read_text()
        if source_line not in main_content:
            with open(HYPR_MAIN, "a") as f:
                f.write(f"\n# theme-changer\n{source_line}\n")
            print("  [hyprland] Agregado source → hyprland.conf")

    subprocess.run(["hyprctl", "reload"], capture_output=True)


def apply_hyprlock(ctx: dict):
    """
    Genera el bloque de colores de hyprlock.conf vía marcadores Hyprland.
    El resto del archivo (posiciones, tamaños) permanece intacto.
    """
    r_bg,  g_bg,  b_bg  = hex_to_rgb(ctx['bg'])
    r_acc, g_acc, b_acc = hex_to_rgb(ctx['accent'])
    r_fg,  g_fg,  b_fg  = hex_to_rgb(ctx['fg'])

    block = f"""background {{
    monitor =
    color = rgba({r_bg},{g_bg},{b_bg},1.0)
    blur_passes = 2
    contrast = 0.8916
    brightness = 0.8172
    vibrancy = 0.1696
    vibrancy_darkness = 0.0
}}

general {{
    no_fade_in = false
    grace = 0
    disable_loading = true
}}

input-field {{
    monitor =
    size = 250, 60
    outline_thickness = 2
    dots_size = 0.2
    dots_spacing = 0.2
    dots_center = true
    outer_color = rgb({r_acc},{g_acc},{b_acc})
    inner_color = rgb({r_bg},{g_bg},{b_bg})
    font_color = rgb({r_fg},{g_fg},{b_fg})
    fade_on_empty = true
    placeholder_text = <span foreground="{ctx['fg_dim']}">Password...</span>
    hide_input = false
    position = 0, -120
    halign = center
    valign = center
}}

label {{
    monitor =
    text = $TIME
    color = rgb({r_fg},{g_fg},{b_fg})
    font_size = 120
    font_family = JetBrainsMono Nerd Font Bold
    position = 0, 80
    halign = center
    valign = center
}}

label {{
    monitor =
    text = hi, $USER
    color = rgb({r_acc},{g_acc},{b_acc})
    font_size = 25
    font_family = JetBrainsMono Nerd Font
    position = 0, -40
    halign = center
    valign = center
}}"""

    inject_hypr(HYPRLOCK_CONF, block)


def apply_rofi(ctx: dict):
    """Inyecta variables de color en el bloque * {} de todos los .rasi."""
    bg   = ctx['bg']
    sel  = ctx['surface']
    fg   = ctx['fg']
    dim  = ctx['fg_dim']
    bdr  = ctx['border_inactive']
    acc  = ctx['accent']

    # config.rasi  /  spotlight.rasi  /  config-keybinds.rasi  — usan bg-sel
    block_sel = f"""    bg:      {bg};
    bg-sel:  {sel};
    fg:      {fg};
    fg-dim:  {dim};
    accent:  {acc};

    background-color: transparent;
    text-color:       @fg;
    border-color:     {bdr};
    spacing:          0;
    padding:          0;
    margin:           0;"""

    for path in (ROFI_CONFIG, ROFI_SPOTLIGHT, ROFI_KEYBINDS, ROFI_WP_PICKER):
        inject_rasi(path, block_sel)

    # launchpad.rasi  /  wallpaper-grid.rasi  — usan bg-alt y sel
    block_alt = f"""    bg:      {bg};
    bg-alt:  {sel};
    fg:      {fg};
    fg-dim:  {dim};
    sel:     {acc};

    background-color: transparent;
    text-color:       @fg;
    border-color:     transparent;
    spacing:          0;
    padding:          0;
    margin:           0;"""

    for path in (ROFI_LAUNCHPAD, ROFI_WALLPAPER):
        inject_rasi(path, block_alt)


def apply_eww(ctx: dict, variant: str = "dark"):
    """
    Genera eww.css desde template con los colores del tema.
    Usa template de luz u oscuro según la variante.
    Usa 'eww reload' para recargar sin matar el daemon ni cerrar ventanas.
    """
    tpl = f"eww.{'light' if variant == 'light' else 'dark'}.css.tpl"
    tpl_path = TEMPLATES_DIR / tpl
    # Fallback al template único si no existe el de variante
    if not tpl_path.exists():
        tpl_path = TEMPLATES_DIR / "eww.css.tpl"
    apply_template(tpl_path, EWW_CSS, ctx)
    result = subprocess.run(["eww", "reload"], capture_output=True)
    if result.returncode != 0:
        subprocess.Popen(["eww", "daemon"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply_wlogout(ctx: dict):
    """
    Genera wlogout/style.css desde template con los colores del tema.
    También recolorea los iconos SVG reemplazando su fill con el accent actual.
    """
    apply_template(TEMPLATES_DIR / "wlogout.style.css.tpl", WLOGOUT_STYLE, ctx)

    # Recolorear iconos SVG: reemplazar cualquier fill="#xxxxxx" con el accent
    icons_dir = WLOGOUT_STYLE.parent / "icons"
    if icons_dir.exists():
        accent = ctx["accent"]
        for svg in icons_dir.glob("*.svg"):
            text = svg.read_text()
            # Reemplazar fill="#..." (colores hex de 3 o 6 dígitos)
            new_text = re.sub(r'fill="#[0-9a-fA-F]{3,8}"', f'fill="{accent}"', text)
            if new_text != text:
                svg.write_text(new_text)


def apply_vsfetch(ctx: dict):
    """Inyecta colores en la paleta de vsfetch config.json."""
    palette = {
        "bg":        ctx['bg'],
        "bg_header": ctx['bg_alt'],
        "border":    ctx['surface'],
        "text":      ctx['fg'],
        "text_dim":  ctx['fg_dim'],
        "text_mid":  ctx['overlay'],
        "accent":    ctx['accent'],
        "ok":        ctx['green'],
        "mid":       ctx['yellow'],
        "hi":        ctx['red']
    }
    inject_json(VSFETCH_CONFIG, palette)


def apply_hyprswitch(ctx: dict):
    """Inyecta variables de color y estilos en style.css de hyprswitch."""
    block = f"""@define-color bg      {ctx['bg']};
@define-color bg_alt  {ctx['bg_alt']};
@define-color accent  {ctx['accent']};
@define-color surface {ctx['surface']};
@define-color fg      {ctx['fg']};
@define-color fg_dim  {ctx['fg_dim']};

window {{
    background-color: {ctx['bg_rgba_50']};
    border: 1px solid {ctx['accent_rgba_15']};
    border-top: 2px solid {ctx['accent_rgba_35']};
}}

.workspace {{
    color: {ctx['fg_dim']};
}}

.client {{
    background-image: linear-gradient(
        160deg,
        {ctx['surface_rgba_92']} 0%,
        {ctx['bg_rgba_95']} 100%
    );
    border: 1px solid {ctx['surface_rgba_40']};
}}

.client:hover {{
    border: 1px solid {ctx['accent_rgba_45']};
}}

.client_active {{
    background-image: linear-gradient(
        160deg,
        {ctx['surface2_rgba_98']} 0%,
        {ctx['bg']} 100%
    );
    border: 2px solid {ctx['accent']};
}}"""

    inject_css(HYPRSWITCH_STYLE, block)


def apply_gtk4(ctx: dict):
    """
    Inyecta variables de color en gtk-4.0/gtk.css vía marcadores.
    Si el archivo es un symlink (p.ej. tema catppuccin instalado), lo rompe
    creando un archivo real que importa el original y luego override los colores.
    """
    GTK4_CSS.parent.mkdir(parents=True, exist_ok=True)
    # El tema base carga vía settings.ini/gtk-theme-name — el user stylesheet
    # solo necesita los color overrides sin @import.
    # Si es symlink o tiene @import (de una migración previa), lo reemplazamos limpio.
    if GTK4_CSS.is_symlink():
        GTK4_CSS.unlink()
        GTK4_CSS.write_text("/* GTK4 color overrides — gestionado por theme-changer */\n")
    elif not GTK4_CSS.exists():
        GTK4_CSS.write_text("/* GTK4 color overrides — gestionado por theme-changer */\n")
    elif GTK4_CSS.read_text().startswith("@import"):
        GTK4_CSS.write_text("/* GTK4 color overrides — gestionado por theme-changer */\n")
    block = f"""/* libadwaita */
@define-color accent_color                    {ctx['accent']};
@define-color accent_bg_color                 {ctx['accent']};
@define-color accent_fg_color                 {ctx['bg']};
@define-color window_bg_color                 {ctx['bg']};
@define-color window_fg_color                 {ctx['fg']};
@define-color view_bg_color                   {ctx['surface']};
@define-color view_fg_color                   {ctx['fg']};
@define-color headerbar_bg_color              {ctx['bg_alt']};
@define-color headerbar_fg_color              {ctx['fg']};
@define-color headerbar_backdrop_color        {ctx['bg']};
@define-color headerbar_border_color          {ctx['border_inactive']};
@define-color headerbar_shade_color           {ctx['shadow']};
@define-color headerbar_darker_shade_color    {ctx['shadow']};
@define-color sidebar_bg_color                {ctx['bg_alt']};
@define-color sidebar_fg_color                {ctx['fg']};
@define-color sidebar_backdrop_color          {ctx['bg']};
@define-color sidebar_border_color            {ctx['border_inactive']};
@define-color sidebar_shade_color             {ctx['shadow']};
@define-color secondary_sidebar_bg_color      {ctx['bg']};
@define-color secondary_sidebar_fg_color      {ctx['fg']};
@define-color secondary_sidebar_backdrop_color {ctx['bg']};
@define-color secondary_sidebar_border_color  {ctx['border_inactive']};
@define-color secondary_sidebar_shade_color   {ctx['shadow']};
@define-color card_bg_color                   {ctx['surface']};
@define-color card_fg_color                   {ctx['fg']};
@define-color card_shade_color                {ctx['shadow']};
@define-color popover_bg_color                {ctx['surface2']};
@define-color popover_fg_color                {ctx['fg']};
@define-color popover_shade_color             {ctx['shadow']};
@define-color dialog_bg_color                 {ctx['surface']};
@define-color dialog_fg_color                 {ctx['fg']};
@define-color thumbnail_bg_color              {ctx['surface2']};
@define-color thumbnail_fg_color              {ctx['fg']};
@define-color shade_color                     {ctx['shadow']};
@define-color scrollbar_outline_color         {ctx['shadow']};

/* GTK legacy */
@define-color theme_bg_color              {ctx['bg']};
@define-color theme_base_color            {ctx['surface']};
@define-color theme_fg_color              {ctx['fg']};
@define-color theme_text_color            {ctx['fg']};
@define-color theme_selected_bg_color     {ctx['accent']};
@define-color theme_selected_fg_color     {ctx['bg']};
@define-color theme_unfocused_bg_color    {ctx['bg']};
@define-color theme_unfocused_fg_color    {ctx['fg_dim']};
@define-color insensitive_fg_color        {ctx['fg_dim']};
@define-color borders                     {ctx['border_inactive']};
@define-color content_view_bg             {ctx['surface']};
@define-color error_color                 {ctx['red']};
@define-color success_color               {ctx['green']};
@define-color warning_color               {ctx['yellow']};"""

    inject_css(GTK4_CSS, block)

    # gtk-dark.css se carga encima de gtk.css cuando color-scheme=prefer-dark —
    # hay que romper el symlink e inyectar los mismos colores para que no los pise.
    if GTK4_DARK_CSS.is_symlink():
        GTK4_DARK_CSS.unlink()
        GTK4_DARK_CSS.write_text("/* GTK4 dark overrides — gestionado por theme-changer */\n")
    elif not GTK4_DARK_CSS.exists():
        GTK4_DARK_CSS.write_text("/* GTK4 dark overrides — gestionado por theme-changer */\n")
    elif GTK4_DARK_CSS.read_text().startswith("@import"):
        GTK4_DARK_CSS.write_text("/* GTK4 dark overrides — gestionado por theme-changer */\n")
    inject_css(GTK4_DARK_CSS, block)


def apply_gtk3(ctx: dict):
    """
    Cambia el tema GTK3 base a Adwaita (que sí referencia @define-color) e
    inyecta los color overrides en gtk-3.0/gtk.css.
    Catppuccin GTK3 usa hex hardcodeados — no sirve de base para theming dinámico.
    """
    GTK3_CSS.parent.mkdir(parents=True, exist_ok=True)

    # Cambiar gtk-theme-name a Adwaita en settings.ini
    if GTK3_SETTINGS.exists():
        cfg = configparser.ConfigParser()
        cfg.read(GTK3_SETTINGS)
        section = "Settings"
        if not cfg.has_section(section):
            cfg.add_section(section)
        cfg.set(section, "gtk-theme-name", "Adwaita")
        is_dark = ctx.get("variant", "dark") != "light"
        cfg.set(section, "gtk-application-prefer-dark-theme", "1" if is_dark else "0")
        with GTK3_SETTINGS.open("w") as f:
            cfg.write(f)

    if not GTK3_CSS.exists():
        GTK3_CSS.write_text("/* GTK3 color overrides — gestionado por theme-changer */\n")

    block = f"""@define-color theme_bg_color           {ctx['bg']};
@define-color theme_base_color         {ctx['surface']};
@define-color theme_fg_color           {ctx['fg']};
@define-color theme_text_color         {ctx['fg']};
@define-color theme_selected_bg_color  {ctx['accent']};
@define-color theme_selected_fg_color  {ctx['bg']};
@define-color theme_unfocused_bg_color {ctx['bg']};
@define-color theme_unfocused_fg_color {ctx['fg_dim']};
@define-color insensitive_bg_color     {ctx['surface']};
@define-color insensitive_fg_color     {ctx['fg_dim']};
@define-color insensitive_base_color   {ctx['surface']};
@define-color borders                  {ctx['border_inactive']};
@define-color warning_color            {ctx['yellow']};
@define-color error_color              {ctx['red']};
@define-color success_color            {ctx['green']};"""

    inject_css(GTK3_CSS, block)


def apply_qt6ct(ctx: dict):
    """
    Genera un esquema de color KDE (.colors) con los colores del tema
    y actualiza qt6ct.conf para usarlo. Reinicia Dolphin si está corriendo.
    """
    def rgb(key: str) -> str:
        r, g, b = hex_to_rgb(ctx[key])
        return f"{r},{g},{b}"

    scheme_name = "ThemeChanger"
    content = f"""[ColorEffects:Disabled]
Color=56,56,56
ColorAmount=0
ColorEffect=0
ContrastAmount=0.65
ContrastEffect=1
IntensityAmount=0.1
IntensityEffect=2

[ColorEffects:Inactive]
ChangeSelectionColor=true
Color=112,111,110
ColorAmount=0.025
ColorEffect=2
ContrastAmount=0.1
ContrastEffect=2
Enable=false
IntensityAmount=0
IntensityEffect=0

[Colors:Button]
BackgroundNormal={rgb('bg_alt')}
BackgroundAlternate={rgb('surface2')}
ForegroundNormal={rgb('fg')}
ForegroundInactive={rgb('fg_dim')}
ForegroundActive={rgb('accent')}
ForegroundLink={rgb('teal')}
ForegroundVisited={rgb('accent_alt')}
ForegroundNegative={rgb('red')}
ForegroundNeutral={rgb('yellow')}
ForegroundPositive={rgb('green')}
DecorationFocus={rgb('accent')}
DecorationHover={rgb('accent')}

[Colors:Selection]
BackgroundNormal={rgb('accent')}
BackgroundAlternate={rgb('accent_dim')}
ForegroundNormal={rgb('bg')}
ForegroundInactive={rgb('bg_alt')}
ForegroundActive={rgb('bg')}
ForegroundLink={rgb('teal')}
ForegroundVisited={rgb('accent_alt')}
ForegroundNegative={rgb('red')}
ForegroundNeutral={rgb('yellow')}
ForegroundPositive={rgb('green')}
DecorationFocus={rgb('accent')}
DecorationHover={rgb('accent')}

[Colors:Tooltip]
BackgroundNormal={rgb('surface2')}
BackgroundAlternate={rgb('surface')}
ForegroundNormal={rgb('fg')}
ForegroundInactive={rgb('fg_dim')}
ForegroundActive={rgb('accent')}
ForegroundLink={rgb('teal')}
ForegroundVisited={rgb('accent_alt')}
ForegroundNegative={rgb('red')}
ForegroundNeutral={rgb('yellow')}
ForegroundPositive={rgb('green')}
DecorationFocus={rgb('accent')}
DecorationHover={rgb('accent')}

[Colors:View]
BackgroundNormal={rgb('surface')}
BackgroundAlternate={rgb('bg_alt')}
ForegroundNormal={rgb('fg')}
ForegroundInactive={rgb('fg_dim')}
ForegroundActive={rgb('accent')}
ForegroundLink={rgb('teal')}
ForegroundVisited={rgb('accent_alt')}
ForegroundNegative={rgb('red')}
ForegroundNeutral={rgb('yellow')}
ForegroundPositive={rgb('green')}
DecorationFocus={rgb('accent')}
DecorationHover={rgb('accent')}

[Colors:Window]
BackgroundNormal={rgb('bg')}
BackgroundAlternate={rgb('bg_alt')}
ForegroundNormal={rgb('fg')}
ForegroundInactive={rgb('fg_dim')}
ForegroundActive={rgb('accent')}
ForegroundLink={rgb('teal')}
ForegroundVisited={rgb('accent_alt')}
ForegroundNegative={rgb('red')}
ForegroundNeutral={rgb('yellow')}
ForegroundPositive={rgb('green')}
DecorationFocus={rgb('accent')}
DecorationHover={rgb('accent')}

[Colors:Complementary]
BackgroundNormal={rgb('surface2')}
BackgroundAlternate={rgb('surface')}
ForegroundNormal={rgb('fg')}
ForegroundInactive={rgb('fg_dim')}
ForegroundActive={rgb('accent')}
ForegroundLink={rgb('teal')}
ForegroundVisited={rgb('accent_alt')}
ForegroundNegative={rgb('red')}
ForegroundNeutral={rgb('yellow')}
ForegroundPositive={rgb('green')}
DecorationFocus={rgb('accent')}
DecorationHover={rgb('accent')}

[General]
ColorScheme={scheme_name}
Name={scheme_name}
shadeSortColumn=true

[KDE]
contrast=4

[WM]
activeBackground={rgb('bg_alt')}
activeBlend={rgb('bg_alt')}
activeForeground={rgb('fg')}
inactiveBackground={rgb('bg')}
inactiveBlend={rgb('bg')}
inactiveForeground={rgb('fg_dim')}
"""
    QT_COLOR_SCHEME.parent.mkdir(parents=True, exist_ok=True)
    QT_COLOR_SCHEME.write_text(content)

    # Actualizar qt6ct.conf preservando el formato exacto (sin espacios en key=value)
    if QT6CT_CONF.exists():
        text = QT6CT_CONF.read_text()
        text = re.sub(r'(?m)^color_scheme_path\s*=.*$',
                      f'color_scheme_path={QT_COLOR_SCHEME}', text)
        text = re.sub(r'(?m)^custom_palette\s*=.*$',
                      'custom_palette=true', text)
        # Si no existían las claves, insertarlas en [Appearance]
        if 'color_scheme_path' not in text:
            text = text.replace('[Appearance]',
                                f'[Appearance]\ncolor_scheme_path={QT_COLOR_SCHEME}\ncustom_palette=true')
        QT6CT_CONF.write_text(text)

    # Reiniciar Dolphin si está corriendo
    if subprocess.run(["pgrep", "-x", "dolphin"], capture_output=True).returncode == 0:
        subprocess.run(["pkill", "-x", "dolphin"], capture_output=True)
        subprocess.Popen(["dolphin"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def apply_qt5ct(ctx: dict):
    """
    Genera un esquema de color en formato qt5ct y lo activa en qt5ct.conf.
    Qt5ct usa 21 roles QPalette como #AARRGGBB separados por comas.
    """
    def argb(key: str, alpha: int = 0xff) -> str:
        r, g, b = hex_to_rgb(ctx[key])
        return f"#{alpha:02x}{r:02x}{g:02x}{b:02x}"

    # 21 roles QPalette en orden:
    # WindowText, Button, Light, Midlight, Dark, Mid, Text, BrightText,
    # ButtonText, Base, Window, Shadow, Highlight, HighlightedText,
    # Link, LinkVisited, AlternateBase, NoRole, ToolTipBase, ToolTipText,
    # PlaceholderText
    active = [
        argb('fg'),           # 0  WindowText
        argb('bg_alt'),       # 1  Button
        argb('surface2'),     # 2  Light
        argb('surface2'),     # 3  Midlight
        argb('bg'),           # 4  Dark
        argb('surface'),      # 5  Mid
        argb('fg'),           # 6  Text
        argb('fg'),           # 7  BrightText
        argb('fg'),           # 8  ButtonText
        argb('surface'),      # 9  Base
        argb('bg'),           # 10 Window
        argb('shadow'),       # 11 Shadow
        argb('accent'),       # 12 Highlight
        argb('bg'),           # 13 HighlightedText
        argb('teal'),         # 14 Link
        argb('accent_alt'),   # 15 LinkVisited
        argb('bg_alt'),       # 16 AlternateBase
        argb('bg'),           # 17 NoRole
        argb('surface2'),     # 18 ToolTipBase
        argb('fg'),           # 19 ToolTipText
        argb('fg_dim', 0x80), # 20 PlaceholderText
    ]
    disabled = [
        argb('fg_dim'),       # 0  WindowText
        argb('bg_alt'),       # 1  Button
        argb('surface2'),     # 2  Light
        argb('surface2'),     # 3  Midlight
        argb('bg'),           # 4  Dark
        argb('surface'),      # 5  Mid
        argb('fg_dim'),       # 6  Text
        argb('fg_dim'),       # 7  BrightText
        argb('fg_dim'),       # 8  ButtonText
        argb('surface'),      # 9  Base
        argb('bg'),           # 10 Window
        argb('shadow'),       # 11 Shadow
        argb('surface2'),     # 12 Highlight
        argb('fg_dim'),       # 13 HighlightedText
        argb('teal'),         # 14 Link
        argb('accent_alt'),   # 15 LinkVisited
        argb('bg_alt'),       # 16 AlternateBase
        argb('bg'),           # 17 NoRole
        argb('surface2'),     # 18 ToolTipBase
        argb('fg_dim'),       # 19 ToolTipText
        argb('fg_dim', 0x60), # 20 PlaceholderText
    ]

    def row(roles): return ", ".join(roles)

    content = f"[ColorScheme]\nactive_colors={row(active)}\ndisabled_colors={row(disabled)}\ninactive_colors={row(active)}\n"

    QT5CT_COLORS.parent.mkdir(parents=True, exist_ok=True)
    QT5CT_COLORS.write_text(content)

    if QT5CT_CONF.exists():
        text = QT5CT_CONF.read_text()
        text = re.sub(r'(?m)^custom_palette\s*=.*$', 'custom_palette=true', text)
        text = re.sub(r'(?m)^color_scheme_path\s*=.*$',
                      f'color_scheme_path={QT5CT_COLORS}', text)
        if 'color_scheme_path' not in text:
            text = text.replace('[Appearance]',
                                f'[Appearance]\ncolor_scheme_path={QT5CT_COLORS}\ncustom_palette=true')
        QT5CT_CONF.write_text(text)


def apply_kdeglobals(ctx: dict):
    """
    Actualiza ~/.config/kdeglobals con los colores del tema.
    KDE apps (Dolphin, etc.) leen paleta de colores desde este archivo.
    """
    def rgb(key: str) -> str:
        r, g, b = hex_to_rgb(ctx[key])
        return f"{r},{g},{b}"

    if not KDEGLOBALS.exists():
        return

    # Reemplazar secciones de color en kdeglobals preservando el resto
    text = KDEGLOBALS.read_text()

    new_sections = {
        "Colors:Button": {
            "BackgroundNormal":    rgb('bg_alt'),
            "BackgroundAlternate": rgb('surface2'),
            "ForegroundNormal":    rgb('fg'),
            "ForegroundInactive":  rgb('fg_dim'),
            "ForegroundActive":    rgb('accent'),
            "ForegroundLink":      rgb('teal'),
            "ForegroundVisited":   rgb('accent_alt'),
            "ForegroundNegative":  rgb('red'),
            "ForegroundNeutral":   rgb('yellow'),
            "ForegroundPositive":  rgb('green'),
            "DecorationFocus":     rgb('accent'),
            "DecorationHover":     rgb('accent'),
        },
        "Colors:Selection": {
            "BackgroundNormal":    rgb('accent'),
            "BackgroundAlternate": rgb('accent_dim'),
            "ForegroundNormal":    rgb('bg'),
            "ForegroundInactive":  rgb('bg_alt'),
            "ForegroundActive":    rgb('bg'),
            "ForegroundLink":      rgb('teal'),
            "ForegroundVisited":   rgb('accent_alt'),
            "ForegroundNegative":  rgb('red'),
            "ForegroundNeutral":   rgb('yellow'),
            "ForegroundPositive":  rgb('green'),
            "DecorationFocus":     rgb('accent'),
            "DecorationHover":     rgb('accent'),
        },
        "Colors:Tooltip": {
            "BackgroundNormal":    rgb('surface2'),
            "ForegroundNormal":    rgb('fg'),
            "DecorationFocus":     rgb('accent'),
            "DecorationHover":     rgb('accent'),
        },
        "Colors:View": {
            "BackgroundNormal":    rgb('surface'),
            "BackgroundAlternate": rgb('bg_alt'),
            "ForegroundNormal":    rgb('fg'),
            "ForegroundInactive":  rgb('fg_dim'),
            "ForegroundActive":    rgb('accent'),
            "ForegroundLink":      rgb('teal'),
            "ForegroundVisited":   rgb('accent_alt'),
            "ForegroundNegative":  rgb('red'),
            "ForegroundNeutral":   rgb('yellow'),
            "ForegroundPositive":  rgb('green'),
            "DecorationFocus":     rgb('accent'),
            "DecorationHover":     rgb('accent'),
        },
        "Colors:Window": {
            "BackgroundNormal":    rgb('bg'),
            "BackgroundAlternate": rgb('bg_alt'),
            "ForegroundNormal":    rgb('fg'),
            "ForegroundInactive":  rgb('fg_dim'),
            "ForegroundActive":    rgb('accent'),
            "ForegroundLink":      rgb('teal'),
            "ForegroundVisited":   rgb('accent_alt'),
            "ForegroundNegative":  rgb('red'),
            "ForegroundNeutral":   rgb('yellow'),
            "ForegroundPositive":  rgb('green'),
            "DecorationFocus":     rgb('accent'),
            "DecorationHover":     rgb('accent'),
        },
        "WM": {
            "activeBackground":   rgb('bg_alt'),
            "activeBlend":        rgb('bg_alt'),
            "activeForeground":   rgb('fg'),
            "inactiveBackground": rgb('bg'),
            "inactiveBlend":      rgb('bg'),
            "inactiveForeground": rgb('fg_dim'),
        },
    }

    for section, keys in new_sections.items():
        section_pattern = re.compile(
            r'(\[' + re.escape(section) + r'\]\n)(.*?)(?=\n\[|\Z)',
            re.DOTALL
        )
        new_block = f"[{section}]\n" + "\n".join(f"{k}={v}" for k, v in keys.items()) + "\n"
        if section_pattern.search(text):
            text = section_pattern.sub(new_block, text)
        else:
            text += f"\n{new_block}"

    # Actualizar ColorScheme en [General] para que apps KDE lo tomen automáticamente
    text = re.sub(r'(?m)^ColorScheme\s*=.*$', 'ColorScheme=ThemeChanger', text)
    if 'ColorScheme=' not in text:
        text = re.sub(r'(?m)^(\[General\])', r'\1\nColorScheme=ThemeChanger', text)

    KDEGLOBALS.write_text(text)

    # Parchar apps KDE que sobreescriben ColorScheme en su propio rc
    for rc_file in list(CFG.glob("*.rc")) + list(CFG.glob("*rc")):
        try:
            rc_text = rc_file.read_text()
            if 'ColorScheme=' in rc_text:
                rc_text = re.sub(r'(?m)^ColorScheme\s*=.*$', 'ColorScheme=ThemeChanger', rc_text)
                rc_file.write_text(rc_text)
        except Exception:
            pass


def apply_kvantum(ctx: dict):
    """
    Crea un tema Kvantum personalizado con los colores del tema activo.
    Copia el SVG del tema base (catppuccin) para preservar las formas de widgets
    y sobreescribe [GeneralColors] con nuestros colores.
    """
    KVANTUM_THEME_DIR.mkdir(parents=True, exist_ok=True)

    # Buscar el SVG base (siempre catppuccin-mocha-blue para preservar las formas)
    # El SVG se re-copia y re-parchea en cada apply para actualizar colores.
    svg_dst = KVANTUM_THEME_DIR / "ThemeChanger.svg"
    svg_src = Path("/usr/share/Kvantum/catppuccin-mocha-blue/catppuccin-mocha-blue.svg")
    if not svg_src.exists():
        for fallback in Path("/usr/share/Kvantum").glob("catppuccin-mocha-*/"):
            candidate = fallback / f"{fallback.name}.svg"
            if candidate.exists():
                svg_src = candidate
                break

    current_kv_theme = "catppuccin-mocha-blue"

    if svg_src.exists():
        svg_text = svg_src.read_text()
        # Mapeo catppuccin-mocha → colores del tema activo (case-insensitive)
        catppuccin_map = {
            "#1E1E2E": ctx['bg'],          # Base (window bg)
            "#181825": ctx['bg'],          # Mantle (darker bg)
            "#313244": ctx['surface'],     # Surface0
            "#45475A": ctx['surface2'],    # Surface1
            "#585B70": ctx['overlay'],     # Surface2/Overlay
            "#6C7086": ctx['overlay'],     # Overlay0
            "#89B4FA": ctx['accent'],      # Blue (accent)
            "#CDD6F4": ctx['fg'],          # Text
            "#A6ADC8": ctx['fg_dim'],      # Subtext1
            "#7EA5E6": ctx['accent_alt'],  # Lighter accent
            "#CBA6F7": ctx['mauve'],       # Mauve
            "#F38BA8": ctx['red'],         # Red
            "#141414": ctx['shadow'],      # Very dark shadow
            "#31363b": ctx['bg_alt'],      # Dark surface (mixed)
        }
        for src_color, dst_color in catppuccin_map.items():
            svg_text = svg_text.replace(src_color, dst_color.upper())
            svg_text = svg_text.replace(src_color.lower(), dst_color.upper())
        svg_dst.write_text(svg_text)

    # Leer el kvconfig base para preservar todas las opciones de estilo
    base_kv = Path(f"/usr/share/Kvantum/{current_kv_theme}/{current_kv_theme}.kvconfig")
    if base_kv.exists():
        base_content = base_kv.read_text()
        # Eliminar [GeneralColors] existente si hay
        base_content = re.sub(r'\[GeneralColors\].*?(?=\[|\Z)', '', base_content, flags=re.DOTALL)
    else:
        base_content = "[%General]\ncomposite=true\n"

    def hx(key: str) -> str:
        return ctx[key].upper()

    colors_block = f"""[GeneralColors]
window.color={hx('bg')}
base.color={hx('surface')}
alt.base.color={hx('bg_alt')}
button.color={hx('bg_alt')}
light.color={hx('surface2')}
mid.light.color={hx('surface2')}
dark.color={hx('bg')}
mid.color={hx('surface')}
highlight.color={hx('accent')}
inactive.highlight.color={hx('surface2')}
tooltip.base.color={hx('surface2')}
text.color={hx('fg')}
window.text.color={hx('fg')}
button.text.color={hx('fg')}
disabled.text.color={hx('fg_dim')}
tooltip.text.color={hx('fg')}
highlight.text.color={hx('bg')}
link.color={hx('teal')}
link.visited.color={hx('accent_alt')}
text.press.color={hx('fg')}
text.toggle.color={hx('fg')}
text.normal.color={hx('fg')}
text.focus.color={hx('accent')}
"""

    KVANTUM_THEME_KV.write_text(base_content.rstrip() + "\n\n" + colors_block)

    # Activar el tema ThemeChanger en kvantum.kvconfig
    if KVANTUM_CONF.exists():
        kv_text = KVANTUM_CONF.read_text()
        kv_text = re.sub(r'(?m)^theme\s*=.*$', 'theme=ThemeChanger', kv_text)
        if 'theme=' not in kv_text:
            kv_text = kv_text.replace('[General]', '[General]\ntheme=ThemeChanger')
        KVANTUM_CONF.write_text(kv_text)

    # Reiniciar Dolphin si está corriendo
    if subprocess.run(["pgrep", "-x", "dolphin"], capture_output=True).returncode == 0:
        subprocess.run(["pkill", "-x", "dolphin"], capture_output=True)
        subprocess.Popen(["dolphin"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def apply_wallpaper_sh(wallpaper: str):
    """Actualiza la ruta de imagen en wallpaper.sh manteniendo el resto intacto."""
    if not WALLPAPER_SH.exists():
        return
    content = WALLPAPER_SH.read_text()
    new_content = re.sub(
        r'(awww img\s+")[^"]*(")',
        rf'\g<1>{wallpaper}\g<2>',
        content
    )
    if new_content != content:
        WALLPAPER_SH.write_text(new_content)
        print(f"  [wallpaper.sh] → {wallpaper}")

def apply_swww(wallpaper: str):
    """Establece wallpaper con awww y genera versión difuminada para wlogout."""
    # Asegurar que el daemon está corriendo
    subprocess.run(["awww-daemon", "--daemon"], capture_output=True)

    subprocess.run([
        "awww", "img", wallpaper,
        "--transition-type",     "wipe",
        "--transition-angle",    "29",
        "--transition-duration", "0.75",
        "--transition-bezier",   ".43,1.19,1,.4",
    ], capture_output=True)

    # Generar wallpaper difuminado para wlogout/hyprlock
    blurred_dir = HOME / ".cache" / "wlogout"
    blurred_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "magick", wallpaper,
        "-blur", "0x20",
        str(blurred_dir / "blurred_wallpaper.png"),
    ], capture_output=True)

# ── Estado ─────────────────────────────────────────────────────────────────────

def save_state(theme: str, wallpaper: str | None = None):
    STATE_FILE.write_text(json.dumps({"theme": theme, "wallpaper": wallpaper}, indent=2))

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"theme": None, "wallpaper": None}

# ── Modo dinámico (matugen) ────────────────────────────────────────────────────

def apply_dynamic(wallpaper: str, variant: str = "dark"):
    """
    Genera paleta de colores desde un wallpaper usando Matugen
    y aplica el tema resultante.
    variant: 'dark' o 'light'
    """
    theme_name  = f"dynamic-{variant}"
    dynamic_dir = THEMES_DIR / theme_name
    dynamic_dir.mkdir(exist_ok=True)

    label = "Dark" if variant == "dark" else "Light"
    print(f"  [matugen] Generando paleta {label} desde: {wallpaper}")
    result = subprocess.run(
        ["matugen", "image", wallpaper, "-m", variant, "-t", "scheme-tonal-spot",
         "--json", "hex", "--prefer", "saturation"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(f"Error matugen: {result.stderr}")

    # Matugen 4.x retorna JSON donde cada rol tiene sub-objetos {dark, default, light}
    # Estructura: colors.<rol>.default.color  (no colors.dark.<rol>)
    raw_colors = json.loads(result.stdout).get("colors", {})

    def c(key: str, fallback: str) -> str:
        entry = raw_colors.get(key, {})
        # Para light usamos la sub-clave "light", para dark usamos "default"
        sub = "light" if variant == "light" else "default"
        return entry.get(sub, entry.get("dark", {})).get("color", fallback)

    if variant == "dark":
        # Mapeo validado contra colors.json.tpl de referencia (dark)
        mapped = {
            "bg":              c("surface",                   "#11140e"),
            "bg_alt":          c("surface_variant",           "#43483e"),
            "surface":         c("surface_container",         "#1d211a"),
            "surface2":        c("surface_container_high",    "#282b24"),
            "surface3":        c("surface_container_highest", "#33362f"),
            "overlay":         c("surface_container_highest", "#33362f"),
            "fg":              c("on_surface",                "#e1e4d9"),
            "fg_dim":          c("on_surface_variant",        "#c4c8bb"),
            "accent":          c("primary",                   "#abd290"),
            "accent_alt":      c("secondary",                 "#bdcbaf"),
            "accent_dim":      c("primary_container",         "#2e4f1b"),
            "red":             c("error",                     "#ffb4ab"),
            "orange":          c("tertiary_container",        "#1e4e4e"),
            "yellow":          c("secondary_container",       "#3e4a35"),
            "green":           c("tertiary",                  "#a0cfcf"),
            "teal":            c("primary_container",         "#2e4f1b"),
            "teal_dim":        c("on_primary_fixed_variant",  "#2e4f1b"),
            "blue":            c("primary",                   "#abd290"),
            "sky":             c("secondary_fixed_dim",       "#bdcbaf"),
            "mauve":           c("tertiary_fixed_dim",        "#a0cfcf"),
            "pink":            c("error_container",           "#93000a"),
            "lavender":        c("secondary_fixed",           "#d9e7ca"),
            "border_active":   c("primary",                   "#abd290"),
            "border_inactive": c("surface_variant",           "#43483e"),
            "shadow":          c("shadow",                    "#000000"),
        }
    else:
        # Mapeo light: mismos roles, sub-clave "light"
        mapped = {
            "bg":              c("surface",                   "#f8faf0"),
            "bg_alt":          c("surface_variant",           "#dde4d8"),
            "surface":         c("surface_container",         "#edf0e8"),
            "surface2":        c("surface_container_high",    "#e7ebe2"),
            "surface3":        c("surface_container_highest", "#e1e4db"),
            "overlay":         c("surface_container_highest", "#e1e4db"),
            "fg":              c("on_surface",                "#191d17"),
            "fg_dim":          c("on_surface_variant",        "#43483e"),
            "accent":          c("primary",                   "#386a20"),
            "accent_alt":      c("secondary",                 "#55624c"),
            "accent_dim":      c("primary_container",         "#b5f181"),
            "red":             c("error",                     "#ba1a1a"),
            "orange":          c("tertiary_container",        "#cceaea"),
            "yellow":          c("secondary_container",       "#d8e8ca"),
            "green":           c("tertiary",                  "#386666"),
            "teal":            c("primary_container",         "#b5f181"),
            "teal_dim":        c("on_primary_fixed_variant",  "#1f5004"),
            "blue":            c("primary",                   "#386a20"),
            "sky":             c("secondary_fixed_dim",       "#b8ccaa"),
            "mauve":           c("tertiary_fixed_dim",        "#9cd2d2"),
            "pink":            c("error_container",           "#ffdad6"),
            "lavender":        c("secondary_fixed",           "#d4e8c5"),
            "border_active":   c("primary",                   "#386a20"),
            "border_inactive": c("surface_variant",           "#dde4d8"),
            "shadow":          c("shadow",                    "#000000"),
        }

    out = {
        "meta": {
            "name":         theme_name,
            "display_name": f"Dynamic {label}",
            "variant":      variant,
        },
        "colors": mapped,
    }
    (dynamic_dir / "colors.json").write_text(json.dumps(out, indent=2))

    apply_theme(theme_name, wallpaper)  # backup se hace aquí al inicio
    apply_wallpaper_sh(wallpaper)       # modifica después del backup

ROFI_PICKER_BG = CFG / "rofi" / "images" / "picker-bg.jpg"

def apply_rofi_banner(theme_name: str, wallpaper: str | None = None):
    """
    Actualiza la imagen de banner del rofi-picker con el wallpaper del tema.
    Prioridad: 1) wallpaper dinámico aplicado  2) wallpaper del tema  3) swww actual
    """
    ROFI_PICKER_BG.parent.mkdir(parents=True, exist_ok=True)

    src = None

    # 1. Wallpaper dinámico (pasado como argumento)
    if wallpaper and Path(wallpaper).exists():
        src = Path(wallpaper)

    # 2. Wallpaper predeterminado del tema (themes/{name}/wallpaper.jpg)
    if not src:
        for ext in ("jpg", "png", "jpeg", "webp"):
            candidate = THEMES_DIR / theme_name / f"wallpaper.{ext}"
            if candidate.exists():
                src = candidate
                break

    # 3. Wallpaper activo en awww
    if not src:
        try:
            result = subprocess.run(
                ["awww", "query"], capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if "image:" in line:
                    path_str = line.split("image:")[-1].strip()
                    candidate = Path(path_str)
                    if candidate.exists():
                        src = candidate
                        break
        except Exception:
            pass

    if not src:
        return

    # Redimensionar a formato banner 700×220
    try:
        subprocess.run(
            ["magick", str(src),
             "-resize", "700x220^",
             "-gravity", "Center",
             "-extent", "700x220",
             "-quality", "88",
             str(ROFI_PICKER_BG)],
            capture_output=True
        )
    except Exception as e:
        print(f"  [warn] banner rofi: {e}")


# ── Apply principal ────────────────────────────────────────────────────────────

def apply_theme(theme_name: str, wallpaper: str | None = None):
    print(f"\nAplicando tema: {theme_name}")

    backup_original()
    backup_timestamped()

    colors, variant = read_theme(theme_name)
    ctx = build_context(colors)

    steps = [
        ("kitty",    lambda: apply_kitty(ctx)),
        ("waybar",   lambda: apply_waybar(ctx)),
        ("swaync",   lambda: apply_swaync(ctx)),
        ("hyprland", lambda: apply_hyprland(ctx)),
        ("hyprlock", lambda: apply_hyprlock(ctx)),
        ("rofi",     lambda: apply_rofi(ctx)),
        ("eww",      lambda: apply_eww(ctx, variant)),
        ("wlogout",  lambda: apply_wlogout(ctx)),
        ("vsfetch",  lambda: apply_vsfetch(ctx)),
        ("hyprswitch", lambda: apply_hyprswitch(ctx)),
        ("gtk4",       lambda: apply_gtk4(ctx)),
        ("gtk3",       lambda: apply_gtk3(ctx)),
        ("qt6ct",      lambda: apply_qt6ct(ctx)),
        ("qt5ct",      lambda: apply_qt5ct(ctx)),
        ("kdeglobals", lambda: apply_kdeglobals(ctx)),
        ("kvantum",    lambda: apply_kvantum(ctx)),
    ]

    for name, fn in steps:
        print(f"  → {name}")
        try:
            fn()
        except Exception as e:
            print(f"  [error] {name}: {e}")

    if wallpaper:
        print(f"  → awww")
        apply_swww(wallpaper)

    # Actualizar banner del rofi picker con el wallpaper del tema
    apply_rofi_banner(theme_name, wallpaper)

    save_state(theme_name, wallpaper)

    # Fijar el tema GTK base a Adwaita para que @define-color del user CSS funcione
    # en apps GTK3 (catppuccin GTK3 hardcodea hex — no referencia @define-color).
    # Apps GTK4/libadwaita no dependen del tema base, usan el user CSS directamente.
    try:
        is_dark = ctx.get("variant", "dark") != "light"
        subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "gtk-theme", "Adwaita"], capture_output=True)
        subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme",
                        "prefer-dark" if is_dark else "prefer-light"], capture_output=True)
    except Exception:
        pass

    # Reiniciar Nautilus si está corriendo (libadwaita no recarga CSS en caliente)
    nautilus_running = subprocess.run(["pgrep", "-x", "nautilus"], capture_output=True).returncode == 0
    if nautilus_running:
        subprocess.run(["nautilus", "-q"], capture_output=True)
        subprocess.Popen(["nautilus", "--no-desktop"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    print(f"\nTema '{theme_name}' aplicado correctamente.\n")

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso:")
        print("  vshypr-theme-manager.py <tema>                  Aplica un tema")
        print("  vshypr-theme-manager.py <tema> <wallpaper>      Aplica tema + wallpaper")
        print("  vshypr-theme-manager.py dynamic-dark  <wallpaper>  Genera paleta oscura con matugen")
        print("  vshypr-theme-manager.py dynamic-light <wallpaper>  Genera paleta clara con matugen")
        print("  vshypr-theme-manager.py --list                  Lista temas disponibles")
        sys.exit(0)

    if sys.argv[1] == "--list":
        for t in list_themes():
            state = load_state()
            marker = " ◆" if t == state.get("theme") else ""
            print(f"  {t}{marker}")
        return

    theme = sys.argv[1]
    wp    = sys.argv[2] if len(sys.argv) > 2 else None

    if theme in ("dynamic-dark", "dynamic-light"):
        if not wp:
            sys.exit(f"Error: modo {theme} requiere ruta del wallpaper")
        variant = theme.split("-")[1]
        apply_dynamic(wp, variant)
    else:
        apply_theme(theme, wp)


if __name__ == "__main__":
    main()
