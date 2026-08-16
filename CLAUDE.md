# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Gestor de Crédito — a Windows desktop application for a Dominican financiera (lending company)
that only grants credit to employees ("colaboradores") of partner companies ("empresas convenio").
The app's job is to track each credit case from presolicitud through disbursement, using a case
log ("bitácora") exported periodically from an external system (MIDESA) as an Excel file, plus
day-to-day manual follow-up done directly in the app.

Primary design constraint: the UI must be fully usable with the NVDA screen reader and must meet
WCAG 2.2. This is not incidental — it is the reason wxPython was chosen over other GUI toolkits,
and it should inform every UI decision (see Accessibility section below). Two hard UI rules that
follow from this:
- **No popups, ever** — with one explicit, narrow exception (added after real NVDA testing, see
  below): all views live as tabs inside the single main window. Notifications, confirmations,
  forms — everything is a tab/panel, never a separate modal window, to keep NVDA navigation
  predictable. **Exception**: `wx.MessageBox` *is* used for a small number of transient outcomes
  that need immediate screen-reader attention and have no other reliable way to get it:
  - Casos search (`casos_panel.py`, `_cargar_casos`): invalid search term, zero results.
  - Configuración (`configuracion_panel.py`): empty agent name on save, import errors, and
    import-completed. The import-completed popup deliberately shows only the 4 headline counts
    (clientes/casos nuevos, casos actualizados, filas omitidas), not the full per-row detail —
    a real import had 59 omitted rows, and dumping all of that into a modal would be a long,
    blocking wall of text; the popup instead points to `resultado_texto` (the existing read-only
    text box) for the row-by-row detail, which the user can review with NVDA at their own pace.
  The reasoning: status bar text (`SetStatusText`) and `wx.StaticText.SetLabel` changes are
  **not** proactively announced by NVDA — the user has to manually go check them, which for a
  failed/empty search (or a silent validation error) means no indication anything happened. A
  native `wx.MessageBox` reliably grabs focus and gets announced immediately, which is exactly
  why it's normally reserved for dialogs — here it's the pragmatic fix for a real reported gap,
  confirmed directly by the user (who is blind and tests with NVDA). Don't generalize this to
  "add a MessageBox whenever something changes" — success/count feedback that isn't the sole
  indication of an otherwise-silent outcome (e.g. "N caso(s) encontrados", "Cambios guardados",
  "Agente configurado: X") stays on the status bar/inline label, popup-free — a dialog on every
  successful action would be far more disruptive than helpful. When adding a new user-facing
  outcome anywhere in the app, ask "would NVDA hear anything at all if this weren't a popup?"
  before defaulting to one.
- **The Franklin Accesible logo appears on every tab**, unobtrusively (e.g. small, in a corner —
  not a banner), with this exact alt text / accessible name: "Logo de Franklin Accesible: figura
  humana azul en movimiento, atravesando una barrera fragmentada de color naranja y amarillo."

## Domain model

Two entities, both driven by the MIDESA Excel bitácora import:

- **Cliente** — a person, identified by `cedula` (national ID), which is the only durable natural
  key. A cliente can have many casos over their lifetime (e.g. an old credit fully paid off, then
  a new one requested months later) — this is legitimate history, never a duplicate to be merged
  or overwritten.
- **Caso** (a credit application/case) — belongs to one cliente. Identity is the combination of
  `cliente` + a case reference number from the Excel (`No. Presolicitud`, falling back to
  `ID Caso` when the former is blank) — this combination is what decides "already imported" vs.
  "new row" during import.

Schema (`gestor_credito/db/database.py`, `SCHEMA` constant):

```sql
cliente(id, cedula UNIQUE, nombre, telefono,
        documentos_completos_fecha,   -- NULL = Alerta 1 still active for this cliente
        fecha_creacion, fecha_actualizacion)

caso(id, cliente_id -> cliente.id,
     id_caso, no_presolicitud, clave_caso,   -- clave_caso = COALESCE(no_presolicitud, id_caso)
     fecha_registro, canal_origen, ejecutivo, empresa_convenio, monto_solicitado,
     destino_credito, microseguro, estado_solicitud, etapa_proceso, responsable_actual,
     fecha_ultima_gestion, proxima_gestion, dias_en_gestion, alerta_seguimiento,
     requiere_siaf, fecha_envio_siaf, fecha_decision, decision, motivo_no_aplica, observaciones,
     constancia_solicitada,               -- informational only, raw value from Excel (not a date)
     estado_solicitud_fecha_cambio,      -- since when estado_solicitud holds its current value
     constancia_recibida_fecha,          -- set by the importer, not the user — see below
     origen_ultima_modificacion, fecha_creacion_registro, fecha_actualizacion_registro,
     UNIQUE(cliente_id, clave_caso))

configuracion(clave PRIMARY KEY, valor)   -- key/value settings, e.g. ('ejecutivo_actual', 'fmartinez')
```

Design notes / assumptions baked into this schema (flag to the user if any of these turn out to
be wrong — they're inferred from the business description, not explicitly spelled out column by
column):

- `nombre`/`telefono` live only on `cliente`, not duplicated per `caso` — the Excel repeats them
  on every row, but the import just updates `cliente` from the latest row it sees.
- `dias_en_gestion` is stored as imported (historical), but any "live" days-pending shown in the
  UI should be computed from `fecha_ultima_gestion` at query time, not trusted as always current.
- A general dating rule that resolves an apparent tension in the spec: **business dates that the
  Excel actually provides** (fecha_registro, fecha_ultima_gestion, etc.) always come from the
  Excel's own columns, never from import time. But **system-detected transition timestamps** —
  things the Excel doesn't tell us directly, like "since when has this case been in its current
  estado_solicitud" (`estado_solicitud_fecha_cambio`) or "when did the importer notice the
  constancia arrived" (`constancia_recibida_fecha`) — are stamped with the system time at the
  moment the app detects them, because there is no Excel column for either. Flag if this reading
  is wrong.
- `estado_solicitud_fecha_cambio` is initialized to "now" on first insert and reset to "now" on
  every value change (import-detected or manual). This means a case that was already sitting in
  "En espera de constancia" for days before its first import into this app will under-count how
  long it's actually been waiting. Confirmed acceptable with the user: there is no "fecha de
  cambio de estado" column in the Excel, so the app has no way to know that prior history — the
  count intentionally starts from first import.

## Reference template: MachoteBaseDeDatos.xlsx

The user keeps a reference/template workbook at the project root, **`MachoteBaseDeDatos.xlsx`**
(git-ignored — it's real pilot data with real names/cédulas, not a fixture), used to learn the
real column structure. It is *not* a fixed filename the importer looks for — `import_bitacora()`
accepts any `.xlsx` the user picks; the file only serves as a reference for what real MIDESA
exports look like. Two sheets are worth knowing about if this comes up again:

- **`01_Bitacora_Piloto`** — the actual case log, whose real headers are messier than a first
  guess would produce: each is like `"ID Caso\n(Auto)"` or `"Estado Solicitud\n(Manual)"` — an
  embedded newline plus a `"(Manual)"`/`"(Auto)"` suffix baked into the header text itself. Also,
  `"No. PRESOLICITUD"` can come through as a raw number (e.g. `2877`), not a string.
- **`02_Catalogos`** — lists the actual fixed/allowed values per field. Confirmed real values:
  - **Estado Solicitud**: En espera de constancia, En proceso, Desembolsada, No aplica, Cliente
    desistió, Pendiente de información, Devuelta para corrección. (`ESTADO_DESEMBOLSADA =
    "Desembolsada"` and `ESTADO_EN_ESPERA_CONSTANCIA` are both defined in `database.py`.)
  - **Etapa Proceso**: Pre-solicitud, Completar expediente / requisitos, Solicitud formal,
    Aprobación, Formalización, Desembolso, Cierre.
  - Also has fixed catalogs for Responsable Actual, Microseguro, Decisión, Requiere SIAF, and
    Canal/Origen — not modeled in `catalogos.py` yet since nothing consumes them, but the same
    "add a list + wx.Choice" pattern used for Estado Solicitud/Etapa Proceso (see "UI implemented
    so far" below) applies if/when those fields get similar closed-dropdown editing.

## Import behavior (Excel bitácora)

Implemented in `gestor_credito/importer/excel_importer.py` (`import_bitacora(file_path)`).
`_normalize_header()` strips the real-world header noise described above (embedded newlines,
the `(Manual)`/`(Auto)` suffix, inconsistent spacing around `/`) before matching against
`COLUMN_ALIASES` — this is deliberately more aggressive than simple case/accent tolerance because
the reference template proved headers aren't clean. Cell *values* (e.g. `estado_solicitud`
strings) are taken verbatim and never normalized — confirmed with the user that MIDESA's
`estado_solicitud` text, including accents/capitalization, is exact and stable, so
`ESTADO_EN_ESPERA_CONSTANCIA` matching by plain string equality is safe. Every non-date/int/float
field is coerced to `str` in `_row_to_dict()` regardless of the type Excel/openpyxl handed back
(guards against exactly the `No. Presolicitud`-as-int case above blowing up `.strip()` calls).

The uploaded file is always supplied manually by the user; its filename is irrelevant. For every
row, match on (`cliente.cedula`, `caso.clave_caso`):
- No match → insert a new cliente (if the cédula is new — this is what makes Alerta 1 eligible)
  and a new caso. `estado_solicitud_fecha_cambio` is set to "now".
- Match found → **update** the existing caso's fields from the row (Excel is the source of truth
  for its own columns on every reimport, including `estado_solicitud`/`etapa_proceso`). Before
  overwriting `estado_solicitud`, compare old vs. new value:
  - If it changed at all, reset `estado_solicitud_fecha_cambio` to "now".
  - If the old value was `ESTADO_EN_ESPERA_CONSTANCIA` ("En espera de constancia") **and** the new
    value is specifically `ESTADO_EN_PROCESO` ("En proceso") — not just "any different value" —
    additionally stamp `constancia_recibida_fecha` = now. Confirmed with the user: transitioning
    to any other state (e.g. "No aplica", "Cliente desistió") does not start this clock. This is
    the *only* way constancia-received is detected (no manual step), and it starts the 48h
    response clock for the "Constancia en mano" alert (see Alerts section below).

All case dates that the Excel actually provides (`fecha_registro`, `fecha_ultima_gestion`, etc.)
come from the Excel's own date columns — never from the moment the file happens to be imported.

## Manual editing vs. reimport

The user edits `estado_solicitud` and `etapa_proceso` directly in the app during daily follow-up,
without touching Excel. Because reimporting later overwrites these same columns from the Excel
(see above), the expected behavior is: manual edits are authoritative until the next reimport
brings a newer value from MIDESA, at which point Excel wins. `origen_ultima_modificacion` records
which side made the last change, for troubleshooting. A manual edit to `estado_solicitud` also
resets `estado_solicitud_fecha_cambio` to "now", same as an import-detected change.

## Configuración (agente actual)

The **Configuración** tab (`gestor_credito/ui/configuracion_panel.py`) lets the user set their own
agent name (e.g. "fmartinez") into `configuracion('ejecutivo_actual', ...)` via
`gestor_credito/db/configuracion.py` (`obtener_valor`/`guardar_valor`, keyed by
`CLAVE_EJECUTIVO_ACTUAL`). This is a single global setting, not per-session.

