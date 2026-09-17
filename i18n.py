"""
i18n.py — Localization for the Discord bot.

Locale detection uses Discord's own client-language setting (interaction.locale),
so a player never has to configure anything — the bot just speaks whatever
language their Discord client is already set to, among the ones we support.
Anyone on an unsupported locale silently gets English; nothing ever breaks
because a translation is missing (see t()'s fallback).

Supported: English (en), Spanish (es), French (fr), Portuguese (pt), German (de).

Adding a language: add its Discord locale code(s) to DISCORD_LOCALE_TO_LANG,
then add translations for any keys in TRANSLATIONS. Missing keys silently
fall back to English — nothing breaks if a language's coverage is partial.

Adding a translatable string anywhere else in the bot: add a key to TRANSLATIONS
with an 'en' entry (required) and whichever other languages you have, then call
t('your.key', lang, **kwargs) instead of hardcoding the English string in place.
"""

import discord

SUPPORTED_LANGS = ['en', 'es', 'fr', 'pt', 'de']

# Discord's Locale enum values (BCP-47 codes) -> our internal language code.
# Discord has two Spanish locales and only a Brazilian Portuguese locale —
# both map onto our single 'es'/'pt' catalog.
DISCORD_LOCALE_TO_LANG = {
    'es-ES': 'es',
    'es-419': 'es',
    'fr': 'fr',
    'pt-BR': 'pt',
    'de': 'de',
}


def resolve_lang(interaction: discord.Interaction) -> str:
    """
    Map an interaction's Discord client locale to one of our supported
    languages, defaulting to English for anything else (including English
    itself, or a locale we don't have translations for).
    """
    locale = getattr(interaction, 'locale', None)
    if locale is None:
        return 'en'
    code = str(locale)  # discord.Locale.__str__ returns the BCP-47 value, e.g. 'de'
    return DISCORD_LOCALE_TO_LANG.get(code, 'en')


def t(key: str, lang: str = 'en', **kwargs) -> str:
    """
    Look up a translated, formatted string. Falls back to English if the
    language or the key is missing, and falls back to the raw key (never
    raises) if even English is missing — a missing translation should never
    take down a command.
    """
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry.get('en')
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def tlist(key: str, lang: str = 'en'):
    """Like t(), but for values that are lists of (name, value) field tuples
    (used for the manual's per-command fields) rather than plain strings."""
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return []
    return entry.get(lang) or entry.get('en') or []


# =============================================================================
# TRANSLATIONS
# =============================================================================
#
# Keyed by a dotted path. Most values are {lang: str}. The manual's field
# lists are {lang: [(name, description), ...]} — see tlist() above.

TRANSLATIONS: dict = {}

# -----------------------------------------------------------------------
# Manual — navigation chrome
# -----------------------------------------------------------------------

TRANSLATIONS['manual.nav.prev'] = {
    'en': '◀ Prev', 'es': '◀ Anterior', 'fr': '◀ Précédent', 'pt': '◀ Anterior', 'de': '◀ Zurück',
}
TRANSLATIONS['manual.nav.next'] = {
    'en': 'Next ▶', 'es': 'Siguiente ▶', 'fr': 'Suivant ▶', 'pt': 'Próximo ▶', 'de': 'Weiter ▶',
}
TRANSLATIONS['manual.nav.close'] = {
    'en': '✕ Close', 'es': '✕ Cerrar', 'fr': '✕ Fermer', 'pt': '✕ Fechar', 'de': '✕ Schließen',
}
TRANSLATIONS['manual.nav.footer'] = {
    'en': 'Page {page} of {total}  •  Slash commands use `/`, prefix commands use `!`',
    'es': 'Página {page} de {total}  •  Los comandos de barra usan `/`, los comandos con prefijo usan `!`',
    'fr': 'Page {page} sur {total}  •  Les commandes slash utilisent `/`, les commandes à préfixe utilisent `!`',
    'pt': 'Página {page} de {total}  •  Comandos de barra usam `/`, comandos com prefixo usam `!`',
    'de': 'Seite {page} von {total}  •  Slash-Befehle verwenden `/`, Präfix-Befehle verwenden `!`',
}
TRANSLATIONS['manual.closed'] = {
    'en': 'Manual closed.', 'es': 'Manual cerrado.', 'fr': 'Manuel fermé.',
    'pt': 'Manual fechado.', 'de': 'Handbuch geschlossen.',
}

# -----------------------------------------------------------------------
# Manual — page titles
# -----------------------------------------------------------------------

TRANSLATIONS['manual.page1.title'] = {
    'en': '📋 Commands — Gameplay (1/5)',
    'es': '📋 Comandos — Jugabilidad (1/5)',
    'fr': '📋 Commandes — Jeu (1/5)',
    'pt': '📋 Comandos — Jogabilidade (1/5)',
    'de': '📋 Befehle — Spielablauf (1/5)',
}
TRANSLATIONS['manual.page2.title'] = {
    'en': '📋 Commands — Matchup & Ladder (2/5)',
    'es': '📋 Comandos — Enfrentamientos y Escalafón (2/5)',
    'fr': '📋 Commandes — Affrontements et Classement (2/5)',
    'pt': '📋 Comandos — Confrontos e Ranking (2/5)',
    'de': '📋 Befehle — Matchup & Rangliste (2/5)',
}
TRANSLATIONS['manual.page3.title'] = {
    'en': '📋 Commands — Siege (3/5)',
    'es': '📋 Comandos — Asedio (3/5)',
    'fr': '📋 Commandes — Siège (3/5)',
    'pt': '📋 Comandos — Cerco (3/5)',
    'de': '📋 Befehle — Belagerung (3/5)',
}
TRANSLATIONS['manual.page4.title'] = {
    'en': '📋 Commands — Admin (4/5)',
    'es': '📋 Comandos — Administración (4/5)',
    'fr': '📋 Commandes — Administration (4/5)',
    'pt': '📋 Comandos — Administração (4/5)',
    'de': '📋 Befehle — Verwaltung (4/5)',
}
TRANSLATIONS['manual.page5.title'] = {
    'en': '📋 Commands — GIFs & Tournaments (5/5)',
    'es': '📋 Comandos — GIFs y Torneos (5/5)',
    'fr': '📋 Commandes — GIFs et Tournois (5/5)',
    'pt': '📋 Comandos — GIFs e Torneios (5/5)',
    'de': '📋 Befehle — GIFs & Turniere (5/5)',
}

# -----------------------------------------------------------------------
# Manual — page 1 fields (Gameplay)
# -----------------------------------------------------------------------

TRANSLATIONS['manual.page1.fields'] = {
    'en': [
        ("/score", "Record a player's score.\n`/score player:Grizzly points:22`\nUse M for missed drives, E for excused absence. Optional: DEF OVR faced, 4th down stats."),
        ("/dscore", "Record a player's defensive score for a day — for the common case where one opponent faced all 3 drives.\n`/dscore player:Grizzly drive1:3 drive2:F drive3:5 ovr:235` — each drive is 0-8 (points allowed) or F/I/S (fumble/interception/safety). Points allowed is totaled automatically. No modal — the opponent's OVR is entered inline and applied to all 3 drives. For a day where more than one opponent faced the player, use `/dscore_multiple` instead."),
        ("/dscore_multiple", "Record a player's defensive score for a day, drive by drive — for when more than one opponent faced the player across the 3 drives.\n`/dscore_multiple player:Grizzly drive1:3 drive2:F drive3:5` — each drive is 0-8 (points allowed) or F/I/S (fumble/interception/safety). Points allowed is totaled automatically. A modal opens for Drive 1 right away (OVR faced, plus down/distance/play/forced-by if it was a turnover); a button then continues to Drive 2, then Drive 3, one modal at a time, ending with a full summary."),
        ("/ovr", "Update a player's OVR.\n`/ovr player:Grizzly`"),
        ("/avg", "Get a player's average.\n`/avg player:Grizzly` → pick type."),
        ("/player", "Full stats card for a player.\n`/player player:Grizzly`"),
        ("/history", "Score history over a date range.\n`/history player:Grizzly start:2026-06-01`"),
        ("/status", "Today's matchup score and remaining players.\n`/status league:NP`"),
        ("/scores", "All player scores for a league across a date range, shown as a grid.\n`/scores league:NP start:2026-07-01 end:2026-07-07`"),
        ("/opp", "Show a player's opponent in today's ladder.\n`/opp player:Grizzly`"),
    ],
    'es': [
        ("/score", "Registra la puntuación de un jugador.\n`/score player:Grizzly points:22`\nUsa M para drives fallados, E para ausencia justificada. Opcional: DEF OVR enfrentado, estadísticas de 4to down."),
        ("/dscore", "Registra la puntuación defensiva de un jugador para el día — para el caso común donde un solo oponente enfrentó las 3 series.\n`/dscore player:Grizzly drive1:3 drive2:F drive3:5 ovr:235` — cada serie es 0-8 (puntos permitidos) o F/I/S (balón perdido/intercepción/safety). Los puntos totales se calculan automáticamente. Sin modal — el OVR del oponente se ingresa en línea y se aplica a las 3 series. Para un día con más de un oponente, usa `/dscore_multiple`."),
        ("/dscore_multiple", "Registra la puntuación defensiva de un jugador para el día, serie por serie — para cuando más de un oponente enfrentó al jugador en las 3 series.\n`/dscore_multiple player:Grizzly drive1:3 drive2:F drive3:5` — cada serie es 0-8 (puntos permitidos) o F/I/S (balón perdido/intercepción/safety). Los puntos totales se calculan automáticamente. Un modal se abre para la Serie 1 de inmediato (OVR enfrentado, más down/distancia/jugada/quién lo forzó si fue un balón perdido); un botón continúa luego a la Serie 2, y a la 3, un modal a la vez, terminando con un resumen completo."),
        ("/ovr", "Actualiza el OVR de un jugador.\n`/ovr player:Grizzly`"),
        ("/avg", "Obtén el promedio de un jugador.\n`/avg player:Grizzly` → elige el tipo."),
        ("/player", "Ficha completa de estadísticas de un jugador.\n`/player player:Grizzly`"),
        ("/history", "Historial de puntuaciones en un rango de fechas.\n`/history player:Grizzly start:2026-06-01`"),
        ("/status", "Puntuación del enfrentamiento de hoy y jugadores restantes.\n`/status league:NP`"),
        ("/scores", "Todas las puntuaciones de una liga en un rango de fechas, en forma de tabla.\n`/scores league:NP start:2026-07-01 end:2026-07-07`"),
        ("/opp", "Muestra el oponente de un jugador en el escalafón de hoy.\n`/opp player:Grizzly`"),
    ],
    'fr': [
        ("/score", "Enregistre le score d'un joueur.\n`/score player:Grizzly points:22`\nUtilisez M pour un drive manqué, E pour une absence excusée. Optionnel : DEF OVR affronté, statistiques de 4e down."),
        ("/dscore", "Enregistre le score défensif d'un joueur pour la journée — pour le cas courant où un seul adversaire a affronté les 3 séries.\n`/dscore player:Grizzly drive1:3 drive2:F drive3:5 ovr:235` — chaque série vaut 0-8 (points concédés) ou F/I/S (ballon perdu/interception/sécurité). Le total des points est calculé automatiquement. Aucun formulaire — l'OVR de l'adversaire est saisi directement et appliqué aux 3 séries. Pour une journée avec plusieurs adversaires, utilisez `/dscore_multiple`."),
        ("/dscore_multiple", "Enregistre le score défensif d'un joueur pour la journée, série par série — pour quand plusieurs adversaires ont affronté le joueur sur les 3 séries.\n`/dscore_multiple player:Grizzly drive1:3 drive2:F drive3:5` — chaque série vaut 0-8 (points concédés) ou F/I/S (ballon perdu/interception/sécurité). Le total des points est calculé automatiquement. Un formulaire s'ouvre pour la Série 1 immédiatement (OVR affronté, plus down/distance/action/qui l'a provoqué si c'était un ballon perdu) ; un bouton continue ensuite vers la Série 2, puis la 3, un formulaire à la fois, avant un résumé complet."),
        ("/ovr", "Met à jour l'OVR d'un joueur.\n`/ovr player:Grizzly`"),
        ("/avg", "Obtient la moyenne d'un joueur.\n`/avg player:Grizzly` → choisissez le type."),
        ("/player", "Fiche de statistiques complète d'un joueur.\n`/player player:Grizzly`"),
        ("/history", "Historique des scores sur une période.\n`/history player:Grizzly start:2026-06-01`"),
        ("/status", "Score de l'affrontement du jour et joueurs restants.\n`/status league:NP`"),
        ("/scores", "Tous les scores des joueurs d'une ligue sur une plage de dates, sous forme de grille.\n`/scores league:NP start:2026-07-01 end:2026-07-07`"),
        ("/opp", "Affiche l'adversaire d'un joueur dans le classement du jour.\n`/opp player:Grizzly`"),
    ],
    'pt': [
        ("/score", "Registra a pontuação de um jogador.\n`/score player:Grizzly points:22`\nUse M para drives perdidos, E para ausência justificada. Opcional: DEF OVR enfrentado, estatísticas de 4th down."),
        ("/dscore", "Registra a pontuação defensiva de um jogador no dia — para o caso comum de um único adversário ter enfrentado as 3 séries.\n`/dscore player:Grizzly drive1:3 drive2:F drive3:5 ovr:235` — cada série é 0-8 (pontos permitidos) ou F/I/S (fumble/interceptação/safety). O total de pontos é calculado automaticamente. Sem modal — o OVR do adversário é inserido diretamente e aplicado às 3 séries. Para um dia com mais de um adversário, use `/dscore_multiple`."),
        ("/dscore_multiple", "Registra a pontuação defensiva de um jogador no dia, série por série — para quando mais de um adversário enfrentou o jogador nas 3 séries.\n`/dscore_multiple player:Grizzly drive1:3 drive2:F drive3:5` — cada série é 0-8 (pontos permitidos) ou F/I/S (fumble/interceptação/safety). O total de pontos é calculado automaticamente. Um modal abre para a Série 1 imediatamente (OVR enfrentado, mais down/distância/jogada/quem forçou se foi uma perda de bola); um botão continua então para a Série 2, e a 3, um modal de cada vez, terminando com um resumo completo."),
        ("/ovr", "Atualiza o OVR de um jogador.\n`/ovr player:Grizzly`"),
        ("/avg", "Obtém a média de um jogador.\n`/avg player:Grizzly` → escolha o tipo."),
        ("/player", "Ficha completa de estatísticas de um jogador.\n`/player player:Grizzly`"),
        ("/history", "Histórico de pontuações em um período.\n`/history player:Grizzly start:2026-06-01`"),
        ("/status", "Placar do confronto de hoje e jogadores restantes.\n`/status league:NP`"),
        ("/scores", "Todas as pontuações de uma liga em um intervalo de datas, em forma de grade.\n`/scores league:NP start:2026-07-01 end:2026-07-07`"),
        ("/opp", "Mostra o oponente de um jogador no ranking de hoje.\n`/opp player:Grizzly`"),
    ],
    'de': [
        ("/score", "Erfasst den Punktestand eines Spielers.\n`/score player:Grizzly points:22`\nM für verpasste Drives, E für entschuldigtes Fehlen. Optional: gegnerischer DEF OVR, 4th-Down-Statistiken."),
        ("/dscore", "Erfasst die Defensivwertung eines Spielers für einen Tag — für den häufigen Fall, dass ein Gegner alle 3 Drives bestritten hat.\n`/dscore player:Grizzly drive1:3 drive2:F drive3:5 ovr:235` — jeder Drive ist 0-8 (zugelassene Punkte) oder F/I/S (Fumble/Interception/Safety). Die Gesamtpunktzahl wird automatisch berechnet. Kein Formular — der OVR des Gegners wird direkt eingegeben und auf alle 3 Drives angewendet. Für einen Tag mit mehreren Gegnern nutze `/dscore_multiple`."),
        ("/dscore_multiple", "Erfasst die Defensivwertung eines Spielers für einen Tag, Drive für Drive — für wenn mehrere Gegner den Spieler über die 3 Drives hinweg bestritten haben.\n`/dscore_multiple player:Grizzly drive1:3 drive2:F drive3:5` — jeder Drive ist 0-8 (zugelassene Punkte) oder F/I/S (Fumble/Interception/Safety). Die Gesamtpunktzahl wird automatisch berechnet. Ein Formular öffnet sich sofort für Drive 1 (gegnerischer OVR, plus Down/Distanz/Spielzug/wer ihn erzwungen hat bei einem Ballverlust); ein Button führt dann weiter zu Drive 2, dann 3, ein Formular nach dem anderen, mit einer abschließenden Zusammenfassung."),
        ("/ovr", "Aktualisiert den OVR eines Spielers.\n`/ovr player:Grizzly`"),
        ("/avg", "Ruft den Durchschnitt eines Spielers ab.\n`/avg player:Grizzly` → Typ auswählen."),
        ("/player", "Vollständige Statistikkarte eines Spielers.\n`/player player:Grizzly`"),
        ("/history", "Punkteverlauf über einen Zeitraum.\n`/history player:Grizzly start:2026-06-01`"),
        ("/status", "Punktestand des heutigen Matchups und verbleibende Spieler.\n`/status league:NP`"),
        ("/scores", "Alle Spielerwertungen einer Liga über einen Datumsbereich, als Raster.\n`/scores league:NP start:2026-07-01 end:2026-07-07`"),
        ("/opp", "Zeigt den Gegner eines Spielers in der heutigen Rangliste.\n`/opp player:Grizzly`"),
    ],
}

# -----------------------------------------------------------------------
# Manual — page 2 fields (Matchup & Ladder)
# -----------------------------------------------------------------------

TRANSLATIONS['manual.page2.fields'] = {
    'en': [
        ("/matchup", "**Admin.** Full matchup editor — opponent, division, ranks, outcome, drives, all player scores.\n`/matchup league:NP` or `/matchup league:NP date:2026-07-07`\nOptional: `our_defaults`, `opp_defaults`."),
        ("/ladder", "**Admin.** Build today's ladder matchups interactively.\n`/ladder league:NP` — manual flow.\n`/ladder league:NP screenshot1:[img]` — AI extracts both sides from screenshots, pre-selects your 16 sorted by ladder rank, pre-fills opponents. Reports OVR changes and unregistered players.\nOnce you hit **Done — Sort & Arrange** in the opponent step, that list is saved — if you have to abort and rerun `/ladder league:NP` with no screenshot, the opponent-entry modal reloads it for free."),
        ("/show_ladder", "Display the ladder matchups for a league.\n`/show_ladder league:NP`"),
        ("/rank", "Power ranking table for a league.\n`/rank league:NP`"),
        ("/stats", "League-wide averages for a team — one row per stat category, not per-player (that's `/rank`).\n`/stats league:NP` — active players only.\n`/stats league:NP include_inactive:True` — also folds in inactive/transferred-away players who have historical scores for this league."),
        ("/legacy", "**Read-only lookups against an archived past season.** Same subcommands and arguments as their live counterparts, plus `year`.\n`/legacy rank league:NP year:2026`\n`/legacy player player:Grizzly year:2026`\n`/legacy stats league:NP year:2026`\n`/legacy history player:Grizzly start:2026-07-01 year:2026`\n`/legacy scores league:NP year:2026 start:2026-07-01`\n`/legacy show_ladder league:NP year:2026`\nOnly works for a season that's actually been archived on the server."),
        ("/factors", "Current weight factors for a league.\n`/factors league:NP`"),
        ("/streak", "A player's current hot streaks: consecutive 24pt games (Kobe streak) and consecutive 18+pt games with no dropped drives (no-drop streak).\n`/streak player:Grizzly`"),
        ("/openspots", "How many open roster spots each league has (18 minus its current active player count), sorted by most open first.\n`/openspots`"),
    ],
    'es': [
        ("/matchup", "**Admin.** Editor completo de enfrentamientos — oponente, división, rangos, resultado, drives, puntuaciones de todos los jugadores.\n`/matchup league:NP` o `/matchup league:NP date:2026-07-07`\nOpcional: `our_defaults`, `opp_defaults`."),
        ("/ladder", "**Admin.** Arma el escalafón de hoy de forma interactiva.\n`/ladder league:NP` — flujo manual.\n`/ladder league:NP screenshot1:[img]` — la IA extrae ambos lados de las capturas, preselecciona tus 16 jugadores ordenados por rango de escalafón, y precompleta los oponentes. Informa cambios de OVR y jugadores no registrados.\nEn cuanto pulses **Done — Sort & Arrange** en el paso de oponentes, esa lista se guarda — si tienes que abortar y volver a ejecutar `/ladder league:NP` sin captura, el modal de ingreso de oponentes la recarga automáticamente."),
        ("/show_ladder", "Muestra los enfrentamientos del escalafón de una liga.\n`/show_ladder league:NP`"),
        ("/rank", "Tabla de clasificación por poder de una liga.\n`/rank league:NP`"),
        ("/stats", "Promedios de toda la liga para un equipo — una fila por categoría de estadística, no por jugador (para eso está `/rank`).\n`/stats league:NP` — solo jugadores activos.\n`/stats league:NP include_inactive:True` — también incluye jugadores inactivos o transferidos con puntuaciones históricas en esta liga."),
        ("/legacy", "**Consultas de solo lectura contra una temporada archivada.** Mismos subcomandos y argumentos que sus equivalentes en vivo, más `year`.\n`/legacy rank league:NP year:2026`\n`/legacy player player:Grizzly year:2026`\n`/legacy stats league:NP year:2026`\n`/legacy history player:Grizzly start:2026-07-01 year:2026`\n`/legacy scores league:NP year:2026 start:2026-07-01`\n`/legacy show_ladder league:NP year:2026`\nSolo funciona para una temporada que realmente haya sido archivada en el servidor."),
        ("/factors", "Factores de ponderación actuales de una liga.\n`/factors league:NP`"),
        ("/streak", "Las rachas actuales de un jugador: juegos consecutivos de 24pts (racha Kobe) y juegos consecutivos de 18+pts sin drives perdidos (racha sin fumbles).\n`/streak player:Grizzly`"),
        ("/openspots", "Cuántos cupos abiertos tiene cada liga (18 menos su cantidad actual de jugadores activos), ordenados de más a menos abiertos.\n`/openspots`"),
    ],
    'fr': [
        ("/matchup", "**Admin.** Éditeur complet d'affrontement — adversaire, division, rangs, résultat, drives, scores de tous les joueurs.\n`/matchup league:NP` ou `/matchup league:NP date:2026-07-07`\nOptionnel : `our_defaults`, `opp_defaults`."),
        ("/ladder", "**Admin.** Construit le classement du jour de façon interactive.\n`/ladder league:NP` — mode manuel.\n`/ladder league:NP screenshot1:[img]` — l'IA extrait les deux côtés à partir des captures d'écran, présélectionne vos 16 joueurs triés par rang de classement, et pré-remplit les adversaires. Signale les changements d'OVR et les joueurs non enregistrés.\nDès que vous appuyez sur **Done — Sort & Arrange** à l'étape des adversaires, cette liste est enregistrée — si vous devez interrompre puis relancer `/ladder league:NP` sans capture d'écran, le formulaire de saisie des adversaires la recharge automatiquement."),
        ("/show_ladder", "Affiche les affrontements du classement d'une ligue.\n`/show_ladder league:NP`"),
        ("/rank", "Tableau de classement par puissance d'une ligue.\n`/rank league:NP`"),
        ("/stats", "Moyennes globales de la ligue pour une équipe — une ligne par catégorie de statistique, pas par joueur (c'est le rôle de `/rank`).\n`/stats league:NP` — joueurs actifs uniquement.\n`/stats league:NP include_inactive:True` — inclut aussi les joueurs inactifs ou transférés ayant des scores historiques dans cette ligue."),
        ("/legacy", "**Consultations en lecture seule d'une saison archivée.** Mêmes sous-commandes et arguments que leurs équivalents en direct, plus `year`.\n`/legacy rank league:NP year:2026`\n`/legacy player player:Grizzly year:2026`\n`/legacy stats league:NP year:2026`\n`/legacy history player:Grizzly start:2026-07-01 year:2026`\n`/legacy scores league:NP year:2026 start:2026-07-01`\n`/legacy show_ladder league:NP year:2026`\nNe fonctionne que pour une saison réellement archivée sur le serveur."),
        ("/factors", "Facteurs de pondération actuels d'une ligue.\n`/factors league:NP`"),
        ("/streak", "Les séries actuelles d'un joueur : matchs consécutifs à 24pts (série Kobe) et matchs consécutifs à 18+pts sans drive manqué (série sans drive manqué).\n`/streak player:Grizzly`"),
        ("/openspots", "Le nombre de places disponibles pour chaque ligue (18 moins son nombre actuel de joueurs actifs), triées des plus disponibles aux moins disponibles.\n`/openspots`"),
    ],
    'pt': [
        ("/matchup", "**Admin.** Editor completo de confrontos — oponente, divisão, rankings, resultado, drives, pontuações de todos os jogadores.\n`/matchup league:NP` ou `/matchup league:NP date:2026-07-07`\nOpcional: `our_defaults`, `opp_defaults`."),
        ("/ladder", "**Admin.** Monta o ranking de hoje de forma interativa.\n`/ladder league:NP` — fluxo manual.\n`/ladder league:NP screenshot1:[img]` — a IA extrai os dois lados das capturas de tela, pré-seleciona seus 16 jogadores ordenados por rank, e preenche os oponentes automaticamente. Relata mudanças de OVR e jogadores não registrados.\nAo clicar em **Done — Sort & Arrange** na etapa de oponentes, essa lista é salva — se precisar abortar e executar `/ladder league:NP` novamente sem captura de tela, o modal de entrada de oponentes a recarrega automaticamente."),
        ("/show_ladder", "Exibe os confrontos do ranking de uma liga.\n`/show_ladder league:NP`"),
        ("/rank", "Tabela de classificação por poder de uma liga.\n`/rank league:NP`"),
        ("/stats", "Médias de toda a liga para um time — uma linha por categoria de estatística, não por jogador (esse é o papel do `/rank`).\n`/stats league:NP` — apenas jogadores ativos.\n`/stats league:NP include_inactive:True` — também inclui jogadores inativos ou transferidos com pontuações históricas nesta liga."),
        ("/legacy", "**Consultas somente leitura em uma temporada arquivada.** Mesmos subcomandos e argumentos de seus equivalentes ao vivo, mais `year`.\n`/legacy rank league:NP year:2026`\n`/legacy player player:Grizzly year:2026`\n`/legacy stats league:NP year:2026`\n`/legacy history player:Grizzly start:2026-07-01 year:2026`\n`/legacy scores league:NP year:2026 start:2026-07-01`\n`/legacy show_ladder league:NP year:2026`\nSó funciona para uma temporada que realmente foi arquivada no servidor."),
        ("/factors", "Fatores de ponderação atuais de uma liga.\n`/factors league:NP`"),
        ("/streak", "As sequências atuais de um jogador: jogos consecutivos de 24pts (sequência Kobe) e jogos consecutivos de 18+pts sem drives perdidos (sequência sem drive perdido).\n`/streak player:Grizzly`"),
        ("/openspots", "Quantas vagas abertas cada liga tem (18 menos sua contagem atual de jogadores ativos), ordenadas das mais abertas às menos abertas.\n`/openspots`"),
    ],
    'de': [
        ("/matchup", "**Admin.** Vollständiger Matchup-Editor — Gegner, Division, Ränge, Ergebnis, Drives, alle Spielerwertungen.\n`/matchup league:NP` oder `/matchup league:NP date:2026-07-07`\nOptional: `our_defaults`, `opp_defaults`."),
        ("/ladder", "**Admin.** Baut die heutige Rangliste interaktiv auf.\n`/ladder league:NP` — manueller Ablauf.\n`/ladder league:NP screenshot1:[img]` — die KI liest beide Seiten aus Screenshots aus, wählt deine 16 Spieler nach Ranglistenrang vor und füllt Gegner automatisch aus. Meldet OVR-Änderungen und nicht registrierte Spieler.\nSobald du im Gegner-Schritt auf **Done — Sort & Arrange** klickst, wird diese Liste gespeichert — falls du abbrechen und `/ladder league:NP` ohne Screenshot erneut ausführen musst, lädt das Gegner-Eingabeformular sie automatisch neu."),
        ("/show_ladder", "Zeigt die Ranglisten-Matchups einer Liga an.\n`/show_ladder league:NP`"),
        ("/rank", "Power-Ranking-Tabelle einer Liga.\n`/rank league:NP`"),
        ("/stats", "Liga-weite Durchschnitte für ein Team — eine Zeile pro Statistikkategorie, nicht pro Spieler (dafür ist `/rank`).\n`/stats league:NP` — nur aktive Spieler.\n`/stats league:NP include_inactive:True` — bezieht auch inaktive oder abgewanderte Spieler mit historischen Wertungen in dieser Liga ein."),
        ("/legacy", "**Reine Lesezugriffe auf eine archivierte, vergangene Saison.** Gleiche Unterbefehle und Argumente wie die Live-Gegenstücke, plus `year`.\n`/legacy rank league:NP year:2026`\n`/legacy player player:Grizzly year:2026`\n`/legacy stats league:NP year:2026`\n`/legacy history player:Grizzly start:2026-07-01 year:2026`\n`/legacy scores league:NP year:2026 start:2026-07-01`\n`/legacy show_ladder league:NP year:2026`\nFunktioniert nur für eine Saison, die tatsächlich auf dem Server archiviert wurde."),
        ("/factors", "Aktuelle Gewichtungsfaktoren einer Liga.\n`/factors league:NP`"),
        ("/streak", "Die aktuellen Serien eines Spielers: aufeinanderfolgende 24-Punkte-Spiele (Kobe-Serie) und aufeinanderfolgende 18+-Punkte-Spiele ohne verlorene Drives (Serie ohne verlorenen Drive).\n`/streak player:Grizzly`"),
        ("/openspots", "Wie viele offene Kaderplätze jede Liga hat (18 minus ihrer aktuellen Anzahl aktiver Spieler), sortiert von den meisten zu den wenigsten offenen Plätzen.\n`/openspots`"),
    ],
}

