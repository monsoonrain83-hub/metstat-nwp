# MetStat NWP — Numerical Weather Prediction

Operational model processing component of MetStat. Scheduled workflows obtain upstream forecasts, generate meteorological products, and publish them to the website through authenticated interfaces. The web frontend and private operational databases are separate. Forecasts are guidance, not official warnings. See existing workflow definitions for actual model availability, cadence and commands; do not run publication workflows against production when developing.

## MetStat project family

MetStat is a multi-repository project with independent release and deployment boundaries. Start with the [website repository](https://github.com/monsoonrain83-hub/metstat-site) for the project overview.

| Repository | Responsibility |
|---|---|
| [metstat-site](https://github.com/monsoonrain83-hub/metstat-site) | Web interface, climate tools, station workflows and server integration |
| [metstat-nwp](https://github.com/monsoonrain83-hub/metstat-nwp) | Numerical weather prediction data ingestion, processing and product publication |
| [LightningLab](https://github.com/monsoonrain83-hub/LightningLab) | Android atmospheric media analysis, lightning detection and photo/video tools; web integration requires a separately verified adapter |

Production databases, credentials, private observations and provider-restricted data are not required to review the source and must not be distributed with it. See [architecture](docs/ARCHITECTURE.md), [security](SECURITY.md) and [contributing](CONTRIBUTING.md). Public source does not imply that third-party data, trained weights or assets are redistributable. No repository may deploy code from untrusted pull requests.

## Development and licensing

Inspect `.github/workflows/` and existing `test_*.py` files for model-specific tests. Run tests on synthetic or licensed fixtures without production credentials. Original project source code is licensed under [GNU GPL v3](LICENSE). Third-party libraries retain their own licenses; upstream weather data, derived products, and other third-party material are subject to their respective terms. See [data and licensing](docs/DATA_AND_LICENSING.md).
