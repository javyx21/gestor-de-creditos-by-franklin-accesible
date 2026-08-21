# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Gestor de Crédito — Windows desktop app for a Dominican financiera that grants credit only to
employees ("colaboradores") of partner companies ("empresas convenio"). Tracks each credit case
from presolicitud through disbursement, using a case log ("bitácora") periodically exported from
MIDESA (Excel) plus day-to-day manual follow-up in the app.

**Primary constraint: the UI must be fully usable with NVDA and meet WCAG 2.2.** This is why
wxPython was chosen over other GUI toolkits, and it must inform every UI decision. Two hard rules:

- **No popups, ever**, with one narrow exception: `wx.MessageBox` for transient outcomes that need
  immediate screen-reader attention and have no other reliable way to get it (e.g. empty/invalid
  search, validation errors, import results, delete/mark confirmations naming the exact record).
  Reason: `SetStatusText`/`SetLabel` changes are **not** proactively announced by NVDA — the user
  has to manually check them. Don't add a MessageBox for routine success feedback that isn't the
  sole indication of an otherwise-silent outcome (that stays on the status bar/inline label) — ask
  "would NVDA hear anything at all if this weren't a popup?" before defaulting to one. Native OS
  dialogs (`wx.FileDialog`) are exempt from this rule — they're already screen-reader accessible.
- **The Franklin Accesible logo appears on every tab/dialog**, small, unobtrusive, with this exact
  accessible name: "Logo de Franklin Accesible: figura humana azul en movimiento, atravesando una
  barrera fragmentada de color naranja y amarillo." Never set via `SetToolTip()` (draws a visible
  balloon) — only via the accessible-name mechanism (see Accessibility section).

## Domain model

Two entities, both driven by the MIDESA Excel bitácora import:

- **Cliente** — a person, identified by `cedula` (the only durable natural key). Can have many
  casos over their lifetime; never merge/overwrite on a new caso.
- **Caso** — belongs to one cliente. Identity = `cliente` + `clave_caso` (`COALESCE(no_presolicitud,
  id_caso)`), which is what decides "already imported" vs. "new row" during import.

Schema (`gestor_credito/db/database.py`, `SCHEMA`):

```sql
cliente(id, cedula UNIQUE, nombre, telefono,
        documentos_completos_fecha,   -- NULL = Alerta 1 still active
        fecha_creacion, fecha_actualizacion)

caso(id, cliente_id -> cliente.id,
     id_caso, no_presolicitud, clave_caso,   -- clave_caso = COALESCE(no_presolicitud, id_caso)
     fecha_registro, canal_origen, ejecutivo, empresa_convenio, monto_solicitado,
     destino_credito, microseguro, estado_solicitud, etapa_proceso, responsable_actual,
     fecha_ultima_gestion, proxima_gestion, dias_en_gestion, alerta_seguimiento,
     requiere_siaf, fecha_envio_siaf, fecha_decision, decision, motivo_no_aplica, observaciones,
     constancia_solicitada,               -- informational, raw value from Excel, not a date
     estado_solicitud_fecha_cambio,      -- since when estado_solicitud holds its current value
     constancia_recibida_fecha,          -- set only by the importer, historical/informational only
     origen_ultima_modificacion, fecha_creacion_registro, fecha_actualizacion_registro,
     UNIQUE(cliente_id, clave_caso))

configuracion(clave PRIMARY KEY, valor)   -- e.g. ('ejecutivo_actual', 'fmartinez')

convenio_tasa(empresa_convenio PRIMARY KEY, tasa_interes REAL, fecha_actualizacion)
calculo_credito(id, caso_id UNIQUE REFERENCES caso(id), empresa_convenio, tasa_interes,
                fecha_ingreso_empresa, salario_bruto_cordobas, ingresos_extra_cordobas,
                monto_credito_usd, plazo_meses, periodicidad, tipo_cambio, deuda_activa_cordobas,
                pasivo_laboral_cordobas, salario_neto_cordobas, cuota_usd,
                cobertura_pasivo_laboral, nivel_endeudamiento, fecha_calculo)
                -- currently unused: the Calculadora panel's save/link feature was removed (see
                -- below); table + db/calculo_credito.py still exist, untouched, nothing writes here

reporte_credito(id, no_credito TEXT NOT NULL UNIQUE, cedula TEXT NOT NULL,
                 nombre_cliente TEXT NOT NULL, fecha_desembolso, fecha_vencimiento,
                 monto_desembolsado REAL, estado_credito, empresa_convenio,
                 plazo_credito INTEGER,       -- MONTHS, not installment count
                 numero_cuotas INTEGER,       -- total installments (nullable pre-2026-08-16 rows)
                 cuotas_pagadas INTEGER,
                 saldo_principal REAL, saldo_intereses REAL,  -- feed-only, see below, no own list column
                 estado_credito_fecha_cambio TEXT NOT NULL, fecha_actualizacion_registro)
```

Design notes baked into this schema — flag to the user if any turn out wrong, they're inferred
from the business description, not spelled out column by column:

- `nombre`/`telefono` live only on `cliente` — the import just updates `cliente` from the latest
  row seen, doesn't duplicate them per caso.
- `dias_en_gestion` is stored as imported (historical); a "live" days-pending in the UI should be
  computed from `fecha_ultima_gestion` at query time.
- **Dating rule**: business dates the Excel actually provides (fecha_registro, etc.) always come
  from Excel's own columns, never import time. System-detected transitions the Excel doesn't state
  directly (`estado_solicitud_fecha_cambio`, `constancia_recibida_fecha`) are stamped with system
  time at the moment the app detects them.
- `estado_solicitud_fecha_cambio` inits to "now" on first insert, resets to "now" on every value
  change (import or manual) — never recalculated by a reimport that doesn't actually change the
  value. A case already sitting in a state for days before its first import into this app
  under-counts how long it's been waiting; confirmed acceptable (no Excel column for prior history).
  **This general rule applies identically to `caso.estado_solicitud_fecha_cambio`,
  `cliente.fecha_creacion` (Alerta 1), and `reporte_credito.estado_credito_fecha_cambio`.**