# -----------------------------------------------------------------------
# Manual — page 3 fields (Siege)
# -----------------------------------------------------------------------

TRANSLATIONS['manual.page3.fields'] = {
    'en': [
        ("/siege", "**Admin.** Start a new siege match for a league.\n`/siege league:NP` → modal for opposing league, ranks, division. Only one active match per league at a time."),
        ("/node", "Report a newly-visible opponent (node) once its path is cleared in-game.\n`/node league:NP mod:Run Plays Only` → modal for opponent name, OVR, points required to clear, points reward. Use mod `No Mod` for un-modded opponents (up to 6 per match). Each of the 10 named mods can only be reported once per match."),
        ("/siegescore", "Log drives/points scored against an open node.\n`/siegescore league:NP player:Grizzly opponent:BigBoy87` → pick from the autocomplete list (shows every open node regardless of mod) → modal for drives played, points scored. Auto-clears the node once required points are met."),
        ("/siegestatus", "Check the active match: open nodes (top 3 by reward ⭐), cleared totals, player totals, PPD, and league score.\n`/siegestatus league:NP`"),
        ("/updatesiege", "**Admin.** Set the opponent's total points and correct any node or score entry in the active match.\n`/updatesiege league:NP`"),
        ("/siegefinal", "**Admin.** Same corrections as `/updatesiege`, then closes out the active match.\n`/siegefinal league:NP`"),
        ("/siegesplits", "A player's cumulative siege points/drives/PPD, broken down by mod, across every match they've played.\n`/siegesplits player:Grizzly`"),
        ("/siegehistory", "Past completed siege matches for a league — opponent, date, final score.\n`/siegehistory league:NP`"),
    ],
    'es': [
        ("/siege", "**Admin.** Inicia un nuevo combate de asedio para una liga.\n`/siege league:NP` → modal para liga oponente, rangos, división. Solo un combate activo por liga a la vez."),
        ("/node", "Reporta un oponente recién visible (nodo) una vez que su camino esté despejado en el juego.\n`/node league:NP mod:Run Plays Only` → modal para nombre del oponente, OVR, puntos requeridos para despejarlo, puntos de recompensa. Usa el mod `No Mod` para oponentes sin modificador (hasta 6 por combate). Cada uno de los 10 mods con nombre solo puede reportarse una vez por combate."),
        ("/siegescore", "Registra drives/puntos anotados contra un nodo abierto.\n`/siegescore league:NP player:Grizzly opponent:BigBoy87` → elige de la lista de autocompletado (muestra todos los nodos abiertos sin importar el mod) → modal para drives jugados, puntos anotados. Despeja el nodo automáticamente al alcanzar los puntos requeridos."),
        ("/siegestatus", "Consulta el combate activo: nodos abiertos (los 3 mejores por recompensa ⭐), totales despejados, totales por jugador, PPD y puntuación de liga.\n`/siegestatus league:NP`"),
        ("/updatesiege", "**Admin.** Establece los puntos totales del oponente y corrige cualquier nodo o registro de puntuación del combate activo.\n`/updatesiege league:NP`"),
        ("/siegefinal", "**Admin.** Mismas correcciones que `/updatesiege`, y además cierra el combate activo.\n`/siegefinal league:NP`"),
        ("/siegesplits", "Puntos/drives/PPD acumulados de un jugador en asedio, desglosados por mod, en todos los combates que ha jugado.\n`/siegesplits player:Grizzly`"),
        ("/siegehistory", "Combates de asedio ya completados de una liga — oponente, fecha, puntuación final.\n`/siegehistory league:NP`"),
    ],
    'fr': [
        ("/siege", "**Admin.** Démarre un nouveau siège pour une ligue.\n`/siege league:NP` → formulaire pour la ligue adverse, les rangs, la division. Un seul siège actif par ligue à la fois."),
        ("/node", "Signale un adversaire nouvellement visible (nœud) une fois son chemin dégagé dans le jeu.\n`/node league:NP mod:Run Plays Only` → formulaire pour le nom de l'adversaire, l'OVR, les points requis pour le dégager, les points de récompense. Utilisez le mod `No Mod` pour les adversaires sans mod (jusqu'à 6 par siège). Chacun des 10 mods nommés ne peut être signalé qu'une seule fois par siège."),
        ("/siegescore", "Enregistre les drives/points marqués contre un nœud ouvert.\n`/siegescore league:NP player:Grizzly opponent:BigBoy87` → choisissez dans la liste d'autocomplétion (affiche tous les nœuds ouverts, quel que soit le mod) → formulaire pour les drives joués, les points marqués. Dégage automatiquement le nœud une fois les points requis atteints."),
        ("/siegestatus", "Consulte le siège actif : nœuds ouverts (top 3 par récompense ⭐), totaux dégagés, totaux par joueur, PPD et score de ligue.\n`/siegestatus league:NP`"),
        ("/updatesiege", "**Admin.** Définit le total de points de l'adversaire et corrige n'importe quel nœud ou score du siège actif.\n`/updatesiege league:NP`"),
        ("/siegefinal", "**Admin.** Mêmes corrections que `/updatesiege`, puis clôture le siège actif.\n`/siegefinal league:NP`"),
        ("/siegesplits", "Points/drives/PPD cumulés d'un joueur en siège, répartis par mod, sur tous les sièges auxquels il a participé.\n`/siegesplits player:Grizzly`"),
        ("/siegehistory", "Sièges déjà terminés d'une ligue — adversaire, date, score final.\n`/siegehistory league:NP`"),
    ],
    'pt': [
        ("/siege", "**Admin.** Inicia um novo cerco para uma liga.\n`/siege league:NP` → modal para liga adversária, rankings, divisão. Apenas um cerco ativo por liga por vez."),
        ("/node", "Reporta um oponente recém-visível (nó) assim que seu caminho é liberado no jogo.\n`/node league:NP mod:Run Plays Only` → modal para nome do oponente, OVR, pontos necessários para liberar, pontos de recompensa. Use o mod `No Mod` para oponentes sem modificador (até 6 por cerco). Cada um dos 10 mods nomeados só pode ser reportado uma vez por cerco."),
        ("/siegescore", "Registra drives/pontos marcados contra um nó aberto.\n`/siegescore league:NP player:Grizzly opponent:BigBoy87` → escolha na lista de autocompletar (mostra todos os nós abertos, independente do mod) → modal para drives jogados, pontos marcados. Libera o nó automaticamente ao atingir os pontos necessários."),
        ("/siegestatus", "Consulta o cerco ativo: nós abertos (top 3 por recompensa ⭐), totais liberados, totais por jogador, PPD e pontuação da liga.\n`/siegestatus league:NP`"),
        ("/updatesiege", "**Admin.** Define o total de pontos do adversário e corrige qualquer nó ou registro de pontuação do cerco ativo.\n`/updatesiege league:NP`"),
        ("/siegefinal", "**Admin.** Mesmas correções que `/updatesiege`, e também encerra o cerco ativo.\n`/siegefinal league:NP`"),
        ("/siegesplits", "Pontos/drives/PPD acumulados de um jogador em cercos, detalhados por mod, em todos os cercos que já jogou.\n`/siegesplits player:Grizzly`"),
        ("/siegehistory", "Cercos já concluídos de uma liga — oponente, data, pontuação final.\n`/siegehistory league:NP`"),
    ],
    'de': [
        ("/siege", "**Admin.** Startet eine neue Belagerung für eine Liga.\n`/siege league:NP` → Formular für gegnerische Liga, Ränge, Division. Immer nur eine aktive Belagerung pro Liga."),
        ("/node", "Meldet einen neu sichtbaren Gegner (Knoten), sobald sein Pfad im Spiel freigeschaltet ist.\n`/node league:NP mod:Run Plays Only` → Formular für Gegnername, OVR, benötigte Punkte zum Freischalten, Belohnungspunkte. Verwende `No Mod` für Gegner ohne Modifikator (bis zu 6 pro Belagerung). Jeder der 10 benannten Mods kann nur einmal pro Belagerung gemeldet werden."),
        ("/siegescore", "Erfasst Drives/Punkte gegen einen offenen Knoten.\n`/siegescore league:NP player:Grizzly opponent:BigBoy87` → aus der Autovervollständigungsliste wählen (zeigt alle offenen Knoten unabhängig vom Mod) → Formular für gespielte Drives, erzielte Punkte. Schließt den Knoten automatisch bei Erreichen der benötigten Punkte."),
        ("/siegestatus", "Zeigt die aktive Belagerung: offene Knoten (Top 3 nach Belohnung ⭐), abgeschlossene Summen, Spielersummen, PPD und Liga-Punktzahl.\n`/siegestatus league:NP`"),
        ("/updatesiege", "**Admin.** Legt die Gesamtpunktzahl des Gegners fest und korrigiert jeden Knoten- oder Punktestand-Eintrag der aktiven Belagerung.\n`/updatesiege league:NP`"),
        ("/siegefinal", "**Admin.** Gleiche Korrekturen wie `/updatesiege`, schließt danach die aktive Belagerung ab.\n`/siegefinal league:NP`"),
        ("/siegesplits", "Kumulierte Belagerungspunkte/Drives/PPD eines Spielers, aufgeschlüsselt nach Mod, über alle gespielten Belagerungen.\n`/siegesplits player:Grizzly`"),
        ("/siegehistory", "Bereits abgeschlossene Belagerungen einer Liga — Gegner, Datum, Endpunktzahl.\n`/siegehistory league:NP`"),
    ],
}

# -----------------------------------------------------------------------
# Manual — page 4 fields (Admin)
# -----------------------------------------------------------------------

TRANSLATIONS['manual.page4.fields'] = {
    'en': [
        ("/register", "Register a new player.\n`/register league:NP`"),
        ("/transfer", "Move a player to a different league.\n`/transfer player:Grizzly`"),
        ("/inactive", "Mark a player as having left.\n`/inactive player:Grizzly`"),
        ("/reactivate", "Restore a player to active status.\n`/reactivate player:Grizzly`"),
        ("/nick", "Change a player's bot nickname — start typing their real IGN or current nickname to find them.\n`/nick player:xX_Slayer_Xx nickname:Slayer`"),
        ("/ign", "Update a player's real in-game name for when they change it in-game (their bot nickname stays the same).\n`/ign player:Slayer new_real_ign:xX_NewName_Xx`"),
        ("/rename", "Change a player's bot nickname without touching their real in-game name mapping.\n`/rename player:Slayer new_nickname:SlayerX`"),
        ("/league", "Add or rename a league.\n`/league action:Add new league`"),
        ("/weights", "Manage power rank or ladder weight factors.\n`/weights category:Power Rank`"),
        ("/newday", "Manually trigger the new day reset."),
        ("/sync", "Re-register slash commands to this server."),
        ("/nukeguildcmds", "Clear stale guild-registered commands."),
        ("/test", "Run the unit test suite and post results."),
    ],
    'es': [
        ("/register", "Registra un nuevo jugador.\n`/register league:NP`"),
        ("/transfer", "Mueve a un jugador a otra liga.\n`/transfer player:Grizzly`"),
        ("/inactive", "Marca a un jugador como retirado.\n`/inactive player:Grizzly`"),
        ("/reactivate", "Restaura a un jugador al estado activo.\n`/reactivate player:Grizzly`"),
        ("/nick", "Cambia el apodo de un jugador en el bot — empieza a escribir su IGN real o apodo actual para encontrarlo.\n`/nick player:xX_Slayer_Xx nickname:Slayer`"),
        ("/ign", "Actualiza el IGN real de un jugador cuando lo cambie en el juego (su apodo en el bot no cambia).\n`/ign player:Slayer new_real_ign:xX_NewName_Xx`"),
        ("/rename", "Cambia el apodo de un jugador en el bot sin tocar su IGN real asignado.\n`/rename player:Slayer new_nickname:SlayerX`"),
        ("/league", "Agrega o renombra una liga.\n`/league action:Add new league`"),
        ("/weights", "Gestiona los factores de ponderación de poder o de escalafón.\n`/weights category:Power Rank`"),
        ("/newday", "Activa manualmente el reinicio del nuevo día."),
        ("/sync", "Vuelve a registrar los comandos de barra en este servidor."),
        ("/nukeguildcmds", "Elimina comandos obsoletos registrados en el servidor."),
        ("/test", "Ejecuta la suite de pruebas unitarias y publica los resultados."),
    ],
    'fr': [
        ("/register", "Enregistre un nouveau joueur.\n`/register league:NP`"),
        ("/transfer", "Déplace un joueur vers une autre ligue.\n`/transfer player:Grizzly`"),
        ("/inactive", "Marque un joueur comme parti.\n`/inactive player:Grizzly`"),
        ("/reactivate", "Restaure un joueur au statut actif.\n`/reactivate player:Grizzly`"),
        ("/nick", "Change le pseudo d'un joueur dans le bot — commencez à taper son IGN réel ou son pseudo actuel pour le trouver.\n`/nick player:xX_Slayer_Xx nickname:Slayer`"),
        ("/ign", "Met à jour l'IGN réel d'un joueur lorsqu'il en change en jeu (son pseudo dans le bot ne change pas).\n`/ign player:Slayer new_real_ign:xX_NewName_Xx`"),
        ("/rename", "Change le pseudo d'un joueur dans le bot sans toucher à son IGN réel associé.\n`/rename player:Slayer new_nickname:SlayerX`"),
        ("/league", "Ajoute ou renomme une ligue.\n`/league action:Add new league`"),
        ("/weights", "Gère les facteurs de pondération de puissance ou de classement.\n`/weights category:Power Rank`"),
        ("/newday", "Déclenche manuellement la réinitialisation du nouveau jour."),
        ("/sync", "Réenregistre les commandes slash sur ce serveur."),
        ("/nukeguildcmds", "Supprime les commandes obsolètes enregistrées sur le serveur."),
        ("/test", "Exécute la suite de tests unitaires et publie les résultats."),
    ],
    'pt': [
        ("/register", "Registra um novo jogador.\n`/register league:NP`"),
        ("/transfer", "Move um jogador para outra liga.\n`/transfer player:Grizzly`"),
        ("/inactive", "Marca um jogador como afastado.\n`/inactive player:Grizzly`"),
        ("/reactivate", "Restaura um jogador ao status ativo.\n`/reactivate player:Grizzly`"),
        ("/nick", "Muda o apelido de um jogador no bot — comece a digitar o IGN real ou apelido atual para encontrá-lo.\n`/nick player:xX_Slayer_Xx nickname:Slayer`"),
        ("/ign", "Atualiza o IGN real de um jogador para quando ele mudar no jogo (o apelido no bot permanece o mesmo).\n`/ign player:Slayer new_real_ign:xX_NewName_Xx`"),
        ("/rename", "Muda o apelido de um jogador no bot sem alterar seu IGN real vinculado.\n`/rename player:Slayer new_nickname:SlayerX`"),
        ("/league", "Adiciona ou renomeia uma liga.\n`/league action:Add new league`"),
        ("/weights", "Gerencia os fatores de ponderação de poder ou de ranking.\n`/weights category:Power Rank`"),
        ("/newday", "Aciona manualmente a redefinição do novo dia."),
        ("/sync", "Registra novamente os comandos de barra neste servidor."),
        ("/nukeguildcmds", "Remove comandos obsoletos registrados no servidor."),
        ("/test", "Executa a suíte de testes unitários e publica os resultados."),
    ],
    'de': [
        ("/register", "Registriert einen neuen Spieler.\n`/register league:NP`"),
        ("/transfer", "Verschiebt einen Spieler in eine andere Liga.\n`/transfer player:Grizzly`"),
        ("/inactive", "Markiert einen Spieler als ausgeschieden.\n`/inactive player:Grizzly`"),
        ("/reactivate", "Setzt einen Spieler wieder auf aktiv.\n`/reactivate player:Grizzly`"),
        ("/nick", "Ändert den Bot-Spitznamen eines Spielers — tippe den echten IGN oder aktuellen Spitznamen ein, um ihn zu finden.\n`/nick player:xX_Slayer_Xx nickname:Slayer`"),
        ("/ign", "Aktualisiert den echten Spielnamen eines Spielers, wenn er ihn im Spiel ändert (der Bot-Spitzname bleibt gleich).\n`/ign player:Slayer new_real_ign:xX_NewName_Xx`"),
        ("/rename", "Ändert den Bot-Spitznamen eines Spielers, ohne seine echte IGN-Zuordnung zu verändern.\n`/rename player:Slayer new_nickname:SlayerX`"),
        ("/league", "Fügt eine Liga hinzu oder benennt sie um.\n`/league action:Add new league`"),
        ("/weights", "Verwaltet Power-Rank- oder Ranglisten-Gewichtungsfaktoren.\n`/weights category:Power Rank`"),
        ("/newday", "Löst den Tageswechsel-Reset manuell aus."),
        ("/sync", "Registriert die Slash-Befehle auf diesem Server neu."),
        ("/nukeguildcmds", "Entfernt veraltete, serverregistrierte Befehle."),
        ("/test", "Führt die Testsuite aus und postet die Ergebnisse."),
    ],
}

# -----------------------------------------------------------------------
# Manual — page 5 fields (GIFs & Tournaments)
# -----------------------------------------------------------------------

TRANSLATIONS['manual.page5.fields'] = {
    'en': [
        ("/addgif", "Add a GIF to a folder.\n`/addgif folder:kobe gif:[attach file]`\nRequires an **Admin** role or **Gif Master** role."),
        ("/reloadgifs", "Reload all GIF folders from disk.\nRequires an **Admin** role or **Gif Master** role."),
        ("/tournament_start", "**Admin.** Start a tournament.\n`/tournament_start name:Summer players:Grizzly dougbaldwin FHRITP`"),
        ("/tournament_result", "Record a match result.\n`/tournament_result tournament_id:abc123 match_num:1 winner:Grizzly`"),
        ("/tournament_bracket", "View a tournament bracket.\n`/tournament_bracket tournament_id:abc123`"),
        ("/tournament_list", "**Admin.** List all tournaments."),
    ],
    'es': [
        ("/addgif", "Agrega un GIF a una carpeta.\n`/addgif folder:kobe gif:[archivo adjunto]`\nRequiere un rol de **Admin** o **Gif Master**."),
        ("/reloadgifs", "Vuelve a cargar todas las carpetas de GIFs desde el disco.\nRequiere un rol de **Admin** o **Gif Master**."),
        ("/tournament_start", "**Admin.** Inicia un torneo.\n`/tournament_start name:Summer players:Grizzly dougbaldwin FHRITP`"),
        ("/tournament_result", "Registra el resultado de una partida.\n`/tournament_result tournament_id:abc123 match_num:1 winner:Grizzly`"),
        ("/tournament_bracket", "Muestra el cuadro de un torneo.\n`/tournament_bracket tournament_id:abc123`"),
        ("/tournament_list", "**Admin.** Lista todos los torneos."),
    ],
    'fr': [
        ("/addgif", "Ajoute un GIF à un dossier.\n`/addgif folder:kobe gif:[fichier joint]`\nNécessite un rôle **Admin** ou **Gif Master**."),
        ("/reloadgifs", "Recharge tous les dossiers de GIFs depuis le disque.\nNécessite un rôle **Admin** ou **Gif Master**."),
        ("/tournament_start", "**Admin.** Démarre un tournoi.\n`/tournament_start name:Summer players:Grizzly dougbaldwin FHRITP`"),
        ("/tournament_result", "Enregistre le résultat d'un match.\n`/tournament_result tournament_id:abc123 match_num:1 winner:Grizzly`"),
        ("/tournament_bracket", "Affiche le tableau d'un tournoi.\n`/tournament_bracket tournament_id:abc123`"),
        ("/tournament_list", "**Admin.** Liste tous les tournois."),
    ],
    'pt': [
        ("/addgif", "Adiciona um GIF a uma pasta.\n`/addgif folder:kobe gif:[arquivo anexado]`\nRequer um cargo de **Admin** ou **Gif Master**."),
        ("/reloadgifs", "Recarrega todas as pastas de GIFs do disco.\nRequer um cargo de **Admin** ou **Gif Master**."),
        ("/tournament_start", "**Admin.** Inicia um torneio.\n`/tournament_start name:Summer players:Grizzly dougbaldwin FHRITP`"),
        ("/tournament_result", "Registra o resultado de uma partida.\n`/tournament_result tournament_id:abc123 match_num:1 winner:Grizzly`"),
        ("/tournament_bracket", "Exibe o chaveamento de um torneio.\n`/tournament_bracket tournament_id:abc123`"),
        ("/tournament_list", "**Admin.** Lista todos os torneios."),
    ],
    'de': [
        ("/addgif", "Fügt einer Ordner ein GIF hinzu.\n`/addgif folder:kobe gif:[Datei anhängen]`\nErfordert eine **Admin**-Rolle oder **Gif Master**."),
        ("/reloadgifs", "Lädt alle GIF-Ordner neu von der Festplatte.\nErfordert eine **Admin**-Rolle oder **Gif Master**."),
        ("/tournament_start", "**Admin.** Startet ein Turnier.\n`/tournament_start name:Summer players:Grizzly dougbaldwin FHRITP`"),
        ("/tournament_result", "Erfasst ein Spielergebnis.\n`/tournament_result tournament_id:abc123 match_num:1 winner:Grizzly`"),
        ("/tournament_bracket", "Zeigt einen Turnierbaum an.\n`/tournament_bracket tournament_id:abc123`"),
        ("/tournament_list", "**Admin.** Listet alle Turniere auf."),
    ],
}

MANUAL_PAGE_KEYS = ['manual.page1', 'manual.page2', 'manual.page3', 'manual.page4', 'manual.page5']

# =============================================================================
# TIER 1 — Core player-facing commands
# =============================================================================

# --- Shared / common ---

TRANSLATIONS['common.player_not_found'] = {
    'en': "⚠️ Player `{player}` not found.",
    'es': "⚠️ Jugador `{player}` no encontrado.",
    'fr': "⚠️ Joueur `{player}` introuvable.",
    'pt': "⚠️ Jogador `{player}` não encontrado.",
    'de': "⚠️ Spieler `{player}` nicht gefunden.",
}
TRANSLATIONS['common.admin_required'] = {
    'en': "⛔ This command requires the **Administrator**, **League Owner**, or **Madden Admin** role.",
    'es': "⛔ Este comando requiere el rol de **Administrador**, **League Owner** o **Madden Admin**.",
    'fr': "⛔ Cette commande nécessite le rôle **Administrateur**, **League Owner** ou **Madden Admin**.",
    'pt': "⛔ Este comando requer o cargo de **Administrador**, **League Owner** ou **Madden Admin**.",
    'de': "⛔ Dieser Befehl erfordert die Rolle **Administrator**, **League Owner** oder **Madden Admin**.",
}
TRANSLATIONS['common.invalid_league'] = {
    'en': "Invalid league '{league}'. Use: {leagues}",
    'es': "Liga no válida '{league}'. Usa: {leagues}",
    'fr': "Ligue invalide « {league} ». Utilisez : {leagues}",
    'pt': "Liga inválida '{league}'. Use: {leagues}",
    'de': "Ungültige Liga „{league}“. Verwende: {leagues}",
}
TRANSLATIONS['common.invalid_date_format'] = {
    'en': "⚠️ Use format `YYYY-MM-DD`.",
    'es': "⚠️ Usa el formato `YYYY-MM-DD`.",
    'fr': "⚠️ Utilisez le format `YYYY-MM-DD`.",
    'pt': "⚠️ Use o formato `YYYY-MM-DD`.",
    'de': "⚠️ Verwende das Format `YYYY-MM-DD`.",
}

# --- /score ---