Once set, it scopes two independent things (don't conflate them):
- **Casos tab default view**: with no search term typed, only casos whose `ejecutivo` matches
  `ejecutivo_actual` are shown. A specific search (by cédula or nombre — see Filters below)
  *overrides* this and searches across all agents, on the theory that the user is explicitly
  looking for a specific person regardless of who's handling their case.
- **Alerta 1 and Alerta 2** (not yet implemented) will only ever surface cases/clientes whose
  associated `caso.ejecutivo` matches this value — cases for other agents in the same imported
  Excel are filtered out of alerts entirely (not deleted, just not alerted on). For Alerta 1
  (client-level), match via the ejecutivo of the caso that introduced that cliente.

The **Excel import UI also lives on this tab now** (moved from a former standalone "Importar" tab
— see "UI implemented so far" below for why), since importing and configuring your agent are both
one-time/infrequent setup actions, unlike the Casos tab which is the daily-use screen.

## Alerts / workflow

Implemented in `gestor_credito/db/alertas.py` (pure query functions, no UI) and surfaced by
`gestor_credito/ui/notificaciones_panel.py` (`NotificacionesPanel`, the **Notificaciones** tab).
Three alerts, all scoped to the configured `ejecutivo_actual` (like the Casos tab's default view)
and computed **live** from `cliente`/`caso` state on each refresh — never stored as separate alert
rows. A client/case can have more than one active at once; they don't suppress each other. Time
thresholds are computed with SQLite's `julianday('now')` (always UTC), not Python's
`datetime.now()`, to avoid mixing UTC-stamped columns (`datetime('now')` defaults) with local time
and silently shifting every threshold by the local UTC offset.

**General rule for all three, confirmed with the user after a real bug report**: the start-of-count
timestamp is set the FIRST TIME the system detects the cliente/caso entering the relevant state —
whether it witnessed a live transition during an import, or the record already arrived in that
state the very first time it was imported — and that timestamp is NEVER recalculated by a later
reimport that doesn't actually change anything; it only resets when the state genuinely changes.
If every daily reimport reset the clock for unchanged cases, no alert would ever fire. This is why
alerts 1 and 2 use `cliente.fecha_creacion` / `caso.estado_solicitud_fecha_cambio` respectively —
both are stamped once at INSERT and only touched again on a real value change (see Import behavior
above and `actualizar_edicion_manual` in `db/casos.py`) — never anything importer/transition-specific.

1. **Documentos pendientes** (`alertas_documentos_pendientes`, per `cliente`): active while
   `documentos_completos_fecha IS NULL`, ≥24h have passed since `cliente.fecha_creacion`, **and**
   the cliente has at least one caso whose `estado_solicitud` is not in `ESTADOS_CERRADOS`
   (Desembolsada / No aplica / Cliente desistió — same closed-set already used by
   `FILTRO_ALERTA_DOCUMENTOS_PENDIENTES` in `db/casos.py`). **This estado_solicitud exclusion was
   added 2026-07-08 after a real production bug**: originally this alert fired "regardless of
   estado_solicitud" by design, which meant a cliente whose only credit was already Desembolsada —
   obviously already had complete documents to get there — kept alerting forever if nobody had ever
   clicked the checkbox for them; 42 such stale alerts had piled up for one agent alone in real
   production data (118 total, dropping to 25 after the fix). If a cliente has at least one *other*
   still-open caso, the alert still fires normally — only clients with ALL their casos closed are
   excluded. Does **not** turn off by itself after 48h or any later point once active — it keeps
   firing every time the alert list is recomputed, indefinitely, until the user marks
   `documentos_completos_fecha` via `marcar_documentos_completos()` (button "Marcar documentos
   completados" in Notificaciones; in Casos, either the "Documentos completados (cliente)" checkbox
   in the edit panel, or — the safer, deliberate path, see below — "Marcar documentos completados
   (cliente)" in the context menu), which turns it off permanently for that cliente — or reactivates
   it again via `marcar_documentos_pendientes()` (Casos context menu, see UI section below). The
   `ejecutivo` used to scope this alert is read from the *first* caso that introduced that cliente
   (`MIN(fecha_creacion_registro)`, tie-broken by `MIN(id)`), since `documentos_completos_fecha`
   lives on `cliente`, not `caso`. **Known gap, not yet fixed**: `marcar_documentos_pendientes()`
   only clears `documentos_completos_fecha`; it doesn't touch `cliente.fecha_creacion`, so after a
   revert-to-pendiente the alert reuses the ORIGINAL creation date as "since when pending" (likely
   already far in the past) instead of the revert moment — the alert still fires correctly (arguably
   immediately, which is probably fine), but the "Desde" time shown in Notificaciones would read
   e.g. "hace 45 días" instead of reflecting the actual revert. Would need a dedicated
   `documentos_pendientes_desde` column (schema migration) to fix properly — flag to the user if it
   comes up before fixing.

   **Auto-completion on desembolso (added 2026-07-11)**: the 2026-07-08 exclusion above stops the
   *alert* from firing for a cliente whose casos are all closed, but it never actually set
   `documentos_completos_fecha` — a cliente whose only credit reached Desembolsada sat with that
   column NULL forever, silent but never actually resolved. Real user report: trying to toggle this
   by hand for a Desembolsada caso (Miguel Ángel Sevilla, IMMSA) didn't work because the checkbox is
   deliberately hidden for closed casos (see `_on_seleccionar_caso` in `casos_panel.py`) — the
   context menu items still work for closed casos, but the underlying gap (nothing ever closes the
   field automatically) was real: 78 real production clients had a Desembolsada caso with
   `documentos_completos_fecha` still NULL. Fixed with `completar_documentos_por_desembolso(conn,
   cliente_id)` in `db/alertas.py`: sets `documentos_completos_fecha = datetime('now')` **only if
   still NULL** (never overwrites a real, earlier completion date) whenever a caso reaches
   `ESTADO_DESEMBOLSADA`. Called from both write paths that can produce that transition:
   `actualizar_edicion_manual()` in `db/casos.py` (covers "Guardar cambios", "Cambiar estatus de
   solicitud", and "Cambiar estado a desembolso" — all three route through it) and
   `_upsert_caso()` in `importer/excel_importer.py` (covers both a caso inserted already-Desembolsada
   on first import, and an existing caso updated to Desembolsada on reimport). The 78 pre-existing
   clients were backfilled once by hand (not a schema migration, just a data UPDATE via this same
   function) — their `documentos_completos_fecha` reads today's backfill date, not the real
   historical desembolso date, since that was never recorded anywhere. The other ~14 clients with
   all-closed casos but *no* Desembolsada among them (e.g. only "No aplica"/"Cliente desistió") were
   deliberately left NULL — they never actually disbursed, so marking their documents "completed"
   would be factually wrong; they stay correctly excluded from the alert by the 2026-07-08 rule
   regardless.

   **Second real production incident, same day**: the Casos edit-panel checkbox writes to the
   database immediately on check (`EVT_CHECKBOX`), with no separate confirm step, and reaching it
   with Tab during normal NVDA navigation is easy to do by accident — combined with the filtered
   list not refreshing after marking (a second bug, now fixed in both the checkbox and the new menu
   item below), several real unrelated clients got silently marked "documentos completados" over a
   session without the user noticing, until an unrelated action finally refreshed the list and they
   all vanished at once. **Fix, per explicit user decision**: the checkbox itself was left exactly
   as-is (the user wants it kept for a sighted user to be able to use) — instead, the context menu
   gained a new **"Marcar documentos completados (cliente)"** item next to the pre-existing "Marcar
   como pendiente de completar documentos", giving a deliberate menu-navigate-then-Enter path that
   doesn't risk an accidental Tab+Space trigger. This is the path the user (blind, tests with NVDA)
   actually uses now. Don't remove or auto-fire the checkbox without asking first.

   **Same-day visual/audio addition**: `CasosPanel` now highlights, in the main Casos list, any row
   matching this same "still pending, not closed" criterion (`CasosPanel._documentos_pendientes()`)
   with a light-red background (`wx.Colour(255, 214, 214)`) and dark-red text
   (`wx.Colour(139, 0, 0)`) — contrast ≈7.5:1, passes WCAG AAA, verified by hand; don't change these
   two colors without re-checking contrast. For the blind user, since color alone isn't an
   accessible equivalent (WCAG 1.4.1), landing on such a row with the keyboard/NVDA (any
   `EVT_LIST_ITEM_SELECTED`, i.e. arrows, Tab, or click) plays `documentoPendiente.wav`
   (`SONIDO_FILA_DOCUMENTOS_PENDIENTES` in `ui/sonido.py`) — a *different* file from
   `datosPendientes.wav` (`SONIDO_DOCUMENTOS_PENDIENTES`), which is the one-shot sound Notificaciones
   plays once on open/refresh if any alert of this type exists; this new one is a per-row navigation
   cue local to Casos, explicitly requested as the auditory equivalent of the red highlight.
2. **Constancia pendiente** (`alertas_constancia_pendiente`, per `caso`): active while
   `estado_solicitud == ESTADO_EN_ESPERA_CONSTANCIA` and ≥7 days have passed since
   `estado_solicitud_fecha_cambio`. Turns off as soon as a reimport (or manual edit) changes
   `estado_solicitud` away from "En espera de constancia" (which resets
   `estado_solicitud_fecha_cambio`, see Import behavior above).
3. **Constancia en mano** (`alertas_constancia_en_mano`, per `caso`): active while
   `estado_solicitud == ESTADO_EN_PROCESO` and ≥48h have passed since `estado_solicitud_fecha_cambio`
   — same mechanism as Alerta 2, just a different target state/threshold. **Previously** used a
   separate `constancia_recibida_fecha` column, stamped only when the importer *witnessed* the "En
   espera de constancia" → "En proceso" transition live within one import; a caso imported for the
   first time already at "En proceso" (constancia already in hand before it ever reached this app)
   never got that column stamped, so it silently never alerted no matter how long it sat unanswered
   — a real bug the user hit and reported. Fixed by reusing `estado_solicitud_fecha_cambio` (which
   already satisfies the general rule above) instead. Being scoped strictly to
   `estado_solicitud == ESTADO_EN_PROCESO` also means the previous "assumption, not confirmed" about
   `ESTADO_DESEMBOLSADA` turning this off is moot now — the alert stops the moment `estado_solicitud`
   changes to ANYTHING else, not just Desembolsada. The `constancia_recibida_fecha` column still
   exists in the schema and the importer still stamps it on that specific transition (informational/
   historical only) — nothing queries it for alerting anymore. The Casos tab's "Filtrar por alerta"
   combobox (`FILTRO_ALERTA_CONSTANCIA_EN_MANO` in `db/casos.py`) had the identical bug and got the
   identical fix (checks `estado_solicitud == ESTADO_EN_PROCESO` directly, still with no time
   threshold, per its own by-design difference from the Notificaciones alert).

All three play a WAV sound via `gestor_credito/ui/sonido.py` (`reproducir_sonido()`, using
`wx.adv.Sound` — silently does nothing if the file isn't present yet, so a missing sound never
crashes the app or blocks NVDA) and surface only inside the **Notificaciones** tab (one grouped
`wx.ListCtrl`, columns Tipo de alerta/Nombre/Identificación/Caso/Desde — never individual popups),
consistent with the no-popups UI rule above. Sound filenames, agreed with the user, live in
`gestor_credito/assets/sonidos/` (a subfolder of assets, separate from `logo.png`):
`datosPendientes.wav` (documentos pendientes), `alerta.wav` (constancia pendiente),
`alertaMaxima.wav` (constancia en mano). These `.wav` files are real audio assets the user
supplies directly (like `logo.png`), not something generated by Claude Code.

Like Casos, `NotificacionesPanel.recargar()` is called automatically by `MainFrame` whenever the
Notificaciones tab becomes active (`EVT_NOTEBOOK_PAGE_CHANGED`), plus on an explicit "Actualizar"
button — there is no background timer/scheduler checking on a fixed clock (e.g. 09:00/16:00); the
list is only as fresh as the last time the tab was opened or refreshed. Flag if a background
schedule turns out to be required instead.

**Not yet implemented / out of scope of the above**: a separate "amarilla" alert (7 days without
an update while `etapa_proceso == "Completar expediente / requisitos"`) and "roja" alert (3 days
in `etapa_proceso == "Desembolso"`) were mentioned by the user as already-defined elsewhere:
neither exists yet in this codebase (no schema column tracks "since when has etapa_proceso held
its current value" the way `estado_solicitud_fecha_cambio` does for Estado Solicitud), and the
user asked for them to be left alone in this round of work. Don't assume they exist.

## Filters and reporting

The Casos tab has **one combined search box** (cédula or nombre — not separate fields, and no
ejecutivo/fecha filters anymore; those were removed once `ejecutivo_actual` in Configuración took
over as the default scope). Implemented by `gestor_credito/db/casos.py`'s `buscar_casos()`, with
term classification in `clasificar_termino_busqueda()`:

- Empty search box → filter by `ejecutivo_actual` (or show everything if no agent is configured
  yet).
- Term contains a digit → treated as a **cédula** search (partial/substring match). Real cédulas
  can end in a letter (e.g. `"2011307810010Q"`), so the rule is "has at least one digit", not
  "only digits" — a plain digit-only cédula still matches this branch fine.
- Term is letters only (including Spanish accented vowels and ñ) → treated as a **nombre** search
  (partial/substring, case-insensitive via Python's `str.upper()` — deliberately *not* using
  SQLite's `UPPER()`, which is ASCII-only and would silently fail to case-fold `ñ`/accented
  vowels). Accents are matched exactly, not folded: searching `"pena"` will *not* find `"PEÑA"` —
  confirmed with the user this is intentional (no fuzzy/guessing behavior on accents).
- Any other content (symbols, mixed garbage) → `clasificar_termino_busqueda()` raises `ValueError`
  with a user-facing message; `CasosPanel` catches it and shows it via the status bar instead of
  running a query.
- A cédula/nombre search **ignores `ejecutivo_actual` entirely** — it searches across every
  agent's casos, by design (see Configuración above).
- Zero results (search or default view) shows "No se encontraron resultados." on the status bar
  rather than silently leaving the list empty.

Monthly reporting (not yet implemented) will export to Excel via
`gestor_credito/export/excel_export.py`, with its own "Todos los agentes" vs. one-specific-agente
selector — independent of `ejecutivo_actual`, which only scopes the Casos tab's default view and
alerts, not reports.

## UI implemented so far

`MainFrame` hosts a `wx.Notebook` with three tabs, in this order (`gestor_credito/ui/main_frame.py`):
**Casos** (the daily-use screen), **Notificaciones** (the alerts list — see Alerts/workflow above),
and **Configuración** (one-time/infrequent setup — agent name + Excel import). There used to be a
separate, standalone "Importar" tab; it was folded into Configuración because importing and
setting your agent are both setup actions, not something you do while working a case, and the user
wanted fewer top-level tabs. `MainFrame` binds `EVT_NOTEBOOK_PAGE_CHANGED` so both Casos and
Notificaciones recompute their live data (`recargar()`) every time the user switches into them —
neither tab is a one-shot load-on-init screen.

- **Casos** (`casos_panel.py`): a single combined search box above a `wx.ListCtrl` showing
  16 columns, in this exact order (user-specified, matches `buscar_casos()`'s internal `SELECT`
  order in `gestor_credito/db/casos.py` — keep the two in sync if either changes): Fecha Registro, No.
  Presolicitud, Ejecutivo, Empresa Convenio, Nombre del Cliente, Identificación, Teléfono, Monto
  Solicitado, Destino del Crédito, Microseguro, Estado Solicitud, Etapa Proceso, Responsable
  Actual, Decisión, Motivo No Aplica / Desistimiento, Observaciones. **NVDA note**: an earlier
  version showed only 3 columns because a 7-column row was read by NVDA as one run-on concatenated
  string when arrowing through the list — confirmed with the user this was actually fine once the
  column count didn't include unnecessary noise and they knew about NVDA's `Ctrl+Alt+Arrow`
  per-cell table navigation; the user then explicitly asked for the full 16-column view back, so
  this row-reading behavior is accepted/expected now, not a bug.
- **Empty cells show the literal text `"Celda vacía"`** (`CasosPanel.CELDA_VACIA`), not a true
  blank string. This reverses an earlier decision (blank with no placeholder) — in practice, for
  sparse fields like Motivo No Aplica/Desistimiento (only ~13 of 135 real casos have a value,
  since it only applies when Estado Solicitud is "No aplica" or "Cliente desistió"), NVDA reading
  a truly empty cell just repeats the column header with no value read after it, which the user
  experienced as confusing noise ("sounds like it's saying the same thing for every row"). The
  fix is applied uniformly to every column in `_fila_a_columnas()`, not just the one that
  triggered the report, so the same class of confusion doesn't recur elsewhere (Decisión,
  Teléfono, Observaciones, etc. can all legitimately be blank too).

  Selecting a row loads it for editing: a one-line confirmation ("Editando: {nombre} — Cédula {x}
  — No. Presolicitud {y}") plus Estado Solicitud and Etapa Proceso as closed `wx.Choice` dropdowns
  populated from `gestor_credito/catalogos.py` (`ESTADOS_SOLICITUD`/`ETAPAS_PROCESO` — the real
  fixed lists from `02_Catalogos`), not free text — this is what keeps `estado_solicitud`
  guaranteed to exactly match `ESTADO_EN_ESPERA_CONSTANCIA`/`ESTADO_DESEMBOLSADA` after a manual
  edit. If a caso's current value isn't in the catalog (bad/legacy data), the dropdown just shows
  no selection rather than crashing (`_seleccionar_en_choice` uses `FindString`, which returns
  `wx.NOT_FOUND` safely). "Guardar cambios" calls `actualizar_edicion_manual()`, which never
  touches `constancia_recibida_fecha` (only the importer sets that).

  **Real production incident, confirmed by the user (2026-07-07)**: the "Documentos completados
  (cliente)" checkbox writes to the database immediately on check (`EVT_CHECKBOX`), with no
  separate confirm step — unlike Notificaciones' "Marcar documentos completados", which requires
  selecting a row *and* clicking a separate button. Reaching the checkbox with Tab and landing on
  it is normal keyboard/NVDA navigation, and accidentally hitting Space on it silently commits
  "documents received" for a real client with no undo from that panel. This combined with a second
  bug — the filtered list wasn't refreshed after marking, so a marked case kept showing in
  "Documentos pendientes" with no visible change — meant several real, unrelated clients got marked
  complete by accident over a session without the user noticing, until an unrelated action (Guardar
  cambios) finally refreshed the list and they all vanished at once, looking like one action had
  wrongly mass-marked 10 people. **Fix, per explicit user decision**: the checkbox itself stays
  exactly as-is (immediate on-check write, no confirm step) — the user wants it left alone for a
  sighted user to be able to use it. Instead, the context menu (`_construir_menu_contextual`) got a
  new **"Marcar documentos completados (cliente)"** item, next to the pre-existing "Marcar como
  pendiente de completar documentos", so a deliberate menu navigation + Enter is available as the
  safe path — this is the one the user (blind, tests with NVDA) actually uses now that they know
  the checkbox can trigger by accident. Both the checkbox and the new menu item now call
  `self._cargar_casos()` right after writing, so the list refreshes immediately either way — that
  refresh gap was a real bug regardless of which path is used, fixed for both. If a similar
  "changed without asking" report comes up again for this checkbox, don't touch it without asking
  first — the checkbox behavior itself is confirmed intentional, not an oversight.

  **Second real production report (2026-07-11)**, after a week of live use: even via the "safe"
  menu path above, the user occasionally found the wrong cliente had been marked documentos
  completados — not the one they had active. Investigated at the code level first (selection
  tracking in `casos_panel.py` and `marcar_documentos_completos()` in `db/alertas.py`) and
  confirmed both are correct: `wx.ListCtrl` selection events fire synchronously (verified
  empirically — `SetItemState`/`InsertItem`/`DeleteAllItems` don't leave any async gap where
  `_cliente_seleccionado_id` could lag behind the actual selection), the DB write always targets
  the exact `cliente_id` passed in, and `_seleccionar_casos()`'s `ORDER BY` is stable, so no
  reordering happens from marking alone. Confirmed with the user this happens through **both** the
  checkbox and the menu item, and **not** only when "Filtrar por alerta: Documentos pendientes" is
  active — ruling out a filtered-list-reshuffle explanation too. Root cause not reproducible at the
  code level (most likely a timing gap between what NVDA has announced and what the user acts on,
  e.g. arrow-key repeat overshoot — outside the app's control). **Fix**: `_on_marcar_documentos_completos_menu`
  now shows a `wx.MessageBox` confirmation naming the exact cliente ("¿Marcar a {nombre} — Cédula
  {x} — como documentos completados?") before writing, same YES/NO pattern as
  `_eliminar_caso_seleccionado`/`_eliminar_cliente_seleccionado` — this is the safety net regardless
  of the underlying cause: NVDA reliably announces `wx.MessageBox`, so the user gets one more
  checkpoint to catch a mismatch before it's written, not after. **The checkbox was deliberately
  left untouched again** — confirmed with the user this time too: adding a confirm step there would
  reverse the earlier explicit "keep it one-step" decision, so only the menu item changed.
- **Notificaciones** (`notificaciones_panel.py`): see Alerts/workflow above for the full design.
  One `wx.ListCtrl` ("Lista de alertas activas") grouping all three active alert types, an
  "Actualizar" button, and a "Marcar documentos completados" button that's only enabled when the
  selected row is a "Documentos pendientes" alert (mirrors the selection-driven edit panel in
  Casos). Marking calls `marcar_documentos_completos()` and immediately recomputes the list.
- **Configuración** (`configuracion_panel.py`): the agent picker went through three iterations —
  worth knowing the history if a similar "can't change X" report comes up elsewhere:
  1. An editable `wx.ComboBox` pre-populated with `obtener_ejecutivos()` as suggestions — dropped
     after the user reported being unable to switch to a different agent once one was saved
     (editable combo boxes are a known trouble spot for screen readers: ambiguous whether you're
     typing free text or navigating the dropdown history).
  2. A plain `wx.TextCtrl` plus a separate **read-only** label listing known agents — fixed the
     ComboBox ambiguity, but the user then reported this *still* didn't let them actually switch
     agent: the label was just informational text, not something you could act on, so you had to
     already know and retype the exact agent name by hand.
  3. **Current design**: a single closed `wx.Choice` ("Escoge un agente", populated from
     `obtener_ejecutivos()` — every agent comes from the imported bitácora, so free-text entry
     isn't needed at all) plus one "Guardar y usar este agente" button that saves
     `agentes_choice.GetStringSelection()` straight to `ejecutivo_actual`. The currently configured
     agent is pre-selected on load (`FindString` + `SetSelection`, safely falling back to no
     selection via `wx.NOT_FOUND` if it's not in the list). **Enter-key bug**: with focus in a
     native Windows `wx.Choice`, Enter is consumed by the OS combobox before a plain
     `EVT_KEY_DOWN` handler on the control ever sees it — confirmed by testing `EVT_KEY_DOWN`
     directly on `agentes_choice`, which did nothing. Fixed by binding `wx.EVT_CHAR_HOOK` on the
     panel itself (which intercepts the keystroke earlier, before the native control swallows it)
     and checking `wx.Window.FindFocus() is self.agentes_choice`. If Enter silently does nothing in
     some *other* control later, suspect this same native-control-eats-the-key issue first.
  Also here: the Excel import UI (file picker + "Importar" + read-only result text area) that used
  to be its own standalone tab.

Judgment calls made while building this that are worth the user's attention:

- **File selection uses `wx.FileDialog`** (a native, OS-level, already-screen-reader-accessible
  modal) despite the "no popups" rule. That rule is read as targeting *in-app* modals (confirmations,
  message boxes, notification popups) that would otherwise duplicate/disrupt tab navigation — not
  the standard OS file-open dialog, since there's no in-app alternative for browsing the filesystem
  that would be more accessible. Flag if this reading is wrong.
- **The logo's accessible name must be inaudible/invisible to sighted users.** `AppLogo` exposes
  the required alt text only via `SetName()` (the MSAA/UIA accessible name NVDA reads) — it must
  **never** also be set via `SetToolTip()`, which draws a large visible balloon on hover. That was
  a real bug found during NVDA testing and is now fixed; don't reintroduce it. The real logo file
  (`gestor_credito/assets/logo.png`) is 2048x2048px, so `AppLogo` scales it down to `DISPLAY_SIZE`
  (32px) before rendering — never show the source bitmap unscaled, it would dominate the window.
  **`SetName()` doesn't actually work — anywhere in this app (found + fixed 2026-07-11)**: real
  user report — NVDA landed on the logo and announced only the role ("gráfico"), no name at all.
  This turned into a full accessibility audit once the same root cause turned up on other controls
  too; see `gestor_credito/ui/accesibilidad.py` for the fixes. **How it was verified** (don't take
  this on faith, the tooling is cheap to rebuild): temporarily `pip install pywinauto comtypes`
  (diagnostic only, never added to `requirements.txt`), then either (a) `pywinauto`'s
  `Desktop(backend="uia")` + `print_control_identifiers()` for a quick tree dump, or (b), more
  authoritative since it's the exact interface NVDA queries for a classic wx/Win32 app,
  `oleacc.AccessibleObjectFromWindow` via `comtypes` to call the real `IAccessible.accName`/
  `accRole`/`accState` directly on a control's HWND. UIA inspection can look fine while raw MSAA is
  still broken (or vice versa) — when in doubt, check both.
  - **The name bug**: `wx.Window.SetName()` does not propagate to the real accessible name for
    *any* control type tested — static (`wx.StaticBitmap`, `wx.StaticText`) or interactive
    (`wx.ListCtrl`, `wx.TextCtrl`, `wx.Choice`, `wx.TreeCtrl`). Windows silently falls back to its
    own "nearest preceding STATIC label by creation order" heuristic, which sometimes happens to
    read fine (a `wx.Choice` right after its own `wx.StaticText` label) and sometimes doesn't — the
    Casos results list (`self.lista`, code says `SetName("Lista de casos")`) was actually being
    announced as **"Buscar"**, borrowed from the nearest unrelated GroupBox, confirmed with raw
    MSAA. **Fix**: `nombre_accesible(control, nombre)` in `accesibilidad.py` — calls `SetName()`
    still (harmless) but the part that actually works is `control.SetAccessible(_SoloNombreAccesible(...))`,
    a `wx.Accessible` subclass overriding **only** `GetName`. Verified empirically that leaving
    `GetRole`/`GetState` unoverridden preserves the control's native role/state correctly (tested
    against a real `wx.ListCtrl`: name fixed, role stayed `ROLE_SYSTEM_LIST`, state untouched) —
    don't override those for a real native control, only for a decorative one (see next point).
    Every `.SetName(...)` call site in the codebase was migrated to `nombre_accesible(...)`.
  - **The logo's second bug, found only via real NVDA (fixing the name wasn't enough)**: even
    with the name correct at the MSAA level, the user's actual NVDA still couldn't reach it —
    `wx.StaticBitmap`/`wx.StaticText` don't accept keyboard focus by default, so the logo was
    invisible to Tab navigation (which is how the user reaches literally everything else in this
    app) and apparently not surfaced by NVDA's object-navigation fallback either, without resorting
    to a non-default NVDA cursor. Also, `wx.StaticBitmap`'s native role/state MSAA implementation is
    itself broken/empty (unlike a normal control) — a raw UIA check with only `GetName` overridden
    showed the control's type silently degrade from "Image" to a generic "Pane". **Fix**: `logo.py`
    defines `_LogoBitmap`/`_LogoTexto` (subclasses of `wx.StaticBitmap`/`wx.StaticText` overriding
    `AcceptsFocus`/`AcceptsFocusFromKeyboard` to return `True`, confirmed via simulated Shift+Tab
    that focus actually lands on the HWND now) plus `_NombreAccesible` (a **local**, more complete
    `wx.Accessible` override than the generic helper above — also supplies `GetRole` returning
    `wx.ROLE_SYSTEM_GRAPHIC` and `GetState` returning `ACC_STATE_SYSTEM_FOCUSABLE`/`_FOCUSED`, since
    the native implementation can't be trusted here). Confirmed fixed against the user's real NVDA.
    Visual side effect, accepted: a sighted user tabbing through now sees a standard focus rectangle
    around the small logo — no visible text, alt text still fully inaudible/invisible per the rule
    above, just a focus outline like any other tab stop.
  - **Silent status bar changes, also found via real NVDA use**: filtering Casos by alert type
    ("Filtrar por alerta": Documentos pendientes, En espera de constancia, etc.) updates the
    "N caso(s) encontrados" status bar text, but — per the general SetStatusText limitation already
    documented above — NVDA never announced it, and the user had no way to know the count without
    manually navigating to check. A `wx.MessageBox` per filter change was already rejected earlier
    for this exact combobox (`_cargar_casos` in `casos_panel.py`: `EVT_CHOICE` fires on every
    arrow key while navigating it, so a modal per keystroke made the filter unusable). **Fix**:
    `anunciar_texto_estado(status_bar)` in `accesibilidad.py`, called right after every
    `SetStatusText()` — fires the MSAA `EVENT_OBJECT_LIVEREGIONCHANGED` event (via
    `user32.NotifyWinEvent`, the same mechanism browsers use for `aria-live="polite"`) targeted at
    the status bar's first field (verified with raw MSAA: the status bar object itself always
    reports `accName=None`; the actual text lives on child id 1). This doesn't steal focus and isn't
    modal, so it's safe to fire unconditionally on every status change, not just explicit searches.
    Wired into both places `SetStatusText` is exposed to child panels: `MainFrame.SetStatusText`
    (new override; previously just inherited `wx.Frame`'s, silently) and `_PanelDialog.SetStatusText`
    (the manual status bar wrapper used by the Notificaciones/Configuración/Ayuda modal dialogs —
    see architecture note below). Confirmed to fire without error; full live-announcement behavior
    depends on the user's real NVDA (a synthetic test rig can't "hear" speech output), so this one
    still wants a real-world confirmation pass, unlike the name/focus fixes above which were
    verified directly against the user's actual screen reader.

  **That real-world confirmation came back negative (2026-07-11)**: the user reported the status
  bar's live-region announcement (`anunciar_texto_estado`) simply isn't heard in practice on the
  Casos tab's "Filtrar por alerta" combobox (`filtro_alerta_choice`) — neither while arrowing
  through options nor after landing on one. The user also clarified the *wanted* behavior is more
  specific than "announce on every change": arrowing through options should only get NVDA's own
  native announcement of the option name (already free, since `wx.Choice` is a real native
  combobox), and a *separate*, explicit announcement of the real filtered case count should fire
  only once the user commits a choice with Enter — not on every arrow keystroke. **Fix**:
  `anunciar_voz_nvda(texto)` in `accesibilidad.py` — instead of relying on NVDA noticing an MSAA
  live-region event on some object, this calls straight into NVDA's own public API for external
  (non-add-on) applications, `nvdaController_speakText` in `nvdaControllerClient(32|64).dll`,
  found documented in the NVDA add-on manual the user placed at the project root ("manual creación
  de complementos.docx") — that's the officially documented mechanism for a program that lives
  outside NVDA's own process (unlike an add-on, which would use `ui.message()` from inside NVDA)
  to make NVDA speak a string immediately, with no dependency on focus, roles, or NVDA's live-region
  heuristics. Verified empirically end-to-end (not just import-level) before trusting it: NVDA is
  actually running on the dev machine, `nvdaController_testIfRunning()` returns 0, and
  `nvdaController_speakText()` returns 0 (success) both from a standalone ctypes call and from
  inside a real `CasosPanel` instance with a real DB connection and a simulated Enter keypress —
  audible confirmation from the user's actual NVDA is still the last word, same caveat as
  `anunciar_texto_estado` above, but this path no longer depends on an NVDA heuristic that's
  already been reported not to fire. The `.dll` files are **not** part of a normal NVDA
  installation (confirmed by hand: absent from `C:\Program Files\NVDA` on this machine) — they're
  a separate redistributable NV Access publishes for third-party apps to embed in themselves, and
  were pulled here from the `accessible_output2` PyPI package (which bundles them verbatim) into
  `gestor_credito/assets/nvda/` rather than adding that whole package as a dependency — only
  `nvdaController_speakText` was needed, not `accessible_output2`'s full multi-screen-reader
  abstraction layer. Being under `gestor_credito/assets/`, the existing PyInstaller `--add-data`
  flag already picks them up with no packaging changes needed. Wired into `CasosPanel`
  (`casos_panel.py`): `EVT_CHOICE` on `filtro_alerta_choice` is unchanged (still silently reloads
  the list on every arrow key, same as before — needed for a sighted user to see the list update
  live and for `self._filas` to stay in sync with whatever option is currently selected). A new
  `EVT_CHAR_HOOK` on the panel (same native-control-eats-Enter workaround as the agent picker in
  `configuracion_panel.py` — `wx.Choice`'s native Win32 combobox consumes Enter before a plain
  `EVT_KEY_DOWN` on the control would ever see it) checks `wx.Window.FindFocus() is
  self.filtro_alerta_choice`, and if so calls `self._cargar_casos(avisar_sin_resultados=False,
  anunciar_voz=True)` — a new keyword-only escape hatch on `_cargar_casos()` that, after computing
  the exact same status-bar message every other call already computes (`_mensaje_cantidad()`,
  which already names the active filter — "N caso(s) con documentos pendientes", etc., see
  Filters/reporting above), also passes that same string to `anunciar_voz_nvda()`. No other caller
  of `_cargar_casos()` passes `anunciar_voz=True`, so this stays scoped to the one interaction the
  user asked about — arrow-key browsing elsewhere in the app keeps behaving exactly as before.
  `anunciar_texto_estado`/`EVENT_OBJECT_LIVEREGIONCHANGED` was **not** ripped out — it's left in
  place everywhere else in the app (Notificaciones, Configuración, other Casos status-bar updates)
  since only this one interaction was confirmed broken and asked about; if the same "not heard"
  report comes back for another spot, `anunciar_voz_nvda` is the fix to reach for there too, but
  don't swap it in preemptively without a fresh report.

  **Architecture note, found while doing this audit**: the "UI implemented so far" section below
  still describes three `wx.Notebook` tabs (Casos/Notificaciones/Configuración). That's stale — the
  actual current code (`main_frame.py`) has `MainFrame` host Casos directly (no notebook at all) and
  open Notificaciones/Configuración/**Ayuda** (a 4th screen, not documented below either — a
  keyboard-shortcuts reference list) as modal `wx.Dialog`s from a classic Windows menu bar
  ("Herramientas", "Configuración", "Ayuda"), per `_PanelDialog` in `main_frame.py`. This evidently
  changed at some point after that section was last updated, per an explicit comment in the code:
  "pedido explícito del usuario por cómo navega con NVDA." Flagging it here rather than silently
  leaving stale docs — the "UI implemented so far" section needs a real rewrite to match, out of
  scope for this accessibility-audit pass; ask the user before doing that rewrite since it's a
  sizable, separate edit.

## Calculadora de Crédito

A second, independent module (2026-07-11) that replicates the calculation engine of a reference
Excel workbook the user supplied, `recursos/calculadora.xlsx` (git-ignored, real client data —
same treatment as `MachoteBaseDeDatos.xlsx`): given a salary, hire date, requested credit amount,
term and payment frequency — all typed by hand, every time — it computes labor liability (pasivo
laboral), net salary, the level loan installment, labor-liability coverage, and debt-to-income
ratio — the same numbers a loan officer used to work out by hand in that spreadsheet.

**Explicitly kept separate from Casos** — user's words: "en el panel actual no se debe añadir
absolutamente nada [...] esto debe ir separado e independiente para no saturar ni mezclar las
funciones." No file under `casos_panel.py`'s reach references it, and (see "Reverted to a fully
standalone calculator" below) the reverse is also true: this panel doesn't reach into Casos either.

**Navigation went through two iterations, worth knowing if a similar report comes up again**:
1. First built as a menu-triggered modal dialog (`_PanelDialog`, exact same mechanism as
   Notificaciones/Configuración/Ayuda) — seemed consistent with the rest of the app's established
   "no notebook tabs, classic menu bar" pattern (see Architecture note above).
2. **Real user report after trying it**: couldn't find the feature at first (a 4th top-level menu
   easily gets arrow-keyed past when you're used to 3), and separately hit a real bug once found
   (see "Scroll bug" below). User's explicit follow-up request: "lo quiero como otra pestaña no
   como una opción en el menú [...] esto es una función no una configuración, por eso si o si
   tiene que estar en un apartado extra." The user draws a real distinction: Notificaciones/
   Configuración/Ayuda are setup/lookup tools, fine tucked in a menu; the Calculadora is something
   used routinely, so it needs to be a first-class module like Casos itself.
   **Fix**: `MainFrame` now hosts a `wx.Notebook` (`self.notebook`) with exactly two pages, `Casos`
   and `Calculadora de Crédito` — the only tabs in the app; Notificaciones/Configuración/Ayuda stay
   exactly as modal dialogs, unchanged. Both `CasosPanel` and `CalculadoraPanel` must be
   constructed with `self.notebook` as their `parent` (not `self`/MainFrame) — wx.Notebook asserts
   `pPage->GetParent() == this` on `AddPage()`, a real error hit while wiring this up. Switching
   tabs fires `EVT_NOTEBOOK_PAGE_CHANGED`, which calls `recargar()` on whichever panel became
   active — same live-refresh-on-entry pattern documented for the old Casos/Notificaciones
   notebook setup before it was replaced by dialogs. `CalculadoraPanel.recargar()` is deliberately
   light: it only re-reads `convenio_tasa` (in case a rate changed elsewhere) and preserves the
   currently-selected empresa/tasa and every other in-progress field — it must NOT wipe out data
   the user is mid-typing just because they tabbed over to check something in Casos and came back.
   **This reintroduces the exact `wx.Notebook` mechanism the app moved away from once already**
   (see Architecture note above — that move was also "pedido explícito del usuario por cómo navega
   con NVDA", but the specific complaint was never spelled out in this file). Flagging this
   tension rather than assuming it's risk-free: this hasn't been confirmed against the user's real
   NVDA yet the way the dialog-based navigation was. If tab-switching (Ctrl+Tab/Ctrl+Shift+Tab, or
   arrowing the tab strip) turns out to have the same friction that motivated the original move
   away from notebooks, that needs a real report before assuming it's fine.

**Scroll bug, found via real user report (2026-07-11)**: the panel stacks four sections (buscar
caso, datos para calcular, resultados, tasas por convenio) inside a plain `wx.Panel` sized to the
dialog's fixed 820×760 — measured directly (`GetVirtualSize()` vs `GetClientSize()`): content was
858px tall against only 438px of visible client area once title bar/status bar/borders were
subtracted. With a plain `wx.Panel`, content taller than the visible area is just clipped — no
scrollbar, and controls below the fold were effectively unreachable, which is what the user hit
("ahí sale solo como las tasas de interés... donde hago el cálculo?"). **Fix**: `CalculadoraPanel`
now subclasses `wx.lib.scrolledpanel.ScrolledPanel` instead of `wx.Panel`, with
`self.SetupScrolling(scroll_x=False, scroll_y=True)` called right after `SetSizer()`. Don't revert
this to a plain `wx.Panel` even if the notebook page ends up taller than 820×760 in practice —
there's no guarantee every future addition to this panel fits in one screen, and clipped/
unreachable content is a real accessibility failure (WCAG 2.1.1), not just a cosmetic issue.

**Second occurrence of the same symptom, different root cause (found + fixed 2026-07-12)**: after
the panel moved from modal dialog to notebook tab (see Navigation history above), the user reported
with real NVDA that entering the tab with Ctrl+Tab and then Tabbing through it, the only reachable
control was the interest-rate field — "solo me aparece el campo para seleccionar la tasa de
interés... no se muestra ningún elemento de la interfaz para ingresar el salario, los plazos, el
monto ni el botón para calcular el crédito" — nearly the same wording as the 2026-07-11 scroll bug
above, but this time `GetVirtualSize()`/`GetClientSize()` and `Shown`/position were all verified
correct (not a layout/scroll problem). Root cause: `__init__` called
`self._habilitar_entradas(False)` on the nine "Datos para calcular" inputs (empresa, fecha de
ingreso, salario, ingresos extra, monto, plazo, periodicidad, tipo de cambio, deuda activa) plus
`calcular_btn`, only re-enabling them once a caso was selected via search. **A disabled `wx.Window`
does not receive keyboard focus, so Windows Tab navigation silently skips it entirely** — with
nothing selected yet, Tab jumped straight from "Buscar caso" past the entire (disabled)
"Datos para calcular" section and the (non-focusable, plain `wx.StaticText`) "Resultados" section,
landing on "Tasas por convenio", which is always enabled — exactly matching what the user described
as "the only thing I can reach". This wasn't caught earlier because verification only checked
`Shown`/position/size, never `Enabled`, and the app hadn't been tested with a fresh CalculadoraPanel
where no caso had been selected yet. **Fix**: removed `_habilitar_entradas()`/`_controles_entrada`
entirely — the nine input fields and `calcular_btn` are now always enabled/reachable, matching the
pattern already used (and already NVDA-verified) in `casos_panel.py`'s edit panel, where
`estado_choice`/`etapa_choice` are never disabled and only the terminal "commit" buttons
(`guardar_btn`/`eliminar_btn`) are gated on selection. `guardar_btn` here keeps the same
single-button gating (still starts `Disable()`d, only `Enable()`d after a successful Calcular) since
that mirrors the established, already-tested pattern and is a single control, not a whole section —
but it's now also gated on having an actual `caso_id` (`self.guardar_btn.Enable(self._caso_seleccionado_id
is not None)`), since `calculo_credito.caso_id` requires one; Calcular itself never required a caso
(it's pure — see Flow below), so that part was always fine. When Calcular succeeds without a caso
selected, the spoken/status message now adds "Para guardar esta simulación, primero buscá y
seleccioná un caso." so the user isn't left wondering why Guardar stayed disabled. **Lesson for any
future `Enable(False)` on a *block* of input controls in this app**: don't — it removes them from
Tab navigation, which for a screen-reader user is indistinguishable from the controls not existing.
Gating a single terminal action button on prior state is the established, accepted pattern instead.

**Reverted to a fully standalone calculator, no caso/cliente/cédula linkage at all (2026-07-12)**:
the panel used to have a "Buscar caso" section (reusing `buscar_casos()` from Casos to prefill
Empresa/Monto) and a "Guardar simulación en este caso" button writing to `calculo_credito`. The
user explicitly rejected this: *"no estoy de acuerdo con la vinculación que estás haciendo...
elimina por completo cualquier intento de tomar datos de las solicitudes o de la lógica de las
cédulas... este módulo debe ser estrictamente una calculadora de crédito independiente y nada
más."* Both were removed completely — `calculadora_panel.py` no longer imports `buscar_casos` or
anything from `db/calculo_credito.py`. `db/calculo_credito.py` and the `calculo_credito` table
(see Base de datos below) still exist in the codebase — nothing was asked to be deleted there —
but nothing in the UI calls them anymore; they're dead code until/unless a future,
explicitly-requested feature reconnects them. Empresa (`wx.Choice`) is a completely free
selection now, same reason it always had to allow manual override (a caso's `empresa_convenio`
could read `"CAFE LAS FLORES CHAIN"` while the convenio table's real name was `"CAFE LAS FLORES"`
— see `db/convenios.py:obtener_tasa`) — just with no caso to auto-select from anymore.

**Flow (current)**: the officer types every field by hand, every time — empresa (resolves tasa),
fecha de ingreso + salario (pasivo laboral, live — see below), ingresos extra, monto/plazo/
periodicidad/deuda activa (the rest of the credit terms) — then presses Calcular. Nothing is
persisted; this is a scratch tool for exploring scenarios, not a record.

**Pasivo laboral calculates live, without pressing Calcular (2026-07-12)** — user's words: *"no
puedo esperar a presionar un botón de Calcular al final para conocer este dato... con ese valor
determino cuánto dinero tiene disponible el cliente y si es viable ofrecerle un crédito."*
`_actualizar_pasivo_laboral_en_vivo()` is bound to `EVT_TEXT` on `fecha_ingreso_texto` and
`salario_texto` (the only two cells Calculadora!B8 actually depends on — see
`pasivo_laboral.py`) and recomputes on every keystroke, independent of every other field
(empresa/monto/plazo/etc. can all be empty). It's also the single source of truth for the
`resultado_pasivo_laboral` label and for what Ctrl+Shift+Q announces (see below) — `_on_calcular`
calls this same function instead of computing pasivo laboral a second time from
`evaluar_capacidad()`'s result, so there's never a risk of the live value and the
post-Calcular value disagreeing. If fecha/salario are missing or invalid, the label falls back to
"Pasivo laboral: —" rather than showing a stale number.

**Voice-only shortcuts, Ctrl+Shift+Q / Ctrl+Shift+W (2026-07-12)** — user's words: *"para agilizar
la usabilidad... y evitar que el flujo de tabulación se vuelva lento o invasivo con demasiados
campos informativos."* Bound via `wx.EVT_CHAR_HOOK` on the panel itself (same mechanism as the
`filtro_alerta_choice` Enter workaround in `casos_panel.py`, but here deliberately WITHOUT a
`FindFocus()` check — it must fire no matter which control currently has focus):
- **Ctrl+Shift+Q**: speaks the current pasivo laboral (dólares y córdobas) via `anunciar_voz_nvda()`
  — the same live-tracked value described above, not a stale one from the last Calcular.
- **Ctrl+Shift+W**: speaks the salario con deducciones from the last Calcular (`_ultimo_resultado`
  — this one is NOT live yet, only Pasivo laboral was asked to be; flag if the user wants Ctrl+Shift+W
  to become live too).
Neither moves keyboard focus — `anunciar_voz_nvda()` calls straight into NVDA's speech API, it
doesn't touch any control — which was the explicit point: read a result out loud without losing
your place in the form. The result boxes ("Resultados") stay visible on screen for sighted users;
these shortcuts are purely an additional, faster path for screen-reader use, not a replacement.

**Tipo de cambio is a fixed constant, not a field (2026-07-12)** — user's words: *"por el momento
es estrictamente fijo... no va a variar... por ahora déjalo fijo internamente en el código."*
`TIPO_CAMBIO_FIJO = 36.6243` at the top of `calculadora_panel.py` replaces what used to be a
`tipo_cambio_texto` `wx.TextCtrl` the officer typed on every calculation — removed from the UI
entirely (one less field to tab through). The user was explicit this is temporary: a future
Configuración module (not yet requested/built) is meant to let the exchange rate — along with
empresas and tasas por convenio — be edited from one place; don't move `TIPO_CAMBIO_FIJO` there
preemptively before that's actually asked for.

**No thousands separator anywhere in this panel's output (2026-07-12)** — user's words (testing
with real NVDA): *"mi lector de pantalla lee las comas de una manera muy incómoda y frena el flujo
de trabajo... en lugar de mostrar 16,523.23, el formato debe salir estrictamente como 16523.23."*
Every monetary value in `calculadora_panel.py` uses plain `f"{valor:.2f}"` (decimal point only,
digits run together) instead of `f"{valor:,.2f}"` — applies to every result label, the spoken
Calcular summary, and both voice shortcuts. **Scoped to this panel only** (the user's ask was
about "todas las salidas de texto y cajas de resultado de la calculadora", not the app in general)
— `casos_panel.py`'s monto formatting (`f"{monto_solicitado:,.2f}"`) still uses commas and wasn't
touched; don't assume this rule generalizes to the rest of the app without being told.

**Real bug found via user report, NOT a formula error (2026-07-12)**: user reported the cuota for
MIDESA (monto US$1140, plazo 24 meses) came out "excesivamente alto" and asked for a full audit of
every rate against the Excel plus a recheck of the cuota formula itself. Verified the formula
first, rigorously: drove `recursos/calculadora.xlsx` via Excel COM (`ReadOnly=True`, per the
OneDrive/AutoSave lesson above) with those exact inputs (MIDESA, monto=1140, plazo=24, Mensual) —
Excel's own `B14` returned US$59.05, and `evaluar_capacidad()` with the same inputs and `tasa=0.18`
returns the identical value (`59.05328338275904`, matching to 10+ decimal places) — the formula is
correct, not the bug. Then queried the **live** `convenio_tasa` table directly and compared every
row against the Excel's `Convenios` sheet: **MIDESA alone was wrong — 0.70 (70%) in the database
vs. 0.18 (18%) in the Excel**, timestamped the same day, almost certainly a leftover from testing
the "Actualizar tasa" feature before it was removed from this panel (see above) — every other
company matched exactly. Fixed by calling `guardar_tasa(conn, "MIDESA", 0.18)` directly against the
live database (not a code change — the code was never wrong). **Lesson**: when a computed number
looks wrong, verify the formula against Excel via COM *and* check the live data the formula was fed
before assuming which one is broken — here the formula was fine and a single stale row in the
manually-editable table was the actual cause.

**Empresa list now speaks its own rate (2026-07-12)** — directly motivated by the MIDESA incident
above: user's words, *"para estar completamente seguro de qué tasa se está aplicando... necesito
que al navegar por la lista, cada opción muestre y verbalice el nombre de la empresa junto con su
respectivo porcentaje de tasa"* (e.g. "Aceitera El Real: Tasa: 33%"). `_texto_opcion_empresa()`
builds that combined string for every `empresa_choice` item — NVDA already announces a
`wx.Choice` item's own text while arrowing through it, so folding the tasa into the item text was
enough; no new accessibility plumbing needed. This meant `empresa_choice`'s visible/announced text
is no longer the real empresa name, which broke every place that used to read it with
`GetStringSelection()` — replaced with `_empresa_seleccionada()`, which maps the selected *index*
back to the real empresa name via a parallel list (`_empresas_por_indice`, kept in the same order
as the choice items by `_cargar_empresas`). `self.tasa_texto` (the separate "Tasa: X%" label next
to the dropdown) was left in place too — belt and suspenders, not asked to be removed, and it still
serves a sighted user glancing at the screen without navigating the dropdown.

**Confirmation-only "Seleccionada", Ctrl+Shift+E, and a shorter Calcular summary (2026-07-12,
same day, two follow-up rounds)** — three related refinements after the empresa list started
speaking its own rate, all aimed at cutting down repetitive/noisy speech:
- **Enter/Espacio on `empresa_choice`** speaks an explicit confirmation, via the same
  `EVT_CHAR_HOOK` + `wx.Window.FindFocus() is self.empresa_choice` pattern already established for
  `filtro_alerta_choice` (`casos_panel.py`) and `agentes_choice` (`configuracion_panel.py`) — folded
  into the same handler as the Ctrl+Shift+Q/W/E hotkeys below, since only one `EVT_CHAR_HOOK` is
  bound per panel. Arrowing through the list (`EVT_CHOICE`) stays silent on the app's side, same as
  before — NVDA's own native announcement of each item's text (which now includes the tasa) is
  untouched and not something app code can suppress for a standard `wx.Choice` without abandoning
  it for a custom-drawn control (against the project's own accessibility guidance). **Went through
  two iterations on the exact wording**: first attempt spoke `"{empresa}, tasa {tasa}, seleccionada"`
  (repeating the rate) — user reported this as "demasiada información... mucho ruido" after testing,
  since the rate was already just heard while arrowing. **Final form**: `"Seleccionada {empresa}"`
  only, e.g. `"Seleccionada Midesa"`, `"Seleccionada EL ZOCALO"` — no tasa, no trailing punctuation
  read awkwardly by the synthesizer. `_anunciar_empresa_confirmada()` in `calculadora_panel.py`.
- **Ctrl+Shift+E**: new voice-only shortcut, same family as Q/W — speaks only the currently chosen
  empresa's name (`"Empresa: Midesa."`), deliberately without the tasa (user's words: "ese dato ya
  lo revisé en la lista"). Never moves focus, same as Q/W.
- **Calcular's spoken summary dropped the pasivo laboral line** — it used to open with "Pasivo
  laboral: X córdobas." before the cuota/endeudamiento, which the user found redundant now that
  Ctrl+Shift+Q exists specifically for that number; the summary is now just "Cuota calculada: X
  dólares. Nivel de endeudamiento: Y%." The visible result label (`resultado_pasivo_laboral`) is
  untouched — only the *spoken* summary changed.

**Validation errors on Calcular** (missing/invalid fields, empresa with no tasa configured) use
`wx.MessageBox`, matching this app's one established exception to "no popups" — same reasoning as
everywhere else it's used: an inline label wouldn't be proactively announced by NVDA, and this is
the sole indication something's wrong. A **successful** Calcular is different: results go into the
visible result labels AND get spoken directly via `anunciar_voz_nvda()` (not just
`anunciar_texto_estado`'s status-bar live region) — this module was built right after that live
region was confirmed unreliable for exactly this kind of "user pressed a button, needs to hear the
real number back" interaction (see the NVDA speech section under Accessibility below), so it uses
the more reliable mechanism from the start rather than the older, weaker one.

### Base de datos

Two new tables, `caso` untouched:

```sql
convenio_tasa(empresa_convenio PRIMARY KEY, tasa_interes REAL, fecha_actualizacion)
calculo_credito(id, caso_id UNIQUE REFERENCES caso(id), empresa_convenio, tasa_interes,
                fecha_ingreso_empresa, salario_bruto_cordobas, ingresos_extra_cordobas,
                monto_credito_usd, plazo_meses, periodicidad, tipo_cambio, deuda_activa_cordobas,
                pasivo_laboral_cordobas, salario_neto_cordobas, cuota_usd,
                cobertura_pasivo_laboral, nivel_endeudamiento, fecha_calculo)
```

- `convenio_tasa` replaces the Excel's "Convenios" sheet — seeded once (`INSERT OR IGNORE`, so a
  manually-edited rate is never clobbered on restart) with the 29 real companies/rates extracted
  from that sheet; user confirmed (2026-07-11) they're still current. Two of those 29
  (`GRUPO TALSE`, `LABORATORIOS ROMAN`) had no rate in the source Excel either — seeded with
  `tasa_interes = NULL` on purpose rather than inventing a number; `obtener_tasa()` returns `None`
  for "empresa known but no rate assigned" same as "empresa not known at all", and the panel
  refuses to Calcular until the officer assigns one via the "Tasas por convenio" section.
- `calculo_credito` is **one row per caso** (`UNIQUE(caso_id)`), no history — confirmed with the
  user (2026-07-11): "por el momento solo la última simulación vale... más adelante evaluaremos
  cómo avanzar con esa funcionalidad." `db/calculo_credito.py:guardar_simulacion()` is an upsert
  (`ON CONFLICT(caso_id) DO UPDATE`). It stores inputs AND outputs together, not just the result —
  if a rate or the calculation logic changes later, an already-saved simulation still shows
  exactly what was calculated when it was saved, instead of silently drifting if it were
  recomputed from live data. **Currently unused** (2026-07-12): the panel's "Guardar simulación en
  este caso" button and its caso search were removed entirely (see "Reverted to a fully standalone
  calculator" above) — this table and `db/calculo_credito.py` still exist, untouched, but nothing
  writes to or reads from them anymore. Left in place since removing them wasn't asked for.
- A separate table rather than new columns on `caso`: keeps `caso` focused on the MIDESA-driven
  workflow (per the Domain model section above) instead of a dozen mostly-NULL columns for casos
  that never get simulated. Confirmed with the user as the preferred design (2026-07-11).

### Motor de cálculo — `gestor_credito/calculo/`

Pure functions, no DB/UI dependency (same separation-of-concerns principle as `export/`), each one
a direct port of a specific part of `recursos/calculadora.xlsx`'s "Calculadora" and "Calculo Plan
de pago" sheets — reconstructed by reading the actual formulas (not guessed from the visible
numbers) and validated against the real workbook opened via Excel COM automation (`win32com`), not
just eyeballed. Every module below has a pytest file with "golden" values taken directly from that
real Excel, not hand-computed:

- `dias360.py` — Excel `DAYS360` (US/NASD method). No such function in Python's stdlib; the two
  adjustment rules (day 31 → 30, last-day-of-February → 30) were verified against 11 real date
  pairs run through actual Excel via COM, covering the edge cases (leap/non-leap February, double
  31sts, chained 30/31-day months) — not just Microsoft's prose documentation, which alone wasn't
  enough to get right on the first attempt.
- `pasivo_laboral.py` — Nicaraguan Labor Code Art. 45 severance approximation (1 month/year for
  the first 3 years, 20/30 of a month/year beyond that, capped at 5 months total). Replicated
  literally, including the Excel formula's slightly unusual mixed use of `INT()` in the
  "additional years" term — the business already makes credit decisions off this exact number, so
  bit-for-bit fidelity to the current Excel behavior mattered more than a textbook-clean rewrite.
- `deducciones.py` — INSS laboral (7% flat) and IR anual (progressive brackets, exempt up to
  C$100k then 15/20/25/30% marginal bands up to and beyond C$500k). These are legal rates that can
  change — kept as named constants (`TASA_INSS_LABORAL`, `BANDAS_IR_ANUAL`), not buried in
  formulas, so updating them later doesn't mean re-deriving the math.
- `amortizacion.py` — the real engine: a level-payment (cuota nivelada) loan schedule using actual
  calendar days between payments (not fixed 30-day months) and simple per-period interest
  (`E_t = días_t × tasa_anual/360`). The level payment itself is the classic variable-period
  annuity formula, `Cuota = Principal / Σ(t=1..n)[1 / Π(k=1..t)(1+E_k)]` — arrived at by
  reconstructing the Excel's own (differently-shaped, column-based) method by hand and confirming
  numerically that both give identical results. Also replicates the next-payment-date logic
  (`siguiente_fecha_pago`): Quincenal is +15 days, +16 if that lands on a Sunday; Mensual is
  `EDATE` (same day-of-month) with a Sunday push too, PLUS a drift-correction (if the previous
  payment's day-of-month is exactly the anchor day + 1 — meaning it was pushed by a prior Sunday
  adjustment — the next `EDATE` is computed from `previous_date - 1 day` instead, to stop that
  +1 drift from compounding forever). This whole date engine, dates AND capital/interest amounts
  together, was verified against a real 24-installment schedule pulled from Excel via COM — not
  just the final cuota number — because this is exactly the kind of subtle date-arithmetic bug
  that a smaller test wouldn't have caught: the 24-row case was specifically chosen because it
  naturally hits both the Sunday-push and the drift-correction in real data.
  Only `Quincenal`/`Mensual` are implemented (`PERIODICIDADES_VALIDAS`) — the Excel's own data
  validation on that field only allows those two, even though the underlying "Calculo Plan de
  pago" sheet's lookup table knows about more (Semanal, Bimensual, etc.); adding those without a
  real case to verify against would be exactly the "replicating formulas blindly" the user asked
  to avoid.
  Deliberately does NOT support Seguro (SVD), Comisión, or Gasto Legal, nor the "Decreciente"/
  "Vencimiento" amortization systems the Excel also supports — all off in the real case analyzed,
  and the user confirmed (2026-07-11) to leave them out of this first version entirely.
- `capacidad.py` — orchestrates the above into `evaluar_capacidad()`, matching
  `Calculadora!B8:B19`. Two things here that weren't obvious from reading the Excel's formulas at
  a glance, both caught by the golden-value tests failing and then investigating why:
  - **`Calculadora!B14` (cuota) is NOT the raw level payment.** It adds a flat surcharge before
    display/use — **+US$1 per cuota if Quincenal, +US$2 if Mensual** (`MARGEN_CUOTA_USD`). This
    surcharge does NOT feed back into the internal schedule (`F12:F108` in the Excel still use the
    raw `$P$12` cuota) — it's purely what gets quoted/used for endeudamiento on top of the
    mathematically exact number. **Confirmed with the user (2026-07-12)**: this is the cost of a
    funeral-assistance service (asistencia funeraria), US$2/month total — charged in full (+2) when
    the cuota is Mensual, or split in half (+1) per cuota when Quincenal, since that periodicity has
    two cuotas per month. Not a rounding convention or collection buffer, and not signaled anywhere
    in the Excel itself — the business reason came from the user directly, not from the spreadsheet.
  - **`Calculadora!B11` ("Plazo") is always in MONTHS**, never in number-of-installments, even
    when Periodicidad is Quincenal — `'Calculo Plan de pago'!F4` doubles it for Quincenal to get
    the real installment count. `capacidad.py`'s `plazo_meses` parameter and `_numero_de_cuotas()`
    keep this conversion at the orchestration layer; `amortizacion.py` itself stays unit-agnostic
    (takes a literal installment count) so the low-level engine doesn't need to know about this
    months-vs-periodicidad business rule.

All of the above — `calculo/`, `db/convenios.py`, `db/calculo_credito.py` — were verified against
real Excel output (COM automation) before being trusted, following the same empirical standard
the rest of this project's accessibility fixes already use ("verificado empíricamente" is the bar,
not "looks right").

**A real mistake made while doing this verification, worth remembering**: driving
`recursos/calculadora.xlsx` via Excel COM for testing actually **wrote test values into that real
file on disk**, even though every script called `wb.Close(SaveChanges=False)` — because the file
lives inside a OneDrive-synced folder, AutoSave persisted the changes regardless of the explicit
"don't save" close. Caught by re-reading the file afterward and noticing the last test scenario's
values were sitting in cells that should have held the original real client's data; fixed by
reopening and restoring the exact original values (cross-checked cell-by-cell against the very
first dump taken of that file). Lesson applied going forward: open reference files like this one
`ReadOnly=True` via COM, don't rely on `SaveChanges=False` alone when the file is inside OneDrive/
SharePoint.

## Historial de Créditos

A third, independent module (2026-07-12) — same independence principle already established for
Calculadora de Crédito (kept apart from Casos, no FK to `cliente`/`caso`): a read-only search
screen over a periodic external export, `recursos/reporte.xlsx` (git-ignored, real client data —
same treatment as `MachoteBaseDeDatos.xlsx`/`calculadora.xlsx`), listing every credit already
disbursed and its current collection status (Corriente, Cancelado, Saneado, Vencido, Trámite).
Purely for lookup — the user's ask was "buscar un cliente y ver el estatus de su crédito / su
historial", not edit the report from the app.

**Schema** (`gestor_credito/db/database.py`):

```sql
reporte_credito(id, no_credito TEXT NOT NULL UNIQUE, cedula TEXT NOT NULL,
                 nombre_cliente TEXT NOT NULL, fecha_desembolso, fecha_vencimiento,
                 monto_desembolsado REAL, estado_credito, empresa_convenio,
                 plazo_credito INTEGER, numero_cuotas INTEGER, cuotas_pagadas INTEGER,
                 estado_credito_fecha_cambio TEXT NOT NULL, fecha_actualizacion_registro)
```

One table, **no FK to `cliente`/`caso`** — `cedula`/`nombre_cliente` are this report's own columns,
deliberately not joined against the MIDESA-driven `cliente` table, same reasoning already used for
`convenio_tasa`/`calculo_credito`. `no_credito` is the real identity key from the source Excel
(UNIQUE) — a periodic reimport updates the existing row instead of duplicating it, the same
`clave_caso` pattern the bitácora import already uses.

`numero_cuotas` and `estado_credito_fecha_cambio` were added 2026-08-16, for the filtering features
below — see "Filtros y vista de finalizados" further down. **`numero_cuotas` is the TOTAL number of
installments, not to be confused with `plazo_credito`** (which is in months — same distinction
already documented for `Calculadora!B11` under Calculadora de Crédito above): a credit's real
installment count is `numero_cuotas`, and "cuotas pendientes" is always `numero_cuotas -
cuotas_pagadas`, never derived from `plazo_credito`. `estado_credito_fecha_cambio` mirrors
`caso.estado_solicitud_fecha_cambio` exactly (see Domain model) — stamped at INSERT and reset only
when `estado_credito` actually changes, never on a reimport that leaves it the same; used to order
the "Finalizados" view by most-recently-paid-off rather than by `fecha_desembolso` (which is when
the credit *started*, a different date). **Migrating an existing database that predates these two
columns hits a real SQLite restriction**: `ALTER TABLE ... ADD COLUMN ... DEFAULT (datetime('now'))`
is rejected outright — "Cannot add a column with non-constant default" (confirmed empirically) —
unlike `CREATE TABLE`, which allows it freely (already used all over this schema, e.g.
`caso.fecha_creacion_registro`). `_migrar_reporte_credito()` in `database.py`, called from
`init_db()` right after `executescript(SCHEMA)`, works around this by adding
`estado_credito_fecha_cambio` with no default (nullable) and backfilling it with a single
`UPDATE ... datetime('now')` pass instead — same "backfill once" precedent already used for
`documentos_completos_fecha` (see Alerts/workflow). `numero_cuotas` is added nullable and left NULL
for every pre-existing row (no way to reconstruct it from what was already imported); it only
populates from the next reimport onward. Both are then always explicitly written by application
code in `_upsert_credito()` (never relying on the schema's own `DEFAULT`), so the fresh-install
vs. migrated-install schema difference (`NOT NULL DEFAULT (...)` vs. plain nullable) has no
behavioral effect. **Verified against a copy of the user's real database** (4833 rows, pre-migration
schema): migration completes cleanly, row count unchanged, `estado_credito_fecha_cambio` backfilled
for all 4833 rows, `numero_cuotas` NULL as expected until reimport.

**Import** (`gestor_credito/importer/reporte_creditos_importer.py`, `import_reporte_creditos()`),
triggered from **Configuración → "Configuración de Reporte de Créditos"** (a third category in the
tree alongside Casos/Calculadora — importing is a setup action, same reasoning as the MIDESA
bitácora import living in Configuración, not in the daily-use tab):
- Real headers (`recursos/reporte.xlsx`, sheet "REPORTE DE DATOS DE CREDITOS") are clean —
  underscore-separated (`NO_CREDITO`, `NO_IDENTIFICACION`), no embedded newlines or `(Manual)`/
  `(Auto)` suffixes unlike the MIDESA bitácora — but `_normalize_header()` still converts `_` to a
  space before matching `COLUMN_ALIASES`, so header variants with spaces or the wording the user
  originally used when requesting the module ("NOMBRE del CLIENTE", "PLAZO del CREDITO") also
  match. `no_credito`/`cedula`/`nombre_cliente`/`numero_cuotas` (added 2026-08-16 — previously
  unmapped, see above) plus the other `CREDITO_COLUMNS` are mapped; extra real columns
  (`SALDO_PRINCIPAL`, `MONTO_GARANTIA`, `PRODUCTO_CREDITO`, `NO_CLIENTE_SIAF`) are present in the
  real file but intentionally unmapped — ignored, not an error.
- A row missing `no_credito`, `cedula`, or `nombre_cliente` is skipped (`filas_omitidas`), same
  no-hard-fail pattern as the bitácora importer.
- **Per-row errors no longer abort the whole import (fixed 2026-08-16, real user report of silent
  data loss)**. Originally, the only two guarded conditions were missing `no_credito`/`cedula`; a row
  with a non-numeric value in `PLAZO_CREDITO`/`CUOTAS_PAGADAS`/`MONTO_DESEMBOLSADO` (uncaught
  `ValueError` from `_to_int`/`_to_float`) or a blank `NOMBRE_CLIENTE` (uncaught
  `sqlite3.IntegrityError` — `nombre_cliente TEXT NOT NULL` in the schema, but never checked before
  the earlier version's upsert) would raise out of the per-row loop before `conn.commit()` — which
  only runs once, after the loop — silently rolling back every row already processed in that
  import, not just the offending one. Fixed two ways: `nombre_cliente` is now validated up front
  next to `no_credito`/`cedula` (same `filas_omitidas` path, no DB round-trip needed to discover the
  problem), and the whole per-row body is wrapped in `try/except (ValueError, TypeError,
  sqlite3.Error)`, recording the error text into `filas_omitidas` and moving on to the next row —
  same principle as the bitácora importer's row-level tolerance, just made to actually hold under a
  real invalid value instead of only under a missing one.
- **`no_credito` matching is now format-tolerant on reimport (fixed 2026-08-16, real user report)**.
  `_row_to_dict()` coerces `no_credito` to `str(value).strip()` regardless of what type openpyxl
  handed back — same defensive cast excel_importer.py already applies to `No. Presolicitud` — but if
  Excel itself delivers the cell as a raw number in one export and as zero-padded text in another
  (e.g. `"0012456"` vs `12456`), the two reimports produce two different literal strings for what is
  the same real credit. `_upsert_credito()`'s original lookup (`WHERE no_credito = ?`, exact text
  match) missed the existing row in that case and inserted a duplicate instead of updating it —
  which is what "Historial de Créditos" then showed as the same credit appearing twice for one
  client. Fixed with a fallback lookup, only reached when the exact match misses and the incoming
  `no_credito` is purely digits (`no_credito.isdigit()` — guards against ever reaching this for a
  hypothetical future non-numeric `no_credito`, since SQLite's `CAST(... AS INTEGER)` silently
  yields `0` for non-numeric text instead of erroring): `WHERE no_credito != ? AND CAST(no_credito
  AS INTEGER) = CAST(? AS INTEGER)`, comparing the numeric value with leading zeros ignored. The
  match's `no_credito` column is never rewritten on `UPDATE` (only `CREDITO_COLUMNS` are), so
  whichever text form was imported *first* for a given credit stays its permanent identity in the
  database — later reimports with a different digit-formatting only update the other fields, they
  never change the stored `no_credito` text itself.
- `.xls` is accepted in the file picker's filter alongside `.xlsx` (user's explicit ask) even though
  `openpyxl` can't actually read the legacy binary format — the real reference file is already
  `.xlsx`; if a genuine `.xls` ever gets picked, `import_reporte_creditos()`'s failure to open it is
  caught and surfaced the same way any other import error already is, in `_on_importar_creditos()`.

**Query** (`gestor_credito/db/reporte_creditos.py`, `buscar_creditos()`):
- `termino` → same `clasificar_termino_busqueda()` cédula-vs-nombre classification already used by
  `buscar_casos()` (`db/casos.py`), and both comparisons are done in Python with `str.upper()`, not
  SQLite's ASCII-only `UPPER()` — same reasoning/same real bug already documented for Casos (a
  cédula stored uppercase wasn't found typed lowercase).
- `estado` (default `ESTADO_CREDITO_ACTIVO`, i.e. "Corriente") — filters `estado_credito` exactly
  for a literal value like `ESTADO_CREDITO_ACTIVO`. Pass `ESTADO_CREDITO_FINALIZADO` for the
  finalizados view — **not** a literal equality check, see "Próximos a finalizar..." below for the
  compound OR condition it actually applies — or the sentinel `ESTADO_TODOS` for no estado filter at
  all (see "Filtros y vista de finalizados" below for why this is a distinct sentinel and not just
  `None`/omitting the argument).
- `empresa` (default `None`) — exact match on `empresa_convenio`.
- `cuotas_pendientes_maximo` (default `None`) — **`<=`, not exact match** (changed same-day, see
  "Próximos a finalizar" below) against `numero_cuotas - cuotas_pagadas`; a row missing either of
  those two never matches (no way to compute how many cuotas it has left).
- All four filters combine with AND. Ordering is `fecha_desembolso DESC, id DESC` (most recent
  credit first) **except** when `estado == ESTADO_CREDITO_FINALIZADO`, which orders by
  `estado_credito_fecha_cambio DESC, id DESC` instead — see the schema note above for why
  (fecha_desembolso is when the credit *started*, not when it finished).

**UI** (`gestor_credito/ui/creditos_panel.py`, `CreditosPanel`) mirrors `CasosPanel`'s established
NVDA-tested patterns rather than inventing new ones: one combined cédula-or-nombre search box, a
12-column `wx.ListCtrl` (Fecha Desembolso, Fecha Vencimiento, No. Crédito, Monto Desembolsado,
Nombre del Cliente, Identificación, Empresa Convenio, Estado del Crédito, Plazo del Crédito, Número
de Cuotas, Cuotas Pagadas, Cuotas Pendientes — must stay in sync with `buscar_creditos()`'s `SELECT`
order, same coupling already called out for Casos), `CELDA_VACIA = "Celda vacía"` placeholder text
for blank cells (same NVDA reasoning as Casos — a truly empty cell reads as just the repeated
column header with nothing after it), and `Freeze()`/`Thaw()` around list rebuilds plus a column
width set once in `__init__` rather than on every refresh (same measured perf pattern as Casos,
worth it here too since the real report is already ~4800 rows). Selecting a row shows a one-line
summary ("{nombre} — Cédula {x} — Crédito No. {y} — Estado: {estado} — Cuotas pendientes: {n}") —
read-only, no edit fields, consistent with this module being lookup-only. **The 10th column used to
be mislabeled**: before 2026-08-16 it was called "Número de Cuotas" but actually displayed
`cuotas_pagadas` (there was no `numero_cuotas` column yet) — fixed by adding the real `numero_cuotas`
column/data and splitting the display into three honest columns (Número de Cuotas, Cuotas Pagadas,
Cuotas Pendientes) instead of one mislabeled one.

**Filtros y vista de finalizados (2026-08-16)** — three explicit user requests, all in
`_crear_filtros()`/`_cargar_creditos()` in `creditos_panel.py`:
1. **Filtro "Cuotas pendientes (máximo)"**: a free-text `wx.TextCtrl` — label spells out "(máximo,
   ej. 2 o 3 — 'Próximos a finalizar')" so the field is self-documenting. **Comparison is `<=`, not
   exact match** (changed in a same-day follow-up round — see "Próximos a finalizar" below for why).
   Validated as a non-negative integer or empty; an invalid value shows a `wx.MessageBox` (same
   "invalid input" pattern already established for a bad cédula/nombre term) instead of guessing
   what was meant. Applied via the same "Buscar" button/Enter as the cédula/nombre search
   (`EVT_TEXT_ENTER` bound the same way), since it's free text, not a `wx.Choice`.
2. **Filtro "Empresa"**: a `wx.Choice` populated from `obtener_empresas_convenio()` — the distinct
   `empresa_convenio` values **actually present in `reporte_credito`**, not the 29-company global
   catalog in `convenio_tasa` (which can include companies with zero credits in this report, or
   name them differently — see the "CAFE LAS FLORES CHAIN" vs. "CAFE LAS FLORES" mismatch already
   documented under Calculadora de Crédito). Explicit user requirement: "evitando listar todas las
   empresas globalmente". First option is always "Todas las empresas" (no filter); reloaded by
   `_cargar_empresas()` both at `__init__` and from `recargar()`, so a company that only appears
   after a fresh reimport shows up without restarting the app. Selection tracked by index into a
   parallel `self._empresas` list (same `_empresa_seleccionada()`-by-index pattern already used for
   `empresa_choice` in `calculadora_panel.py`, for the same reason: the choice's displayed text must
   stay a plain company name here, but the pattern of resolving by index instead of
   `GetStringSelection()` is reused regardless). Combines with every other filter/vista below, e.g.
   "Próximos a finalizar en IMMSA" = Estado Activos + Empresa "IMMSA" + Cuotas pendientes (máximo).
3. **Vista "Estado" con Finalizados**: a third `wx.Choice` — "Activos (Corriente)" (default),
   "Finalizados (para reenganche)", "Todos los estados" — for browsing clients who already paid off
   their credit in full, explicitly for reengagement/new-credit campaigns (user's own framing).
   Ordered by most-recently-finalized first (see `estado_credito_fecha_cambio` above), so the
   campaign list naturally leads with the newest payoffs.

All three combine (AND) with each other and with the cédula/nombre search box. `estado_choice` and
`empresa_choice` reload the list live on `EVT_CHOICE` (silent, matches `filtro_alerta_choice` in
`casos_panel.py`) and additionally announce the resulting count via `anunciar_voz_nvda()` when
confirmed with Enter (same `EVT_CHAR_HOOK` + `wx.Window.FindFocus()` workaround already established
for `filtro_alerta_choice`/`agentes_choice`/`empresa_choice` in Calculadora — a `wx.Choice`'s native
Win32 combobox swallows Enter before a plain `EVT_KEY_DOWN` ever sees it). `limpiar_busqueda()`
(Alt+L / "Vaciar búsqueda") now resets all three filters back to their defaults, not just the search
box, and still plays `SONIDO_BORRAR` on every clear as already established.

**"Próximos a finalizar" and a broader "Créditos finalizados" (same-day follow-up round,
2026-08-16)** — two explicit refinements to the business logic above, both in
`buscar_creditos()`/`ESTADO_CREDITO_FINALIZADO` (`db/reporte_creditos.py`):
- **"Próximos a finalizar" has no dedicated control** — it's the existing "Cuotas pendientes"
  filter (now `<=`, previously exact match) combined with the Estado selector's own default
  ("Activos"). The user's own examples ("<= 2 cuotas", "<= 3 cuotas") are a threshold, not a single
  exact count, so the field's comparison changed from `=` to `<=` to match — this is a deliberate
  reuse of the control built earlier the same day rather than adding a fourth filter widget, per
  this project's own established accessibility principle of not padding the tab order with more
  controls than needed (see the "evitar que el flujo de tabulación se vuelva lento o invasivo"
  quote under Calculadora de Crédito). The field's label spells out "'Próximos a finalizar'" so
  this mapping is discoverable without reading source code.
- **`ESTADO_CREDITO_FINALIZADO` changed from a literal `"Cancelado"` string to a sentinel
  triggering a compound OR condition**: `estado_credito IN ('Cancelado', 'Finalizado') OR
  (numero_cuotas - cuotas_pagadas) <= 0`. Explicit user ask: "clientes cuyos créditos tengan 0
  cuotas pendientes **o** cuyo estado sea 'Cancelado' / 'Finalizado'". `'Finalizado'` is included in
  the `IN (...)` even though no row in the verified real report ever uses that literal value today
  (the real `ESTADO_CREDITO` values are Corriente/Cancelado/Saneado/Vencido/Trámite) — included
  defensively per the user's explicit wording, harmless if it never matches anything. The `<= 0`
  branch is the one with a real, verified payoff: of the real report's rows, 22 have
  `cuotas_pagadas >= numero_cuotas` (i.e. functionally paid off) while `estado_credito` still reads
  "Trámite" — the source system (MIDESA) hadn't caught up to "Cancelado" yet for those. Without the
  cuotas-based branch, those 22 real clients would stay invisible to the reengagement campaign view
  until a future reimport eventually flips their `estado_credito` — which could be a long wait, or
  never, if nobody at MIDESA revisits them. `ESTADO_CREDITO_FINALIZADO`'s value itself is now an
  internal sentinel string, not something callers should compare against `"Cancelado"` directly.

**Carga asíncrona de la lista y de empresas — corrección de accesibilidad (2026-08-16, mismo día)**
— real user report: opening/using the filters ("el cajón de filtros") made "la lectura o salida por
voz" (NVDA speech) freeze momentarily. Root cause: `_cargar_creditos()`/`_cargar_empresas()` ran
their SQLite queries directly on the UI thread — while a query is in flight, wx/Windows doesn't pump
the window's message loop, and NVDA's own speech depends on that pump continuing (it's an external
process synchronized via Windows messages/MSAA), so any pending announcement stalls until the query
returns. This got materially worse once this tab started running *two* DB round-trips per load
(empresas + créditos) instead of one, and once `estado_choice`/`empresa_choice` began re-querying on
every arrow key (`EVT_CHOICE`, same live-reload pattern as `filtro_alerta_choice` in Casos).
**Fixed** with `ejecutar_en_segundo_plano(trabajo, callback)`, a new small helper in
`ui/accesibilidad.py`: runs `trabajo()` (the DB query) on a background `threading.Thread`, then
delivers its return value to `callback` back on the main thread via `wx.CallAfter` — the UI thread,
and therefore Windows' message pump and NVDA's speech, stay free the entire time the query runs.
Both `_cargar_creditos()` and `_cargar_empresas()` in `creditos_panel.py` now dispatch through this
helper instead of querying inline. A few things worth knowing about the implementation:
- **A version counter (`_version_creditos`/`_version_empresas`) guards against stale results.**
  Going async means two overlapping loads are now possible (e.g. two fast arrow presses on
  `estado_choice` each spawn their own background query) — without a guard, a slower older query
  could finish *after* a newer one and silently overwrite the screen with stale data. Each load
  increments its counter before dispatching and captures that value; the callback checks it's still
  current before touching any UI state, discarding itself otherwise.
- **Immediate synchronous status-bar feedback ("Buscando…") before dispatching.** The async fix
  alone doesn't address the *feeling* of a freeze if the status bar stays silent for the whole
  round-trip; this line is cheap/instant and gives the user something to read while the real query
  runs in the background.
- **`ValueError` from an invalid search term can no longer just propagate** the way it could when
  the query ran inline — an exception raised inside the background thread never reaches anywhere if
  left uncaught (see the same lesson already learned for `reporte_creditos_importer.py`'s per-row
  errors). `trabajo()` now catches it itself and returns `(False, mensaje)` instead of `(True,
  filas)`; the callback branches on that tuple to show the same `wx.MessageBox` as before.
  `cuotas_pendientes`'s own validation stays synchronous (no DB access, so no need to defer it) — it
  still runs and can still short-circuit before ever dispatching a background thread.
- **Testability**: `ejecutar_en_segundo_plano` is a module-level function (not a method) specifically
  so `tests/test_creditos_panel.py` can monkeypatch it to run synchronously
  (`lambda trabajo, callback: callback(trabajo())`) via an `autouse` fixture — real threads plus
  `wx.CallAfter` would need the event loop pumped and the thread awaited in every single test
  otherwise, which is slow and flaky in a headless test with no `wx.MainLoop()` running. The real
  threading path is separately covered by `tests/test_accesibilidad.py`, which verifies against the
  actual mechanism (real thread, real `wx.CallAfter`, manually pumped via `wx.YieldIfNeeded()`) that
  `trabajo()` runs off the calling thread, `callback` runs back on it, and the call returns
  immediately without waiting for `trabajo()` to finish.
- **Not yet applied elsewhere.** Casos' `_cargar_casos()`/Calculadora's DB calls still run inline —
  they weren't reported as freezing (Casos already pushes its filter to SQL and was specifically
  perf-tested at 25k rows/0.158s, see Filters and reporting), and this fix was scoped to the concrete
  report. If a similar "voice freezes" report comes up for another tab, `ejecutar_en_segundo_plano`
  is the fix to reach for there too.

**This deliberately supersedes the search behavior described above under "Query"**: previously (see
the original 2026-07-12 design further up), typing a cédula/nombre term automatically ignored the
Corriente-only default and showed the client's entire history across every `estado_credito` — there
was no way to search a specific client while staying restricted to just Finalizados, for example.
That implicit term-controls-estado coupling is now gone: `estado_choice` is fully explicit and
independent of whether there's a search term, defaulting to Activos same as before. To get the old
"full history for this client" behavior, the user now has to explicitly pick "Todos los estados" —
one extra deliberate step, traded for predictable, accessible, non-hidden filter state (the estado
selector always means exactly what it says, regardless of what's typed in the search box). Flag to
the user if this trade-off turns out to be unwelcome in practice — it wasn't explicitly requested as
part of this change, it fell out of making Estado a first-class combinable filter.

**Third notebook tab, and shortcuts became tab-aware (2026-07-12)** — adding this module grew
`MainFrame`'s `wx.Notebook` from the 2 pages described under Calculadora de Crédito above (Casos,
Calculadora de Crédito) to 3 (**Casos, Calculadora de Crédito, Historial de Créditos**). Before this,
Ctrl+F/Ctrl+R/Alt+L were wired directly to `CasosPanel`'s methods regardless of which tab was
active, so on Calculadora (already a 2nd tab at that point) Alt+L had no visible effect — a real gap
that only got noticed once a 3rd tab made the pattern obviously wrong. Fixed by making all three
shortcuts dispatch on the active notebook page instead of a fixed target:
- **Ctrl+F** (focus search) / **Ctrl+R** (focus results list): Casos and Historial de Créditos each
  focus their own search box / results list; Calculadora de Crédito has neither concept (no search,
  no list), so these two are simply no-ops there.
- **Alt+L** ("Limpiar"/clear) meant something different per tab, all confirmed with the user
  2026-07-12: on Casos, it cleared the **edit panel** (the search box itself was moved to a new local
  button, "&Vaciar búsqueda"/Alt+V, so Alt+L and Alt+V were deliberately different actions there); on
  Calculadora, it cleared the input form **while preserving the currently-selected empresa**
  (re-picking the rate every time was the friction reported); on Historial de Créditos, it cleared
  the search box and returned to the default Corriente-only view. **Superseded 2026-08-16** — see
  "Standardized clear shortcut: Ctrl+L" further down: the key changed to Ctrl+L, Alt+V was retired,
  and Casos' two separate clear actions were merged into one.
- Every one of these clear actions now also plays the delete-confirmation sound (`SONIDO_BORRAR`)
  — explicit user request: "la acción de borrar siempre tiene que hacer llamado al sonido", applied
  uniformly across all three tabs' clear actions, not just the one that prompted the request.
- Dispatch is three separate hand-written `if`/`elif` chains in `main_frame.py`, keyed on which
  panel is the active notebook page — no generic per-panel interface yet. Adding a 4th tab means
  remembering to extend all three chains (plus `_on_cambiar_pestana`'s `recargar()` list); nothing
  currently enforces that at compile time, flag it if a shortcut silently stops working on a future
  new tab.

**Reused/verified case-insensitive-cédula fix applied here too**: the same real bug already fixed
for Casos (a cédula saved uppercase, typed lowercase, not found — SQLite's `UPPER()` is ASCII-only
and doesn't fold `Ñ`/accented vowels) got the identical fix in `buscar_creditos()` the same day,
since this module's cédula search has the exact same failure mode.

**Note**: the "Architecture note, found while doing this audit" further up (under "UI implemented
so far") predates both this module and the Calculadora de Crédito one — it still describes
`MainFrame` hosting Casos alone with no notebook. That's doubly stale now: the notebook holds 3
tabs (Casos, Calculadora de Crédito, Historial de Créditos), not 0 or 2 — see the `ui/main_frame.py`
line in the Architecture tree below for the current state.

## Standardized clear shortcut: Ctrl+L (2026-08-16)

Explicit user request: "unifica el comando para limpiar formularios o campos en todos los módulos
(incluido el apartado de Casos)... Cambia los atajos anteriores (Alt+L, Alt+V, etc.) por Ctrl+L, de
modo que funcione como el único gesto global para limpiar de forma congruente en toda la
aplicación." This replaces **two** previous mechanisms at once:
- The GLOBAL Alt+L accelerator (`MainFrame._limpiar_segun_pestana_activa`, dispatching per active
  tab — see "Third notebook tab..." above for its original 2026-07-12 design) is now bound to
  **Ctrl+L** instead — same dispatch function, same per-tab targets, just a different key
  (`wx.ACCEL_CTRL, ord("L")` instead of `wx.ACCEL_ALT, ord("L")` in `atajos.py`).
- The LOCAL Alt+V mnemonic that the "Vaciar búsqueda" buttons in Casos and Historial de Créditos had
  (a plain wx.Button `&`-mnemonic, not a `MainFrame`-registered accelerator) is **retired** — both
  buttons' labels changed from `"&Vaciar búsqueda"` to plain `"Vaciar búsqueda"`. The buttons
  themselves still exist and still work via mouse click or Tab+Enter, they just no longer claim a
  keyboard shortcut of their own now that Ctrl+L covers that role globally.

**Casos went from two separate clear actions to one.** Before, Alt+L cleared only the edit panel
(`CasosPanel.limpiar_edicion()`) and the local "Vaciar búsqueda" button (Alt+V) cleared only the
search box + alert filter (`CasosPanel.limpiar_busqueda()`) — two distinct actions, each with its
own trigger. Ctrl+L in Casos now calls a new `CasosPanel.limpiar_todo()`, which does both together:
search, alert filter, AND the edit panel, in one gesture, leaving the tab exactly as if freshly
opened. `limpiar_edicion()`/`limpiar_busqueda()` still exist as public methods (the local "Vaciar
búsqueda" button — now without a keyboard mnemonic — still calls `limpiar_busqueda()` alone, for
someone who wants to clear just the search without losing the case they're mid-editing), but neither
is directly wired to the global shortcut anymore; `limpiar_todo()` is. To avoid the confirmation
sound (`SONIDO_BORRAR`) playing twice when both underlying actions run together, the actual
state-resetting logic was factored out into sound-less helpers (`_vaciar_busqueda_y_filtro()`,
`_resetear_panel_edicion()`) that `limpiar_busqueda()`/`limpiar_edicion()`/`limpiar_todo()` all call,
with each of the three public methods playing the sound exactly once at its own end.

Calculadora and Historial de Créditos didn't have this two-actions problem (each only ever had one
clear concept), so their `limpiar_formulario()`/`limpiar_busqueda()` targets are unchanged — only
the key that reaches them changed, from Alt+L to Ctrl+L.

## Direct tab navigation: Ctrl+1/Ctrl+2/Ctrl+3 (2026-08-16)

Explicit user request, same round as the Ctrl+L change above: jump directly to a specific notebook
tab regardless of which one is currently active, as a faster alternative to Ctrl+Tab/Ctrl+Shift+Tab
(which only step forward/backward in order — reaching Historial de Créditos from Casos means two
Ctrl+Tab presses, or one Ctrl+Shift+Tab from Calculadora, neither of which lets you jump straight
there). **Ctrl+1** → Casos, **Ctrl+2** → Calculadora de Crédito, **Ctrl+3** → Historial de Créditos —
matching the pages' fixed left-to-right order (`MainFrame._INDICE_CASOS/_INDICE_CALCULADORA/
_INDICE_CREDITOS`, mirroring the order pages are added to `self.notebook` in `__init__`).

Implemented as three thin methods (`MainFrame._ir_a_casos/_ir_a_calculadora/_ir_a_creditos`, each
just `self.notebook.SetSelection(<índice>)`) rather than three inline lambdas in the `acciones` dict
— named methods keep this consistent with every other entry in that dict (`_limpiar_segun_pestana_activa`
etc.), and let tests call them directly the same way, instead of only being reachable through a
simulated key event. **`wx.Notebook.SetSelection()` was confirmed empirically (not assumed) to fire
`EVT_NOTEBOOK_PAGE_CHANGED`** in this app/wxPython/Windows combination — `wx.Notebook` has a separate
`ChangeSelection()` method specifically documented to skip that event, so this isn't guaranteed
behavior for `wx.BookCtrlBase` in general, but it does hold here. That means these three methods
don't need to duplicate `_on_cambiar_pestana()`'s work (reload the target tab's data, announce its
name via `anunciar_voz_nvda`) — switching via Ctrl+1/2/3 goes through the exact same event handler as
a mouse click or Ctrl+Tab, so it stays automatically in sync with whatever that handler does, now or
later.

## Commands

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

python main.py          # run the app
pytest                  # run tests
pytest tests/test_database.py::test_init_db_creates_file   # run a single test
```

Note: on this machine, wxPython, openpyxl, and python-docx are already available in the global
Python install; `pytest` is not, so `pip install -r requirements.txt` (or `pip install pytest`)
is needed before running tests.

### Empaquetado portable (pendrive)

```
pyinstaller --name "GestorDeCredito" --windowed --noconfirm --add-data "gestor_credito/assets;gestor_credito/assets" main.py
```

Produces `dist/GestorDeCredito/` — the `.exe` plus a support folder
(`_internal/`); the whole folder must be copied as a unit (--onedir, chosen
over --onefile: faster startup, no self-extraction to a temp folder on every
launch — confirmed with the user). `gestor_credito/db/database.py`'s
`DB_PATH` is frozen-aware (`sys.frozen`/`sys.executable`) specifically so that
`data/gestor_credito.db` is created next to the `.exe`, not inside the
PyInstaller-internal bundle path that `__file__` would otherwise resolve to —
this is what makes the data persist across runs and survive being moved to a
different machine on a pendrive. Don't revert that check to a plain
`Path(__file__)`-relative path; it would silently break portability. Build
artifacts (`build/`, `dist/`, `*.spec`) are git-ignored.

## Architecture

```
main.py                        # entry point, calls gestor_credito.app.main()
gestor_credito/
  app.py                       # wx.App subclass, creates the main frame
  catalogos.py                  # fixed value lists from 02_Catalogos (Estado Solicitud, Etapa Proceso)
  assets/
    logo.png                     # real logo, 2048x2048px — AppLogo scales it down for display
    sonidos/                      # .wav alert sounds, supplied by the user (not generated by Claude)
    nvda/                          # nvdaControllerClient(32|64).dll — see anunciar_voz_nvda in accesibilidad.py
  calculo/                       # pure calculation engine for Calculadora de Crédito, no DB/UI — see that section above
    dias360.py                     # Excel DAYS360 (US/NASD) replica
    pasivo_laboral.py               # Nicaraguan labor-liability approximation
    deducciones.py                  # INSS/IR
    amortizacion.py                 # cuota nivelada + payment schedule/dates
    capacidad.py                    # orchestrates the above into evaluar_capacidad()
  ui/
    main_frame.py                # wx.Frame; hosts a 3-page wx.Notebook (Casos, Calculadora de Crédito,
                                   # Historial de Créditos) — everything else (Notificaciones/Configuración/
                                   # Ayuda) stays a menu-triggered modal dialog. Also dispatches Ctrl+F/
                                   # Ctrl+R/Alt+L per active tab — see Historial de Créditos section above
    logo.py                       # AppLogo — the accessible logo shown on every tab/dialog
    sonido.py                     # reproducir_sonido() — plays a .wav from assets/sonidos/ via wx.adv.Sound
    fechas.py                     # ISO <-> DD/MM/AAAA date formatting for the UI boundary
    accesibilidad.py               # nombre_accesible/activar_con_enter/anunciar_texto_estado/anunciar_voz_nvda/
                                     # ejecutar_en_segundo_plano
    atajos.py                      # central registry of every documented keyboard shortcut
    casos_panel.py                 # "Casos" tab (search/list/manually edit)
    calculadora_panel.py            # "Calculadora de Crédito" tab — see that section above
    creditos_panel.py               # "Historial de Créditos" tab — see that section above
    notificaciones_panel.py         # Notificaciones dialog (alert list, see Alerts/workflow)
    configuracion_panel.py          # Configuración dialog (agente actual + importar Excel de bitácora/reporte)
    ayuda_panel.py                  # Ayuda dialog (keyboard shortcut reference, from atajos.py)
  db/
    database.py                  # sqlite3 connection + schema management
    casos.py                      # queries/updates for the caso entity (search, filter, edit)
    configuracion.py              # get/set for the configuracion key-value table
    alertas.py                     # live alert queries (documentos/constancia pendiente/en mano)
    convenios.py                   # convenio_tasa CRUD (empresa -> tasa), for Calculadora de Crédito
    calculo_credito.py              # last-saved-simulation-per-caso CRUD, for Calculadora de Crédito
    reporte_creditos.py             # buscar_creditos(), for Historial de Créditos
  importer/
    excel_importer.py             # reads the MIDESA bitácora, upserts cliente/caso
    reporte_creditos_importer.py    # reads recursos/reporte.xlsx, upserts reporte_credito
  export/
    excel_export.py              # openpyxl-based report export
    word_export.py                # python-docx-based document export
data/
  gestor_credito.db              # SQLite file, created on first run, git-ignored
tests/                            # pytest, mirrors the gestor_credito/ package layout
```

- `gestor_credito/db/database.py` holds `DB_PATH`, `get_connection()`/`init_db()`, and the schema.
  Entity-specific queries/commands (e.g. `casos.py`) live in their own module in `db/` rather than
  growing `database.py` into a catch-all.
- `gestor_credito/ui/` has one wx.Frame/wx.Panel per file; `MainFrame` only wires the `wx.Notebook`
  together, it doesn't hold page-specific logic.
- `gestor_credito/export/` holds one module per output format. Export functions take plain data
  (rows/headers, or title/paragraphs) and an output path — they should not reach back into the
  database or UI layer directly, so they stay independently testable.

## Accessibility (NVDA)

Since screen-reader support is the core requirement driving the choice of wxPython, keep these in
mind for any UI work:

- Every input control needs a real, associated label (`wx.StaticText` + control, or the control's
  accessible name set explicitly) — NVDA announces controls by their label, not by placeholder
  text or visual proximity.
- Preserve a logical tab order matching visual/reading order; don't rely on mouse-only
  interactions for anything.
- Prefer standard wx widgets (wx.TextCtrl, wx.ListCtrl, wx.Choice, etc.) over custom-drawn
  controls — standard widgets get MSAA/UIA support for free, custom-drawn ones generally don't.
- Default to `SetStatusText` / the status bar, or an in-panel message area, for feedback — not a
  dialog, per the no-popups rule above. But be aware `SetStatusText`/`SetLabel` changes are *not*
  proactively announced by NVDA (the user has to go check them manually); for an outcome that
  genuinely needs immediate screen-reader attention and has no focus change to piggyback on (e.g.
  a failed/empty search), `wx.MessageBox` is the confirmed, deliberate exception — see the
  Project section above before reaching for it elsewhere. Don't convey state through color or
  icon changes alone.
- Any `wx.Button` created must be passed through `activar_con_enter()`
  (`gestor_credito/ui/accesibilidad.py`). Space already activates a focused button by default in a
  plain `wx.Frame`/`wx.Panel`, but Enter does not — that binding only exists in `wx.Dialog`'s
  default-button handling, which this app's `wx.Notebook`-in-a-`wx.Frame` layout doesn't get for
  free. Confirmed as a real keyboard-accessibility bug during NVDA testing; every button must get
  this, not just the one that got reported.