## Reference template files (git-ignored, real pilot data — never touch/expose, see memory)

- `MachoteBaseDeDatos.xlsx` — MIDESA bitácora structure reference. `01_Bitacora_Piloto` has messy
  real headers (embedded newlines, `(Manual)`/`(Auto)` suffixes baked into header text;
  `_normalize_header()` strips this before matching `COLUMN_ALIASES`). `02_Catalogos` lists the
  real fixed values (Estado Solicitud, Etapa Proceso, Responsable Actual, Microseguro, Decisión,
  Requiere SIAF, Canal/Origen — only Estado Solicitud/Etapa Proceso are modeled in `catalogos.py`
  so far). `"No. PRESOLICITUD"` can come through as a raw number, not a string.
  - **Estado Solicitud**: En espera de constancia, En proceso, Desembolsada, No aplica, Cliente
    desistió, Pendiente de información, Devuelta para corrección.
  - **Etapa Proceso**: Pre-solicitud, Completar expediente / requisitos, Solicitud formal,
    Aprobación, Formalización, Desembolso, Cierre.
- `recursos/calculadora.xlsx` — Calculadora de Crédito formula reference.
- `recursos/reporte.xlsx` — Historial de Créditos import reference.

## Import behavior (Excel bitácora) — `importer/excel_importer.py`, `import_bitacora()`

Cell *values* (e.g. `estado_solicitud`) are taken verbatim, never normalized — MIDESA's text
including accents/capitalization is exact and stable. Every non-date/int/float field is coerced to
`str` in `_row_to_dict()` (guards the raw-number `No. Presolicitud` case above). File is always
picked manually; filename is irrelevant. Match on (`cliente.cedula`, `caso.clave_caso`):

- No match → insert new cliente (if cédula is new) and new caso; `estado_solicitud_fecha_cambio`
  set to "now".
- Match found → **update** existing caso from the row (Excel is source of truth on every reimport).
  Before overwriting `estado_solicitud`: if it changed at all, reset
  `estado_solicitud_fecha_cambio` to "now". If old value was `ESTADO_EN_ESPERA_CONSTANCIA` **and**
  new value is specifically `ESTADO_EN_PROCESO`, additionally stamp `constancia_recibida_fecha` =
  now (historical/informational only — nothing queries it for alerting, see Alerts below).

All Excel-provided case dates come from Excel's own columns, never import time.

## Manual editing vs. reimport

User edits `estado_solicitud`/`etapa_proceso` directly in the app. Manual edits are authoritative
until the next reimport brings a newer value from MIDESA, at which point Excel wins.
`origen_ultima_modificacion` records which side made the last change. A manual edit to
`estado_solicitud` also resets `estado_solicitud_fecha_cambio` to "now".

## Configuración (agente actual)

`configuracion_panel.py` sets the user's own agent name into `configuracion('ejecutivo_actual', ...)`
(`db/configuracion.py`, `CLAVE_EJECUTIVO_ACTUAL`) — a single global setting. Agent picker is a
closed `wx.Choice` populated from `obtener_ejecutivos()` (editable combo box and plain textbox were
tried first and rejected — see Judgment calls below) + "Guardar y usar este agente" button. Scopes:

- **Casos tab default view**: empty search box → only casos with matching `ejecutivo`. A specific
  cédula/nombre search overrides this and searches across all agents.
- **Alertas 1 & 2**: only surface cases/clientes whose `caso.ejecutivo` matches. For Alerta 1
  (client-level), match via the ejecutivo of the caso that introduced that cliente.

Excel import UI (both bitácora and reporte de créditos) also lives on this tab — one-time/infrequent
setup, unlike the daily-use Casos tab.

## Alerts / workflow — `db/alertas.py` (pure queries) + `ui/notificaciones_panel.py`

Three alerts, scoped to `ejecutivo_actual`, computed **live** on each refresh — never stored as
rows. Time thresholds use SQLite's `julianday('now')` (UTC), never Python's `datetime.now()`, to
avoid mixing UTC-stamped columns with local time.

**General rule** (confirmed after a real bug: reimport was resetting clocks on unchanged rows,
which meant alerts never fired): the start-of-count timestamp is set the FIRST TIME the system
detects the entity entering the relevant state, and is NEVER recalculated by a reimport that
doesn't actually change the value — see the Dating rule under Domain model.