TRANSLATIONS['score.modal.title'] = {
    'en': "Record Score", 'es': "Registrar Puntuación", 'fr': "Enregistrer le Score",
    'pt': "Registrar Pontuação", 'de': "Punktestand Erfassen",
}
TRANSLATIONS['score.modal.label_score'] = {
    'en': "Score (M=missed drives, E=excused)",
    'es': "Puntuación (M=drives fallados, E=justificado)",
    'fr': "Score (M=drive manqué, E=excusé)",
    'pt': "Pontuação (M=drives perdidos, E=justificado)",
    'de': "Punktestand (M=verpasste Drives, E=entschuldigt)",
}
TRANSLATIONS['score.modal.label_def_ovr'] = {
    'en': "Opponent DEF OVR Faced", 'es': "DEF OVR del Oponente Enfrentado",
    'fr': "DEF OVR Adverse Affronté", 'pt': "DEF OVR do Oponente Enfrentado",
    'de': "Gegnerischer DEF OVR",
}
TRANSLATIONS['score.modal.label_4th_att'] = {
    'en': "4th Down Attempts", 'es': "Intentos de 4to Down", 'fr': "Tentatives de 4e Down",
    'pt': "Tentativas de 4th Down", 'de': "4th-Down-Versuche",
}
TRANSLATIONS['score.modal.label_4th_conv'] = {
    'en': "4th Down Conversions", 'es': "Conversiones de 4to Down", 'fr': "Conversions de 4e Down",
    'pt': "Conversões de 4th Down", 'de': "4th-Down-Conversions",
}
TRANSLATIONS['score.err.invalid_score'] = {
    'en': "⚠️ Score must be an integer, M for missed drives, or E for excused.",
    'es': "⚠️ La puntuación debe ser un número entero, M para drives fallados o E para justificado.",
    'fr': "⚠️ Le score doit être un entier, M pour un drive manqué, ou E pour une absence excusée.",
    'pt': "⚠️ A pontuação deve ser um número inteiro, M para drives perdidos ou E para justificado.",
    'de': "⚠️ Der Punktestand muss eine ganze Zahl sein, M für verpasste Drives oder E für entschuldigt.",
}
TRANSLATIONS['score.err.points_too_long'] = {
    'en': "⚠️ `points` must be 4 characters or fewer (e.g. `22`, `M`, or `E`). You entered `{points}`.",
    'es': "⚠️ `points` debe tener 4 caracteres o menos (por ejemplo, `22`, `M`, o `E`). Ingresaste `{points}`.",
    'fr': "⚠️ `points` doit contenir 4 caractères ou moins (par ex. `22`, `M`, ou `E`). Vous avez saisi `{points}`.",
    'pt': "⚠️ `points` deve ter no máximo 4 caracteres (ex.: `22`, `M`, ou `E`). Você digitou `{points}`.",
    'de': "⚠️ `points` darf höchstens 4 Zeichen haben (z. B. `22`, `M`, oder `E`). Du hast `{points}` eingegeben.",
}
TRANSLATIONS['score.err.invalid_def_ovr'] = {
    'en': "⚠️ DEF OVR must be an integer.", 'es': "⚠️ El DEF OVR debe ser un número entero.",
    'fr': "⚠️ Le DEF OVR doit être un entier.", 'pt': "⚠️ O DEF OVR deve ser um número inteiro.",
    'de': "⚠️ Der DEF OVR muss eine ganze Zahl sein.",
}
TRANSLATIONS['score.err.invalid_4th_att'] = {
    'en': "⚠️ 4th down attempts must be an integer.",
    'es': "⚠️ Los intentos de 4to down deben ser un número entero.",
    'fr': "⚠️ Les tentatives de 4e down doivent être un entier.",
    'pt': "⚠️ As tentativas de 4th down devem ser um número inteiro.",
    'de': "⚠️ 4th-Down-Versuche müssen eine ganze Zahl sein.",
}
TRANSLATIONS['score.err.invalid_4th_conv'] = {
    'en': "⚠️ 4th down conversions must be an integer.",
    'es': "⚠️ Las conversiones de 4to down deben ser un número entero.",
    'fr': "⚠️ Les conversions de 4e down doivent être un entier.",
    'pt': "⚠️ As conversões de 4th down devem ser um número inteiro.",
    'de': "⚠️ 4th-Down-Conversions müssen eine ganze Zahl sein.",
}
TRANSLATIONS['score.err.convs_exceed'] = {
    'en': "⚠️ Conversions can't exceed attempts.",
    'es': "⚠️ Las conversiones no pueden superar los intentos.",
    'fr': "⚠️ Les conversions ne peuvent pas dépasser les tentatives.",
    'pt': "⚠️ As conversões não podem exceder as tentativas.",
    'de': "⚠️ Conversions dürfen die Versuche nicht übersteigen.",
}
TRANSLATIONS['score.suffix.missed'] = {
    'en': "  *(missed drives)*", 'es': "  *(drives fallados)*", 'fr': "  *(drive manqué)*",
    'pt': "  *(drives perdidos)*", 'de': "  *(verpasste Drives)*",
}
TRANSLATIONS['score.suffix.excused'] = {
    'en': "  *(excused)*", 'es': "  *(justificado)*", 'fr': "  *(excusé)*",
    'pt': "  *(justificado)*", 'de': "  *(entschuldigt)*",
}
TRANSLATIONS['score.suffix.def'] = {
    'en': " vs DEF {ovr}", 'es': " vs DEF {ovr}", 'fr': " vs DEF {ovr}",
    'pt': " vs DEF {ovr}", 'de': " vs. DEF {ovr}",
}
TRANSLATIONS['score.suffix.4th_rate'] = {
    'en': "  |  4th: {convs}/{attempts} ({rate}%)",
    'es': "  |  4to down: {convs}/{attempts} ({rate}%)",
    'fr': "  |  4e down : {convs}/{attempts} ({rate}%)",
    'pt': "  |  4th down: {convs}/{attempts} ({rate}%)",
    'de': "  |  4th Down: {convs}/{attempts} ({rate}%)",
}
TRANSLATIONS['score.suffix.4th_noconv'] = {
    'en': "  |  4th: {attempts} attempts",
    'es': "  |  4to down: {attempts} intentos",
    'fr': "  |  4e down : {attempts} tentatives",
    'pt': "  |  4th down: {attempts} tentativas",
    'de': "  |  4th Down: {attempts} Versuche",
}
TRANSLATIONS['score.suffix.date'] = {
    'en': " on {date}", 'es': " el {date}", 'fr': " le {date}", 'pt': " em {date}", 'de': " am {date}",
}
TRANSLATIONS['score.success'] = {
    'en': "✅ **{player}** ({league}) → **{actual}**{missed}{def_str}{fourth}{date}.",
    'es': "✅ **{player}** ({league}) → **{actual}**{missed}{def_str}{fourth}{date}.",
    'fr': "✅ **{player}** ({league}) → **{actual}**{missed}{def_str}{fourth}{date}.",
    'pt': "✅ **{player}** ({league}) → **{actual}**{missed}{def_str}{fourth}{date}.",
    'de': "✅ **{player}** ({league}) → **{actual}**{missed}{def_str}{fourth}{date}.",
}
TRANSLATIONS['score.past.placeholder'] = {
    'en': "Select a past matchup...", 'es': "Selecciona un enfrentamiento pasado...",
    'fr': "Sélectionnez un affrontement passé...", 'pt': "Selecione um confronto anterior...",
    'de': "Vergangenes Matchup auswählen...",
}
TRANSLATIONS['score.past.pending'] = {
    'en': "Pending", 'es': "Pendiente", 'fr': "En attente", 'pt': "Pendente", 'de': "Ausstehend",
}
TRANSLATIONS['score.past.prompt'] = {
    'en': "Which matchup is **{player}**'s score for?",
    'es': "¿Para qué enfrentamiento es la puntuación de **{player}**?",
    'fr': "Pour quel affrontement est le score de **{player}** ?",
    'pt': "Para qual confronto é a pontuação de **{player}**?",
    'de': "Für welches Matchup ist der Punktestand von **{player}**?",
}
TRANSLATIONS['score.no_past_matchups'] = {
    'en': "⚠️ No past matchups found. Use `/matchup` to record one first.",
    'es': "⚠️ No se encontraron enfrentamientos pasados. Usa `/matchup` para registrar uno primero.",
    'fr': "⚠️ Aucun affrontement passé trouvé. Utilisez `/matchup` pour en enregistrer un d'abord.",
    'pt': "⚠️ Nenhum confronto anterior encontrado. Use `/matchup` para registrar um primeiro.",
    'de': "⚠️ Keine vergangenen Matchups gefunden. Verwende zuerst `/matchup`, um eins zu erfassen.",
}

# --- /dscore ---

TRANSLATIONS['dscore.modal.title'] = {
    'en': "Record Defensive Score", 'es': "Registrar Puntuación Defensiva",
    'fr': "Enregistrer le Score Défensif", 'pt': "Registrar Pontuação Defensiva",
    'de': "Defensivwertung Erfassen",
}
TRANSLATIONS['dscore.modal.label_points'] = {
    'en': "Points Let Up", 'es': "Puntos Permitidos", 'fr': "Points Concédés",
    'pt': "Pontos Permitidos", 'de': "Zugelassene Punkte",
}
TRANSLATIONS['dscore.modal.label_avg_ovr'] = {
    'en': "Avg Offensive OVR Faced", 'es': "OVR Ofensivo Promedio Enfrentado",
    'fr': "OVR Offensif Moyen Affronté", 'pt': "OVR Ofensivo Médio Enfrentado",
    'de': "Durchschn. Gegnerischer Offensiv-OVR",
}
TRANSLATIONS['dscore.modal.title_drive'] = {
    'en': "Drive {n} Detail", 'es': "Detalle Serie {n}",
    'fr': "Détail Série {n}", 'pt': "Detalhe Série {n}",
    'de': "Drive {n} Detail",
}
TRANSLATIONS['dscore.modal.label_ovr'] = {
    'en': "Opponent OVR Faced", 'es': "OVR del Oponente Enfrentado",
    'fr': "OVR Adverse Affronté", 'pt': "OVR do Oponente Enfrentado",
    'de': "Gegnerischer OVR",
}
TRANSLATIONS['dscore.continue_button.label'] = {
    'en': "Continue to Drive {n}", 'es': "Continuar a la Serie {n}",
    'fr': "Continuer à la Série {n}", 'pt': "Continuar para a Série {n}",
    'de': "Weiter zu Drive {n}",
}
TRANSLATIONS['dscore.continue_prompt'] = {
    'en': "✅ Drive {n} saved — click below to continue with Drive {next}.",
    'es': "✅ Serie {n} guardada — haz clic abajo para continuar con la Serie {next}.",
    'fr': "✅ Série {n} enregistrée — cliquez ci-dessous pour continuer avec la Série {next}.",
    'pt': "✅ Série {n} salva — clique abaixo para continuar com a Série {next}.",
    'de': "✅ Drive {n} gespeichert — klicke unten, um mit Drive {next} fortzufahren.",
}
TRANSLATIONS['dscore.err.invalid_points'] = {
    'en': "⚠️ Points let up must be an integer.",
    'es': "⚠️ Los puntos permitidos deben ser un número entero.",
    'fr': "⚠️ Les points concédés doivent être un entier.",
    'pt': "⚠️ Os pontos permitidos devem ser um número inteiro.",
    'de': "⚠️ Zugelassene Punkte müssen eine ganze Zahl sein.",
}
TRANSLATIONS['dscore.err.invalid_avg_ovr'] = {
    'en': "⚠️ Avg offensive OVR must be a number.",
    'es': "⚠️ El OVR ofensivo promedio debe ser un número.",
    'fr': "⚠️ L'OVR offensif moyen doit être un nombre.",
    'pt': "⚠️ O OVR ofensivo médio deve ser um número.",
    'de': "⚠️ Der durchschnittliche Offensiv-OVR muss eine Zahl sein.",
}
TRANSLATIONS['dscore.suffix.ovr'] = {
    'en': "  |  Avg OFF OVR faced: **{ovr}**", 'es': "  |  OVR OFF promedio enfrentado: **{ovr}**",
    'fr': "  |  OVR OFF moyen affronté : **{ovr}**", 'pt': "  |  OVR OFF médio enfrentado: **{ovr}**",
    'de': "  |  Durchschn. gegnerischer OFF OVR: **{ovr}**",
}
TRANSLATIONS['dscore.success'] = {
    'en': "✅ **{player}** allowed **{allowed}** pts{ovr}{drives}{date}.",
    'es': "✅ **{player}** permitió **{allowed}** pts{ovr}{drives}{date}.",
    'fr': "✅ **{player}** a concédé **{allowed}** pts{ovr}{drives}{date}.",
    'pt': "✅ **{player}** permitiu **{allowed}** pts{ovr}{drives}{date}.",
    'de': "✅ **{player}** hat **{allowed}** Punkte zugelassen{ovr}{drives}{date}.",
}
TRANSLATIONS['dscore.modal.label_drive1'] = {
    'en': "1st Drive (0-8/F/I/S)", 'es': "1ra Serie (0-8/F/I/S)",
    'fr': "1re Série (0-8/F/I/S)", 'pt': "1ª Série (0-8/F/I/S)",
    'de': "1. Drive (0-8/F/I/S)",
}
TRANSLATIONS['dscore.modal.label_drive2'] = {
    'en': "2nd Drive (0-8/F/I/S)", 'es': "2da Serie (0-8/F/I/S)",
    'fr': "2e Série (0-8/F/I/S)", 'pt': "2ª Série (0-8/F/I/S)",
    'de': "2. Drive (0-8/F/I/S)",
}
TRANSLATIONS['dscore.modal.label_drive3'] = {
    'en': "3rd Drive (0-8/F/I/S)", 'es': "3ra Serie (0-8/F/I/S)",
    'fr': "3e Série (0-8/F/I/S)", 'pt': "3ª Série (0-8/F/I/S)",
    'de': "3. Drive (0-8/F/I/S)",
}
TRANSLATIONS['dscore.err.invalid_drive'] = {
    'en': "⚠️ {label} must be 0-8, F, I, or S.",
    'es': "⚠️ {label} debe ser 0-8, F, I o S.",
    'fr': "⚠️ {label} doit être 0-8, F, I ou S.",
    'pt': "⚠️ {label} deve ser 0-8, F, I ou S.",
    'de': "⚠️ {label} muss 0-8, F, I oder S sein.",
}
TRANSLATIONS['dscore.suffix.drives'] = {
    'en': "  |  Drives: {summary}", 'es': "  |  Series: {summary}",
    'fr': "  |  Séries : {summary}", 'pt': "  |  Séries: {summary}",
    'de': "  |  Drives: {summary}",
}
TRANSLATIONS['dscore.turnover_modal.title'] = {
    'en': "Drive {n} Turnover ({type})", 'es': "Serie {n} — Turnover ({type})",
    'fr': "Série {n} — Turnover ({type})", 'pt': "Série {n} — Turnover ({type})",
    'de': "Drive {n} Ballverlust ({type})",
}
TRANSLATIONS['dscore.turnover_modal.label_down'] = {
    'en': "Down", 'es': "Down", 'fr': "Down", 'pt': "Down", 'de': "Down",
}
TRANSLATIONS['dscore.turnover_modal.label_distance'] = {
    'en': "Distance", 'es': "Distancia", 'fr': "Distance", 'pt': "Distância", 'de': "Distanz",
}
TRANSLATIONS['dscore.turnover_modal.label_play'] = {
    'en': "Play", 'es': "Jugada", 'fr': "Action", 'pt': "Jogada", 'de': "Spielzug",
}
TRANSLATIONS['dscore.turnover_modal.label_forced_by'] = {
    'en': "Forced By", 'es': "Forzado Por", 'fr': "Forcé Par", 'pt': "Forçado Por", 'de': "Erzwungen Von",
}
TRANSLATIONS['dscore.turnover_modal.placeholder_down'] = {
    'en': "e.g. 3rd", 'es': "ej. 3ro", 'fr': "ex. 3e", 'pt': "ex. 3ª", 'de': "z. B. 3.",
}
TRANSLATIONS['dscore.turnover_modal.placeholder_distance'] = {
    'en': "e.g. 8", 'es': "ej. 8", 'fr': "ex. 8", 'pt': "ex. 8", 'de': "z. B. 8",
}
TRANSLATIONS['dscore.turnover_modal.placeholder'] = {
    'en': "e.g. ball popped out on the tackle",
    'es': "ej. se le cayó el balón en el tackle",
    'fr': "ex. ballon perdu sur le plaquage",
    'pt': "ex. a bola saiu no carrinho",
    'de': "z. B. Ball beim Tackle verloren",
}
TRANSLATIONS['dscore.turnover_modal.placeholder_forced_by'] = {
    'en': "e.g. Grizzly", 'es': "ej. Grizzly", 'fr': "ex. Grizzly", 'pt': "ex. Grizzly", 'de': "z. B. Grizzly",
}
TRANSLATIONS['dscore.turnover_success'] = {
    'en': "✅ **{player}** allowed **{allowed}** pts{ovr}{drives}{date}.\n{plays}",
    'es': "✅ **{player}** permitió **{allowed}** pts{ovr}{drives}{date}.\n{plays}",
    'fr': "✅ **{player}** a concédé **{allowed}** pts{ovr}{drives}{date}.\n{plays}",
    'pt': "✅ **{player}** permitiu **{allowed}** pts{ovr}{drives}{date}.\n{plays}",
    'de': "✅ **{player}** hat **{allowed}** Punkte zugelassen{ovr}{drives}{date}.\n{plays}",
}
TRANSLATIONS['dscore.turnover_success.play_line'] = {
    'en': "Drive {n} ({type}): {down} & {distance} — {play} (forced by {forced_by})",
    'es': "Serie {n} ({type}): {down} y {distance} — {play} (forzado por {forced_by})",
    'fr': "Série {n} ({type}) : {down} et {distance} — {play} (forcé par {forced_by})",
    'pt': "Série {n} ({type}): {down} e {distance} — {play} (forçado por {forced_by})",
    'de': "Drive {n} ({type}): {down} & {distance} — {play} (erzwungen von {forced_by})",
}
TRANSLATIONS['dscore.turnover_type.F'] = {
    'en': "Fumble", 'es': "Balón Perdido", 'fr': "Ballon Perdu", 'pt': "Fumble", 'de': "Fumble",
}
TRANSLATIONS['dscore.turnover_type.I'] = {
    'en': "Interception", 'es': "Intercepción", 'fr': "Interception", 'pt': "Interceptação", 'de': "Interception",
}
TRANSLATIONS['dscore.turnover_type.S'] = {
    'en': "Safety", 'es': "Safety", 'fr': "Sécurité", 'pt': "Safety", 'de': "Safety",
}
TRANSLATIONS['dscore.turnover_button.label'] = {
    'en': "Enter Drive {n} Details", 'es': "Ingresar Detalles Serie {n}",
    'fr': "Saisir les Détails Série {n}", 'pt': "Inserir Detalhes Série {n}",
    'de': "Drive {n} Details Eingeben",
}
TRANSLATIONS['dscore.turnover_prompt'] = {
    'en': "⚠️ Drive {n} was a turnover ({type}) — click below to enter the details.",
    'es': "⚠️ La serie {n} fue un balón perdido ({type}) — haz clic abajo para ingresar los detalles.",
    'fr': "⚠️ La série {n} a été un ballon perdu ({type}) — cliquez ci-dessous pour saisir les détails.",
    'pt': "⚠️ A série {n} foi uma perda de bola ({type}) — clique abaixo para inserir os detalhes.",
    'de': "⚠️ Drive {n} war ein Ballverlust ({type}) — klicke unten, um die Details einzugeben.",
}

# --- /player ---

TRANSLATIONS['player.status_active']   = {'en': "🟢 Active", 'es': "🟢 Activo", 'fr': "🟢 Actif", 'pt': "🟢 Ativo", 'de': "🟢 Aktiv"}
TRANSLATIONS['player.status_inactive'] = {'en': "⚫ Inactive", 'es': "⚫ Inactivo", 'fr': "⚫ Inactif", 'pt': "⚫ Inativo", 'de': "⚫ Inaktiv"}
TRANSLATIONS['player.field.league']    = {'en': "League", 'es': "Liga", 'fr': "Ligue", 'pt': "Liga", 'de': "Liga"}
TRANSLATIONS['player.field.status']    = {'en': "Status", 'es': "Estado", 'fr': "Statut", 'pt': "Status", 'de': "Status"}
TRANSLATIONS['player.field.pwr_rank']  = {'en': "Pwr Rank", 'es': "Rango de Poder", 'fr': "Rang de Puissance", 'pt': "Rank de Poder", 'de': "Power-Rang"}
TRANSLATIONS['player.field.off_ovr']   = {'en': "Off OVR", 'es': "OVR Ofensivo", 'fr': "OVR Offensif", 'pt': "OVR Ofensivo", 'de': "Offensiv-OVR"}
TRANSLATIONS['player.field.def_ovr']   = {'en': "Def OVR", 'es': "OVR Defensivo", 'fr': "OVR Défensif", 'pt': "OVR Defensivo", 'de': "Defensiv-OVR"}
TRANSLATIONS['player.field.total_ovr'] = {'en': "Total OVR", 'es': "OVR Total", 'fr': "OVR Total", 'pt': "OVR Total", 'de': "Gesamt-OVR"}
TRANSLATIONS['player.field.games']     = {'en': "Games", 'es': "Partidas", 'fr': "Matchs", 'pt': "Jogos", 'de': "Spiele"}
TRANSLATIONS['player.field.points']    = {'en': "Points", 'es': "Puntos", 'fr': "Points", 'pt': "Pontos", 'de': "Punkte"}
TRANSLATIONS['player.field.kobes']     = {'en': "Kobes", 'es': "Kobes", 'fr': "Kobes", 'pt': "Kobes", 'de': "Kobes"}
TRANSLATIONS['player.field.yearly_avg']= {'en': "Yearly Avg", 'es': "Promedio Anual", 'fr': "Moyenne Annuelle", 'pt': "Média Anual", 'de': "Jahresdurchschnitt"}
TRANSLATIONS['player.field.30day_avg'] = {'en': "30-Day Avg", 'es': "Promedio 30 Días", 'fr': "Moyenne 30 Jours", 'pt': "Média 30 Dias", 'de': "30-Tage-Schnitt"}
TRANSLATIONS['player.field.14day_avg'] = {'en': "14-Day Avg", 'es': "Promedio 14 Días", 'fr': "Moyenne 14 Jours", 'pt': "Média 14 Dias", 'de': "14-Tage-Schnitt"}
TRANSLATIONS['player.field.7day_avg']  = {'en': "7-Day Avg", 'es': "Promedio 7 Días", 'fr': "Moyenne 7 Jours", 'pt': "Média 7 Dias", 'de': "7-Tage-Schnitt"}
TRANSLATIONS['player.field.3day_avg']  = {'en': "3-Day Avg", 'es': "Promedio 3 Días", 'fr': "Moyenne 3 Jours", 'pt': "Média 3 Dias", 'de': "3-Tage-Schnitt"}
TRANSLATIONS['player.field.hof_avg']   = {'en': "HOF Avg", 'es': "Promedio HOF", 'fr': "Moyenne HOF", 'pt': "Média HOF", 'de': "HOF-Schnitt"}
TRANSLATIONS['player.field.e1_avg']    = {'en': "E1 Avg", 'es': "Promedio E1", 'fr': "Moyenne E1", 'pt': "Média E1", 'de': "E1-Schnitt"}
TRANSLATIONS['player.field.e2_avg']    = {'en': "E2 Avg", 'es': "Promedio E2", 'fr': "Moyenne E2", 'pt': "Média E2", 'de': "E2-Schnitt"}
TRANSLATIONS['player.field.e3_avg']    = {'en': "E3 Avg", 'es': "Promedio E3", 'fr': "Moyenne E3", 'pt': "Média E3", 'de': "E3-Schnitt"}
TRANSLATIONS['player.field.gold_avg']  = {'en': "Gold- Avg", 'es': "Promedio Gold-", 'fr': "Moyenne Gold-", 'pt': "Média Gold-", 'de': "Gold--Schnitt"}
# Combined plain+fumble-adjusted display for the player card — folds both
# numbers into one field's value rather than a separate field per average,
# since showing all 10 averages as separate plain/fumble-adj pairs would
# need ~20 fields on their own, well past Discord's 25-per-embed limit
# once combined with everything else already on this card.
TRANSLATIONS['player.avg_with_fumble_adj'] = {
    'en': "{plain} (FA: {fumble_adj})", 'es': "{plain} (FA: {fumble_adj})",
    'fr': "{plain} (FA : {fumble_adj})", 'pt': "{plain} (FA: {fumble_adj})",
    'de': "{plain} (FA: {fumble_adj})",
}
TRANSLATIONS['player.field.3td_pct']   = {'en': "3TD%", 'es': "3TD%", 'fr': "3TD%", 'pt': "3TD%", 'de': "3TD%"}
TRANSLATIONS['player.field.2pt_pct']   = {'en': "2PT%", 'es': "2PT%", 'fr': "2PT%", 'pt': "2PT%", 'de': "2PT%"}
TRANSLATIONS['player.field.fumbles']   = {'en': "Fumbles", 'es': "Balones Perdidos", 'fr': "Fumbles", 'pt': "Fumbles", 'de': "Fumbles"}
TRANSLATIONS['player.field.missed_drives'] = {'en': "Missed Drives", 'es': "Drives Fallados", 'fr': "Drives Manqués", 'pt': "Drives Perdidos", 'de': "Verpasste Drives"}
TRANSLATIONS['player.field.4th_downs'] = {'en': "4th Downs", 'es': "4tos Downs", 'fr': "4e Downs", 'pt': "4th Downs", 'de': "4th Downs"}

# --- /avg ---

TRANSLATIONS['avg.select_placeholder'] = {
    'en': "Choose average type...", 'es': "Elige el tipo de promedio...",
    'fr': "Choisissez le type de moyenne...", 'pt': "Escolha o tipo de média...",
    'de': "Durchschnittstyp wählen...",
}
TRANSLATIONS['avg.prompt'] = {
    'en': "What average would you like for **{player}**?",
    'es': "¿Qué promedio te gustaría ver de **{player}**?",
    'fr': "Quelle moyenne souhaitez-vous pour **{player}** ?",
    'pt': "Qual média você gostaria de ver de **{player}**?",
    'de': "Welchen Durchschnitt möchtest du für **{player}** sehen?",
}
TRANSLATIONS['streak.result'] = {
    'en': "🔥 **{player}**'s current streaks:\nKobe streak (24+pt games in a row): **{kobe_streak}**\nNo-drop streak (18+pt games in a row, no dropped drives): **{no_drop_streak}**",
    'es': "🔥 Rachas actuales de **{player}**:\nRacha Kobe (juegos de 24+pts consecutivos): **{kobe_streak}**\nRacha sin fumbles (juegos de 18+pts consecutivos, sin drives perdidos): **{no_drop_streak}**",
    'fr': "🔥 Séries actuelles de **{player}** :\nSérie Kobe (matchs à 24+pts consécutifs) : **{kobe_streak}**\nSérie sans drive manqué (matchs à 18+pts consécutifs, sans drive manqué) : **{no_drop_streak}**",
    'pt': "🔥 Sequências atuais de **{player}**:\nSequência Kobe (jogos de 24+pts consecutivos): **{kobe_streak}**\nSequência sem drive perdido (jogos de 18+pts consecutivos, sem drives perdidos): **{no_drop_streak}**",
    'de': "🔥 Aktuelle Serien von **{player}**:\nKobe-Serie (24+-Punkte-Spiele in Folge): **{kobe_streak}**\nSerie ohne verlorenen Drive (18+-Punkte-Spiele in Folge, ohne verlorene Drives): **{no_drop_streak}**",
}
TRANSLATIONS['openspots.header'] = {
    'en': "📋 **Open Roster Spots by League**",
    'es': "📋 **Cupos Abiertos por Liga**",
    'fr': "📋 **Places Disponibles par Ligue**",
    'pt': "📋 **Vagas Abertas por Liga**",
    'de': "📋 **Offene Kaderplätze pro Liga**",
}
TRANSLATIONS['openspots.line'] = {
    'en': "**{league}**: {open_spots} open ({active}/18 active)",
    'es': "**{league}**: {open_spots} abiertos ({active}/18 activos)",
    'fr': "**{league}** : {open_spots} disponibles ({active}/18 actifs)",
    'pt': "**{league}**: {open_spots} abertas ({active}/18 ativos)",
    'de': "**{league}**: {open_spots} offen ({active}/18 aktiv)",
}
TRANSLATIONS['avg.no_avg_found'] = {
    'en': "⚠️ No {atype} average found for **{player}**.",
    'es': "⚠️ No se encontró el promedio de {atype} para **{player}**.",
    'fr': "⚠️ Aucune moyenne {atype} trouvée pour **{player}**.",
    'pt': "⚠️ Nenhuma média de {atype} encontrada para **{player}**.",
    'de': "⚠️ Kein {atype}-Durchschnitt für **{player}** gefunden.",
}
TRANSLATIONS['avg.result'] = {
    'en': "**{player}**'s {atype} average: **{avg}**\nFumble-adjusted (fumbles counted as null drives): **{fumble_adj_avg}**",
    'es': "Promedio de {atype} de **{player}**: **{avg}**\nAjustado por fumbles (fumbles contados como drives nulos): **{fumble_adj_avg}**",
    'fr': "Moyenne {atype} de **{player}** : **{avg}**\nAjustée pour les fumbles (fumbles comptés comme des drives nuls) : **{fumble_adj_avg}**",
    'pt': "Média de {atype} de **{player}**: **{avg}**\nAjustada por fumbles (fumbles contados como drives nulos): **{fumble_adj_avg}**",
    'de': "{atype}-Durchschnitt von **{player}**: **{avg}**\nFumble-bereinigt (Fumbles als Null-Drives gezählt): **{fumble_adj_avg}**",
}

# --- /history ---

