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
  ui/
    main_frame.py                # wx.Frame with the wx.Notebook that hosts every tab
    logo.py                       # AppLogo — the accessible logo shown on every tab
    sonido.py                     # reproducir_sonido() — plays a .wav from assets/sonidos/ via wx.adv.Sound
    fechas.py                     # ISO <-> DD/MM/AAAA date formatting for the UI boundary
    accesibilidad.py               # activar_con_enter() — apply to every wx.Button, see below
    casos_panel.py                 # "Casos" tab (search/list/manually edit)
    notificaciones_panel.py         # "Notificaciones" tab (alert list, see Alerts/workflow)
    configuracion_panel.py          # "Configuración" tab (agente actual + importar Excel)
  db/
    database.py                  # sqlite3 connection + schema management
    casos.py                      # queries/updates for the caso entity (search, filter, edit)
    configuracion.py              # get/set for the configuracion key-value table
    alertas.py                     # live alert queries (documentos/constancia pendiente/en mano)
  importer/
    excel_importer.py             # reads the MIDESA bitácora, upserts cliente/caso
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
