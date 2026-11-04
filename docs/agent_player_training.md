# Training: sechs UI-Players mit Stock-Economy

Main vergibt Run, Client-Ownership und Attack-Windows: **A/B Federation, C/D Klingon, E Romulan, F Borg**. Alle sechs Player-Slots werden durch Agents über die Game-UI geführt; native Opponent-AI bleibt aus. Main startet und beendet Clients. Geplant sind ausschließlich Stock-Lobby-Options: **5000 Dilithium, 5000 Crew, 250 Officers, Standard Tech**, normale endliche Moons. Keine 1m-Fixture oder Infinite Moons.

**Proof-Stand:** Der frühere B-UI-Proof belegt Construction, Defense, Move, Selection und Groups. Mining, Deposit, Research und Special-Casts sind damit **noch nicht praktisch validiert**. Die folgenden Zahlen, Prerequisites und Ability-Pfade sind Source-Facts; jeder Player muss ihre tatsächliche Funktion im neuen Run beobachten.

**Gameplay-Priorität:** Fehlende Detail-Proofs sind keine Anweisung, eine vorhandene Fleet stillstehen zu lassen. Sichtbare Mining-Station, Mining-Beam und beobachtetes positives Income reichen operativ, um Production, Research und Combat fortzusetzen. Cargo-/Deposit-Detail-Proofs nebenbei ergänzen und weiterhin ehrlich als offen führen. Ein erster Skirmish beginnt mit einer einsatzfähigen kleinen Group; Economy und andere Groups während Builds/Travel weiter steuern.

Quellen: [GOG Manual.pdf](../work/install/Manual.pdf), PDF Pages **4, 6-8, 23-25, 37-43, 46**; [Input.map](../work/install/Input.map); Stock-Members aus [assets.zfs](../work/install/assets.zfs), insbesondere `tech1.tt`, `fmining.odf`, `ffreight.odf`, `fbase.odf` und die unten genannten Research-Pods als `.odf`-Members, etwa `assets.zfs::fedpod4.odf`.

## 1. UI-Vertrag und Evidence

Für Race-spezifische Build Orders und Combat-Rollen gilt zusätzlich das [Internet-recherchierte Race Playbook](race_playbook_2026-11-04.md). `UIPlayer.key/chord` verwenden die festen Letter-Positionen aus `Input.map`, unabhängig vom deutschen OS-Layout. Keine manuellen Y/Z-Swaps vornehmen; Yard ist semantisch `ord('Y')`.

Die lokalen Window-Positionen pro Client stehen dauerhaft in `work/game_window_positions.json`. `mp_inst.ps1` stellt sie bei jedem Start wieder her; die Match-Launcher wiederholen den Restore nach dem Render-Init. `python tools/game_window_positions.py save <run> A B C D E F` übernimmt eine neue manuelle Anordnung. Restore verändert weder Size noch Focus/Z-Order und läuft nicht permanent gegen manuelle Window-Bewegungen.

Verwende ausschließlich `tools/ui_player.py`: `UIPlayer(run, tag)` mit `.enable()`, `.move()`, `.click()`, `.drag()`, `.key()`, `.chord()`, `.frame(label)` und `.note(...)`. Frames sind bereits auf **640x480, top-left** normalisiert. Shell-Calls erhalten den Prefix `rtk`.

```python
import sys
sys.path.insert(0, 'tools')
from ui_player import UIPlayer

player = UIPlayer(run, tag)  # beide Werte und Ownership kommen von Main
player.enable()
opening = player.frame('opening')
player.note(goal='first_mining_cycle', runtime_proof='pending')
```

`key/chord` erwarten Windows-VK-Ints: etwa `ord('M')`, Ctrl `0x11`, Shift `0x10`, F1/F2/F4/F5 `0x70/0x71/0x73/0x74`.