TRANSLATIONS['history.err.start_date'] = {
    'en': "⚠️ Start date must be YYYY-MM-DD.", 'es': "⚠️ La fecha de inicio debe ser YYYY-MM-DD.",
    'fr': "⚠️ La date de début doit être au format YYYY-MM-DD.",
    'pt': "⚠️ A data de início deve ser YYYY-MM-DD.", 'de': "⚠️ Das Startdatum muss YYYY-MM-DD sein.",
}
TRANSLATIONS['history.err.end_date'] = {
    'en': "⚠️ End date must be YYYY-MM-DD.", 'es': "⚠️ La fecha de fin debe ser YYYY-MM-DD.",
    'fr': "⚠️ La date de fin doit être au format YYYY-MM-DD.",
    'pt': "⚠️ A data de término deve ser YYYY-MM-DD.", 'de': "⚠️ Das Enddatum muss YYYY-MM-DD sein.",
}
TRANSLATIONS['history.err.end_before_start'] = {
    'en': "⚠️ End date must be after start date.",
    'es': "⚠️ La fecha de fin debe ser posterior a la fecha de inicio.",
    'fr': "⚠️ La date de fin doit être postérieure à la date de début.",
    'pt': "⚠️ A data de término deve ser posterior à data de início.",
    'de': "⚠️ Das Enddatum muss nach dem Startdatum liegen.",
}
TRANSLATIONS['history.no_scores'] = {
    'en': "No scores found for **{player}** between `{start}` and `{end}`.",
    'es': "No se encontraron puntuaciones de **{player}** entre `{start}` y `{end}`.",
    'fr': "Aucun score trouvé pour **{player}** entre le `{start}` et le `{end}`.",
    'pt': "Nenhuma pontuação encontrada para **{player}** entre `{start}` e `{end}`.",
    'de': "Keine Punktestände für **{player}** zwischen `{start}` und `{end}` gefunden.",
}
TRANSLATIONS['history.col.date'] = {'en': "Date", 'es': "Fecha", 'fr': "Date", 'pt': "Data", 'de': "Datum"}
TRANSLATIONS['history.col.evt']  = {'en': "Evt", 'es': "Evt", 'fr': "Évt", 'pt': "Evt", 'de': "Evt"}
TRANSLATIONS['history.col.sc']   = {'en': "Sc", 'es': "Pt", 'fr': "Sc", 'pt': "Pt", 'de': "Pkt"}
TRANSLATIONS['history.col.def']  = {'en': "DEF", 'es': "DEF", 'fr': "DEF", 'pt': "DEF", 'de': "DEF"}
TRANSLATIONS['history.col.4th']  = {'en': "4th", 'es': "4to", 'fr': "4e", 'pt': "4th", 'de': "4th"}
TRANSLATIONS['history.footer.games_avg'] = {
    'en': "Games:{games}  Avg:{avg}  Hi:{hi}  Lo:{lo}",
    'es': "Partidas:{games}  Prom:{avg}  Máx:{hi}  Mín:{lo}",
    'fr': "Matchs:{games}  Moy:{avg}  Max:{hi}  Min:{lo}",
    'pt': "Jogos:{games}  Média:{avg}  Máx:{hi}  Mín:{lo}",
    'de': "Spiele:{games}  Schnitt:{avg}  Hoch:{hi}  Tief:{lo}",
}
TRANSLATIONS['history.footer.4th_downs'] = {
    'en': "4th downs: {conv}/{total} ({rate})",
    'es': "4tos downs: {conv}/{total} ({rate})",
    'fr': "4e downs : {conv}/{total} ({rate})",
    'pt': "4th downs: {conv}/{total} ({rate})",
    'de': "4th Downs: {conv}/{total} ({rate})",
}
TRANSLATIONS['history.footer.missed'] = {
    'en': "Missed Drives: {count}", 'es': "Drives Fallados: {count}", 'fr': "Drives Manqués : {count}",
    'pt': "Drives Perdidos: {count}", 'de': "Verpasste Drives: {count}",
}
TRANSLATIONS['history.footer.fumbles'] = {
    'en': "Fumbles: {count}", 'es': "Balones Perdidos: {count}", 'fr': "Fumbles : {count}",
    'pt': "Fumbles: {count}", 'de': "Fumbles: {count}",
}
TRANSLATIONS['history.title'] = {
    'en': "📊 {player} — {start} to {end}", 'es': "📊 {player} — {start} a {end}",
    'fr': "📊 {player} — {start} au {end}", 'pt': "📊 {player} — {start} a {end}",
    'de': "📊 {player} — {start} bis {end}",
}
TRANSLATIONS['history.field.scores'] = {'en': "Scores", 'es': "Puntuaciones", 'fr': "Scores", 'pt': "Pontuações", 'de': "Punktestände"}
TRANSLATIONS['history.field.scores_paged'] = {
    'en': "Scores (page {page}/{total})", 'es': "Puntuaciones (página {page}/{total})",
    'fr': "Scores (page {page}/{total})", 'pt': "Pontuações (página {page}/{total})",
    'de': "Punktestände (Seite {page}/{total})",
}

# --- /status ---

TRANSLATIONS['status.already_clinched'] = {'en': "Already clinched!", 'es': "¡Ya asegurado!", 'fr': "Déjà remporté !", 'pt': "Já garantido!", 'de': "Bereits gesichert!"}
TRANSLATIONS['status.ppd_needed'] = {
    'en': "{ppd} pts/drive needed", 'es': "{ppd} pts/drive necesarios", 'fr': "{ppd} pts/drive nécessaires",
    'pt': "{ppd} pts/drive necessários", 'de': "{ppd} Pkt/Drive benötigt",
}
TRANSLATIONS['status.no_drives_left'] = {'en': "No drives left", 'es': "Sin drives restantes", 'fr': "Plus de drives restants", 'pt': "Sem drives restantes", 'de': "Keine Drives mehr übrig"}
TRANSLATIONS['status.ahead']  = {'en': "🟢 **AHEAD**", 'es': "🟢 **POR DELANTE**", 'fr': "🟢 **EN TÊTE**", 'pt': "🟢 **NA FRENTE**", 'de': "🟢 **VORNE**"}
TRANSLATIONS['status.behind'] = {'en': "🔴 **BEHIND**", 'es': "🔴 **POR DETRÁS**", 'fr': "🔴 **DERRIÈRE**", 'pt': "🔴 **ATRÁS**", 'de': "🔴 **HINTEN**"}
TRANSLATIONS['status.tied']   = {'en': "🟡 **TIED**", 'es': "🟡 **EMPATADO**", 'fr': "🟡 **ÉGALITÉ**", 'pt': "🟡 **EMPATADO**", 'de': "🟡 **UNENTSCHIEDEN**"}
TRANSLATIONS['status.field.scoreboard'] = {'en': "📊 Scoreboard", 'es': "📊 Marcador", 'fr': "📊 Tableau des Scores", 'pt': "📊 Placar", 'de': "📊 Punktetafel"}
TRANSLATIONS['status.field.drives'] = {'en': "🚗 Drives", 'es': "🚗 Drives", 'fr': "🚗 Drives", 'pt': "🚗 Drives", 'de': "🚗 Drives"}
TRANSLATIONS['status.defaults_us'] = {
    'en': "{n} default(s) (us)", 'es': "{n} default(es) (nosotros)", 'fr': "{n} forfait(s) (nous)",
    'pt': "{n} default(s) (nós)", 'de': "{n} Default(s) (wir)",
}
TRANSLATIONS['status.defaults_them'] = {
    'en': "{n} default(s) (them)", 'es': "{n} default(es) (ellos)", 'fr': "{n} forfait(s) (eux)",
    'pt': "{n} default(s) (eles)", 'de': "{n} Default(s) (Gegner)",
}
TRANSLATIONS['status.field.outlook'] = {'en': "📈 Outlook", 'es': "📈 Perspectiva", 'fr': "📈 Perspective", 'pt': "📈 Perspectiva", 'de': "📈 Prognose"}
TRANSLATIONS['status.clinched_value'] = {
    'en': "**Clinched!** Win is locked.", 'es': "**¡Asegurado!** La victoria está garantizada.",
    'fr': "**Remporté !** La victoire est assurée.", 'pt': "**Garantido!** A vitória está assegurada.",
    'de': "**Gesichert!** Der Sieg ist garantiert.",
}
TRANSLATIONS['status.impossible_suffix'] = {
    'en': " *(impossible)*", 'es': " *(imposible)*", 'fr': " *(impossible)*",
    'pt': " *(impossível)*", 'de': " *(unmöglich)*",
}
TRANSLATIONS['status.need_value'] = {
    'en': "Need **{pts}** pts\n{ppd}{impossible}",
    'es': "Necesitas **{pts}** pts\n{ppd}{impossible}",
    'fr': "Besoin de **{pts}** pts\n{ppd}{impossible}",
    'pt': "Precisa de **{pts}** pts\n{ppd}{impossible}",
    'de': "Benötigt **{pts}** Pkt\n{ppd}{impossible}",
}
TRANSLATIONS['status.field.to_clinch'] = {'en': "To Clinch", 'es': "Para Asegurar", 'fr': "Pour Remporter", 'pt': "Para Garantir", 'de': "Zum Sichern"}
TRANSLATIONS['status.all_scored'] = {
    'en': "✅ All players have scored!", 'es': "✅ ¡Todos los jugadores han anotado!",
    'fr': "✅ Tous les joueurs ont marqué !", 'pt': "✅ Todos os jogadores já pontuaram!",
    'de': "✅ Alle Spieler haben gewertet!",
}
TRANSLATIONS['status.field.remaining'] = {
    'en': "⏳ Players Remaining — {left} of {total}", 'es': "⏳ Jugadores Restantes — {left} de {total}",
    'fr': "⏳ Joueurs Restants — {left} sur {total}", 'pt': "⏳ Jogadores Restantes — {left} de {total}",
    'de': "⏳ Verbleibende Spieler — {left} von {total}",
}
TRANSLATIONS['status.footer'] = {
    'en': "Progress  [{bar}]  {played}/{total}  ·  Game day: {today}",
    'es': "Progreso  [{bar}]  {played}/{total}  ·  Día de juego: {today}",
    'fr': "Progression  [{bar}]  {played}/{total}  ·  Jour de jeu : {today}",
    'pt': "Progresso  [{bar}]  {played}/{total}  ·  Dia de jogo: {today}",
    'de': "Fortschritt  [{bar}]  {played}/{total}  ·  Spieltag: {today}",
}

# --- /scores ---

TRANSLATIONS['scores.no_scores'] = {
    'en': "No scores recorded for this date.", 'es': "No hay puntuaciones registradas para esta fecha.",
    'fr': "Aucun score enregistré pour cette date.", 'pt': "Nenhuma pontuação registrada para esta data.",
    'de': "Für dieses Datum sind keine Punktestände erfasst.",
}
TRANSLATIONS['scores.team_total'] = {
    'en': "**Team Total: {total}**", 'es': "**Total del Equipo: {total}**",
    'fr': "**Total de l'Équipe : {total}**", 'pt': "**Total da Equipe: {total}**",
    'de': "**Team-Gesamt: {total}**",
}

# --- /opp ---

TRANSLATIONS['opp.source_today'] = {'en': "today's ladder", 'es': "escalafón de hoy", 'fr': "classement du jour", 'pt': "ranking de hoje", 'de': "heutige Rangliste"}
TRANSLATIONS['opp.source_static'] = {'en': "static ladder reference", 'es': "referencia estática de escalafón", 'fr': "référence de classement statique", 'pt': "referência estática de ranking", 'de': "statische Ranglisten-Referenz"}
TRANSLATIONS['opp.no_matchup'] = {
    'en': "⚠️ No ladder matchup found for **{player}**. Use `/ladder` to build today's matchups.",
    'es': "⚠️ No se encontró un enfrentamiento de escalafón para **{player}**. Usa `/ladder` para armar los enfrentamientos de hoy.",
    'fr': "⚠️ Aucun affrontement de classement trouvé pour **{player}**. Utilisez `/ladder` pour construire les affrontements du jour.",
    'pt': "⚠️ Nenhum confronto de ranking encontrado para **{player}**. Use `/ladder` para montar os confrontos de hoje.",
    'de': "⚠️ Kein Ranglisten-Matchup für **{player}** gefunden. Verwende `/ladder`, um die heutigen Matchups zu erstellen.",
}
TRANSLATIONS['opp.field.opponent'] = {'en': "Opponent", 'es': "Oponente", 'fr': "Adversaire", 'pt': "Oponente", 'de': "Gegner"}
TRANSLATIONS['opp.def_ovr_label'] = {'en': "DEF OVR: **{ovr}**", 'es': "DEF OVR: **{ovr}**", 'fr': "DEF OVR : **{ovr}**", 'pt': "DEF OVR: **{ovr}**", 'de': "DEF OVR: **{ovr}**"}
TRANSLATIONS['opp.field.your_ovr'] = {'en': "Your OVR", 'es': "Tu OVR", 'fr': "Votre OVR", 'pt': "Seu OVR", 'de': "Dein OVR"}
TRANSLATIONS['opp.tier_label'] = {'en': "\nTier: **{tier}**", 'es': "\nNivel: **{tier}**", 'fr': "\nNiveau : **{tier}**", 'pt': "\nNível: **{tier}**", 'de': "\nStufe: **{tier}**"}
TRANSLATIONS['opp.field.your_score'] = {'en': "Your Score Today", 'es': "Tu Puntuación de Hoy", 'fr': "Votre Score du Jour", 'pt': "Sua Pontuação Hoje", 'de': "Dein Heutiger Punktestand"}
TRANSLATIONS['opp.score_excused'] = {'en': "**E** *(excused)*", 'es': "**E** *(justificado)*", 'fr': "**E** *(excusé)*", 'pt': "**E** *(justificado)*", 'de': "**E** *(entschuldigt)*"}
TRANSLATIONS['opp.score_missed'] = {'en': "**M** *(missed drives)*", 'es': "**M** *(drives fallados)*", 'fr': "**M** *(drive manqué)*", 'pt': "**M** *(drives perdidos)*", 'de': "**M** *(verpasste Drives)*"}
TRANSLATIONS['opp.not_scored'] = {'en': "*Not yet scored*", 'es': "*Aún sin puntuación*", 'fr': "*Pas encore marqué*", 'pt': "*Ainda não pontuou*", 'de': "*Noch nicht gewertet*"}
TRANSLATIONS['opp.field.result'] = {'en': "Result", 'es': "Resultado", 'fr': "Résultat", 'pt': "Resultado", 'de': "Ergebnis"}
TRANSLATIONS['opp.footer'] = {
    'en': "Game day: {today}", 'es': "Día de juego: {today}", 'fr': "Jour de jeu : {today}",
    'pt': "Dia de jogo: {today}", 'de': "Spieltag: {today}",
}

# =============================================================================
# TIER 2 — Siege gamemode
# =============================================================================

# --- /siege ---

TRANSLATIONS['siege.start.modal_title'] = {'en': "Start Siege Match", 'es': "Iniciar Combate de Asedio", 'fr': "Démarrer un Siège", 'pt': "Iniciar Cerco", 'de': "Belagerung Starten"}
TRANSLATIONS['siege.start.label_opp_league'] = {'en': "Opposing League", 'es': "Liga Oponente", 'fr': "Ligue Adverse", 'pt': "Liga Adversária", 'de': "Gegnerische Liga"}
TRANSLATIONS['siege.start.label_opp_rank']   = {'en': "Opponent Rank", 'es': "Rango del Oponente", 'fr': "Rang de l'Adversaire", 'pt': "Rank do Oponente", 'de': "Gegnerischer Rang"}
TRANSLATIONS['siege.start.label_our_rank']   = {'en': "Our Rank", 'es': "Nuestro Rango", 'fr': "Notre Rang", 'pt': "Nosso Rank", 'de': "Unser Rang"}
TRANSLATIONS['siege.start.label_division']   = {'en': "Division", 'es': "División", 'fr': "Division", 'pt': "Divisão", 'de': "Division"}
TRANSLATIONS['siege.start.success'] = {
    'en': "⚔️ Siege started for **{league}** vs **{opp_league}**!\nUse `/node` as opponents become visible, then `/siegescore` to log drives.",
    'es': "⚔️ ¡Combate de asedio iniciado para **{league}** vs **{opp_league}**!\nUsa `/node` a medida que los oponentes se hagan visibles, luego `/siegescore` para registrar drives.",
    'fr': "⚔️ Siège démarré pour **{league}** contre **{opp_league}** !\nUtilisez `/node` dès que des adversaires deviennent visibles, puis `/siegescore` pour enregistrer les drives.",
    'pt': "⚔️ Cerco iniciado para **{league}** vs **{opp_league}**!\nUse `/node` conforme os oponentes ficam visíveis, depois `/siegescore` para registrar drives.",
    'de': "⚔️ Belagerung gestartet für **{league}** gegen **{opp_league}**!\nVerwende `/node`, sobald Gegner sichtbar werden, dann `/siegescore`, um Drives zu erfassen.",
}

# --- /node ---

TRANSLATIONS['siege.node.modal_title'] = {'en': "Report Siege Node", 'es': "Reportar Nodo de Asedio", 'fr': "Signaler un Nœud de Siège", 'pt': "Reportar Nó de Cerco", 'de': "Belagerungsknoten Melden"}
TRANSLATIONS['siege.node.label_opponent_name']   = {'en': "Opponent Name", 'es': "Nombre del Oponente", 'fr': "Nom de l'Adversaire", 'pt': "Nome do Oponente", 'de': "Gegnername"}
TRANSLATIONS['siege.node.label_opponent_ovr']    = {'en': "Opponent OVR", 'es': "OVR del Oponente", 'fr': "OVR de l'Adversaire", 'pt': "OVR do Oponente", 'de': "Gegner-OVR"}
TRANSLATIONS['siege.node.label_points_required'] = {'en': "Points Required to Clear", 'es': "Puntos Requeridos para Despejar", 'fr': "Points Requis pour Dégager", 'pt': "Pontos Necessários para Liberar", 'de': "Benötigte Punkte zum Freischalten"}
TRANSLATIONS['siege.node.label_points_reward']   = {'en': "Points Reward", 'es': "Puntos de Recompensa", 'fr': "Points de Récompense", 'pt': "Pontos de Recompensa", 'de': "Belohnungspunkte"}
TRANSLATIONS['siege.node.err_blank_name'] = {
    'en': "⚠️ Opponent name can't be blank.", 'es': "⚠️ El nombre del oponente no puede estar vacío.",
    'fr': "⚠️ Le nom de l'adversaire ne peut pas être vide.", 'pt': "⚠️ O nome do oponente não pode ficar em branco.",
    'de': "⚠️ Der Gegnername darf nicht leer sein.",
}
TRANSLATIONS['siege.node.err_invalid_numbers'] = {
    'en': "⚠️ Opponent OVR / points required / points reward must be integers.",
    'es': "⚠️ El OVR del oponente / puntos requeridos / puntos de recompensa deben ser números enteros.",
    'fr': "⚠️ L'OVR de l'adversaire / les points requis / les points de récompense doivent être des entiers.",
    'pt': "⚠️ O OVR do oponente / pontos necessários / pontos de recompensa devem ser números inteiros.",
    'de': "⚠️ Gegner-OVR / benötigte Punkte / Belohnungspunkte müssen ganze Zahlen sein.",
}
TRANSLATIONS['siege.node.ovr_suffix'] = {'en': " (OVR {ovr})", 'es': " (OVR {ovr})", 'fr': " (OVR {ovr})", 'pt': " (OVR {ovr})", 'de': " (OVR {ovr})"}
TRANSLATIONS['siege.node.success'] = {
    'en': "🔓 Node added: **{name}**{ovr} — **{mod}**\nRequires **{req}** pts to clear, rewards **{reward}** pts. Use `/siegescore` to log against it.",
    'es': "🔓 Nodo agregado: **{name}**{ovr} — **{mod}**\nRequiere **{req}** pts para despejarlo, recompensa **{reward}** pts. Usa `/siegescore` para registrar contra él.",
    'fr': "🔓 Nœud ajouté : **{name}**{ovr} — **{mod}**\nNécessite **{req}** pts pour le dégager, récompense **{reward}** pts. Utilisez `/siegescore` pour enregistrer contre lui.",
    'pt': "🔓 Nó adicionado: **{name}**{ovr} — **{mod}**\nRequer **{req}** pts para liberar, recompensa **{reward}** pts. Use `/siegescore` para registrar contra ele.",
    'de': "🔓 Knoten hinzugefügt: **{name}**{ovr} — **{mod}**\nBenötigt **{req}** Pkt zum Freischalten, belohnt **{reward}** Pkt. Verwende `/siegescore`, um dagegen zu erfassen.",
}
TRANSLATIONS['siege.no_active_match'] = {
    'en': "⚠️ No active siege match for **{league}**. Use `/siege` to start one.",
    'es': "⚠️ No hay un combate de asedio activo para **{league}**. Usa `/siege` para iniciar uno.",
    'fr': "⚠️ Aucun siège actif pour **{league}**. Utilisez `/siege` pour en démarrer un.",
    'pt': "⚠️ Nenhum cerco ativo para **{league}**. Use `/siege` para iniciar um.",
    'de': "⚠️ Keine aktive Belagerung für **{league}**. Verwende `/siege`, um eine zu starten.",
}
TRANSLATIONS['siege.no_active_match_short'] = {
    'en': "⚠️ No active siege match for **{league}**.", 'es': "⚠️ No hay un combate de asedio activo para **{league}**.",
    'fr': "⚠️ Aucun siège actif pour **{league}**.", 'pt': "⚠️ Nenhum cerco ativo para **{league}**.",
    'de': "⚠️ Keine aktive Belagerung für **{league}**.",
}

# --- /siegescore ---

TRANSLATIONS['siege.score.ambiguous_name'] = {
    'en': "⚠️ There are **{count}** open nodes named `{name}` in this match (this can happen among the un-modded opponents). Please pick the exact one from the autocomplete list instead of typing the name.",
    'es': "⚠️ Hay **{count}** nodos abiertos llamados `{name}` en este combate (esto puede pasar entre los oponentes sin mod). Elige el exacto desde la lista de autocompletado en lugar de escribir el nombre.",
    'fr': "⚠️ Il y a **{count}** nœuds ouverts nommés `{name}` dans ce siège (cela peut arriver parmi les adversaires sans mod). Veuillez choisir le bon dans la liste d'autocomplétion plutôt que de taper le nom.",
    'pt': "⚠️ Existem **{count}** nós abertos chamados `{name}` neste cerco (isso pode acontecer entre os oponentes sem mod). Escolha o exato na lista de autocompletar em vez de digitar o nome.",
    'de': "⚠️ Es gibt **{count}** offene Knoten namens `{name}` in dieser Belagerung (kann bei Gegnern ohne Mod vorkommen). Bitte wähle den richtigen aus der Autovervollständigungsliste, statt den Namen einzutippen.",
}
TRANSLATIONS['siege.score.no_node_found'] = {
    'en': "⚠️ No open node found for `{name}`. Check spelling, or pick from the autocomplete list.",
    'es': "⚠️ No se encontró un nodo abierto para `{name}`. Revisa la ortografía o elige de la lista de autocompletado.",
    'fr': "⚠️ Aucun nœud ouvert trouvé pour `{name}`. Vérifiez l'orthographe ou choisissez dans la liste d'autocomplétion.",
    'pt': "⚠️ Nenhum nó aberto encontrado para `{name}`. Verifique a ortografia ou escolha na lista de autocompletar.",
    'de': "⚠️ Kein offener Knoten für `{name}` gefunden. Prüfe die Schreibweise oder wähle aus der Autovervollständigungsliste.",
}
TRANSLATIONS['siege.score.modal_title'] = {'en': "Log Siege Score", 'es': "Registrar Puntuación de Asedio", 'fr': "Enregistrer un Score de Siège", 'pt': "Registrar Pontuação de Cerco", 'de': "Belagerungspunkte Erfassen"}
TRANSLATIONS['siege.score.label_drives'] = {'en': "Drives Played", 'es': "Drives Jugados", 'fr': "Drives Joués", 'pt': "Drives Jogados", 'de': "Gespielte Drives"}
TRANSLATIONS['siege.score.label_points'] = {'en': "Points Scored", 'es': "Puntos Anotados", 'fr': "Points Marqués", 'pt': "Pontos Marcados", 'de': "Erzielte Punkte"}
TRANSLATIONS['siege.score.err_invalid'] = {
    'en': "⚠️ Drives and points must be integers.", 'es': "⚠️ Los drives y los puntos deben ser números enteros.",
    'fr': "⚠️ Les drives et les points doivent être des entiers.", 'pt': "⚠️ Drives e pontos devem ser números inteiros.",
    'de': "⚠️ Drives und Punkte müssen ganze Zahlen sein.",
}
TRANSLATIONS['siege.score.cleared_suffix'] = {
    'en': "\n🔓 **Node cleared!**", 'es': "\n🔓 **¡Nodo despejado!**", 'fr': "\n🔓 **Nœud dégagé !**",
    'pt': "\n🔓 **Nó liberado!**", 'de': "\n🔓 **Knoten freigeschaltet!**",
}
TRANSLATIONS['siege.score.success'] = {
    'en': "✅ **{player}** logged **{points}** pts / **{drives}** drives vs **{opponent}**.{cleared}",
    'es': "✅ **{player}** registró **{points}** pts / **{drives}** drives vs **{opponent}**.{cleared}",
    'fr': "✅ **{player}** a enregistré **{points}** pts / **{drives}** drives contre **{opponent}**.{cleared}",
    'pt': "✅ **{player}** registrou **{points}** pts / **{drives}** drives vs **{opponent}**.{cleared}",
    'de': "✅ **{player}** hat **{points}** Pkt / **{drives}** Drives gegen **{opponent}** erfasst.{cleared}",
}

# --- /siegestatus ---