1. **Documentos pendientes** (per cliente): active while `documentos_completos_fecha IS NULL`, ≥24h
   since `cliente.fecha_creacion`, **and** the cliente has ≥1 caso with `estado_solicitud` not in
   `ESTADOS_CERRADOS` (Desembolsada/No aplica/Cliente desistió). The estado_solicitud exclusion was
   added after clientes with only a Desembolsada caso alerted forever with nobody ever clicking the
   checkbox. Never turns off automatically — only via `marcar_documentos_completos()` (sets
   `documentos_completos_fecha`) or reactivated via `marcar_documentos_pendientes()` (clears it —
   **known gap**: doesn't reset `cliente.fecha_creacion`, so the "Desde" time after a revert reads
   the original creation date, not the revert moment; would need a dedicated column to fix).
   `completar_documentos_por_desembolso()` auto-sets `documentos_completos_fecha` (only if still
   NULL, never overwrites) whenever a caso reaches Desembolsada, called from both
   `actualizar_edicion_manual()` and the bitácora importer's `_upsert_caso()`.
   Casos list highlights matching rows (light-red bg `wx.Colour(255,214,214)` / dark-red text
   `wx.Colour(139,0,0)`, contrast ≈7.5:1 — don't change without re-checking contrast) and plays
   `documentoPendiente.wav` on `EVT_LIST_ITEM_SELECTED` (color alone isn't WCAG 1.4.1-compliant).
   **Marking this checkbox is deliberately two-path**: the "Documentos completados (cliente)"
   checkbox in the Casos edit panel writes immediately on check, no confirm — kept as-is per
   explicit user decision (wanted for sighted users). The context-menu items ("Marcar documentos
   completados (cliente)" / "Marcar como pendiente") are the deliberate, safer path (menu-navigate
   + Enter, with a `wx.MessageBox` confirmation naming the exact cliente before writing) — this is
   the path the blind user actually uses. **Don't touch the checkbox's immediate-write behavior
   without asking first** — confirmed intentional twice after real incidents.
2. **Constancia pendiente** (per caso): active while `estado_solicitud == ESTADO_EN_ESPERA_CONSTANCIA`
   and ≥7 days since `estado_solicitud_fecha_cambio`. Turns off as soon as estado_solicitud changes.
3. **Constancia en mano** (per caso): active while `estado_solicitud == ESTADO_EN_PROCESO` and ≥48h
   since `estado_solicitud_fecha_cambio`. Uses `estado_solicitud_fecha_cambio`, not
   `constancia_recibida_fecha` — a caso imported already-at-"En proceso" never got
   `constancia_recibida_fecha` stamped (importer only stamps it on a live transition it witnesses),
   so it silently never alerted; fixed by reusing the general-rule column instead. Casos' "Filtrar
   por alerta" combobox had the identical bug/fix.

All three play a `.wav` via `ui/sonido.py` (`reproducir_sonido()`, silently no-ops if missing) and
surface only in the Notificaciones dialog (one grouped `wx.ListCtrl`: Tipo/Nombre/Identificación/
Caso/Desde — never individual popups). Sounds: `datosPendientes.wav`, `alerta.wav`,
`alertaMaxima.wav` in `assets/sonidos/` (real audio the user supplies, not generated).
`NotificacionesPanel.recargar()` runs on dialog open + explicit "Actualizar" — no background
scheduler/fixed clock.

**Not yet implemented, left alone per user request**: "amarilla" (7 days no update while etapa =
"Completar expediente/requisitos") and "roja" (3 days in etapa "Desembolso") — no schema column
tracks etapa_proceso's own transition timestamp yet.

## Filters and reporting — `db/casos.py`, `buscar_casos()` / `clasificar_termino_busqueda()`

One combined cédula-or-nombre search box (no separate ejecutivo/fecha fields — `ejecutivo_actual`
in Configuración replaced those):

- Empty → filter by `ejecutivo_actual` (or everything if none configured).
- Term has ≥1 digit → cédula search, partial/substring (cédulas can end in a letter, e.g.
  `"2011307810010Q"`).
- Letters-only (incl. accented vowels/ñ) → nombre search, partial/case-insensitive via Python's
  `str.upper()` — **deliberately not SQLite's `UPPER()`**, which is ASCII-only and silently fails
  to fold ñ/accented vowels. This same fix was later reused verbatim in `reporte_creditos.py`.
  Accents are matched exactly, not folded ("pena" won't find "PEÑA" — confirmed intentional).
- Anything else → `ValueError` with a user-facing message, caught and shown on the status bar.
- A cédula/nombre search ignores `ejecutivo_actual` entirely (searches all agents).
- Zero results shows "No se encontraron resultados." on the status bar, not a silently empty list.

Monthly reporting (`export/excel_export.py`) not yet implemented; will have its own agent selector
independent of `ejecutivo_actual`.

## UI structure (current)

`MainFrame` hosts a `wx.Notebook` with **3 tabs**: Casos, Calculadora de Crédito, Historial de
Créditos. Everything else — Notificaciones, Configuración, Ayuda, and Actualizaciones (a cascading
submenu under Ayuda) — lives in a classic Windows menu bar as modal `wx.Dialog`s (`_PanelDialog` in
`main_frame.py`), per explicit user request about how they navigate with NVDA (menus over extra
tabs, for setup/lookup screens that aren't daily-use). `EVT_NOTEBOOK_PAGE_CHANGED` calls
`recargar()` on the newly active tab.

Global shortcuts (`ui/atajos.py`), dispatched per active notebook tab in `main_frame.py`:
- **Ctrl+F** — focus search box (Casos, Historial de Créditos; no-op on Calculadora).
- **Ctrl+R** — focus results list (Casos, Historial de Créditos; no-op on Calculadora).
- **Ctrl+D** — clear/reset the active tab's form+filters (unified shortcut, replaced the old
  per-tab Alt+L / Alt+V mnemonics 2026-08-16). Casos: `limpiar_todo()` clears search + alert filter
  + edit panel together (previously two separate actions). Calculadora: clears inputs but
  **preserves the selected empresa**. Historial: clears search + returns to default Corriente view.
  Always plays `SONIDO_BORRAR` exactly once.
- **Ctrl+1/2/3** — jump directly to Casos/Calculadora/Historial (`MainFrame._ir_a_casos/
  _ir_a_calculadora/_ir_a_creditos`, just `self.notebook.SetSelection(i)` — confirmed empirically
  this still fires `EVT_NOTEBOOK_PAGE_CHANGED`, unlike `ChangeSelection()`).
- Adding a 4th tab means updating all of the above dispatch chains by hand — nothing enforces this
  at compile time.

### Casos (`casos_panel.py`)

16-column `wx.ListCtrl` (must stay in sync with `buscar_casos()`'s SELECT order): Fecha Registro,
No. Presolicitud, Ejecutivo, Empresa Convenio, Nombre del Cliente, Identificación, Teléfono, Monto
Solicitado, Destino del Crédito, Microseguro, Estado Solicitud, Etapa Proceso, Responsable Actual,
Decisión, Motivo No Aplica/Desistimiento, Observaciones. Empty cells show literal `"Celda vacía"`
(`CELDA_VACIA`) — a truly empty cell makes NVDA repeat just the column header with nothing after
it, confusing when arrowing through rows; applied uniformly to every column.

Selecting a row loads it for editing: one-line confirmation + Estado Solicitud/Etapa Proceso as
closed `wx.Choice` dropdowns from `catalogos.py` (never free text — keeps exact string matching
safe for `ESTADO_EN_ESPERA_CONSTANCIA`/`ESTADO_DESEMBOLSADA`; unmatched legacy values just show no
selection via `FindString`, no crash). "Guardar cambios" → `actualizar_edicion_manual()`. Never
touches `constancia_recibida_fecha` (importer-only).

"Filtrar por alerta" `wx.Choice` reloads the list live and silently on every arrow key
(`EVT_CHOICE`), and additionally announces the resulting count via `anunciar_voz_nvda()` only on
Enter (`EVT_CHAR_HOOK` + `wx.Window.FindFocus()` check — `wx.Choice`'s native Win32 combobox
swallows Enter before a plain `EVT_KEY_DOWN` would see it; this same workaround pattern recurs for
every `wx.Choice` in the app that needs an Enter-triggered action).

### Notificaciones (`notificaciones_panel.py`)

One `wx.ListCtrl` grouping all 3 active alert types, "Actualizar" button, and "Marcar documentos
completados" (enabled only when the selected row is a Documentos pendientes alert) — same
selection-driven pattern as Casos' edit panel.

### Calculadora de Crédito (`calculadora_panel.py`)

**Fully standalone — no link to caso/cliente/cédula at all.** An earlier version had a "Buscar
caso" prefill + "Guardar simulación" button; both removed per explicit user rejection ("este módulo
debe ser estrictamente una calculadora de crédito independiente y nada más"). The officer types
every field by hand each time: empresa (`wx.Choice`, resolves tasa — free selection, since a
caso's `empresa_convenio` text can mismatch the convenio table's name), fecha de ingreso, salario,
ingresos extra, monto/plazo/periodicidad/deuda activa, then Calcular. Nothing is persisted.

- `wx.lib.scrolledpanel.ScrolledPanel` (not plain `wx.Panel`) with `SetupScrolling(scroll_y=True)`
  — content taller than the visible area must scroll, not clip (WCAG 2.1.1). Don't revert.
- **All input controls stay always-enabled/reachable** — a disabled `wx.Window` is skipped by Tab
  navigation entirely; only `guardar_btn`-style terminal action buttons should ever be gated on
  prior state, never a whole section of inputs. (Real bug: `_habilitar_entradas(False)` on 9 input
  fields made everything but "Tasas por convenio" unreachable until a caso was selected.)
- **Pasivo laboral and salario neto (con deducciones) both recalculate live on every keystroke**
  (`EVT_TEXT` on fecha_ingreso/salario for pasivo laboral; salario/ingresos extra for salario neto)
  — independent of every other field, shown in their own result labels, and are the single source
  of truth for what Ctrl+Shift+Q/W announce. **Any control with >1 handler bound to the same event
  needs `event.Skip()` in every handler** — without it, wx only calls the most-recently-bound
  handler and the other one silently stops firing with no error (real bug hit here).
- **Ctrl+Shift+Q** speaks pasivo laboral, **Ctrl+Shift+W** speaks salario neto, **Ctrl+Shift+E**
  speaks the selected empresa name only (no tasa — already heard while arrowing the list). None
  move focus — pure `anunciar_voz_nvda()` calls. Bound via panel-level `EVT_CHAR_HOOK` with no
  `FindFocus()` check (must fire regardless of focused control).
- **Ctrl+D** clears the form and moves focus to "Fecha de ingreso" (continuous data entry).
- **Ctrl+T / Ctrl+Shift+T** copy a ready-to-paste summary to the clipboard (quincenal / mensual
  cuota respectively): `"monto de USD $[Monto]\nplazo de [Plazo] meses \ncuota [quincenal|mensual]
  aproximada de USD $[Cuota]"` (trailing space on the plazo line is intentional). Forces
  `evaluar_capacidad()` with the periodicidad the shortcut names, ignoring the periodicidad combo.
  Announces success via `anunciar_voz_nvda()`, not `SONIDO_BORRAR` (that sound means
  cleared/deleted elsewhere in the app). Clipboard access wrapped with a short retry (`Open()` can
  transiently fail on Windows).
- **No thousands separator anywhere in this panel** — `f"{v:.2f}"` not `f"{v:,.2f}"`, everywhere
  (labels, spoken summaries, shortcuts) — NVDA reads commas awkwardly. **Scoped to this panel
  only**, Casos' monto formatting is untouched.
- `empresa_choice` items speak their own tasa (`"Aceitera El Real: Tasa: 33%"`) so the officer can
  verify the exact rate while arrowing — added after a real incident where a stale DB row (MIDESA
  at 0.70 instead of 0.18) went unnoticed. Selection is tracked by index (`_empresa_seleccionada()`),
  not `GetStringSelection()`, since the displayed text now includes the tasa. Enter/Space on the
  choice speaks `"Seleccionada {empresa}"` only (no tasa — redundant, reported as noisy). The
  separate visible `"Tasa: X%"` label next to the combo was **removed** (2026-08-21, explicit user
  request, see below) — NVDA already announces the tasa via the combo's own selected text (open or
  closed), so the label added nothing by voice, only visual clutter.
- **Ctrl+R** (no Shift) speaks the already-calculated cuota rounded up to the nearest whole number
  (`math.ceil`, e.g. 19.25 → 20) times `TIPO_CAMBIO_FIJO`, without recalculating — distinct from
  Ctrl+Shift+R, which does recalculate. Requires a prior Calcular (unlike Q/W, which are live); if
  none yet, speaks a "todavía no" message instead of failing silently. No visible label in
  Resultados (2026-08-21, explicit user request) — same pattern as the empresa name (Ctrl+Shift+E),
  voice-only, no dedicated on-screen text.
- **Screen-visible content is a deliberately curated subset** (explicit user request, 2026-08-21,
  from someone who uses the app daily with NVDA: "cosas que he realizado para ciegos que no
  deberían de estarse mostrando"). Exactly 8 input fields + 6 result labels stay visible: Empresa,
  Fecha de ingreso, Salario, Ingresos extra, Monto del crédito, Plazo, Periodicidad, Cuotas de
  deudas activas + Salario bruto, Salario neto, Pasivo laboral, Cuota calculada, Cobertura de
  pasivo laboral, Nivel de endeudamiento. Cuota redondeada and the standalone Tasa label are
  voice-only (see above) — nothing else has been added or removed from this list since; before
  adding a new visible label to this panel, confirm it belongs in that set.
- **Ctrl+P / "Guardar PDF" button**: exports the last Calcular's 8 inputs + 6 results (the same
  set as the bullet above, nothing else — never a transient status message like "copiado al
  portapapeles") to a PDF via `wx.FileDialog` (`gestor_credito/export/pdf_export.py`,
  `generar_pdf_calculo()` — pure function, no DB/UI, same pattern as `word_export.py`). Explicit
  user request (2026-08-21): a printable file to attach to a client's physical/digital expediente
  — the Calculadora itself still saves nothing, this is a one-off export the officer places
  wherever they want. Default filename is date/time-based (`Calculo_credito_DD-MM-AAAA_HHMM.pdf`,
  editable in the dialog) since the panel has no client identity to name it after. Requires a
  prior Calcular, same `wx.MessageBox` guard as Ctrl+R. `_on_guardar_pdf` (shows the real dialog)
  and `_guardar_pdf_en_ruta` (does the actual work) are split on purpose so tests can bypass the
  modal dialog — same pattern as `_seleccionar_archivo_simulado` in
  `tests/test_configuracion_creditos.py`. `_ultimas_entradas` snapshots the exact inputs behind
  `_ultimo_resultado` so the PDF can't mix a stale calculation with fields edited afterward without
  recalculating. **Header carries a branding block** (explicit user request, 2026-08-21, picked
  from 5 options offered — "identidad + contacto"): the same logo as `ui/logo.py` (`LOGO_PATH`,
  same relative-path resolution, works both from source and the PyInstaller build) plus
  `MARCA_NOMBRE = "Franklin Accesible"` and `MARCA_TELEFONO = "+505 5771 4938"` — so the PDF is
  self-sufficient if it ends up loose in a physical expediente without the rest of the paperwork.
  The logo file itself is 2048x2048px (~2MB) — embedding it at that resolution bloated every PDF to
  ~2.4MB for no visible gain at a 1.6cm print size, so `pdf_export.py` downsamples it with Pillow
  (`Image.thumbnail`, 300px cap) before handing it to reportlab's `drawImage` via `ImageReader` —
  brings a typical PDF down to ~60KB. If the logo file is missing, the name/phone still draw (same
  graceful-degradation as `AppLogo`), just without the image.
- `TIPO_CAMBIO_FIJO = 36.6243` is a hardcoded constant, not a field — explicitly temporary per the
  user, don't move it into a future rate-config screen preemptively.
- Validation errors use `wx.MessageBox` (missing/invalid fields, empresa with no tasa, no prior
  Calcular for Ctrl+R/Ctrl+P). A successful Calcular writes to result labels AND speaks via
  `anunciar_voz_nvda()` directly (not the weaker status-bar live region).

### Historial de Créditos (`creditos_panel.py`, `db/reporte_creditos.py`)

Read-only lookup over `reporte_credito` (no FK to cliente/caso, deliberately independent — same
principle as `convenio_tasa`/`calculo_credito`). 13-column list (`COLUMNAS` in `creditos_panel.py`
— column order is independent of `buscar_creditos()`'s SELECT order, `_fila_a_columnas()` maps
between the two): Fecha Desembolso, Fecha Vencimiento, No. Crédito, Monto Desembolsado, **Saldo a
la fecha**, Nombre del Cliente, Identificación, Empresa Convenio, Estado del Crédito, Plazo del
Crédito, Número de Cuotas, Cuotas Pagadas, Cuotas Pendientes. Same `CELDA_VACIA` placeholder as
Casos. Selecting a row shows a read-only one-line summary, no edit fields.

**Saldo a la fecha** (added 2026-08-21, explicit user request) = `saldo_principal +
saldo_intereses`, computed in `_formatear_saldo_a_la_fecha()` at display time — same principle as
Cuotas Pendientes (computed, never its own stored column). `saldo_principal`/`saldo_intereses`
(imported from the real report's `SALDO_PRINCIPAL`/`SALDO_INTERESES` columns) exist in the schema
and the importer purely to feed this sum — **they have no column of their own in the list**,
explicit user request ("son relleno... solo se muestra el saldo a la fecha"). Empty (not `0`) if
either input is `None` — a partial sum would look like a complete one. Of the 94 columns in the
real report headers, the user marked exactly 13 as needed (yellow highlight in the sample file);
9 were already covered, these 2 were the only genuinely new ones. Two other highlighted columns —
`ES_CONVENIO` and `FECHA_REPORTE` — were explicitly declined ("ignórala, no la vamos a usar") and
are not imported.

Filters (all AND together, all live-reload on `EVT_CHOICE`, count announced via `anunciar_voz_nvda`
on Enter — same `FindFocus()` pattern as Casos):
- **Cuotas pendientes (máximo)** — free-text int, `<=` comparison against `numero_cuotas -
  cuotas_pagadas` (rows missing either value never match). This is the "Próximos a finalizar"
  control — no separate dedicated widget for that concept.
- **Empresa** — from `obtener_empresas_convenio()`, the distinct values actually present in
  `reporte_credito` (not the 29-company global `convenio_tasa` catalog, which can list companies
  with zero credits here or under a different name).
- **Estado** — "Activos (Corriente)" (default), "Finalizados (para reenganche)", "Todos los
  estados". `ESTADO_CREDITO_FINALIZADO` is a compound condition: `estado_credito IN ('Cancelado',
  'Finalizado') OR (numero_cuotas - cuotas_pagadas) <= 0` — the cuotas-based branch catches real
  cases where MIDESA hadn't flipped `estado_credito` to Cancelado yet despite being functionally
  paid off. Ordered by `estado_credito_fecha_cambio DESC` (not fecha_desembolso, which is when the
  credit *started*) so newest payoffs lead the reengagement list.
- Cédula/nombre search does **not** override the Estado filter (unlike Casos' ejecutivo override)
  — to search a specific client across all statuses, explicitly pick "Todos los estados".

**Vencido/Saneado row alert** (added 2026-08-21, explicit user request): same visual+audio
equivalent Casos already has for "Documentos pendientes" (see below), here for
`estado_credito` in `ESTADOS_CREDITO_ALERTA` (`db/reporte_creditos.py`: `ESTADO_CREDITO_VENCIDO`
= "Vencido", `ESTADO_CREDITO_SANEADO` = "Saneado"). Rows highlight in the same red
(`wx.Colour(255,214,214)` bg / `wx.Colour(139,0,0)` text, same contrast already verified for
Casos) and `SONIDO_FILA_CREDITO_VENCIDO_SANEADO` (`documentoPendiente.wav` — same file as Casos'
alert, own named constant per this app's one-constant-per-alert-concept convention) plays on
`EVT_LIST_ITEM_SELECTED`. Purely decorative on top of whatever `buscar_creditos()` already
returns — **does not touch any filter**: the default "Activos (Corriente)" view still excludes
Vencido/Saneado rows exactly as before this change (explicit user confirmation: seeing them in
the default view isn't wanted, but when a client is searched and "Todos los estados" is picked,
the row must be identifiable at a glance/by ear without re-reading the Estado column by hand).

`_cargar_creditos()`/`_cargar_empresas()` run their SQLite queries via `ejecutar_en_segundo_plano()`
(`accesibilidad.py`) — a background thread + `wx.CallAfter` back to the UI thread — because running
them inline froze NVDA's speech (the UI thread not pumping messages while a query is in flight).
Guarded by a version counter so a slower, older query can't overwrite a newer result. Not applied
to Casos/Calculadora (not reported as freezing there; reach for this fix if that report comes up
elsewhere).

Import (`importer/reporte_creditos_importer.py`, triggered from Configuración): per-row errors
(bad numeric field, blank nombre_cliente) are caught and recorded per-row, never abort the whole
loop (a single bad row used to roll back the entire import via one unhandled exception before
`conn.commit()`). `no_credito` matching on reimport falls back to a numeric-cast comparison
(`CAST(... AS INTEGER)`, only when both sides are pure digits) so `"0012456"` vs `12456` from
different exports don't create duplicate rows — the identity text itself, once first imported, is
never rewritten by later reimports.

## Actualizaciones automáticas — `actualizador/actualizador.py`, `ui/actualizacion_dialog.py`

Lets the developer/agente check for and install a newer packaged build from inside the running app.
Anonymous HTTPS `GET` only (no cloud account sign-in — office PC has none by design), no push/auto-
notify (the same person publishes every release and always knows). Hosted on GitHub Releases,
**definitive repo: `javyx21/gestor-de-credito-releases`** (public, releases only, no source code).
`URL_VERSION_JSON` points at the stable `.../releases/latest/download/version.json` alias — no code
change needed for future releases, as long as each release includes an asset named exactly
`version.json` and isn't published `--prerelease`. Integrity model: SHA256 checksum + HTTPS, no
code signing (confirmed sufficient by the user).

UI lives under **Ayuda ▸ Actualizaciones** (a real cascading `wx.Menu` submenu, not a tab/dialog
panel — two prior attempts, buttons-in-a-list and a `wx.TreeCtrl`, were both explicitly rejected;
the user described the exact arrow-key sequence they wanted, which turned out to be native menu
navigation). Two separate items: **"Buscar actualizaciones"** only checks/reports (never
downloads); if newer, opens **"Actualización disponible"** (`actualizacion_dialog.py`) showing
version/changelog (`notas`, optional field in `version.json`) and the single **"Instalar
actualización"** button (click itself is the confirmation, no extra MessageBox). **"Información
sobre la versión"** is always-available, never touches the network, reports installed `VERSION`
plus the last check's result if one ran this session.

`verificar_actualizacion()`/`descargar_actualizacion()`/`aplicar_actualizacion()` have no DB/UI
dependency. Download uses `urlopen(..., timeout=30)` with manual chunked reads (per-operation
timeout, not whole-download — `urlretrieve` alone had no timeout and could hang forever). Every
failure re-raises as a plain-Spanish `RuntimeError`, shown via `wx.MessageBox`.

**A running `.exe` can't overwrite its own files on Windows** — `aplicar_actualizacion()` launches
`GestorDeCredito_Updater.exe` (PID, zip, app folder, main exe path), then the dialog closes the app
immediately. The updater (`updater/actualizar_app.py`, stdlib-only) polls `tasklist` until the PID
is gone, extracts the zip over the app folder (5 retries w/ 1s gap if a file is still locked, never
deletes the zip on failure, always relaunches some working copy), and relaunches the main exe.
Logs to `GestorDeCredito_Updater.log` next to the app (this process has no console).

**Packaging**: updater is built `--onefile` (separately from the main `--onedir` build) so it has
no `_internal/` folder of its own to collide with the app's. **Exclude
`GestorDeCredito_Updater.exe` from every release zip** — the updater can't overwrite the file it's
currently running from. **Build the release zip from the app folder's *contents*, not the folder
itself** — `Compress-Archive -Path 'GestorDeCredito.exe','_internal' -Dest ...`, not `-Path
'GestorDeCredito'` (a real v1.0.1 release shipped the wrong shape once, creating a nested duplicate
subfolder on update instead of overwriting — always re-`Expand-Archive` a built zip and confirm
`GestorDeCredito.exe` sits at the top level before publishing).

**Key lessons from real production incidents (v1.0.0–v1.0.10)**:
- A compiled `.exe` must be re-verified after ANY source change that could affect it — verifying
  the *source* imports/runs correctly says nothing about whether an already-built `.exe` was
  compiled from that same source (a real release shipped with `URL_VERSION_JSON` still empty
  because the exe predated that edit).
- Grepping a PyInstaller `.exe` for a plain string doesn't prove absence — the bundled PYZ archive
  is zlib-compressed as a whole. To really inspect what's embedded: pull `PYZ.pyz` out via
  `PyInstaller.archive.readers.CArchiveReader`, or better, drive the actual compiled exe live with
  `pywinauto` (`backend="win32"` for this app's native Win32 cascading menus — `uia`'s
  `menu_select()` raised `IndexError` on them) and read the real resulting dialog.
- When the app process wouldn't close after "Instalar actualización", several independently
  plausible fixes (`wx.Exit()` ordering, `os._exit()`, raw `TerminateProcess()`) were each tried
  and each failed identically — the real fix, `taskkill /F /PID <pid>` via `subprocess.Popen`, was
  shipped not because it was proven uniquely necessary but because it has no dependency on wx, any
  event loop, or any DLL's cleanup path, making it the most failure-proof option. **The actual root
  cause of several of those "failed" attempts was a corrupted test folder left over from the
  earlier nested-zip bug** — a folder that went through one real failure isn't a valid target for
  testing a later, unrelated fix; always retest against a freshly deployed copy. When a live bug
  survives several plausible fixes in a row, add real instrumentation (a step-by-step log file)
  instead of continuing to guess blind.
- `TerminateProcess()` (Win32, ctypes) is used in place of `os._exit(0)` for the same DLL-cleanup
  reason — confirmed via testing that `ExitProcess`-based paths could stall waiting on
  `DLL_PROCESS_DETACH` across this app's many bundled native DLLs.

## Commands

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

python main.py          # run the app
pytest                  # run tests
pytest tests/test_database.py::test_init_db_creates_file   # run a single test
```

wxPython/openpyxl/python-docx/reportlab are already in the global Python install on this machine;
`pytest` is not — `pip install -r requirements.txt` (or `pip install pytest`) first.

### Empaquetado portable (pendrive)

```
pyinstaller --name "GestorDeCredito" --windowed --noconfirm --add-data "gestor_credito/assets;gestor_credito/assets" main.py

pyinstaller --name "GestorDeCredito_Updater" --onefile --noconfirm updater/actualizar_app.py
copy dist\GestorDeCredito_Updater\GestorDeCredito_Updater.exe dist\GestorDeCredito\
```

`--onedir` for the main app (faster startup, no self-extraction per launch — confirmed with user).
`DB_PATH` in `db/database.py` is frozen-aware (`sys.frozen`/`sys.executable`) so
`data/gestor_credito.db` sits next to the `.exe`, not inside the PyInstaller bundle — don't revert
to a plain `Path(__file__)`-relative path, it would break portability. Build artifacts (`build/`,
`dist/`, `*.spec`) are git-ignored.

**If building inside this OneDrive-synced project folder fails with `PermissionError` deleting old
build output**, point `--distpath`/`--workpath`/`--specpath` outside the synced folder (OneDrive
holds file locks mid-sync) — same root cause as the Excel-COM lesson below.

**Excel COM testing lesson**: driving `.xlsx` files via COM for verification must open them
`ReadOnly=True` — `wb.Close(SaveChanges=False)` alone isn't enough for a file inside a
OneDrive-synced folder, since AutoSave can persist changes regardless of the explicit close flag (a
real reference file got test values written into it this way once; restored from a first-dump
backup afterward).

## Architecture

```
main.py                        # entry point, calls gestor_credito.app.main()
updater/
  actualizar_app.py             # external updater process, stdlib-only, built --onefile separately
gestor_credito/
  app.py                       # wx.App subclass, creates the main frame
  version.py                    # VERSION constant, bumped by hand before each release
  catalogos.py                  # fixed value lists from 02_Catalogos (Estado Solicitud, Etapa Proceso)
  actualizador/
    actualizador.py              # verificar_actualizacion/descargar_actualizacion/aplicar_actualizacion
  assets/
    logo.png                     # real logo, 2048x2048px — AppLogo scales it down for display
    sonidos/                      # .wav alert sounds, supplied by the user (not generated)
    nvda/                          # nvdaControllerClient(32|64).dll — see anunciar_voz_nvda
  calculo/                       # pure calc engine for Calculadora de Crédito, no DB/UI
    dias360.py                     # Excel DAYS360 (US/NASD) replica
    pasivo_laboral.py               # Nicaraguan labor-liability approximation
    deducciones.py                  # INSS/IR
    amortizacion.py                 # cuota nivelada + payment schedule/dates
    capacidad.py                    # orchestrates the above into evaluar_capacidad()
  ui/
    main_frame.py                # wx.Frame; hosts the 3-page wx.Notebook + menu bar dialogs
    logo.py                       # AppLogo — the accessible logo shown on every tab/dialog
    sonido.py                     # reproducir_sonido() — plays a .wav via wx.adv.Sound
    fechas.py                     # ISO <-> DD/MM/AAAA date formatting for the UI boundary
    accesibilidad.py               # nombre_accesible/activar_con_enter/anunciar_texto_estado/
                                     # anunciar_voz_nvda/ejecutar_en_segundo_plano
    atajos.py                      # central registry of every documented keyboard shortcut
    casos_panel.py                 # "Casos" tab
    calculadora_panel.py            # "Calculadora de Crédito" tab
    creditos_panel.py               # "Historial de Créditos" tab
    notificaciones_panel.py         # Notificaciones dialog
    configuracion_panel.py          # Configuración dialog (agente + importar bitácora/reporte)
    ayuda_panel.py                  # Ayuda dialog — ONLY the keyboard shortcut reference
    actualizacion_dialog.py          # "Ayuda ▸ Actualizaciones" logic, wired from main_frame's menu
  db/
    database.py                  # sqlite3 connection + schema management
    casos.py                      # queries/updates for caso (search, filter, edit)
    configuracion.py              # get/set for the configuracion key-value table
    alertas.py                     # live alert queries
    convenios.py                   # convenio_tasa CRUD
    calculo_credito.py              # last-saved-simulation-per-caso CRUD (currently unused)
    reporte_creditos.py             # buscar_creditos(), for Historial de Créditos
  importer/
    excel_importer.py             # reads the MIDESA bitácora, upserts cliente/caso
    reporte_creditos_importer.py    # reads recursos/reporte.xlsx, upserts reporte_credito
  export/
    excel_export.py              # openpyxl-based report export (not yet implemented)
    word_export.py                # python-docx-based document export
    pdf_export.py                  # reportlab-based PDF export (Calculadora "Guardar PDF")
data/
  gestor_credito.db              # SQLite file, created on first run, git-ignored
tests/                            # pytest, mirrors the gestor_credito/ package layout
```

- `db/database.py` holds `DB_PATH`, `get_connection()`/`init_db()`, and the schema. Entity-specific
  queries live in their own `db/` module, not crammed into `database.py`.
- `ui/` has one wx.Frame/wx.Panel per file; `MainFrame` only wires the notebook + menu together.
- `export/` modules take plain data (rows/headers) and an output path — no DB/UI reach-back, so
  they stay independently testable.

## Accessibility (NVDA)

- Every input control needs a real associated label — NVDA announces by label, not placeholder
  text or visual proximity.
- Preserve logical tab order matching visual/reading order; nothing mouse-only.
- Prefer standard wx widgets over custom-drawn ones — standard widgets get MSAA/UIA for free.
- Feedback goes to the status bar/an in-panel message, not a dialog — except the narrow
  `wx.MessageBox` exception in Project above. Never convey state through color/icon alone.
- **`wx.Window.SetName()` does not propagate to the real accessible name for any control type**
  (verified with raw MSAA via `comtypes`/`oleacc` — Windows falls back to a "nearest preceding
  STATIC label" heuristic that's often wrong). Use `nombre_accesible(control, nombre)`
  (`accesibilidad.py`) instead — it wraps `control.SetAccessible()` with a `wx.Accessible`
  subclass overriding only `GetName`, leaving native role/state untouched. Every `SetName()` call
  site in the codebase was migrated to this.
- **Decorative/non-native controls need extra work to be Tab-reachable at all.**
  `wx.StaticBitmap`/`wx.StaticText` don't accept keyboard focus by default and their native
  MSAA role/state can be broken/empty. `ui/logo.py`'s `_LogoBitmap`/`_LogoTexto` override
  `AcceptsFocus`/`AcceptsFocusFromKeyboard` plus a local `wx.Accessible` supplying `GetRole`/
  `GetState` explicitly (`ROLE_SYSTEM_GRAPHIC`, focusable/focused state).
- **Status-bar live-region announcements (`anunciar_texto_estado`, `EVENT_OBJECT_LIVEREGIONCHANGED`
  via `user32.NotifyWinEvent`) are unreliable in practice** — confirmed not heard by the user's
  real NVDA for at least one interaction (the Casos alert-filter combobox). Prefer
  `anunciar_voz_nvda(texto)` (`accesibilidad.py`) instead, which calls directly into NVDA's public
  `nvdaController_speakText` API (DLLs in `assets/nvda/`, from the `accessible_output2` PyPI
  package) — no dependency on focus/roles/live-region heuristics. `anunciar_texto_estado` is still
  used elsewhere in the app where it wasn't reported broken; if a "not heard" report comes back for
  another spot, switch that spot to `anunciar_voz_nvda` rather than converting preemptively.
- Any `wx.Button` must go through `activar_con_enter()` (`accesibilidad.py`) — Space activates a
  focused button by default outside `wx.Dialog`, but Enter does not (that binding is
  `wx.Dialog`-only, and this app's notebook-in-a-frame layout doesn't get it for free).
- **A native `wx.Choice`'s Win32 combobox swallows Enter before a plain `EVT_KEY_DOWN` on the
  control ever sees it.** The fix used throughout the app: bind `wx.EVT_CHAR_HOOK` on the *panel*,
  check `wx.Window.FindFocus() is <the choice>`. If Enter silently does nothing in some other
  control later, suspect this same issue first.
- **A disabled `wx.Window` is skipped by Tab navigation entirely** — for a screen-reader user this
  is indistinguishable from the control not existing. Never `Enable(False)` a whole block/section
  of input controls; gate only a single terminal action button (like a Guardar/Calcular button) on
  prior state.
- **When binding more than one handler to the same event on the same control, every handler needs
  `event.Skip()`** — otherwise only the most-recently-bound handler fires; the other silently stops
  with no error.
- Long-running DB/network calls on the UI thread block Windows' message pump, which stalls NVDA's
  speech (an external process synchronized via that pump). Use `ejecutar_en_segundo_plano(trabajo,
  callback)` (`accesibilidad.py` — background thread + `wx.CallAfter`) for anything slower than
  instant; guard against stale results with a version counter if the same load can be triggered
  faster than it completes.

## Judgment calls worth knowing

- **File selection uses native `wx.FileDialog`** despite the "no popups" rule — read as targeting
  in-app modals (confirmations, notification popups), not the standard, already-accessible OS
  file-open dialog.
- **The Configuración agent picker went through 3 iterations** before landing on a closed
  `wx.Choice`: an editable `wx.ComboBox` (ambiguous typing-vs-navigating for screen readers) → a
  plain textbox + read-only label (not actually actionable) → closed `wx.Choice` (current). If a
  similar "can't change X" report comes up for a free-text/combo-box control elsewhere, consider
  whether a closed `wx.Choice` sidesteps the same ambiguity.
- **Where to put a new feature in the menu vs. the notebook**: Actualizaciones (Ayuda ▸
  Actualizaciones) and Calculadora de Crédito took opposite paths for a reason the user articulated
  directly — a quick/occasional lookup or one-time setup action belongs in a menu dialog; a routine,
  frequently-used function belongs as a first-class notebook tab. Ask which kind a new feature is
  before defaulting to either pattern.
