# DayLog iOS

Minimale SwiftUI-app: een toggle, een uploadbuffer en een link naar de webview.

## Bouwen

```bash
brew install xcodegen
make ios                  # genereert ios/DayLog.xcodeproj uit project.yml
open ios/DayLog.xcodeproj
```

1. Zet in Xcode bij *Signing & Capabilities* je team (betaald developer-account, anders
   verloopt de app na 7 dagen).
2. Kies je iPhone als target en run.
3. Vul in de app de Tailscale-URL van je Mac en het API-token uit `.env` in.
4. Sta microfoon en locatie ("Altijd") toe.

## Hoe het werkt

| Bestand | Rol |
|---|---|
| `Recorder.swift` | AVAudioEngine-tap → `ChunkWriter`, AAC 32 kbps, chunks van 5 min; herstart na telefoongesprek of route-wissel |
| `ChunkStore.swift` | buffer in Application Support: `.partial` tijdens opname, `.m4a` + JSON-sidecar als klaar |
| `Uploader.swift` | background `URLSession`, alleen wifi, metadata in headers, lokaal verwijderen bij 2xx |
| `LocationTracker.swift` | significant location changes (grof en zuinig) |

## Bekende beperkingen

- iOS toont tijdens opnemen de oranje microfoonstip; dat hoort zo.
- Na een force-quit (omhoog vegen) stopt de opname tot je de app weer opent.
- Na een telefoongesprek probeert de app te hervatten; iOS staat dat niet altijd toe
  vanuit de achtergrond. Check de toggle-status als je twijfelt.
- Het token staat in UserDefaults, niet in de Keychain. Prima voor een privé-app op je eigen
  telefoon, maar een kandidaat voor later.
- Deze code is op Linux geschreven en nog niet in Xcode gecompileerd: reken op een paar kleine fixes.