TRANSLATIONS['siege.status.title'] = {
    'en': "⚔️ Siege Status — {league} vs {opp_league}", 'es': "⚔️ Estado del Asedio — {league} vs {opp_league}",
    'fr': "⚔️ Statut du Siège — {league} contre {opp_league}", 'pt': "⚔️ Status do Cerco — {league} vs {opp_league}",
    'de': "⚔️ Belagerungsstatus — {league} vs. {opp_league}",
}
TRANSLATIONS['siege.status.matchup_info_label'] = {'en': "Matchup Info", 'es': "Información del Enfrentamiento", 'fr': "Infos du Match", 'pt': "Informações do Confronto", 'de': "Matchup-Info"}
TRANSLATIONS['siege.status.matchup_info_value'] = {
    'en': "Our Rank: **{our_rank}**  |  Opp Rank: **{opp_rank}**  |  Division: **{division}**",
    'es': "Nuestro Rango: **{our_rank}**  |  Rango del Oponente: **{opp_rank}**  |  División: **{division}**",
    'fr': "Notre Rang : **{our_rank}**  |  Rang Adverse : **{opp_rank}**  |  Division : **{division}**",
    'pt': "Nosso Rank: **{our_rank}**  |  Rank do Oponente: **{opp_rank}**  |  Divisão: **{division}**",
    'de': "Unser Rang: **{our_rank}**  |  Gegnerischer Rang: **{opp_rank}**  |  Division: **{division}**",
}
TRANSLATIONS['siege.status.open_nodes_label'] = {
    'en': "🔓 Open Nodes ({count})", 'es': "🔓 Nodos Abiertos ({count})", 'fr': "🔓 Nœuds Ouverts ({count})",
    'pt': "🔓 Nós Abertos ({count})", 'de': "🔓 Offene Knoten ({count})",
}
TRANSLATIONS['siege.status.open_node_line'] = {
    'en': "{star}**{name}**{ovr} — {mod}\n\u3000{so_far}/{required} pts to clear · reward {reward}",
    'es': "{star}**{name}**{ovr} — {mod}\n\u3000{so_far}/{required} pts para despejar · recompensa {reward}",
    'fr': "{star}**{name}**{ovr} — {mod}\n\u3000{so_far}/{required} pts pour dégager · récompense {reward}",
    'pt': "{star}**{name}**{ovr} — {mod}\n\u3000{so_far}/{required} pts para liberar · recompensa {reward}",
    'de': "{star}**{name}**{ovr} — {mod}\n\u3000{so_far}/{required} Pkt zum Freischalten · Belohnung {reward}",
}
TRANSLATIONS['siege.status.no_nodes_yet'] = {
    'en': "None reported yet — use `/node`.", 'es': "Ninguno reportado aún — usa `/node`.",
    'fr': "Aucun signalé pour l'instant — utilisez `/node`.", 'pt': "Nenhum reportado ainda — use `/node`.",
    'de': "Noch keiner gemeldet — verwende `/node`.",
}
TRANSLATIONS['siege.status.cleared_nodes_label'] = {
    'en': "🔒 Cleared Nodes ({count})", 'es': "🔒 Nodos Despejados ({count})", 'fr': "🔒 Nœuds Dégagés ({count})",
    'pt': "🔒 Nós Liberados ({count})", 'de': "🔒 Freigeschaltete Knoten ({count})",
}
TRANSLATIONS['siege.status.cleared_totals_value'] = {
    'en': "Required total: **{req}**  |  Reward total: **{reward}**",
    'es': "Total requerido: **{req}**  |  Total de recompensa: **{reward}**",
    'fr': "Total requis : **{req}**  |  Total de récompense : **{reward}**",
    'pt': "Total necessário: **{req}**  |  Total de recompensa: **{reward}**",
    'de': "Gesamt benötigt: **{req}**  |  Gesamtbelohnung: **{reward}**",
}
TRANSLATIONS['siege.status.none_cleared'] = {
    'en': "None cleared yet.", 'es': "Ninguno despejado aún.", 'fr': "Aucun dégagé pour l'instant.",
    'pt': "Nenhum liberado ainda.", 'de': "Noch keiner freigeschaltet.",
}
TRANSLATIONS['siege.status.player_totals_label'] = {'en': "Player Totals", 'es': "Totales por Jugador", 'fr': "Totaux par Joueur", 'pt': "Totais por Jogador", 'de': "Spielersummen"}
TRANSLATIONS['siege.status.league_ppd_label'] = {'en': "League PPD / Score", 'es': "PPD / Puntuación de Liga", 'fr': "PPD / Score de Ligue", 'pt': "PPD / Pontuação da Liga", 'de': "Liga-PPD / Punktzahl"}
TRANSLATIONS['siege.status.league_ppd_value'] = {
    'en': "PPD: **{ppd}**  (bonus **{bonus}**)\n**League Score: {score}**",
    'es': "PPD: **{ppd}**  (bono **{bonus}**)\n**Puntuación de Liga: {score}**",
    'fr': "PPD : **{ppd}**  (bonus **{bonus}**)\n**Score de Ligue : {score}**",
    'pt': "PPD: **{ppd}**  (bônus **{bonus}**)\n**Pontuação da Liga: {score}**",
    'de': "PPD: **{ppd}**  (Bonus **{bonus}**)\n**Liga-Punktzahl: {score}**",
}
TRANSLATIONS['siege.status.opp_total_points_label'] = {
    'en': "Opponent Total Points", 'es': "Puntos Totales del Oponente", 'fr': "Total des Points Adverses",
    'pt': "Pontos Totais do Oponente", 'de': "Gesamtpunkte des Gegners",
}

# --- /updatesiege, /siegefinal ---

TRANSLATIONS['siege.correction.opp_points_modal_title'] = {'en': "Set Opponent Total Points", 'es': "Establecer Puntos Totales del Oponente", 'fr': "Définir le Total de Points Adverses", 'pt': "Definir Pontos Totais do Oponente", 'de': "Gesamtpunkte des Gegners Festlegen"}
TRANSLATIONS['siege.correction.opp_points_label'] = {'en': "Opponent Total Points", 'es': "Puntos Totales del Oponente", 'fr': "Total de Points Adverses", 'pt': "Pontos Totais do Oponente", 'de': "Gesamtpunkte des Gegners"}
TRANSLATIONS['siege.correction.opp_points_err'] = {
    'en': "⚠️ Must be a number.", 'es': "⚠️ Debe ser un número.", 'fr': "⚠️ Doit être un nombre.",
    'pt': "⚠️ Deve ser um número.", 'de': "⚠️ Muss eine Zahl sein.",
}
TRANSLATIONS['siege.correction.opp_points_success'] = {
    'en': "✅ Opponent total points set to **{val}**.", 'es': "✅ Puntos totales del oponente establecidos en **{val}**.",
    'fr': "✅ Total de points adverses défini à **{val}**.", 'pt': "✅ Pontos totais do oponente definidos como **{val}**.",
    'de': "✅ Gesamtpunkte des Gegners auf **{val}** festgelegt.",
}
TRANSLATIONS['siege.correction.node_edit_title'] = {'en': "Edit Node", 'es': "Editar Nodo", 'fr': "Modifier le Nœud", 'pt': "Editar Nó", 'de': "Knoten Bearbeiten"}
TRANSLATIONS['siege.correction.node_success'] = {
    'en': "✅ **{name}** updated — now **{status}** ({req} required / {reward} reward).",
    'es': "✅ **{name}** actualizado — ahora **{status}** ({req} requeridos / {reward} recompensa).",
    'fr': "✅ **{name}** mis à jour — maintenant **{status}** ({req} requis / {reward} récompense).",
    'pt': "✅ **{name}** atualizado — agora **{status}** ({req} necessários / {reward} recompensa).",
    'de': "✅ **{name}** aktualisiert — jetzt **{status}** ({req} benötigt / {reward} Belohnung).",
}
TRANSLATIONS['siege.status_open']    = {'en': "open", 'es': "abierto", 'fr': "ouvert", 'pt': "aberto", 'de': "offen"}
TRANSLATIONS['siege.status_cleared'] = {'en': "cleared", 'es': "despejado", 'fr': "dégagé", 'pt': "liberado", 'de': "freigeschaltet"}
TRANSLATIONS['siege.correction.score_edit_title'] = {'en': "Edit Score Entry", 'es': "Editar Registro de Puntuación", 'fr': "Modifier l'Entrée de Score", 'pt': "Editar Registro de Pontuação", 'de': "Punkteeintrag Bearbeiten"}
TRANSLATIONS['siege.correction.score_success'] = {
    'en': "✅ Score entry updated to **{points}** pts / **{drives}** drives.",
    'es': "✅ Registro de puntuación actualizado a **{points}** pts / **{drives}** drives.",
    'fr': "✅ Entrée de score mise à jour à **{points}** pts / **{drives}** drives.",
    'pt': "✅ Registro de pontuação atualizado para **{points}** pts / **{drives}** drives.",
    'de': "✅ Punkteeintrag aktualisiert auf **{points}** Pkt / **{drives}** Drives.",
}
TRANSLATIONS['siege.correction.node_gone'] = {
    'en': "⚠️ That node no longer exists.", 'es': "⚠️ Ese nodo ya no existe.", 'fr': "⚠️ Ce nœud n'existe plus.",
    'pt': "⚠️ Esse nó não existe mais.", 'de': "⚠️ Dieser Knoten existiert nicht mehr.",
}
TRANSLATIONS['siege.correction.score_gone'] = {
    'en': "⚠️ That score entry no longer exists.", 'es': "⚠️ Ese registro de puntuación ya no existe.",
    'fr': "⚠️ Cette entrée de score n'existe plus.", 'pt': "⚠️ Esse registro de pontuação não existe mais.",
    'de': "⚠️ Dieser Punkteeintrag existiert nicht mehr.",
}
TRANSLATIONS['siege.correction.btn_set_opp_points'] = {'en': "💰 Set Opponent Total Points", 'es': "💰 Establecer Puntos Totales del Oponente", 'fr': "💰 Définir les Points Adverses", 'pt': "💰 Definir Pontos Totais do Oponente", 'de': "💰 Gegnerpunkte Festlegen"}
TRANSLATIONS['siege.correction.select_node_placeholder'] = {'en': "✏️ Edit a node's info...", 'es': "✏️ Editar información de un nodo...", 'fr': "✏️ Modifier les infos d'un nœud...", 'pt': "✏️ Editar informações de um nó...", 'de': "✏️ Knoteninfo bearbeiten..."}
TRANSLATIONS['siege.correction.select_score_placeholder'] = {'en': "✏️ Edit a score entry...", 'es': "✏️ Editar un registro de puntuación...", 'fr': "✏️ Modifier une entrée de score...", 'pt': "✏️ Editar um registro de pontuação...", 'de': "✏️ Punkteeintrag bearbeiten..."}
TRANSLATIONS['siege.correction.btn_finalize'] = {'en': "🏁 Finalize Match", 'es': "🏁 Finalizar Combate", 'fr': "🏁 Clôturer le Siège", 'pt': "🏁 Finalizar Cerco", 'de': "🏁 Belagerung Abschließen"}
TRANSLATIONS['siege.correction.finalized_title'] = {
    'en': "🏁 Siege Finalized — {league} vs {opp_league}", 'es': "🏁 Asedio Finalizado — {league} vs {opp_league}",
    'fr': "🏁 Siège Clôturé — {league} contre {opp_league}", 'pt': "🏁 Cerco Finalizado — {league} vs {opp_league}",
    'de': "🏁 Belagerung Abgeschlossen — {league} vs. {opp_league}",
}
TRANSLATIONS['siege.correction.finalized_desc'] = {
    'en': "**Final League Score: {score}**\nOpponent Total Points: **{opp_pts}**",
    'es': "**Puntuación Final de Liga: {score}**\nPuntos Totales del Oponente: **{opp_pts}**",
    'fr': "**Score de Ligue Final : {score}**\nTotal de Points Adverses : **{opp_pts}**",
    'pt': "**Pontuação Final da Liga: {score}**\nPontos Totais do Oponente: **{opp_pts}**",
    'de': "**Finale Liga-Punktzahl: {score}**\nGesamtpunkte des Gegners: **{opp_pts}**",
}
TRANSLATIONS['siege.correction.finalized_content'] = {
    'en': "Match finalized.", 'es': "Combate finalizado.", 'fr': "Siège clôturé.", 'pt': "Cerco finalizado.", 'de': "Belagerung abgeschlossen.",
}
TRANSLATIONS['siege.correction.cleared_nodes_field'] = {'en': "Cleared Nodes", 'es': "Nodos Despejados", 'fr': "Nœuds Dégagés", 'pt': "Nós Liberados", 'de': "Freigeschaltete Knoten"}
TRANSLATIONS['siege.correction.ppd_field'] = {'en': "PPD", 'es': "PPD", 'fr': "PPD", 'pt': "PPD", 'de': "PPD"}

# --- /siegesplits ---

TRANSLATIONS['siege.splits.no_scores'] = {
    'en': "No siege scores logged yet for **{player}**.", 'es': "Aún no hay puntuaciones de asedio registradas para **{player}**.",
    'fr': "Aucun score de siège enregistré pour **{player}**.", 'pt': "Nenhuma pontuação de cerco registrada para **{player}** ainda.",
    'de': "Für **{player}** sind noch keine Belagerungspunkte erfasst.",
}
TRANSLATIONS['siege.splits.title'] = {
    'en': "⚔️ Siege Splits — {player}", 'es': "⚔️ Estadísticas de Asedio — {player}",
    'fr': "⚔️ Répartition de Siège — {player}", 'pt': "⚔️ Estatísticas de Cerco — {player}",
    'de': "⚔️ Belagerungsstatistik — {player}",
}
TRANSLATIONS['siege.splits.by_mod_label'] = {'en': "By Mod", 'es': "Por Mod", 'fr': "Par Mod", 'pt': "Por Mod", 'de': "Nach Mod"}
TRANSLATIONS['siege.splits.mod_line'] = {
    'en': "**{mod}**: {points} pts / {drives} drives ({ppd} PPD)",
    'es': "**{mod}**: {points} pts / {drives} drives ({ppd} PPD)",
    'fr': "**{mod}** : {points} pts / {drives} drives ({ppd} PPD)",
    'pt': "**{mod}**: {points} pts / {drives} drives ({ppd} PPD)",
    'de': "**{mod}**: {points} Pkt / {drives} Drives ({ppd} PPD)",
}
TRANSLATIONS['siege.splits.overall_label'] = {'en': "Overall", 'es': "General", 'fr': "Global", 'pt': "Geral", 'de': "Gesamt"}
TRANSLATIONS['siege.splits.overall_value'] = {
    'en': "{points} pts / {drives} drives ({ppd} PPD)", 'es': "{points} pts / {drives} drives ({ppd} PPD)",
    'fr': "{points} pts / {drives} drives ({ppd} PPD)", 'pt': "{points} pts / {drives} drives ({ppd} PPD)",
    'de': "{points} Pkt / {drives} Drives ({ppd} PPD)",
}

# --- /siegehistory ---

TRANSLATIONS['siege.history.no_matches'] = {
    'en': "No completed siege matches yet for **{league}**.", 'es': "Aún no hay combates de asedio completados para **{league}**.",
    'fr': "Aucun siège terminé pour **{league}**.", 'pt': "Nenhum cerco concluído ainda para **{league}**.",
    'de': "Für **{league}** sind noch keine Belagerungen abgeschlossen.",
}
TRANSLATIONS['siege.history.title'] = {
    'en': "⚔️ Siege History — {league}", 'es': "⚔️ Historial de Asedio — {league}",
    'fr': "⚔️ Historique des Sièges — {league}", 'pt': "⚔️ Histórico de Cercos — {league}",
    'de': "⚔️ Belagerungsverlauf — {league}",
}
TRANSLATIONS['siege.history.line'] = {
    'en': "**vs {opp_league}** ({date})\n\u3000Score: **{score}**  |  Opp Pts: **{opp_pts}**",
    'es': "**vs {opp_league}** ({date})\n\u3000Puntuación: **{score}**  |  Pts del Oponente: **{opp_pts}**",
    'fr': "**contre {opp_league}** ({date})\n\u3000Score : **{score}**  |  Pts Adverses : **{opp_pts}**",
    'pt': "**vs {opp_league}** ({date})\n\u3000Pontuação: **{score}**  |  Pts do Oponente: **{opp_pts}**",
    'de': "**vs. {opp_league}** ({date})\n\u3000Punktzahl: **{score}**  |  Gegnerpunkte: **{opp_pts}**",
}

# =============================================================================
# TIER 3 — /matchup, /show_ladder, /factors, and the /ladder flow
# =============================================================================

# --- /matchup ---

TRANSLATIONS['matchup.err.no_active_players'] = {
    'en': "No active players found for **{league}**.", 'es': "No se encontraron jugadores activos para **{league}**.",
    'fr': "Aucun joueur actif trouvé pour **{league}**.", 'pt': "Nenhum jogador ativo encontrado para **{league}**.",
    'de': "Keine aktiven Spieler für **{league}** gefunden.",
}
TRANSLATIONS['matchup.scores_modal.title'] = {
    'en': "Update Scores ({page}/{total})", 'es': "Actualizar Puntuaciones ({page}/{total})",
    'fr': "Mettre à Jour les Scores ({page}/{total})", 'pt': "Atualizar Pontuações ({page}/{total})",
    'de': "Punktestände Aktualisieren ({page}/{total})",
}
TRANSLATIONS['matchup.scores_modal.placeholder'] = {
    'en': "score, M=missed, E=excused, blank=remove",
    'es': "puntuación, M=fallado, E=justificado, vacío=quitar",
    'fr': "score, M=manqué, E=excusé, vide=retirer",
    'pt': "pontuação, M=perdido, E=justificado, vazio=remover",
    'de': "Punktestand, M=verpasst, E=entschuldigt, leer=entfernen",
}
TRANSLATIONS['matchup.info_modal.title'] = {'en': "Matchup Info", 'es': "Información del Enfrentamiento", 'fr': "Infos du Match", 'pt': "Informações do Confronto", 'de': "Matchup-Info"}
TRANSLATIONS['matchup.info_modal.label_opp'] = {'en': "Opponent Name", 'es': "Nombre del Oponente", 'fr': "Nom de l'Adversaire", 'pt': "Nome do Oponente", 'de': "Gegnername"}
TRANSLATIONS['matchup.info_modal.label_division'] = {'en': "Division (E1/E2/E3/HOF)", 'es': "División (E1/E2/E3/HOF)", 'fr': "Division (E1/E2/E3/HOF)", 'pt': "Divisão (E1/E2/E3/HOF)", 'de': "Division (E1/E2/E3/HOF)"}
TRANSLATIONS['matchup.info_modal.label_our_rank'] = {'en': "Our Rank", 'es': "Nuestro Rango", 'fr': "Notre Rang", 'pt': "Nosso Rank", 'de': "Unser Rang"}
TRANSLATIONS['matchup.info_modal.label_opp_rank'] = {'en': "Opponent Rank", 'es': "Rango del Oponente", 'fr': "Rang de l'Adversaire", 'pt': "Rank do Oponente", 'de': "Gegnerischer Rang"}
TRANSLATIONS['matchup.btn.edit_info'] = {'en': "✏️ Edit Matchup Info", 'es': "✏️ Editar Información del Enfrentamiento", 'fr': "✏️ Modifier les Infos du Match", 'pt': "✏️ Editar Informações do Confronto", 'de': "✏️ Matchup-Info Bearbeiten"}
TRANSLATIONS['matchup.btn.scores_page'] = {
    'en': "📝 Scores {page}/{total} ({filled}/{count})", 'es': "📝 Puntuaciones {page}/{total} ({filled}/{count})",
    'fr': "📝 Scores {page}/{total} ({filled}/{count})", 'pt': "📝 Pontuações {page}/{total} ({filled}/{count})",
    'de': "📝 Punktestände {page}/{total} ({filled}/{count})",
}
TRANSLATIONS['matchup.btn.set_outcome'] = {'en': "🏆 Set Outcome", 'es': "🏆 Establecer Resultado", 'fr': "🏆 Définir le Résultat", 'pt': "🏆 Definir Resultado", 'de': "🏆 Ergebnis Festlegen"}
TRANSLATIONS['matchup.outcome_label'] = {
    'en': "🏆 {outcome}  {our}–{opp}  ({drives} opp drives)", 'es': "🏆 {outcome}  {our}–{opp}  ({drives} drives del oponente)",
    'fr': "🏆 {outcome}  {our}–{opp}  ({drives} drives adverses)", 'pt': "🏆 {outcome}  {our}–{opp}  ({drives} drives do oponente)",
    'de': "🏆 {outcome}  {our}–{opp}  ({drives} gegnerische Drives)",
}
TRANSLATIONS['matchup.btn.save'] = {
    'en': "💾 Save All ({filled}/{total} scored)", 'es': "💾 Guardar Todo ({filled}/{total} anotados)",
    'fr': "💾 Tout Sauvegarder ({filled}/{total} marqués)", 'pt': "💾 Salvar Tudo ({filled}/{total} pontuados)",
    'de': "💾 Alles Speichern ({filled}/{total} gewertet)",
}
TRANSLATIONS['matchup.embed.title'] = {
    'en': "📋 Update Matchup — {league} {date}", 'es': "📋 Actualizar Enfrentamiento — {league} {date}",
    'fr': "📋 Mettre à Jour le Match — {league} {date}", 'pt': "📋 Atualizar Confronto — {league} {date}",
    'de': "📋 Matchup Aktualisieren — {league} {date}",
}
TRANSLATIONS['matchup.field.matchup'] = {'en': "Matchup", 'es': "Enfrentamiento", 'fr': "Match", 'pt': "Confronto", 'de': "Matchup"}
TRANSLATIONS['matchup.field.matchup_value'] = {
    'en': "vs **{opp}** | Division: **{division}**\nOur rank: **{our_rank}** · Opp rank: **{opp_rank}**",
    'es': "vs **{opp}** | División: **{division}**\nNuestro rango: **{our_rank}** · Rango del oponente: **{opp_rank}**",
    'fr': "contre **{opp}** | Division : **{division}**\nNotre rang : **{our_rank}** · Rang adverse : **{opp_rank}**",
    'pt': "vs **{opp}** | Divisão: **{division}**\nNosso rank: **{our_rank}** · Rank do oponente: **{opp_rank}**",
    'de': "vs. **{opp}** | Division: **{division}**\nUnser Rang: **{our_rank}** · Gegnerischer Rang: **{opp_rank}**",
}
TRANSLATIONS['matchup.field.outcome'] = {'en': "Outcome", 'es': "Resultado", 'fr': "Résultat", 'pt': "Resultado", 'de': "Ergebnis"}
TRANSLATIONS['matchup.field.outcome_value'] = {
    'en': "**{outcome}**  {our_s} ({our_drives} drives) — {opp_s} ({opp_drives} drives)",
    'es': "**{outcome}**  {our_s} ({our_drives} drives) — {opp_s} ({opp_drives} drives)",
    'fr': "**{outcome}**  {our_s} ({our_drives} drives) — {opp_s} ({opp_drives} drives)",
    'pt': "**{outcome}**  {our_s} ({our_drives} drives) — {opp_s} ({opp_drives} drives)",
    'de': "**{outcome}**  {our_s} ({our_drives} Drives) — {opp_s} ({opp_drives} Drives)",
}
TRANSLATIONS['matchup.field.scores'] = {'en': "Scores", 'es': "Puntuaciones", 'fr': "Scores", 'pt': "Pontuações", 'de': "Punktestände"}
TRANSLATIONS['matchup.footer'] = {
    'en': "✅ = pending save  📌 = existing  ·  M=missed drives  E=excused",
    'es': "✅ = pendiente de guardar  📌 = existente  ·  M=drives fallados  E=justificado",
    'fr': "✅ = en attente d'enregistrement  📌 = existant  ·  M=drive manqué  E=excusé",
    'pt': "✅ = pendente de salvar  📌 = existente  ·  M=drives perdidos  E=justificado",
    'de': "✅ = ausstehend  📌 = vorhanden  ·  M=verpasste Drives  E=entschuldigt",
}
TRANSLATIONS['matchup.outcome_modal.title'] = {'en': "Set Outcome", 'es': "Establecer Resultado", 'fr': "Définir le Résultat", 'pt': "Definir Resultado", 'de': "Ergebnis Festlegen"}
TRANSLATIONS['matchup.outcome_modal.label_our_score'] = {'en': "Our Score", 'es': "Nuestra Puntuación", 'fr': "Notre Score", 'pt': "Nossa Pontuação", 'de': "Unser Punktestand"}
TRANSLATIONS['matchup.outcome_modal.label_our_drives'] = {'en': "Our Drives", 'es': "Nuestros Drives", 'fr': "Nos Drives", 'pt': "Nossos Drives", 'de': "Unsere Drives"}
TRANSLATIONS['matchup.outcome_modal.label_opp_score'] = {'en': "Opponent Score", 'es': "Puntuación del Oponente", 'fr': "Score Adverse", 'pt': "Pontuação do Oponente", 'de': "Gegnerischer Punktestand"}
TRANSLATIONS['matchup.outcome_modal.label_opp_drives'] = {'en': "Opponent Drives", 'es': "Drives del Oponente", 'fr': "Drives Adverses", 'pt': "Drives do Oponente", 'de': "Gegnerische Drives"}
TRANSLATIONS['matchup.outcome_modal.label_result'] = {'en': "Result (WIN/LOSS/TIE)", 'es': "Resultado (WIN/LOSS/TIE)", 'fr': "Résultat (WIN/LOSS/TIE)", 'pt': "Resultado (WIN/LOSS/TIE)", 'de': "Ergebnis (WIN/LOSS/TIE)"}
TRANSLATIONS['matchup.saved.title'] = {'en': "✅ Matchup Updated", 'es': "✅ Enfrentamiento Actualizado", 'fr': "✅ Match Mis à Jour", 'pt': "✅ Confronto Atualizado", 'de': "✅ Matchup Aktualisiert"}
TRANSLATIONS['matchup.saved.field_matchup'] = {'en': "Matchup", 'es': "Enfrentamiento", 'fr': "Match", 'pt': "Confronto", 'de': "Matchup"}
TRANSLATIONS['matchup.saved.matchup_value'] = {
    'en': "vs {opp} saved", 'es': "vs {opp} guardado", 'fr': "contre {opp} enregistré",
    'pt': "vs {opp} salvo", 'de': "vs. {opp} gespeichert",
}
TRANSLATIONS['matchup.saved.field_scores'] = {'en': "Scores", 'es': "Puntuaciones", 'fr': "Scores", 'pt': "Pontuações", 'de': "Punktestände"}
TRANSLATIONS['matchup.saved.scores_value'] = {
    'en': "{count} player scores saved", 'es': "{count} puntuaciones de jugadores guardadas",
    'fr': "{count} scores de joueurs enregistrés", 'pt': "{count} pontuações de jogadores salvas",
    'de': "{count} Spielerwertungen gespeichert",
}

# --- /show_ladder ---

TRANSLATIONS['ladder_cmd.err.no_data'] = {
    'en': "⚠️ No ladder data found for **{league}**. Use `/ladder` to build one.",
    'es': "⚠️ No se encontraron datos de escalafón para **{league}**. Usa `/ladder` para armar uno.",
    'fr': "⚠️ Aucune donnée de classement trouvée pour **{league}**. Utilisez `/ladder` pour en construire un.",
    'pt': "⚠️ Nenhum dado de ranking encontrado para **{league}**. Use `/ladder` para montar um.",
    'de': "⚠️ Keine Ranglisten-Daten für **{league}** gefunden. Verwende `/ladder`, um eine zu erstellen.",
}

# --- /factors ---

TRANSLATIONS['factors.scope_global'] = {'en': "**Global**", 'es': "**Global**", 'fr': "**Global**", 'pt': "**Global**", 'de': "**Global**"}
TRANSLATIONS['factors.title'] = {
    'en': "⚖️ Weight Factors — {scope}", 'es': "⚖️ Factores de Ponderación — {scope}",
    'fr': "⚖️ Facteurs de Pondération — {scope}", 'pt': "⚖️ Fatores de Ponderação — {scope}",
    'de': "⚖️ Gewichtungsfaktoren — {scope}",
}
TRANSLATIONS['factors.no_factors'] = {
    'en': "*No factors defined.*", 'es': "*No hay factores definidos.*", 'fr': "*Aucun facteur défini.*",
    'pt': "*Nenhum fator definido.*", 'de': "*Keine Faktoren definiert.*",
}
TRANSLATIONS['factors.col_factor'] = {'en': "Factor", 'es': "Factor", 'fr': "Facteur", 'pt': "Fator", 'de': "Faktor"}
TRANSLATIONS['factors.col_weight'] = {'en': "Weight", 'es': "Peso", 'fr': "Poids", 'pt': "Peso", 'de': "Gewicht"}
TRANSLATIONS['factors.col_total'] = {'en': "Total", 'es': "Total", 'fr': "Total", 'pt': "Total", 'de': "Gesamt"}
TRANSLATIONS['factors.field_pwr'] = {'en': "Power Rank Factors", 'es': "Factores de Rango de Poder", 'fr': "Facteurs de Rang de Puissance", 'pt': "Fatores de Rank de Poder", 'de': "Power-Rang-Faktoren"}
TRANSLATIONS['factors.field_ladder'] = {'en': "Ladder Factors", 'es': "Factores de Escalafón", 'fr': "Facteurs de Classement", 'pt': "Fatores de Ranking", 'de': "Ranglisten-Faktoren"}
TRANSLATIONS['factors.footer_team'] = {
    'en': "Showing team-specific overrides merged with global values.",
    'es': "Mostrando anulaciones específicas del equipo combinadas con valores globales.",
    'fr': "Affichage des remplacements spécifiques à l'équipe fusionnés avec les valeurs globales.",
    'pt': "Mostrando substituições específicas da equipe combinadas com valores globais.",
    'de': "Zeigt teamspezifische Überschreibungen kombiniert mit globalen Werten.",
}
TRANSLATIONS['factors.footer_global'] = {
    'en': "These are the global defaults. Use /weights to edit them.",
    'es': "Estos son los valores globales predeterminados. Usa /weights para editarlos.",
    'fr': "Ce sont les valeurs par défaut globales. Utilisez /weights pour les modifier.",
    'pt': "Estes são os padrões globais. Use /weights para editá-los.",
    'de': "Dies sind die globalen Standardwerte. Verwende /weights, um sie zu bearbeiten.",
}

