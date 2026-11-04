# Armada 1: Race Playbook für sechs UI-Players

Internet-Recherche vom 2026-11-04 für **Armada 1, Stock/GOG, Standard Tech**, Run `agents6_2`. Die folgenden Build Orders sind unser aus den Quellen abgeleiteter Match-Plan, keine behauptete universelle Tournament-Meta. Vorhandene Buildings behalten und am nächsten fehlenden Schritt fortsetzen. UI-Proofs stehen separat im [Training](agent_player_training.md).

## Quellen und Einordnung

- [Archivierte offizielle Strategy-Tipps, QA-Team](https://gaming.trekcore.com/armada/strategy.html): Scout als separate Guard-Escort für Artillery; mobile und räumlich verteilte Basis. Primary Source, von TrekCore als Kopie der offiziellen Website gekennzeichnet.
- [Billy Lee: Armada 1 Guide, General/Federation/Klingon/Romulan/Borg Tactics](https://gamefaqs.gamespot.com/pc/250551-star-trek-armada/faqs/27107): zeitgenössische Spieler-Erfahrung, darunter Focus Fire, unterschiedliche Fleet-Rollen und Special-Einsatz. Campaign-Hero-Werte gelten nicht für unsere Multiplayer-Ships. Hinweise auf Glitches sind unbestätigte Follow-ups.
- [Armada-1-Economy](https://www.mobile-infanterie.de/wiki/doku.php?id=en:games:star_trek_armada_1:economy) und [Factions](https://www.mobile-infanterie.de/wiki/doku.php?id=en:games:star_trek_armada_1:factions): Community-Referenz für Mining-Auslastung, Crew-Bottlenecks und Unit-Rollen. Keine unabhängige Runtime-Validierung unserer Partie.
- Lokale Primary Sources: GOG `Input.map`, `Manual.pdf`, `assets.zfs`/`tech1.tt`, siehe [Training](agent_player_training.md). Costs, Unlocks und Ability-Keys dort gegen Stock geprüft. Keine Fleet-Operations-/Armada-2-Regeln übernehmen.

## Gemeinsame Opening und Prioritäten

1. Constructor 1 baut Mining am **identifizierten** Dilithium Moon; Constructor 2 baut den Tier-1-Yard auf freier, erreichbarer Site. Scout erkundet sichere Wege und den nächsten Moon. Nicht auf das Ende eines Builds warten, solange ein anderer Actor sinnvoll steuerbar ist.
2. Mining Station fertig: Sie bringt einen Freighter. Zwei weitere Freighters aus der Starbase ergeben die von der Economy-Referenz empfohlene **Baseline von drei pro Moon**. Das ist ein Startwert: tatsächliche Mining-/Travel-/Deposit-Cycles beobachten, nicht weitere Freighters an eine volle Waiting Queue hängen. Ein einzelner gleichzeitig minender Freighter bedeutet nicht, dass nur ein Freighter pro Moon nützlich ist.
3. Mining und Yard in Betrieb: kleine erste Combat-Group bauen, parallel Tier-1-Research und die erste relevante Special erforschen. Nicht die ganze Opening in Turrets oder einen frühen Capital-Tech-Rush investieren. Einen erkundeten zweiten Moon erschließen, wenn das Budget die nächste benötigte Production/Research nicht blockiert.
4. Feste Control Groups: z. B. 1 Combat, 2 Scout, 3 Support/Special, 4 Constructor, 5 Yard. Freie Nummern wählen, vorhandene Groups nicht unbemerkt überschreiben. Scout nicht blind mit schnellen Attack-Orders in den Gegner schicken.
5. Pro Rückkehr zur Basis HUD auf Dilithium/Crew/Officers prüfen; fehlendes Income vor mehr Yards beheben. Yard ohne bezahlbare Queue oder fertige Fleet ohne Auftrag ist ein konkreter nächster Arbeitsauftrag. Eine zweite Production nur finanzieren, wenn sie auch dauerhaft versorgt werden kann.

## Federation: A und B

**Plan:** Mining + Shipyard → erste Defiants → Research Facility und Special → Akiras; danach bei laufender Economy Advanced Yard und Sovereigns. Für Nebula-Support zusätzlich **Science Station und die benötigten Research-Pods** einplanen; Advanced Yard allein produziert nur das Ship. A führt zunächst mobile Defiants mit Mines, B Akiras mit Pulsar. Nicht beide Slots bei reinem Defiant-Queue-Refill belassen. [Offizieller Federation-Eintrag](https://gaming.trekcore.com/armada/ships-federation.html).

**Combat:** Eine kleine Front-Group aktiv führen und Focus Fire auf einen sichtbaren Gegner setzen. Beschädigte Ships rechtzeitig zum Yard schicken und nach Repair zurückholen. Steamrunners mit Abstand, Combat-Escort und Sichtunterstützung nutzen; der offizielle QA-Tipp ist ein separat gesteuerter Scout mit Guard auf die Artillery. Scout-Guard ersetzt keine Combat-Escort. Artillery gegen nahe Gegner kann die eigene Fleet treffen. Nebula später separat gruppieren, damit erforschte Support-Specials zugänglich bleiben. Standard Sovereigns nicht mit Campaign-Enterprise-Werten kalkulieren. [Offizielle QA-Tipps](https://gaming.trekcore.com/armada/strategy.html).

**Special-Ziel:** A erforscht Antimatter Mines, platziert sie auf einem tatsächlich genutzten Approach und beobachtet Mine/Energy. B setzt Chain Reaction Pulsar gegen eine sichtbare, **nicht cloaked** Enemy-Group ein; die archivierten 1.2-Notes schließen cloaked Targets aus. Corbomite-aktive Sovereigns sind ein Grund, reflektierbare Specials zurückzuhalten. [1.2-Patch-Notes](https://gaming.trekcore.com/armada/faq.html).

## Klingon: C und D

**Plan:** Mining + Shipyard → Birds of Prey für frühe Bewegung und Druck → Weapons Center → C Gravity Mines, D Polaron/Vor'cha → später Imperial Yard und Negh'Vars. Frühe kleine Groups tatsächlich einsetzen, während Tech entsteht.

**Combat:** BoP als mobile Attack-Group: anfliegen, decloaken, gemeinsam feuern, beschädigte Ships zurückziehen. Vor'cha-Specials überlegt staffeln; der zeitgenössische Guide empfiehlt Polaron nicht gleichzeitig mit allen Ships auf dasselbe System zu verschwenden. Negh'Var-Specials auf sinnvolle Targets verteilen. Kein Ion-Cannon-Cast auf einen aktiv reflektierenden Sovereign.

**Special-Ziel:** C legt Gravity Mines auf einen sichtbaren Kampf-/Retreat-Weg, D setzt Polaron auf ein sichtbares Enemy-Ship ein und prüft den Target-State. Niedrige Crew ist keine allgemeine Unverwundbarkeit: beschädigte Klingon Ships brauchen weiterhin Repair/Recrew.

## Romulan: E

**Plan:** Mining + Shipyard → Shrikes und Talon-Scouting → Covert Ops, dann passende Special → Griffins oder geschützte Raptors nach Situation → Advanced Yard, Warbirds und Shield Inversion. Cloak dient einem geplanten Approach/Retreat, nicht ziellosem Kreisen.

**Combat:** Talon sammelt Information, Attack-Group greift ein bekanntes Ziel an und zieht sich geordnet zurück. Raptors separat mit Schutz und Sicht führen. Warbirds gegen ein sichtbares Ziel zusammenführen; Shield Inversion gezielt einsetzen. Ein Shrike mit erforschtem Spy ist später eine Option für Intelligence. Keine Crew-intensiven Boarding-Versuche ohne konkreten Vorteil.

**Special-Ziel:** Sofort normaler Cloak/Decloak mit State-/Energy-Proof; später Shield Inversion mit vorher angeschlagenen eigenen Shields und sichtbarer Target-/Shield-Änderung. Angeschlagene eigene Shields sind ein sinnvoller Nutzungs-/Proof-Fall, kein belegtes Cast-Prerequisite. Cloak nimmt Shields herunter; vor dem offenen Fight decloaken und nicht im feindlichen Fire als universellen Escape behandeln. Laut Firsthand-Guide regenerieren Shields/Energy während Cloak nicht: einen sicheren Decloak-/Repair-Point einplanen. [Firsthand Guide, §065](https://gamefaqs.gamespot.com/pc/250551-star-trek-armada/faqs/27107).

## Borg: F

**Plan:** Mining + Assembly Matrix → Interceptors und Detector für aktive Exploration → Modification Center + Transwarp → Spheres und Regeneration; Advanced Matrix/Cubes erst mit passender Economy. Bei Crew-Bottleneck einen weiteren Nexus priorisieren, statt noch mehr Yards ohne Crew zu bauen.

**Combat:** Interceptors sind mobile Raid-/Recovery-Units, keine Cube-Ersatz-Tanks. Transwarp braucht einen gültigen Point mit **aktueller eigener/allied Line of Sight**, nicht nur früher erkundeten Fog. Spheres für den Frontkampf nutzen; Regeneration am beschädigten Ship aktivieren und Recovery beobachten. Cubes später mit Crew-Reserve führen; Assimilation kostet auch eigene Crew. Nach einem Capture Officers und Crew erneut prüfen. [Manual, PDF Pages 22–23](../work/gog_repaired/Manual.pdf).

**Special-Ziel:** Ein tatsächlicher Transwarp mit neuer Position und Energy-Abzug, dann beobachtete Regeneration. Holding Beam erst mit Research, geeignetem Target und ausreichender Crew einsetzen.

## Gegen langsame und zufällige UI-Aktionen

Der nächste Auftrag folgt dem ersten offenen Engpass: **akute Gefahr → Income → blockierte Production/Officers/Crew → Research → Fleet-Manöver/Special → Expansion**. Jeder Click verfolgt einen dieser Zwecke. Nach zwei erfolglosen Placement-Versuchen Selection, Menu und Footprint erneut identifizieren; nicht dieselbe zufällige Clickfolge wiederholen. Während Cargo-/Build-Timern andere Units führen. Kohärente UI-Aktionen in einem Tool-Call bündeln, danach das Ergebnis prüfen.

**Input-Korrektur:** `UIPlayer.key/chord` übersetzen jetzt die festen `Input.map`-Letter-Positionen gegen das Keyboard-Layout des Game-Window-Threads. Semantisches `ord('Y')` ist wieder der Yard-Key. Alle manuellen Y/Z-Swaps entfernen; neu importieren. Kein OS-Layout, Focus oder Desktop-Input wird verändert.

Erster Skirmish beginnt mit einer einsatzfähigen kleinen Group; nicht auf volle Capital-Fleets oder vollständige Cargo-Tooltip-Proofs warten. Positive Income- und Construction-Beobachtungen ermöglichen operativ weitere Orders, während fehlende Detail-Proofs offen bleiben. Im initialen Training die sechs Starting Economies erhalten. Danach größere Fleets, mehrere Fronten, Loss-Replacement und Specials fortsetzen. Dauer, Player-Fleet-Größe und simultane Kämpfe sind separate Late-Game-Gates; mehr Clicks allein ist kein bestandener Desync-Test.
