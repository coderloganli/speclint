# tidewatch

[![CI](https://img.shields.io/badge/ci-passing-brightgreen)](#)
[![PyPI](https://img.shields.io/badge/pypi-v0.9.2-blue)](#)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](#)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

**tidewatch** is a small command-line tool that polls tide-gauge sensors, checks
readings against thresholds you define, and sends alerts when water levels
cross them. It is designed to run unattended on a Raspberry Pi in a harbour
shed as comfortably as on a server in a data centre.

- Polls sensors over HTTP, Modbus TCP, or serial (NMEA-style line protocols)
- Threshold, rate-of-change, and stale-data rules
- Alerts via email, webhook, Slack-compatible webhooks, or a shell command
- Alert deduplication and quiet hours so nobody gets paged forty times a night
- Writes readings to CSV or SQLite for later analysis

> **Status:** tidewatch is pre-1.0. The configuration format is stable, but
> the plugin API may still change between minor releases.

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Installation

tidewatch requires Python 3.10 or newer.

```bash
pip install tidewatch
```

Serial and Modbus support are optional extras:

```bash
pip install "tidewatch[serial,modbus]"
```

To install from source:

```bash
git clone https://github.com/tidewatch/tidewatch.git
cd tidewatch
pip install -e ".[dev]"
```

Verify the install:

```console
$ tidewatch --version
tidewatch 0.9.2
```

## Quick start

1. Generate a starter configuration:

   ```bash
   tidewatch init --output tidewatch.toml
   ```

2. Edit `tidewatch.toml` and point the example sensor at your gauge's URL.

3. Check that tidewatch can reach the sensor:

   ```console
   $ tidewatch probe harbour-north
   harbour-north  OK  level=2.41 m  received 2026-10-08T06:12:04Z  (143 ms)
   ```

4. Start monitoring:

   ```bash
   tidewatch run --config tidewatch.toml
   ```

tidewatch logs each poll to stderr and sends an alert the first time a rule
fires. Press `Ctrl+C` to stop.

## Configuration

tidewatch reads a single TOML file. By default it looks in `./tidewatch.toml`,
then `$XDG_CONFIG_HOME/tidewatch/config.toml`. Pass `--config` to override.

A minimal but complete example:

```toml
[general]
poll_interval = "60s"
timezone = "Europe/Lisbon"
storage = "sqlite:///var/lib/tidewatch/readings.db"

[[sensors]]
id = "harbour-north"
transport = "http"
url = "http://10.0.4.21/api/level"
value_path = "$.level_m"     # JSONPath into the response body
datum_offset = -0.35         # metres, applied before rules are evaluated

[[rules]]
sensor = "harbour-north"
kind = "threshold"
above = 3.20
severity = "warning"

[[rules]]
sensor = "harbour-north"
kind = "rate"
rise_per_hour = 0.50
severity = "critical"

[[rules]]
sensor = "harbour-north"
kind = "stale"
after = "10m"
severity = "warning"

[alerts.email]
smtp_host = "smtp.example.org"
smtp_port = 587
from = "tidewatch@example.org"
to = ["harbourmaster@example.org"]
password_env = "TIDEWATCH_SMTP_PASSWORD"

[alerts.dedup]
window = "30m"
quiet_hours = "23:00-06:00"   # warnings are held; criticals always go out
```

### Key options

| Key | Default | Description |
| --- | --- | --- |
| `general.poll_interval` | `"60s"` | How often each sensor is polled. Accepts `s`, `m`, `h` suffixes. |
| `general.storage` | none | `csv:///path/dir` or `sqlite:///path/file.db`. Omit to disable storage. |
| `sensors[].transport` | required | One of `http`, `modbus`, `serial`. |
| `sensors[].datum_offset` | `0.0` | Offset in metres added to every raw reading. |
| `rules[].kind` | required | One of `threshold`, `rate`, `stale`. |
| `rules[].severity` | `"warning"` | `info`, `warning`, or `critical`. |
| `alerts.dedup.window` | `"15m"` | Identical alerts within this window are suppressed. |

Secrets should never be written into the config file. Any key ending in `_env`
names an environment variable to read the value from.

Run `tidewatch config check` to validate a file without starting the monitor.

## Usage

```text
tidewatch [--config PATH] [--log-level LEVEL] COMMAND [ARGS]

Commands:
  init           Write a starter configuration file
  probe SENSOR   Poll one sensor once and print the reading
  run            Start the monitoring loop
  config check   Validate the configuration file
  alerts test    Send a test alert through every configured channel
  history        Print stored readings
```

Poll every sensor once and exit (useful in cron or CI):

```bash
tidewatch run --once
```

Send a test alert to confirm your email and webhook settings:

```bash
tidewatch alerts test --severity critical
```

Export the last 24 hours of readings as CSV:

```bash
tidewatch history harbour-north --since 24h --format csv > harbour-north.csv
```

Run as a systemd service:

```ini
# /etc/systemd/system/tidewatch.service
[Unit]
Description=tidewatch tide-gauge monitor
After=network-online.target

[Service]
ExecStart=/usr/local/bin/tidewatch run --config /etc/tidewatch/config.toml
EnvironmentFile=/etc/tidewatch/secrets.env
Restart=on-failure
User=tidewatch

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl enable --now tidewatch`.

## Troubleshooting

**`probe` reports `timeout` for an HTTP sensor.**
Confirm the gauge is reachable from the host with `curl <url>`. Many field
loggers only answer on a management VLAN. You can raise the per-request
timeout with `sensors[].timeout = "10s"`.

**Readings look offset by a constant amount.**
Your gauge probably reports against a different vertical datum than you
expect. Set `datum_offset` on the sensor rather than adjusting every rule.

**Serial sensor fails with `Permission denied: /dev/ttyUSB0`.**
Add the service user to the `dialout` group (`sudo usermod -aG dialout
tidewatch`) and restart the service.

**No alerts arrive, but the log shows rules firing.**
Run `tidewatch alerts test` and check the output for each channel. Also check
whether the alert falls inside `quiet_hours` or the dedup window.

**Too many alerts during a storm surge.**
Increase `alerts.dedup.window`, or add a `hysteresis` value to threshold rules
so a level must fall back below `above - hysteresis` before re-arming.

If you are still stuck, run with `--log-level debug` and open an issue with the
relevant log lines (remove any credentials first).

## Contributing

Contributions are welcome — bug reports, documentation fixes, new transports,
and new alert channels alike.

1. Fork the repository and create a branch from `main`.
2. Install development dependencies: `pip install -e ".[dev]"`.
3. Install the pre-commit hooks: `pre-commit install`.
4. Make your change and add tests under `tests/`.
5. Run the checks:

   ```bash
   pytest
   ruff check .
   mypy src/tidewatch
   ```

6. Open a pull request describing what changed and why.

For larger changes, such as a new transport, please open an issue first so we
can agree on the design. See [CONTRIBUTING.md](CONTRIBUTING.md) for the code
style guide and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community
expectations.

## License

tidewatch is released under the [Apache License 2.0](LICENSE).