# --- /ladder flow: general ---

TRANSLATIONS['ladder.no_active_players'] = {
    'en': "No active players found for `{team}`.", 'es': "No se encontraron jugadores activos para `{team}`.",
    'fr': "Aucun joueur actif trouvé pour `{team}`.", 'pt': "Nenhum jogador ativo encontrado para `{team}`.",
    'de': "Keine aktiven Spieler für `{team}` gefunden.",
}

# --- Step 1 ---

TRANSLATIONS['ladder.step1.title'] = {
    'en': "Step 1 — Select Players  ({count}/{total})", 'es': "Paso 1 — Seleccionar Jugadores  ({count}/{total})",
    'fr': "Étape 1 — Sélectionner les Joueurs  ({count}/{total})", 'pt': "Passo 1 — Selecionar Jogadores  ({count}/{total})",
    'de': "Schritt 1 — Spieler Auswählen  ({count}/{total})",
}
TRANSLATIONS['ladder.step1.desc'] = {
    'en': "**{league}**  |  Page {page}/{total_pages}\nSelected = Active (A), unselected = Rested (R). Select exactly **{total}** to continue.",
    'es': "**{league}**  |  Página {page}/{total_pages}\nSeleccionado = Activo (A), no seleccionado = Descanso (R). Selecciona exactamente **{total}** para continuar.",
    'fr': "**{league}**  |  Page {page}/{total_pages}\nSélectionné = Actif (A), non sélectionné = Repos (R). Sélectionnez exactement **{total}** pour continuer.",
    'pt': "**{league}**  |  Página {page}/{total_pages}\nSelecionado = Ativo (A), não selecionado = Descanso (R). Selecione exatamente **{total}** para continuar.",
    'de': "**{league}**  |  Seite {page}/{total_pages}\nAusgewählt = Aktiv (A), nicht ausgewählt = Pausiert (R). Wähle genau **{total}**, um fortzufahren.",
}
TRANSLATIONS['ladder.step1.selected_label'] = {'en': "Selected", 'es': "Seleccionados", 'fr': "Sélectionnés", 'pt': "Selecionados", 'de': "Ausgewählt"}
TRANSLATIONS['ladder.step1.next_btn'] = {
    'en': "Next ({count}/{total})", 'es': "Siguiente ({count}/{total})", 'fr': "Suivant ({count}/{total})",
    'pt': "Próximo ({count}/{total})", 'de': "Weiter ({count}/{total})",
}
TRANSLATIONS['ladder.step1.already_selected'] = {
    'en': "Already have {total} selected. Deselect one first.",
    'es': "Ya tienes {total} seleccionados. Deselecciona uno primero.",
    'fr': "Vous avez déjà {total} sélectionnés. Désélectionnez-en un d'abord.",
    'pt': "Já há {total} selecionados. Remova um primeiro.",
    'de': "Bereits {total} ausgewählt. Zuerst einen abwählen.",
}

# --- Step 2 ---

TRANSLATIONS['ladder.opponent_csv.modal_title'] = {
    'en': "Enter All 16 Opponents", 'es': "Ingresa los 16 Oponentes", 'fr': "Saisir les 16 Adversaires",
    'pt': "Insira os 16 Oponentes", 'de': "Alle 16 Gegner Eingeben",
}
TRANSLATIONS['ladder.opponent_csv.label'] = {
    'en': "Name, Total OVR, DEF OVR  (one per line)", 'es': "Nombre, OVR Total, DEF OVR  (uno por línea)",
    'fr': "Nom, OVR Total, DEF OVR  (un par ligne)", 'pt': "Nome, OVR Total, DEF OVR  (um por linha)",
    'de': "Name, Gesamt-OVR, DEF OVR  (einer pro Zeile)",
}
TRANSLATIONS['ladder.step2.enter_btn'] = {
    'en': "Enter Opponents  ({filled}/{total} filled)", 'es': "Ingresar Oponentes  ({filled}/{total} completados)",
    'fr': "Saisir les Adversaires  ({filled}/{total} remplis)", 'pt': "Inserir Oponentes  ({filled}/{total} preenchidos)",
    'de': "Gegner Eingeben  ({filled}/{total} ausgefüllt)",
}
TRANSLATIONS['ladder.step2.done_btn'] = {
    'en': "Done — Sort & Arrange", 'es': "Listo — Ordenar y Organizar", 'fr': "Terminé — Trier et Organiser",
    'pt': "Concluído — Ordenar e Organizar", 'de': "Fertig — Sortieren & Anordnen",
}
TRANSLATIONS['ladder.step2.title'] = {
    'en': "Step 2 — Enter Opponents  ({filled}/{total} filled)", 'es': "Paso 2 — Ingresar Oponentes  ({filled}/{total} completados)",
    'fr': "Étape 2 — Saisir les Adversaires  ({filled}/{total} remplis)", 'pt': "Passo 2 — Inserir Oponentes  ({filled}/{total} preenchidos)",
    'de': "Schritt 2 — Gegner Eingeben  ({filled}/{total} ausgefüllt)",
}
TRANSLATIONS['ladder.step2.desc'] = {
    'en': "**{league}**\nEnter each opponent as: `Name, Total OVR, DEF OVR` (one per line).\nExample: `WolfpackMafia, 6481, 219`",
    'es': "**{league}**\nIngresa cada oponente como: `Nombre, OVR Total, DEF OVR` (uno por línea).\nEjemplo: `WolfpackMafia, 6481, 219`",
    'fr': "**{league}**\nSaisissez chaque adversaire comme : `Nom, OVR Total, DEF OVR` (un par ligne).\nExemple : `WolfpackMafia, 6481, 219`",
    'pt': "**{league}**\nInsira cada oponente como: `Nome, OVR Total, DEF OVR` (um por linha).\nExemplo: `WolfpackMafia, 6481, 219`",
    'de': "**{league}**\nGib jeden Gegner ein als: `Name, Gesamt-OVR, DEF OVR` (einer pro Zeile).\nBeispiel: `WolfpackMafia, 6481, 219`",
}
TRANSLATIONS['ladder.step2.slots1_8'] = {'en': "Slots 1-8", 'es': "Espacios 1-8", 'fr': "Emplacements 1-8", 'pt': "Vagas 1-8", 'de': "Plätze 1-8"}
TRANSLATIONS['ladder.step2.slots9_16'] = {'en': "Slots 9-16", 'es': "Espacios 9-16", 'fr': "Emplacements 9-16", 'pt': "Vagas 9-16", 'de': "Plätze 9-16"}
TRANSLATIONS['ladder.step3.title'] = {'en': "Step 3 — Sort Criteria", 'es': "Paso 3 — Criterio de Orden", 'fr': "Étape 3 — Critère de Tri", 'pt': "Passo 3 — Critério de Ordenação", 'de': "Schritt 3 — Sortierkriterium"}
TRANSLATIONS['ladder.step3.desc'] = {
    'en': "How should **our players** be pre-sorted?\n\nOpponents auto-sort by **DEF OVR (highest first)**.\nYou can manually reorder both lists in the next step.",
    'es': "¿Cómo deben preordenarse **nuestros jugadores**?\n\nLos oponentes se ordenan automáticamente por **DEF OVR (mayor primero)**.\nPuedes reordenar manualmente ambas listas en el siguiente paso.",
    'fr': "Comment **nos joueurs** doivent-ils être pré-triés ?\n\nLes adversaires se trient automatiquement par **DEF OVR (le plus élevé d'abord)**.\nVous pourrez réorganiser manuellement les deux listes à l'étape suivante.",
    'pt': "Como **nossos jogadores** devem ser pré-ordenados?\n\nOs oponentes são ordenados automaticamente por **DEF OVR (maior primeiro)**.\nVocê pode reordenar manualmente ambas as listas na próxima etapa.",
    'de': "Wie sollen **unsere Spieler** vorsortiert werden?\n\nGegner werden automatisch nach **DEF OVR (höchster zuerst)** sortiert.\nDu kannst beide Listen im nächsten Schritt manuell neu anordnen.",
}

# --- Step 3 (sort picker) ---

TRANSLATIONS['ladder.step3.placeholder'] = {
    'en': "Sort our players by... (opponents auto-sort by DEF OVR)",
    'es': "Ordenar a nuestros jugadores por... (los oponentes se ordenan automáticamente por DEF OVR)",
    'fr': "Trier nos joueurs par... (les adversaires se trient automatiquement par DEF OVR)",
    'pt': "Ordenar nossos jogadores por... (oponentes são ordenados automaticamente por DEF OVR)",
    'de': "Unsere Spieler sortieren nach... (Gegner werden automatisch nach DEF OVR sortiert)",
}
TRANSLATIONS['ladder.sort.pwr_rank']    = {'en': "Power Rank", 'es': "Rango de Poder", 'fr': "Rang de Puissance", 'pt': "Rank de Poder", 'de': "Power-Rang"}
TRANSLATIONS['ladder.sort.yearly_avg']  = {'en': "Yearly Avg", 'es': "Promedio Anual", 'fr': "Moyenne Annuelle", 'pt': "Média Anual", 'de': "Jahresdurchschnitt"}
TRANSLATIONS['ladder.sort.7day_avg']    = {'en': "7-Day Avg", 'es': "Promedio 7 Días", 'fr': "Moyenne 7 Jours", 'pt': "Média 7 Dias", 'de': "7-Tage-Schnitt"}
TRANSLATIONS['ladder.sort.total_ovr']   = {'en': "Total OVR", 'es': "OVR Total", 'fr': "OVR Total", 'pt': "OVR Total", 'de': "Gesamt-OVR"}
TRANSLATIONS['ladder.sort.ladder_rank'] = {'en': "Ladder Rank", 'es': "Rango de Escalafón", 'fr': "Rang de Classement", 'pt': "Rank de Ranking", 'de': "Ranglisten-Rang"}

# --- Step 4 (reorder) ---

TRANSLATIONS['ladder.step4.title'] = {'en': "Step 4 — Arrange Matchups", 'es': "Paso 4 — Organizar Enfrentamientos", 'fr': "Étape 4 — Organiser les Affrontements", 'pt': "Passo 4 — Organizar Confrontos", 'de': "Schritt 4 — Matchups Anordnen"}
TRANSLATIONS['ladder.step4.desc'] = {
    'en': "**{league}**  |  Editing: **{panel}**\nRow **{row}** selected. Use cursor buttons to navigate, row buttons to reorder.",
    'es': "**{league}**  |  Editando: **{panel}**\nFila **{row}** seleccionada. Usa los botones de cursor para navegar, los botones de fila para reordenar.",
    'fr': "**{league}**  |  Édition : **{panel}**\nLigne **{row}** sélectionnée. Utilisez les boutons de curseur pour naviguer, les boutons de ligne pour réorganiser.",
    'pt': "**{league}**  |  Editando: **{panel}**\nLinha **{row}** selecionada. Use os botões de cursor para navegar, os botões de linha para reordenar.",
    'de': "**{league}**  |  Bearbeite: **{panel}**\nZeile **{row}** ausgewählt. Cursor-Schaltflächen zum Navigieren, Zeilen-Schaltflächen zum Neuanordnen.",
}
TRANSLATIONS['ladder.step4.panel_ours'] = {'en': "Our Players", 'es': "Nuestros Jugadores", 'fr': "Nos Joueurs", 'pt': "Nossos Jogadores", 'de': "Unsere Spieler"}
TRANSLATIONS['ladder.step4.panel_opps'] = {'en': "Opponents", 'es': "Oponentes", 'fr': "Adversaires", 'pt': "Oponentes", 'de': "Gegner"}
TRANSLATIONS['ladder.step4.toggle_btn'] = {
    'en': "Editing: {panel} — click to switch", 'es': "Editando: {panel} — clic para cambiar",
    'fr': "Édition : {panel} — cliquez pour changer", 'pt': "Editando: {panel} — clique para trocar",
    'de': "Bearbeite: {panel} — klicken zum Wechseln",
}
TRANSLATIONS['ladder.step4.cursor_up']   = {'en': "Move cursor up", 'es': "Mover cursor arriba", 'fr': "Déplacer le curseur vers le haut", 'pt': "Mover cursor para cima", 'de': "Cursor nach oben"}
TRANSLATIONS['ladder.step4.cursor_down'] = {'en': "Move cursor down", 'es': "Mover cursor abajo", 'fr': "Déplacer le curseur vers le bas", 'pt': "Mover cursor para baixo", 'de': "Cursor nach unten"}
TRANSLATIONS['ladder.step4.move_up']     = {'en': "Move row up", 'es': "Mover fila arriba", 'fr': "Déplacer la ligne vers le haut", 'pt': "Mover linha para cima", 'de': "Zeile nach oben"}
TRANSLATIONS['ladder.step4.move_down']   = {'en': "Move row down", 'es': "Mover fila abajo", 'fr': "Déplacer la ligne vers le bas", 'pt': "Mover linha para baixo", 'de': "Zeile nach unten"}
TRANSLATIONS['ladder.step4.sort_btn'] = {
    'en': "Sort: {label}", 'es': "Ordenar: {label}", 'fr': "Trier : {label}", 'pt': "Ordenar: {label}", 'de': "Sortieren: {label}",
}
TRANSLATIONS['ladder.step4.confirm_btn'] = {'en': "Confirm Matchups", 'es': "Confirmar Enfrentamientos", 'fr': "Confirmer les Affrontements", 'pt': "Confirmar Confrontos", 'de': "Matchups Bestätigen"}
TRANSLATIONS['ladder.step4.field_our'] = {'en': "Our Players", 'es': "Nuestros Jugadores", 'fr': "Nos Joueurs", 'pt': "Nossos Jogadores", 'de': "Unsere Spieler"}
TRANSLATIONS['ladder.step4.field_opp'] = {'en': "Opponents", 'es': "Oponentes", 'fr': "Adversaires", 'pt': "Oponentes", 'de': "Gegner"}
TRANSLATIONS['ladder.step4.finalized_content'] = {
    'en': "Ladder finalized!", 'es': "¡Escalafón finalizado!", 'fr': "Classement finalisé !",
    'pt': "Ranking finalizado!", 'de': "Rangliste abgeschlossen!",
}

# --- Final embed ---

TRANSLATIONS['ladder.final.title'] = {
    'en': "{league} Ladder Matchups — {date}", 'es': "Enfrentamientos de Escalafón de {league} — {date}",
    'fr': "Affrontements de Classement de {league} — {date}", 'pt': "Confrontos de Ranking de {league} — {date}",
    'de': "{league} Ranglisten-Matchups — {date}",
}
TRANSLATIONS['ladder.final.col_player']   = {'en': "Player", 'es': "Jugador", 'fr': "Joueur", 'pt': "Jogador", 'de': "Spieler"}
TRANSLATIONS['ladder.final.col_opponent'] = {'en': "Opponent", 'es': "Oponente", 'fr': "Adversaire", 'pt': "Oponente", 'de': "Gegner"}
TRANSLATIONS['ladder.final.field_context'] = {
    'en': "Matchup", 'es': "Enfrentamiento", 'fr': "Affrontement", 'pt': "Confronto", 'de': "Begegnung",
}
TRANSLATIONS['ladder.final.context_value'] = {
    'en': "vs {opp}{division}{rank}",
    'es': "vs {opp}{division}{rank}",
    'fr': "vs {opp}{division}{rank}",
    'pt': "vs {opp}{division}{rank}",
    'de': "vs {opp}{division}{rank}",
}
TRANSLATIONS['ladder.final.context_division'] = {
    'en': "  ({division})", 'es': "  ({division})", 'fr': "  ({division})",
    'pt': "  ({division})", 'de': "  ({division})",
}
TRANSLATIONS['ladder.final.context_rank'] = {
    'en': "  — Our Rank #{rank}", 'es': "  — Nuestro Rango #{rank}",
    'fr': "  — Notre Rang #{rank}", 'pt': "  — Nosso Rank #{rank}",
    'de': "  — Unser Rang #{rank}",
}
TRANSLATIONS['ladder.matchup_info_btn'] = {
    'en': "Edit Matchup Info", 'es': "Editar Info del Enfrentamiento",
    'fr': "Modifier les Infos", 'pt': "Editar Info do Confronto",
    'de': "Begegnung Bearbeiten",
}
TRANSLATIONS['ladder.matchup_info_modal.title'] = {
    'en': "Matchup Info", 'es': "Info del Enfrentamiento",
    'fr': "Infos de l'Affrontement", 'pt': "Info do Confronto",
    'de': "Begegnungs-Info",
}
TRANSLATIONS['ladder.matchup_info_modal.label_opp'] = {
    'en': "Opponent League Name", 'es': "Nombre de la Liga Oponente",
    'fr': "Nom de la Ligue Adverse", 'pt': "Nome da Liga Oponente",
    'de': "Name der Gegner-Liga",
}
TRANSLATIONS['ladder.matchup_info_modal.label_division'] = {
    'en': "Division (E1/E2/E3/HOF/Gold-)", 'es': "División (E1/E2/E3/HOF/Gold-)",
    'fr': "Division (E1/E2/E3/HOF/Gold-)", 'pt': "Divisão (E1/E2/E3/HOF/Gold-)",
    'de': "Division (E1/E2/E3/HOF/Gold-)",
}
TRANSLATIONS['ladder.matchup_info_modal.label_rank'] = {
    'en': "Our Rank", 'es': "Nuestro Rango", 'fr': "Notre Rang", 'pt': "Nosso Rank", 'de': "Unser Rang",
}
TRANSLATIONS['ladder.final.field_matchups'] = {'en': "Matchups", 'es': "Enfrentamientos", 'fr': "Affrontements", 'pt': "Confrontos", 'de': "Matchups"}
TRANSLATIONS['ladder.final.field_matchups_cont'] = {
    'en': "Matchups (cont.)", 'es': "Enfrentamientos (cont.)", 'fr': "Affrontements (suite)",
    'pt': "Confrontos (cont.)", 'de': "Matchups (Forts.)",
}

# =============================================================================
# TIER 4 — Admin commands (register, transfer, inactive, reactivate, league,
# weights, newday, sync, nukeguildcmds, test, gifs, tournaments) + /ovr
# (a Tier-1 gameplay command missed in the first pass, completed here)
# =============================================================================

# --- /ovr ---

TRANSLATIONS['ovr.modal.title'] = {'en': "Update Team Overall", 'es': "Actualizar Overall del Equipo", 'fr': "Mettre à Jour l'OVR de l'Équipe", 'pt': "Atualizar Overall da Equipe", 'de': "Team-Overall Aktualisieren"}
TRANSLATIONS['ovr.err.invalid'] = {
    'en': "⚠️ OVR values must be integers.", 'es': "⚠️ Los valores de OVR deben ser números enteros.",
    'fr': "⚠️ Les valeurs d'OVR doivent être des entiers.", 'pt': "⚠️ Os valores de OVR devem ser números inteiros.",
    'de': "⚠️ OVR-Werte müssen ganze Zahlen sein.",
}
TRANSLATIONS['ovr.success'] = {
    'en': "✅ Updated **{player}**'s team to {off} / {deff} / {total}.",
    'es': "✅ Equipo de **{player}** actualizado a {off} / {deff} / {total}.",
    'fr': "✅ Équipe de **{player}** mise à jour à {off} / {deff} / {total}.",
    'pt': "✅ Equipe de **{player}** atualizada para {off} / {deff} / {total}.",
    'de': "✅ Team von **{player}** aktualisiert auf {off} / {deff} / {total}.",
}

# --- /register ---

TRANSLATIONS['register.modal.title'] = {'en': "Register New Player", 'es': "Registrar Nuevo Jugador", 'fr': "Enregistrer un Nouveau Joueur", 'pt': "Registrar Novo Jogador", 'de': "Neuen Spieler Registrieren"}
TRANSLATIONS['register.modal.label_nickname'] = {'en': "Nickname (used in bot commands)", 'es': "Apodo (usado en los comandos del bot)", 'fr': "Pseudo (utilisé dans les commandes du bot)", 'pt': "Apelido (usado nos comandos do bot)", 'de': "Spitzname (in Bot-Befehlen verwendet)"}
TRANSLATIONS['register.modal.label_real_ign'] = {'en': "Real IGN (in-game name, optional)", 'es': "IGN Real (nombre en el juego, opcional)", 'fr': "IGN Réel (nom en jeu, optionnel)", 'pt': "IGN Real (nome no jogo, opcional)", 'de': "Echter IGN (Spielname, optional)"}
TRANSLATIONS['register.modal.placeholder_real_ign'] = {'en': "Leave blank if same as nickname", 'es': "Déjalo en blanco si es igual al apodo", 'fr': "Laissez vide si identique au pseudo", 'pt': "Deixe em branco se igual ao apelido", 'de': "Leer lassen, falls identisch mit Spitzname"}
TRANSLATIONS['register.err.blank_nickname'] = {
    'en': "⚠️ Nickname cannot be blank.", 'es': "⚠️ El apodo no puede estar vacío.", 'fr': "⚠️ Le pseudo ne peut pas être vide.",
    'pt': "⚠️ O apelido não pode ficar em branco.", 'de': "⚠️ Der Spitzname darf nicht leer sein.",
}
TRANSLATIONS['register.err.already_registered'] = {
    'en': "⚠️ `{nickname}` is already registered in {league}{status}. IGNs must be unique across all leagues.",
    'es': "⚠️ `{nickname}` ya está registrado en {league}{status}. Los IGN deben ser únicos en todas las ligas.",
    'fr': "⚠️ `{nickname}` est déjà enregistré dans {league}{status}. Les IGN doivent être uniques dans toutes les ligues.",
    'pt': "⚠️ `{nickname}` já está registrado em {league}{status}. Os IGNs devem ser únicos em todas as ligas.",
    'de': "⚠️ `{nickname}` ist bereits in {league}{status} registriert. IGNs müssen ligaübergreifend eindeutig sein.",
}
TRANSLATIONS['register.status_inactive_suffix'] = {'en': " (inactive)", 'es': " (inactivo)", 'fr': " (inactif)", 'pt': " (inativo)", 'de': " (inaktiv)"}
TRANSLATIONS['register.err.real_ign_taken'] = {
    'en': "⚠️ Real IGN `{real}` is already mapped to player `{ign}`.",
    'es': "⚠️ El IGN real `{real}` ya está asignado al jugador `{ign}`.",
    'fr': "⚠️ L'IGN réel `{real}` est déjà associé au joueur `{ign}`.",
    'pt': "⚠️ O IGN real `{real}` já está vinculado ao jogador `{ign}`.",
    'de': "⚠️ Der echte IGN `{real}` ist bereits dem Spieler `{ign}` zugeordnet.",
}
TRANSLATIONS['register.err.invalid_ovr'] = TRANSLATIONS['ovr.err.invalid']
TRANSLATIONS['register.success.title'] = {'en': "✅ Player Registered", 'es': "✅ Jugador Registrado", 'fr': "✅ Joueur Enregistré", 'pt': "✅ Jogador Registrado", 'de': "✅ Spieler Registriert"}
TRANSLATIONS['register.success.field_nickname'] = {'en': "Nickname", 'es': "Apodo", 'fr': "Pseudo", 'pt': "Apelido", 'de': "Spitzname"}
TRANSLATIONS['register.success.field_league'] = {'en': "League", 'es': "Liga", 'fr': "Ligue", 'pt': "Liga", 'de': "Liga"}
TRANSLATIONS['register.success.field_ovr'] = {'en': "OVR", 'es': "OVR", 'fr': "OVR", 'pt': "OVR", 'de': "OVR"}
TRANSLATIONS['register.success.field_real_ign'] = {'en': "Real IGN", 'es': "IGN Real", 'fr': "IGN Réel", 'pt': "IGN Real", 'de': "Echter IGN"}

# --- /transfer ---

TRANSLATIONS['transfer.select_placeholder'] = {
    'en': "Select destination league...", 'es': "Selecciona la liga de destino...",
    'fr': "Sélectionnez la ligue de destination...", 'pt': "Selecione a liga de destino...",
    'de': "Zielliga auswählen...",
}
TRANSLATIONS['transfer.already_there'] = {
    'en': "**{player}** is already in {league}.", 'es': "**{player}** ya está en {league}.",
    'fr': "**{player}** est déjà dans {league}.", 'pt': "**{player}** já está em {league}.",
    'de': "**{player}** ist bereits in {league}.",
}
TRANSLATIONS['transfer.success'] = {
    'en': "✅ **{player}** transferred from **{from_league}** → **{to_league}**.",
    'es': "✅ **{player}** transferido de **{from_league}** → **{to_league}**.",
    'fr': "✅ **{player}** transféré de **{from_league}** → **{to_league}**.",
    'pt': "✅ **{player}** transferido de **{from_league}** → **{to_league}**.",
    'de': "✅ **{player}** von **{from_league}** → **{to_league}** transferiert.",
}
TRANSLATIONS['transfer.prompt'] = {
    'en': "Transfer **{player}** (currently in **{league}**) to:",
    'es': "Transferir a **{player}** (actualmente en **{league}**) a:",
    'fr': "Transférer **{player}** (actuellement dans **{league}**) vers :",
    'pt': "Transferir **{player}** (atualmente em **{league}**) para:",
    'de': "**{player}** (derzeit in **{league}**) transferieren nach:",
}

# --- /inactive, /reactivate ---

TRANSLATIONS['inactive.status_active']  = {'en': "Active", 'es': "Activo", 'fr': "Actif", 'pt': "Ativo", 'de': "Aktiv"}
TRANSLATIONS['inactive.status_already'] = {'en': "Already inactive", 'es': "Ya inactivo", 'fr': "Déjà inactif", 'pt': "Já inativo", 'de': "Bereits inaktiv"}
TRANSLATIONS['inactive.confirm.title'] = {'en': "Confirm Player Left League", 'es': "Confirmar Salida del Jugador de la Liga", 'fr': "Confirmer le Départ du Joueur", 'pt': "Confirmar Saída do Jogador da Liga", 'de': "Spielerausscheiden Bestätigen"}
TRANSLATIONS['inactive.confirm.desc'] = {
    'en': "**{player}** ({league}) — {status}\nThis will hide them from active rosters.",
    'es': "**{player}** ({league}) — {status}\nEsto lo ocultará de las plantillas activas.",
    'fr': "**{player}** ({league}) — {status}\nCela le masquera des effectifs actifs.",
    'pt': "**{player}** ({league}) — {status}\nIsso o ocultará dos elencos ativos.",
    'de': "**{player}** ({league}) — {status}\nDadurch wird der Spieler aus den aktiven Kadern ausgeblendet.",
}
TRANSLATIONS['inactive.success'] = {
    'en': "⚫ **{player}** has left the league.", 'es': "⚫ **{player}** ha dejado la liga.",
    'fr': "⚫ **{player}** a quitté la ligue.", 'pt': "⚫ **{player}** deixou a liga.",
    'de': "⚫ **{player}** hat die Liga verlassen.",
}
TRANSLATIONS['reactivate.confirm.title'] = {'en': "Confirm Reactivation", 'es': "Confirmar Reactivación", 'fr': "Confirmer la Réactivation", 'pt': "Confirmar Reativação", 'de': "Reaktivierung Bestätigen"}
TRANSLATIONS['reactivate.confirm.desc'] = {
    'en': "Reactivate **{player}** in **{league}**?", 'es': "¿Reactivar a **{player}** en **{league}**?",
    'fr': "Réactiver **{player}** dans **{league}** ?", 'pt': "Reativar **{player}** em **{league}**?",
    'de': "**{player}** in **{league}** reaktivieren?",
}
TRANSLATIONS['reactivate.success'] = {
    'en': "🟢 **{player}** reactivated in **{league}**.", 'es': "🟢 **{player}** reactivado en **{league}**.",
    'fr': "🟢 **{player}** réactivé dans **{league}**.", 'pt': "🟢 **{player}** reativado em **{league}**.",
    'de': "🟢 **{player}** in **{league}** reaktiviert.",
}