Zeige den gespeicherten Frame mit `view_image` an. Arbeite als **Frame ansehen -> HUD/Selection prüfen -> begrenzte UI-Aktion -> neuer Frame**. Nutze sichtbare Actor-/Target-Informationen, keine Actor-IDs für Control. `.command()` ist gesperrt; direkte Build/Attack-IPC, Gameplay-Memory-Writes, AI-Toggles sowie OS-Focus und physischer Mouse/Input sind ausgeschlossen. Bei einem Bridge-Fehler Main informieren und den UI-Bypass unterlassen. Fragen und Blocker gehen ausschließlich an Main.

`.frame()` und `.note()` schreiben nach `work/det/<run>/<tag>_ui/` bzw. `<tag>_ui_events.jsonl`. Notiere Ziel, tatsächlich beobachtete Änderung und zugehörige Frames. Ein Device-Poll-ACK oder eine ausgeführte Click-Sequence ist kein Gameplay-Proof.

## 2. Opening: Income vor großer Produktion

1. **World prüfen und Moon erkunden.** Main muss sechs deklarierte Human-Slots ohne native AI und Standard Tech bestätigen. Opening-Frame mit Resource-HUD sichern. Scout selektieren, einen sichtbaren Ground Point anfahren und einen Dilithium Moon über die UI identifizieren. Fertig, wenn Position und Resource-Anzeige des Moons sichtbar sind.
2. **Mining Station bauen.** Constructor selektieren, Build Menu öffnen (`B`, dann Mining Station `D`; Menu/HUD kontrollieren). Einen grünen Ghost nahe dem Moon platzieren. Rote Ghosts verlangen eine andere freie Site; Buildings, Units und Nebula-Blocking beachten. Resource-Abzug, Construction-Fortschritt und fertige Station beobachten. Ein grüner Ghost allein genügt nicht als Completion.
3. **Den ersten vollständigen Mining-Cycle verfolgen.** Die Station bringt einen Freighter mit. Beobachte **Moon -> Full Cargo -> Station -> Deposit -> Dilithium-Income**. Für den Income-Proof kurz keine Dilithium-Ausgaben auslösen: Frame mit Cargo/Resource-HUD vor dem Deposit und Frame mit leerem Cargo sowie gestiegenem Dilithium danach sichern. Fertig erst bei beobachtetem Deposit und positivem Income, nicht bereits bei einem Mining-Order.
4. **Economy sinnvoll ausbauen.** Die [Armada-1-Economy-Referenz](https://www.mobile-infanterie.de/wiki/doku.php?id=en:games:star_trek_armada_1:economy) empfiehlt typischerweise **drei Freighters pro Moon**, inklusive des einen mitgelieferten Freighters. Diese Baseline anhand der Mining-/Travel-/Deposit-Cycles prüfen. Falls kein Loop startet: Freighter selektieren, Harvest `D` + sichtbaren Moon über die UI setzen. Pro Moon kann nur **ein** Freighter gleichzeitig minen; weitere wechseln Mining, Travel und Deposit. Zusätzliche Freighters ohne beobachteten Nutzen verbrauchen Budget. Moon-Capacity verfolgen und bei Bedarf einen weiteren erkundeten Moon erschließen.
5. **Tech und Defense aus Income finanzieren.** Shipyard, Research und eine begründete lokale Defense bauen; genug Resources für Ersatz und Expansion behalten. Federation: Research für **1300 Dilithium** schaltet in normalem `tech1.tt` Akira/Steamrunner frei; **Shipyard + Research -> Advanced Yard**. Für andere Races die jeweiligen Stock-Prerequisites im HUD prüfen. **Full Tech überspringt auch Special-Research** und eignet sich deshalb nicht für dieses Training.

Stock-Economy-Referenz; die genannten `f*`-Members beschreiben Federation, andere Races anhand ihrer Pendants und des HUD prüfen:

| Mechanik | Source-Fact / auszuführender Check |
|---|---|
| Mining Station (`fmining`) | 1000 Dilithium, 250 Crew, 4 Officers; Build-Zeit 50 s; ein Freighter inklusive. |
| Zusätzlicher Freighter (`ffreight`) | 400 Dilithium; Starbase selektieren, `B,F`; `tech1.tt` verlangt `fbase + fmining`. Construction und anschließenden Mining-Cycle prüfen. |
| Crew | Starbase: 3,5 Crew/s; wirksamer Planet-Modifier 1,25. Crew-HUD über Zeit prüfen, statt einen großen Start-Pool als Crew-Economy zu behandeln. |
| Officer-Capacity | `fbase` liefert +20; Officer Quarters jeweils +20, maximal sechs Upgrades pro Base. Capacity im HUD verfolgen; den Lobby-Wert nicht als bewiesenen harten Game-Cap darstellen. |

## 3. Fleet-Control, Attack und Recovery

Prüfe vor jedem Shortcut den selektierten Actor und das Menu. Derselbe Key hat je nach Kontext andere Funktionen: `B,A` auf Research ist kein Constructor-Build-Order.

| Aktion | UI-Pfad und Proof |
|---|---|
| Selection | Click/Drag, `E` oder `N` nutzen; HUD prüfen. Praktisch wurden bis zu acht Selection-Icons beobachtet. Mehrere Groups für größere Fleets anlegen. |
| Groups / Camera | `Ctrl+Digit` speichert, `Digit` ruft ab. Zweimal `Digit` zentriert die Camera praktisch belegt; `Shift+Digit` ist der Manual-Pfad zum Recenter. Minimap-Clicks und NumpadMinus-Taps halfen im bisherigen UI-Proof. |
| Move / Attack / Stop | `M` + sichtbarer Ground Point; `A` + Enemy-Target; `S` stoppt. Normaler Rightclick wurde für Move und sichtbare Enemy-Targets eingesetzt. Target, tatsächliche Bewegung und Combat/Damage mit Frames beobachten. |
| Guard / Rally | Source-Pfad: `U` + Friendly-Target; diesen Target-Flow erst visuell validieren. Der frühere U+Base-Click bewies ihn nicht. Bei selektiertem Yard ist `P` der Rally-Pfad; den Weg neu produzierter Ships zum gewählten Punkt beobachten. |
| Alerts / Retreat | `Shift+G/Y/R` setzt Green/Yellow/Red Alert für Idle-Verhalten. Bedrohte Miners oder Ships explizit selektieren und mit Move zu einem sicheren sichtbaren Point zurückziehen; ein Alert ersetzt keinen Retreat-Order. |
| Repair / Recrew | Beschädigtes Ship selektieren, `R`: zum nächsten Friendly-Yard zurückkehren lassen. Ankunft, gestiegene Health und Crew prüfen. Das ist ein neuer Runtime-Check, kein aus dem früheren Proof übernommener Erfolg. |

Pro Player eine kleine Fleet tatsächlich erkunden und bewegen, im von Main koordinierten Skirmish ein sichtbares Enemy-Ship gezielt angreifen, einen bedrohten Actor zurückziehen und Repair/Recrew eines beschädigten Ships beobachten. Groups bis acht Ships getrennt führen, damit größere Bestände kontrollierbar bleiben. Combat-Frames müssen Target und Reaktion zeigen; fremde Economy nicht ohne Main-Abstimmung zerstören.

## 4. Special-Abilities: Research -> Cast -> sichtbarer Effect

Research-Pfade gelten bei **selektierter passender Research Station**. `B,<Key>` öffnet deren Build Menu und wählt den Pod; Fertigstellung zuerst im HUD prüfen. Ship selektieren, ausreichende Energy und aktiven Ability-Button prüfen, dann den Cast ausführen. `F1/F2/F4/F5` sind die normalen Special-Keys aus `Input.map`, ohne Ctrl/Alt.

| Slot / Ship | Stock-Prerequisite | Cast und Target |
|---|---|---|
| A: Federation Defiant | Research `B,A` -> `fedpod4` (Antimatter Mines) | `F1`, **kein Target**, 500 Energy. Mine/Effect nach dem Cast sichtbar prüfen. |
| B: Federation Akira | Research `B,C` -> `fedpod2` (Chain Reaction Pulsar) | `F2`, **kein Target**, 800 Energy; in einem passenden Combat-Fenster den Effect beobachten. |
| C: Klingon Bird of Prey | Research `B,M` -> `klipod4` (Gravity Mine) | `F1`, **kein Target**, 400 Energy; platzierte Mine/Effect prüfen. |
| D: Klingon Vorcha | Research `B,P` -> `klipod2` (Polaron Torpedo) | `F2`, dann sichtbares **Enemy-Target**, 800 Energy; Projectile/Target-State prüfen. |
| E: cloakfähiges Romulan Ship | Kein Pod für normales Cloak | `C` oder `F5`, 100 Energy; Cloak-Status und sichtbare Änderung prüfen. |
| E, Capital-Ausbau: Warbird | **Advanced Yard zuerst**, Warbird bauen und `rompod1` (Shield Inversion) erforschen; Research-Key `B,I` laut `Input.map` | `F4`, **Enemy-Target**. Energy-Anforderung im HUD prüfen; Effect und Shield-/Target-State beobachten. |
| F: Borg Interceptor | Research `B,W` -> `borpod4` (Transwarp) | `F1`, dann ein **aktuell sichtbarer Ground Point**, 1000 Energy. Neue Position nach dem Jump mit Camera/Recenter prüfen. |
| F, Ausbau: Borg Sphere | Research `B,R` -> `borpod3` (Regeneration) | `F2`, **Self**, kein fremdes Target; Energy im HUD prüfen. An einer beschädigten Sphere die tatsächliche Shield-/System-Recovery beobachten; Hull-Heilung nicht ungeprüft voraussetzen. |

Für einen No-Target-Cast keinen beliebigen Ground-Click nachschieben. Für Target-Casts nach dem Special-Key auf den gültigen sichtbaren Enemy bzw. Ground Point klicken; die Ship-Selection davor beibehalten. Weitere F4-Capital-Pods erst nach ihrem Advanced-Yard-Prerequisite planen; einen Shortcut allein nicht als Unlock behandeln.

**Cast-Proof pro Player:** Vorher-Frame mit Ship, fertigem Research/Ability, Energy und gegebenenfalls Target; Cast; unmittelbar danach und nach kurzer Effect-Zeit weitere Frames. Energy-Verbrauch, Ability-/Cooldown-State sowie sichtbaren Effect bzw. Target-State gemeinsam bewerten. Ein deaktivierter Button, Click oder Source-Eintrag allein belegt keinen Cast. Mines brauchen einen beobachteten Mine/Effect, Transwarp einen Positionswechsel, Regeneration eine tatsächliche Heilung. Unklare Resultate als offen protokollieren.

## 5. Acceptance und Übergang ins Late Game

Jeder der sechs Player braucht einen eigenen, mit Frames belegten Ledger:

- [ ] Fertige Mining Station; Freighter beim Mining, mit Full Cargo und beim Deposit beobachtet; positives Dilithium-Income isoliert belegt.
- [ ] Sinnvoller Economy-/Tech-Ausbau aus laufendem Income; Crew, Officers und Moon-Capacity kontrolliert; Standard-Tech-Prerequisites eingehalten.
- [ ] Fleet-Exploration und gezielter Move sowie ein tatsächlicher Attack auf ein sichtbares Enemy-Target.
- [ ] Expliziter Retreat eines bedrohten Actors und beobachteter Repair-/Recrew-Cycle.
- [ ] Mindestens ein zur Slot-Role passender, tatsächlich beobachteter Special-Cast mit Before/After-Proof. Weitere freigeschaltete Abilities im Match einsetzen.
- [ ] Offene Mechanics und fehlende Runtime-Proofs klar an Main gemeldet; keine Source-Aussage als praktischen Erfolg ausgegeben.

Main koordiniert größere Fleets und mehrere gleichzeitige Fronten, während verbleibende individuelle Proofs weiter gesammelt werden. Die Acceptance-Checklist bleibt erforderlich für den vollständigen Training-Nachweis, blockiert aber keine sinnvollen Gameplay-Orders. Economy weiter betreiben: Income reinvestieren, Moons/Travel-Routen sichern, Verluste ersetzen, Ships zwischen Front und Repair rotieren und Specials gezielt einsetzen. Late-Game-Training verlangt beobachtete Entscheidungen auf diesen Fronten; reine Queue-Refills erfüllen es nicht.
