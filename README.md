# Docker Projekt: Prozess-Monitoring mit Prometheus + Grafana (Jetson AGX Orin)

Dieses Projekt zeigt dir ein komplettes, aber einfaches Docker-Setup, um einen Prozess zu beobachten und die Metriken im Browser zu visualisieren.

Du bekommst dabei drei Dinge gleichzeitig:

1. Eine lauffaehige Monitoring-Umgebung mit Docker Compose.
2. Ein verstaendliches Beispiel fuer Docker-Grundlagen.
3. Ein Setup, das auf ARM64 (Jetson AGX Orin) ausgelegt ist.

## Zielbild

Der Stack besteht aus drei Containern:

- `process-exporter` (eigene Python-App): liest Prozessdaten aus `/proc` und stellt Prometheus-Metriken bereit.
- `prometheus`: sammelt Metriken vom Exporter.
- `grafana`: zeigt die Metriken als Dashboard im Browser.

Datenfluss:

- Exporter stellt Metriken auf `:8000/metrics` bereit.
- Prometheus scraped `process-exporter:8000`.
- Grafana liest aus Prometheus (`http://prometheus:9090`).

## Projektstruktur

```text
.
├── docker-compose.yml
├── .env.example
├── exporter/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── process_exporter.py
├── prometheus/
│   └── prometheus.yml
├── grafana/
│   ├── dashboards/
│   │   └── process-observer.json
│   └── provisioning/
│       ├── dashboards/
│       │   └── dashboards.yml
│       └── datasources/
│           └── datasource.yml
└── demo/
    ├── python_demo.py
    └── cpp_demo.cpp
```

## Docker Grundlagen (kurz und praktisch)

### Was ist ein Image?

Ein Image ist eine unveraenderliche Vorlage (Template) fuer einen Container.

Beispiel hier:

- Das Exporter-Image wird aus `exporter/Dockerfile` gebaut.

### Was ist ein Container?

Ein Container ist eine laufende Instanz eines Images.

Beispiel hier:

- Der laufende Container `process-exporter` ist eine Instanz des Exporter-Images.

### Was macht Docker Compose?

Compose startet mehrere Container als zusammengehoeriges System.

In diesem Projekt:

- Ein Befehl startet Exporter, Prometheus und Grafana zusammen.
- Netzwerk, Ports und Volumes sind zentral in `docker-compose.yml` definiert.

### Was ist ein Volume?

Volumes sind persistente Datenbereiche ausserhalb der Container-Lebenszeit.

Hier:

- `prometheus-data` speichert Prometheus-Zeitreihen.
- `grafana-data` speichert Grafana-Zustand.

## Voraussetzungen

- Docker Engine mit Compose Plugin
- Linux (x86_64 oder ARM64)
- Fuer Jetson: Docker laeuft auf dem Geraet (JetPack-Umgebung)

Pruefen:

```bash
docker --version
docker compose version
```

## Schnellstart (interaktiv)

### 1) Stack starten

```bash
docker compose up --build
```

Der Exporter fragt beim Start im Terminal:

- nach PID
- oder exaktem Prozessnamen
- oder Namensmuster

Wichtig:

- Interaktive Eingabe funktioniert nur mit TTY.
- In diesem Compose ist `stdin_open: true` und `tty: true` bereits gesetzt.

### 2) Web UIs oeffnen

- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090
- Exporter Metrics: http://localhost:8000/metrics

Grafana Login:

- User: `admin`
- Passwort: `admin`

Dashboard `Observed Process Overview` wird automatisch provisioniert.

## Nicht-interaktiv starten (empfohlen fuer Automatisierung)

Setze in `docker-compose.yml` eine der folgenden Variablen im `process-exporter` Service:

- `PROCESS_PID=1234`
- `PROCESS_NAME=python3`
- `PROCESS_PATTERN=python*`

Dann kannst du `INTERACTIVE_SELECT=false` setzen.

Beispiel:

```yaml
environment:
  - PROC_ROOT=/host_proc
  - PROCESS_NAME=python3
  - INTERACTIVE_SELECT=false
```

## Demo-Prozess starten

### Python Demo

In einem zweiten Terminal:

```bash
python3 demo/python_demo.py
```

Dann im Exporter als Prozessname `python3` waehlen.

### C++ Demo

```bash
g++ -O2 -std=c++17 demo/cpp_demo.cpp -o demo/cpp_demo
./demo/cpp_demo
```

Dann im Exporter Prozessname `cpp_demo` waehlen.

## Jetson AGX Orin Hinweise

### Architektur

Jetson AGX Orin ist ARM64 (`linux/arm64`).

Dieses Projekt nutzt:

- `python:3.11-slim` (multi-arch)
- `prom/prometheus` (multi-arch)
- `grafana/grafana` (multi-arch)

Damit ist das Setup auf Jetson in der Regel direkt lauffaehig.

### Wichtige Laufzeitpunkte auf Jetson

- Der Exporter liest Host-Prozesse via:
  - `pid: host`
  - Mount `/proc:/host_proc:ro`
- Manche `/proc/<pid>/io` Felder koennen je nach Rechten fehlen.
  - Das ist im Code abgefangen.

### Start auf Jetson

```bash
docker compose up --build
```

Wenn du explizit ARM64 bauen willst (z. B. von x86_64 aus):

```bash
docker buildx build --platform linux/arm64 -t process-exporter:arm64 ./exporter
```

## Debugging und Verstehen

### Logs ansehen

```bash
docker compose logs -f process-exporter
docker compose logs -f prometheus
docker compose logs -f grafana
```

### Laufende Container

```bash
docker compose ps
```

### In einen Container schauen

```bash
docker compose exec process-exporter sh
```

### Prometheus Targets pruefen

Im Browser:

- http://localhost:9090/targets

`process-exporter` sollte `UP` sein.

## Wichtige Metriken

- `observed_process_up`
- `observed_process_pid`
- `observed_process_cpu_percent`
- `observed_process_rss_bytes`
- `observed_process_vsz_bytes`
- `observed_process_threads`
- `observed_process_uptime_seconds`
- `observed_process_read_bytes_total`
- `observed_process_write_bytes_total`

## Stoppen und Aufraeumen

Stack stoppen:

```bash
docker compose down
```

Mit Volume-Loeschung:

```bash
docker compose down -v
```

## Wie es intern funktioniert

1. Exporter waehlt beim Start einen Prozess (PID/Name/Muster).
2. Exporter liest periodisch aus `/host_proc/<pid>/...`.
3. Exporter rechnet Rohwerte in Prometheus-Metriken um.
4. Prometheus scraped alle 2 Sekunden.
5. Grafana visualisiert die Zeitreihen.

Wenn der Prozess endet, setzt der Exporter `observed_process_up=0`.

## Naechste sinnvolle Erweiterungen

- Prozesswechsel zur Laufzeit ohne Containerneustart
- Mehrere Prozesse gleichzeitig beobachten (Labels)
- Alerting in Prometheus/Grafana (z. B. CPU > 90% fuer 5 min)
- NVIDIA/GPU-Metriken fuer Jetson ergaenzen