# --- Shared ConfirmView ---

TRANSLATIONS['confirm.btn_confirm'] = {'en': "✅ Confirm", 'es': "✅ Confirmar", 'fr': "✅ Confirmer", 'pt': "✅ Confirmar", 'de': "✅ Bestätigen"}
TRANSLATIONS['confirm.btn_cancel']  = {'en': "❌ Cancel", 'es': "❌ Cancelar", 'fr': "❌ Annuler", 'pt': "❌ Cancelar", 'de': "❌ Abbrechen"}
TRANSLATIONS['confirm.cancelled']  = {'en': "Cancelled.", 'es': "Cancelado.", 'fr': "Annulé.", 'pt': "Cancelado.", 'de': "Abgebrochen."}

# --- /weights ---

TRANSLATIONS['weights.edit_modal.title'] = {
    'en': "Edit: {label}", 'es': "Editar: {label}", 'fr': "Modifier : {label}", 'pt': "Editar: {label}", 'de': "Bearbeiten: {label}",
}
TRANSLATIONS['weights.edit_modal.label_value'] = {'en': "New Weight Value", 'es': "Nuevo Valor de Peso", 'fr': "Nouvelle Valeur de Poids", 'pt': "Novo Valor de Peso", 'de': "Neuer Gewichtswert"}
TRANSLATIONS['weights.err.must_be_number'] = {
    'en': "⚠️ Must be a number.", 'es': "⚠️ Debe ser un número.", 'fr': "⚠️ Doit être un nombre.",
    'pt': "⚠️ Deve ser um número.", 'de': "⚠️ Muss eine Zahl sein.",
}
TRANSLATIONS['weights.add_value_modal.title'] = {'en': "Set Weight Value", 'es': "Establecer Valor de Peso", 'fr': "Définir la Valeur de Poids", 'pt': "Definir Valor de Peso", 'de': "Gewichtswert Festlegen"}
TRANSLATIONS['weights.add_value_modal.label_display'] = {'en': "Display Name", 'es': "Nombre a Mostrar", 'fr': "Nom Affiché", 'pt': "Nome de Exibição", 'de': "Anzeigename"}
TRANSLATIONS['weights.add_value_modal.label_weight'] = {'en': "Weight Value", 'es': "Valor de Peso", 'fr': "Valeur de Poids", 'pt': "Valor de Peso", 'de': "Gewichtswert"}
TRANSLATIONS['weights.err.weight_must_be_number'] = {
    'en': "⚠️ Weight must be a number.", 'es': "⚠️ El peso debe ser un número.", 'fr': "⚠️ Le poids doit être un nombre.",
    'pt': "⚠️ O peso deve ser um número.", 'de': "⚠️ Das Gewicht muss eine Zahl sein.",
}
TRANSLATIONS['weights.select_stat_placeholder'] = {
    'en': "Choose a stat to add...", 'es': "Elige una estadística para agregar...",
    'fr': "Choisissez une statistique à ajouter...", 'pt': "Escolha uma estatística para adicionar...",
    'de': "Statistik zum Hinzufügen wählen...",
}
TRANSLATIONS['weights.all_used'] = {
    'en': "All available stats are already in use.", 'es': "Todas las estadísticas disponibles ya están en uso.",
    'fr': "Toutes les statistiques disponibles sont déjà utilisées.", 'pt': "Todas as estatísticas disponíveis já estão em uso.",
    'de': "Alle verfügbaren Statistiken werden bereits verwendet.",
}
TRANSLATIONS['weights.which_stat_prompt'] = {
    'en': "Which stat would you like to add?", 'es': "¿Qué estadística te gustaría agregar?",
    'fr': "Quelle statistique souhaitez-vous ajouter ?", 'pt': "Qual estatística você gostaria de adicionar?",
    'de': "Welche Statistik möchtest du hinzufügen?",
}
TRANSLATIONS['weights.recalc_footer'] = {
    'en': "✅ Weights saved. Stats compute live — no recalculation needed.",
    'es': "✅ Pesos guardados. Las estadísticas se calculan en vivo — no se necesita recalcular.",
    'fr': "✅ Poids enregistrés. Les statistiques se calculent en direct — aucun recalcul nécessaire.",
    'pt': "✅ Pesos salvos. As estatísticas são calculadas ao vivo — nenhum recálculo necessário.",
    'de': "✅ Gewichte gespeichert. Statistiken werden live berechnet — keine Neuberechnung nötig.",
}
TRANSLATIONS['weights.delete_btn'] = {
    'en': "🗑️ Delete '{name}'", 'es': "🗑️ Eliminar '{name}'", 'fr': "🗑️ Supprimer « {name} »",
    'pt': "🗑️ Excluir '{name}'", 'de': "🗑️ '{name}' Löschen",
}
TRANSLATIONS['weights.cancel_btn'] = {'en': "Cancel", 'es': "Cancelar", 'fr': "Annuler", 'pt': "Cancelar", 'de': "Abbrechen"}
TRANSLATIONS['weights.delete_confirm_prompt'] = {
    'en': "Delete **{name}** (`{label}`)? This cannot be undone.",
    'es': "¿Eliminar **{name}** (`{label}`)? Esto no se puede deshacer.",
    'fr': "Supprimer **{name}** (`{label}`) ? Cette action est irréversible.",
    'pt': "Excluir **{name}** (`{label}`)? Isso não pode ser desfeito.",
    'de': "**{name}** (`{label}`) löschen? Dies kann nicht rückgängig gemacht werden.",
}
TRANSLATIONS['weights.edit_btn'] = {'en': "✏️ {label}: {value}", 'es': "✏️ {label}: {value}", 'fr': "✏️ {label} : {value}", 'pt': "✏️ {label}: {value}", 'de': "✏️ {label}: {value}"}
TRANSLATIONS['weights.add_btn'] = {'en': "➕ Add", 'es': "➕ Agregar", 'fr': "➕ Ajouter", 'pt': "➕ Adicionar", 'de': "➕ Hinzufügen"}
TRANSLATIONS['weights.recalc_btn'] = {'en': "🔄 Recalculate All", 'es': "🔄 Recalcular Todo", 'fr': "🔄 Tout Recalculer", 'pt': "🔄 Recalcular Tudo", 'de': "🔄 Alles Neu Berechnen"}
TRANSLATIONS['weights.delete_select_placeholder'] = {'en': "🗑️ Delete a factor...", 'es': "🗑️ Eliminar un factor...", 'fr': "🗑️ Supprimer un facteur...", 'pt': "🗑️ Excluir um fator...", 'de': "🗑️ Faktor löschen..."}
TRANSLATIONS['weights.delete_option_desc'] = {'en': "Weight: {value}", 'es': "Peso: {value}", 'fr': "Poids : {value}", 'pt': "Peso: {value}", 'de': "Gewicht: {value}"}
TRANSLATIONS['weights.title_pwr'] = {'en': "Power Rank", 'es': "Rango de Poder", 'fr': "Rang de Puissance", 'pt': "Rank de Poder", 'de': "Power-Rang"}
TRANSLATIONS['weights.title_ladder'] = {'en': "Ladder", 'es': "Escalafón", 'fr': "Classement", 'pt': "Ranking", 'de': "Rangliste"}
TRANSLATIONS['weights.title'] = {
    'en': "⚖️ {cat} Weights{scope}", 'es': "⚖️ Pesos de {cat}{scope}", 'fr': "⚖️ Poids de {cat}{scope}",
    'pt': "⚖️ Pesos de {cat}{scope}", 'de': "⚖️ {cat}-Gewichte{scope}",
}
TRANSLATIONS['weights.scope_league'] = {'en': " — {league}", 'es': " — {league}", 'fr': " — {league}", 'pt': " — {league}", 'de': " — {league}"}
TRANSLATIONS['weights.scope_global'] = {'en': " (Global)", 'es': " (Global)", 'fr': " (Global)", 'pt': " (Global)", 'de': " (Global)"}
TRANSLATIONS['weights.no_weights'] = {
    'en': "No weights defined. Click **➕ Add** to create one.",
    'es': "No hay pesos definidos. Haz clic en **➕ Agregar** para crear uno.",
    'fr': "Aucun poids défini. Cliquez sur **➕ Ajouter** pour en créer un.",
    'pt': "Nenhum peso definido. Clique em **➕ Adicionar** para criar um.",
    'de': "Keine Gewichte definiert. Klicke auf **➕ Hinzufügen**, um eines zu erstellen.",
}
TRANSLATIONS['weights.override_note'] = {
    'en': " *(override: {league})*", 'es': " *(anulación: {league})*", 'fr': " *(remplacement : {league})*",
    'pt': " *(substituição: {league})*", 'de': " *(Überschreibung: {league})*",
}
TRANSLATIONS['weights.footer'] = {
    'en': "Click a button to edit • ➕ Add new • Select to delete",
    'es': "Haz clic en un botón para editar • ➕ Agregar nuevo • Selecciona para eliminar",
    'fr': "Cliquez sur un bouton pour modifier • ➕ Ajouter • Sélectionnez pour supprimer",
    'pt': "Clique em um botão para editar • ➕ Adicionar novo • Selecione para excluir",
    'de': "Klicke auf eine Schaltfläche zum Bearbeiten • ➕ Neu hinzufügen • Zum Löschen auswählen",
}

# --- /weights: the 26 selectable stat labels ---

TRANSLATIONS['stat.yearly_avg']        = {'en': "Yearly Avg", 'es': "Promedio Anual", 'fr': "Moyenne Annuelle", 'pt': "Média Anual", 'de': "Jahresdurchschnitt"}
TRANSLATIONS['stat.30day_avg']         = {'en': "30-Day Avg", 'es': "Promedio 30 Días", 'fr': "Moyenne 30 Jours", 'pt': "Média 30 Dias", 'de': "30-Tage-Schnitt"}
TRANSLATIONS['stat.14day_avg']         = {'en': "14-Day Avg", 'es': "Promedio 14 Días", 'fr': "Moyenne 14 Jours", 'pt': "Média 14 Dias", 'de': "14-Tage-Schnitt"}
TRANSLATIONS['stat.7day_avg']          = {'en': "7-Day Avg", 'es': "Promedio 7 Días", 'fr': "Moyenne 7 Jours", 'pt': "Média 7 Dias", 'de': "7-Tage-Schnitt"}
TRANSLATIONS['stat.3day_avg']          = {'en': "3-Day Avg", 'es': "Promedio 3 Días", 'fr': "Moyenne 3 Jours", 'pt': "Média 3 Dias", 'de': "3-Tage-Schnitt"}
TRANSLATIONS['stat.hof_avg']           = {'en': "HOF Avg", 'es': "Promedio HOF", 'fr': "Moyenne HOF", 'pt': "Média HOF", 'de': "HOF-Schnitt"}
TRANSLATIONS['stat.e1_avg']            = {'en': "E1 Avg", 'es': "Promedio E1", 'fr': "Moyenne E1", 'pt': "Média E1", 'de': "E1-Schnitt"}
TRANSLATIONS['stat.e2_avg']            = {'en': "E2 Avg", 'es': "Promedio E2", 'fr': "Moyenne E2", 'pt': "Média E2", 'de': "E2-Schnitt"}
TRANSLATIONS['stat.e3_avg']            = {'en': "E3 Avg", 'es': "Promedio E3", 'fr': "Moyenne E3", 'pt': "Média E3", 'de': "E3-Schnitt"}
TRANSLATIONS['stat.gold_avg']          = {'en': "Gold- Avg", 'es': "Promedio Gold-", 'fr': "Moyenne Gold-", 'pt': "Média Gold-", 'de': "Gold--Schnitt"}
TRANSLATIONS['stat.total_ovr']         = {'en': "Total OVR", 'es': "OVR Total", 'fr': "OVR Total", 'pt': "OVR Total", 'de': "Gesamt-OVR"}
TRANSLATIONS['stat.team_total_ovr']    = {'en': "Team Total OVR", 'es': "OVR Total del Equipo", 'fr': "OVR Total de l'Équipe", 'pt': "OVR Total da Equipe", 'de': "Team-Gesamt-OVR"}
TRANSLATIONS['stat.total_ovr_ladder']  = {'en': "Total OVR (Ladder)", 'es': "OVR Total (Escalafón)", 'fr': "OVR Total (Classement)", 'pt': "OVR Total (Ranking)", 'de': "Gesamt-OVR (Rangliste)"}
TRANSLATIONS['stat.off_ovr']           = {'en': "Off OVR", 'es': "OVR Ofensivo", 'fr': "OVR Offensif", 'pt': "OVR Ofensivo", 'de': "Offensiv-OVR"}
TRANSLATIONS['stat.off_ovr_ladder']    = {'en': "Off OVR (Ladder)", 'es': "OVR Ofensivo (Escalafón)", 'fr': "OVR Offensif (Classement)", 'pt': "OVR Ofensivo (Ranking)", 'de': "Offensiv-OVR (Rangliste)"}
TRANSLATIONS['stat.def_ovr']           = {'en': "Def OVR", 'es': "OVR Defensivo", 'fr': "OVR Défensif", 'pt': "OVR Defensivo", 'de': "Defensiv-OVR"}
TRANSLATIONS['stat.30day_ladder']      = {'en': "30-Day (Ladder)", 'es': "30 Días (Escalafón)", 'fr': "30 Jours (Classement)", 'pt': "30 Dias (Ranking)", 'de': "30 Tage (Rangliste)"}
TRANSLATIONS['stat.kobes']             = {'en': "Kobes", 'es': "Kobes", 'fr': "Kobes", 'pt': "Kobes", 'de': "Kobes"}
TRANSLATIONS['stat.points']            = {'en': "Points", 'es': "Puntos", 'fr': "Points", 'pt': "Pontos", 'de': "Punkte"}
TRANSLATIONS['stat.games']             = {'en': "Games Played", 'es': "Partidas Jugadas", 'fr': "Matchs Joués", 'pt': "Jogos Disputados", 'de': "Gespielte Spiele"}
TRANSLATIONS['stat.three_td']          = {'en': "3+ TD Count", 'es': "Cantidad de 3+ TD", 'fr': "Nombre de 3+ TD", 'pt': "Quantidade de 3+ TD", 'de': "Anzahl 3+ TD"}
TRANSLATIONS['stat.three_td_pct']      = {'en': "3+ TD Pct", 'es': "Porcentaje de 3+ TD", 'fr': "Pourcentage de 3+ TD", 'pt': "Porcentagem de 3+ TD", 'de': "3+ TD Prozent"}
TRANSLATIONS['stat.two_pt_pct']        = {'en': "2-Pt Conv Pct", 'es': "Porcentaje de Conv. de 2 Pts", 'fr': "Pourcentage de Conv. à 2 Pts", 'pt': "Porcentagem de Conv. de 2 Pts", 'de': "2-Punkt-Conversion-Prozent"}
TRANSLATIONS['stat.yearly_avg_fumble_adj']   = {'en': "Yearly Avg (Fumble-Adj.)", 'es': "Promedio Anual (Ajust. Fumbles)", 'fr': "Moyenne Annuelle (Ajustée Fumbles)", 'pt': "Média Anual (Ajust. Fumbles)", 'de': "Jahresschnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.30day_avg_fumble_adj']    = {'en': "30-Day Avg (Fumble-Adj.)", 'es': "Promedio 30 Días (Ajust. Fumbles)", 'fr': "Moyenne 30 Jours (Ajustée Fumbles)", 'pt': "Média 30 Dias (Ajust. Fumbles)", 'de': "30-Tage-Schnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.hof_avg_fumble_adj']      = {'en': "HOF Avg (Fumble-Adj.)", 'es': "Promedio HOF (Ajust. Fumbles)", 'fr': "Moyenne HOF (Ajustée Fumbles)", 'pt': "Média HOF (Ajust. Fumbles)", 'de': "HOF-Schnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.e1_avg_fumble_adj']       = {'en': "E1 Avg (Fumble-Adj.)", 'es': "Promedio E1 (Ajust. Fumbles)", 'fr': "Moyenne E1 (Ajustée Fumbles)", 'pt': "Média E1 (Ajust. Fumbles)", 'de': "E1-Schnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.e2_avg_fumble_adj']       = {'en': "E2 Avg (Fumble-Adj.)", 'es': "Promedio E2 (Ajust. Fumbles)", 'fr': "Moyenne E2 (Ajustée Fumbles)", 'pt': "Média E2 (Ajust. Fumbles)", 'de': "E2-Schnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.e3_avg_fumble_adj']       = {'en': "E3 Avg (Fumble-Adj.)", 'es': "Promedio E3 (Ajust. Fumbles)", 'fr': "Moyenne E3 (Ajustée Fumbles)", 'pt': "Média E3 (Ajust. Fumbles)", 'de': "E3-Schnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.gold_avg_fumble_adj']     = {'en': "Gold- Avg (Fumble-Adj.)", 'es': "Promedio Gold- (Ajust. Fumbles)", 'fr': "Moyenne Gold- (Ajustée Fumbles)", 'pt': "Média Gold- (Ajust. Fumbles)", 'de': "Gold--Schnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.3day_avg_fumble_adj']     = {'en': "3-Day Avg (Fumble-Adj.)", 'es': "Promedio 3 Días (Ajust. Fumbles)", 'fr': "Moyenne 3 Jours (Ajustée Fumbles)", 'pt': "Média 3 Dias (Ajust. Fumbles)", 'de': "3-Tage-Schnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.7day_avg_fumble_adj']     = {'en': "7-Day Avg (Fumble-Adj.)", 'es': "Promedio 7 Días (Ajust. Fumbles)", 'fr': "Moyenne 7 Jours (Ajustée Fumbles)", 'pt': "Média 7 Dias (Ajust. Fumbles)", 'de': "7-Tage-Schnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.14day_avg_fumble_adj']    = {'en': "14-Day Avg (Fumble-Adj.)", 'es': "Promedio 14 Días (Ajust. Fumbles)", 'fr': "Moyenne 14 Jours (Ajustée Fumbles)", 'pt': "Média 14 Dias (Ajust. Fumbles)", 'de': "14-Tage-Schnitt (Fumble-Bereinigt)"}
TRANSLATIONS['stat.30day_ladder_fumble_adj'] = {'en': "30-Day (Ladder, Fumble-Adj.)", 'es': "30 Días (Escalafón, Ajust. Fumbles)", 'fr': "30 Jours (Classement, Ajustée Fumbles)", 'pt': "30 Dias (Ranking, Ajust. Fumbles)", 'de': "30 Tage (Rangliste, Fumble-Bereinigt)"}
TRANSLATIONS['stat.fumbles']           = {'en': "Fumbles", 'es': "Balones Perdidos", 'fr': "Fumbles", 'pt': "Fumbles", 'de': "Fumbles"}
TRANSLATIONS['stat.fourth_down_conv_pct'] = {'en': "4th Down Conv %", 'es': "% Conv. de 4to Down", 'fr': "% Conv. 4e Down", 'pt': "% Conv. 4th Down", 'de': "4th-Down-Conversion-%"}

# --- /league ---

TRANSLATIONS['league.add_modal.title'] = {'en': "Add New League", 'es': "Agregar Nueva Liga", 'fr': "Ajouter une Nouvelle Ligue", 'pt': "Adicionar Nova Liga", 'de': "Neue Liga Hinzufügen"}
TRANSLATIONS['league.add_modal.label_id'] = {'en': "League ID (2 letters, e.g. NX)", 'es': "ID de Liga (2 letras, ej. NX)", 'fr': "ID de Ligue (2 lettres, ex. NX)", 'pt': "ID da Liga (2 letras, ex. NX)", 'de': "Liga-ID (2 Buchstaben, z. B. NX)"}
TRANSLATIONS['league.add_modal.label_name'] = {'en': "Full Name (e.g. NeuroChristians)", 'es': "Nombre Completo (ej. NeuroChristians)", 'fr': "Nom Complet (ex. NeuroChristians)", 'pt': "Nome Completo (ex. NeuroChristians)", 'de': "Vollständiger Name (z. B. NeuroChristians)"}
TRANSLATIONS['league.err.id_must_be_2_letters'] = {
    'en': "⚠️ League ID must be exactly 2 letters.", 'es': "⚠️ El ID de la liga debe tener exactamente 2 letras.",
    'fr': "⚠️ L'ID de la ligue doit comporter exactement 2 lettres.", 'pt': "⚠️ O ID da liga deve ter exatamente 2 letras.",
    'de': "⚠️ Die Liga-ID muss genau 2 Buchstaben haben.",
}
TRANSLATIONS['league.err.already_exists'] = {
    'en': "⚠️ League `{id}` already exists.", 'es': "⚠️ La liga `{id}` ya existe.", 'fr': "⚠️ La ligue `{id}` existe déjà.",
    'pt': "⚠️ A liga `{id}` já existe.", 'de': "⚠️ Die Liga `{id}` existiert bereits.",
}
TRANSLATIONS['league.add.success'] = {
    'en': "✅ League **{name}** (`{id}`) added. Re-sync slash commands with `!sync` to update dropdowns.",
    'es': "✅ Liga **{name}** (`{id}`) agregada. Vuelve a sincronizar los comandos con `!sync` para actualizar los menús.",
    'fr': "✅ Ligue **{name}** (`{id}`) ajoutée. Resynchronisez les commandes avec `!sync` pour mettre à jour les menus.",
    'pt': "✅ Liga **{name}** (`{id}`) adicionada. Sincronize novamente os comandos com `!sync` para atualizar os menus.",
    'de': "✅ Liga **{name}** (`{id}`) hinzugefügt. Synchronisiere die Befehle mit `!sync` neu, um die Dropdowns zu aktualisieren.",
}
TRANSLATIONS['league.rename_select_placeholder'] = {
    'en': "Choose a league to rename...", 'es': "Elige una liga para renombrar...",
    'fr': "Choisissez une ligue à renommer...", 'pt': "Escolha uma liga para renomear...",
    'de': "Liga zum Umbenennen wählen...",
}
TRANSLATIONS['league.rename_modal_title'] = {
    'en': "Rename League {id}", 'es': "Renombrar Liga {id}", 'fr': "Renommer la Ligue {id}",
    'pt': "Renomear Liga {id}", 'de': "Liga {id} Umbenennen",
}
TRANSLATIONS['league.rename_modal_label'] = {'en': "New Name", 'es': "Nuevo Nombre", 'fr': "Nouveau Nom", 'pt': "Novo Nome", 'de': "Neuer Name"}
TRANSLATIONS['league.rename.success'] = {
    'en': "✅ League `{id}` renamed to **{name}**. Re-sync with `!sync` to update dropdowns.",
    'es': "✅ Liga `{id}` renombrada a **{name}**. Vuelve a sincronizar con `!sync` para actualizar los menús.",
    'fr': "✅ Ligue `{id}` renommée en **{name}**. Resynchronisez avec `!sync` pour mettre à jour les menus.",
    'pt': "✅ Liga `{id}` renomeada para **{name}**. Sincronize novamente com `!sync` para atualizar os menus.",
    'de': "✅ Liga `{id}` umbenannt in **{name}**. Mit `!sync` neu synchronisieren, um die Dropdowns zu aktualisieren.",
}
TRANSLATIONS['league.which_rename_prompt'] = {
    'en': "Which league would you like to rename?", 'es': "¿Qué liga te gustaría renombrar?",
    'fr': "Quelle ligue souhaitez-vous renommer ?", 'pt': "Qual liga você gostaria de renomear?",
    'de': "Welche Liga möchtest du umbenennen?",
}

# --- /newday, /sync ---

TRANSLATIONS['newday.success'] = {
    'en': "✅ New day initialised and rank cache cleared.", 'es': "✅ Nuevo día inicializado y caché de rango eliminada.",
    'fr': "✅ Nouveau jour initialisé et cache de classement vidé.", 'pt': "✅ Novo dia iniciado e cache de rank limpo.",
    'de': "✅ Neuer Tag initialisiert und Rangdaten-Cache geleert.",
}
TRANSLATIONS['sync.success'] = {
    'en': "✅ Synced {count} commands to this server. Globals cleared.",
    'es': "✅ Se sincronizaron {count} comandos con este servidor. Globales eliminados.",
    'fr': "✅ {count} commandes synchronisées avec ce serveur. Commandes globales effacées.",
    'pt': "✅ {count} comandos sincronizados com este servidor. Globais limpos.",
    'de': "✅ {count} Befehle mit diesem Server synchronisiert. Globale Befehle geleert.",
}

# --- gifs ---

TRANSLATIONS['gif.role_required'] = {
    'en': "⛔ Requires **Administrator**, **League Owner**, **Madden Admin**, or **Gif Master** role.",
    'es': "⛔ Requiere el rol de **Administrador**, **League Owner**, **Madden Admin** o **Gif Master**.",
    'fr': "⛔ Nécessite le rôle **Administrateur**, **League Owner**, **Madden Admin** ou **Gif Master**.",
    'pt': "⛔ Requer o cargo de **Administrador**, **League Owner**, **Madden Admin** ou **Gif Master**.",
    'de': "⛔ Erfordert die Rolle **Administrator**, **League Owner**, **Madden Admin** oder **Gif Master**.",
}
TRANSLATIONS['gif.reload_success'] = {
    'en': "✅ Reloaded GIF folders.", 'es': "✅ Carpetas de GIF recargadas.", 'fr': "✅ Dossiers de GIF rechargés.",
    'pt': "✅ Pastas de GIF recarregadas.", 'de': "✅ GIF-Ordner neu geladen.",
}
TRANSLATIONS['gif.err.invalid_folder'] = {
    'en': "⚠️ Invalid folder.", 'es': "⚠️ Carpeta no válida.", 'fr': "⚠️ Dossier invalide.", 'pt': "⚠️ Pasta inválida.", 'de': "⚠️ Ungültiger Ordner.",
}
TRANSLATIONS['gif.err.not_gif'] = {
    'en': "⚠️ File must be a `.gif`.", 'es': "⚠️ El archivo debe ser un `.gif`.", 'fr': "⚠️ Le fichier doit être un `.gif`.",
    'pt': "⚠️ O arquivo deve ser um `.gif`.", 'de': "⚠️ Die Datei muss eine `.gif` sein.",
}
TRANSLATIONS['gif.err.too_large'] = {
    'en': "⚠️ File too large ({size}KB). Max 5MB.", 'es': "⚠️ Archivo demasiado grande ({size}KB). Máximo 5MB.",
    'fr': "⚠️ Fichier trop volumineux ({size}Ko). Max 5 Mo.", 'pt': "⚠️ Arquivo muito grande ({size}KB). Máximo de 5MB.",
    'de': "⚠️ Datei zu groß ({size}KB). Maximal 5MB.",
}
TRANSLATIONS['gif.add_success'] = {
    'en': "✅ Saved `{filename}` to `{folder}/`.", 'es': "✅ Se guardó `{filename}` en `{folder}/`.",
    'fr': "✅ `{filename}` enregistré dans `{folder}/`.", 'pt': "✅ `{filename}` salvo em `{folder}/`.",
    'de': "✅ `{filename}` in `{folder}/` gespeichert.",
}

# --- tournaments ---

TRANSLATIONS['tournament.err.need_2_players'] = {
    'en': "⚠️ Need at least 2 players.", 'es': "⚠️ Se necesitan al menos 2 jugadores.", 'fr': "⚠️ Il faut au moins 2 joueurs.",
    'pt': "⚠️ São necessários pelo menos 2 jogadores.", 'de': "⚠️ Mindestens 2 Spieler erforderlich.",
}
TRANSLATIONS['tournament.start.success'] = {
    'en': "✅ Tournament **{name}** created! ID: `{id}`", 'es': "✅ ¡Torneo **{name}** creado! ID: `{id}`",
    'fr': "✅ Tournoi **{name}** créé ! ID : `{id}`", 'pt': "✅ Torneio **{name}** criado! ID: `{id}`",
    'de': "✅ Turnier **{name}** erstellt! ID: `{id}`",
}
TRANSLATIONS['tournament.champion'] = {
    'en': "🎉 Tournament over! **{winner}** is the champion!", 'es': "🎉 ¡Torneo terminado! **{winner}** es el campeón!",
    'fr': "🎉 Tournoi terminé ! **{winner}** est le champion !", 'pt': "🎉 Torneio encerrado! **{winner}** é o campeão!",
    'de': "🎉 Turnier beendet! **{winner}** ist der Champion!",
}
TRANSLATIONS['tournament.match_result'] = {
    'en': "✅ Match {num} — **{winner}** wins.", 'es': "✅ Partida {num} — **{winner}** gana.",
    'fr': "✅ Match {num} — **{winner}** gagne.", 'pt': "✅ Partida {num} — **{winner}** vence.",
    'de': "✅ Spiel {num} — **{winner}** gewinnt.",
}

# --- /nukeguildcmds ---

TRANSLATIONS['nuke.result'] = {
    'en': "Guild ID: `{guild_id}`\nOur guild commands cleared: **{count}** (status {status})\nGlobal commands intact: **{global_count}**",
    'es': "ID del Servidor: `{guild_id}`\nComandos del servidor eliminados: **{count}** (estado {status})\nComandos globales intactos: **{global_count}**",
    'fr': "ID du Serveur : `{guild_id}`\nCommandes du serveur effacées : **{count}** (statut {status})\nCommandes globales intactes : **{global_count}**",
    'pt': "ID do Servidor: `{guild_id}`\nComandos do servidor limpos: **{count}** (status {status})\nComandos globais intactos: **{global_count}**",
    'de': "Server-ID: `{guild_id}`\nServer-Befehle geleert: **{count}** (Status {status})\nGlobale Befehle unverändert: **{global_count}**",
}

# --- /test ---

TRANSLATIONS['test_cmd.timeout'] = {
    'en': "⚠️ Tests timed out after 120 seconds.", 'es': "⚠️ Las pruebas superaron el tiempo de espera de 120 segundos.",
    'fr': "⚠️ Les tests ont expiré après 120 secondes.", 'pt': "⚠️ Os testes expiraram após 120 segundos.",
    'de': "⚠️ Zeitüberschreitung der Tests nach 120 Sekunden.",
}
TRANSLATIONS['test_cmd.failed_to_run'] = {
    'en': "⚠️ Failed to run tests: {error}", 'es': "⚠️ Error al ejecutar las pruebas: {error}",
    'fr': "⚠️ Échec de l'exécution des tests : {error}", 'pt': "⚠️ Falha ao executar os testes: {error}",
    'de': "⚠️ Tests konnten nicht ausgeführt werden: {error}",
}
TRANSLATIONS['test_cmd.title'] = {'en': "{icon} Test Results", 'es': "{icon} Resultados de las Pruebas", 'fr': "{icon} Résultats des Tests", 'pt': "{icon} Resultados dos Testes", 'de': "{icon} Testergebnisse"}
TRANSLATIONS['test_cmd.field_summary'] = {'en': "Summary", 'es': "Resumen", 'fr': "Résumé", 'pt': "Resumo", 'de': "Zusammenfassung"}
TRANSLATIONS['test_cmd.field_failures'] = {'en': "Failures", 'es': "Fallos", 'fr': "Échecs", 'pt': "Falhas", 'de': "Fehlschläge"}

# --- tournament.py embeds ---

TRANSLATIONS['tournament.round_grand_final'] = {'en': "🏆 Grand Final", 'es': "🏆 Gran Final", 'fr': "🏆 Grande Finale", 'pt': "🏆 Grande Final", 'de': "🏆 Großes Finale"}
TRANSLATIONS['tournament.round_semifinals']  = {'en': "Semifinals", 'es': "Semifinales", 'fr': "Demi-finales", 'pt': "Semifinais", 'de': "Halbfinale"}
TRANSLATIONS['tournament.round_quarterfinals'] = {'en': "Quarterfinals", 'es': "Cuartos de Final", 'fr': "Quarts de Finale", 'pt': "Quartas de Final", 'de': "Viertelfinale"}
TRANSLATIONS['tournament.round_n'] = {'en': "Round {n}", 'es': "Ronda {n}", 'fr': "Manche {n}", 'pt': "Rodada {n}", 'de': "Runde {n}"}
TRANSLATIONS['tournament.current_suffix'] = {'en': "  ← current", 'es': "  ← actual", 'fr': "  ← en cours", 'pt': "  ← atual", 'de': "  ← aktuell"}
TRANSLATIONS['tournament.bye'] = {'en': "*(bye)*", 'es': "*(pase directo)*", 'fr': "*(exempt)*", 'pt': "*(passagem direta)*", 'de': "*(Freilos)*"}
TRANSLATIONS['tournament.cont'] = {'en': "{label} (cont.)", 'es': "{label} (cont.)", 'fr': "{label} (suite)", 'pt': "{label} (cont.)", 'de': "{label} (Forts.)"}
TRANSLATIONS['tournament.status_active']   = {'en': "Active", 'es': "Activo", 'fr': "Actif", 'pt': "Ativo", 'de': "Aktiv"}
TRANSLATIONS['tournament.status_complete'] = {'en': "Complete", 'es': "Completado", 'fr': "Terminé", 'pt': "Concluído", 'de': "Abgeschlossen"}
TRANSLATIONS['tournament.status_line'] = {
    'en': "Status: **{status}**", 'es': "Estado: **{status}**", 'fr': "Statut : **{status}**",
    'pt': "Status: **{status}**", 'de': "Status: **{status}**",
}
TRANSLATIONS['tournament.champion_footer'] = {
    'en': "🎉 Champion: {champ}", 'es': "🎉 Campeón: {champ}", 'fr': "🎉 Champion : {champ}",
    'pt': "🎉 Campeão: {champ}", 'de': "🎉 Champion: {champ}",
}
TRANSLATIONS['tournament.pending_footer'] = {
    'en': "ID: {id}  •  Round {cur}/{total}  •  {pending} match(es) pending",
    'es': "ID: {id}  •  Ronda {cur}/{total}  •  {pending} partida(s) pendiente(s)",
    'fr': "ID : {id}  •  Manche {cur}/{total}  •  {pending} match(s) en attente",
    'pt': "ID: {id}  •  Rodada {cur}/{total}  •  {pending} partida(s) pendente(s)",
    'de': "ID: {id}  •  Runde {cur}/{total}  •  {pending} Spiel(e) ausstehend",
}
TRANSLATIONS['tournament.list_title'] = {'en': "📋 All Tournaments", 'es': "📋 Todos los Torneos", 'fr': "📋 Tous les Tournois", 'pt': "📋 Todos os Torneios", 'de': "📋 Alle Turniere"}
TRANSLATIONS['tournament.list_active'] = {'en': "🟢 Active", 'es': "🟢 Activos", 'fr': "🟢 Actifs", 'pt': "🟢 Ativos", 'de': "🟢 Aktiv"}
TRANSLATIONS['tournament.list_completed'] = {'en': "✅ Completed", 'es': "✅ Completados", 'fr': "✅ Terminés", 'pt': "✅ Concluídos", 'de': "✅ Abgeschlossen"}
TRANSLATIONS['tournament.list_row'] = {
    'en': "`{id}` — **{name}**  ({count} players, {created})",
    'es': "`{id}` — **{name}**  ({count} jugadores, {created})",
    'fr': "`{id}` — **{name}**  ({count} joueurs, {created})",
    'pt': "`{id}` — **{name}**  ({count} jogadores, {created})",
    'de': "`{id}` — **{name}**  ({count} Spieler, {created})",
}
TRANSLATIONS['tournament.list_row_champion'] = {
    'en': "`{id}` — **{name}**, Winner: {champ}  ({count} players, {created})",
    'es': "`{id}` — **{name}**, Ganador: {champ}  ({count} jugadores, {created})",
    'fr': "`{id}` — **{name}**, Vainqueur : {champ}  ({count} joueurs, {created})",
    'pt': "`{id}` — **{name}**, Vencedor: {champ}  ({count} jogadores, {created})",
    'de': "`{id}` — **{name}**, Gewinner: {champ}  ({count} Spieler, {created})",
}
TRANSLATIONS['tournament.no_tournaments'] = {
    'en': "No tournaments have been created yet.", 'es': "Aún no se han creado torneos.",
    'fr': "Aucun tournoi n'a encore été créé.", 'pt': "Nenhum torneio foi criado ainda.",
    'de': "Es wurden noch keine Turniere erstellt.",
}

# --- /ladder (optimized_bot.py entry point, screenshot-extraction path) ---

TRANSLATIONS['ladder_cmd.err.screenshot_extraction_failed'] = {
    'en': "⚠️ Screenshot extraction failed: {error}", 'es': "⚠️ Falló la extracción de la captura: {error}",
    'fr': "⚠️ Échec de l'extraction de la capture d'écran : {error}", 'pt': "⚠️ Falha na extração da captura de tela: {error}",
    'de': "⚠️ Screenshot-Extraktion fehlgeschlagen: {error}",
}
TRANSLATIONS['ladder_cmd.ovr_updated'] = {
    'en': "📊 **{ign}** OVR updated: {changes}", 'es': "📊 OVR de **{ign}** actualizado: {changes}",
    'fr': "📊 OVR de **{ign}** mis à jour : {changes}", 'pt': "📊 OVR de **{ign}** atualizado: {changes}",
    'de': "📊 OVR von **{ign}** aktualisiert: {changes}",
}
TRANSLATIONS['ladder_cmd.missing_players'] = {
    'en': "⚠️ The following players from the screenshot are not registered in **{league}** and have been excluded from the pre-selection:\n{list}\n\nUse `/ign` to set their real IGN mapping or `/register` to add them.",
    'es': "⚠️ Los siguientes jugadores de la captura no están registrados en **{league}** y fueron excluidos de la preselección:\n{list}\n\nUsa `/ign` para asignar su IGN real o `/register` para agregarlos.",
    'fr': "⚠️ Les joueurs suivants de la capture d'écran ne sont pas enregistrés dans **{league}** et ont été exclus de la présélection :\n{list}\n\nUtilisez `/ign` pour définir leur IGN réel ou `/register` pour les ajouter.",
    'pt': "⚠️ Os seguintes jogadores da captura de tela não estão registrados em **{league}** e foram excluídos da pré-seleção:\n{list}\n\nUse `/ign` para definir o IGN real deles ou `/register` para adicioná-los.",
    'de': "⚠️ Die folgenden Spieler aus dem Screenshot sind nicht in **{league}** registriert und wurden von der Vorauswahl ausgeschlossen:\n{list}\n\nVerwende `/ign`, um ihren echten IGN zuzuordnen, oder `/register`, um sie hinzuzufügen.",
}
TRANSLATIONS['ladder_cmd.ovr_updates_header'] = {
    'en': "**OVR updates applied from screenshots:**\n{changes}",
    'es': "**Actualizaciones de OVR aplicadas desde las capturas:**\n{changes}",
    'fr': "**Mises à jour d'OVR appliquées depuis les captures d'écran :**\n{changes}",
    'pt': "**Atualizações de OVR aplicadas a partir das capturas de tela:**\n{changes}",
    'de': "**OVR-Aktualisierungen aus Screenshots angewendet:**\n{changes}",
}
TRANSLATIONS['ladder_cmd.match.prompt'] = {
    'en': "⚠️ Couldn't confidently match the following names from the screenshot to a registered **{league}** player — the AI vision may have misread them slightly. Pick who each one actually is below, or skip if they're not really in the league:\n{list}",
    'es': "⚠️ No se pudo emparejar con confianza los siguientes nombres de la captura con un jugador registrado de **{league}** — es posible que la IA los haya leído mal. Elige quién es cada uno abajo, o omite si no están realmente en la liga:\n{list}",
    'fr': "⚠️ Impossible de faire correspondre avec certitude les noms suivants de la capture d'écran à un joueur enregistré de **{league}** — l'IA a peut-être mal lu certains noms. Choisissez qui est réellement chacun ci-dessous, ou ignorez s'ils ne sont pas vraiment dans la ligue :\n{list}",
    'pt': "⚠️ Não foi possível combinar com confiança os seguintes nomes da captura de tela com um jogador registrado em **{league}** — a IA pode ter lido os nomes incorretamente. Escolha quem é cada um abaixo, ou pule se não estiverem realmente na liga:\n{list}",
    'de': "⚠️ Die folgenden Namen aus dem Screenshot konnten nicht zuverlässig einem registrierten **{league}**-Spieler zugeordnet werden — die KI hat sie möglicherweise leicht falsch gelesen. Wähle unten aus, wer jeweils gemeint ist, oder überspringe, falls sie nicht wirklich in der Liga sind:\n{list}",
}
TRANSLATIONS['ladder_cmd.match.placeholder'] = {
    'en': "Match '{name}' to...", 'es': "Emparejar '{name}' con...",
    'fr': "Faire correspondre « {name} » à...", 'pt': "Combinar '{name}' com...",
    'de': "'{name}' zuordnen zu...",
}
TRANSLATIONS['ladder_cmd.match.skip_option'] = {
    'en': "Skip — not actually in this league", 'es': "Omitir — no está realmente en esta liga",
    'fr': "Ignorer — pas réellement dans cette ligue", 'pt': "Pular — não está realmente nesta liga",
    'de': "Überspringen — nicht wirklich in dieser Liga",
}
TRANSLATIONS['ladder_cmd.match.confirm_btn'] = {
    'en': "Confirm Matches", 'es': "Confirmar Coincidencias",
    'fr': "Confirmer les Correspondances", 'pt': "Confirmar Correspondências",
    'de': "Zuordnungen Bestätigen",
}
TRANSLATIONS['ladder_cmd.match.skip_all_btn'] = {
    'en': "Skip All", 'es': "Omitir Todo", 'fr': "Tout Ignorer", 'pt': "Pular Tudo", 'de': "Alle Überspringen",
}
TRANSLATIONS['ladder_cmd.match.next_batch'] = {
    'en': "✅ {done}/{total} matched so far. A few more couldn't be confidently matched either — pick who each one actually is below, or skip:\n{list}",
    'es': "✅ {done}/{total} emparejados hasta ahora. Algunos más no se pudieron emparejar con confianza — elige quién es cada uno abajo, o omite:\n{list}",
    'fr': "✅ {done}/{total} déjà associés. Quelques autres n'ont pas pu être associés avec certitude non plus — choisissez qui est réellement chacun ci-dessous, ou ignorez :\n{list}",
    'pt': "✅ {done}/{total} correspondidos até agora. Mais alguns também não puderam ser combinados com confiança — escolha quem é cada um abaixo, ou pule:\n{list}",
    'de': "✅ {done}/{total} bisher zugeordnet. Ein paar weitere konnten ebenfalls nicht zuverlässig zugeordnet werden — wähle unten aus, wer jeweils gemeint ist, oder überspringe:\n{list}",
}
TRANSLATIONS['ladder_cmd.sanity.prompt'] = {
    'en': "⚠️ The following OVR change(s) from the screenshot look unusually large compared to what's on record — this can happen when the AI vision misreads a digit (e.g. a 3 read as an 8). Review each below before it affects the ladder:\n{list}",
    'es': "⚠️ Los siguientes cambios de OVR de la captura parecen inusualmente grandes en comparación con lo registrado — esto puede pasar cuando la IA lee mal un dígito (por ejemplo, un 3 leído como un 8). Revisa cada uno abajo antes de que afecte la escalera:\n{list}",
    'fr': "⚠️ Les changements d'OVR suivants issus de la capture semblent anormalement importants par rapport à ce qui est enregistré — cela peut arriver quand l'IA lit mal un chiffre (par ex. un 3 lu comme un 8). Vérifiez chacun ci-dessous avant qu'il n'affecte le classement :\n{list}",
    'pt': "⚠️ As seguintes mudanças de OVR da captura parecem incomumente grandes em comparação com o registrado — isso pode acontecer quando a IA lê um dígito errado (ex.: um 3 lido como 8). Revise cada uma abaixo antes que afete a ladder:\n{list}",
    'de': "⚠️ Die folgenden OVR-Änderungen aus dem Screenshot wirken im Vergleich zum bisherigen Wert ungewöhnlich groß — das kann passieren, wenn die KI eine Ziffer falsch liest (z. B. eine 3 als 8). Prüfe jede einzeln, bevor sie sich auf die Ladder auswirkt:\n{list}",
}
TRANSLATIONS['ladder_cmd.sanity.placeholder'] = {
    'en': "{ign}'s OVR change...", 'es': "Cambio de OVR de {ign}...",
    'fr': "Changement d'OVR de {ign}...", 'pt': "Mudança de OVR de {ign}...",
    'de': "OVR-Änderung von {ign}...",
}
TRANSLATIONS['ladder_cmd.sanity.accept_option'] = {
    'en': "Use extracted: {changes}", 'es': "Usar extraído: {changes}",
    'fr': "Utiliser extrait : {changes}", 'pt': "Usar extraído: {changes}",
    'de': "Extrahiert verwenden: {changes}",
}
TRANSLATIONS['ladder_cmd.sanity.reject_option'] = {
    'en': "Keep current value (likely a misread)", 'es': "Mantener valor actual (probable error de lectura)",
    'fr': "Conserver la valeur actuelle (probable erreur de lecture)", 'pt': "Manter valor atual (provável erro de leitura)",
    'de': "Aktuellen Wert behalten (wahrscheinlich falsch gelesen)",
}
TRANSLATIONS['ladder_cmd.sanity.confirm_btn'] = {
    'en': "Confirm", 'es': "Confirmar", 'fr': "Confirmer", 'pt': "Confirmar", 'de': "Bestätigen",
}
TRANSLATIONS['ladder_cmd.sanity.next_batch'] = {
    'en': "✅ {done}/{total} OVR changes reviewed so far. A few more need review:\n{list}",
    'es': "✅ {done}/{total} cambios de OVR revisados hasta ahora. Faltan algunos más:\n{list}",
    'fr': "✅ {done}/{total} changements d'OVR examinés jusqu'ici. Quelques autres restent à vérifier :\n{list}",
    'pt': "✅ {done}/{total} mudanças de OVR revisadas até agora. Mais algumas precisam de revisão:\n{list}",
    'de': "✅ {done}/{total} OVR-Änderungen bisher überprüft. Ein paar weitere müssen noch geprüft werden:\n{list}",
}

# =============================================================================
# /nick, /ign, /rename — player name management (newly documented commands)
# =============================================================================

TRANSLATIONS['nick.err.not_found'] = {
    'en': "⚠️ No player found with real IGN `{real_ign}`.", 'es': "⚠️ No se encontró ningún jugador con el IGN real `{real_ign}`.",
    'fr': "⚠️ Aucun joueur trouvé avec l'IGN réel `{real_ign}`.", 'pt': "⚠️ Nenhum jogador encontrado com o IGN real `{real_ign}`.",
    'de': "⚠️ Kein Spieler mit dem echten IGN `{real_ign}` gefunden.",
}
TRANSLATIONS['nick.err.taken'] = {
    'en': "⚠️ Nickname `{nickname}` is already taken by another player.",
    'es': "⚠️ El apodo `{nickname}` ya lo tiene otro jugador.",
    'fr': "⚠️ Le pseudo `{nickname}` est déjà pris par un autre joueur.",
    'pt': "⚠️ O apelido `{nickname}` já está em uso por outro jogador.",
    'de': "⚠️ Der Spitzname `{nickname}` wird bereits von einem anderen Spieler verwendet.",
}
TRANSLATIONS['nick.success.title'] = {'en': "✅ Nickname Set", 'es': "✅ Apodo Establecido", 'fr': "✅ Pseudo Défini", 'pt': "✅ Apelido Definido", 'de': "✅ Spitzname Festgelegt"}
TRANSLATIONS['nick.footer.previously_known'] = {
    'en': "Previously known as: {old_nick}", 'es': "Anteriormente conocido como: {old_nick}",
    'fr': "Anciennement connu sous : {old_nick}", 'pt': "Anteriormente conhecido como: {old_nick}",
    'de': "Vorher bekannt als: {old_nick}",
}

TRANSLATIONS['ign_cmd.success.title'] = {'en': "✅ Real IGN Updated", 'es': "✅ IGN Real Actualizado", 'fr': "✅ IGN Réel Mis à Jour", 'pt': "✅ IGN Real Atualizado", 'de': "✅ Echter IGN Aktualisiert"}
TRANSLATIONS['ign_cmd.field.old_real_ign'] = {'en': "Old Real IGN", 'es': "IGN Real Anterior", 'fr': "Ancien IGN Réel", 'pt': "IGN Real Anterior", 'de': "Alter Echter IGN"}
TRANSLATIONS['ign_cmd.field.new_real_ign'] = {'en': "New Real IGN", 'es': "Nuevo IGN Real", 'fr': "Nouvel IGN Réel", 'pt': "Novo IGN Real", 'de': "Neuer Echter IGN"}

TRANSLATIONS['rename_cmd.err.taken'] = {
    'en': "⚠️ Nickname `{nickname}` is already taken.", 'es': "⚠️ El apodo `{nickname}` ya está en uso.",
    'fr': "⚠️ Le pseudo `{nickname}` est déjà pris.", 'pt': "⚠️ O apelido `{nickname}` já está em uso.",
    'de': "⚠️ Der Spitzname `{nickname}` wird bereits verwendet.",
}
TRANSLATIONS['rename_cmd.success.title'] = {'en': "✅ Player Renamed", 'es': "✅ Jugador Renombrado", 'fr': "✅ Joueur Renommé", 'pt': "✅ Jogador Renomeado", 'de': "✅ Spieler Umbenannt"}
TRANSLATIONS['rename_cmd.field.old_nickname'] = {'en': "Old Nickname", 'es': "Apodo Anterior", 'fr': "Ancien Pseudo", 'pt': "Apelido Anterior", 'de': "Alter Spitzname"}
TRANSLATIONS['rename_cmd.field.new_nickname'] = {'en': "New Nickname", 'es': "Nuevo Apodo", 'fr': "Nouveau Pseudo", 'pt': "Novo Apelido", 'de': "Neuer Spitzname"}

# --- /score: fumbles (added after the original score.* keys, directly logged
# per entry rather than derived from the score value) ---

TRANSLATIONS['score.modal.label_fumbles'] = {
    'en': "Fumbles", 'es': "Balones Perdidos", 'fr': "Fumbles", 'pt': "Fumbles", 'de': "Fumbles",
}
TRANSLATIONS['score.err.invalid_fumbles'] = {
    'en': "⚠️ Fumbles must be an integer.", 'es': "⚠️ Los balones perdidos deben ser un número entero.",
    'fr': "⚠️ Le nombre de fumbles doit être un entier.", 'pt': "⚠️ Os fumbles devem ser um número inteiro.",
    'de': "⚠️ Fumbles müssen eine ganze Zahl sein.",
}
TRANSLATIONS['score.suffix.fumbles'] = {
    'en': "  |  Fumbles: {count}", 'es': "  |  Balones Perdidos: {count}", 'fr': "  |  Fumbles : {count}",
    'pt': "  |  Fumbles: {count}", 'de': "  |  Fumbles: {count}",
}

# --- Deprecated prefix-command notice (no slash-command interaction exists
# here to read locale from, so this uses the guild's preferred_locale as a
# best-effort signal instead — see on_command_error in optimized_bot.py) ---

TRANSLATIONS['prefix.deprecated'] = {
    'en': "Whoops, looks like you're trying to use an old command style, please check the /manual to see the list of current supported commands",
    'es': "Ups, parece que estás usando un estilo de comando antiguo. Consulta /manual para ver la lista de comandos compatibles actualmente",
    'fr': "Oups, on dirait que vous utilisez un ancien style de commande. Consultez /manual pour voir la liste des commandes actuellement prises en charge",
    'pt': "Ops, parece que você está usando um estilo de comando antigo. Confira /manual para ver a lista de comandos atualmente suportados",
    'de': "Hoppla, es sieht so aus, als würdest du einen alten Befehlsstil verwenden. Schau dir /manual an, um die Liste der aktuell unterstützten Befehle zu sehen",
}

# --- /scores grid redesign (date range, players x dates) ---

TRANSLATIONS['scores.no_scores_range'] = {
    'en': "No scores recorded for {league} between {start} and {end}.",
    'es': "No hay puntuaciones registradas para {league} entre {start} y {end}.",
    'fr': "Aucun score enregistré pour {league} entre {start} et {end}.",
    'pt': "Nenhuma pontuação registrada para {league} entre {start} e {end}.",
    'de': "Für {league} sind zwischen {start} und {end} keine Punktestände erfasst.",
}
TRANSLATIONS['scores.err.range_order'] = {
    'en': "⚠️ The end date must be on or after the start date.",
    'es': "⚠️ La fecha de fin debe ser igual o posterior a la fecha de inicio.",
    'fr': "⚠️ La date de fin doit être identique ou postérieure à la date de début.",
    'pt': "⚠️ A data final deve ser igual ou posterior à data inicial.",
    'de': "⚠️ Das Enddatum muss am oder nach dem Startdatum liegen.",
}
TRANSLATIONS['scores.legend_title'] = {
    'en': "**Matchups this range:**", 'es': "**Enfrentamientos en este rango:**",
    'fr': "**Affrontements sur cette période :**", 'pt': "**Confrontos neste período:**",
    'de': "**Begegnungen in diesem Zeitraum:**",
}
TRANSLATIONS['scores.legend_line'] = {
    'en': "`{date}` vs **{opp}**", 'es': "`{date}` vs **{opp}**",
    'fr': "`{date}` vs **{opp}**", 'pt': "`{date}` vs **{opp}**",
    'de': "`{date}` vs **{opp}**",
}
TRANSLATIONS['scores.grid_title'] = {
    'en': "{league} — {start} to {end}", 'es': "{league} — {start} a {end}",
    'fr': "{league} — {start} au {end}", 'pt': "{league} — {start} a {end}",
    'de': "{league} — {start} bis {end}",
}
TRANSLATIONS['scores.total_row_label'] = {
    'en': "TOTAL", 'es': "TOTAL", 'fr': "TOTAL", 'pt': "TOTAL", 'de': "GESAMT",
}

# --- /legacy command group + /stats ---

TRANSLATIONS['legacy.err.no_archive'] = {
    'en': "⚠️ No archived season found for {year}.",
    'es': "⚠️ No se encontró una temporada archivada para {year}.",
    'fr': "⚠️ Aucune saison archivée trouvée pour {year}.",
    'pt': "⚠️ Nenhuma temporada arquivada encontrada para {year}.",
    'de': "⚠️ Keine archivierte Saison für {year} gefunden.",
}
TRANSLATIONS['legacy.season_label'] = {
    'en': "({year} Season)", 'es': "(Temporada {year})",
    'fr': "(Saison {year})", 'pt': "(Temporada {year})",
    'de': "(Saison {year})",
}
TRANSLATIONS['stats.title'] = {
    'en': "{league} — League Averages{scope}",
    'es': "{league} — Promedios de la Liga{scope}",
    'fr': "{league} — Moyennes de la Ligue{scope}",
    'pt': "{league} — Médias da Liga{scope}",
    'de': "{league} — Liga-Durchschnitte{scope}",
}
TRANSLATIONS['stats.scope_all'] = {
    'en': "  (incl. inactive)", 'es': "  (incl. inactivos)",
    'fr': "  (incl. inactifs)", 'pt': "  (incl. inativos)",
    'de': "  (inkl. inaktiv)",
}
TRANSLATIONS['stats.no_data'] = {
    'en': "No stats found for `{league}`.", 'es': "No se encontraron estadísticas para `{league}`.",
    'fr': "Aucune statistique trouvée pour `{league}`.", 'pt': "Nenhuma estatística encontrada para `{league}`.",
    'de': "Keine Statistiken für `{league}` gefunden.",
}
